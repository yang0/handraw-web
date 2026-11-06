"""Exercise document error pages and client reporting over isolated HTTP."""
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.server import HandrawRequestHandler
from backend.services import ServiceError


class ErrorProbe(HandrawRequestHandler):
    def _enforce_token_scope(self):
        pass

    def _handle_get(self):
        if self.path.startswith('/api/native-error'):
            self.send_error(404, 'private file location')
            return
        if self.path.startswith('/api/crash'):
            raise RuntimeError('private database detail')
        raise ServiceError('操作无效 <script>alert(1)</script>', status=409, code='invalid_operation')


class ApplicationErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), ErrorProbe)
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, path, headers=None, body=None):
        request_headers = {'Accept': 'application/json', 'Content-Type': 'application/json', 'Origin': self.base}
        request_headers.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.base + path, data=data, headers=request_headers)
        with patch.dict(os.environ, {'HANDRAW_ALLOWED_ORIGINS': self.base}), patch('backend.server.check_auth_rate_limit', return_value=True):
            try:
                response = urlopen(request, timeout=5)
            except HTTPError as exc:
                response = exc
            with response:
                return response.code, response.headers, response.read().decode()

    def test_navigation_errors_are_escaped_html_with_reference_and_recovery_links(self):
        for path, expected in (('/api/crash', 500), ('/api/conflict', 409)):
            with self.subTest(path=path), self.assertLogs('backend.server', level='WARNING'):
                status, headers, body = self.request(path, {'Accept': 'text/html', 'Sec-Fetch-Mode': 'navigate'})
            self.assertEqual(status, expected)
            self.assertIn('text/html', headers['Content-Type'])
            self.assertIn(headers['X-Request-ID'], body)
            self.assertIn('href="/"', body)
            self.assertIn('href="/?view=auth"', body)
            self.assertNotIn('private database detail', body)
            self.assertNotIn('<script>', body)
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertIn("default-src 'none'", headers['Content-Security-Policy'])

    def test_programmatic_api_errors_remain_json(self):
        with self.assertLogs('backend.server', level='ERROR'):
            status, headers, body = self.request('/api/crash')
        self.assertEqual(status, 500)
        self.assertIn('application/json', headers['Content-Type'])
        self.assertEqual(json.loads(body)['requestId'], headers['X-Request-ID'])

    def test_stdlib_errors_also_use_the_public_error_page(self):
        with self.assertLogs('backend.server', level='WARNING'):
            status, headers, body = self.request('/api/native-error', {'Accept': 'text/html'})
        self.assertEqual(status, 404)
        self.assertIn('text/html', headers['Content-Type'])
        self.assertNotIn('private file location', body)
        self.assertIn(headers['X-Request-ID'], body)

    def test_unsupported_head_request_has_no_response_body(self):
        with self.assertLogs('backend.server', level='ERROR'):
            try:
                response = urlopen(Request(self.base + '/api/native-error', method='HEAD'), timeout=5)
            except HTTPError as response:
                with response:
                    self.assertEqual(response.code, 501)
                    self.assertEqual(response.read(), b'')

    def test_client_event_is_logged_with_bounded_metadata(self):
        event = {'kind': 'runtime', 'errorType': 'TypeError', 'channel': 'studio', 'script': 'shared.js',
                 'line': 44, 'column': 9, 'eventId': 'a' * 32, 'relatedRequestId': 'b' * 32, 'status': 500}
        with self.assertLogs('backend.application_errors', level='WARNING') as logs:
            status, headers, body = self.request('/api/client-errors', body=event)
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(body)['requestId'], headers['X-Request-ID'])
        self.assertIn('event=client_error kind=runtime type=TypeError channel=studio script=shared.js line=44', logs.output[0])
        self.assertIn('related_request_id=' + 'b' * 32, logs.output[0])

    def test_raw_messages_unknown_fields_and_oversized_reports_are_rejected(self):
        for event, expected in (({'kind': 'runtime', 'message': 'private content'}, 400),
                                ({'kind': []}, 400), ({'kind': 'x' * 5000}, 413)):
            with self.subTest(expected=expected), self.assertLogs('backend.server', level='WARNING'):
                status, _, _ = self.request('/api/client-errors', body=event)
            self.assertEqual(status, expected)

    def test_cross_origin_report_is_denied(self):
        with self.assertLogs('backend.server', level='WARNING'):
            status, _, _ = self.request('/api/client-errors', {'Origin': 'https://untrusted.test'}, {'kind': 'runtime'})
        self.assertEqual(status, 403)

    def test_client_report_rate_limit_cannot_be_bypassed(self):
        from backend.server import HandrawRequestHandler
        # Call the real boundary with a denied rate-limit decision.
        handler = object.__new__(HandrawRequestHandler)
        handler.headers = {}
        handler.client_address = ('192.0.2.1', 1)
        with patch.object(handler, '_demo_enabled', return_value=False), patch('backend.server.check_auth_rate_limit', return_value=False):
            with self.assertRaises(ServiceError) as error:
                handler._enforce_auth_rate_limit('client_error', '', per_ip_only=True)
        self.assertEqual(error.exception.status, 429)


if __name__ == '__main__':
    unittest.main()
