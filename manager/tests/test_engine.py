import time

import pytest

from conftest import run_sim
from gryphon_manager.core.engine import Engine
from gryphon_manager.core.laps import LapTimer, fmt_lap
from gryphon_manager.core.model import Frame, RadioPacket
from gryphon_manager.core.simulator import SimCar


def test_healthy_car_is_all_green(cfg):
    e, _ = run_sim(cfg, 20)
    assert {k: d.status for k, d in e.devices.items()} == {
        "ecu": "green", "daq": "green", "pdm": "green", "lambda": "green", "screen": "green"}
    assert e.devices["ecu"].rate == pytest.approx(10, abs=0.3)
    assert e.devices["daq"].rate == pytest.approx(20, abs=0.5)
    assert e.ecu_check.status == "green" and e.daq_check.status == "green"
    assert [r[4] for r in e.daq_check.rows] == ["green"] * 5
    assert e.bus_summary()[0] == "green"
    assert 1.0 < e.bus_load < 6.0 and e.frame_rate == pytest.approx(200, abs=10)
    assert e.alarms.active == {}


def test_pdm_and_lambda_grey_until_ids_known(cfg):
    from gryphon_manager.core.pipeline import Pipeline
    p = Pipeline(cfg)
    p.engine.mark_connected(1000.0, True)
    p.run(SimCar(cfg).step(0, 8, 1000.0))
    assert p.engine.devices["pdm"].status == "grey" and "Settings" in p.engine.devices["pdm"].text
    unknown = [fs for fs in p.engine.frames.values() if not p.engine.is_known(fs)]
    assert sorted(fs.id for fs in unknown) == [0x460, 0x500, 0x501]
    p2 = Pipeline(cfg, {"pdm_ids": "0x500-0x501", "lambda_ids": "0x460"})
    p2.engine.mark_connected(1000.0, True)
    p2.run(SimCar(cfg).step(0, 8, 1000.0))
    assert p2.engine.devices["pdm"].status == "green" and p2.engine.devices["lambda"].status == "green"


def test_ecu_at_1hz_is_flagged_with_the_ftmanager_fix(cfg):
    e, _ = run_sim(cfg, 20, fault="ecu_1hz")
    assert e.devices["ecu"].status == "amber"
    assert e.ecu_check.status == "amber"
    assert "about 1 Hz" in e.ecu_check.text and "CAN communication" in e.ecu_check.text
    assert e.daq_check.status == "green"


def test_daq_sending_wrong_values_is_flagged(cfg):
    e, _ = run_sim(cfg, 15, fault="daq_wrong")
    assert e.daq_check.status == "red"
    assert "RPM" in e.daq_check.text and "Engine temp" in e.daq_check.text
    rows = {r[0]: r[4] for r in e.daq_check.rows}
    assert rows["RPM"] == "red" and rows["Throttle"] == "green"


def test_daq_missing(cfg):
    e, _ = run_sim(cfg, 10, fault="daq_missing")
    assert e.devices["daq"].status == "red" and e.daq_check.status == "red"
    assert e.devices["screen"].status == "grey"
    assert "DAQ missing" in e.alarms.active


def test_device_that_stops_goes_red(cfg):
    from gryphon_manager.core.pipeline import Pipeline
    from gryphon_manager.core.simulator import SIM_DEVICES
    car = SimCar(cfg)
    p = Pipeline(cfg)
    p.engine.set_sim_devices(SIM_DEVICES)
    p.engine.mark_connected(1000.0, True)
    p.run(car.step(0, 6, 1000.0))
    assert p.engine.devices["ecu"].status == "green"
    p.run([i for i in car.step(6, 14, 1000.0) if not (i[0] == "frame" and i[1].ext)])
    assert p.engine.devices["ecu"].status == "red" and "Stopped" in p.engine.devices["ecu"].text
    assert "ECU missing" in p.engine.alarms.active


def test_low_oil_alarm_raises_then_clears(cfg):
    from gryphon_manager.core.pipeline import Pipeline
    car = SimCar(cfg, fault="low_oil")
    p = Pipeline(cfg)
    p.run(car.step(0, 6, 1000.0))
    assert "Low oil pressure" in p.engine.alarms.active
    car.fault = "none"
    p.run(car.step(6, 10, 1000.0))
    assert "Low oil pressure" not in p.engine.alarms.active
    names = [(ev.name, ev.raised) for ev in p.engine.alarms.events if ev.name == "Low oil pressure"]
    assert names == [("Low oil pressure", True), ("Low oil pressure", False)]


def test_battery_zero_does_not_alarm_but_reads_zero(cfg):
    e, _ = run_sim(cfg, 8, fault="battery_zero")
    assert e.signals["daq.battery"].value == 0
    assert "Battery low" not in e.alarms.active


def test_engine_off_mode(cfg):
    e, _ = run_sim(cfg, 8, mode="off")
    assert e.signals["rpm"].value == 0 and e.signals["engine_temp"].value == pytest.approx(20, abs=0.5)
    assert e.car_stationary()
    e2, _ = run_sim(cfg, 8, mode="drive")
    assert not e2.car_stationary()


def test_bus_errors(cfg):
    e, _ = run_sim(cfg, 6, fault="bus_errors")
    assert e.error_frames >= 20
    assert e.daq_usb_health()[0] == "red"


def test_radio_link_counts_lost_packets(cfg):
    e = Engine(cfg)
    lat = 52.0
    for i, tx in enumerate([1, 2, 3, 7, 8, 65535, 0, 1]):
        e.on_packet(RadioPacket(100.0 + i * 0.5, {"tx_count": tx, "gps_lat": lat + i * 1e-4, "gps_lon": -1.0,
                                                  "gps_fix": 1, "gps_speed": 30.0}, -70, 8))
    assert e.radio.received == 8
    assert e.radio.lost == 3
    assert e.radio.restarts == 1
    assert e.radio.rate == pytest.approx(2.0)
    assert len(e.radio.loss_points) == 2
    assert e.signals["radio.rssi"].value == -70 and len(e.track) == 8


def test_radio_sim_has_dropouts_on_the_far_side(cfg):
    e, car = run_sim(cfg, 120)
    assert e.radio.received > 100 and e.radio.lost > 20
    assert e.radio.received + e.radio.lost == pytest.approx(car.tx_count, abs=8)
    assert len(e.radio.loss_points) > 4 and len(e.track) > 100
    assert e.radio.format == "FS26 text box"


def test_gps_glitch_is_ignored(cfg):
    e = Engine(cfg)
    for i, lat in enumerate([52.0, 52.0001, 53.5, 52.0002, 0.0]):
        e.on_packet(RadioPacket(10.0 + i, {"tx_count": i, "gps_lat": lat, "gps_lon": -1.0, "gps_fix": 1}))
    assert [round(p[1], 4) for p in e.track] == [52.0, 52.0001, 52.0002]


def test_track_from_can_when_there_is_no_radio(cfg):
    from gryphon_manager.core.pipeline import Pipeline
    p = Pipeline(cfg)
    p.run(i for i in SimCar(cfg).step(0, 10, 1000.0) if i[0] == "frame")
    assert len(p.engine.track) > 20


def test_lap_timing(cfg):
    from gryphon_manager.core.pipeline import Pipeline
    car = SimCar(cfg)
    p = Pipeline(cfg)
    p.run(i for i in car.step(0, 5, 1000.0) if i[0] == "frame")
    e = p.engine
    assert e.laps.set_gate_from_track(e.track[-1][1], e.track[-1][2], e.track)
    p.run(i for i in car.step(5, 200, 1000.0) if i[0] == "frame")
    laps = e.laps.laps
    assert len(laps) >= 3
    times = [l.time for l in laps]
    assert max(times) - min(times) < 3.0, times
    assert e.laps.best.time == min(times)
    assert e.laps.gate_line() is not None
    assert fmt_lap(83.456) == "1:23.46" and fmt_lap(None) == "--:--.--"


def test_lap_gate_ignores_wrong_direction_and_far_passes():
    lt = LapTimer()
    lt.set_gate(52.0, -1.0, 1.0, 0.0)
    assert lt.add_point(0.0, 52.0, -1.0002) is None
    assert lt.add_point(1.0, 52.0, -0.9998) is None
    assert lt.add_point(5.0, 52.0, -1.0002) is None
    assert lt.add_point(6.0, 52.0, -0.9998) is None
    lt.add_point(20.0, 52.01, -1.0002)
    assert lt.add_point(21.0, 52.01, -0.9998) is None
    lt.add_point(30.0, 52.0, -1.0002)
    lap = lt.add_point(31.0, 52.0, -0.9998)
    assert lap is not None and lap.time == pytest.approx(30.0, abs=0.05)


def test_handles_2000_frames_a_second_easily(cfg):
    from gryphon_manager.core.pipeline import Pipeline
    items = SimCar(cfg, stress_fps=2000).step(0, 10, 1000.0)
    frames = [i for i in items if i[0] == "frame"]
    assert len(frames) > 21000
    p = Pipeline(cfg)
    t = time.perf_counter()
    p.run(items)
    took = time.perf_counter() - t
    assert took < 5.0, f"10 s of bus at 2200 frames/s took {took:.2f} s to process"
    assert p.engine.frame_rate > 2000


def test_out_of_range_and_best_source(cfg):
    e = Engine(cfg)
    e.on_frame(Frame(10.0, 0x14080600, True, bytes([0x04, 0x4C, 0, 0, 0, 0, 0, 0])))
    e.tick(10.1)
    assert e.signals["tps"].out_of_range
    e.on_packet(RadioPacket(10.2, {"rpm": 5000, "tx_count": 1}))
    e.tick(10.3)
    assert e.best("rpm").key == "radio.rpm" and e.value("rpm") == 5000
    e.on_frame(Frame(10.4, 0x14080602, True, bytes([0, 0, 0x1F, 0x40, 0, 0, 0, 0])))
    e.tick(10.5)
    assert e.best("rpm").key == "rpm" and e.value("rpm") == 8000
    e.tick(30.0)
    assert e.value("rpm") is None
