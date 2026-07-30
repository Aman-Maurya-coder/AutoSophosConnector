"""
state_manager.py – Deterministic multi-layer connectivity state machine.

Layer 1 – Gateway reachability (TCP socket probe to 192.168.100.1:8090)
Layer 2 – Sequential internet health probes via health.py
Layer 3 – Auth re-login (only when captive portal is intercepted or soft-auth confirms session expiry)

States:
  STARTING
  CONNECTING
  CONNECTED
  VERIFYING
  INTERNET_UNAVAILABLE
  COLLEGE_WIFI_NOT_CONNECTED
  AUTHENTICATION_EXPIRED
  RETRYING_LOGIN
  FAILED
"""

import threading
import time
import traceback

import config
from health import CheckResult, interpret_health, run_health_check
from logger import log, log_debug, log_diagnostic
from wifi_client import WifiClient


class StateManager:

    def __init__(self):
        self.client = WifiClient()
        self.state = "STARTING"
        self.running = False
        self.monitor_thread = None
        self.lock = threading.Lock()
        self.callbacks = []
        self.is_connecting = False

        self._college_wifi_confirmed = False
        self._wake_pending = False

        self._consecutive_internet_failures = 0
        self._consecutive_auth_failures = 0

    def subscribe(self, cb):
        self.callbacks.append(cb)

    def set_state(self, value: str):
        """
        Update the current state.
        State transitions are deduplicated; callbacks and logs are triggered
        only when the state value actually changes.
        """
        with self.lock:
            old = self.state
            if old == value:
                return
            self.state = value

        log("State " + value)
        for cb in self.callbacks:
            try:
                cb(value)
            except Exception as e:
                log_debug(f"Callback exception for state {value}: {e}")

    def connect(self):
        threading.Thread(
            target=self._connect,
            daemon=True
        ).start()

    def handle_system_resume(self):
        if not self.running:
            return

        log("System resume event received")
        with self.lock:
            self._wake_pending = True
            self._college_wifi_confirmed = False

        self.client.reset_session()

    def _connect(self):
        with self.lock:
            if getattr(self, "is_connecting", False):
                return
            self.is_connecting = True

        try:
            self.running = False
            if self.monitor_thread and self.monitor_thread.is_alive():
                self.monitor_thread.join(timeout=5)

            self._consecutive_internet_failures = 0
            self._consecutive_auth_failures = 0

            self.set_state("CONNECTING")

            if not self.client.is_college_wifi_connected():
                self.set_state("COLLEGE_WIFI_NOT_CONNECTED")
                return

            with self.lock:
                self._college_wifi_confirmed = True

            if self.client.login():
                self.client.reset_health_session()
                self.set_state("CONNECTED")
                time.sleep(config.POST_LOGIN_GRACE)
                self.start_monitor()
            else:
                self.set_state("FAILED")

        finally:
            with self.lock:
                self.is_connecting = False

    def disconnect(self):
        self.running = False
        with self.lock:
            self._college_wifi_confirmed = False

        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)

        self.client.logout()
        self.set_state("DISCONNECTED")

    def start_monitor(self):
        if self.monitor_thread and self.monitor_thread.is_alive():
            return

        self.running = True
        self.monitor_thread = threading.Thread(
            target=self.monitor,
            daemon=True
        )
        self.monitor_thread.start()

    def _attempt_relogin(self) -> bool:
        """Execute a re-login attempt and update state."""
        self.set_state("RETRYING_LOGIN")
        log("Attempting re-login due to authentication expiry")

        if self.client.login():
            self.client.reset_health_session()
            self._consecutive_internet_failures = 0
            self._consecutive_auth_failures = 0
            self.set_state("CONNECTED")
            return True
        else:
            self._consecutive_auth_failures += 1
            log(
                f"Re-login failed (consecutive_auth_failures={self._consecutive_auth_failures})",
                level="ERROR",
            )
            self.set_state("FAILED")
            return False

    def monitor(self):
        """
        Main monitor loop running on daemon thread.

        Tick sequence:
          1. Check system sleep / wake.
          2. Layer 1: Check gateway reachability.
          3. Layer 2: Perform sequential internet health check.
          4. Evaluate aggregate result and manage counters / re-logins.
        """
        last_tick = time.monotonic()
        tick_count = 0

        while self.running:
            tick_count += 1
            now = time.monotonic()
            sleep_gap = now - last_tick

            with self.lock:
                wake_pending = self._wake_pending
                self._wake_pending = False

            woke_from_sleep = wake_pending or sleep_gap > (config.CHECK_INTERVAL * 2)
            last_tick = now

            if woke_from_sleep:
                log("Sleep/wake detected — refreshing connection state")
                with self.lock:
                    self._college_wifi_confirmed = False
                self.client.reset_session()
                self._consecutive_internet_failures = 0
                self._consecutive_auth_failures = 0

            # ------------------------------------------------------------------
            # Layer 1 — Gateway reachability
            # ------------------------------------------------------------------
            if not self.client.is_college_wifi_connected():
                with self.lock:
                    self._college_wifi_confirmed = False

                self.set_state("COLLEGE_WIFI_NOT_CONNECTED")
                self._consecutive_internet_failures = 0
                time.sleep(config.CHECK_INTERVAL)
                continue

            with self.lock:
                self._college_wifi_confirmed = True

            # ------------------------------------------------------------------
            # Layer 2 — Sequential Internet health check
            # ------------------------------------------------------------------
            # Discard stale health session if it has exceeded its max age.
            self.client.recycle_health_session_if_stale()

            # Transition to VERIFYING only if not currently CONNECTED to prevent UI flicker
            if self.state != "CONNECTED":
                self.set_state("VERIFYING")

            try:
                results = run_health_check(self.client.health_session)
            except Exception:
                log(
                    f"Unexpected error in run_health_check:\n{traceback.format_exc()}",
                    level="ERROR",
                )
                time.sleep(config.CHECK_INTERVAL)
                continue

            aggregate = interpret_health(results)
            # primary_endpoint = results[0].endpoint if results else "Unknown"
            # primary_latency = results[0].latency_ms if results and results[0].latency_ms else 0.0
            # primary_exc = results[0].exc_type if results else None
            matching = next(
                (r for r in results if r.result == aggregate),
                results[0] if results else None,
            )

            if matching:
                primary_endpoint = matching.endpoint
                primary_latency = matching.latency_ms or 0.0
                primary_exc = matching.exc_type
            else:
                primary_endpoint = "Unknown"
                primary_latency = 0.0
                primary_exc = None

            # ------------------------------------------------------------------
            # React to aggregate health result
            # ------------------------------------------------------------------

            if aggregate == CheckResult.SUCCESS:
                if self.state == "INTERNET_UNAVAILABLE":
                    log("Internet connection recovered", level="INFO")

                self._consecutive_internet_failures = 0
                self._consecutive_auth_failures = 0
                self.set_state("CONNECTED")

                # Periodic backstop: even when health checks succeed, verify
                # the session via direct portal probe every N ticks.  This
                # catches expiry masked by stale keep-alive sockets or
                # allowlisted health-check domains.
                if tick_count % config.SOFT_AUTH_BACKSTOP_INTERVAL == 0:
                    if self.client.soft_auth_check():
                        log(
                            "Periodic backstop: captive portal detected "
                            "despite SUCCESS health checks"
                        )
                        log_diagnostic(
                            endpoint="BACKSTOP_SOFT_AUTH",
                            latency_ms=0.0,
                            result="PORTAL_DETECTED",
                            retry_count=self._consecutive_auth_failures,
                            gw_reachable=True,
                            state=self.state,
                            decision="TRIGGER_REAUTH",
                            explanation="Periodic backstop soft_auth_check detected captive portal",
                        )
                        self._consecutive_auth_failures += 1
                        self.set_state("AUTHENTICATION_EXPIRED")
                        if self._consecutive_auth_failures >= config.MAX_AUTH_FAILURES:
                            self._attempt_relogin()
                            time.sleep(config.POST_LOGIN_GRACE)
                        else:
                            time.sleep(config.CHECK_INTERVAL)
                        continue

                log_diagnostic(
                    endpoint=primary_endpoint,
                    latency_ms=primary_latency,
                    result="SUCCESS",
                    retry_count=0,
                    gw_reachable=True,
                    state=self.state,
                    decision="KEEP_CONNECTED",
                    explanation="Internet reachable via sequential health check",
                )
                time.sleep(config.CHECK_INTERVAL)
                continue

            if aggregate == CheckResult.CAPTIVE_PORTAL_DETECTED:
                self._consecutive_auth_failures += 1
                log(
                    f"Captive portal detected (consecutive_auth_failures={self._consecutive_auth_failures})"
                )
                log_diagnostic(
                    endpoint=primary_endpoint,
                    latency_ms=primary_latency,
                    result="CAPTIVE_PORTAL_DETECTED",
                    retry_count=self._consecutive_auth_failures,
                    gw_reachable=True,
                    state=self.state,
                    decision="EXPIRE_AUTH",
                    explanation="Captive portal fingerprint detected on internet probe",
                )
                self.set_state("AUTHENTICATION_EXPIRED")

                if self._consecutive_auth_failures >= config.MAX_AUTH_FAILURES:
                    if not self._attempt_relogin():
                        time.sleep(config.CHECK_INTERVAL)
                    else:
                        time.sleep(config.POST_LOGIN_GRACE)
                else:
                    time.sleep(config.CHECK_INTERVAL)
                continue

            if aggregate == CheckResult.SSL_ERROR:
                log("SSL error during health check — skipping reconnect", level="WARNING")
                log_diagnostic(
                    endpoint=primary_endpoint,
                    latency_ms=primary_latency,
                    result="SSL_ERROR",
                    exc_type=primary_exc,
                    retry_count=self._consecutive_internet_failures,
                    gw_reachable=True,
                    state=self.state,
                    decision="IGNORE_RECONNECT",
                    explanation="SSL verification failure is not an auth expiry signal",
                )
                self.set_state("INTERNET_UNAVAILABLE")
                time.sleep(config.CHECK_INTERVAL)
                continue

            # DNS_FAILURE / CONNECT_TIMEOUT / READ_TIMEOUT / HTTP_ERROR
            self._consecutive_internet_failures += 1
            log(
                f"Internet check failure: aggregate={aggregate.value} "
                f"(consecutive_failures={self._consecutive_internet_failures}/{config.MAX_INTERNET_FAILURES})",
                level="WARNING",
            )
            log_diagnostic(
                endpoint=primary_endpoint,
                latency_ms=primary_latency,
                result=aggregate.value,
                exc_type=primary_exc,
                retry_count=self._consecutive_internet_failures,
                gw_reachable=True,
                state=self.state,
                decision="INCREMENT_TRANSIENT_COUNTER",
                explanation=f"Transient failure category {aggregate.value}",
            )

            if self._consecutive_internet_failures < config.MAX_INTERNET_FAILURES:
                self.set_state("INTERNET_UNAVAILABLE")
                time.sleep(config.CHECK_INTERVAL)
                continue

            # Extended outage threshold reached. Run soft auth check over LAN.
            log(
                f"Extended internet outage ({self._consecutive_internet_failures} consecutive failures). "
                "Performing soft auth check …"
            )
            session_expired = self.client.soft_auth_check()

            if session_expired:
                log("Soft auth check indicates session has expired — triggering re-login")
                log_diagnostic(
                    endpoint="LAN_SOFT_AUTH",
                    latency_ms=0.0,
                    result="EXPIRED",
                    retry_count=self._consecutive_internet_failures,
                    gw_reachable=True,
                    state=self.state,
                    decision="TRIGGER_RELOGIN",
                    explanation="Soft auth check confirmed Sophos session expired",
                )
                self.set_state("AUTHENTICATION_EXPIRED")
                self._consecutive_auth_failures += 1
                self._attempt_relogin()
                time.sleep(config.POST_LOGIN_GRACE)
            else:
                log(
                    "Soft auth check: session still valid — internet outage only, NOT reconnecting"
                )
                log_diagnostic(
                    endpoint="LAN_SOFT_AUTH",
                    latency_ms=0.0,
                    result="VALID",
                    retry_count=self._consecutive_internet_failures,
                    gw_reachable=True,
                    state=self.state,
                    decision="SUPPRESS_RELOGIN",
                    explanation="Soft auth check confirmed session still valid despite internet outage",
                )
                self._consecutive_internet_failures = 0
                self.set_state("INTERNET_UNAVAILABLE")
                time.sleep(config.CHECK_INTERVAL)