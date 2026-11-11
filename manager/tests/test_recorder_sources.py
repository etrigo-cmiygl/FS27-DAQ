import csv
import queue
import time

import pytest

from gryphon_manager.core.recorder import (Recorder, analyse, export_csv, list_sessions, load_alarms,
                                           load_events, update_meta)
from gryphon_manager.core.simulator import SimCar
from gryphon_manager.core.sources import CanSource, ReplaySource, SimSource, friendly_can_error


def record(cfg, tmp_path, fmt="blf", seconds=12.0, **kw):
    rec = Recorder()
    d = rec.start({"name": "Test run!", "driver": "HP", "notes": "n", "source": "Simulator"}, fmt, tmp_path)
    items = SimCar(cfg, **kw).step(0, seconds, 1700000000.0)
    for kind, payload in items:
        rec.on_item(kind, payload)
    rec.stop({"config_version": cfg.version})
    return d, items


@pytest.mark.parametrize("fmt", ["blf", "asc"])
def test_record_and_read_back(cfg, tmp_path, fmt):
    d, items = record(cfg, tmp_path, fmt)
    assert (d / f"can.{fmt}").exists() and (d / "radio.log").exists() and (d / "daq.log").exists()
    assert d.name.endswith("_Test_run")
    meta = list_sessions(tmp_path)[0]
    assert meta["driver"] == "HP" and meta["finished"] and meta["config_version"] == 1
    assert meta["frames"] == sum(1 for k, _ in items if k == "frame")
    events = load_events(d)
    assert len(events) == len(items)
    assert events == sorted(events, key=lambda e: e[0])
    frames = [p for _, k, p in events if k == "frame"]
    orig = [p for k, p in items if k == "frame"]
    assert {(f.id, f.ext, f.data) for f in frames} == {(f.id, f.ext, f.data) for f in orig}
    assert frames[0].ts == pytest.approx(min(f.ts for f in orig), abs=0.01)


def test_analyse_and_csv_export(cfg, tmp_path):
    d, _ = record(cfg, tmp_path, seconds=20.0)
    a = analyse(d, cfg)
    assert a["duration"] == pytest.approx(20.0, abs=0.6)
    assert a["stats"]["rpm"]["max"] > 5000 and a["stats"]["rpm"]["samples"] >= 190
    assert "radio.rpm" in a["series"] and "usb.rpm" in a["series"] and len(a["track"]) > 10
    out = tmp_path / "out.csv"
    rows = export_csv(d, cfg, out)
    with open(out, newline="") as fh:
        table = list(csv.reader(fh))
    assert rows == len(table) - 1 and rows >= 195
    head = table[0]
    assert head[0] == "time_s" and "rpm [rpm]" in head and "engine_temp [°C]" in head
    assert float(table[-1][head.index("rpm [rpm]")]) > 3000


def test_meta_edit_and_alarm_log(cfg, tmp_path):
    from gryphon_manager.core.alarms import AlarmEvent
    rec = Recorder()
    d = rec.start({"name": "a"}, "blf", tmp_path)
    rec.on_alarm(AlarmEvent(5.0, "Low oil pressure", "Oil pressure is 0.4 bar", True))
    rec.stop()
    assert load_alarms(d)[0]["name"] == "Low oil pressure"
    update_meta(d, {"notes": "wet track"})
    assert list_sessions(tmp_path)[0]["notes"] == "wet track"


def drain(q, seconds, until=None):
    out = []
    end = time.time() + seconds
    while time.time() < end:
        try:
            item = q.get(timeout=0.05)
        except queue.Empty:
            continue
        out.append(item)
        if until and item[0] == until:
            break
    return out


def test_can_source_on_the_virtual_bus(cfg):
    import can
    q = queue.Queue()
    src = CanSource(q, "virtual", "gryphon_test", listen_only=True)
    src.start()
    assert drain(q, 3, until="opened")[-1][0] == "opened"
    tx = can.Bus(interface="virtual", channel="gryphon_test")
    car = SimCar(cfg)
    sent = [p for k, p in car.step(0, 0.5) if k == "frame"]
    for f in sent:
        tx.send(can.Message(arbitration_id=f.id, is_extended_id=f.ext, data=f.data))
    time.sleep(0.3)
    assert src.send(0x123, False, b"\x01") is False
    src.stop()
    src.join(3)
    tx.shutdown()
    got = [p for k, p in drain(q, 0.3) if k == "frame"]
    assert [(f.id, f.ext, f.data) for f in got] == [(f.id, f.ext, f.data) for f in sent]
    assert abs(got[0].ts - time.time()) < 5


def test_sim_source_streams_everything(cfg):
    q = queue.Queue()
    src = SimSource(q, cfg, parts="all")
    src.start()
    items = drain(q, 1.3)
    src.stop()
    src.join(2)
    kinds = {k for k, _ in items}
    assert {"opened", "frame", "rxline", "daqline", "status"} <= kinds
    q2 = queue.Queue()
    only = SimSource(q2, cfg, parts="radio")
    only.start()
    items = drain(q2, 0.8)
    only.stop()
    only.join(2)
    assert "frame" not in {k for k, _ in items} and not only.can_expected


def test_replay_source_plays_seeks_and_finishes(cfg, tmp_path):
    d, items = record(cfg, tmp_path, seconds=6.0)
    q = queue.Queue()
    src = ReplaySource(q, str(d), speed=8.0)
    src.start()
    assert src.loaded.wait(5)
    assert src.duration == pytest.approx(6.0, abs=0.6)
    got = drain(q, 4, until="finished")
    assert got[-1][0] == "finished"
    assert sum(1 for k, _ in got if k in ("frame", "rxline", "daqline")) == len(items)
    src.seek(5.0)
    got = drain(q, 3, until="finished")
    assert got[0][0] == "reset"
    n = sum(1 for k, _ in got if k == "frame")
    assert 0 < n < sum(1 for k, _ in items if k == "frame") / 3
    src.stop()
    src.join(2)


def test_missing_pcan_driver_gets_a_friendly_message():
    q = queue.Queue()
    src = CanSource(q, "pcan", "PCAN_USBBUS1")
    src.start()
    src.join(5)
    items = drain(q, 0.2)
    errors = [p for k, p in items if k == "error"]
    assert errors and "peak-system.com" in errors[0] and "Traceback" not in errors[0]
    assert items[-1][0] == "ended"
    assert "COM port" in friendly_can_error("slcan", RuntimeError("x"))
