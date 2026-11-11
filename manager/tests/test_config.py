import copy

import yaml

from gryphon_manager.core.config import MasterConfig


def test_shipped_config_is_valid_and_describes_todays_car(cfg):
    assert cfg.validate() == []
    assert cfg.radio_size == 68
    assert cfg.screen_ids == [0x600, 0x601, 0x602, 0x603]
    assert sorted(i for i, ext in cfg.by_id if ext) == list(range(0x14080600, 0x14080609))
    assert cfg.devices["ecu"]["ids"] == list(range(0x14080600, 0x14080609))
    assert cfg.devices["pdm"]["ids"] == []


def test_yaml_round_trip(cfg, tmp_path):
    again = MasterConfig(yaml.safe_load(cfg.dump_yaml()))
    assert again.data == cfg.data
    cfg.save(tmp_path / "c.yaml")
    assert MasterConfig.load(tmp_path / "c.yaml").data == cfg.data


def test_validation_catches_mistakes(cfg):
    c = cfg.copy()
    c.channels.append(copy.deepcopy(c.channels[0]))
    assert any("used twice" in p for p in c.validate())

    c = cfg.copy()
    c.channels.append({"key": "pdm_volts", "name": "PDM volts", "source": {"type": "can", "id": "0x500",
                       "byte": 0, "bits": 16}, "scale": 0.01, "units": "V", "radio": "off"})
    c.channels.append({"key": "pdm_amps", "name": "PDM amps", "source": {"type": "can", "id": "0x500",
                       "byte": 1, "bits": 16}, "scale": 0.1, "units": "A", "radio": "off"})
    c.compile()
    assert any("overlap" in p for p in c.validate())

    c = cfg.copy()
    c.channels.append({"key": "bad key", "name": "", "source": {"type": "nope"}})
    probs = c.validate()
    assert any("letters" in p for p in probs) and any("missing name" in p for p in probs)
    assert any("source type" in p for p in probs)

    c = cfg.copy()
    c.channels[0]["scale"] = 0
    c.channels[1]["source"]["slot"] = 7
    c.data["radio_packet"]["fields"][0]["channel"] = "ghost"
    probs = c.validate()
    assert any("scale" in p for p in probs) and any("slot" in p for p in probs)
    assert any("ghost" in p for p in probs)


def test_new_can_channel_decodes_and_lands_in_the_dbc(cfg):
    import cantools
    from gryphon_manager.core.engine import Engine
    from gryphon_manager.core.model import Frame
    c = cfg.copy()
    c.channels.append({"key": "pdm_volts", "name": "PDM volts", "group": "Electrics",
                       "source": {"type": "can", "id": "0x500", "byte": 2, "bits": 16, "order": "big",
                                  "signed": False}, "scale": 0.01, "units": "V", "radio": "slow"})
    c.compile()
    assert c.validate() == []
    e = Engine(c)
    e.on_frame(Frame(1.0, 0x500, False, bytes([0, 0, 0x05, 0x69, 0, 0, 0, 0])))
    assert abs(e.signals["pdm_volts"].value - 13.85) < 1e-9
    db = cantools.database.load_string(c.generate()["gryphon_fs27.dbc"], "dbc")
    assert abs(db.get_message_by_frame_id(0x500).decode(bytes([0, 0, 0x05, 0x69, 0, 0, 0, 0]))["PDM_volts"]
               - 13.85) < 1e-9


def test_generated_header(cfg):
    h = cfg.generate()["gryphon_channels.h"]
    assert "#define GRYPHON_PACKET_SIZE 68" in h
    assert "#define GRYPHON_PACKET_MAGIC 0x46533236u" in h
    assert "GRYPHON_CH_RPM," in h and "GRYPHON_CH_COUNT" in h
    body = h[h.index("typedef struct __attribute__((packed))"):]
    order = [line.split()[-1].rstrip(";") for line in body.splitlines()[1:] if line.startswith("    ")]
    assert order[:4] == ["magic", "latitude", "longitude", "gps_speed_kph"]
    assert order[-2:] == ["tx_count", "can_frame_count"]


def test_header_packet_matches_firmware_struct(cfg, repo):
    src = (repo / "FS26-DAQ_fs27.c").read_text()
    struct_src = src[src.index("typedef struct __attribute__((packed))"):src.index("} combined_telemetry_packet_t;")]
    theirs = [line.split("//")[0].split() for line in struct_src.splitlines()[1:] if ";" in line]
    theirs = [(t[0], t[1].rstrip(";")) for t in theirs]
    h = cfg.generate()["gryphon_channels.h"]
    body = h[h.index("typedef struct __attribute__((packed))"):h.index("} gryphon_telemetry_packet_t;")]
    ours = [tuple(line.split()) for line in body.splitlines()[1:] if ";" in line]
    ours = [(o[0], o[1].rstrip(";")) for o in ours]
    assert ours == theirs


def test_signal_list_is_json(cfg):
    import json
    data = json.loads(cfg.generate()["signals.json"])
    keys = [s["key"] for s in data["signals"]]
    assert "rpm" in keys and "daq.rpm" in keys and data["packet_size"] == 68
