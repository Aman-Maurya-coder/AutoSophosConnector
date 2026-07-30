import logging
import os
import sys

def get_log_path():
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        log_path = os.path.join(exe_dir, "sophos.log")
        # Fall back to %APPDATA% only if the exe dir is not writable
        # (e.g. installed to Program Files without admin rights).
        try:
            with open(log_path, "a"):
                pass
            return log_path
        except OSError:
            app_data = os.environ.get("APPDATA", exe_dir)
            log_dir = os.path.join(app_data, "AutoSophosWifi")
            os.makedirs(log_dir, exist_ok=True)
            return os.path.join(log_dir, "sophos.log")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "sophos.log")

logging.basicConfig(
    filename=get_log_path(),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def log(msg, level="INFO"):
    if level == "INFO":
        logging.info(msg)
    elif level == "ERROR":
        logging.error(msg)
    elif level == "DEBUG":
        logging.debug(msg)