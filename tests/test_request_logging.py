"""Exercise the HTTP error boundary without real users or provider traffic."""
import io
import json
import logging
import tempfile
import threading
import sys
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.observability import RedactingFormatter, configure_logging, log_unhandled_exception, log_unhandled_thread
from backend.server import GenerationReconciler, HandrawHTTPServer, HandrawRequestHandler
from backend.services import ServiceError


class ProbeHandler(HandrawRequestHandler):
    def _enforce_token_scope(self):
        if self.path.startswith('/api/scope-failure'):
            raise RuntimeError('authentication failure detail')

    def _handle_get(self):
        if self.path.startswith('/api/boom'):
            raise ValueError('internal-query-detail')
        if self.path.startswith('/api/unavailable'):
            raise ServiceError('服务暂不可用', status=503, code='test_unavailable')
        if self.path.startswith('/api/handled'):
            self._send_json({'ok': False, 'code': 'handled_failure'}, status=502)
        elif self.path.startswith('/api/forbidden'):
            raise ServiceError('无权访问', status=403, code='forbidden')
        else:
            self._send_json({'ok': True})

    _handle_post = _handle_get
    _handle_put = _handle_get
    _handle_delete = _handle_get


class RequestLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), ProbeHandler)
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, method, path):
        req = Request(self.base + path, method=method, headers={
            'Authorization': 'Bearer private-header', 'Cookie': 'private-cookie',
            'X-Request-ID': 'untrusted-client-id',
        })
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            return response.code, response.headers, json.load(response)

    def test_all_methods_capture_unexpected_exceptions_once(self):
        for method in ('GET', 'POST', 'PUT', 'DELETE'):
            with self.subTest(method=method), self.assertLogs('backend.server', level='INFO') as logs:
                status, headers, body = self.request(method, '/api/boom?code=private-code&state=private-state')
            self.assertEqual(status, 500)
            self.assertEqual(body['code'], 'internal_error')
            self.assertNotIn('internal-query-detail', json.dumps(body))
            self.assertEqual(headers['X-Request-ID'], body['requestId'])
            self.assertNotEqual(body['requestId'], 'untrusted-client-id')
            self.assertEqual(len(logs.records), 1)
            record = logs.records[0]
            self.assertEqual(record.levelno, logging.ERROR)
            self.assertIs(record.exc_info[0], ValueError)
            output = '\n'.join(logs.output)
            self.assertIn('Traceback', output)
            self.assertIn('path=/api/boom status=500 duration_ms=', output)
            self.assertIn(body['requestId'], output)
            for private in ('private-code', 'private-state', 'private-header', 'private-cookie'):
                self.assertNotIn(private, output)

    def test_authentication_is_inside_boundary(self):
        with self.assertLogs('backend.server', level='ERROR') as logs:
            status, _, _ = self.request('GET', '/api/scope-failure')
        self.assertEqual(status, 500)
        self.assertIs(logs.records[0].exc_info[0], RuntimeError)

    def test_expected_and_explicit_5xx_are_also_logged(self):
        for path, expected, has_traceback in (('/api/unavailable', 503, True), ('/api/handled', 502, False)):
            with self.subTest(path=path), self.assertLogs('backend.server', level='ERROR') as logs:
                status, headers, body = self.request('GET', path)
            self.assertEqual(status, expected)
            self.assertEqual(len(logs.records), 1)
            self.assertEqual(bool(logs.records[0].exc_info), has_traceback)
            self.assertEqual(body['requestId'], headers['X-Request-ID'])

    def test_4xx_has_no_traceback_and_success_has_request_summary(self):
        with self.assertLogs('backend.server', level='WARNING') as logs:
            status, _, body = self.request('GET', '/api/forbidden')
        self.assertEqual(status, 403)
        self.assertEqual(body['code'], 'forbidden')
        self.assertFalse(logs.records[0].exc_info)
        with self.assertLogs('backend.server', level='INFO') as logs:
            status, headers, _ = self.request('GET', '/api/ok')
        self.assertEqual(status, 200)
        self.assertIn(headers['X-Request-ID'], logs.output[0])


class LoggingConfigurationTests(unittest.TestCase):
    def test_redacts_credentials_and_urls_in_exception_traceback(self):
        try:
            raise ValueError('https://upstream.test/token?code=secret-code&state=secret-state password=secret-password Bearer secret-bearer postgresql://admin:secret-db@localhost/db')
        except ValueError:
            import sys
            record = logging.LogRecord('test', logging.ERROR, __file__, 1, 'failure', (), sys.exc_info())
        output = RedactingFormatter('%(message)s').format(record)
        self.assertIn('Traceback', output)
        for secret in ('secret-code', 'secret-state', 'secret-password', 'secret-bearer', 'secret-db'):
            self.assertNotIn(secret, output)

    def test_configuration_is_idempotent_and_file_rotation_preserves_history(self):
        root = logging.getLogger()
        old_handlers, old_level = list(root.handlers), root.level
        old_sys_hook, old_thread_hook = sys.excepthook, threading.excepthook
        with tempfile.TemporaryDirectory() as temp, patch('backend.observability.get_storage_root', return_value=Path(temp)), patch('sys.stderr', new_callable=io.StringIO):
            try:
                configure_logging()
                configure_logging()
                added = [h for h in root.handlers if h not in old_handlers]
                self.assertEqual(len(added), 2)
                file_handler = next(h for h in added if hasattr(h, 'maxBytes'))
                self.assertEqual(file_handler.maxBytes, 10 * 1024 * 1024)
                self.assertEqual(file_handler.backupCount, 5)
                file_handler.maxBytes = 250
                for i in range(15):
                    logging.getLogger('test').info('rotation entry=%d %s', i, 'x' * 80)
                files = list((Path(temp) / 'logs').glob('web-3080.log*'))
                self.assertGreater(len(files), 1)
                self.assertLessEqual(len(files), 6)
                self.assertIn('rotation entry=14', (Path(temp) / 'logs/web-3080.log').read_text(encoding='utf-8'))
            finally:
                for handler in list(root.handlers):
                    if handler not in old_handlers:
                        root.removeHandler(handler)
                        handler.close()
                root.setLevel(old_level)
                sys.excepthook, threading.excepthook = old_sys_hook, old_thread_hook

    def test_system_and_thread_exceptions_reach_application_logger(self):
        from types import SimpleNamespace
        try:
            raise RuntimeError('test system failure')
        except RuntimeError:
            info = sys.exc_info()
            with self.assertLogs('handraw.system', level='CRITICAL') as logs:
                log_unhandled_exception(*info)
                log_unhandled_thread(SimpleNamespace(exc_type=info[0], exc_value=info[1], exc_traceback=info[2], thread=threading.current_thread()))
        self.assertIn('event=process_unhandled_exception', logs.output[0])
        self.assertIn('event=thread_unhandled_exception', logs.output[1])

    def test_background_reconciler_logs_and_survives_iteration_failure(self):
        worker = GenerationReconciler(Mock())
        worker._stop = Mock()
        worker._stop.is_set.side_effect = [False, False, True]
        worker.reconcile_once = Mock(side_effect=[RuntimeError('temporary DB failure'), 0])
        worker.reconcile_economy_once = Mock(side_effect=[RuntimeError('temporary economy failure'), None])
        with self.assertLogs('backend.server', level='ERROR') as logs:
            worker._run()
        self.assertEqual(worker.reconcile_once.call_count, 2)
        self.assertEqual(worker.reconcile_economy_once.call_count,2)
        self.assertTrue(any('worker=generation-reconciler iteration failed' in message for message in logs.output))
        self.assertTrue(any('worker=economy-maintenance iteration failed' in message for message in logs.output))

    def test_connection_failures_outside_dispatch_reach_log_fallback(self):
        server = HandrawHTTPServer(('127.0.0.1', 0), ProbeHandler)
        try:
            with self.assertLogs('backend.server', level='ERROR') as logs:
                try:
                    raise RuntimeError('connection cleanup failure')
                except RuntimeError:
                    server.handle_error(None, ('127.0.0.1', 1))
            self.assertIn('event=http_connection_failure', logs.output[0])
            self.assertIs(logs.records[0].exc_info[0], RuntimeError)
        finally:
            server.server_close()


if __name__ == '__main__':
    unittest.main()
