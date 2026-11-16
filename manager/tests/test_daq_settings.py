"""The DAQ settings protocol: the app's side, the simulator's pretend DAQ, and the real firmware C code."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from gryphon_manager.core import daq_protocol as proto
from gryphon_manager.core.daq_sim import DaqSim, FACTORY_FRAMES, FACTORY_RADIO

REPO = Path(__file__).resolve().parents[2]


class RealFirmware:
    """daq_settings_fs27.c compiled for this machine, driven over a pipe."""

    def __init__(self, exe):
        self.p = subprocess.Popen([str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    def send(self, line: str) -> list[str]:
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        out = []
        while True:
            reply = self.p.stdout.readline().rstrip("\n")
            if reply == ".":
                return out
            out.append(reply)

    def handle(self, line, rpm=0, speed=0):
        self.send(f"!rpm={int(rpm)}")
        self.send(f"!speed={speed}")
        return self.send(line)

    def close(self):
        self.p.stdin.close()
        self.p.wait(5)


@pytest.fixture(scope="module")
def firmware(tmp_path_factory):
    cc = shutil.which("cc") or shutil.which("gcc")
    if not cc:
        pytest.skip("no C compiler here, so the real firmware code can't be run")
    exe = tmp_path_factory.mktemp("fw") / ("daq_proto_host.exe" if os.name == "nt" else "daq_proto_host")
    subprocess.run([cc, "-I", str(REPO), "-o", str(exe), str(REPO / "tests" / "daq_proto_host_fs27.c"),
                    str(REPO / "daq_settings_fs27.c"), str(REPO / "ft550_decoder.c"), "-lm"], check=True)
    fw = RealFirmware(exe)
    yield fw
    fw.close()


def test_lines_and_checksums():
    line = proto.build_line("SET", radio_hz=5, gps_hz=10)
    assert line == "$GM,SET,radio_hz=5,gps_hz=10*" + proto.checksum("GM,SET,radio_hz=5,gps_hz=10")
    assert proto.parse_line(line) == ("SET", ["radio_hz=5", "gps_hz=10"])
    assert proto.key_values(["radio_hz=5", "x"]) == {"radio_hz": "5"}
    assert proto.parse_line(line[:-1] + ("0" if line[-1] != "0" else "1")) is None
    assert proto.parse_line("[TX] RPM:0") is None and proto.parse_line("$GM,*47") is None
    assert proto.checksum("PMTK251,57600") == "2C"
    assert proto.validate({"gps_hz": 5, "radio_hz": 10, "screen_hz": 20}) == []
    assert len(proto.validate({"gps_hz": 7, "radio_hz": 50, "screen_hz": 0, "nope": 1, "radio_power_dbm": "x"})) == 5


def test_master_config_is_the_factory_layout(cfg):
    layout, problems = proto.layout_from_config(cfg)
    assert problems == []
    assert layout["radio"] == FACTORY_RADIO and layout["layout"] == 1
    assert proto.same_layout(layout, {"frames": FACTORY_FRAMES, "radio": FACTORY_RADIO})
    assert proto.packet_size(layout["radio"], True) == 68 == cfg.radio_size
    assert proto.source_number(cfg, "rpm") == 10 and proto.source_number(cfg, "brake_pressure") == 36
    assert proto.source_number(cfg, "battery") == 37 and proto.source_number(cfg, "gps_fix") == 45
    assert proto.source_number(cfg, "nope") is None


def test_config_the_daq_cant_supply_is_reported(cfg):
    c = cfg.copy()
    c.channels.append({"key": "steer", "name": "Steering", "source": {"type": "daq_input", "input": "A0"},
                       "scale": 1, "radio": "off"})
    c.data["radio_packet"]["fields"].append({"name": "steer", "channel": "steer", "type": "f32"})
    c.data["screen_frames"][1]["signals"].append({"channel": "steer", "name": "Steer", "byte": 4, "bits": 16,
                                                  "scale": 0.1})
    layout, problems = proto.layout_from_config(c)
    assert len(problems) == 2 and all("steer" in p for p in problems)
    assert len(layout["radio"]) == 21


SCRIPT = [
    ("GM,HELLO", 0, 0), ("GM,GET", 0, 0), ("GM,GETL", 0, 0), ("GM,DANCE", 0, 0),
    ("GM,SET,radio_hz=5,gps_hz=10", 0, 0), ("GM,SET,radio_hz=50", 0, 0), ("GM,SET,volume=11", 0, 0),
    ("GM,SET", 0, 0), ("GM,SET,radio_hz", 0, 0), ("GM,SET,radio_hz=-1", 0, 0), ("GM,SET,radio_hz=5=5", 0, 0),
    ("GM,GET", 0, 0), ("GM,SAVE", 1500, 0), ("GM,SET,radio_hz=4", 0, 30), ("GM,HELLO", 0, 30),
    ("GM,SAVE", 0, 0.4), ("GM,HELLO", 0, 0), ("GM,GET", 0, 0),
    ("GM,SF,4,604,5/0/16/0/1/1000,4/2/16/1/1/10", 0, 0), ("GM,SF,5,605,5/0/16/0/1/1000,9/1/16/1/1/10", 0, 0),
    ("GM,SF,5,600,5/0/16/0/1/1000", 0, 0), ("GM,SF,5,605,5/0/16", 0, 0), ("GM,SF,9,600", 0, 0),
    ("GM,SF,0,FFFF", 0, 0), ("GM,SF", 0, 0), ("GM,SF,0,600,1/0/16/0/x/1", 0, 0), ("GM,SF,3,603,42/0/16/0/0.1/3.5", 0, 0),
    ("GM,RP,0,10/2,4/3,5/6", 0, 0), ("GM,RPN,3", 0, 0), ("GM,SET,layout=7", 0, 0), ("GM,GETL", 0, 0),
    ("GM,GET", 0, 0), ("GM,SAVE", 0, 0), ("GM,RP", 0, 0), ("GM,RP,47,1/0,2/0", 0, 0), ("GM,RP,0,99/0", 0, 0),
    ("GM,RP,0,1/9", 0, 0), ("GM,RPN,0", 0, 0), ("GM,RPN,99", 0, 0), ("GM,RPN,40", 0, 0), ("GM,SAVE", 0, 0),
    ("GM,CANCEL", 0, 0), ("GM,GET", 0, 0), ("GM,FACTORY", 0, 0), ("GM,GET", 0, 0), ("GM,GETL", 0, 0),
    ("GM,SF,0,0", 0, 0), ("GM,SF,1,0", 0, 0), ("GM,GETL", 0, 0), ("GM,CANCEL", 0, 0),
]


def test_simulated_daq_answers_exactly_like_the_real_firmware_code(firmware):
    sim = DaqSim()
    for body, rpm, speed in SCRIPT:
        line = proto.build_line(*body.split(",")[1:2], *body.split(",")[2:])
        assert line == "$" + body + "*" + proto.checksum(body)
        assert sim.handle(line, rpm, speed) == firmware.handle(line, rpm, speed), body
    for junk in ("$GM,HELLO*00", "$GM,HELLO", "hello", "$GM,", "$GM,HELLO*ZZ", "[TX] RPM:0"):
        assert sim.handle(junk) == firmware.handle(junk), junk


def test_app_layout_commands_load_into_the_real_firmware(firmware, cfg):
    firmware.handle(proto.build_line("FACTORY"))
    layout, _ = proto.layout_from_config(cfg)
    for line in proto.layout_commands(layout):
        assert proto.parse_line(firmware.handle(line)[-1])[0] == "OK", line
    replies = [proto.parse_line(r) for r in firmware.handle(proto.build_line("GETL"))]
    assert proto.same_layout(proto.parse_layout(replies), layout)
    val = proto.key_values(proto.parse_line(firmware.handle(proto.build_line("GET"))[0])[1])
    assert val["packet"] == "68" and val["frames"] == "4" and val["fields"] == "21"
    assert firmware.send("!packet")[0].startswith("36325346") and len(firmware.send("!packet")[0]) == 136

    c = cfg.copy()
    c.data["screen_frames"].append({"id": "0x604", "name": "GRYPHON_PRESS", "signals": [
        {"channel": "oil_pressure", "name": "Oil", "byte": 0, "bits": 16, "signed": False, "scale": 0.01},
        {"channel": "lambda", "name": "Lambda", "byte": 2, "bits": 16, "signed": False, "scale": 0.001}]})
    c.data["radio_packet"]["fields"].append({"name": "water_pressure", "channel": "water_pressure", "type": "u16"})
    c.data["radio_packet"]["layout_version"] = 2
    custom, problems = proto.layout_from_config(c)
    assert problems == []
    for line in proto.layout_commands(custom) + [proto.build_line("SAVE")]:
        assert proto.parse_line(firmware.handle(line)[-1])[0] == "OK", line
    replies = [proto.parse_line(r) for r in firmware.handle(proto.build_line("GETL"))]
    got = proto.parse_layout(replies)
    assert proto.same_layout(got, custom) and not proto.same_layout(got, layout)
    packet = firmware.send("!packet")[0]
    assert packet.startswith("3732534602") and len(packet) == 2 * (5 + 64 + 2)
    assert proto.parse_line(firmware.handle(proto.build_line("FACTORY"))[0])[0] == "OK"


def test_simulated_daq_without_a_compiler():
    sim = DaqSim()
    assert proto.parse_line(sim.handle(proto.build_line("HELLO"))[0]) == \
        ("HELLO", ["fw=FS27-DAQ-2.0", "proto=2", "settings=0", "saved=0"])
    assert sim.handle(proto.build_line("SET", radio_hz=5)) == [proto.build_line("OK", settings=0)]
    assert sim.handle(proto.build_line("SAVE"), rpm=900) == [proto.build_line("ERR", "moving")]
    assert sim.handle(proto.build_line("SAVE")) == [proto.build_line("OK", settings=1)]
    assert sim.live["radio_hz"] == 5 and sim.saved
    assert sim.handle("[TX] RPM:0") == []


def run_client(client, device, rpm=0, speed=0, answer=True):
    now, result = 0.0, None
    for _ in range(400):
        sent = []
        result = client.poll(now, sent.append)
        if result is not None:
            return result
        for line in sent:
            if answer:
                for reply in device.handle(line, rpm, speed):
                    client.feed("[TX] RPM:0 noise")
                    client.feed(reply)
        now += 0.1
    raise AssertionError("the client never finished")


def test_client_reads_sends_verifies_and_resets(cfg):
    from gryphon_manager.core.daq_client import DaqClient
    sim, client = DaqSim(), DaqClient()
    client.read()
    r = run_client(client, sim)
    assert r["ok"] and r["hello"]["proto"] == "2" and r["val"]["packet"] == "68" and len(r["layout"]["frames"]) == 4
    client.send_rates({"gps_hz": 10, "radio_hz": 8, "screen_hz": 25})
    r = run_client(client, sim)
    assert r["ok"] and sim.live["radio_hz"] == 8 and sim.live["gps_hz"] == 10 and sim.live["counter"] == 1
    client.send_rates({"gps_hz": 10, "radio_hz": 4, "screen_hz": 25})
    r = run_client(client, sim, rpm=3000)
    assert not r["ok"] and r["code"] == "moving" and sim.live["radio_hz"] == 8
    c = cfg.copy()
    c.data["radio_packet"]["fields"].append({"name": "lambda", "channel": "lambda", "type": "f32"})
    layout, _ = proto.layout_from_config(c)
    client.send_layout(layout)
    r = run_client(client, sim)
    assert r["ok"] and sim.live["n_radio"] == 22 and sim.live["radio_hz"] == 8
    sim.flash_fail = True
    client.factory()
    r = run_client(client, sim)
    assert not r["ok"] and r["code"] == "flash" and sim.live["n_radio"] == 22
    sim.flash_fail = False
    client.factory()
    r = run_client(client, sim)
    assert r["ok"] and sim.live["radio_hz"] == 2 and sim.live["n_radio"] == 21 and r["val"]["packet"] == "68"


def test_client_with_v1_firmware_changes_nothing():
    from gryphon_manager.core.daq_client import DaqClient
    client, sent = DaqClient(), []
    client.send_rates({"gps_hz": 10, "radio_hz": 8, "screen_hz": 25})
    now, r = 0.0, None
    while r is None:
        r = client.poll(now, sent.append)
        client.feed("[TX] RPM:0 TPS:0.0 MAP:1.01 bar ECT:21.0 BAT:12.4 V")
        now += 0.1
    assert not r["ok"] and r["code"] == "old" and "older firmware" in r["error"]
    assert sent == [proto.build_line("HELLO")]


def test_client_notices_a_wrong_read_back():
    from gryphon_manager.core.daq_client import DaqClient

    class Forgetful(DaqSim):
        def handle(self, line, rpm=0, speed=0):
            out = super().handle(line, rpm, speed)
            if ",SAVE*" in line:
                self.live["radio_hz"] = self.pending["radio_hz"] = 2
            return out

    client = DaqClient()
    client.send_rates({"gps_hz": 5, "radio_hz": 9, "screen_hz": 20})
    r = run_client(client, Forgetful())
    assert not r["ok"] and r["code"] == "verify"
