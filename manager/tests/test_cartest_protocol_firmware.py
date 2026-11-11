from conftest import run_sim
from gryphon_manager.core import daq_protocol as proto
from gryphon_manager.core import firmware as fw
from gryphon_manager.core.cartest import STEPS, build_report_html, evaluate, overall, suggest
from gryphon_manager.core.engine import Engine


def labels(checks):
    return {c.label: c.ok for c in checks}


def test_termination_readings(cfg):
    e = Engine(cfg)
    assert evaluate("wiring", e, {})[0].ok is None
    assert evaluate("wiring", e, {"ohms": "60.4"})[0].ok is True
    one = evaluate("wiring", e, {"ohms": "119"})[0]
    assert one.ok is False and "one terminator" in one.detail
    three = evaluate("wiring", e, {"ohms": "40"})[0]
    assert three.ok is False and "three" in three.detail and "DAQ" in three.detail
    assert "broken" in evaluate("wiring", e, {"ohms": "45000"})[0].detail
    assert evaluate("wiring", e, {"ohms": "abc"})[0].ok is None


def test_engine_off_steps_pass_on_a_healthy_car(cfg):
    e, _ = run_sim(cfg, 8, mode="off")
    for key in ("ecu", "engine_off", "daq"):
        checks = evaluate(key, e, {})
        assert suggest(checks) == "pass", (key, [(c.label, c.ok, c.detail) for c in checks])
    assert suggest(evaluate("wiring", e, {"ohms": 60})) == "pass"
    assert suggest(evaluate("running", e, {})) == "fail"


def test_engine_running_step(cfg):
    e, _ = run_sim(cfg, 10, mode="idle")
    assert suggest(evaluate("running", e, {})) == "pass"
    assert labels(evaluate("engine_off", e, {}))["RPM is 0"] is False
    e2, _ = run_sim(cfg, 10, mode="idle", fault="battery_zero")
    checks = evaluate("running", e2, {})
    assert labels(checks)["Battery charging"] is None and suggest(checks) == "pending"
    e3, _ = run_sim(cfg, 10, mode="idle", fault="low_oil")
    assert labels(evaluate("running", e3, {}))["Oil pressure"] is False


def test_faults_fail_the_right_step(cfg):
    e, _ = run_sim(cfg, 12, mode="off", fault="ecu_1hz")
    checks = evaluate("ecu", e, {})
    assert labels(checks)["Broadcast rate"] is False and suggest(checks) == "fail"
    e2, _ = run_sim(cfg, 10, mode="idle", fault="daq_wrong")
    assert labels(evaluate("daq", e2, {}))["RPM matches the ECU"] is False
    e3, _ = run_sim(cfg, 8, mode="off", fault="daq_missing")
    assert suggest(evaluate("daq", e3, {})) == "fail"


def test_screen_and_ftmanager_steps(cfg):
    e, _ = run_sim(cfg, 8, mode="idle")
    ticks = {k: True for k, _, kind in STEPS[4].inputs}
    assert suggest(evaluate("screen", e, ticks)) == "pass"
    ticks["scr_gps"] = False
    assert suggest(evaluate("screen", e, ticks)) == "fail"
    assert suggest(evaluate("ftmanager", e, {})) == "pending"
    rpm = e.value("rpm")
    good = evaluate("ftmanager", e, {"ft_rpm": str(rpm + 40), "ft_engine_temp": f"{e.value('engine_temp'):.1f}"})
    assert suggest(good) == "pass"
    bad = evaluate("ftmanager", e, {"ft_rpm": str(rpm + 900)})
    assert suggest(bad) == "fail"


def test_report(cfg):
    e, _ = run_sim(cfg, 8, mode="off")
    results = {}
    for s in STEPS[:4]:
        results[s.key] = {"result": "pass", "notes": "", "checks": evaluate(s.key, e, {"ohms": 60}),
                          "inputs": {"ohms": 60} if s.key == "wiring" else {}}
    assert overall(results) == "INCOMPLETE"
    for s in STEPS[4:]:
        results[s.key] = {"result": "skip", "notes": "", "checks": [], "inputs": {}}
    assert overall(results) == "PASS"
    results["screen"] = {"result": "fail", "notes": "Screen shows <zeros>", "checks": [], "inputs": {}}
    assert overall(results) == "FAIL"
    html = build_report_html({"tester": "HP", "car": "F27", "source": "Simulator", "log": "can.blf"}, results)
    assert "Result: FAIL" in html and "Screen shows &lt;zeros&gt;" in html
    assert "two terminators" in html and "Multimeter reading" in html and "can.blf" in html
    for s in STEPS:
        assert s.title in html


def test_settings_protocol_lines():
    line = proto.build_line("SET", gps_hz=10, radio_hz=5)
    assert line.startswith("$GM,SET,gps_hz=10,radio_hz=5*") and len(line.split("*")[1]) == 2
    assert proto.parse_line(line) == ("SET", {"gps_hz": "10", "radio_hz": "5"})
    assert proto.parse_line(line[:-1] + ("0" if line[-1] != "0" else "1")) is None
    assert proto.parse_line("[TX] RPM:0") is None
    cmd, vals = proto.parse_line(proto.build_line("ERR") .replace("ERR", "ERR")) or ("", {})
    assert cmd == "ERR"
    body = "GM,ERR,moving"
    assert proto.parse_line(f"${body}*{proto.checksum(body)}") == ("ERR", {"_": "moving"})
    assert proto.checksum("PMTK251,57600") == "2C"


def test_settings_protocol_validation_and_can():
    assert proto.validate({"gps_hz": 5, "radio_hz": 10, "sd_log": 1, "ch.rpm": "fast"}) == []
    probs = proto.validate({"gps_hz": 7, "radio_hz": 50, "radio_power_dbm": 22, "nope": 1, "ch.rpm": "x"})
    assert len(probs) == 5
    frame = proto.build_can("SET", "radio_hz", 5, seq=9)
    assert len(frame) == 8
    assert proto.parse_can(frame) == {"command": 0x02, "is_reply": False, "key": "radio_hz", "value": 5, "seq": 9}
    assert proto.parse_can(frame[:7] + bytes([frame[7] ^ 1])) is None
    assert proto.CAN_ID_REQUEST not in range(0x600, 0x604)


def test_firmware_helpers(tmp_path):
    good = tmp_path / "FS27-DAQ.uf2"
    block = b"UF2\n" + (0x9E5D5157).to_bytes(4, "little") + bytes(504)
    good.write_bytes(block * 3)
    assert fw.check_uf2(good) == ""
    bad = tmp_path / "x.uf2"
    bad.write_bytes(b"hello")
    assert fw.check_uf2(bad) != ""
    drive = tmp_path / "RP2350"
    drive.mkdir()
    fw.flash(good, str(drive))
    assert (drive / "FS27-DAQ.uf2").read_bytes() == good.read_bytes()
    assert fw.is_rp2350("RP2350") and fw.is_rp2350("Raspberry Pi Pico 2") and not fw.is_rp2350("RPI-RP2")
    releases = [
        {"tag_name": "manager-v1.2.0", "assets": [{"name": "GryphonManager-windows.zip",
                                                    "browser_download_url": "u"}], "html_url": "h"},
        {"tag_name": "manager-v0.9.0", "assets": [], "html_url": "h0"},
        {"tag_name": "fw-v3", "published_at": "2027-01-05T10:00:00Z",
         "assets": [{"name": "FS27-DAQ.uf2", "browser_download_url": "dl", "size": 1536}]},
    ]
    assert fw.latest_firmware(releases)["tag"] == "fw-v3"
    assert fw.latest_firmware(releases[:2]) is None
    assert fw.newer_manager(releases, "1.0.0")["version"] == "1.2.0"
    assert fw.newer_manager(releases, "1.2.0") is None
    assert fw.version_tuple("v1.10.2") > fw.version_tuple("1.9.9")
