"""Takes the screenshots used in docs/Gryphon-Manager-Manual.md, with the simulator and no screen.

    QT_QPA_PLATFORM=offscreen python tools/manual_shots.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
out = root / "docs" / "img"
out.mkdir(parents=True, exist_ok=True)
home = Path(tempfile.mkdtemp(prefix="gryphon_manual_"))
os.environ["GRYPHON_HOME"] = str(home)

from gryphon_manager.app import create_app, create_window  # noqa: E402
from gryphon_manager.core.settings import Settings  # noqa: E402
from gryphon_manager.ui.hub import Hub  # noqa: E402

app = create_app()
cfg_copy = home / "channels.yaml"
cfg_copy.write_text((root / "config" / "channels.yaml").read_text(encoding="utf-8"), encoding="utf-8")
settings = Settings()
settings["first_run_done"] = True
settings["driver"] = "Hriday"
settings["graph_signals"] = ["rpm", "tps", "engine_temp", "oil_pressure"]
hub = Hub(settings, cfg_copy)
win = create_window(hub)
win.resize(1280, 800)
win.show()


def wait(seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def shot(name: str, key: str | None = None, settle: float = 0.8) -> None:
    if key:
        win.show_view(key)
    wait(settle)
    win.grab().save(str(out / f"{name}.png"))
    print("saved", name)


def sim(fault="none", mode="drive", warmup=0.0, settle=3.0):
    hub.connect_source("sim", fault=fault, mode=mode, parts="all", warmup=warmup)
    win._set_combo(win.sim_fault, fault)
    win._set_combo(win.sim_mode, mode)
    wait(settle)


shot("home_not_connected", "home")
sim(warmup=150.0, settle=4.0)
shot("home", "home")
shot("garage", "garage")
shot("signals", "signals")
shot("raw", "raw", 1.5)
g = win.views["graphs"]
win.show_view("graphs")
g.window_combo.setCurrentIndex(2)
shot("graphs", settle=1.5)
e = hub.engine
win.show_view("telemetry")
mid = list(e.track)[len(e.track) // 3]
e.laps.set_gate_from_track(mid[1], mid[2], e.track)
win.views["telemetry"]._track_len = -1
shot("telemetry", settle=1.5)
hub.start_recording("Skidpad run 1", notes="Dry, new tyres")
wait(4.0)
hub.stop_recording()
sim(fault="low_oil", warmup=6.0, settle=3.0)
shot("alarms", "alarms")
sim(fault="ecu_1hz", warmup=12.0, settle=4.0)
shot("garage_ecu_1hz", "garage")
sim(mode="off", warmup=8.0, settle=3.0)
ct = win.views["cartest"]
win.show_view("cartest")
ct._goto(0)
shot("cartest", settle=0.6)
ch = win.views["channels"]
shot("channels", "channels")
ch.tabs.setCurrentIndex(1)
shot("channels_screen_frames", settle=0.5)
ch.tabs.setCurrentIndex(0)

from gryphon_manager.ui.views.channels import ChannelDialog  # noqa: E402

brake = {"key": "brake_front", "name": "Front brake pressure", "group": "Driver", "scale": 1, "units": "bar",
         "min": 0, "max": 160, "radio": "off", "screen": False,
         "source": {"type": "daq_input", "input": "X0", "sensor": "linear", "v_min": 0.5, "v_max": 4.5,
                    "value_min": 0.0, "value_max": 160.0, "divider": 1.0}}
dlg = ChannelDialog(win, brake, True)
dlg.setModal(False)
dlg.show()
wait(0.5)
dlg.grab().save(str(out / "channel_dialog_sensor.png"))
print("saved channel_dialog_sensor")
dlg.close()
ch.cfg.channels.append(brake)
ch.cfg.channels.append({"key": "gearbox_temp", "name": "Gearbox oil temp", "group": "Engine", "scale": 1, "units": "C",
                        "radio": "off", "screen": False,
                        "source": {"type": "daq_input", "input": "A0", "sensor": "thermistor", "pullup": 10000.0,
                                   "r25": 10000.0, "beta": 3950.0, "supply": 3.3}})
ch.cfg.channels.append({"key": "wheel_fl_daq", "name": "Front left wheel (DAQ)", "group": "Wheels", "scale": 1,
                        "units": "km/h", "radio": "off", "screen": False,
                        "source": {"type": "daq_input", "input": "F0", "sensor": "wheel_speed", "teeth": 20.0,
                                   "circumference_m": 1.6}})
ch._changed()
shot("daq_settings_before", "daq")
win.show_view("channels")
ch._send_to_daq(confirm=False)
wait(4.0)
d = win.views["daq"]
win.show_view("daq")
d._check()
wait(4.0)
shot("daq_settings", settle=0.5)
shot("firmware", "firmware")
shot("help", "help")
shot("settings", "settings")
hub.disconnect_source()
shot("sessions", "sessions", 3.0)
hub.shutdown()
