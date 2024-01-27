import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from conftest import NOW, ok
from uptime_ping.checks import CERT_EXPIRING, DOWN, OK, SLOW, check_target, http_fetch
from uptime_ping.config import Target

URL = "https://a.example/"


def check(response, **target_kwargs):
    target = Target(name="a", url=URL, **target_kwargs)

    def fetch(url, timeout):
        assert url == URL
        assert timeout == target.timeout_seconds
        if isinstance(response, Exception):
            raise response
        return response

    return check_target(target, fetch, NOW)


def test_healthy():
    result = check(ok(ms=85, cert_days=60))
    assert result.status == OK
    assert result.detail == "HTTP 200 in 85 ms, TLS certificate valid for 60 more days"
    assert result.status_code == 200
    assert result.cert_days_left == pytest.approx(60)


@pytest.mark.parametrize("code", [200, 204, 301, 399])
def test_2xx_and_3xx_are_healthy_by_default(code):
    assert check(ok(code=code)).status == OK


@pytest.mark.parametrize("code", [199, 400, 404, 500, 503])
def test_other_statuses_are_down(code):
    result = check(ok(code=code))
    assert result.status == DOWN
    assert result.detail == f"HTTP {code}, expected 2xx or 3xx"


def test_expect_status_is_exact():
    assert check(ok(code=401), expect_status=(401,)).status == OK
    result = check(ok(code=200), expect_status=(401, 403))
    assert result.status == DOWN
    assert result.detail == "HTTP 200, expected 401 or 403"


def test_slow_only_above_threshold():
    assert check(ok(ms=2000), slow_ms=2000).status == OK
    result = check(ok(ms=2000.5), slow_ms=2000)
    assert result.status == SLOW
    assert "slower than the 2000 ms threshold" in result.detail


def test_cert_expiring():
    assert check(ok(cert_days=14.5), cert_warn_days=14).status == OK
    result = check(ok(cert_days=3.25), cert_warn_days=14)
    assert result.status == CERT_EXPIRING
    assert result.detail == "TLS certificate expires in 3.2 days (warning threshold 14 days)"


def test_plain_http_has_no_cert_check():
    result = check(ok(cert_days=None))
    assert result.status == OK and result.cert_days_left is None


def test_worst_problem_wins():
    # wrong status + slow + expiring cert -> down
    assert check(ok(code=500, ms=9000, cert_days=1)).status == DOWN
    # slow + expiring cert -> slow
    assert check(ok(ms=9000, cert_days=1)).status == SLOW


def test_connection_errors_are_down():
    result = check(ConnectionRefusedError(61, "Connection refused"))
    assert result.status == DOWN
    assert "Connection refused" in result.detail
    assert result.status_code is None and result.elapsed_ms is None


def test_timeout_message():
    result = check(TimeoutError("timed out"), timeout_seconds=3)
    assert (result.status, result.detail) == (DOWN, "timed out after 3 s")


def test_expired_certificate_is_down():
    error = ssl.SSLCertVerificationError(1, "certificate verify failed")
    error.verify_message = "certificate has expired"
    result = check(error)
    assert result.status == DOWN
    assert result.detail == "TLS certificate check failed: certificate has expired"


def test_to_dict_rounds():
    data = check(ok(ms=85.4567, cert_days=60)).to_dict()
    assert data["elapsed_ms"] == 85.5
    assert data["cert_days_left"] == 60.0


# --- the real fetch function, against a server on the loopback interface only ---


@pytest.fixture
def local_server():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("User-Agent")))
            self.send_response(302 if self.path.startswith("/go") else 200)
            if self.path.startswith("/go"):
                self.send_header("Location", "/elsewhere")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", seen
    httpd.shutdown()
    httpd.server_close()


def test_http_fetch_gets_status_and_timing(local_server):
    base, seen = local_server
    response = http_fetch(base + "/health?deep=1", 5)
    assert response.status_code == 200
    assert response.elapsed_ms > 0
    assert response.cert_expires_at is None
    assert seen == [("/health?deep=1", "lambda-uptime-ping/0.1")]


def test_http_fetch_does_not_follow_redirects(local_server):
    base, seen = local_server
    assert http_fetch(base + "/go", 5).status_code == 302
    assert [path for path, _ in seen] == ["/go"]


def test_http_fetch_raises_when_nothing_listens(local_server):
    base, _ = local_server
    port = int(base.rsplit(":", 1)[1])
    closed = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    free_port = closed.server_address[1]
    closed.server_close()
    assert free_port != port
    with pytest.raises(OSError):
        http_fetch(f"http://127.0.0.1:{free_port}/", 2)
