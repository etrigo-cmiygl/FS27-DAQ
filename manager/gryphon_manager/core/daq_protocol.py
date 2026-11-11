"""DAQ settings protocol (proposal, version 1). The FS27 firmware doesn't implement it yet.

USB serial, one line per message, NMEA-style:   $GM,<COMMAND>[,key=value...]*CS
CS is the XOR of every character between '$' and '*', as two hex digits.

Commands to the DAQ: HELLO, GET, SET (with key=value pairs), SAVE, FACTORY
Replies from the DAQ: $GM,HELLO,fw=<text>,proto=1,settings=<n>   $GM,VAL,key=value,...
                      $GM,OK,settings=<n>                         $GM,ERR,<reason>

The same thing over CAN uses two standard IDs: 0x6F0 to the DAQ and 0x6F1 back.
"""
from __future__ import annotations

from functools import reduce

PROTO_VERSION = 1
CAN_ID_REQUEST = 0x6F0
CAN_ID_REPLY = 0x6F1
CAN_CMD = {"HELLO": 0x7F, "GET": 0x01, "SET": 0x02, "SAVE": 0x03, "FACTORY": 0x04}

# key: (index for CAN, label, kind, allowed, default, help)
SETTINGS = {
    "gps_hz": (1, "GPS update rate", "choice", [1, 5, 10], 5, "How often the GPS reports position (Hz)."),
    "gps_radio": (2, "Send GPS over the radio", "bool", [0, 1], 1, "Include position in the radio packet."),
    "gps_screen": (3, "Send GPS to the screen", "bool", [0, 1], 1, "Send frames 0x602 and 0x603."),
    "radio_hz": (4, "Radio packets a second", "range", (1, 10), 2, "More is smoother but leaves less margin."),
    "radio_power_dbm": (5, "Radio power (dBm)", "range", (0, 13), 13,
                        "13 dBm is what FS26 ran. Check the rules before asking for more."),
    "radio_sf": (6, "Radio spreading factor", "range", (5, 12), 7, "Higher reaches further but is slower."),
    "screen_hz": (7, "Screen frames a second", "range", (1, 50), 20, "How often 0x600-0x603 are sent."),
    "sd_log": (8, "Log to the SD card", "bool", [0, 1], 0, "Needs the FS27 board with an SD slot."),
}


def checksum(body: str) -> str:
    return f"{reduce(lambda a, c: a ^ ord(c), body, 0):02X}"


def build_line(command: str, **values) -> str:
    body = "GM," + command.upper()
    for k, v in values.items():
        body += f",{k}={v}"
    return f"${body}*{checksum(body)}"


def parse_line(line: str) -> tuple[str, dict] | None:
    line = line.strip()
    if not line.startswith("$GM,") or "*" not in line:
        return None
    body, _, cs = line[1:].rpartition("*")
    if checksum(body) != cs.strip().upper():
        return None
    parts = body.split(",")[1:]
    if not parts:
        return None
    values = {}
    extra = []
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            values[k] = v
        else:
            extra.append(p)
    if extra:
        values["_"] = ",".join(extra)
    return parts[0].upper(), values


def validate(values: dict) -> list[str]:
    problems = []
    for key, value in values.items():
        if key.startswith("ch."):
            if value not in ("off", "slow", "fast"):
                problems.append(f"{key}: must be off, slow or fast")
            continue
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
        elif kind in ("choice", "bool") and iv not in allowed:
            problems.append(f"{label}: must be one of {', '.join(str(a) for a in allowed)}")
    return problems


def build_can(command: str, key: str = "", value: int = 0, seq: int = 0) -> bytes:
    idx = SETTINGS[key][0] if key else 0
    body = bytes([CAN_CMD[command.upper()], idx]) + int(value).to_bytes(4, "little", signed=True) + bytes([seq & 0xFF])
    return body + bytes([sum(body) & 0xFF])


def parse_can(data: bytes) -> dict | None:
    if len(data) != 8 or sum(data[:7]) & 0xFF != data[7]:
        return None
    key = next((k for k, s in SETTINGS.items() if s[0] == data[1]), "")
    return {"command": data[0] & 0x7F, "is_reply": bool(data[0] & 0x80), "key": key,
            "value": int.from_bytes(data[2:6], "little", signed=True), "seq": data[6]}
