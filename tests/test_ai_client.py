"""Tests for backend.ai_client (C1, S1, S7, S10)."""
from __future__ import annotations

import http.server
import json
import socket
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from backend import ai_client, document_parser, skill_prompt


class AIClientTests(unittest.TestCase):
    def test_no_key_configured_skips_request(self):
        with patch("backend.ai_client.load_ai_config", return_value={"url": "http://127.0.0.1:3065/v1", "key": "", "model": "test"}):
            text, meta = ai_client.chat([{"role": "user", "content": "hi"}], timeout=10)
            self.assertEqual(text, "")
            self.assertFalse(meta["ok"])
            self.assertEqual(meta["reason"], "no_key")

    def test_real_http_valid_chunked_json(self):
        """(a) Valid chunked JSON response succeeds with ok."""
        class ChunkedHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    self.rfile.read(content_len)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Connection", "close")
                self.end_headers()

                body = json.dumps({"choices": [{"message": {"content": "Chunked Hello"}}]}).encode("utf-8")
                # Send in 2 chunks
                part1 = body[:10]
                part2 = body[10:]
                self.wfile.write(f"{len(part1):X}\r\n".encode("ascii") + part1 + b"\r\n")
                self.wfile.write(f"{len(part2):X}\r\n".encode("ascii") + part2 + b"\r\n")
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ChunkedHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with patch("backend.ai_client.load_ai_config", return_value={"url": f"http://127.0.0.1:{port}", "key": "sk-test", "model": "m"}):
                text, meta = ai_client.chat([{"role": "user", "content": "hi"}], timeout=5.0)
                self.assertTrue(meta["ok"])
                self.assertEqual(meta["reason"], "")
                self.assertEqual(text, "Chunked Hello")
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=3.0)

    def test_real_http_content_length_json(self):
        """(b) Content-Length JSON response succeeds with ok."""
        class ContentLengthHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    self.rfile.read(content_len)

                body = json.dumps({"choices": [{"message": {"content": "Content-Length Hello"}}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ContentLengthHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with patch("backend.ai_client.load_ai_config", return_value={"url": f"http://127.0.0.1:{port}", "key": "sk-test", "model": "m"}):
                text, meta = ai_client.chat([{"role": "user", "content": "hi"}], timeout=5.0)
                self.assertTrue(meta["ok"])
                self.assertEqual(meta["reason"], "")
                self.assertEqual(text, "Content-Length Hello")
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=3.0)

    def test_real_http_slow_headers_timeout(self):
        """(c) Slow response headers trickling byte-by-byte times out within budget."""
        stop_event = threading.Event()
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        port = server_sock.getsockname()[1]

        def handle_conn():
            try:
                server_sock.settimeout(2.0)
                client_sock, _ = server_sock.accept()
                with client_sock:
                    # Read request line
                    client_sock.recv(4096)
                    # Trickle header 1 byte every 50ms
                    header = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    for b in header:
                        if stop_event.is_set():
                            break
                        client_sock.sendall(bytes([b]))
                        time.sleep(0.05)
            except Exception:
                pass

        server_thread = threading.Thread(target=handle_conn, daemon=True)
        server_thread.start()

        try:
            with patch("backend.ai_client.load_ai_config", return_value={"url": f"http://127.0.0.1:{port}", "key": "sk-test", "model": "m"}):
                start = time.monotonic()
                text, meta = ai_client.chat([{"role": "user", "content": "hi"}], timeout=0.1)
                elapsed = time.monotonic() - start
                self.assertFalse(meta["ok"])
                self.assertEqual(meta["reason"], "timeout")
                self.assertLess(elapsed, 0.5)
        finally:
            stop_event.set()
            server_sock.close()
            server_thread.join(timeout=1.0)

    def test_real_http_slow_body_trickle_times_out(self):
        """(d) Slow response body trickling times out within budget."""
        class TrickleHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    self.rfile.read(content_len)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                try:
                    for _ in range(50):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        time.sleep(0.05)
                except Exception:
                    pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), TrickleHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with patch("backend.ai_client.load_ai_config", return_value={"url": f"http://127.0.0.1:{port}", "key": "sk-test", "model": "m"}):
                start = time.monotonic()
                text, meta = ai_client.chat([{"role": "user", "content": "hi"}], timeout=0.15)
                elapsed = time.monotonic() - start
                self.assertFalse(meta["ok"])
                self.assertEqual(meta["reason"], "timeout")
                self.assertLess(elapsed, 0.6)
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=3.0)

    def test_real_http_huge_response_aborts_too_large(self):
        """(e) 3MB response body aborts with too_large."""
        class HugeHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    self.rfile.read(content_len)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                chunk = b"A" * (64 * 1024)
                try:
                    for _ in range(50):  # 50 * 64KB = 3.2MB > 2MB
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except Exception:
                    pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), HugeHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with patch("backend.ai_client.load_ai_config", return_value={"url": f"http://127.0.0.1:{port}", "key": "sk-test", "model": "m"}):
                text, meta = ai_client.chat([{"role": "user", "content": "hi"}], timeout=5.0)
                self.assertFalse(meta["ok"])
                self.assertEqual(meta["reason"], "too_large")
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=3.0)

    def test_5xx_retries_once_then_succeeds(self):
        call_count = 0
        call_lock = threading.Lock()

        class RetryHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                nonlocal call_count
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    self.rfile.read(content_len)

                with call_lock:
                    call_count += 1
                    current = call_count

                if current == 1:
                    self.send_response(500)
                    self.send_header("Content-Length", "0")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.flush()
                else:
                    body = json.dumps({"choices": [{"message": {"content": "Recovered Hello"}}]}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(body)
                    self.wfile.flush()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RetryHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with patch("backend.ai_client.load_ai_config", return_value={"url": f"http://127.0.0.1:{port}", "key": "sk-test", "model": "m"}):
                text, meta = ai_client.chat([{"role": "user", "content": "hi"}], timeout=10)
                self.assertEqual(call_count, 2)
                self.assertTrue(meta["ok"])
                self.assertEqual(text, "Recovered Hello")
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=3.0)

    def test_5xx_retries_once_and_fails(self):
        call_count = 0
        call_lock = threading.Lock()

        class FailHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                nonlocal call_count
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    self.rfile.read(content_len)

                with call_lock:
                    call_count += 1

                self.send_response(502)
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.flush()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FailHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with patch("backend.ai_client.load_ai_config", return_value={"url": f"http://127.0.0.1:{port}", "key": "sk-test", "model": "m"}):
                text, meta = ai_client.chat([{"role": "user", "content": "hi"}], timeout=10)
                self.assertEqual(call_count, 2)
                self.assertFalse(meta["ok"])
                self.assertEqual(meta["reason"], "http_502")
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=3.0)

    def test_4xx_does_not_retry(self):
        call_count = 0
        call_lock = threading.Lock()

        class ClientErrorHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                nonlocal call_count
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    self.rfile.read(content_len)

                with call_lock:
                    call_count += 1

                self.send_response(401)
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.flush()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ClientErrorHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with patch("backend.ai_client.load_ai_config", return_value={"url": f"http://127.0.0.1:{port}", "key": "sk-test", "model": "m"}):
                text, meta = ai_client.chat([{"role": "user", "content": "hi"}], timeout=10)
                self.assertEqual(call_count, 1)
                self.assertFalse(meta["ok"])
                self.assertEqual(meta["reason"], "http_401")
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=3.0)

    def test_skill_prompt_call_model_parameters(self):
        with patch("backend.ai_client.chat") as mock_chat:
            mock_chat.return_value = ("prompt result", {"ok": True, "reason": "", "elapsed_ms": 10})
            res = skill_prompt._call_model("sys prompt", "user prompt", timeout=120)
            self.assertEqual(res, "prompt result")
            mock_chat.assert_called_once_with(
                [
                    {"role": "system", "content": "sys prompt"},
                    {"role": "user", "content": "user prompt"},
                ],
                temperature=0.4,
                max_tokens=1200,
                timeout=120,
                json_mode=False,
            )

    def test_document_parser_ai_parse_article_parameters(self):
        with patch("backend.ai_client.chat") as mock_chat:
            mock_chat.return_value = (
                json.dumps({"title": "Test Title", "markdown": "# Test Title\n\nBody"}),
                {"ok": True, "reason": "", "elapsed_ms": 10},
            )
            res = document_parser.ai_parse_article("Some article text", "doc.txt")
            self.assertTrue(res["aiUsed"])
            self.assertEqual(res["title"], "Test Title")
            args, kwargs = mock_chat.call_args
            self.assertEqual(kwargs.get("temperature"), 0.1)
            self.assertEqual(kwargs.get("timeout"), 35)
            self.assertTrue(kwargs.get("json_mode"))

    def test_v1_dns_resolution_timeout_aborts_without_sending_request(self):
        """V1: Mock getaddrinfo delays 0.35s with 0.05s budget -> finishes <= 0.3s, 0 requests received."""
        request_received = False

        class RecordHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                nonlocal request_received
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    self.rfile.read(content_len)
                request_received = True
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.flush()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RecordHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()

        real_getaddrinfo = socket.getaddrinfo

        def slow_getaddrinfo(host, p, *args, **kwargs):
            if host == "slow-dns.mock":
                time.sleep(0.35)
                return real_getaddrinfo("127.0.0.1", p, *args, **kwargs)
            return real_getaddrinfo(host, p, *args, **kwargs)

        try:
            with patch("socket.getaddrinfo", side_effect=slow_getaddrinfo):
                with patch("backend.ai_client.load_ai_config", return_value={"url": f"http://slow-dns.mock:{port}", "key": "sk-test", "model": "m"}):
                    t0 = time.monotonic()
                    text, meta = ai_client.chat([{"role": "user", "content": "hi"}], timeout=0.05)
                    elapsed = time.monotonic() - t0
                    self.assertLess(elapsed, 0.3)
                    self.assertFalse(meta["ok"])
                    self.assertEqual(meta["reason"], "timeout")
                    self.assertFalse(request_received)
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=3.0)

    def test_v1_post_connect_deadline_expired_sends_no_request(self):
        """V1: If deadline expires right after connection, conn.close() is called and 0 requests sent."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        port = server_sock.getsockname()[1]
        request_bytes = bytearray()

        def accept_conn():
            try:
                server_sock.settimeout(1.0)
                conn, _ = server_sock.accept()
                with conn:
                    conn.settimeout(0.5)
                    try:
                        while True:
                            chunk = conn.recv(1024)
                            if not chunk:
                                break
                            request_bytes.extend(chunk)
                    except Exception:
                        pass
            except Exception:
                pass

        th = threading.Thread(target=accept_conn, daemon=True)
        th.start()

        real_connect = ai_client.DirectHTTPConnection.connect

        def delayed_connect(conn_self):
            real_connect(conn_self)
            # Sleep past the deadline
            time.sleep(0.12)

        try:
            with patch.object(ai_client.DirectHTTPConnection, "connect", delayed_connect):
                with patch("backend.ai_client.load_ai_config", return_value={"url": f"http://127.0.0.1:{port}", "key": "sk-test", "model": "m"}):
                    text, meta = ai_client.chat([{"role": "user", "content": "hi"}], timeout=0.05)
                    self.assertFalse(meta["ok"])
                    self.assertEqual(meta["reason"], "timeout")
                    self.assertEqual(len(request_bytes), 0)
        finally:
            server_sock.close()
            th.join(timeout=1.0)

    def test_v1_ip_literal_skips_dns_resolution_thread(self):
        """V1: IP literals like 127.0.0.1 must not call _resolve_host or thread-based DNS."""
        with patch("backend.ai_client._resolve_host") as mock_resolve:
            with patch("backend.ai_client.DirectHTTPConnection.connect"), \
                 patch("backend.ai_client.DirectHTTPConnection.getresponse") as mock_resp, \
                 patch("backend.ai_client.DirectHTTPConnection.request"):
                mock_response = MagicMock()
                mock_response.status = 200
                mock_response.read.side_effect = [
                    json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8"),
                    b"",
                ]
                mock_resp.return_value = mock_response
                with patch("backend.ai_client.load_ai_config", return_value={"url": "http://127.0.0.1:3065", "key": "sk-test", "model": "m"}):
                    text, meta = ai_client.chat([{"role": "user", "content": "hi"}], timeout=5.0)
                    self.assertTrue(meta["ok"])
                    mock_resolve.assert_not_called()

    def test_v3_invalid_json_returns_immediately_without_retry(self):
        """V3: 200 response with invalid JSON body returns invalid_json immediately without retry."""
        call_count = 0
        call_lock = threading.Lock()

        class BadJsonHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                nonlocal call_count
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    self.rfile.read(content_len)

                with call_lock:
                    call_count += 1

                body = b"<html>502 Bad Gateway from Nginx</html>"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), BadJsonHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with patch("backend.ai_client.load_ai_config", return_value={"url": f"http://127.0.0.1:{port}", "key": "sk-test", "model": "m"}):
                text, meta = ai_client.chat([{"role": "user", "content": "hi"}], timeout=5.0)
                self.assertEqual(call_count, 1)
                self.assertFalse(meta["ok"])
                self.assertEqual(meta["reason"], "invalid_json")
                self.assertEqual(text, "")
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=3.0)

    def test_v3_connection_reset_retries_once(self):
        """V3: Transient connection reset triggers a single retry and succeeds on attempt 2."""
        attempt = 0
        attempt_lock = threading.Lock()

        class ResetThenSuccessHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                nonlocal attempt
                with attempt_lock:
                    attempt += 1
                    curr_attempt = attempt

                if curr_attempt == 1:
                    # Abruptly close connection without response to trigger ConnectionResetError / RemoteDisconnected
                    self.close_connection = True
                    return

                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    self.rfile.read(content_len)

                body = json.dumps({"choices": [{"message": {"content": "Retry Success"}}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ResetThenSuccessHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with patch("backend.ai_client.load_ai_config", return_value={"url": f"http://127.0.0.1:{port}", "key": "sk-test", "model": "m"}):
                text, meta = ai_client.chat([{"role": "user", "content": "hi"}], timeout=5.0)
                self.assertEqual(attempt, 2)
                self.assertTrue(meta["ok"])
                self.assertEqual(text, "Retry Success")
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=3.0)


if __name__ == "__main__":
    unittest.main()
