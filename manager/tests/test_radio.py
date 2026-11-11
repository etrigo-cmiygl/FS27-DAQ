import pytest

from gryphon_manager.core.radio import (ReceiverParser, explain_daq_can, format_pkt_line, format_text_box,
                                        pack_packet, parse_daq_line, unpack_packet)

VALUES = {"gps_lat": 52.078613, "gps_lon": -1.016940, "gps_speed": 61.5, "gps_alt": 153.0, "gps_sats": 11,
          "gps_fix": 1, "rpm": 8450, "engine_temp": 88.5, "tps": 72.5, "oil_pressure": 3.75,
          "fuel_pressure": 3.0, "brake_pressure": 0.0, "battery": 13.85, "wheel_speed_fr": 61,
          "wheel_speed_fl": 61, "wheel_speed_rr": 62, "wheel_speed_rl": 62, "g_lateral": 1.0, "heading": 270.0,
          "tx_count": 1234, "can_count": 40000}


def test_packet_is_68_bytes_with_fs26_magic(cfg):
    raw = pack_packet(cfg, VALUES)
    assert len(raw) == 68 == cfg.radio_size
    assert raw[:4] == (0x46533236).to_bytes(4, "little")
    assert raw[4:8] == __import__("struct").pack("<f", 52.078613)
    assert raw[20:22] == bytes([11, 1])
    assert raw[22:24] == (8450).to_bytes(2, "little")
    assert raw[64:68] == (1234).to_bytes(2, "little") + (40000).to_bytes(2, "little")


def test_packet_round_trip(cfg):
    out = unpack_packet(cfg, pack_packet(cfg, VALUES))
    for k, v in VALUES.items():
        assert out[k] == pytest.approx(v, rel=1e-6), k


def test_bad_packets_rejected(cfg):
    raw = pack_packet(cfg, VALUES)
    assert unpack_packet(cfg, raw[:-1]) is None
    assert unpack_packet(cfg, b"\x00" + raw[1:]) is None


def test_fs26_text_box(cfg):
    p = ReceiverParser(cfg)
    pkt = None
    for line in format_text_box(VALUES, -71, 9, 55):
        pkt = p.feed(line, 5.0) or pkt
    assert pkt is not None and p.format == "FS26 text box"
    assert pkt.rssi == -71 and pkt.snr == 9
    assert pkt.values["rpm"] == 8450 and pkt.values["gps_fix"] == 1
    assert pkt.values["gps_lat"] == pytest.approx(52.078613)
    assert pkt.values["battery"] == pytest.approx(13.85)
    assert pkt.values["wheel_speed_rl"] == 62 and pkt.values["tx_count"] == 1234
    assert pkt.values["heading"] == pytest.approx(270.0)


def test_text_box_real_firmware_lines(cfg):
    p = ReceiverParser(cfg)
    lines = [
        "[LORA] Listening for combined GPS + CAN telemetry...",
        "║  GPS:  53.806700, -1.555000                                  ║",
        "║  GPS Spd: 0.0 kph | Alt: 61.2 m | Sat: 0 | Fix: No Fix   ║",
        "║  RPM: 0 | TPS: 0.0% | Eng: 20.0 C | Oil: 0.00 Bar ║",
        "║  Fuel: 0.00 Bar | Brake: 0.00 Bar | Volt: 0.00 V ║",
        "║  Wheels FR/FL/RR/RL: 0/0/0/0                 ║",
        "║  Lateral G: 0.00 | Heading: 0.0 deg              ║",
        "║  TX Count: 7 | CAN Frames: 63                     ║",
        "║  RSSI: -48 dBm  |  SNR: 12 dB  |  RX Count: 7              ║",
        "[STATS] RX Success: 7 | Header Errors: 0 | CRC Errors: 1 | Timeouts: 0",
    ]
    got = [p.feed(line, 1.0) for line in lines]
    pkt = [g for g in got if g][0]
    assert pkt.values["gps_fix"] == 0 and pkt.values["engine_temp"] == 20.0 and pkt.values["can_count"] == 63
    assert p.stats["CRC Errors"] == 1


def test_pkt_line(cfg):
    raw = pack_packet(cfg, VALUES)
    line = format_pkt_line(raw, -80, 7)
    assert line.startswith("PKT,-80,7,") and len(line.split(",")[3]) == 136
    p = ReceiverParser(cfg)
    pkt = p.feed(line, 2.0)
    assert pkt.raw == raw and pkt.rssi == -80 and pkt.values["rpm"] == 8450
    assert p.feed("PKT,-80,7,ZZ", 2.0) is None
    assert p.feed("PKT,-80,7," + "00" * 68, 2.0) is None
    assert p.bad_lines == 2


def test_daq_debug_lines():
    tx = parse_daq_line("[TX] RPM:1650 | Batt:0.00 | TPS:1.500 | EngineTemp:20.0 | TX#12 CAN#108", 1.0)
    assert tx.kind == "TX" and tx.values == {"rpm": 1650, "battery": 0.0, "tps": 1.5, "engine_temp": 20.0,
                                             "tx_count": 12, "can_count": 108}
    ecu = parse_daq_line("[ECU] MAP:1.013 bar | AirTemp:22.0 | Oil:0.00 bar | Fuel:3.01 bar | "
                         "Water:0.10 bar | Lambda:0.998", 1.0)
    assert ecu.values["map"] == 1.013 and ecu.values["lambda"] == 0.998 and ecu.values["fuel_pressure"] == 3.01
    gps = parse_daq_line("[GPS] Sats:9 | Fix:1 | Speed:0.4 kph", 1.0)
    assert gps.values == {"gps_sats": 9, "gps_fix": 1, "gps_speed": 0.4}
    can = parse_daq_line("[CAN] TEC:0 | REC:0 | EFLG:0x00 | TXB0CTRL:0x00 | RX:1234", 1.0)
    assert can.values == {"tec": 0, "rec": 0, "eflg": 0, "txb0ctrl": 0, "rx": 1234}
    assert parse_daq_line("[TX] FAILED #4", 1.0).kind == "TXFAIL"
    assert parse_daq_line("GPS Configured: 57600 baud, 5Hz", 1.0).kind == "BOOT"
    assert parse_daq_line("random noise", 1.0) is None


def test_can_line_explained_in_plain_english():
    assert explain_daq_can({"tec": 0, "rec": 0, "eflg": 0, "txb0ctrl": 0})[0] == "green"
    status, text = explain_daq_can({"tec": 130, "rec": 0, "eflg": 0x15, "txb0ctrl": 0x18})
    assert status == "red" and "failing" in text
    assert explain_daq_can({"tec": 255, "rec": 0, "eflg": 0x20, "txb0ctrl": 0x08})[0] == "red"
    assert explain_daq_can({"tec": 0, "rec": 0, "eflg": 0x40, "txb0ctrl": 0})[0] == "amber"
