"""
logger.py – Application logging system supporting Production, Debug, and Diagnostic modes.

Modes:
  PRODUCTION  - Default mode. Logs only meaningful application events
                (startup, state changes, login success/failure, recovery, errors).
                Suppresses routine successful health checks and third-party
                library debug messages (urllib3, requests, PIL, etc.).
  DEBUG       - Logs complete HTTP diagnostics, endpoint timings, raw tracebacks,
                and enables third-party library verbose output. Creates a new
                timestamped log file when activated.
  DIAGNOSTIC  - Extends DEBUG mode by recording structured runtime decisions
                (endpoint tested, latency, exception type, retry count, gateway
                reachability, monitor state, and reasoning for actions). Creates
                a new timestamped log file when activated.
"""

import datetime
import logging
import os
import sys
from typing import Optional

import config

_current_mode = config.MODE_PRODUCTION
_current_log_path = None
_file_handler = None


def get_base_log_dir() -> str:
    """Return the base directory for log file storage."""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        log_path = os.path.join(exe_dir, "sophos.log")
        try:
            with open(log_path, "a"):
                pass
            return exe_dir
        except OSError:
            app_data = os.environ.get("APPDATA", exe_dir)
            log_dir = os.path.join(app_data, "AutoSophosWifi")
            os.makedirs(log_dir, exist_ok=True)
            return log_dir
    return os.path.dirname(os.path.abspath(__file__))


def _get_log_path_for_mode(mode: str) -> str:
    base_dir = get_base_log_dir()
    if mode == config.MODE_PRODUCTION:
        return os.path.join(base_dir, "sophos.log")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if mode == config.MODE_DEBUG:
        return os.path.join(base_dir, f"sophos_debug_{timestamp}.log")
    if mode == config.MODE_DIAGNOSTIC:
        return os.path.join(base_dir, f"sophos_diagnostic_{timestamp}.log")
    return os.path.join(base_dir, "sophos.log")


def get_current_mode() -> str:
    return _current_mode


def get_log_path() -> str:
    global _current_log_path
    if not _current_log_path:
        _current_log_path = _get_log_path_for_mode(_current_mode)
    return _current_log_path


def log(msg: str, level: str = "INFO"):
    """
    Standard logger call for application events.

    In PRODUCTION mode, DEBUG level calls are suppressed.
    """
    if level == "DEBUG" and _current_mode == config.MODE_PRODUCTION:
        return

    if level == "INFO":
        logging.info(msg)
    elif level == "ERROR":
        logging.error(msg)
    elif level == "WARNING":
        logging.warning(msg)
    elif level == "DEBUG":
        logging.debug(msg)


def log_debug(msg: str):
    """Log detailed debug information if mode is DEBUG or DIAGNOSTIC."""
    if _current_mode in (config.MODE_DEBUG, config.MODE_DIAGNOSTIC):
        logging.debug(f"[DEBUG] {msg}")


def log_diagnostic(
    endpoint: str,
    latency_ms: float,
    result: str,
    exc_type: Optional[str] = None,
    retry_count: int = 0,
    gw_reachable: bool = True,
    state: str = "",
    decision: str = "",
    explanation: str = "",
):
    """
    Log structured diagnostic runtime decision information.
    Active in DIAGNOSTIC and DEBUG modes.
    """
    if _current_mode in (config.MODE_DEBUG, config.MODE_DIAGNOSTIC):
        diag_msg = (
            f"[DIAGNOSTIC] endpoint={endpoint} latency={latency_ms:.0f}ms result={result} "
            f"exc={exc_type or 'None'} retry_count={retry_count} gw_reachable={gw_reachable} "
            f"state={state} decision={decision} | explanation: {explanation}"
        )
        logging.info(diag_msg)


def set_log_mode(mode: str) -> str:
    """
    Switch the logging mode.

    When switching to DEBUG or DIAGNOSTIC, a new timestamped log file is created.
    Returns the path to the active log file.
    """
    global _current_mode, _current_log_path, _file_handler

    if mode not in (config.MODE_PRODUCTION, config.MODE_DEBUG, config.MODE_DIAGNOSTIC):
        mode = config.MODE_PRODUCTION

    _current_mode = mode
    new_log_path = _get_log_path_for_mode(mode)
    _current_log_path = new_log_path

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Remove existing file handler if attached
    if _file_handler is not None:
        root_logger.removeHandler(_file_handler)
        try:
            _file_handler.close()
        except Exception:
            pass

    _file_handler = logging.FileHandler(new_log_path, encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    root_logger.addHandler(_file_handler)

    # Silence or enable third-party library logging
    third_party = ["urllib3", "requests", "PIL", "Pillow", "pystray"]
    if mode == config.MODE_PRODUCTION:
        for name in third_party:
            logging.getLogger(name).setLevel(logging.WARNING)
    else:
        for name in third_party:
            logging.getLogger(name).setLevel(logging.DEBUG)

    log(f"Logging mode set to {mode} (log_file={os.path.basename(new_log_path)})", level="INFO")
    return new_log_path


# Initialize with default PRODUCTION mode after functions are defined
set_log_mode(config.MODE_PRODUCTION)