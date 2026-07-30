import os
import sys
import threading
from PIL import Image
import pystray
from pystray import MenuItem as item

import config
from credential_ui import open_credential_window
from logger import get_current_mode, set_log_mode


class TrayUI:

    def __init__(self, state, on_exit=None):
        self.state_manager = state
        self.on_exit = on_exit
        self.last_state = state.state

        def asset_path(*parts):
            if getattr(sys, "frozen", False):
                base_path = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
            else:
                base_path = os.path.dirname(os.path.abspath(__file__))
            return os.path.join(base_path, *parts)

        self.icons = {
            # Confirmed authenticated + internet reachable.
            "CONNECTED":                  Image.open(asset_path("assets", "connected.png")),

            # Initial login in progress.
            "CONNECTING":                 Image.open(asset_path("assets", "connecting.png")),

            # Running health check probes.
            "VERIFYING":                  Image.open(asset_path("assets", "connecting.png")),

            # Internet probes are failing but gateway is reachable (transient).
            "INTERNET_UNAVAILABLE":       Image.open(asset_path("assets", "connecting.png")),

            # Portal redirect detected — session has expired.
            "AUTHENTICATION_EXPIRED":     Image.open(asset_path("assets", "disconnected.png")),

            # Re-login attempt in progress.
            "RETRYING_LOGIN":             Image.open(asset_path("assets", "connecting.png")),

            # Gateway unreachable — wrong Wi-Fi or no Wi-Fi.
            "COLLEGE_WIFI_NOT_CONNECTED": Image.open(asset_path("assets", "disconnected.png")),

            # Legacy state kept for back-compat.
            "COLLEGE_WIFI_NOT_AVAILABLE": Image.open(asset_path("assets", "disconnected.png")),

            # User manually disconnected.
            "DISCONNECTED":               Image.open(asset_path("assets", "disconnected.png")),

            # Login failed outright.
            "FAILED":                     Image.open(asset_path("assets", "disconnected.png")),
        }

        self.icon = pystray.Icon(
            "Sophos",
            self.icons["DISCONNECTED"],
            "Sophos Wifi",
            menu=self.menu()
        )

        state.subscribe(self.state_change)

    def menu(self):
        return pystray.Menu(
            item(
                lambda item: "Status : " + self.state_manager.state,
                None,
                enabled=False
            ),
            item(
                "Connect",
                self.connect,
                enabled=self.can_connect
            ),
            item(
                "Disconnect",
                self.disconnect,
                enabled=self.can_disconnect
            ),
            item(
                "Change Credentials",
                self.creds
            ),
            pystray.Menu.SEPARATOR,
            item(
                "Debug Mode",
                self.toggle_debug,
                checked=lambda item: get_current_mode() == config.MODE_DEBUG
            ),
            item(
                "Diagnostic Mode",
                self.toggle_diagnostic,
                checked=lambda item: get_current_mode() == config.MODE_DIAGNOSTIC
            ),
            pystray.Menu.SEPARATOR,
            item(
                "Exit",
                self.exit
            )
        )

    def can_connect(self, item):
        return self.state_manager.state not in {
            "CONNECTED",
            "CONNECTING",
            "VERIFYING",
            "RETRYING_LOGIN",
        }

    def can_disconnect(self, item):
        return self.state_manager.state in {
            "CONNECTED",
            "CONNECTING",
            "VERIFYING",
            "INTERNET_UNAVAILABLE",
            "AUTHENTICATION_EXPIRED",
            "RETRYING_LOGIN",
        }

    def toggle_debug(self, icon, item):
        if get_current_mode() == config.MODE_DEBUG:
            set_log_mode(config.MODE_PRODUCTION)
        else:
            set_log_mode(config.MODE_DEBUG)
        self.icon.update_menu()

    def toggle_diagnostic(self, icon, item):
        if get_current_mode() == config.MODE_DIAGNOSTIC:
            set_log_mode(config.MODE_PRODUCTION)
        else:
            set_log_mode(config.MODE_DIAGNOSTIC)
        self.icon.update_menu()

    def connect(self):
        self.state_manager.connect()

    def disconnect(self):
        self.state_manager.disconnect()

    def toggle(self):
        if self.state_manager.state == "CONNECTED":
            self.state_manager.disconnect()
        else:
            self.state_manager.connect()

    def creds(self):
        def _open_and_refresh():
            open_credential_window()
            self.state_manager.client.refresh_credentials()
        threading.Thread(
            target=_open_and_refresh,
            daemon=True
        ).start()

    def state_change(self, new):
        previous = self.last_state
        self.last_state = new

        self.icon.icon = self.icons.get(
            new,
            self.icons["DISCONNECTED"]
        )
        self.icon.update_menu()

        if new != previous and new in {
            "CONNECTED",
            "DISCONNECTED",
            "AUTHENTICATION_EXPIRED",
            "FAILED",
        }:
            self.notify_state(new)

    def notify_state(self, state):
        message_map = {
            "CONNECTED":              "Connected to Sophos Wi-Fi",
            "DISCONNECTED":           "Disconnected from Sophos Wi-Fi",
            "AUTHENTICATION_EXPIRED": "Sophos session expired — reconnecting …",
            "FAILED":                 "Sophos login failed",
        }

        message = message_map.get(state)
        if not message:
            return

        try:
            self.icon.notify(message, "Sophos Wifi")
        except Exception:
            pass

    def exit(self):
        if self.on_exit:
            try:
                self.on_exit()
            except Exception:
                pass

        self.state_manager.disconnect()
        self.icon.stop()

    def run(self):
        self.icon.run()
