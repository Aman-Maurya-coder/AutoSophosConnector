import threading

import time

import config

from wifi_client import WifiClient

from logger import log


class StateManager:


    def __init__(self):

        self.client=WifiClient()

        self.state="DISCONNECTED"

        self.running=False

        self.monitor_thread=None

        self.lock=threading.Lock()

        self.callbacks=[]

        self.is_connecting=False

        # Protected by self.lock. True once we've confirmed we are on the college
        # Wi-Fi; cleared on disconnect / resume / gateway-check failure.
        self._college_wifi_confirmed=False

        # B2: set by handle_system_resume so the monitor loop handles the retry
        # instead of racing a second _connect thread.
        self._wake_pending=False


    def subscribe(self,cb):

        self.callbacks.append(cb)


    def set_state(self,value):

        with self.lock:

            old=self.state

            self.state=value

        # B1: old is captured inside the lock; callbacks fire outside so they
        # don't re-enter set_state under the same lock.
        if old!=value:

            log("State "+value)


        for cb in self.callbacks:

            cb(value)


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

            # B2: Signal the monitor loop to handle the wake-retry instead of
            # spawning a competing _connect thread. If _connect is mid-flight,
            # it will see the flag on its next iteration.
            self._wake_pending=True

            # B6: guard the confirmed flag under the same lock.
            self._college_wifi_confirmed=False

        self.client.reset_session()


    def _connect(self):

        with self.lock:

            if getattr(self, "is_connecting", False):

                return

            self.is_connecting = True


        try:

            self.set_state("CONNECTING")

            if not self.client.is_college_wifi_connected():

                self.set_state("COLLEGE_WIFI_NOT_CONNECTED")

                return

            with self.lock:

                # B6: guard under lock
                self._college_wifi_confirmed=True

            if self.client.login():

                self.set_state("CONNECTED")

                self.start_monitor()

            else:

                self.set_state("FAILED")

        finally:

            with self.lock:

                self.is_connecting = False


    def disconnect(self):

        self.running=False

        with self.lock:

            self._college_wifi_confirmed=False

        if self.monitor_thread:

            self.monitor_thread.join(timeout=2)

        self.client.logout()

        self.set_state("DISCONNECTED")


    def start_monitor(self):

        if self.monitor_thread and self.monitor_thread.is_alive():

            return


        self.running=True

        self.monitor_thread=threading.Thread(

        target=self.monitor,

        # B3: daemon so the thread can't keep the process alive if the app
        # crashes or exits without calling disconnect() cleanly.
        daemon=True

        )

        self.monitor_thread.start()


    def monitor(self):

        last_tick=time.monotonic()

        while self.running:

            now=time.monotonic()

            sleep_gap=now-last_tick

            # B2: also treat an explicit wake signal as a forced retry.
            with self.lock:

                wake_pending=self._wake_pending

                self._wake_pending=False

            woke_from_sleep=wake_pending or sleep_gap>(config.CHECK_INTERVAL*2)

            last_tick=now

            if woke_from_sleep:

                log("Sleep/wake detected. Refreshing connection state")

                with self.lock:

                    # B6: guard under lock
                    self._college_wifi_confirmed=False

                self.client.reset_session()

            ok=self.client.check_connection()

            if ok and not woke_from_sleep:

                # Happy path: ping succeeded and we didn't just wake from sleep.
                # No need to verify gateway — stay CONNECTED and sleep until next tick.
                time.sleep(config.CHECK_INTERVAL)

                continue

            # Ping failed or we woke from sleep — need to verify and retry.
            with self.lock:

                confirmed=self._college_wifi_confirmed

            if not confirmed or not self.client.is_college_wifi_connected():

                with self.lock:

                    self._college_wifi_confirmed=False

                self.set_state("COLLEGE_WIFI_NOT_CONNECTED")

                time.sleep(config.CHECK_INTERVAL)

                continue

            self.set_state("RETRYING")

            if self.client.login():

                self.set_state("CONNECTED")

            else:

                self.set_state("FAILED")

            time.sleep(config.CHECK_INTERVAL)