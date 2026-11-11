from __future__ import annotations

import math
import random
import struct

from .config import MasterConfig
from .laps import EARTH_R
from .model import Frame
from .radio import format_pkt_line, format_text_box, pack_packet

SIM_PDM_IDS = [0x500, 0x501]
SIM_LAMBDA_IDS = [0x460]
SIM_DEVICES = {"pdm": SIM_PDM_IDS, "lambda": SIM_LAMBDA_IDS}

MODES = {"drive": "Driving laps", "idle": "Engine idling", "off": "Ignition on, engine off"}
FAULTS = {
    "none": "Healthy car",
    "ecu_1hz": "ECU broadcasting at 1 Hz",
    "daq_wrong": "DAQ sending wrong values",
    "daq_missing": "DAQ unplugged",
    "battery_zero": "Battery reads 0 (today's car)",
    "low_oil": "Low oil pressure",
    "bus_errors": "Bus errors",
    "radio_bad": "Weak radio link",
}

LAT0, LON0 = 52.07861, -1.01694


class SimCar:
    """A made-up car. Deterministic for a given seed, so tests can rely on it.

    step(t0, t1) returns everything the car would have put out between two times:
    CAN frames (ECU, DAQ, made-up PDM and lambda), receiver serial lines and DAQ debug lines.
    """

    def __init__(self, cfg: MasterConfig, seed: int = 27, ecu_hz: float = 10.0, mode: str = "drive",
                 fault: str = "none", receiver_format: str = "box", stress_fps: int = 0):
        self.cfg = cfg
        self.rng = random.Random(seed)
        self.ecu_hz = ecu_hz
        self.mode = mode
        self.fault = fault
        self.receiver_format = receiver_format
        self.stress_fps = stress_fps
        self.t = 0.0
        self.theta = 0.0
        self.engine_temp = 20.0
        self.rpm = 0.0
        self.tps = 0.0
        self.speed = 0.0
        self.heading = 0.0
        self.g_lat = 0.0
        self.tx_count = 0
        self.can_count = 0
        self.rx_count = 0
        self.fuel_used = 0.0
        self._next = {"ecu": 0.0, "daq": 0.0, "pdm": 0.0, "lambda": 0.0, "radio": 0.0, "daqcan": 0.0,
                      "err": 0.0, "stress": 0.0}
        self.values: dict = {}
        self.lat, self.lon = self._pos(0.0)
        self._update(0.0)

    # ---- the pretend physics ---------------------------------------------

    def _radius(self, th: float) -> float:
        return 95.0 * (1.0 + 0.32 * math.cos(2 * th) + 0.16 * math.sin(3 * th))

    def _xy(self, th: float) -> tuple[float, float]:
        r = self._radius(th)
        return r * math.cos(th), r * math.sin(th)

    def _pos(self, th: float) -> tuple[float, float]:
        x, y = self._xy(th)
        return (LAT0 + math.degrees(y / EARTH_R),
                LON0 + math.degrees(x / (EARTH_R * math.cos(math.radians(LAT0)))))

    def _update(self, dt: float) -> None:
        n = self.rng.gauss
        running = self.mode in ("idle", "drive")
        target_temp = 88.0 if running else 20.0
        tau = 45.0 if running else 240.0
        self.engine_temp += (target_temp - self.engine_temp) * min(1.0, dt / tau)
        if self.mode == "drive":
            x0, y0 = self._xy(self.theta)
            x1, y1 = self._xy(self.theta + 0.01)
            x2, y2 = self._xy(self.theta + 0.02)
            ds = math.hypot(x1 - x0, y1 - y0) / 0.01
            h1, h2 = math.atan2(y1 - y0, x1 - x0), math.atan2(y2 - y1, x2 - x1)
            dh = (h2 - h1 + math.pi) % (2 * math.pi) - math.pi
            curv = abs(dh) / max(math.hypot(x1 - x0, y1 - y0), 1e-6)
            target = max(28.0, min(92.0, math.sqrt(1.3 * 9.81 / max(curv, 1e-4)) * 3.6))
            accel = 22.0 if target > self.speed else -45.0
            new_speed = self.speed + accel * dt
            if (accel > 0 and new_speed > target) or (accel < 0 and new_speed < target):
                new_speed = target
            self.tps = max(0.0, min(100.0, (60.0 + 40.0 * (target - self.speed) / 10.0) if accel > 0 else 0.0))
            self.speed = new_speed
            self.theta = (self.theta + (self.speed / 3.6) * dt / ds) % (2 * math.pi)
            self.heading = (90.0 - math.degrees(h1)) % 360.0
            self.g_lat = (self.speed / 3.6) ** 2 * curv / 9.81 * (1 if dh > 0 else -1)
            gear = min(5, 1 + int(self.speed // 22))
            self.rpm = max(3500.0, min(12500.0, 3500.0 + (self.speed - (gear - 1) * 18) * 185.0 + n(0, 40)))
        elif self.mode == "idle":
            self.speed, self.g_lat = 0.0, 0.0
            self.tps = max(0.0, 1.5 + n(0, 0.2))
            self.rpm = 1650.0 + 400.0 * max(0.0, (60.0 - self.engine_temp) / 40.0) + n(0, 25)
        else:
            self.speed = self.rpm = self.tps = self.g_lat = 0.0
        self.lat, self.lon = self._pos(self.theta)
        rpm, tps = self.rpm, self.tps
        oil = 0.0 if not running else 1.6 + 2.9 * min(1.0, rpm / 9000.0) + n(0, 0.03)
        if self.fault == "low_oil" and running:
            oil = 0.45 + n(0, 0.02)
        batt = (13.9 if running else 12.4) + n(0, 0.02)
        if self.fault == "battery_zero":
            batt = 0.0
        gear = 0 if self.mode != "drive" else min(5, 1 + int(self.speed // 22))
        ws = self.speed
        self.fuel_used += (rpm / 12000.0) * 0.0006 * dt
        self.values = {
            "tps": tps, "map": 1.013 if not running else 0.32 + 0.68 * tps / 100.0 + n(0, 0.004),
            "air_temp": 22.0 + 6.0 * min(1.0, (self.engine_temp - 20.0) / 70.0),
            "engine_temp": self.engine_temp,
            "oil_pressure": max(0.0, oil), "fuel_pressure": 3.0 + n(0, 0.02) if running else 0.0,
            "water_pressure": (0.2 + 0.9 * min(1.0, rpm / 11000.0)) if running else 0.0, "gear": gear,
            "lambda": (1.0 - 0.13 * tps / 100.0 + n(0, 0.008)) if running else 0.0, "rpm": rpm,
            "oil_temp": 20.0 + (self.engine_temp - 20.0) * 1.08, "pit_limit": 0,
            "wheel_speed_fr": ws, "wheel_speed_fl": ws, "wheel_speed_rr": ws * 1.02, "wheel_speed_rl": ws * 1.02,
            "tc_slip": 0, "tc_retard": 0, "tc_cut": 0, "heading": self.heading,
            "shock_fr": 2.5 + 0.4 * self.g_lat, "shock_fl": 2.5 - 0.4 * self.g_lat,
            "shock_rr": 2.5 + 0.3 * self.g_lat, "shock_rl": 2.5 - 0.3 * self.g_lat,
            "g_accel": 0, "g_lateral": round(self.g_lat), "yaw_frontal": 0, "yaw_lateral": 0,
            "lambda_correction": 0, "fuel_flow": rpm / 12000.0 * 0.9 * (0.2 + 0.8 * tps / 100.0),
            "inj_time_a": (1.8 + 6.5 * tps / 100.0) if running else 0.0,
            "inj_time_b": (1.8 + 6.5 * tps / 100.0) if running else 0.0,
            "trans_oil_temp": 20.0 + (self.engine_temp - 20.0) * 0.7,
            "trans_temp": 20.0 + (self.engine_temp - 20.0) * 0.6, "fuel_consumption": self.fuel_used,
            "brake_pressure": 28.0 if (self.mode == "drive" and tps == 0.0) else 0.0,
            "gps_lat": self.lat, "gps_lon": self.lon, "gps_speed": self.speed, "gps_alt": 153.0,
            "gps_sats": 11, "gps_fix": 1, "battery": batt,
        }

    # ---- frames -------------------------------------------------------------

    def ecu_frames(self, ts: float) -> list[Frame]:
        out = []
        for (cid, ext), defs in self.cfg.by_id.items():
            if not ext or not 0x14080600 <= cid <= 0x14080608:
                continue
            buf = bytearray(8)
            for sd in defs:
                sd.encode_into(buf, self.values.get(sd.key, 0) or 0)
            out.append(Frame(ts + (cid & 0xF) * 0.0003, cid, True, bytes(buf)))
        out.sort(key=lambda f: f.id)
        return out

    def daq_values(self) -> dict:
        v = dict(self.values)
        v["tx_count"] = self.tx_count & 0xFFFF
        v["can_count"] = self.can_count & 0xFFFF
        if self.fault == "daq_wrong":
            v["rpm"] = 0
            v["engine_temp"] = v["engine_temp"] + 14.0
        return v

    def daq_frames(self, ts: float) -> list[Frame]:
        v = self.daq_values()
        out = []
        for i, fid in enumerate(self.cfg.screen_ids):
            buf = bytearray(8)
            for sd in self.cfg.by_id[(fid, False)]:
                base = sd.key[4:]
                val = v.get(base, 0) or 0
                if base == "map":
                    val *= 100.0
                raw = int(val / sd.scale)
                lo = -(1 << (sd.bits - 1)) if sd.signed else 0
                hi = (1 << (sd.bits - 1)) - 1 if sd.signed else (1 << sd.bits) - 1
                raw = max(lo, min(hi, raw))
                buf[sd.byte:sd.byte + sd.bits // 8] = raw.to_bytes(sd.bits // 8, "little", signed=sd.signed)
            out.append(Frame(ts + i * 0.0003, fid, False, bytes(buf)))
        return out

    def other_frames(self, ts: float, which: str) -> list[Frame]:
        v = self.values
        if which == "pdm":
            batt = int(v["battery"] * 100) if self.fault != "battery_zero" else 1385
            cur = int((6.0 + 9.0 * (self.rpm > 0)) * 10)
            return [Frame(ts, SIM_PDM_IDS[0], False, struct.pack("<HHHBB", batt, cur, 0x003F, 31, 0)),
                    Frame(ts + 0.0003, SIM_PDM_IDS[1], False,
                          struct.pack("<HHHH", cur // 3, cur // 4, cur // 6, 12))]
        lam = int((v["lambda"] or 0) * 1000)
        return [Frame(ts, SIM_LAMBDA_IDS[0], False, struct.pack("<HHBBH", lam, 780, 1, 0, 0))]

    # ---- serial text ------------------------------------------------------

    def radio_lines(self) -> list[str]:
        v = self.daq_values()
        self.tx_count += 1
        v["tx_count"] = self.tx_count & 0xFFFF
        dist = math.hypot(*self._xy(self.theta))
        far = math.cos(self.theta - 2.6) > 0.55
        p_loss = 0.02
        if self.mode == "drive" and far:
            p_loss = 0.8
        if self.fault == "radio_bad":
            p_loss = max(p_loss, 0.45)
        if self.rng.random() < p_loss:
            return []
        self.rx_count += 1
        rssi = int(-58 - dist * 0.22 - (18 if far else 0) + self.rng.gauss(0, 1.5))
        snr = int(max(-8, 11 - dist * 0.03 - (9 if far else 0) + self.rng.gauss(0, 0.8)))
        if self.receiver_format == "pkt":
            return [format_pkt_line(pack_packet(self.cfg, v), rssi, snr)]
        return format_text_box(v, rssi, snr, self.rx_count)

    def daq_lines(self) -> list[str]:
        v = self.daq_values()
        return [
            f"[TX] RPM:{int(v['rpm'])} | Batt:{v['battery']:.2f} | TPS:{v['tps']:.3f} | "
            f"EngineTemp:{v['engine_temp']:.1f} | TX#{self.tx_count & 0xFFFF} CAN#{self.can_count & 0xFFFF}",
            f"[ECU] MAP:{v['map']:.3f} bar | AirTemp:{v['air_temp']:.1f} | Oil:{v['oil_pressure']:.2f} bar | "
            f"Fuel:{v['fuel_pressure']:.2f} bar | Water:{v['water_pressure']:.2f} bar | Lambda:{v['lambda']:.3f}",
            f"[GPS] Sats:{v['gps_sats']} | Fix:{v['gps_fix']} | Speed:{v['gps_speed']:.1f} kph",
        ]

    def daq_can_line(self) -> str:
        if self.fault == "bus_errors":
            return f"[CAN] TEC:{min(255, 96 + int(self.t) % 120)} | REC:0 | EFLG:0x15 | TXB0CTRL:0x18 | RX:{self.can_count}"
        return f"[CAN] TEC:0 | REC:0 | EFLG:0x00 | TXB0CTRL:0x00 | RX:{self.can_count}"

    # ---- time stepping ----------------------------------------------------

    def step(self, t0: float, t1: float, base: float = 0.0) -> list[tuple[str, object]]:
        """Advance from t0 to t1 (seconds since the sim started). base is added to timestamps."""
        out: list[tuple[str, object]] = []
        ecu_hz = 1.0 if self.fault == "ecu_1hz" else self.ecu_hz
        nxt = self._next
        t = t0
        while True:
            due = min(nxt, key=nxt.get)
            when = nxt[due]
            if when > t1:
                break
            if when > t:
                self._update(when - t)
                t = when
            self.t = t
            ts = base + t
            if due == "ecu":
                for f in self.ecu_frames(ts):
                    out.append(("frame", f))
                    self.can_count += 1
                nxt["ecu"] = when + 1.0 / ecu_hz
            elif due == "daq":
                if self.fault != "daq_missing":
                    out.extend(("frame", f) for f in self.daq_frames(ts))
                nxt["daq"] = when + 0.05
            elif due in ("pdm", "lambda"):
                out.extend(("frame", f) for f in self.other_frames(ts, due))
                nxt[due] = when + 0.1
            elif due == "radio":
                if self.fault != "daq_missing":
                    out.extend(("rxline", (ts, line)) for line in self.radio_lines())
                    out.extend(("daqline", (ts, line)) for line in self.daq_lines())
                nxt["radio"] = when + 0.5
            elif due == "daqcan":
                if self.fault != "daq_missing":
                    out.append(("daqline", (ts, self.daq_can_line())))
                nxt["daqcan"] = when + 1.0
            elif due == "err":
                if self.fault == "bus_errors":
                    out.append(("frame", Frame(ts, 0, False, b"", True)))
                nxt["err"] = when + 0.2
            elif due == "stress":
                if self.stress_fps:
                    n = max(1, self.stress_fps // 100)
                    for i in range(n):
                        out.append(("frame", Frame(ts + i * 1e-5, 0x700 + (i % 16), False,
                                                   struct.pack("<Q", int(t * 1000) + i))))
                nxt["stress"] = when + 0.01
        if t1 > t:
            self._update(t1 - t)
            self.t = t1
        return out
