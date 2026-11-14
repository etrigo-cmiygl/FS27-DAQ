"""Uses a real DAQ USB serial log from the car (10 Nov 2026, engine off, older firmware without [CAN])."""
import random
from pathlib import Path

import pytest

from gryphon_manager.core.pipeline import Pipeline
from gryphon_manager.core.radio import ReceiverParser, parse_daq_line

LOG = Path(__file__).parent / "fixtures" / "daq_usb_car_2026-11-10.log"
NEW_LINES = [
    "[ECU] MAP:1.013 bar | AirTemp:22.0 | Oil:0.00 bar | Fuel:3.01 bar | Water:0.10 bar | Lambda:0.998",
    "[GPS] Sats:9 | Fix:1 | Speed:0.4 kph",
    "[CAN] TEC:0 | REC:0 | EFLG:0x00 | TXB0CTRL:0x00 | RX:1234",
    "[TX] FAILED #4",
    "GPS Configured: 57600 baud, 5Hz",
    "Core 0: GPS + CAN started",
]


def lines():
    return LOG.read_bytes().decode("utf-8", "replace").splitlines()


def test_every_line_in_the_real_log_is_understood():
    kinds = {}
    for line in lines():
        d = parse_daq_line(line, 1.0)
        tag = line[: line.find("]") + 1]
        kinds.setdefault(tag, [0, 0])
        kinds[tag][0 if d else 1] += 1
    assert kinds == {"[DBG]": [0, 625], "[TX]": [125, 0]}


def replay(cfg, text_lines):
    p = Pipeline(cfg)
    t = 1000.0
    for line in text_lines:
        if line.startswith("[TX]"):
            t += 0.5
        p.feed("daqline", (t, line))
        p.engine.tick(t)
    return p.engine


def test_replaying_the_real_log_gives_sensible_values(cfg):
    e = replay(cfg, lines())
    s = e.signals
    assert s["usb.rpm"].value == 0 and s["usb.rpm"].count == 125
    assert s["usb.engine_temp"].value == 20.0 and s["usb.engine_temp"].vmin == 20.0
    assert s["usb.battery"].value == 0.0 and s["usb.tps"].value == 0.0
    assert s["usb.tx_count"].value == 141 and s["usb.tx_count"].vmin == 17
    assert s["usb.can_count"].value == 535 and s["usb.can_count"].vmin == 71
    assert e.value("engine_temp") == 20.0 and e.car_stationary()
    assert e.daq_tx_fail == 0 and e.alarms.active == {}


def test_real_log_shows_the_ecu_broadcasting_at_about_1hz(cfg):
    e = replay(cfg, lines())
    count, rate = e.daq_rx()
    assert count == 535
    assert 0.6 < rate / 9 < 1.3, rate
    status, text = e.daq_usb_health()
    assert status == "grey" and "doesn't print a [CAN] line" in text
    e.on_daq_line(parse_daq_line(NEW_LINES[2], e.now))
    e.tick(e.now)
    assert e.daq_rx()[0] == 1234 and e.daq_usb_health()[0] == "green"


def test_partial_and_mangled_lines_never_crash_or_invent_values(cfg):
    rng = random.Random(27)
    samples = lines()[:12] + NEW_LINES
    p = Pipeline(cfg)
    rx = ReceiverParser(cfg)
    n = 0
    for line in samples:
        for cut in range(len(line) + 1):
            for piece in (line[:cut], line[cut:]):
                d = parse_daq_line(piece, 1.0)
                rx.feed(piece, 1.0)
                if d is not None and d.kind in ("TX", "ECU", "GPS", "CAN"):
                    assert all(isinstance(v, (int, float)) for v in d.values.values())
                p.feed("daqline", (1.0 + n * 0.001, piece))
                n += 1
        for _ in range(40):
            chars = list(line)
            for _ in range(3):
                chars[rng.randrange(len(chars))] = chr(rng.randrange(1, 0x2FF))
            p.feed("daqline", (2.0, "".join(chars)))
    p.engine.tick(3.0)
    assert p.engine.signals["usb.engine_temp"].value == pytest.approx(20.0)


def test_two_lines_run_together_after_a_dropped_newline(cfg):
    line = "[TX] RPM:0 | Batt:0.00 | TPS:0.000 | Engi[TX] RPM:900 | Batt:0.00 | TPS:1.500 | EngineTemp:21.0 | TX#5 CAN#45"
    d = parse_daq_line(line, 1.0)
    assert d is None or d.values["rpm"] in (0, 900)
