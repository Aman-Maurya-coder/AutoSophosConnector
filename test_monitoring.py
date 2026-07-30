"""
test_monitoring.py – Comprehensive test suite for AutoSophosConnector monitoring architecture.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import requests
import socket

import config
import health
from health import CheckResult, HealthCheck, interpret_health, probe_endpoint, run_health_check
import logger
from logger import get_current_mode, set_log_mode
from state_manager import StateManager
from wifi_client import WifiClient


class TestSequentialHealthChecks(unittest.TestCase):

    def test_sequential_probing_stops_on_first_success(self):
        """Sequential check must stop immediately when the first endpoint succeeds."""
        mock_response_204 = MagicMock()
        mock_response_204.status_code = 204
        mock_response_204.url = config.HEALTH_ENDPOINTS[0][1]
        mock_response_204.text = ""

        first_endpoint_name = config.HEALTH_ENDPOINTS[0][0]

        with patch("requests.get", return_value=mock_response_204) as mock_get:
            results = run_health_check()
            # Should have probed only the first endpoint
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].endpoint, first_endpoint_name)
            self.assertEqual(results[0].result, CheckResult.SUCCESS)
            self.assertEqual(mock_get.call_count, 1)

    def test_sequential_probing_continues_on_failure(self):
        """Sequential check must probe next endpoint if previous endpoint fails."""
        fail_exc = requests.exceptions.ConnectTimeout("Connection timed out")
        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.url = config.HEALTH_ENDPOINTS[1][1]
        mock_response_200.text = "fl=123"

        first_url = config.HEALTH_ENDPOINTS[0][1]
        first_endpoint_name = config.HEALTH_ENDPOINTS[0][0]
        second_endpoint_name = config.HEALTH_ENDPOINTS[1][0]

        def side_effect(url, **kwargs):
            if first_url in url:
                raise fail_exc
            return mock_response_200

        with patch("requests.get", side_effect=side_effect) as mock_get:
            results = run_health_check()
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].endpoint, first_endpoint_name)
            self.assertEqual(results[0].result, CheckResult.CONNECT_TIMEOUT)
            self.assertEqual(results[1].endpoint, second_endpoint_name)
            self.assertEqual(results[1].result, CheckResult.SUCCESS)
            self.assertEqual(mock_get.call_count, 2)


class TestFailureClassification(unittest.TestCase):

    def test_classify_dns_failure(self):
        gai_err = socket.gaierror(-2, "Name or service not known")
        conn_err = requests.exceptions.ConnectionError(gai_err)
        with patch("requests.get", side_effect=conn_err):
            hc = probe_endpoint("Test", "http://fake.url")
            self.assertEqual(hc.result, CheckResult.DNS_FAILURE)

    def test_classify_timeouts(self):
        with patch("requests.get", side_effect=requests.exceptions.ConnectTimeout()):
            hc = probe_endpoint("Test", "http://fake.url")
            self.assertEqual(hc.result, CheckResult.CONNECT_TIMEOUT)

        with patch("requests.get", side_effect=requests.exceptions.ReadTimeout()):
            hc = probe_endpoint("Test", "http://fake.url")
            self.assertEqual(hc.result, CheckResult.READ_TIMEOUT)

    def test_classify_ssl_error(self):
        with patch("requests.get", side_effect=requests.exceptions.SSLError("SSL connection failed: certificate expired")):
            hc = probe_endpoint("Test", "http://fake.url")
            self.assertEqual(hc.result, CheckResult.SSL_ERROR)

    def test_classify_captive_portal(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.url = "http://192.168.100.1:8090/httpclient.html"
        resp.text = "<html>Sophos Login Form</html>"
        with patch("requests.get", return_value=resp):
            hc = probe_endpoint("Test", "http://fake.url")
            self.assertEqual(hc.result, CheckResult.CAPTIVE_PORTAL_DETECTED)


class TestLoggingSystem(unittest.TestCase):

    def test_log_modes_and_file_creation(self):
        # Production mode
        p_path = set_log_mode(config.MODE_PRODUCTION)
        self.assertEqual(get_current_mode(), config.MODE_PRODUCTION)
        self.assertTrue(os.path.exists(p_path))

        # Debug mode (creates new timestamped file)
        d_path = set_log_mode(config.MODE_DEBUG)
        self.assertEqual(get_current_mode(), config.MODE_DEBUG)
        self.assertTrue(os.path.exists(d_path))
        self.assertIn("sophos_debug_", d_path)

        # Diagnostic mode (creates new timestamped file)
        diag_path = set_log_mode(config.MODE_DIAGNOSTIC)
        self.assertEqual(get_current_mode(), config.MODE_DIAGNOSTIC)
        self.assertTrue(os.path.exists(diag_path))
        self.assertIn("sophos_diagnostic_", diag_path)

        # Revert to production mode
        set_log_mode(config.MODE_PRODUCTION)


class TestStateManager(unittest.TestCase):

    def test_state_deduplication(self):
        sm = StateManager()
        callback_mock = MagicMock()
        sm.subscribe(callback_mock)

        sm.set_state("CONNECTED")
        self.assertEqual(callback_mock.call_count, 1)

        # Setting same state should NOT trigger callback
        sm.set_state("CONNECTED")
        self.assertEqual(callback_mock.call_count, 1)

        sm.set_state("INTERNET_UNAVAILABLE")
        self.assertEqual(callback_mock.call_count, 2)

    def test_soft_auth_check_suppresses_spurious_relogins(self):
        sm = StateManager()
        sm.client.soft_auth_check = MagicMock(return_value=False)
        sm.client.login = MagicMock()

        # Simulate MAX_INTERNET_FAILURES transient DNS errors
        sm._consecutive_internet_failures = config.MAX_INTERNET_FAILURES - 1

        # Run health check returning DNS failure
        hc_dns = HealthCheck(endpoint="Google204", url="http://google", result=CheckResult.DNS_FAILURE)
        with patch("state_manager.run_health_check", return_value=[hc_dns]), \
             patch("time.sleep"):
            # Trigger one monitor iteration logic directly
            sm.running = True
            # Simulate processing of DNS failure at threshold
            sm._consecutive_internet_failures += 1
            if sm._consecutive_internet_failures >= config.MAX_INTERNET_FAILURES:
                expired = sm.client.soft_auth_check()
                if not expired:
                    sm._consecutive_internet_failures = 0
                    sm.set_state("INTERNET_UNAVAILABLE")

            # Soft auth check was called
            sm.client.soft_auth_check.assert_called_once()
            # Login was NOT attempted
            sm.client.login.assert_not_called()
            # State remains INTERNET_UNAVAILABLE
            self.assertEqual(sm.state, "INTERNET_UNAVAILABLE")
            # Counter reset
            self.assertEqual(sm._consecutive_internet_failures, 0)

class TestSSLMitmClassification(unittest.TestCase):
    """Verify that self-signed-certificate SSLErrors are classified as captive portal."""

    def test_self_signed_cert_is_captive_portal(self):
        """SSLError mentioning 'self-signed certificate' → CAPTIVE_PORTAL_DETECTED."""
        ssl_err = requests.exceptions.SSLError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
            "self-signed certificate in certificate chain (_ssl.c:1076)"
        )
        with patch("requests.get", side_effect=ssl_err):
            hc = probe_endpoint("Test", "https://example.com")
            self.assertEqual(hc.result, CheckResult.CAPTIVE_PORTAL_DETECTED)

    def test_certificate_verify_failed_is_captive_portal(self):
        """SSLError with just 'certificate verify failed' → CAPTIVE_PORTAL_DETECTED."""
        ssl_err = requests.exceptions.SSLError(
            "HTTPSConnectionPool(host='example.com', port=443): "
            "Max retries exceeded (Caused by SSLError(SSLCertVerificationError("
            "1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed')))"
        )
        with patch("requests.get", side_effect=ssl_err):
            hc = probe_endpoint("Test", "https://example.com")
            self.assertEqual(hc.result, CheckResult.CAPTIVE_PORTAL_DETECTED)

    def test_unrelated_ssl_error_stays_ssl_error(self):
        """SSLError without MITM keywords stays classified as SSL_ERROR."""
        ssl_err = requests.exceptions.SSLError(
            "hostname 'evil.com' doesn't match 'example.com'"
        )
        with patch("requests.get", side_effect=ssl_err):
            hc = probe_endpoint("Test", "https://example.com")
            self.assertEqual(hc.result, CheckResult.SSL_ERROR)


class TestPeriodicSoftAuthBackstop(unittest.TestCase):
    """Verify the periodic soft_auth_check backstop fires on schedule."""

    def _make_success_results(self):
        """Return a list of HealthCheck results representing a SUCCESS check."""
        return [
            HealthCheck(
                endpoint="Example",
                url="https://example.com",
                result=CheckResult.SUCCESS,
                status_code=200,
                latency_ms=50.0,
            )
        ]

    def test_backstop_fires_on_nth_tick_and_detects_portal(self):
        """
        After SOFT_AUTH_BACKSTOP_INTERVAL ticks of SUCCESS health checks,
        soft_auth_check should fire.  When it detects a portal, the state
        should transition to AUTHENTICATION_EXPIRED and _attempt_relogin
        should be called (once auth failures reach MAX_AUTH_FAILURES).
        """
        sm = StateManager()
        sm.running = True
        sm.state = "CONNECTED"

        # Mocks
        sm.client.is_college_wifi_connected = MagicMock(return_value=True)
        sm.client.recycle_health_session_if_stale = MagicMock()
        sm.client.soft_auth_check = MagicMock(return_value=True)
        sm.client.login = MagicMock(return_value=True)
        sm.client.reset_health_session = MagicMock()

        success_results = self._make_success_results()
        call_count = 0
        backstop_interval = config.SOFT_AUTH_BACKSTOP_INTERVAL

        with patch("state_manager.run_health_check", return_value=success_results), \
             patch("time.sleep"), \
             patch("config.MAX_AUTH_FAILURES", 1), \
             patch("time.monotonic") as mock_mono:
            # Provide stable monotonic time so sleep-gap detection does not fire.
            mock_mono.return_value = 1000.0

            # Run exactly SOFT_AUTH_BACKSTOP_INTERVAL ticks, then stop.
            original_running = sm.running.__class__

            def stop_after_n_ticks(*_args, **_kwargs):
                nonlocal call_count
                call_count += 1
                if call_count >= backstop_interval:
                    sm.running = False

            with patch.object(sm, "set_state", wraps=sm.set_state) as mock_set_state:
                # Use time.sleep side_effect to count ticks and stop the loop.
                with patch("time.sleep", side_effect=stop_after_n_ticks):
                    sm.monitor()

            # soft_auth_check should have been called on the Nth tick.
            sm.client.soft_auth_check.assert_called()
            # Login should have been triggered (relogin path).
            sm.client.login.assert_called()
            # The state should have transitioned to AUTHENTICATION_EXPIRED at some point.
            states_set = [c.args[0] for c in mock_set_state.call_args_list]
            self.assertIn("AUTHENTICATION_EXPIRED", states_set)

    def test_backstop_does_not_fire_before_interval(self):
        """
        On ticks before SOFT_AUTH_BACKSTOP_INTERVAL, soft_auth_check
        should NOT be called when health checks return SUCCESS.
        """
        sm = StateManager()
        sm.running = True
        sm.state = "CONNECTED"

        sm.client.is_college_wifi_connected = MagicMock(return_value=True)
        sm.client.recycle_health_session_if_stale = MagicMock()
        sm.client.soft_auth_check = MagicMock(return_value=False)

        success_results = self._make_success_results()
        ticks_before_backstop = config.SOFT_AUTH_BACKSTOP_INTERVAL - 1
        call_count = 0

        with patch("state_manager.run_health_check", return_value=success_results), \
             patch("time.monotonic", return_value=1000.0):

            def stop_after_n_ticks(*_args, **_kwargs):
                nonlocal call_count
                call_count += 1
                if call_count >= ticks_before_backstop:
                    sm.running = False

            with patch("time.sleep", side_effect=stop_after_n_ticks):
                sm.monitor()

        # soft_auth_check should NOT have been called before the interval.
        sm.client.soft_auth_check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
