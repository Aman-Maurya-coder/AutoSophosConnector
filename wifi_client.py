"""
wifi_client.py – Low-level Sophos captive-portal interaction.

Session separation
------------------
``auth_session``   – used exclusively for login and logout requests.
                     Kept alive between logins so cookies are preserved.
``health_session`` – used exclusively for internet health checks (Layer 2).
                     Separated to prevent stale keep-alive sockets that were
                     created during authentication from interfering with
                     connectivity probes.
"""

import socket
import time

import requests

import config
from credentials import load_credentials
from logger import log, log_debug, log_diagnostic


class WifiClient:

    def __init__(self):
        # Auth-only session: preserves cookies between login/logout calls.
        self.auth_session = requests.Session()

        # Health-check session: never used for auth, replaced after each login
        # to discard any stale keep-alive connections.
        self.health_session = requests.Session()

        # Cache credentials once at startup to avoid blocking keyring IPC calls.
        self._username, self._password = load_credentials()

    def refresh_credentials(self):
        """Re-read credentials from keyring (call after user saves new credentials)."""
        self._username, self._password = load_credentials()

    def reset_session(self):
        """Reset both auth and health sessions (e.g. after system resume)."""
        self.auth_session = requests.Session()
        self.health_session = requests.Session()

    def reset_health_session(self):
        """
        Discard the current health session and create a fresh one.

        Called after a successful login so connectivity probes start with clean sockets.
        """
        self.health_session = requests.Session()

    def is_college_wifi_connected(self) -> bool:
        if not config.SSID_LOCK_ENABLED:
            return True

        target_gw = (config.COLLEGE_GATEWAY_IP or "").strip()
        if not target_gw:
            return True

        # Probe Sophos portal port 8090 with a raw TCP socket
        t0 = time.monotonic()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.5)
            err = sock.connect_ex((target_gw, 8090))
            sock.close()
            latency_ms = (time.monotonic() - t0) * 1000

            reachable = err in (0, 10061)  # 0=connected, 10061=WSAECONNREFUSED
            if not reachable:
                log(f"College gateway {target_gw}:8090 unreachable (wsa_err={err})")
                log_diagnostic(
                    endpoint=f"{target_gw}:8090",
                    latency_ms=latency_ms,
                    result="UNREACHABLE",
                    exc_type=f"WSA_ERR_{err}",
                    gw_reachable=False,
                    explanation="Gateway TCP connection check failed (wrong network or Wi-Fi disconnected)",
                )
            else:
                log_debug(f"College gateway reachable in {latency_ms:.0f}ms")

            return reachable
        except Exception as e:
            latency_ms = (time.monotonic() - t0) * 1000
            log(f"Gateway reachability check failed: {e}", level="ERROR")
            log_diagnostic(
                endpoint=f"{target_gw}:8090",
                latency_ms=latency_ms,
                result="ERROR",
                exc_type=type(e).__name__,
                gw_reachable=False,
                explanation=f"Exception during gateway reachability check: {e}",
            )
            return False

    def login(self):
        username, password = self._username, self._password
        if not username or not password:
            log("Missing credentials", level="ERROR")
            return False

        payload = {
            "mode": 191,
            "username": username,
            "password": password,
            "a": int(time.time() * 1000),
            "producttype": 0,
        }

        t0 = time.monotonic()
        try:
            r = self.auth_session.post(
                config.LOGIN_URL,
                headers=config.HEADERS,
                data=payload,
                timeout=10,
            )
            latency_ms = (time.monotonic() - t0) * 1000
            success = r.status_code == 200

            log(f"Login request sent (status={r.status_code})")
            log_diagnostic(
                endpoint=config.LOGIN_URL,
                latency_ms=latency_ms,
                result="SUCCESS" if success else f"HTTP_{r.status_code}",
                gw_reachable=True,
                decision="LOGIN_PROCESSED",
                explanation=f"Sophos login POST completed with HTTP {r.status_code}",
            )
            return success
        except Exception as e:
            latency_ms = (time.monotonic() - t0) * 1000
            log(f"Login request failed: {e}", level="ERROR")
            log_diagnostic(
                endpoint=config.LOGIN_URL,
                latency_ms=latency_ms,
                result="FAILED",
                exc_type=type(e).__name__,
                decision="LOGIN_FAILED",
                explanation=f"Sophos login request threw exception: {e}",
            )
            return False

    def logout(self):
        username = self._username
        if not username:
            return

        payload = {
            "mode": 193,
            "username": username,
            "a": int(time.time() * 1000),
            "producttype": 0,
        }

        try:
            self.auth_session.post(
                config.LOGOUT_URL,
                headers=config.HEADERS,
                data=payload,
                timeout=10,
            )
            log("Logout success")
        except Exception as e:
            log_debug(f"Logout failed: {e}")

    def soft_auth_check(self) -> bool:
        """
        Probe the Sophos gateway client page over LAN (no DNS) to test whether
        the captive portal is intercepting requests (indicating session expiry).

        Returns True if portal redirect/page is detected (session expired).
        Returns False if session appears valid or check fails.
        """
        t0 = time.monotonic()
        try:
            resp = requests.get(
                config.GATEWAY_AUTH_CHECK_URL,
                timeout=(3, 5),
                allow_redirects=True,
            )
            latency_ms = (time.monotonic() - t0) * 1000
            body = resp.text[:4096]
            for pattern in config.CAPTIVE_PORTAL_PATTERNS:
                if pattern in (resp.url or "") or pattern in body:
                    log("Soft auth check: captive portal detected — session expired")
                    log_diagnostic(
                        endpoint=config.GATEWAY_AUTH_CHECK_URL,
                        latency_ms=latency_ms,
                        result="PORTAL_DETECTED",
                        gw_reachable=True,
                        decision="TRIGGER_REAUTH",
                        explanation=f"Soft auth check matched pattern '{pattern}'",
                    )
                    return True

            log("Soft auth check: no portal fingerprint — session appears valid")
            log_diagnostic(
                endpoint=config.GATEWAY_AUTH_CHECK_URL,
                latency_ms=latency_ms,
                result="SESSION_VALID",
                gw_reachable=True,
                decision="SUPPRESS_REAUTH",
                explanation="Soft auth check reached gateway with no portal interception",
            )
            return False
        except Exception as e:
            latency_ms = (time.monotonic() - t0) * 1000
            log(f"Soft auth check failed (gateway unreachable?): {e}", level="WARNING")
            log_diagnostic(
                endpoint=config.GATEWAY_AUTH_CHECK_URL,
                latency_ms=latency_ms,
                result="CHECK_FAILED",
                exc_type=type(e).__name__,
                gw_reachable=False,
                decision="SUPPRESS_REAUTH",
                explanation=f"Soft auth check failed with error: {e}",
            )
            return False