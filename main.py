from state_manager import StateManager

from tray import TrayUI

import threading

from credentials import load_credentials

from credential_ui import open_credential_window

from startup import add_to_startup

from power_events import PowerEventListener
from logger import log


def main():

    log("AutoSophosWifiConnector starting up")

    threading.Thread(target=add_to_startup,daemon=True).start()


    username,password=load_credentials()


    if not username or not password:

        saved=open_credential_window()

        if not saved:

            return


        username,password=load_credentials()

        if not username or not password:

            return


    state=StateManager()

    power_listener=PowerEventListener(state.handle_system_resume)

    power_listener.start()

    tray=TrayUI(state,on_exit=power_listener.stop)


    state.connect()


    tray.run()


if __name__=="__main__":

    main()