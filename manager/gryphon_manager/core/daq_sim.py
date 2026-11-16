"""A pretend v2 DAQ for the simulator: answers the settings protocol the way daq_settings_fs27.c does.

tests/test_daq_settings.py runs the same conversation against this and against the real C code.
"""
from __future__ import annotations

import copy

from . import daq_protocol as proto

FW_NAME = "FS27-DAQ-2.0"
FACTORY_FRAMES = [
    (0x600, [(10, 0, 16, 0, 1.0, 1.0), (2, 2, 16, 0, 100.0, 10.0), (4, 4, 16, 1, 1.0, 10.0), (1, 6, 16, 0, 1.0, 10.0)]),
    (0x601, [(37, 0, 16, 0, 1.0, 100.0), (3, 2, 16, 1, 1.0, 10.0)]),
    (0x602, [(40, 0, 32, 1, 1.0, 10000000.0), (41, 4, 32, 1, 1.0, 10000000.0)]),
    (0x603, [(42, 0, 16, 0, 1.0, 10.0), (44, 2, 8, 0, 1.0, 1.0), (45, 3, 8, 0, 1.0, 1.0), (50, 4, 16, 0, 1.0, 1.0),
             (51, 6, 16, 0, 1.0, 1.0)]),
]
FACTORY_RADIO = [(40, 6), (41, 6), (42, 6), (43, 6), (44, 0), (45, 0), (10, 2), (4, 6), (1, 6), (5, 6), (6, 6),
                 (36, 6), (37, 6), (13, 2), (14, 2), (15, 2), (16, 2), (26, 6), (20, 6), (50, 2), (51, 2)]


def factory() -> dict:
    frames = [None] * proto.MAX_FRAMES
    for i, fr in enumerate(FACTORY_FRAMES):
        frames[i] = (fr[0], list(fr[1]))
    radio = list(FACTORY_RADIO) + [(0, 0)] * (proto.MAX_FIELDS - len(FACTORY_RADIO))
    return {"gps_hz": 5, "radio_hz": 2, "screen_hz": 20, "layout": 1, "frames": frames, "radio": radio,
            "n_radio": len(FACTORY_RADIO), "inputs": [proto.INPUT_OFF] * len(proto.INPUT_NAMES), "counter": 0}


def source_ok(src: int) -> bool:
    return 1 <= src <= 37 or 40 <= src <= 45 or src in (50, 51) or 60 <= src <= 74


def is_factory_radio(s: dict) -> bool:
    return s["radio"][:s["n_radio"]] == FACTORY_RADIO and s["n_radio"] == len(FACTORY_RADIO)


def packet_size(s: dict) -> int:
    return proto.packet_size(s["radio"][:s["n_radio"]], is_factory_radio(s))


def in_range(s: dict) -> bool:
    if s["gps_hz"] not in (1, 5, 10) or not 2 <= s["radio_hz"] <= 10 or not 1 <= s["screen_hz"] <= 50:
        return False
    if not 1 <= s["n_radio"] <= proto.MAX_FIELDS:
        return False
    for src, t in s["radio"][:s["n_radio"]]:
        if not source_ok(src) or not 0 <= t < len(proto.TYPES):
            return False
    if packet_size(s) > proto.MAX_PACKET:
        return False
    for i, (kind, *p) in enumerate(s["inputs"]):
        if kind not in (0, 1, 2) or any(x != x or not -1e30 < x < 1e30 for x in p):
            return False
        if kind == proto.IN_THERMISTOR and (i >= proto.ANALOG_INPUTS or min(p) <= 0):
            return False
    ids = set()
    for fr in s["frames"]:
        if not fr or not fr[1]:
            continue
        fid, sigs = fr
        if len(sigs) > proto.MAX_SIGNALS or fid > 0x7FF or fid in ids:
            return False
        ids.add(fid)
        used = 0
        for src, byte, bits, signed, m1, m2 in sigs:
            if not source_ok(src) or bits not in (8, 16, 32) or byte + bits // 8 > 8 or m1 != m1 or m2 != m2:
                return False
            mask = ((1 << (bits // 8)) - 1) << byte
            if used & mask:
                return False
            used |= mask
    return True


def _uint(text: str, base: int, top: int):
    text = text.strip() if text == text.strip() else "x"
    if not text or text[0] in "+-" or "_" in text:
        return None
    if base == 16 and text.lower().startswith("0x"):
        text = text[2:]
    try:
        v = int(text, base)
    except ValueError:
        return None
    return v if 0 <= v <= top else None


def _float(text: str):
    """Like the firmware's strtof: takes nan and inf too, and turns too-big numbers into inf."""
    if not text or text != text.strip() or "_" in text:
        return None
    try:
        v = float(text)
    except ValueError:
        return None
    try:
        return proto.f32(v)
    except OverflowError:
        return float("inf") if v > 0 else float("-inf")


class DaqSim:
    def __init__(self):
        self.live = factory()
        self.pending = copy.deepcopy(self.live)
        self.saved = False
        self.flash_fail = False
        self.spare_raw = [0.0] * len(proto.INPUT_NAMES)
        self.spare_fitted = 0

    def _ok(self) -> str:
        return proto.build_line("OK", settings=self.live["counter"])

    @staticmethod
    def _err(reason: str) -> str:
        return proto.build_line("ERR", reason)

    def handle(self, line: str, rpm: float = 0, speed: float = 0) -> list[str]:
        """Returns the reply lines, or [] if the line isn't a settings line."""
        line = line.rstrip("\r\n ")
        if len(line) < 4 or not line.startswith("$GM,"):
            return []
        if len(line) >= 300:
            return [self._err("format")]
        body, star, cs = line[1:].rpartition("*")
        if not star or len(cs) != 2 or _uint(cs, 16, 255) is None or proto.checksum(body) != f"{_uint(cs, 16, 255):02X}":
            return [self._err("checksum")]
        tok = body.split(",")
        if len(tok) < 2 or len(tok) > 24:
            return [self._err("format")]
        cmd, args = tok[1], tok[2:]
        s = self.pending
        if cmd == "HELLO":
            return [proto.build_line("HELLO", fw=FW_NAME, proto=proto.PROTO_VERSION, settings=self.live["counter"],
                                     saved=1 if self.saved else 0)]
        if cmd == "GET":
            return [proto.build_line("VAL", gps_hz=s["gps_hz"], radio_hz=s["radio_hz"], screen_hz=s["screen_hz"],
                                     layout=s["layout"], frames=sum(1 for f in s["frames"] if f and f[1]),
                                     fields=s["n_radio"], packet=packet_size(s),
                                     unsaved=0 if self.pending == self.live else 1,
                                     inputs=sum(1 for i in s["inputs"] if i[0]))]
        if cmd == "GETL":
            out = []
            for i, fr in enumerate(s["frames"]):
                if fr and fr[1]:
                    out.append(proto.build_line("SF", i, f"{fr[0]:X}", *[proto.signal_text(g) for g in fr[1]]))
            for start in range(0, s["n_radio"], 12):
                out.append(proto.build_line("RP", start, *[f"{a}/{b}" for a, b in
                                                           s["radio"][start:min(start + 12, s["n_radio"])]]))
            out.append(proto.build_line("RPN", s["n_radio"]))
            for i, (kind, *p) in enumerate(s["inputs"]):
                if kind:
                    out.append(proto.build_line("IN", i, kind, *[proto.fmt_float(x) for x in p]))
            return out + [self._ok()]
        if cmd == "GETI":
            return [proto.build_line("INV", self.spare_fitted & 3, *["%.6g" % proto.input_convert(c, x)
                                                                    for c, x in zip(s["inputs"], self.spare_raw)])]
        if cmd == "CANCEL":
            self.pending = copy.deepcopy(self.live)
            return [self._ok()]
        if cmd not in ("SET", "SF", "RP", "RPN", "IN", "SAVE", "FACTORY"):
            return [self._err("unknown")]
        if rpm > 0 or speed > 2.0:
            return [self._err("moving")]
        err = None
        if cmd == "SET":
            trial = copy.deepcopy(s)
            if not args:
                err = "format"
            for a in args:
                if err:
                    break
                kv = a.split("=")
                if len(kv) != 2:
                    err = "format"
                    break
                v = _uint(kv[1], 10, 255)
                if v is None or kv[0] not in ("gps_hz", "radio_hz", "screen_hz", "layout"):
                    err = "unknown"
                else:
                    trial[kv[0]] = v
            if not err and not in_range(trial):
                err = "range"
            if not err:
                self.pending = trial
        elif cmd == "SF":
            err = self._screen_frame(args)
        elif cmd == "RP":
            err = self._radio_fields(args)
        elif cmd == "IN":
            err = self._input(args)
        elif cmd == "RPN":
            n = _uint(args[0], 10, proto.MAX_FIELDS) if len(args) == 1 else None
            if n is None or n < 1:
                err = "range"
            else:
                s["n_radio"] = n
        else:
            nxt = factory() if cmd == "FACTORY" else copy.deepcopy(s)
            if not in_range(nxt):
                err = "range"
            elif self.flash_fail:
                err = "flash"
            else:
                nxt["counter"] = self.live["counter"] + 1
                self.live = nxt
                self.pending = copy.deepcopy(nxt)
                self.saved = True
        return [self._err(err)] if err else [self._ok()]

    def _screen_frame(self, args) -> str | None:
        if len(args) < 2:
            return "range"
        idx, fid = _uint(args[0], 10, proto.MAX_FRAMES - 1), _uint(args[1], 16, 0x7FF)
        if idx is None or fid is None or len(args) - 2 > proto.MAX_SIGNALS:
            return "range"
        sigs = []
        for text in args[2:]:
            p = text.split("/")
            if len(p) != 6:
                return "format"
            ints = [_uint(p[0], 10, 255), _uint(p[1], 10, 7), _uint(p[2], 10, 32), _uint(p[3], 10, 1)]
            if None in ints:
                return "range"
            m1, m2 = _float(p[4]), _float(p[5])
            if m1 is None or m2 is None:
                return "format"
            sigs.append((*ints, m1, m2))
        trial = copy.deepcopy(self.pending)
        trial["frames"][idx] = (fid, sigs)
        if not in_range(trial):
            return "range"
        self.pending = trial
        return None

    def _input(self, args) -> str | None:
        if len(args) != 6:
            return "format"
        idx, kind = _uint(args[0], 10, len(proto.INPUT_NAMES) - 1), _uint(args[1], 10, 2)
        if idx is None or kind is None:
            return "range"
        p = [_float(a) for a in args[2:]]
        if None in p:
            return "format"
        trial = copy.deepcopy(self.pending)
        trial["inputs"][idx] = (kind, *p)
        if not in_range(trial):
            return "range"
        self.pending = trial
        return None

    def _radio_fields(self, args) -> str | None:
        if len(args) < 2:
            return "range"
        start = _uint(args[0], 10, proto.MAX_FIELDS - 1)
        if start is None or start + len(args) - 1 > proto.MAX_FIELDS:
            return "range"
        trial = copy.deepcopy(self.pending)
        for i, text in enumerate(args[1:]):
            p = text.split("/")
            if len(p) != 2:
                return "format"
            src, t = _uint(p[0], 10, 255), _uint(p[1], 10, len(proto.TYPES) - 1)
            if src is None or t is None or not source_ok(src):
                return "range"
            trial["radio"][start + i] = (src, t)
        self.pending = trial
        return None
