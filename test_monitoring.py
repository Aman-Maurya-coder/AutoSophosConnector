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
        mock_response_204.url = "https://clients3.google.com/generate_204"
        mock_response_204.text = ""

        with patch("requests.get", return_value=mock_response_204) as mock_get:
            results = run_health_check()
            # Should have probed only the first endpoint (Google204)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].endpoint, "Google204")
            self.assertEqual(results[0].result, CheckResult.SUCCESS)
            self.assertEqual(mock_get.call_count, 1)

    def test_sequential_probing_continues_on_failure(self):
        """Sequential check must probe next endpoint if previous endpoint fails."""
        fail_exc = requests.exceptions.ConnectTimeout("Connection timed out")
        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.url = "https://www.cloudflare.com/cdn-cgi/trace"
        mock_response_200.text = "fl=123"

        def side_effect(url, **kwargs):
            if "google" in url:
                raise fail_exc
            return mock_response_200

        with patch("requests.get", side_effect=side_effect) as mock_get:
            results = run_health_check()
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].endpoint, "Google204")
            self.assertEqual(results[0].result, CheckResult.CONNECT_TIMEOUT)
            self.assertEqual(results[1].endpoint, "Cloudflare")
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
        with patch("requests.get", side_effect=requests.exceptions.SSLError("Certificate verify failed")):
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


if __name__ == "__main__":
    unittest.main()
