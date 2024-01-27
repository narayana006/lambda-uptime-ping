"""The HTTP check itself.

`check_target` never opens a socket on its own: it calls a `fetch` function
that is passed in. `http_fetch` is the real one; tests pass a fake.
"""

from __future__ import annotations

import http.client
import ssl
import time
from dataclasses import asdict, dataclass
from typing import Callable
from urllib.parse import urlsplit

from .config import Target

OK = "ok"
DOWN = "down"
SLOW = "slow"
CERT_EXPIRING = "cert_expiring"

USER_AGENT = "lambda-uptime-ping/0.1"


@dataclass(frozen=True)
class FetchResponse:
    status_code: int
    elapsed_ms: float
    # Expiry time of the server certificate as a Unix timestamp; None for plain HTTP.
    cert_expires_at: float | None = None


# fetch(url, timeout_seconds) -> FetchResponse, or raises on any connection failure.
Fetch = Callable[[str, float], FetchResponse]


@dataclass(frozen=True)
class CheckResult:
    name: str
    url: str
    status: str
    detail: str
    status_code: int | None = None
    elapsed_ms: float | None = None
    cert_days_left: float | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in ("elapsed_ms", "cert_days_left"):
            if data[key] is not None:
                data[key] = round(data[key], 1)
        return data


def http_fetch(url: str, timeout: float) -> FetchResponse:
    """GET the URL once, without following redirects.

    The timeout applies to each socket operation (connect, send, read), so the
    worst case for one check is a small multiple of it. The elapsed time covers
    connect, TLS handshake and the response headers, not the body.
    """
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    is_https = parts.scheme == "https"
    if is_https:
        conn = http.client.HTTPSConnection(
            parts.hostname, parts.port, timeout=timeout, context=ssl.create_default_context()
        )
    else:
        conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=timeout)

    start = time.monotonic()
    try:
        conn.connect()
        cert_expires_at = None
        if is_https:
            cert = conn.sock.getpeercert()
            if cert and cert.get("notAfter"):
                cert_expires_at = float(ssl.cert_time_to_seconds(cert["notAfter"]))
        conn.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        response = conn.getresponse()
        elapsed_ms = (time.monotonic() - start) * 1000
        return FetchResponse(response.status, elapsed_ms, cert_expires_at)
    finally:
        conn.close()


def _describe_error(exc: Exception, timeout: float) -> str:
    if isinstance(exc, TimeoutError):
        return f"timed out after {timeout:g} s"
    text = str(exc) or type(exc).__name__
    if isinstance(exc, ssl.SSLCertVerificationError):
        text = f"TLS certificate check failed: {exc.verify_message or text}"
    return text[:200]


def _status_is_healthy(code: int, expect: tuple[int, ...] | None) -> bool:
    return code in expect if expect is not None else 200 <= code <= 399


def check_target(target: Target, fetch: Fetch, now: float) -> CheckResult:
    """Run one check and classify it. Worst problem wins: down, slow, cert_expiring."""
    try:
        response = fetch(target.url, target.timeout_seconds)
    except Exception as exc:  # any failure to get a response means "down"
        return CheckResult(target.name, target.url, DOWN, _describe_error(exc, target.timeout_seconds))

    days_left = None
    if response.cert_expires_at is not None:
        days_left = (response.cert_expires_at - now) / 86400
    common = dict(
        name=target.name,
        url=target.url,
        status_code=response.status_code,
        elapsed_ms=response.elapsed_ms,
        cert_days_left=days_left,
    )
    timing = f"HTTP {response.status_code} in {response.elapsed_ms:.0f} ms"

    if not _status_is_healthy(response.status_code, target.expect_status):
        if target.expect_status is None:
            wanted = "2xx or 3xx"
        else:
            wanted = " or ".join(str(code) for code in target.expect_status)
        return CheckResult(status=DOWN, detail=f"HTTP {response.status_code}, expected {wanted}", **common)
    if response.elapsed_ms > target.slow_ms:
        return CheckResult(
            status=SLOW,
            detail=f"{timing}, slower than the {target.slow_ms:.0f} ms threshold",
            **common,
        )
    if days_left is not None and days_left < target.cert_warn_days:
        return CheckResult(
            status=CERT_EXPIRING,
            detail=f"TLS certificate expires in {days_left:.1f} days "
            f"(warning threshold {target.cert_warn_days:g} days)",
            **common,
        )
    if days_left is not None:
        timing += f", TLS certificate valid for {days_left:.0f} more days"
    return CheckResult(status=OK, detail=timing, **common)
