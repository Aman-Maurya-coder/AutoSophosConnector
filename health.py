"""
health.py – Layer-2 internet connectivity health checks.

This module probes configured internet health endpoints sequentially.
If the first endpoint succeeds, probing stops immediately and internet is
marked reachable. If an endpoint fails, probing continues to the next endpoint.

Failures are classified into fine-grained categories:
  - DNS_FAILURE
  - CONNECT_TIMEOUT
  - READ_TIMEOUT
  - SSL_ERROR
  - HTTP_ERROR
  - CAPTIVE_PORTAL_DETECTED
  - GATEWAY_UNREACHABLE
"""

import enum
import socket
import time
import traceback
from dataclasses import dataclass, field
from typing import List, Optional

import requests
import requests.exceptions

import config
from logger import log, log_debug


# ---------------------------------------------------------------------------
# Result classification
# ---------------------------------------------------------------------------

class CheckResult(enum.Enum):
    SUCCESS                 = "SUCCESS"
    DNS_FAILURE             = "DNS_FAILURE"
    CONNECT_TIMEOUT         = "CONNECT_TIMEOUT"
    READ_TIMEOUT            = "READ_TIMEOUT"
    SSL_ERROR               = "SSL_ERROR"
    HTTP_ERROR              = "HTTP_ERROR"
    CAPTIVE_PORTAL_DETECTED  = "CAPTIVE_PORTAL_DETECTED"
    GATEWAY_UNREACHABLE     = "GATEWAY_UNREACHABLE"


# Severity order: lower index = less severe.
_SEVERITY = [
    CheckResult.SUCCESS,
    CheckResult.DNS_FAILURE,
    CheckResult.CONNECT_TIMEOUT,
    CheckResult.READ_TIMEOUT,
    CheckResult.SSL_ERROR,
    CheckResult.HTTP_ERROR,
    CheckResult.CAPTIVE_PORTAL_DETECTED,
    CheckResult.GATEWAY_UNREACHABLE,
]


@dataclass
class HealthCheck:
    """Result of a single endpoint probe."""
    endpoint: str
    url: str
    result: CheckResult
    status_code: Optional[int] = None
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    exc_type: Optional[str] = None
    exc_traceback: Optional[str] = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_captive_portal(response: requests.Response) -> bool:
    """Return True if the response indicates Sophos captive portal interception."""
    final_url = response.url or ""
    for pattern in config.CAPTIVE_PORTAL_PATTERNS:
        if pattern in final_url:
            return True
    try:
        body_snippet = response.text[:2048]
    except Exception:
        body_snippet = ""
    for pattern in config.CAPTIVE_PORTAL_PATTERNS:
        if pattern in body_snippet:
            return True
    return False


# Patterns in SSLError messages that indicate a captive-portal TLS MITM
# (Sophos injects a self-signed certificate when the session expires).
_SSL_MITM_PATTERNS = [
    "self-signed certificate",
    "self signed certificate",
    "certificate verify failed",
]


def _classify_exception(exc: Exception) -> CheckResult:
    """Map a requests/socket exception to a specific CheckResult."""
    if isinstance(exc, requests.exceptions.SSLError):
        ssl_msg = str(exc).lower()
        if any(p in ssl_msg for p in _SSL_MITM_PATTERNS):
            return CheckResult.CAPTIVE_PORTAL_DETECTED
        return CheckResult.SSL_ERROR
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return CheckResult.CONNECT_TIMEOUT
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return CheckResult.READ_TIMEOUT

    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    if isinstance(exc, socket.gaierror) or isinstance(cause, socket.gaierror):
        return CheckResult.DNS_FAILURE

    msg = str(exc).lower()
    if (
        "getaddrinfo" in msg
        or "name or service not known" in msg
        or "nodename nor servname" in msg
        or "nameresolutionerror" in msg
    ):
        return CheckResult.DNS_FAILURE

    if isinstance(exc, requests.exceptions.ConnectionError):
        if "timeout" in msg or "timed out" in msg:
            return CheckResult.CONNECT_TIMEOUT
        return CheckResult.CONNECT_TIMEOUT

    if isinstance(exc, requests.exceptions.HTTPError):
        return CheckResult.HTTP_ERROR

    return CheckResult.HTTP_ERROR


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def probe_endpoint(
    name: str,
    url: str,
    session: Optional[requests.Session] = None,
) -> HealthCheck:
    """
    Probe a single URL sequentially and return a HealthCheck result.
    """
    timeout = (config.HEALTH_CONNECT_TIMEOUT, config.HEALTH_READ_TIMEOUT)
    get = session.get if session is not None else requests.get

    t0 = time.monotonic()
    try:
        resp = get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"Connection": "close"},
        )
        latency_ms = (time.monotonic() - t0) * 1000
        log_debug(
            f"[{name}] "
            f"status={resp.status_code} "
            f"final_url={resp.url} "
            f"history={[r.status_code for r in resp.history]}"
        )

        try:
            log_debug(f"[{name}] body:\n{resp.text[:300]}")
        except Exception:
            pass
        if _is_captive_portal(resp):
            return HealthCheck(
                endpoint=name,
                url=url,
                result=CheckResult.CAPTIVE_PORTAL_DETECTED,
                status_code=resp.status_code,
                latency_ms=latency_ms,
            )

        if resp.status_code in (200, 204):
            return HealthCheck(
                endpoint=name,
                url=url,
                result=CheckResult.SUCCESS,
                status_code=resp.status_code,
                latency_ms=latency_ms,
            )

        return HealthCheck(
            endpoint=name,
            url=url,
            result=CheckResult.HTTP_ERROR,
            status_code=resp.status_code,
            latency_ms=latency_ms,
            error=f"Unexpected HTTP {resp.status_code}",
        )

    except Exception as exc:
        latency_ms = (time.monotonic() - t0) * 1000
        result = _classify_exception(exc)
        log_debug(
            f"[{name}] "
            f"exception={type(exc).__name__} "
            f"message={exc}"
        )
        return HealthCheck(
            endpoint=name,
            url=url,
            result=result,
            latency_ms=latency_ms,
            error=str(exc),
            exc_type=type(exc).__name__,
            exc_traceback=traceback.format_exc(),
        )


def run_health_check(
    health_session: Optional[requests.Session] = None,
) -> List[HealthCheck]:
    """
    Probe configured endpoints sequentially.

    Stops immediately on the first SUCCESS. Only proceeds to the next
    endpoint if the current one fails.
    """
    results: List[HealthCheck] = []

    for name, url in config.HEALTH_ENDPOINTS:
        hc = probe_endpoint(name, url, health_session)
        results.append(hc)

        if hc.result == CheckResult.SUCCESS:
            log_debug(
                f"Health check SUCCESS: endpoint={hc.endpoint} latency={hc.latency_ms:.0f}ms (sequential check stopped)"
            )
            # Stop immediately on success as per requirement
            break
        else:
            msg = (
                f"Health check endpoint probe failed: endpoint={hc.endpoint} "
                f"latency={hc.latency_ms:.0f}ms result={hc.result.value}"
            )
            if hc.error:
                msg += f" error={hc.error}"
            log_debug(msg)
            if hc.exc_traceback:
                log_debug(f"Traceback [{hc.endpoint}]:\n{hc.exc_traceback}")

    return results


def interpret_health(results: List[HealthCheck]) -> CheckResult:
    """
    Collapse sequential HealthCheck results into an aggregate CheckResult.

    Priority order:
    1. Any SUCCESS -> SUCCESS
    2. Any CAPTIVE_PORTAL_DETECTED -> CAPTIVE_PORTAL_DETECTED
    3. Otherwise -> worst failure in severity order.
    """
    if not results:
        return CheckResult.HTTP_ERROR

    for hc in results:
        if hc.result == CheckResult.SUCCESS:
            return CheckResult.SUCCESS

    for hc in results:
        if hc.result == CheckResult.CAPTIVE_PORTAL_DETECTED:
            return CheckResult.CAPTIVE_PORTAL_DETECTED

    worst = CheckResult.DNS_FAILURE
    for hc in results:
        try:
            if _SEVERITY.index(hc.result) > _SEVERITY.index(worst):
                worst = hc.result
        except ValueError:
            pass
    return worst
