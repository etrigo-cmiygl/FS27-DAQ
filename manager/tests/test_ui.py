import time

import pytest

pytest.importorskip("PySide6")


@pytest.fixture()
def win(gryphon_home, tmp_path):
    from pathlib import Path

    from gryphon_manager.app import create_app, create_window
    from gryphon_manager.core.settings import Settings
    from gryphon_manager.ui.hub import Hub
    app = create_app()
    cfg = tmp_path / "channels.yaml"
    cfg.write_text((Path(__file__).resolve().parents[1] / "config" / "channels.yaml").read_text(encoding="utf-8"),
                   encoding="utf-8")
    settings = Settings()
    settings["first_run_done"] = True
    w = create_window(Hub(settings, cfg))
    w.show()
    w.app = app
    yield w
    w.hub.shutdown()
    w.close()
    app.processEvents()


def pump(win, seconds):
    end = time.time() + seconds
    while time.time() < end:
        win.app.processEvents()
        time.sleep(0.005)


def test_every_view_opens_empty_and_with_data(win):
    from gryphon_manager.ui.main_window import NAV
    assert len(NAV) == 14
    for key, _ in NAV:
        win.show_view(key)
        pump(win, 0.05)
    assert win.views["garage"].switch.stack.currentIndex() == 0
    win.hub.connect_source("sim", parts="all", mode="drive", fault="none", warmup=30.0)
    pump(win, 1.5)
    assert win.hub.connected and win.pill.text() == "Connected"
    for key, _ in NAV:
        win.show_view(key)
        pump(win, 0.15)
    g = win.views["garage"]
    win.show_view("garage")
    pump(win, 0.3)
    assert g.switch.stack.currentIndex() == 1
    assert g.tiles["rpm"].value.text() not in ("--", "0")
    assert g.chips["ecu"].line1.text().startswith("OK")
    assert "match the ECU" in g.daq_text.text()
    assert win.views["telemetry"].switch.stack.currentIndex() in (0, 1)
    assert win.hub.engine.total_frames > 5000


def test_fault_shows_in_garage_and_alarm_banner(win):
    win.hub.connect_source("sim", parts="all", mode="drive", fault="ecu_1hz", warmup=15.0)
    win.show_view("garage")
    pump(win, 1.2)
    assert "about 1 Hz" in win.views["garage"].ecu_text.text()
    win.hub.source.set_fault("low_oil")
    pump(win, 2.5)
    assert not win.alarmbar.isHidden() and "Low oil pressure" in win.alarm_label.text()


def test_listen_only_by_default_and_transmit_needs_the_setting(win):
    hub = win.hub
    assert hub.settings["allow_transmit"] is False
    hub.connect_source("can", interface="virtual", channel="ui_test")
    pump(win, 0.6)
    assert hub.connected and hub.source.listen_only is True
    assert hub.source.send(0x123, False, b"\x00") is False
    assert win.listen_pill.text() == "Listen-only"
    win.show_view("raw")
    win.views["raw"].on_state()
    assert not win.views["raw"].tx_btn.isEnabled()
    hub.disconnect_source()
    hub.settings["allow_transmit"] = True
    hub.connect_source("can", interface="virtual", channel="ui_test")
    pump(win, 0.6)
    assert hub.source.listen_only is False and win.listen_pill.text() == "TRANSMIT ALLOWED"


def test_record_replay_and_report(win, gryphon_home):
    from gryphon_manager.core.recorder import list_sessions
    hub = win.hub
    hub.connect_source("sim", parts="all", mode="off", warmup=8.0)
    pump(win, 0.8)
    ct = win.views["cartest"]
    win.show_view("cartest")
    ct.inputs["ohms"] = "60"
    for _ in range(4):
        ct._mark("pass")
        pump(win, 0.1)
    for _ in range(3):
        ct._mark("skip")
    folder = ct._save()
    assert (folder / "report.html").exists() and (folder / "report.pdf").stat().st_size > 2000
    assert "Result: PASS" in (folder / "report.html").read_text(encoding="utf-8")
    assert any(p.is_dir() and (p / "can.blf").exists() for p in folder.iterdir())
    hub.toggle_recording()
    pump(win, 1.0)
    hub.toggle_recording()
    sessions = list_sessions()
    assert len(sessions) == 1 and sessions[0]["frames"] > 100
    hub.disconnect_source()
    ses = win.views["sessions"]
    win.show_view("sessions")
    pump(win, 0.2)
    ses._replay()
    pump(win, 1.0)
    assert hub.kind == "replay" and hub.connected and hub.engine.total_frames > 50
    assert not ses.bar.isHidden()


def test_channel_editor_generates_files(win, tmp_path):
    ch = win.views["channels"]
    win.show_view("channels")
    assert ch.valid
    ch.cfg.channels.append({"key": "steer", "name": "Steering angle", "group": "Driver",
                            "source": {"type": "can", "id": "0x510", "byte": 0, "bits": 16, "signed": True},
                            "scale": 0.1, "units": "deg", "radio": "off", "screen": False})
    ch.dirty = True
    ch._fill()
    assert ch.valid and "46 channels" in ch.status.text()
    ch.cfg.channels.append(dict(ch.cfg.channels[-1], name="Copy"))
    ch._fill()
    assert not ch.valid
    del ch.cfg.channels[-1]
    ch._fill()
    ch.cfg.save(win.hub.config_path)
    win.hub.reload_config()
    assert "steer" in win.hub.engine.signals
    out = ch.out_dir()
    files = win.hub.cfg.generate()
    out.mkdir(exist_ok=True)
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    assert "Steering_angle" in (out / "gryphon_fs27.dbc").read_text(encoding="utf-8")
    assert "GRYPHON_CH_STEER" in (out / "gryphon_channels.h").read_text(encoding="utf-8")
