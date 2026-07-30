import pystray
from pystray import MenuItem as item
from PIL import Image
import threading
import os
import sys
from credential_ui import open_credential_window


class TrayUI:

    def __init__(self,state,on_exit=None):
        self.state_manager=state
        self.on_exit=on_exit
        self.last_state=state.state

        def asset_path(*parts):
            if getattr(sys,"frozen",False):
                base_path=getattr(sys,"_MEIPASS",os.path.dirname(sys.executable))
            else:
                base_path=os.path.dirname(os.path.abspath(__file__))
            return os.path.join(base_path,*parts)

        self.icons={
            "CONNECTED":Image.open(asset_path("assets","connected.png")),
            "CONNECTING":Image.open(asset_path("assets","connecting.png")),
            "RETRYING":Image.open(asset_path("assets","connecting.png")),
            "COLLEGE_WIFI_NOT_CONNECTED":Image.open(asset_path("assets","disconnected.png")),
            "COLLEGE_WIFI_NOT_AVAILABLE":Image.open(asset_path("assets","disconnected.png")),
            "DISCONNECTED":Image.open(asset_path("assets","disconnected.png")),
            "FAILED":Image.open(asset_path("assets","disconnected.png"))
        }

        self.icon=pystray.Icon(
            "Sophos",
            self.icons["DISCONNECTED"],
            "Sophos Wifi",
            menu=self.menu()
        )

        state.subscribe(self.state_change)

    def menu(self):
        return pystray.Menu(
            item(
                lambda item:
                "Status : "+self.state_manager.state,
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
            item(
                "Exit",
                self.exit
            )
        )

    def can_connect(self,item):
        return self.state_manager.state!="CONNECTED"

    def can_disconnect(self,item):
        return self.state_manager.state in {"CONNECTED","CONNECTING","RETRYING"}

    def connect(self):
        self.state_manager.connect()

    def disconnect(self):
        self.state_manager.disconnect()

    def toggle(self):
        if self.state_manager.state=="CONNECTED":
            self.state_manager.disconnect()
        else:
            self.state_manager.connect()

    def creds(self):
        def _open_and_refresh():
            open_credential_window()
            # S2: refresh the in-memory credential cache so the new
            # credentials are picked up without restarting the app.
            self.state_manager.client.refresh_credentials()
        threading.Thread(
            target=_open_and_refresh,
            daemon=True
        ).start()

    def state_change(self,new):
        previous=self.last_state
        self.last_state=new

        self.icon.icon=self.icons.get(
            new,
            self.icons["DISCONNECTED"]
        )
        self.icon.update_menu()

        if new!=previous and new in {"CONNECTED","DISCONNECTED"}:
            self.notify_state(new)

    def notify_state(self,state):
        message_map={
            "CONNECTED":"Connected to Sophos Wi-Fi",
            "DISCONNECTED":"Disconnected from Sophos Wi-Fi"
        }

        message=message_map.get(state)
        if not message:
            return

        try:
            self.icon.notify(message,"Sophos Wifi")
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
