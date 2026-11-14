from __future__ import annotations

import faulthandler
import logging
import platform
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .. import __version__
from .paths import user_home

log = logging.getLogger("gryphon")
_state = {"path": None, "fault_file": None, "on_crash": None, "seen": {}}


def log_path() -> Path:
    d = user_home() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "gryphon-manager.log"


def recent_log(lines: int = 60) -> str:
    try:
        text = log_path().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(text[-lines:])


def crash_details(exc_type, exc, tb, where: str = "") -> str:
    trace = "".join(traceback.format_exception(exc_type, exc, tb))
    return (f"Gryphon Manager {__version__}\n{platform.platform()}, Python {platform.python_version()}\n"
            f"{where}\n\n{trace}\nLast log lines:\n{recent_log(40)}")


def handle_exception(exc_type, exc, tb, where: str = "main thread") -> None:
    """Log an unexpected error once per distinct place, and tell the UI. Never raises."""
    try:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        last = traceback.extract_tb(tb)[-1] if tb else None
        key = (exc_type.__name__, last.filename if last else "", last.lineno if last else 0)
        count = _state["seen"].get(key, 0) + 1
        _state["seen"][key] = count
        if count == 1:
            details = crash_details(exc_type, exc, tb, where)
            log.error("Unexpected error in %s\n%s", where, "".join(traceback.format_exception(exc_type, exc, tb)))
            if _state["on_crash"]:
                _state["on_crash"](details)
        elif count in (10, 100, 1000):
            log.error("The same error (%s at %s:%s) has now happened %d times", *key, count)
    except Exception:
        pass


def setup(on_crash=None) -> Path:
    """File log in Documents/Gryphon Manager/logs, plus hooks so nothing fails silently."""
    path = log_path()
    _state["on_crash"] = on_crash
    _state["seen"] = {}
    if _state["path"] != path:
        for h in list(log.handlers):
            log.removeHandler(h)
            h.close()
        handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False
        _state["path"] = path
        try:
            if _state["fault_file"] is not None:
                faulthandler.disable()
                _state["fault_file"].close()
            _state["fault_file"] = open(path.with_name("hard-crash.log"), "a", encoding="utf-8")
            faulthandler.enable(_state["fault_file"])
        except (OSError, ValueError, RuntimeError):
            pass
    sys.excepthook = handle_exception
    threading.excepthook = lambda a: handle_exception(a.exc_type, a.exc_value, a.exc_traceback,
                                                      f"thread {a.thread.name if a.thread else '?'}")
    log.info("Started Gryphon Manager %s on %s (Python %s)", __version__, platform.platform(),
             platform.python_version())
    return path
