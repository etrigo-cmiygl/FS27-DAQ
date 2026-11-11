from __future__ import annotations

import re

from .config import MasterConfig
from .model import DaqLine, RadioPacket

NUM = r"([+-]?[0-9]*\.?[0-9]+)"

MAX_RPM = 15000
MAX_THROTTLE = 100.0


def pack_packet(cfg: MasterConfig, values: dict) -> bytes:
    args = [cfg.radio_magic]
    for name, channel, ftype in cfg.radio_fields:
        v = values.get(channel, 0) or 0
        if ftype == "f32":
            args.append(float(v))
        else:
            bits = {"u8": 8, "i8": 8, "u16": 16, "i16": 16, "u32": 32, "i32": 32}[ftype]
            iv = int(v)
            if ftype.startswith("u"):
                iv &= (1 << bits) - 1
            args.append(iv)
    return cfg.radio_struct.pack(*args)


def unpack_packet(cfg: MasterConfig, raw: bytes) -> dict | None:
    if len(raw) != cfg.radio_size:
        return None
    fields = cfg.radio_struct.unpack(raw)
    if fields[0] != cfg.radio_magic:
        return None
    return {channel: fields[i + 1] for i, (name, channel, ftype) in enumerate(cfg.radio_fields)}


def format_pkt_line(raw: bytes, rssi: int, snr: int) -> str:
    return f"PKT,{rssi},{snr},{raw.hex().upper()}"


def format_text_box(v: dict, rssi: int, snr: int, rx_count: int) -> list[str]:
    return [
        "",
        "╔══════════════════════════════════════════════════════════════╗",
        "║            FS26 COMBINED TELEMETRY RECEIVED                 ║",
        "╠══════════════════════════════════════════════════════════════╣",
        f"║  GPS:  {v['gps_lat']:.6f}, {v['gps_lon']:.6f}                                  ║",
        f"║  GPS Spd: {v['gps_speed']:.1f} kph | Alt: {v['gps_alt']:.1f} m | Sat: {int(v['gps_sats'])} | "
        f"Fix: {'Valid' if v['gps_fix'] else 'No Fix'}   ║",
        f"║  RPM: {int(v['rpm'])} | TPS: {v['tps']:.1f}% | Eng: {v['engine_temp']:.1f} C | "
        f"Oil: {v['oil_pressure']:.2f} Bar ║",
        f"║  Fuel: {v['fuel_pressure']:.2f} Bar | Brake: {v['brake_pressure']:.2f} Bar | "
        f"Volt: {v['battery']:.2f} V ║",
        f"║  Wheels FR/FL/RR/RL: {int(v['wheel_speed_fr'])}/{int(v['wheel_speed_fl'])}/"
        f"{int(v['wheel_speed_rr'])}/{int(v['wheel_speed_rl'])}                 ║",
        f"║  Lateral G: {v['g_lateral']:.2f} | Heading: {v['heading']:.1f} deg              ║",
        f"║  TX Count: {int(v['tx_count'])} | CAN Frames: {int(v['can_count'])}                     ║",
        "╠══════════════════════════════════════════════════════════════╣",
        f"║  RSSI: {rssi} dBm  |  SNR: {snr} dB  |  RX Count: {rx_count}              ║",
        "╚══════════════════════════════════════════════════════════════╝",
    ]


class ReceiverParser:
    """Turns the receiver's USB serial lines into RadioPacket objects.

    Understands both the FS26 text box (as parsed by fs26_interface.py) and the
    new one-line format: PKT,<rssi>,<snr>,<hex of the raw packet>.
    """

    def __init__(self, cfg: MasterConfig):
        self.cfg = cfg
        self.cur: dict = {}
        self.format: str | None = None
        self.bad_lines = 0
        self.stats: dict = {}

    def feed(self, line: str, ts: float) -> RadioPacket | None:
        line = line.strip()
        if not line:
            return None
        if line.startswith("PKT,"):
            return self._pkt(line, ts)
        try:
            return self._box(line, ts)
        except (ValueError, IndexError):
            self.bad_lines += 1
            return None

    def _pkt(self, line: str, ts: float) -> RadioPacket | None:
        parts = line.split(",")
        if len(parts) != 4:
            self.bad_lines += 1
            return None
        try:
            rssi, snr = float(parts[1]), float(parts[2])
            raw = bytes.fromhex(parts[3])
        except ValueError:
            self.bad_lines += 1
            return None
        values = unpack_packet(self.cfg, raw)
        if values is None:
            self.bad_lines += 1
            return None
        self.format = "PKT lines"
        return RadioPacket(ts, values, rssi, snr, raw)

    def _box(self, line: str, ts: float) -> RadioPacket | None:
        c = self.cur
        if "GPS:" in line and "GPS Spd:" not in line:
            m = re.search(rf"GPS:\s*{NUM},\s*{NUM}", line)
            if m:
                c["gps_lat"], c["gps_lon"] = float(m.group(1)), float(m.group(2))
        elif "GPS Spd:" in line:
            m = re.search(rf"GPS Spd:\s*{NUM}\s*kph\s*\|\s*Alt:\s*{NUM}\s*m\s*\|\s*Sat:\s*(\d+)\s*\|\s*"
                          r"Fix:\s*(Valid|No Fix)", line)
            if m:
                c["gps_speed"], c["gps_alt"] = float(m.group(1)), float(m.group(2))
                c["gps_sats"], c["gps_fix"] = int(m.group(3)), 1 if m.group(4) == "Valid" else 0
        elif "RPM:" in line and "TPS:" in line:
            m = re.search(rf"RPM:\s*(\d+)\s*\|\s*TPS:\s*{NUM}%\s*\|\s*Eng:\s*{NUM}\s*C\s*\|\s*Oil:\s*{NUM}\s*Bar",
                          line)
            if m:
                c["rpm"], c["tps"] = int(m.group(1)), float(m.group(2))
                c["engine_temp"], c["oil_pressure"] = float(m.group(3)), float(m.group(4))
        elif "Fuel:" in line and "Brake:" in line:
            m = re.search(rf"Fuel:\s*{NUM}\s*Bar\s*\|\s*Brake:\s*{NUM}\s*Bar\s*\|\s*(?:Volt|Voltage):\s*{NUM}\s*V",
                          line)
            if m:
                c["fuel_pressure"], c["brake_pressure"] = float(m.group(1)), float(m.group(2))
                c["battery"] = float(m.group(3))
        elif "Wheels FR/FL/RR/RL:" in line:
            m = re.search(r"Wheels FR/FL/RR/RL:\s*(\d+)/(\d+)/(\d+)/(\d+)", line)
            if m:
                for k, g in zip(("wheel_speed_fr", "wheel_speed_fl", "wheel_speed_rr", "wheel_speed_rl"),
                                m.groups()):
                    c[k] = int(g)
        elif "Lateral G:" in line and "Heading:" in line:
            m = re.search(rf"Lateral G:\s*{NUM}\s*\|\s*Heading:\s*{NUM}\s*deg", line)
            if m:
                c["g_lateral"], c["heading"] = float(m.group(1)), float(m.group(2))
        elif "TX Count:" in line and "CAN Frames:" in line:
            m = re.search(r"TX Count:\s*(\d+)\s*\|\s*CAN Frames:\s*(\d+)", line)
            if m:
                c["tx_count"], c["can_count"] = int(m.group(1)), int(m.group(2))
        elif "RSSI:" in line and "SNR:" in line and "RX Count" in line:
            m = re.search(r"RSSI:\s*(-?\d+)\s*dBm\s*\|\s*SNR:\s*(-?\d+)", line)
            if m and c:
                pkt = RadioPacket(ts, dict(c), float(m.group(1)), float(m.group(2)))
                self.cur = {}
                self.format = "FS26 text box"
                return pkt
        elif line.startswith("[STATS]"):
            for k, v in re.findall(r"([A-Za-z ]+):\s*(\d+)", line[7:]):
                self.stats[k.strip()] = int(v)
        return None


_DAQ_PATTERNS = {
    "TX": re.compile(rf"\[TX\]\s*RPM:(\d+)\s*\|\s*Batt:{NUM}\s*\|\s*TPS:{NUM}\s*\|\s*EngineTemp:{NUM}\s*\|\s*"
                     r"TX#(\d+)\s*CAN#(\d+)"),
    "ECU": re.compile(rf"\[ECU\]\s*MAP:{NUM}\s*bar\s*\|\s*AirTemp:{NUM}\s*\|\s*Oil:{NUM}\s*bar\s*\|\s*"
                      rf"Fuel:{NUM}\s*bar\s*\|\s*Water:{NUM}\s*bar\s*\|\s*Lambda:{NUM}"),
    "GPS": re.compile(rf"\[GPS\]\s*Sats:(-?\d+)\s*\|\s*Fix:(\d)\s*\|\s*Speed:{NUM}\s*kph"),
    "CAN": re.compile(r"\[CAN\]\s*TEC:(\d+)\s*\|\s*REC:(\d+)\s*\|\s*EFLG:0x([0-9A-Fa-f]+)\s*\|\s*"
                      r"TXB0CTRL:0x([0-9A-Fa-f]+)\s*\|\s*RX:(\d+)"),
}
_DAQ_KEYS = {
    "TX": (("rpm", int), ("battery", float), ("tps", float), ("engine_temp", float),
           ("tx_count", int), ("can_count", int)),
    "ECU": (("map", float), ("air_temp", float), ("oil_pressure", float), ("fuel_pressure", float),
            ("water_pressure", float), ("lambda", float)),
    "GPS": (("gps_sats", int), ("gps_fix", int), ("gps_speed", float)),
}


def parse_daq_line(line: str, ts: float) -> DaqLine | None:
    """Parses the DAQ's own USB debug lines ([TX], [ECU], [GPS], [CAN])."""
    line = line.strip()
    if not line.startswith("["):
        if "GPS Configured" in line:
            return DaqLine(ts, "BOOT", {"gps_configured": line}, line)
        if line.startswith("Core 0:") or line.startswith("Core 1:") or line.startswith("CAN:"):
            return DaqLine(ts, "BOOT", {}, line)
        return None
    if line.startswith("[TX] FAILED"):
        return DaqLine(ts, "TXFAIL", {}, line)
    tag = line[1:line.find("]")]
    pat = _DAQ_PATTERNS.get(tag)
    if not pat:
        return None
    m = pat.search(line)
    if not m:
        return None
    if tag == "CAN":
        return DaqLine(ts, "CAN", {
            "tec": int(m.group(1)), "rec": int(m.group(2)), "eflg": int(m.group(3), 16),
            "txb0ctrl": int(m.group(4), 16), "rx": int(m.group(5))}, line)
    values = {k: cast(g) for (k, cast), g in zip(_DAQ_KEYS[tag], m.groups())}
    return DaqLine(ts, tag, values, line)


def explain_daq_can(v: dict) -> tuple[str, str]:
    """Plain-English reading of the [CAN] line. Returns (status, text)."""
    tec, eflg, txb = v.get("tec", 0), v.get("eflg", 0), v.get("txb0ctrl", 0)
    if eflg & 0x20:
        return "red", "DAQ is bus-off: it has stopped sending. Check wiring and termination."
    if txb & 0x08 and tec > 0:
        return "red", ("DAQ's sends are failing (TXB0CTRL stuck, TEC climbing). "
                       "Nothing is acknowledging its frames: check CAN H/L and termination.")
    if eflg & 0xC0:
        return "amber", "DAQ dropped incoming frames (receive overflow)."
    if tec >= 96 or v.get("rec", 0) >= 96 or eflg & 0x07:
        return "amber", "DAQ is seeing bus errors (error counters are high)."
    if tec == 0 and txb == 0:
        return "green", "DAQ is sending fine. If the screen shows zeros, look at the screen wiring or project."
    return "green", "DAQ CAN looks OK."
