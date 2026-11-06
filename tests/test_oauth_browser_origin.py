"""OAuth browser-cookie regressions with real HTTP and isolated SQLite storage.

Provider traffic is mocked; neither Google nor real user accounts are accessed.
"""
import http.cookiejar
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, build_opener

from backend.db import Database
from backend.server import HandrawRequestHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OAuthHandler(HandrawRequestHandler):
    def _enforce_auth_rate_limit(self, *args, **kwargs):
        # This suite verifies OAuth state, not the shared rate limiter.
        pass


class OAuthBrowserOriginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'oauth.db')
        self.db.migrate()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), OAuthHandler)
        self.server.db = self.db
        self.server.channel_role = 'main'
        self.server.allow_demo_routes = False
        port = self.server.server_port
        self.canonical = f'http://localhost:{port}'
        self.alias = f'http://127.0.0.1:{port}'
        self.env = patch.dict(os.environ, {
            'HANDRAW_DEMO_MODE': '0',
            'HANDRAW_GOOGLE_CLIENT_ID': 'test-client',
            'HANDRAW_GOOGLE_CLIENT_SECRET': 'test-secret',
            'HANDRAW_GOOGLE_CALLBACK_URL': self.canonical + '/api/auth/google/callback',
            'HANDRAW_GITHUB_CLIENT_ID': 'test-client',
            'HANDRAW_GITHUB_CLIENT_SECRET': 'test-secret',
            'HANDRAW_GITHUB_CALLBACK_URL': self.canonical + '/api/auth/github/callback',
        })
        self.env.start()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.jar), NoRedirect())

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.db.close()
        self.env.stop()
        self.temp.cleanup()

    def request(self, url):
        try:
            response = self.opener.open(url, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            response.read()
            return response.code, response.headers

    def begin_google(self):
        status, headers = self.request(self.canonical + '/api/auth/google/start')
        self.assertEqual(status, 303)
        location = headers['Location']
        self.assertTrue(location.startswith('https://accounts.google.com/'))
        self.assertIn('handraw_google_nonce=', headers['Set-Cookie'])
        return parse_qs(urlsplit(location).query)['state'][0]

    def callback(self, state, origin=None):
        return self.request((origin or self.canonical) + '/api/auth/google/callback?' +
                            urlencode({'state': state, 'code': 'private-callback-code'}))

    def test_alias_redirects_before_creating_state_for_both_providers(self):
        for provider in ('google', 'github'):
            with self.subTest(provider=provider):
                status, headers = self.request(self.alias + f'/api/auth/{provider}/start?mode=login&ignored=private')
                self.assertEqual(status, 303)
                self.assertEqual(headers['Location'], self.canonical + f'/api/auth/{provider}/start?mode=login')
                self.assertIsNone(headers.get('Set-Cookie'))
                self.assertEqual(self.db.get_conn().execute('SELECT COUNT(*) FROM oauth_flows').fetchone()[0], 0)

    def test_linking_never_switches_to_another_hosts_login_session(self):
        for provider in ('google', 'github'):
            with self.subTest(provider=provider), self.assertLogs('backend.server', level='WARNING'):
                try:
                    self.opener.open(self.alias + f'/api/auth/{provider}/start?mode=link', timeout=5)
                except HTTPError as response:
                    with response:
                        body = json.load(response)
                        self.assertEqual(response.code, 409)
                        self.assertIsNone(response.headers.get('Location'))
                        self.assertEqual(body['code'], 'oauth_origin_mismatch')
                else:
                    self.fail('Cross-host linking must require an explicit canonical-site login')
                self.assertEqual(self.db.get_conn().execute('SELECT COUNT(*) FROM oauth_flows').fetchone()[0], 0)

    def test_google_roundtrip_from_alias_preserves_browser_cookie(self):
        status, headers = self.request(self.alias + '/api/auth/google/start')
        self.assertEqual(status, 303)
        self.assertEqual(headers['Location'], self.canonical + '/api/auth/google/start?mode=login')
        state = self.begin_google()
        with patch('backend.p2_google.fetch_google_identity', return_value={
            'subject': 'test-subject-123', 'email': 'origin-test@example.test', 'login': 'Origin Test',
        }) as provider:
            status, headers = self.callback(state)
            provider.assert_called_once()
        self.assertEqual(status, 303)
        self.assertEqual(headers['Location'], '/?view=oauth-register')
        self.assertEqual(self.db.get_conn().execute('SELECT COUNT(*) FROM oauth_flows').fetchone()[0], 0)
        self.assertEqual(self.db.get_conn().execute('SELECT COUNT(*) FROM oauth_signup_tickets').fetchone()[0], 1)
        # Replaying the same callback still fails before provider access.
        with patch('backend.p2_google.fetch_google_identity') as provider, self.assertLogs('backend.p2_oauth', level='WARNING'):
            _, headers = self.callback(state)
            provider.assert_not_called()
        self.assertIn('oauth_error=oauth_state_invalid', headers['Location'])

    def test_wrong_host_callback_loses_cookie_and_logs_reason_without_secrets(self):
        state = self.begin_google()
        nonce = next(cookie.value for cookie in self.jar if cookie.name == 'handraw_google_nonce')
        with patch('backend.p2_google.fetch_google_identity') as provider, self.assertLogs('backend.p2_oauth', level='WARNING') as logs:
            status, headers = self.callback(state, origin=self.alias)
            provider.assert_not_called()
        self.assertEqual(status, 303)
        self.assertIn('oauth_error=oauth_state_invalid', headers['Location'])
        output = '\n'.join(logs.output)
        self.assertIn('reason=missing_browser_nonce', output)
        self.assertIn(headers['X-Request-ID'], output)
        for secret in (state, nonce, 'private-callback-code'):
            self.assertNotIn(secret, output)

    def test_invalid_flow_reasons_preserve_state_validation(self):
        cases = (
            ('flow_expired', 'UPDATE oauth_flows SET expires_at=0'),
            ('provider_mismatch', "UPDATE oauth_flows SET provider='github'"),
            ('pkce_verifier_missing', "UPDATE oauth_flows SET code_verifier=''"),
            ('flow_missing_or_consumed', 'DELETE FROM oauth_flows'),
            ('browser_nonce_mismatch', "UPDATE oauth_flows SET browser_nonce_hash='different'"),
        )
        for reason, query in cases:
            with self.subTest(reason=reason):
                state = self.begin_google()
                self.db.get_conn().execute(query)
                with patch('backend.p2_google.fetch_google_identity') as provider, self.assertLogs('backend.p2_oauth', level='WARNING') as logs:
                    status, headers = self.callback(state)
                    provider.assert_not_called()
                self.assertEqual(status, 303)
                self.assertIn('oauth_error=oauth_state_invalid', headers['Location'])
                self.assertIn('reason=' + reason, '\n'.join(logs.output))
                self.assertNotIn(state, '\n'.join(logs.output))


if __name__ == '__main__':
    unittest.main()
