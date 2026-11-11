import cantools
import pytest

from gryphon_manager.core.engine import Engine
from gryphon_manager.core.model import Frame


def feed(cfg, frames):
    e = Engine(cfg)
    for i, (cid, ext, data) in enumerate(frames):
        e.on_frame(Frame(100.0 + i * 0.01, cid, ext, bytes(data)))
    return e


def test_ft550_matches_firmware_desk_test(cfg):
    e = feed(cfg, [
        (0x14080600, True, [0x02, 0x8A, 0x03, 0xF5, 0x00, 0xFA, 0x03, 0x84]),
        (0x14080601, True, [0x0F, 0xA0, 0x0B, 0xB8, 0x00, 0x64, 0x00, 0x03]),
        (0x14080602, True, [0x03, 0xE8, 0x1F, 0x40, 0xFF, 0x9C, 0x00, 0x01]),
        (0x14080603, True, [0x00, 0x50, 0x00, 0x51, 0x00, 0x52, 0x00, 0x53]),
    ])
    want = {"tps": 65.0, "map": 1.013, "air_temp": 25.0, "engine_temp": 90.0, "oil_pressure": 4.0,
            "fuel_pressure": 3.0, "water_pressure": 0.1, "gear": 3, "lambda": 1.0, "rpm": 8000,
            "oil_temp": -10.0, "pit_limit": 1, "wheel_speed_fr": 80, "wheel_speed_fl": 81,
            "wheel_speed_rr": 82, "wheel_speed_rl": 83}
    for key, value in want.items():
        assert e.signals[key].value == pytest.approx(value, abs=1e-6), key


def test_ft550_scalings_follow_decoder_not_dbc(cfg):
    e = feed(cfg, [
        (0x14080604, True, [0, 5, 0, 30, 0, 7, 1, 0x0E]),
        (0x14080606, True, [0, 2, 0xFF, 0xFF, 0, 9, 0, 4]),
        (0x14080607, True, [0, 3, 0x01, 0x2C, 0x00, 0xC8, 0x00, 0xC9]),
        (0x14080608, True, [0x03, 0x20, 0x02, 0xBC, 0x00, 0x05, 0x4E, 0x20]),
    ])
    s = e.signals
    assert s["tc_retard"].value == 30 and s["heading"].value == 270
    assert s["g_accel"].value == 2 and s["g_lateral"].value == -1 and s["yaw_frontal"].value == 9
    assert s["lambda_correction"].value == 3
    assert s["fuel_flow"].value == pytest.approx(3.0)
    assert s["inj_time_a"].value == pytest.approx(2.0)
    assert s["trans_oil_temp"].value == pytest.approx(80.0)
    assert s["brake_pressure"].value == pytest.approx(20.0)
    for key in ("tc_retard", "heading", "g_accel", "g_lateral", "yaw_frontal", "yaw_lateral",
                "lambda_correction", "fuel_flow"):
        assert "ftcan_packet.dbc" in s[key].note, key


def test_wheel_speed_and_rpm_are_unsigned(cfg):
    e = feed(cfg, [(0x14080602, True, [0, 0, 0xFF, 0xFE, 0, 0, 0, 0])])
    assert e.signals["rpm"].value == 65534


def test_screen_frames(cfg):
    e = feed(cfg, [
        (0x600, False, (8000).to_bytes(2, "little") + (1013).to_bytes(2, "little")
         + (-105).to_bytes(2, "little", signed=True) + (650).to_bytes(2, "little")),
        (0x601, False, (1385).to_bytes(2, "little") + (250).to_bytes(2, "little") + bytes(4)),
        (0x602, False, (520786100).to_bytes(4, "little", signed=True)
         + (-10169400).to_bytes(4, "little", signed=True)),
        (0x603, False, (456).to_bytes(2, "little") + bytes([11, 1]) + (300).to_bytes(2, "little")
         + (9000).to_bytes(2, "little")),
    ])
    s = e.signals
    assert s["daq.rpm"].value == 8000
    assert s["daq.map"].value == pytest.approx(101.3)
    assert s["daq.engine_temp"].value == pytest.approx(-10.5)
    assert s["daq.tps"].value == pytest.approx(65.0)
    assert s["daq.battery"].value == pytest.approx(13.85)
    assert s["daq.air_temp"].value == pytest.approx(25.0)
    assert s["daq.gps_lat"].value == pytest.approx(52.07861)
    assert s["daq.gps_lon"].value == pytest.approx(-1.01694)
    assert s["daq.gps_speed"].value == pytest.approx(45.6)
    assert s["daq.gps_sats"].value == 11 and s["daq.gps_fix"].value == 1
    assert s["daq.tx_count"].value == 300 and s["daq.can_count"].value == 9000


def test_short_frame_does_not_crash(cfg):
    e = feed(cfg, [(0x600, False, [1, 2, 3]), (0x14080600, True, [])])
    assert e.signals["daq.rpm"].value == 513
    assert e.signals["daq.tps"].value is None


def test_screen_dbc_matches_the_one_in_the_screen(cfg, repo):
    theirs = cantools.database.load_file(str(repo / "custom_packet.dbc"))
    ours = cantools.database.load_string(cfg.generate()["gryphon_screen.dbc"], "dbc")
    assert {m.frame_id for m in ours.messages} == {m.frame_id for m in theirs.messages}
    for m in theirs.messages:
        o = ours.get_message_by_frame_id(m.frame_id)
        assert o.name == m.name
        assert {s.name for s in o.signals} == {s.name for s in m.signals}
        for s in m.signals:
            g = o.get_signal_by_name(s.name)
            assert (g.start, g.length, g.byte_order, g.is_signed) == (s.start, s.length, s.byte_order, s.is_signed)
            assert g.scale == pytest.approx(s.scale) and g.offset == pytest.approx(s.offset)


def test_ft550_layout_matches_ftcan_dbc(cfg, repo):
    theirs = cantools.database.load_file(str(repo / "ftcan_packet.dbc"))
    assert len(theirs.messages) == 9
    for m in theirs.messages:
        defs = {d.dbc_start: d for d in cfg.by_id[(m.frame_id, True)]}
        assert len(defs) == 4
        for s in m.signals:
            d = defs[s.start]
            assert s.length == d.bits and s.byte_order == "big_endian"
            if d.scale != pytest.approx(s.scale):
                assert "ftcan_packet.dbc" in d.note, f"{d.key}: scale differs from the DBC but isn't flagged"


def test_team_dbc_decodes_like_the_app(cfg):
    db = cantools.database.load_string(cfg.generate()["gryphon_fs27.dbc"], "dbc")
    data = bytes([0x02, 0x8A, 0x03, 0xF5, 0xFF, 0x06, 0x03, 0x84])
    for (cid, ext), defs in cfg.by_id.items():
        msg = db.get_message_by_frame_id(cid)
        assert msg.is_extended_frame == ext
        decoded = msg.decode(data, decode_choices=False)
        names = {s.name for s in msg.signals}
        assert len(names) == len(defs)
        for d in defs:
            assert decoded[d.dbc_name] == pytest.approx(d.decode(data)), d.key
