import requests

import time

import socket

import config

from credentials import load_credentials

from logger import log


class WifiClient:


    def __init__(self):

        self.session=requests.Session()

        # S2: cache credentials once at startup to avoid a blocking keyring
        # IPC call on every login/logout invocation.
        self._username,self._password=load_credentials()


    def refresh_credentials(self):
        """Re-read credentials from keyring (call after the user saves new ones)."""
        self._username,self._password=load_credentials()


    def reset_session(self):

        self.session=requests.Session()




    def is_college_wifi_connected(self):

        if not config.SSID_LOCK_ENABLED:

            return True


        target_gw = (config.COLLEGE_GATEWAY_IP or "").strip()

        if not target_gw:

            return True


        # Probe the Sophos captive-portal port with a raw TCP socket.
        # connect_ex never reads the Wi-Fi SSID — no location-access trigger.
        # err == 0          : TCP handshake succeeded (portal is up)
        # err == 10061      : WSAECONNREFUSED — host reachable, port not listening
        # Anything else     : gateway unreachable (wrong network / no network)
        try:

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            sock.settimeout(1.5)

            err = sock.connect_ex((target_gw, 8090))

            sock.close()

            reachable = err in (0, 10061)  # 0=connected, 10061=WSAECONNREFUSED

            if not reachable:

                log(f"College gateway {target_gw}:8090 unreachable (wsa_err={err})")

            return reachable

        except Exception as e:

            log(f"Gateway reachability check failed: {e}", level="ERROR")

            return False


    def login(self):

        # Use cached credentials; caller must call refresh_credentials() if they change.
        username,password=self._username,self._password

        if not username or not password:

            log("Missing credentials")

            return False


        payload={

        "mode":191,

        "username":username,

        "password":password,

        "a":int(time.time()*1000),

        "producttype":0

        }


        try:

            r=self.session.post(

            config.LOGIN_URL,

            headers=config.HEADERS,

            data=payload,

            # S1: LOGIN_URL is plain HTTP so verify=False was misleading dead code.
            timeout=10

            )

            log("Login request sent")

            return r.status_code==200

        except Exception as e:

            log(f"Login request failed: {e}", level="ERROR")

            return False


    def logout(self):

        username=self._username

        if not username:

            return


        payload={

        "mode":193,

        "username":username,

        "a":int(time.time()*1000),

        "producttype":0

        }


        try:

            self.session.post(

            config.LOGOUT_URL,

            headers=config.HEADERS,

            data=payload,

            # S1: LOGOUT_URL is plain HTTP — verify=False was misleading dead code.

            )

            log("Logout success")

        except:

            pass


    def check_connection(self):

        try:

            # B4: use self.session to reuse the connection pool, not bare requests.get.
            r=self.session.get(

            config.CHECK_URL,

            timeout=5

            )

            if r.status_code==204:
                return True
            log(f"Connection check failed with status {r.status_code}")
            return False

        except Exception as e:
            log(f"Connection check exception: {e}", level="ERROR")

            return False