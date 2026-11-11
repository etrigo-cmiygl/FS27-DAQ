"""Screenshots every view using the simulator, with no screen needed.

    QT_QPA_PLATFORM=offscreen python tools/screenshots.py [output folder]

Uses a throwaway home folder, so it never touches real recordings or settings.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
out = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "screenshots"
out.mkdir(parents=True, exist_ok=True)
home = Path(tempfile.mkdtemp(prefix="gryphon_shots_"))
os.environ["GRYPHON_HOME"] = str(home)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gryphon_manager.app import create_app, create_window  # noqa: E402
from gryphon_manager.core.config import MasterConfig  # noqa: E402
from gryphon_manager.core.settings import Settings  # noqa: E402
from gryphon_manager.ui.hub import Hub  # noqa: E402

app = create_app()
cfg_copy = home / "channels.yaml"
cfg_copy.write_text((root / "config" / "channels.yaml").read_text(encoding="utf-8"), encoding="utf-8")
(home / "generated").mkdir()
for name, text in MasterConfig.load(cfg_copy).generate().items():
    (home / "generated" / name).write_text(text, encoding="utf-8")
settings = Settings()
settings["first_run_done"] = True
settings["driver"] = "Hriday"
settings["graph_signals"] = ["rpm", "tps", "engine_temp", "oil_pressure"]
hub = Hub(settings, cfg_copy)
win = create_window(hub)
win.resize(1440, 900)
win.show()
shots = []


def wait(seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def shot(name: str, widget=None) -> None:
    wait(0.25)
    path = out / f"{len(shots) + 1:02d}_{name}.png"
    (widget or win).grab().save(str(path))
    shots.append(path)
    print("saved", path.name)


def view(key: str, settle: float = 0.6):
    win.show_view(key)
    wait(settle)
    return win.views[key]


def sim(fault="none", mode="drive", warmup=0.0, settle=3.0):
    hub.connect_source("sim", fault=fault, mode=mode, parts="all", warmup=warmup)
    win._set_combo(win.sim_fault, fault)
    win._set_combo(win.sim_mode, mode)
    wait(settle)


# --- empty states, before connecting -------------------------------------------------------------
view("home")
shot("home_not_connected")
view("garage")
shot("garage_empty_state")
view("telemetry")
shot("telemetry_empty_state")

# --- welcome wizard ------------------------------------------------------------------------------
from gryphon_manager.ui.welcome import WelcomeWizard  # noqa: E402

wiz = WelcomeWizard(win, hub)
wiz.setModal(False)
wiz.show()
for i, name in enumerate(("welcome_1", "welcome_2_adapter", "welcome_3_test", "welcome_4_tour")):
    wiz.pages.setCurrentIndex(i)
    wiz._sync()
    shot(name, wiz)
wiz.close()

# --- healthy car, with two and a half minutes of history ------------------------------------------
sim(warmup=150.0, settle=4.0)
e = hub.engine
view("home")
shot("home_connected")
view("garage")
shot("garage_healthy")
view("signals")
shot("signals")
view("raw", 1.5)
shot("raw_frames")
raw = win.views["raw"]
raw.mode.setCurrentIndex(1)
wait(1.2)
shot("raw_frames_scrolling")
raw.mode.setCurrentIndex(0)
g = view("graphs", 1.5)
g.window_combo.setCurrentIndex(2)
wait(1.0)
shot("graphs")

tel = view("telemetry", 1.0)
mid = list(e.track)[len(e.track) // 3]
e.laps.set_gate_from_track(mid[1], mid[2], e.track)
tel._track_len = -1
wait(1.5)
shot("telemetry_map_and_laps")

# --- recordings ----------------------------------------------------------------------------------
hub.settings["driver"] = "Hriday"
hub.start_recording("Skidpad run 1", notes="Dry, new tyres")
wait(6.0)
hub.stop_recording()
hub.start_recording("Skidpad run 2", notes="After damper change")
wait(5.0)
hub.stop_recording()

# --- faults ----------------------------------------------------------------------------------------
sim(fault="ecu_1hz", warmup=12.0, settle=4.0)
view("garage")
shot("garage_ecu_at_1hz")
sim(fault="daq_wrong", warmup=6.0, settle=4.0)
view("garage")
shot("garage_daq_mismatch")
sim(fault="low_oil", warmup=6.0, settle=3.0)
view("alarms")
shot("alarms_low_oil")
win.hub.settings["pit_wall"] = True
win.apply_pit_wall()
view("garage")
shot("garage_pit_wall_mode_alarm")
win.hub.settings["pit_wall"] = False
win.apply_pit_wall()

# --- PDM and lambda IDs not known yet (what the real car looks like today) ------------------------
sim(warmup=5.0, settle=1.5)
hub.engine.set_sim_devices({})
view("raw", 2.5)
shot("raw_frames_unknown_ids")
view("garage", 1.0)
shot("garage_pdm_lambda_ids_unknown")

# --- DAQ over USB only -----------------------------------------------------------------------------
hub.connect_source("sim", parts="daq", fault="bus_errors", warmup=5.0)
wait(3.0)
view("garage")
shot("garage_daq_usb_send_failing")

# --- car test wizard -------------------------------------------------------------------------------
sim(mode="off", warmup=8.0, settle=3.0)
ct = view("cartest")
ct.inputs["ohms"] = "60.2"
ct._goto(0)
wait(0.5)
shot("car_test_step_1")
ct._mark("pass")
wait(0.5)
ct._mark("pass")
wait(0.5)
shot("car_test_step_3_engine_off")
ct._mark("pass")
wait(0.5)
shot("car_test_step_4_daq")
ct._mark("pass")
for k in ("scr_rpm", "scr_temp", "scr_tps", "scr_map"):
    ct.inputs[k] = True
ct._goto(4)
wait(0.4)
shot("car_test_step_5_screen")
ct._res("screen")["notes"] = "GPS page shows 0 satellites indoors."
ct._mark("fail")
hub.source.set_mode("idle")
win._set_combo(win.sim_mode, "idle")
wait(4.0)
shot("car_test_step_6_engine_running")
ct._mark("pass")
ct.inputs.update({"ft_rpm": str(int(e.value("rpm") or 1650)), "ft_engine_temp": f"{e.value('engine_temp') or 20:.1f}",
                  "ft_tps": "1.5", "ft_map": "0.33"})
ct._goto(6)
wait(0.6)
shot("car_test_step_7_ftmanager")
ct._mark("pass")
ct.tester.setText("Hriday")
ct.overall_notes.setPlainText("Bench run in the simulator.")
wait(0.4)
report_dir = ct._save()
wait(0.5)
shot("car_test_summary_saved")
print("report:", report_dir, sorted(p.name for p in report_dir.iterdir()))
(out / "report").mkdir(exist_ok=True)
for name in ("report.html", "report.pdf"):
    (out / "report" / name).write_bytes((report_dir / name).read_bytes())

# --- sessions and replay -------------------------------------------------------------------------
hub.disconnect_source()
ses = view("sessions", 3.0)
shot("sessions_summary")
ses.tabs.setCurrentIndex(1)
ses.cmp_other.setCurrentIndex(2)
wait(3.0)
ses._draw_compare()
shot("sessions_compare")
ses.tabs.setCurrentIndex(0)
ses._replay()
wait(3.0)
shot("sessions_replaying")
view("garage", 1.0)
shot("garage_during_replay")
hub.disconnect_source()
exported = home / "export.csv"
from gryphon_manager.core.recorder import export_csv  # noqa: E402

print("csv rows:", export_csv(ses.sessions[0]["path"], hub.cfg, exported))

# --- config, settings and the rest -----------------------------------------------------------------
ch = view("channels")
shot("channels")
from gryphon_manager.ui.views.channels import ChannelDialog, DiffDialog  # noqa: E402

dlg = ChannelDialog(win, {"key": "steering_angle", "name": "Steering angle", "group": "Driver",
                          "source": {"type": "can", "id": "0x510", "byte": 0, "bits": 16, "signed": True},
                          "scale": 0.1, "units": "deg", "min": -180, "max": 180, "radio": "fast"}, True)
dlg.show()
shot("channels_add_dialog", dlg)
dlg._ok()
ch.cfg.channels.append(dlg.ch)
ch.cfg.compile()
changes = []
for name, new in ch.cfg.generate().items():
    changes.append((name, (home / "generated" / name).read_text(encoding="utf-8"), new))
diff = DiffDialog(win, changes, home / "generated")
diff.show()
shot("channels_generate_diff", diff)
diff.close()
ch._revert()

view("daq")
shot("daq_settings_disabled")
view("firmware")
shot("firmware")
view("help")
shot("help")
win.views["help"].browser.scrollToAnchor("wiring")
shot("help_wiring")
view("settings")
shot("settings")

from gryphon_manager.ui.views.alarms import RuleDialog  # noqa: E402

rd = RuleDialog(win, hub, hub.settings["alarms"][0])
rd.show()
shot("alarm_rule_dialog", rd)
rd.close()

# --- friendly error when the PEAK driver is missing -------------------------------------------------
win._set_combo(win.source_combo, "can")
win._sync_source_controls()
hub.connect_source("can", interface="pcan", channel="PCAN_USBBUS1")
wait(2.0)
view("garage")
shot("pcan_driver_missing_message")

hub.shutdown()
print(f"{len(shots)} screenshots in {out}")
