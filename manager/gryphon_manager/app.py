from __future__ import annotations

import os
import sys
import threading
import traceback
from pathlib import Path

from . import APP_NAME, __version__


def pick_font() -> str:
    from PySide6.QtGui import QFontDatabase
    families = set(QFontDatabase.families())
    for name in ("Segoe UI", "Inter", "SF Pro Text", "Helvetica Neue", "DejaVu Sans"):
        if name in families:
            return name
    return QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()


def apply_text_size(app, base: int) -> None:
    from . import theme
    app.setStyleSheet(theme.stylesheet(pick_font(), base))


def create_app(argv=None):
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    import pyqtgraph as pg
    from . import theme
    from .core.paths import asset_path
    app = QApplication.instance() or QApplication(argv or sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    from .core.settings import Settings
    apply_text_size(app, int(Settings().get("text_size", 13) or 13))
    icon = asset_path("icon.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    pg.setConfigOptions(antialias=True, background=theme.PANEL, foreground=theme.TEXT_DIM)
    return app


def create_window(hub=None):
    from .ui.hub import Hub
    from .ui.main_window import MainWindow
    hub = hub or Hub()
    return MainWindow(hub)


def selftest(png: str | None) -> int:
    """Starts the real app on the simulator for a few seconds and checks it's alive. Used by CI on the built exe."""
    from PySide6.QtCore import QTimer
    log = []
    code = {"value": 1}
    try:
        app = create_app()
        win = create_window()
        win.hub.settings["first_run_done"] = True
        win.show()
        win.hub.connect_source("sim", mode="drive", fault="none", parts="all")

        def finish():
            try:
                e = win.hub.engine
                from .ui.main_window import NAV
                for key, _ in NAV:
                    win.show_view(key)
                    app.processEvents()
                win.show_view("garage")
                app.processEvents()
                states = {k: d.status for k, d in e.devices.items()}
                log.append(f"version {__version__}")
                log.append(f"frames {e.total_frames}, radio packets {e.radio.received}, devices {states}")
                import importlib
                missing = []
                for mod in ("can.interfaces.pcan", "can.interfaces.pcan.basic", "can.interfaces.slcan",
                            "can.interfaces.virtual", "can.io.blf", "can.io.asc", "serial.tools.list_ports",
                            "cantools", "yaml"):
                    try:
                        importlib.import_module(mod)
                    except ModuleNotFoundError as exc:
                        missing.append(f"{mod}: {exc}")
                    except Exception as exc:
                        log.append(f"note: importing {mod} raised {type(exc).__name__}: {exc}")
                log.append(f"bundled modules missing: {missing or 'none'}")
                import queue as _q
                from .core.sources import CanSource
                probe_q = _q.Queue()
                probe = CanSource(probe_q, "pcan", "PCAN_USBBUS1")
                probe.start()
                probe.join(5)
                while not probe_q.empty():
                    kind, payload = probe_q.get()
                    if kind in ("error", "opened"):
                        log.append(f"PCAN probe ({kind}): " + str(payload).replace(chr(10), " | "))
                ok = (e.total_frames > 300 and e.radio.received > 2 and not missing
                      and all(v == "green" for v in states.values()))
                log.append("SELFTEST PASS" if ok else "SELFTEST FAIL")
                if png:
                    win.grab().save(png)
                code["value"] = 0 if ok else 2
            except Exception:
                log.append(traceback.format_exc())
                code["value"] = 3
            win.hub.shutdown()
            app.quit()

        QTimer.singleShot(4500, finish)
        app.exec()
    except Exception:
        log.append(traceback.format_exc())
        code["value"] = 4
    try:
        Path("selftest.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    except OSError:
        pass
    print("\n".join(log))
    return code["value"]


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(__version__)
        return 0
    if "--selftest" in argv:
        i = argv.index("--selftest")
        return selftest(argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("-") else None)
    app = create_app(argv)
    win = create_window()
    hub = win.hub
    win.show()
    if not hub.settings["first_run_done"]:
        win.show_welcome()
    if hub.settings["check_updates"]:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2500, lambda: win.views["settings"].check_now(quiet=True))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
