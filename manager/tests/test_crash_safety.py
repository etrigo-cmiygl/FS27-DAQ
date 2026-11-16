import json
import sys
import threading
import time

from gryphon_manager.core import applog
from gryphon_manager.core.settings import Settings


def test_settings_survive_a_broken_or_half_written_file(gryphon_home):
    s = Settings()
    s["driver"] = "first"
    s.save()
    s["driver"] = "second"
    s["pdm_ids"] = "0x500"
    s.save()
    assert Settings()["driver"] == "second"
    assert json.loads(s.path.with_suffix(".bak").read_text(encoding="utf-8"))["driver"] == "first"
    s.path.write_text('{"driver": "sec', encoding="utf-8")
    recovered = Settings()
    assert recovered["driver"] == "first" and recovered["allow_transmit"] is False
    recovered["driver"] = "third"
    recovered.save()
    assert Settings()["driver"] == "third"
    assert json.loads(s.path.with_suffix(".bak").read_text(encoding="utf-8"))["driver"] == "first"
    s.path.write_text("[]", encoding="utf-8")
    s.path.with_suffix(".bak").unlink()
    assert Settings()["driver"] == ""


def test_errors_are_logged_once_with_details(gryphon_home):
    got = []
    old_hook, old_thread_hook = sys.excepthook, threading.excepthook
    try:
        path = applog.setup(got.append)
        assert path.parent == gryphon_home / "logs"

        def boom():
            raise ValueError("oil sensor exploded")

        for _ in range(12):
            try:
                boom()
            except ValueError:
                sys.excepthook(*sys.exc_info())
        t = threading.Thread(target=lambda: 1 / 0, name="reader")
        t.start()
        t.join()
        for h in applog.log.handlers:
            h.flush()
        text = path.read_text(encoding="utf-8")
        assert len(got) == 2
        assert "Gryphon Manager 2." in got[0] and "ValueError: oil sensor exploded" in got[0] and "boom" in got[0]
        assert "thread reader" in got[1] and "ZeroDivisionError" in got[1]
        assert text.count("Unexpected error in main thread") == 1 and "has now happened 10 times" in text
        assert "Started Gryphon Manager" in text
    finally:
        sys.excepthook, threading.excepthook = old_hook, old_thread_hook


def test_crash_dialog_appears_and_the_app_keeps_running(gryphon_home, tmp_path):
    from pathlib import Path

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QPlainTextEdit

    from gryphon_manager.app import create_app, create_window
    from gryphon_manager.ui.hub import Hub
    old_hook, old_thread_hook = sys.excepthook, threading.excepthook
    app = create_app()
    cfg = tmp_path / "channels.yaml"
    cfg.write_text((Path(__file__).resolve().parents[1] / "config" / "channels.yaml").read_text(encoding="utf-8"),
                   encoding="utf-8")
    settings = Settings()
    settings["first_run_done"] = True
    win = create_window(Hub(settings, cfg))
    try:
        win.show()
        win.hub.settings["driver"] = "saved on crash"
        QTimer.singleShot(0, lambda: {}["a view bug"])
        end = time.time() + 1.0
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)
        rep = win.crash_reporter
        assert len(rep.reports) == 1 and "KeyError: 'a view bug'" in rep.reports[0]
        assert rep.dialog is not None and rep.dialog.isVisible()
        assert "KeyError" in rep.dialog.findChild(QPlainTextEdit).toPlainText()
        copy = next(b for b in rep.dialog.findChildren(type(win.connect_btn)) if b.text() == "Copy details")
        copy.click()
        assert "KeyError" in QApplication.clipboard().text()
        assert Settings()["driver"] == "saved on crash"
        ticks = win.hub.ticks
        end = time.time() + 0.4
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)
        assert win.hub.ticks > ticks
        rep.dialog.close()
    finally:
        win.hub.shutdown()
        win.close()
        sys.excepthook, threading.excepthook = old_hook, old_thread_hook
