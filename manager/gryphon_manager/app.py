from __future__ import annotations

import os
import sys
import threading
import time
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


class CrashReporter:
    """Shows a dialog with details to copy when something unexpected goes wrong. The app keeps running."""

    def __init__(self, show_dialogs: bool = True):
        from PySide6.QtCore import QObject, Signal

        class Bridge(QObject):
            crashed = Signal(str)

        self.bridge = Bridge()
        self.bridge.crashed.connect(self._show)
        self.show_dialogs = show_dialogs
        self.window = None
        self.reports: list[str] = []
        self.dialog = None

    def report(self, details: str) -> None:
        self.bridge.crashed.emit(details)

    def _show(self, details: str) -> None:
        self.reports.append(details)
        if self.window is not None:
            try:
                self.window.hub.settings.save()
            except Exception:
                pass
        if not self.show_dialogs or len(self.reports) > 3 or (self.dialog is not None and self.dialog.isVisible()):
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices, QFontDatabase
        from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit
        from .core.applog import log_path
        from .ui.widgets import button, hbox, label, vbox
        dlg = QDialog(self.window)
        dlg.setWindowTitle("Something went wrong")
        dlg.resize(760, 480)
        text = QPlainTextEdit(details)
        text.setReadOnly(True)
        text.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        copied = label("", "dim")

        def copy():
            QApplication.clipboard().setText(details)
            copied.setText("Copied. Paste it into a message.")

        dlg.setLayout(vbox(
            label("Something went wrong", "h1"),
            label("The app hit an unexpected error, but it's still running and your settings and any recording "
                  "are safe. Press Copy details and send them on, so it can be fixed. The same details are in "
                  "the log file.", wrap=True),
            (text, 1),
            hbox(button("Copy details", copy, "primary"),
                 button("Open the log folder",
                        lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path().parent)))),
                 copied, None, button("Keep going", dlg.accept)),
            margins=(18, 18, 18, 18)))
        self.dialog = dlg
        dlg.show()


def create_window(hub=None, show_crash_dialogs: bool = True):
    from .core import applog
    from .ui.hub import Hub
    from .ui.main_window import MainWindow
    reporter = CrashReporter(show_crash_dialogs)
    applog.setup(reporter.report)
    hub = hub or Hub()
    win = MainWindow(hub)
    win.crash_reporter = reporter
    reporter.window = win
    hub.notice.connect(lambda level, text: applog.log.log(
        40 if level == "error" else 30 if level == "warn" else 20, "notice: %s", text.replace("\n", " | ")))
    hub.state_changed.connect(lambda: applog.log.info(
        "state: %s, source: %s %s%s", hub.state, hub.kind, hub.label,
        ", recording" if hub.recorder.active else ""))
    hub.alarm.connect(lambda ev: applog.log.warning("alarm %s: %s (%s)", "raised" if ev.raised else "cleared",
                                                    ev.name, ev.text))
    return win


def selftest(png: str | None) -> int:
    """Starts the real app on the simulator for a few seconds and checks it's alive. Used by CI on the built exe."""
    from PySide6.QtCore import QTimer
    log = []
    code = {"value": 1}
    try:
        app = create_app()
        win = create_window(show_crash_dialogs=False)
        win.hub.settings["first_run_done"] = True
        win.show()
        win.hub.connect_source("sim", mode="off", fault="none", parts="all", warmup=20.0)

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
                sim_frames, sim_packets = e.total_frames, e.radio.received
                log.append(f"frames {sim_frames}, radio packets {sim_packets}, devices {states}")
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
                from .core.cartest import STEPS, evaluate, suggest
                ct = win.views["cartest"]
                win.show_view("cartest")
                ct.inputs["ohms"] = "60"
                marks = []
                for step in STEPS:
                    if step.key in ("screen", "running", "ftmanager"):
                        result = "skip"
                    else:
                        result = "pass" if suggest(evaluate(step.key, e, ct.inputs)) == "pass" else "fail"
                    marks.append(f"{step.key}={result}")
                    ct._mark(result)
                    app.processEvents()
                folder = ct._save()
                app.processEvents()
                html = (folder / "report.html").read_text(encoding="utf-8") if (folder / "report.html").exists() else ""
                pdf = (folder / "report.pdf").stat().st_size if (folder / "report.pdf").exists() else 0
                logged = any(p.is_dir() and (p / "can.blf").exists() for p in folder.iterdir())
                report_ok = "Result: PASS" in html and pdf > 2000 and logged
                log.append(f"car test: {' '.join(marks)}; report.html {len(html)} chars, report.pdf {pdf} bytes, "
                           f"raw log {'saved' if logged else 'MISSING'}")
                win.hub.disconnect_source()
                from .core.recorder import list_sessions
                win.hub.connect_source("sim", mode="drive", parts="all")
                win.hub.start_recording("selftest")
                end = time.time() + 1.5
                while time.time() < end:
                    app.processEvents()
                win.hub.stop_recording()
                sessions = list_sessions()
                replay_ok = False
                if sessions:
                    win.hub.connect_source("replay", path=sessions[0]["path"], speed=8.0)
                    end = time.time() + 1.5
                    while time.time() < end:
                        app.processEvents()
                    replay_ok = win.hub.engine.total_frames > 100
                log.append(f"record and replay: {len(sessions)} session, replayed frames {win.hub.engine.total_frames}")
                crashes = win.crash_reporter.reports
                log.append(f"unexpected errors: {len(crashes)}")
                log.extend(crashes[:2])
                from .core.applog import log_path
                log.append(f"log file: {log_path().exists()}")
                ok = (sim_frames > 300 and sim_packets > 2 and not missing and report_ok and replay_ok
                      and not crashes and log_path().exists()
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

        QTimer.singleShot(3500, finish)
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
