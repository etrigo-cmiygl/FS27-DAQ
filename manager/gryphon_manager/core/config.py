from __future__ import annotations

import copy
import json
import struct
from dataclasses import dataclass
from pathlib import Path

import yaml

from .model import fmt_id, parse_id_list, parse_int

SOURCE_TYPES = ("ecu", "can", "gps", "daq", "daq_input")
RADIO_RATES = ("off", "slow", "fast")
FIELD_TYPES = {"u8": "B", "i8": "b", "u16": "H", "i16": "h", "u32": "I", "i32": "i", "f32": "f"}
C_TYPES = {"u8": "uint8_t", "i8": "int8_t", "u16": "uint16_t", "i16": "int16_t",
           "u32": "uint32_t", "i32": "int32_t", "f32": "float"}
FT550_FIRST = 0x14080600
FT550_LAST = 0x14080608

from .paths import bundled_config_path

DEFAULT_CONFIG_PATH = bundled_config_path()


@dataclass(slots=True)
class SignalDef:
    key: str
    name: str
    units: str
    scale: float
    offset: float
    can_id: int
    ext: bool
    byte: int
    bits: int
    order: str
    signed: bool
    bit: int = 0
    group: str = ""
    vmin: float | None = None
    vmax: float | None = None
    note: str = ""
    dbc_name: str = ""

    def raw(self, data: bytes) -> int | None:
        nbytes = (self.bit + self.bits + 7) // 8
        if self.byte + nbytes > len(data):
            return None
        if self.bits % 8 == 0 and self.bit == 0:
            return int.from_bytes(data[self.byte:self.byte + nbytes], self.order, signed=self.signed)
        value = int.from_bytes(data[self.byte:self.byte + nbytes], "little") >> self.bit
        value &= (1 << self.bits) - 1
        if self.signed and value >= 1 << (self.bits - 1):
            value -= 1 << self.bits
        return value

    def decode(self, data: bytes) -> float | None:
        raw = self.raw(data)
        if raw is None:
            return None
        return raw * self.scale + self.offset

    def encode_into(self, buf: bytearray, value: float) -> None:
        raw = int(round((value - self.offset) / self.scale)) if self.scale else 0
        nbytes = self.bits // 8
        lo = -(1 << (self.bits - 1)) if self.signed else 0
        hi = (1 << (self.bits - 1)) - 1 if self.signed else (1 << self.bits) - 1
        raw = max(lo, min(hi, raw))
        buf[self.byte:self.byte + nbytes] = raw.to_bytes(nbytes, self.order, signed=self.signed)

    @property
    def dbc_start(self) -> int:
        if self.order == "big":
            return self.byte * 8 + 7
        return self.byte * 8 + self.bit


class ConfigError(Exception):
    pass


class MasterConfig:
    def __init__(self, data: dict, path: Path | None = None):
        self.data = data
        self.path = path
        self.compile()

    @classmethod
    def load(cls, path: Path | str | None = None) -> "MasterConfig":
        p = Path(path) if path else DEFAULT_CONFIG_PATH
        with open(p, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls(data, p)

    def copy(self) -> "MasterConfig":
        return MasterConfig(copy.deepcopy(self.data), self.path)

    @property
    def version(self) -> int:
        return int(self.data.get("version", 1))

    @property
    def channels(self) -> list[dict]:
        return self.data.setdefault("channels", [])

    def channel(self, key: str) -> dict | None:
        for ch in self.channels:
            if ch.get("key") == key:
                return ch
        return None

    def compile(self) -> None:
        for ch in self.channels:
            if ch.get("radio") is False or ch.get("radio") is None:
                ch["radio"] = "off"
            elif ch.get("radio") is True:
                ch["radio"] = "fast"
        self.by_id: dict[tuple[int, bool], list[SignalDef]] = {}
        self.signal_defs: dict[str, SignalDef] = {}
        self.screen_ids: list[int] = []
        for ch in self.channels:
            src = ch.get("source") or {}
            stype = src.get("type")
            try:
                if stype == "ecu":
                    sd = SignalDef(
                        key=ch["key"], name=ch.get("name", ch["key"]), units=ch.get("units", "") or "",
                        scale=float(ch.get("scale", 1)), offset=float(ch.get("offset", 0)),
                        can_id=parse_int(src["id"]), ext=True, byte=int(src["slot"]) * 2, bits=16,
                        order="big", signed=bool(ch.get("signed", True)), group=ch.get("group", ""),
                        vmin=ch.get("min"), vmax=ch.get("max"), note=ch.get("note", "") or "",
                        dbc_name=_dbc_name(ch.get("name", ch["key"])))
                elif stype == "can":
                    sd = SignalDef(
                        key=ch["key"], name=ch.get("name", ch["key"]), units=ch.get("units", "") or "",
                        scale=float(ch.get("scale", 1)), offset=float(ch.get("offset", 0)),
                        can_id=parse_int(src["id"]), ext=bool(src.get("extended", parse_int(src["id"]) > 0x7FF)),
                        byte=int(src.get("byte", 0)), bits=int(src.get("bits", 16)),
                        order=src.get("order", "little"), signed=bool(src.get("signed", False)),
                        bit=int(src.get("bit", 0)), group=ch.get("group", ""),
                        vmin=ch.get("min"), vmax=ch.get("max"), note=ch.get("note", "") or "",
                        dbc_name=_dbc_name(ch.get("name", ch["key"])))
                else:
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            self.by_id.setdefault((sd.can_id, sd.ext), []).append(sd)
            self.signal_defs[sd.key] = sd
        for fr in self.data.get("screen_frames", []) or []:
            try:
                fid = parse_int(fr["id"])
            except (KeyError, ValueError):
                continue
            self.screen_ids.append(fid)
            for sg in fr.get("signals", []) or []:
                ch = self.channel(sg.get("channel", "")) or {}
                try:
                    sd = SignalDef(
                        key="daq." + sg["channel"], name="DAQ to screen: " + ch.get("name", sg["channel"]),
                        units=sg.get("units", "") or "", scale=float(sg.get("scale", 1)), offset=0.0,
                        can_id=fid, ext=False, byte=int(sg["byte"]), bits=int(sg["bits"]), order="little",
                        signed=bool(sg.get("signed", False)), group="DAQ screen frames",
                        vmin=sg.get("min"), vmax=sg.get("max"), dbc_name=sg.get("name", sg["channel"]))
                except (KeyError, ValueError, TypeError):
                    continue
                self.by_id.setdefault((fid, False), []).append(sd)
                self.signal_defs[sd.key] = sd
        self.devices: dict[str, dict] = {}
        for key, dev in (self.data.get("devices") or {}).items():
            try:
                ids = parse_id_list(dev.get("ids"))
            except ValueError:
                ids = []
            self.devices[key] = {
                "label": dev.get("label", key), "ids": ids,
                "extended": bool(dev.get("extended", False)),
                "expected_hz": float(dev.get("expected_hz", 0) or 0),
            }
        rp = self.data.get("radio_packet") or {}
        self.radio_magic = parse_int(rp.get("magic", "0x46533236"))
        self.radio_fields: list[tuple[str, str, str]] = []
        fmt = "<I"
        for f in rp.get("fields", []) or []:
            if f.get("type") in FIELD_TYPES:
                self.radio_fields.append((f.get("name", f.get("channel", "")), f.get("channel", ""), f["type"]))
                fmt += FIELD_TYPES[f["type"]]
        self.radio_struct = struct.Struct(fmt)

    @property
    def radio_size(self) -> int:
        return self.radio_struct.size

    def validate(self) -> list[str]:
        problems: list[str] = []
        seen: set[str] = set()
        usage: dict[tuple[int, bool], list[tuple[int, int, str]]] = {}
        for i, ch in enumerate(self.channels):
            label = ch.get("key") or f"row {i + 1}"
            key = ch.get("key")
            if not key:
                problems.append(f"Row {i + 1}: missing key (short name with no spaces).")
            elif not str(key).replace("_", "").isalnum():
                problems.append(f"{label}: key can only use letters, numbers and underscores.")
            elif key in seen:
                problems.append(f"{label}: key is used twice.")
            seen.add(key)
            if not ch.get("name"):
                problems.append(f"{label}: missing name.")
            src = ch.get("source") or {}
            stype = src.get("type")
            if stype not in SOURCE_TYPES:
                problems.append(f"{label}: source type must be one of {', '.join(SOURCE_TYPES)}.")
                continue
            try:
                scale = float(ch.get("scale", 1))
                if scale == 0:
                    problems.append(f"{label}: scale can't be 0.")
            except (TypeError, ValueError):
                problems.append(f"{label}: scale isn't a number.")
            if ch.get("radio", "off") not in RADIO_RATES:
                problems.append(f"{label}: radio must be off, slow or fast.")
            lo, hi = ch.get("min"), ch.get("max")
            if lo is not None and hi is not None:
                try:
                    if float(lo) >= float(hi):
                        problems.append(f"{label}: min must be below max.")
                except (TypeError, ValueError):
                    problems.append(f"{label}: min/max aren't numbers.")
            if stype == "ecu":
                try:
                    cid = parse_int(src.get("id"))
                    slot = int(src.get("slot"))
                except (TypeError, ValueError):
                    problems.append(f"{label}: ECU source needs an id and a slot (0-3).")
                    continue
                if not FT550_FIRST <= cid <= FT550_LAST:
                    problems.append(f"{label}: ECU id {fmt_id(cid, True)} isn't an FT550 simplified frame.")
                if not 0 <= slot <= 3:
                    problems.append(f"{label}: slot must be 0-3.")
                    continue
                usage.setdefault((cid, True), []).append((slot * 16, 16, label))
            elif stype == "can":
                try:
                    cid = parse_int(src.get("id"))
                    byte = int(src.get("byte", 0))
                    bits = int(src.get("bits", 16))
                    bit = int(src.get("bit", 0))
                except (TypeError, ValueError):
                    problems.append(f"{label}: CAN source needs id, byte and bits.")
                    continue
                if src.get("order", "little") not in ("little", "big"):
                    problems.append(f"{label}: order must be little or big.")
                if bits < 1 or byte * 8 + bit + bits > 64:
                    problems.append(f"{label}: byte {byte} + {bits} bits doesn't fit in an 8-byte frame.")
                    continue
                if bits >= 8 and (bits % 8 or bit):
                    problems.append(f"{label}: signals of 8 bits or more must be whole bytes.")
                ext = bool(src.get("extended", cid > 0x7FF))
                if (cid, ext) in [(i_, False) for i_ in self.screen_ids] and not ext:
                    problems.append(f"{label}: {fmt_id(cid, ext)} is already used by a DAQ screen frame.")
                usage.setdefault((cid, ext), []).append((byte * 8 + bit, bits, label))
            elif stype in ("gps", "daq") and not src.get("field"):
                problems.append(f"{label}: {stype} source needs a field.")
            elif stype == "daq_input" and not src.get("input"):
                problems.append(f"{label}: DAQ input source needs an input name (e.g. A0).")
        for (cid, ext), spans in usage.items():
            spans.sort()
            for (s1, l1, n1), (s2, l2, n2) in zip(spans, spans[1:]):
                if s2 < s1 + l1:
                    problems.append(f"{n1} and {n2} overlap in frame {fmt_id(cid, ext)}.")
        frame_ids: set[int] = set()
        for fr in self.data.get("screen_frames", []) or []:
            try:
                fid = parse_int(fr.get("id"))
            except (TypeError, ValueError):
                problems.append("A screen frame has no valid id.")
                continue
            if fid in frame_ids:
                problems.append(f"Screen frame {fmt_id(fid, False)} is listed twice.")
            frame_ids.add(fid)
            spans = []
            for sg in fr.get("signals", []) or []:
                if sg.get("channel") not in seen:
                    problems.append(f"Screen frame {fmt_id(fid, False)}: unknown channel '{sg.get('channel')}'.")
                try:
                    start, bits = int(sg["byte"]) * 8, int(sg["bits"])
                except (KeyError, TypeError, ValueError):
                    problems.append(f"Screen frame {fmt_id(fid, False)}: signal needs byte and bits.")
                    continue
                if start + bits > 64:
                    problems.append(f"Screen frame {fmt_id(fid, False)}: {sg.get('name')} doesn't fit.")
                spans.append((start, bits, sg.get("name", sg.get("channel", "?"))))
            spans.sort()
            for (s1, l1, n1), (s2, l2, n2) in zip(spans, spans[1:]):
                if s2 < s1 + l1:
                    problems.append(f"{n1} and {n2} overlap in screen frame {fmt_id(fid, False)}.")
        for f in (self.data.get("radio_packet") or {}).get("fields", []) or []:
            if f.get("channel") not in seen:
                problems.append(f"Radio packet: unknown channel '{f.get('channel')}'.")
            if f.get("type") not in FIELD_TYPES:
                problems.append(f"Radio packet: field '{f.get('name')}' has an unknown type.")
        for key, dev in (self.data.get("devices") or {}).items():
            try:
                parse_id_list(dev.get("ids"))
            except ValueError:
                problems.append(f"Device {key}: IDs aren't valid (use 0x500 or 0x500-0x503).")
        return problems

    def dump_yaml(self) -> str:
        d = self.data
        out = [
            "# Gryphon master config. One list of every channel on the car.",
            "# Edit it in Gryphon Manager (Channels view) or by hand, then press Generate.",
            f"version: {self.version}",
            f"name: {json.dumps(d.get('name', ''))}",
            "bus: " + _flow(d.get("bus", {"bitrate": 1000000})),
            "",
            "devices:",
        ]
        for key, dev in (d.get("devices") or {}).items():
            out.append(f"  {key}: {_flow(dev)}")
        out += ["", "channels:"]
        for ch in self.channels:
            out.append("  - " + _flow(ch))
        out += ["", "screen_frames:"]
        for fr in d.get("screen_frames", []) or []:
            out.append(f"  - id: {json.dumps(str(fr.get('id')))}")
            out.append(f"    name: {fr.get('name', '')}")
            out.append("    signals:")
            for sg in fr.get("signals", []) or []:
                out.append("      - " + _flow(sg))
        rp = d.get("radio_packet") or {}
        out += ["", "radio_packet:", f"  magic: {json.dumps(str(rp.get('magic', '0x46533236')))}",
                f"  layout_version: {rp.get('layout_version', 1)}", "  fields:"]
        for f in rp.get("fields", []) or []:
            out.append("    - " + _flow(f))
        return "\n".join(out) + "\n"

    def save(self, path: Path | str | None = None) -> Path:
        p = Path(path) if path else self.path
        if p is None:
            raise ConfigError("no path to save the config to")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.dump_yaml(), encoding="utf-8")
        self.path = p
        return p

    def generate(self) -> dict[str, str]:
        from . import generators
        return {
            "gryphon_fs27.dbc": generators.team_dbc(self),
            "gryphon_screen.dbc": generators.screen_dbc(self),
            "gryphon_channels.h": generators.c_header(self),
            "signals.json": generators.signal_list(self),
        }


def _dbc_name(name: str) -> str:
    out = "".join(c if c.isalnum() else "_" for c in name.strip())
    while "__" in out:
        out = out.replace("__", "_")
    out = out.strip("_") or "Signal"
    return out if not out[0].isdigit() else "S_" + out


def _scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, int):
        return repr(v)
    if isinstance(v, float):
        text = repr(v)
        if "e" in text and "." not in text.split("e")[0]:
            mant, exp = text.split("e")
            text = f"{mant}.0e{exp}"
        return text
    return json.dumps(str(v), ensure_ascii=False)


def _flow(v) -> str:
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_flow(x)}" for k, x in v.items()) + "}"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_flow(x) for x in v) + "]"
    return _scalar(v)
