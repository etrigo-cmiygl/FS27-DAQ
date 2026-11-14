import os
import queue
import random
import sys
import time

import pytest

from gryphon_manager.core.engine import Engine
from gryphon_manager.core.model import Frame
from gryphon_manager.core.pipeline import Pipeline
from gryphon_manager.core.radio import ReceiverParser, pack_packet, unpack_packet
from gryphon_manager.core.recorder import list_sessions, load_events
from gryphon_manager.core.simulator import SimCar
from gryphon_manager.core.sources import SerialSource, Source


def drain(q, seconds, until=None):
    out, end = [], time.time() + seconds
    while time.time() < end:
        try:
            item = q.get(timeout=0.05)
        except queue.Empty:
            continue
        out.append(item)
        if until and item[0] == until:
            break
    return out


# ---- fuzzing the decoders ------------------------------------------------------------------------

def test_random_frames_never_crash_the_engine(cfg):
    rng = random.Random(1)
    e = Engine(cfg)
    known = [k for k in cfg.by_id]
    for i in range(30000):
        if rng.random() < 0.6:
            cid, ext = rng.choice(known)
        else:
            ext = rng.random() < 0.5
            cid = rng.randrange(0x20000000 if ext else 0x800)
        data = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 9)))
        e.on_frame(Frame(100.0 + i * 0.0005, cid, ext, data, is_error=rng.random() < 0.01))
        if i % 100 == 0:
            e.tick(100.0 + i * 0.0005)
    e.tick(120.0)
    for s in e.signals.values():
        assert s.value is None or s.value == s.value
    assert e.error_frames > 100 and len(e.frames) > 1000


def test_random_and_corrupt_radio_data_is_rejected(cfg):
    rng = random.Random(2)
    p = ReceiverParser(cfg)
    good = pack_packet(cfg, {"rpm": 5000, "gps_lat": 52.0, "gps_lon": -1.0, "gps_fix": 1, "tx_count": 1})
    accepted = 0
    for i in range(4000):
        raw = bytearray(good)
        for _ in range(rng.randrange(1, 6)):
            raw[rng.randrange(4, len(raw))] = rng.randrange(256)
        pkt = p.feed("PKT,-70,8," + bytes(raw).hex(), 1.0)
        if pkt is not None:
            accepted += 1
            for v in pkt.values.values():
                assert v == v and abs(v) < 1e13
    assert 0 < accepted < 4000
    nan = bytearray(good)
    nan[4:8] = b"\x00\x00\xc0\x7f"
    assert unpack_packet(cfg, bytes(nan)) is None
    for line in ("PKT", "PKT,,,", "PKT,a,b,c", "PKT,-70,8", "PKT,-70,8,zz", "PKT,-70,8," + "ff" * 400,
                 "║  RPM: x | TPS: y% | Eng: z C | Oil: w Bar ║", "║  RSSI: -- dBm  |  SNR: -- dB  |  RX Count: 1 ║",
                 "\x00\x01\x02", "║" * 500):
        assert p.feed(line, 1.0) is None
    pipe = Pipeline(cfg)
    for _ in range(3000):
        text = "".join(chr(rng.randrange(1, 0x3000)) for _ in range(rng.randrange(0, 120)))
        pipe.feed("rxline", (1.0, text))
        pipe.feed("daqline", (1.0, text))
    pipe.engine.tick(2.0)
    assert pipe.engine.radio.received == 0


# ---- wrong port, unplugging ------------------------------------------------------------------------

def test_wrong_com_port_gives_a_clear_message():
    q = queue.Queue()
    src = SerialSource(q, "COM_NOT_A_REAL_PORT_99", 115200, "radio")
    src.start()
    src.join(5)
    items = drain(q, 0.2)
    errors = [p for k, p in items if k == "error"]
    assert errors and "Couldn't open COM_NOT_A_REAL_PORT_99" in errors[0] and "Traceback" not in errors[0]
    assert items[-1][0] == "ended"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="uses a pseudo-terminal as the pretend USB serial port")
def test_serial_unplug_mid_stream_keeps_earlier_lines_and_reports_it():
    master, slave = os.openpty()
    q = queue.Queue()
    src = SerialSource(q, os.ttyname(slave), 115200, "daq")
    src.start()
    assert drain(q, 3, until="opened")[-1][0] == "opened"
    os.write(master, b"[TX] RPM:0 | Batt:0.00 | TPS:0.000 | EngineTemp:20.0 | TX#1 CAN#9\r\n[TX] RPM:0 | Ba")
    got = drain(q, 2, until="daqline")
    assert got[-1][1][1].endswith("CAN#9")
    os.close(master)
    os.close(slave)
    src.join(5)
    items = drain(q, 0.3)
    assert not src.is_alive()
    assert [k for k, _ in items][-1] == "ended"
    assert any(k == "error" and "unplugged" in p for k, p in items)
    assert not any(k == "daqline" for k, _ in items)


class FakeAdapter(Source):
    """Stands in for a PCAN, receiver or DAQ. `plugged` says whether it can be opened right now."""
    plugged = True
    opened = 0
    can_expected = True
    label = "Fake adapter"

    def __init__(self, out, cfg):
        super().__init__(out)
        self.car = SimCar(cfg, mode="idle")

    def run(self):
        cls = FakeAdapter
        if not cls.plugged:
            self.emit("error", "Couldn't open the adapter. Is it plugged in?\n(Details: fake)")
            self.emit("ended", None)
            return
        cls.opened += 1
        self.emit("opened", self.label)
        base, t = time.time(), 0.0
        while not self._stop_evt.is_set():
            if not cls.plugged:
                self.emit("error", "The CAN adapter stopped responding. Was it unplugged?\n(Details: fake)")
                break
            time.sleep(0.02)
            now = time.time() - base
            for kind, payload in self.car.step(t, now, base):
                if kind == "frame":
                    self.emit(kind, payload)
            t = now
        self.emit("ended", None)


@pytest.fixture()
def hub(gryphon_home, tmp_path, monkeypatch):
    from pathlib import Path

    from gryphon_manager.app import create_app
    from gryphon_manager.core.settings import Settings
    from gryphon_manager.ui.hub import Hub
    app = create_app()
    cfg = tmp_path / "channels.yaml"
    cfg.write_text((Path(__file__).resolve().parents[1] / "config" / "channels.yaml").read_text(encoding="utf-8"),
                   encoding="utf-8")
    h = Hub(Settings(), cfg)
    h.retry_seconds = 0.2
    h.app = app
    h.notices = []
    h.notice.connect(lambda level, text: h.notices.append((level, text)))
    FakeAdapter.plugged, FakeAdapter.opened = True, 0
    monkeypatch.setattr(h, "_make_source", lambda kind, opts: FakeAdapter(h.q, h.cfg))
    yield h
    h.shutdown()


def pump(hub, seconds):
    end = time.time() + seconds
    while time.time() < end:
        hub.app.processEvents()
        time.sleep(0.005)


def test_unplug_while_recording_saves_the_log_then_reconnects(hub):
    hub.connect_source("can")
    pump(hub, 0.5)
    assert hub.state == "connected"
    hub.start_recording("unplug test")
    pump(hub, 1.0)
    frames_before = hub.engine.total_frames
    FakeAdapter.plugged = False
    pump(hub, 0.8)
    assert hub.state == "reconnecting" and not hub.recorder.active
    assert any(level == "error" and "Trying to reconnect" in text and "recording up to this point is saved" in text
               for level, text in hub.notices)
    assert sum(1 for level, _ in hub.notices if level == "error") == 1
    sessions = list_sessions()
    assert len(sessions) == 1 and sessions[0]["finished"]
    saved = [p for _, k, p in load_events(sessions[0]["path"]) if k == "frame"]
    assert len(saved) == sessions[0]["frames"] > 100
    assert hub.engine.total_frames >= frames_before
    FakeAdapter.plugged = True
    pump(hub, 1.0)
    assert hub.state == "connected" and FakeAdapter.opened == 2
    assert ("info", "Reconnected.") in hub.notices
    assert hub.recorder.active and hub.engine.total_frames > frames_before
    hub.disconnect_source()
    pump(hub, 0.5)
    assert hub.state == "disconnected" and len(list_sessions()) == 2


def test_disconnect_stops_the_reconnect_attempts(hub):
    hub.connect_source("can")
    pump(hub, 0.4)
    FakeAdapter.plugged = False
    pump(hub, 0.6)
    assert hub.state == "reconnecting"
    hub.disconnect_source()
    FakeAdapter.plugged = True
    pump(hub, 0.8)
    assert hub.state == "disconnected" and FakeAdapter.opened == 1 and hub.source is None


def test_an_adapter_that_never_opened_is_not_retried(hub):
    FakeAdapter.plugged = False
    hub.connect_source("can")
    pump(hub, 0.8)
    assert hub.state == "disconnected" and hub.source is None
    assert [level for level, _ in hub.notices] == ["error"]


# ---- soak ---------------------------------------------------------------------------------------

SOAK_MINUTES = int(os.environ.get("GRYPHON_SOAK_MINUTES", "10"))


def test_simulated_soak_stays_bounded(cfg):
    import tracemalloc
    car = SimCar(cfg)
    p = Pipeline(cfg, history=2000)
    e = p.engine
    tracemalloc.start()
    sizes = []
    for minute in range(SOAK_MINUTES):
        p.run(car.step(minute * 60.0, (minute + 1) * 60.0, 1000.0))
        if minute in (SOAK_MINUTES // 3, SOAK_MINUTES - 1):
            sizes.append(tracemalloc.get_traced_memory()[0])
    tracemalloc.stop()
    assert e.total_frames > 11000 * SOAK_MINUTES and e.radio.received > 60 * SOAK_MINUTES
    assert all(len(s.ht) <= 2000 for s in e.signals.values())
    assert len(e.track) <= 20000 and len(e.radio.loss_points) <= 2000 and len(e.alarms.events) <= 500
    assert len(e.frames) == 16
    assert sizes[1] < sizes[0] * 1.25 + 2_000_000, sizes
    assert {d.status for d in e.devices.values()} <= {"green", "grey"}
