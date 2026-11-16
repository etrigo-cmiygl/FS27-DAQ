"""DAQ settings protocol, version 2. The firmware side is daq_settings_fs27.c; the write-up is
wiki/DAQ-Settings-Protocol.md.

USB serial, one line per message:   $GM,<COMMAND>[,arguments...]*CS
CS is the XOR of every character between '$' and '*', as two hex digits (the NMEA checksum).
"""
from __future__ import annotations

import struct
from functools import reduce

PROTO_VERSION = 2
MAX_FRAMES = 8
MAX_SIGNALS = 8
MAX_FIELDS = 48
MAX_PACKET = 200

# key: (order, label, kind, allowed, factory value, help)
SETTINGS = {
    "gps_hz": (1, "GPS update rate (Hz)", "choice", [1, 5, 10], 5, "How often the GPS reports position."),
    "radio_hz": (2, "Radio packets a second", "range", (2, 10), 2,
                 "How often the DAQ radios the pits. More is smoother but leaves less margin."),
    "screen_hz": (3, "Screen frames a second", "range", (1, 50), 20,
                  "How often the DAQ sends its frames to the steering wheel screen."),
}
TYPES = ["u8", "i8", "u16", "i16", "u32", "i32", "f32"]
TYPE_SIZE = {"u8": 1, "i8": 1, "u16": 2, "i16": 2, "u32": 4, "i32": 4, "f32": 4}
GPS_SOURCES = {"latitude": 40, "longitude": 41, "speed_kph": 42, "altitude": 43, "satellites": 44, "fix_valid": 45}
DAQ_SOURCES = {"battery_voltage": 37, "tx_count": 50, "can_frame_count": 51}
INPUT_NAMES = ["A0", "A1", "A2", "X0", "X1", "X2", "X3", "X4", "X5", "X6", "X7", "F0", "F1", "F2", "F3"]
INPUT_WHERE = {"A": "Pico pin (0 to 3.3 V)", "X": "ADS1115 board (0 to 5 V)", "F": "pulse input (Hz)"}
INPUT_PINS = {"A0": "GP26", "A1": "GP27", "A2": "GP28", "X0": "ADS1115 0x48 A0", "X1": "ADS1115 0x48 A1",
              "X2": "ADS1115 0x48 A2", "X3": "ADS1115 0x48 A3", "X4": "ADS1115 0x49 A0", "X5": "ADS1115 0x49 A1",
              "X6": "ADS1115 0x49 A2", "X7": "ADS1115 0x49 A3", "F0": "GP16", "F1": "GP17", "F2": "GP18", "F3": "GP20"}
SPARE_FIRST = 60
ANALOG_INPUTS = 11
IN_OFF, IN_LINEAR, IN_THERMISTOR = 0, 1, 2
INPUT_OFF = (IN_OFF, 0.0, 0.0, 0.0, 0.0)
SENSORS = {"linear": "0-5 V sensor (straight line)", "thermistor": "Thermistor (NTC to ground)",
           "wheel_speed": "Wheel speed (pulses)", "frequency": "Pulses, scaled"}
# sensor: [(key in the config, label, usual value)]
SENSOR_PARAMS = {
    "linear": [("v_min", "Sensor volts at the low end", 0.5), ("v_max", "Sensor volts at the high end", 4.5),
               ("value_min", "Value at the low end", 0.0), ("value_max", "Value at the high end", 100.0),
               ("divider", "Divider: sensor volts / pin volts", 1.0)],
    "thermistor": [("pullup", "Pull-up resistor (ohms)", 10000.0), ("r25", "Resistance at 25 C (ohms)", 10000.0),
                   ("beta", "Beta", 3950.0), ("supply", "Pull-up supply (volts)", 3.3)],
    "wheel_speed": [("teeth", "Teeth on the trigger wheel", 20.0), ("circumference_m", "Tyre circumference (m)", 1.6)],
    "frequency": [("per_hz", "Value per Hz", 1.0)],
}
ERRORS = {
    "checksum": "the line got garbled on the way (checksum). Try again.",
    "format": "the DAQ didn't understand the line (format).",
    "range": "a value is outside what the DAQ allows (range).",
    "unknown": "the DAQ doesn't know that setting. Its firmware may be older than this app.",
    "moving": "the car is moving or the engine is running. Settings only change when it's stopped.",
    "flash": "the DAQ couldn't write its flash memory. Try again, then reflash the firmware.",
}


def checksum(body: str) -> str:
    return f"{reduce(lambda a, c: a ^ (ord(c) & 0xFF), body, 0):02X}"


def build_line(command: str, *args, **values) -> str:
    body = "GM," + command.upper()
    for a in args:
        body += f",{a}"
    for k, v in values.items():
        body += f",{k}={v}"
    return f"${body}*{checksum(body)}"


def parse_line(line: str) -> tuple[str, list[str]] | None:
    """Returns (command, arguments) for a good $GM line, or None."""
    line = line.strip()
    if not line.startswith("$GM,") or "*" not in line:
        return None
    body, _, cs = line[1:].rpartition("*")
    if checksum(body) != cs.strip().upper():
        return None
    parts = body.split(",")[1:]
    if not parts or not parts[0]:
        return None
    return parts[0].upper(), parts[1:]


def key_values(args: list[str]) -> dict:
    return dict(a.split("=", 1) for a in args if "=" in a)


def validate(values: dict) -> list[str]:
    problems = []
    for key, value in values.items():
        spec = SETTINGS.get(key)
        if spec is None:
            problems.append(f"{key}: not a setting")
            continue
        _, label, kind, allowed, _, _ = spec
        try:
            iv = int(value)
        except (TypeError, ValueError):
            problems.append(f"{label}: not a whole number")
            continue
        if kind == "range" and not allowed[0] <= iv <= allowed[1]:
            problems.append(f"{label}: must be {allowed[0]} to {allowed[1]}")
        elif kind == "choice" and iv not in allowed:
            problems.append(f"{label}: must be one of {', '.join(str(a) for a in allowed)}")
    return problems


def f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(x)))[0]


def fmt_float(x: float) -> str:
    return "%.9g" % f32(x)


def input_config(src: dict) -> tuple:
    """A channel's spare-input source -> (kind, p0, p1, p2, p3) for the DAQ. Raises ValueError with a plain reason."""
    name = str(src.get("input", ""))
    if name not in INPUT_NAMES:
        raise ValueError(f"'{name}' isn't a DAQ input. They are {', '.join(INPUT_NAMES)}.")
    if not src.get("sensor"):
        return (IN_LINEAR, 1.0, 0.0, 0.0, 0.0)
    sensor = src["sensor"]
    if sensor not in SENSOR_PARAMS:
        raise ValueError(f"'{sensor}' isn't a sensor type.")
    pulses = name[0] == "F"
    if pulses != (sensor in ("wheel_speed", "frequency")):
        raise ValueError(f"{name} is a {INPUT_WHERE[name[0]]}, which can't take '{SENSORS[sensor]}'.")
    try:
        v = {key: float(src.get(key, usual)) for key, _, usual in SENSOR_PARAMS[sensor]}
    except (TypeError, ValueError):
        raise ValueError("the sensor numbers must all be numbers.") from None
    if sensor == "linear":
        if v["v_max"] == v["v_min"] or v["divider"] <= 0:
            raise ValueError("the two voltages must be different and the divider above 0.")
        top = 3.3 if name[0] == "A" else 5.0
        if max(v["v_min"], v["v_max"]) / v["divider"] > top + 0.01:
            raise ValueError(f"{name} only reads up to {top} V at the pin. Use a divider, or an X input for 5 V sensors.")
        slope = (v["value_max"] - v["value_min"]) / (v["v_max"] - v["v_min"])
        return (IN_LINEAR, f32(slope * v["divider"]), f32(v["value_min"] - v["v_min"] * slope), 0.0, 0.0)
    if sensor == "thermistor":
        if min(v.values()) <= 0:
            raise ValueError("the thermistor numbers must all be above 0.")
        return (IN_THERMISTOR, f32(v["pullup"]), f32(v["r25"]), f32(v["beta"]), f32(v["supply"]))
    if sensor == "wheel_speed":
        if v["teeth"] <= 0 or v["circumference_m"] <= 0:
            raise ValueError("teeth and circumference must be above 0.")
        return (IN_LINEAR, f32(v["circumference_m"] * 3.6 / v["teeth"]), 0.0, 0.0, 0.0)
    return (IN_LINEAR, f32(v["per_hz"]), 0.0, 0.0, 0.0)


def input_convert(cfg_in: tuple, x: float) -> float:
    """What the DAQ makes of x volts (or Hz) on an input. Same sums as daq_input_convert in the firmware."""
    kind, p0, p1, p2, p3 = cfg_in
    if kind == IN_LINEAR:
        return f32(f32(f32(p0) * f32(x)) + f32(p1))
    if kind == IN_THERMISTOR:
        import math
        if x >= p3 - 0.01:
            return -50.0
        if x <= 0.01:
            return 250.0
        ohms = p0 * x / (p3 - x)
        return f32(max(-50.0, min(250.0, 1.0 / (1.0 / 298.15 + math.log(ohms / p1) / p2) - 273.15)))
    return 0.0


def source_number(cfg, channel_key: str) -> int | None:
    """Which DAQ source number a channel in the master config is. None if the firmware can't supply it."""
    ch = cfg.channel(channel_key)
    if not ch:
        return None
    src = ch.get("source") or {}
    kind = src.get("type")
    try:
        if kind == "ecu":
            frame = int(str(src.get("id")), 0) - 0x14080600
            slot = int(src.get("slot"))
            return frame * 4 + slot + 1 if 0 <= frame <= 8 and 0 <= slot <= 3 else None
        if kind == "gps":
            return GPS_SOURCES.get(src.get("field"))
        if kind == "daq":
            return DAQ_SOURCES.get(src.get("field"))
        if kind == "daq_input":
            return SPARE_FIRST + INPUT_NAMES.index(src.get("input")) if src.get("input") in INPUT_NAMES else None
    except (TypeError, ValueError):
        return None
    return None


def layout_from_config(cfg) -> tuple[dict, list[str]]:
    """The screen frames and radio packet from the master config, in the DAQ's terms.

    Returns (layout, problems). layout = {"frames": [(id, [(src, byte, bits, signed, m1, m2), ...])],
    "radio": [(src, type_number)], "inputs": [(kind, p0, p1, p2, p3)] x 15, "layout": version}.
    """
    problems: list[str] = []
    inputs = [INPUT_OFF] * len(INPUT_NAMES)
    taken: dict[str, str] = {}
    for ch in cfg.channels:
        src = ch.get("source") or {}
        if src.get("type") != "daq_input":
            continue
        try:
            setup = input_config(src)
        except ValueError as exc:
            problems.append(f"{ch.get('name') or ch.get('key')}: {exc}")
            continue
        name = src["input"]
        if name in taken:
            problems.append(f"Input {name} is used by both '{taken[name]}' and '{ch.get('key')}'.")
            continue
        taken[name] = ch.get("key", "")
        inputs[INPUT_NAMES.index(name)] = setup
    frames = []
    for fr in cfg.data.get("screen_frames", []) or []:
        try:
            fid = int(str(fr.get("id")), 0)
        except (TypeError, ValueError):
            problems.append("A screen frame has no valid ID.")
            continue
        sigs = []
        for sg in fr.get("signals", []) or []:
            src = source_number(cfg, sg.get("channel", ""))
            if src is None:
                problems.append(f"Screen frame 0x{fid:03X}: the DAQ can't supply '{sg.get('channel')}' "
                                "(only ECU, GPS, DAQ and spare-input values).")
                continue
            scale = float(sg.get("scale", 1) or 1)
            sigs.append((src, int(sg.get("byte", 0)), int(sg.get("bits", 16)), 1 if sg.get("signed") else 0,
                         f32(float(sg.get("convert", 1) or 1)), f32(1.0 / scale)))
        if len(sigs) > MAX_SIGNALS:
            problems.append(f"Screen frame 0x{fid:03X} has more than {MAX_SIGNALS} signals.")
        if sigs:
            frames.append((fid, sigs))
    if len(frames) > MAX_FRAMES:
        problems.append(f"The DAQ can send at most {MAX_FRAMES} screen frames.")
    radio = []
    rp = cfg.data.get("radio_packet") or {}
    for f in rp.get("fields", []) or []:
        src = source_number(cfg, f.get("channel", ""))
        if src is None or f.get("type") not in TYPES:
            problems.append(f"Radio packet: the DAQ can't supply '{f.get('channel')}'.")
            continue
        radio.append((src, TYPES.index(f["type"])))
    if not 1 <= len(radio) <= MAX_FIELDS:
        problems.append(f"The radio packet needs 1 to {MAX_FIELDS} fields.")
    return {"frames": frames, "radio": radio, "inputs": inputs,
            "layout": int(rp.get("layout_version", 1)) & 0xFF}, problems


def signal_text(sig) -> str:
    src, byte, bits, signed, m1, m2 = sig
    return f"{src}/{byte}/{bits}/{signed}/{fmt_float(m1)}/{fmt_float(m2)}"


def layout_commands(layout: dict) -> list[str]:
    """The lines that load a layout into the DAQ's pending copy (not saved yet)."""
    lines = [build_line("SF", slot, 0) for slot in range(MAX_FRAMES)]
    for i, (kind, *p) in enumerate(layout.get("inputs") or [INPUT_OFF] * len(INPUT_NAMES)):
        lines.append(build_line("IN", i, kind, *[fmt_float(x) for x in p]))
    for slot, (fid, sigs) in enumerate(layout["frames"][:MAX_FRAMES]):
        lines.append(build_line("SF", slot, f"{fid:X}", *[signal_text(s) for s in sigs]))
    radio = layout["radio"]
    for start in range(0, len(radio), 12):
        lines.append(build_line("RP", start, *[f"{s}/{t}" for s, t in radio[start:start + 12]]))
    lines.append(build_line("RPN", len(radio)))
    lines.append(build_line("SET", layout=layout["layout"]))
    return lines


def parse_layout(replies: list[tuple[str, list[str]]]) -> dict:
    """Turns the DAQ's answer to GETL back into a layout."""
    frames: dict[int, tuple] = {}
    radio: dict[int, tuple] = {}
    count = None
    inputs = [INPUT_OFF] * len(INPUT_NAMES)
    for cmd, args in replies:
        try:
            if cmd == "SF":
                sigs = []
                for text in args[2:]:
                    p = text.split("/")
                    sigs.append((int(p[0]), int(p[1]), int(p[2]), int(p[3]), f32(float(p[4])), f32(float(p[5]))))
                frames[int(args[0])] = (int(args[1], 16), sigs)
            elif cmd == "RP":
                for i, text in enumerate(args[1:]):
                    s, t = text.split("/")
                    radio[int(args[0]) + i] = (int(s), int(t))
            elif cmd == "RPN":
                count = int(args[0])
            elif cmd == "IN":
                inputs[int(args[0])] = (int(args[1]), *[f32(float(a)) for a in args[2:6]])
        except (ValueError, IndexError):
            continue
    n = count if count is not None else len(radio)
    return {"frames": [frames[k] for k in sorted(frames)], "radio": [radio[i] for i in range(n) if i in radio],
            "inputs": inputs}


def same_layout(a: dict, b: dict) -> bool:
    def norm(layout):
        return ([(fid, [(s, by, bi, sg, fmt_float(m1), fmt_float(m2)) for s, by, bi, sg, m1, m2 in sigs])
                 for fid, sigs in layout["frames"]], list(layout["radio"]),
                [(k, *[fmt_float(x) for x in p]) if k else INPUT_OFF
                 for k, *p in (layout.get("inputs") or [INPUT_OFF] * len(INPUT_NAMES))])
    return norm(a) == norm(b)


def packet_size(radio: list, factory: bool) -> int:
    return (4 if factory else 5) + sum(TYPE_SIZE[TYPES[t]] for _, t in radio)
