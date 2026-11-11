from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from .alarms import AlarmManager
from .config import MasterConfig
from .laps import LapTimer, haversine_m
from .model import DaqLine, Frame, RadioPacket, SourceStatus, fmt_id, parse_id_list
from .radio import explain_daq_can

HISTORY = 20000
PREFIXES = ("", "daq.", "usb.", "radio.")
SOURCE_LABEL = {"": "ECU", "daq.": "DAQ frame", "usb.": "DAQ USB", "radio.": "radio"}

COMPARE = (
    ("RPM", "rpm", 1.0, 150.0, "rpm"),
    ("Engine temp", "engine_temp", 1.0, 1.0, "C"),
    ("Throttle", "tps", 1.0, 2.0, "%"),
    ("MAP", "map", 100.0, 3.0, "kPa"),
    ("Air temp", "air_temp", 1.0, 1.0, "C"),
)


class Sig:
    __slots__ = ("key", "name", "units", "group", "value", "vmin", "vmax", "last_ts", "count",
                 "source", "note", "lo", "hi", "_rts", "ht", "hv")

    def __init__(self, key, name, units="", group="", source="", note="", lo=None, hi=None, maxlen=HISTORY):
        self.key, self.name, self.units, self.group = key, name, units, group
        self.source, self.note, self.lo, self.hi = source, note, lo, hi
        self.value = None
        self.vmin = None
        self.vmax = None
        self.last_ts = 0.0
        self.count = 0
        self._rts = deque(maxlen=16)
        self.ht = deque(maxlen=maxlen)
        self.hv = deque(maxlen=maxlen)

    def update(self, ts: float, value: float) -> None:
        self.value = value
        self.last_ts = ts
        self.count += 1
        if self.vmin is None or value < self.vmin:
            self.vmin = value
        if self.vmax is None or value > self.vmax:
            self.vmax = value
        self._rts.append(ts)
        self.ht.append(ts)
        self.hv.append(value)

    @property
    def rate(self) -> float:
        r = self._rts
        if len(r) < 2 or r[-1] <= r[0]:
            return 0.0
        return (len(r) - 1) / (r[-1] - r[0])

    @property
    def out_of_range(self) -> bool:
        if self.value is None:
            return False
        return (self.lo is not None and self.value < self.lo) or (self.hi is not None and self.value > self.hi)

    def reset_stats(self) -> None:
        self.vmin = self.vmax = self.value


class FrameStat:
    __slots__ = ("id", "ext", "count", "last_ts", "period_ms", "data", "changed", "change_ts",
                 "_rts", "hint", "device")

    def __init__(self, can_id: int, ext: bool):
        self.id, self.ext = can_id, ext
        self.count = 0
        self.last_ts = 0.0
        self.period_ms = 0.0
        self.data = b""
        self.changed = 0
        self.change_ts = [0.0] * 8
        self._rts = deque(maxlen=24)
        self.hint = ""
        self.device = ""

    @property
    def rate(self) -> float:
        r = self._rts
        if len(r) < 2 or r[-1] <= r[0]:
            return 0.0
        return (len(r) - 1) / (r[-1] - r[0])


@dataclass
class DeviceStatus:
    key: str
    label: str
    status: str = "grey"
    text: str = "Not connected"
    rate: float = 0.0
    expected: float = 0.0
    last_seen: float = 0.0
    age: float | None = None
    seen_ids: int = 0
    total_ids: int = 0
    missing: list = field(default_factory=list)


@dataclass
class CheckResult:
    status: str = "grey"
    title: str = ""
    text: str = ""
    rows: list = field(default_factory=list)


class RadioLink:
    def __init__(self):
        self.reset()

    def reset(self):
        self.received = 0
        self.lost = 0
        self.last_ts = 0.0
        self.rssi = None
        self.snr = None
        self.last_tx = None
        self.restarts = 0
        self._rts = deque(maxlen=12)
        self.loss_points: list[tuple[float, float]] = []
        self.format = ""

    @property
    def rate(self) -> float:
        r = self._rts
        if len(r) < 2 or r[-1] <= r[0]:
            return 0.0
        return (len(r) - 1) / (r[-1] - r[0])

    @property
    def loss_pct(self) -> float:
        total = self.received + self.lost
        return 100.0 * self.lost / total if total else 0.0


class Engine:
    """Everything the app knows about the car right now. No Qt in here, so it runs headless."""

    def __init__(self, cfg: MasterConfig, settings: dict | None = None, history: int = HISTORY):
        self.settings = settings or {}
        self.history = history
        self.alarms = AlarmManager(self.settings.get("alarms"))
        self.laps = LapTimer()
        self.set_config(cfg)

    def set_config(self, cfg: MasterConfig) -> None:
        self.cfg = cfg
        self.bitrate = int((cfg.data.get("bus") or {}).get("bitrate", 1000000))
        self.extra_dbs: list = []
        self.reset()

    def reset(self) -> None:
        cfg = self.cfg
        self.signals: dict[str, Sig] = {}
        for key, sd in cfg.signal_defs.items():
            self.signals[key] = Sig(key, sd.name, sd.units, sd.group, fmt_id(sd.can_id, sd.ext),
                                    sd.note, sd.vmin, sd.vmax, self.history)
        self.frames: dict[tuple[int, bool], FrameStat] = {}
        self.device_ids: dict[str, dict] = {}
        self.sim_devices: dict[str, list[int]] = {}
        self._build_devices()
        self.devices: dict[str, DeviceStatus] = {
            k: DeviceStatus(k, d["label"], expected=d["expected_hz"]) for k, d in self.device_ids.items()}
        self.radio = RadioLink()
        self.track: deque = deque(maxlen=20000)
        self.daq_can: dict = {}
        self.daq_can_ts = 0.0
        self.daq_boot: list[str] = []
        self.daq_tx_fail = 0
        self.bus_state = ""
        self.bus_detail = ""
        self.error_frames = 0
        self.dropped = 0
        self.bus_load = 0.0
        self.frame_rate = 0.0
        self.total_frames = 0
        self._win_start = 0.0
        self._win_bits = 0
        self._win_frames = 0
        self.first_ts = 0.0
        self.now = 0.0
        self.connected_since = 0.0
        self.can_expected = False
        self.ecu_check = CheckResult(title="ECU broadcast rate")
        self.daq_check = CheckResult(title="DAQ frames vs ECU")
        self._mismatch_since: dict[str, float] = {}
        self._track_ts = 0.0
        self.laps.reset()
        self.alarms.reset()

    def _build_devices(self) -> None:
        s = self.settings
        self.device_ids = {}
        for key, dev in self.cfg.devices.items():
            ids = list(dev["ids"])
            ext = dev["extended"]
            override = s.get(f"{key}_ids")
            if override:
                try:
                    ids = parse_id_list(override)
                    ext = any(i > 0x7FF for i in ids)
                except ValueError:
                    pass
            if key in self.sim_devices:
                ids = self.sim_devices[key]
            expected = dev["expected_hz"]
            if key == "ecu" and s.get("ecu_expected_hz"):
                expected = float(s["ecu_expected_hz"])
            self.device_ids[key] = {"label": dev["label"], "ids": ids, "extended": ext,
                                    "expected_hz": expected}
        self._id_device: dict[tuple[int, bool], str] = {}
        for key, dev in self.device_ids.items():
            for i in dev["ids"]:
                self._id_device[(i, dev["extended"] or i > 0x7FF)] = key

    def set_sim_devices(self, mapping: dict[str, list[int]]) -> None:
        self.sim_devices = dict(mapping)
        self._build_devices()
        for k, d in self.device_ids.items():
            if k not in self.devices:
                self.devices[k] = DeviceStatus(k, d["label"])
            self.devices[k].expected = d["expected_hz"]
        for fs in self.frames.values():
            fs.device = self._id_device.get((fs.id, fs.ext), "")

    def apply_settings(self, settings: dict) -> None:
        self.settings = settings
        self.alarms.set_rules(settings.get("alarms"))
        self.set_sim_devices(self.sim_devices)

    def mark_connected(self, now: float, can_expected: bool) -> None:
        self.connected_since = now
        self.can_expected = can_expected

    # ---- inputs -------------------------------------------------------------

    def on_frame(self, f: Frame) -> None:
        ts = f.ts
        if not self.first_ts:
            self.first_ts = ts
        if f.is_error:
            self.error_frames += 1
            return
        self.total_frames += 1
        self._win_frames += 1
        self._win_bits += int(((67 if f.ext else 47) + 8 * len(f.data)) * 1.1)
        key = (f.id, f.ext)
        fs = self.frames.get(key)
        if fs is None:
            fs = self.frames[key] = FrameStat(f.id, f.ext)
            fs.device = self._id_device.get(key, "")
            defs = self.cfg.by_id.get(key)
            if defs:
                fs.hint = ", ".join(d.name.replace("DAQ to screen: ", "") for d in defs)
        if fs.count:
            fs.period_ms = (ts - fs.last_ts) * 1000.0
            old = fs.data
            data = f.data
            if old != data:
                mask = 0
                for i in range(min(len(old), len(data))):
                    if old[i] != data[i]:
                        mask |= 1 << i
                        fs.change_ts[i] = ts
                fs.changed = mask
        fs.count += 1
        fs.last_ts = ts
        fs.data = f.data
        fs._rts.append(ts)
        defs = self.cfg.by_id.get(key)
        if defs:
            sigs = self.signals
            for sd in defs:
                v = sd.decode(f.data)
                if v is not None:
                    sigs[sd.key].update(ts, v)
        elif self.extra_dbs:
            self._decode_extra(f)

    def _decode_extra(self, f: Frame) -> None:
        for db in self.extra_dbs:
            try:
                msg = db.get_message_by_frame_id(f.id)
            except KeyError:
                continue
            if msg.is_extended_frame != f.ext:
                continue
            try:
                decoded = msg.decode(f.data, decode_choices=False)
            except Exception:
                continue
            fs = self.frames[(f.id, f.ext)]
            if not fs.hint:
                fs.hint = msg.name
            for name, value in decoded.items():
                key = f"{msg.name}.{name}"
                sig = self.signals.get(key)
                if sig is None:
                    sg = msg.get_signal_by_name(name)
                    sig = self.signals[key] = Sig(key, f"{msg.name}: {name}", sg.unit or "", "Extra DBC",
                                                  fmt_id(f.id, f.ext), "", sg.minimum, sg.maximum, self.history)
                if isinstance(value, (int, float)):
                    sig.update(f.ts, float(value))
            return

    def _set(self, key: str, ts: float, value, source: str) -> None:
        sig = self.signals.get(key)
        if sig is None:
            base = key.split(".", 1)[1] if "." in key else key
            ch = self.cfg.channel(base) or {}
            prefix = key[: len(key) - len(base)]
            label = {"radio.": "Radio: ", "usb.": "DAQ USB: "}.get(prefix, "")
            group = {"radio.": "Radio telemetry", "usb.": "DAQ USB"}.get(prefix, ch.get("group", ""))
            sig = self.signals[key] = Sig(key, label + ch.get("name", base), ch.get("units", "") or "",
                                          group, source, "", ch.get("min"), ch.get("max"), self.history)
        sig.update(ts, float(value))

    def on_packet(self, p: RadioPacket) -> None:
        r = self.radio
        if not self.first_ts:
            self.first_ts = p.ts
        v = p.values
        tx = v.get("tx_count")
        lost_here = 0
        if tx is not None and r.last_tx is not None:
            gap = (int(tx) - int(r.last_tx)) & 0xFFFF
            if 1 < gap < 2000:
                lost_here = gap - 1
                r.lost += lost_here
            elif gap >= 2000 or gap == 0:
                r.restarts += 1
        if tx is not None:
            r.last_tx = int(tx)
        r.received += 1
        r.last_ts = p.ts
        r.rssi, r.snr = p.rssi, p.snr
        r._rts.append(p.ts)
        for k, val in v.items():
            if val is not None:
                self._set("radio." + k, p.ts, val, "radio")
        if p.rssi is not None:
            self._set("radio.rssi", p.ts, p.rssi, "radio")
            self.signals["radio.rssi"].name, self.signals["radio.rssi"].units = "Radio: signal strength", "dBm"
        if p.snr is not None:
            self._set("radio.snr", p.ts, p.snr, "radio")
            self.signals["radio.snr"].name, self.signals["radio.snr"].units = "Radio: signal to noise", "dB"
        lat, lon = v.get("gps_lat"), v.get("gps_lon")
        if lat is not None and lon is not None and v.get("gps_fix", 1):
            if self._add_track(p.ts, lat, lon, v.get("gps_speed", 0.0) or 0.0) and lost_here:
                r.loss_points.append((lat, lon))
                if len(self.track) >= 2:
                    prev = self.track[-2]
                    r.loss_points.append((prev[1], prev[2]))

    def _add_track(self, ts: float, lat: float, lon: float, speed: float) -> bool:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (abs(lat) < 1e-6 and abs(lon) < 1e-6):
            return False
        if self.track:
            pt, plat, plon, _ = self.track[-1]
            dist = haversine_m(plat, plon, lat, lon)
            if dist > 500 and ts - pt < 10:
                return False
        self.track.append((ts, lat, lon, speed))
        self.laps.add_point(ts, lat, lon)
        return True

    def on_daq_line(self, d: DaqLine) -> None:
        if not self.first_ts:
            self.first_ts = d.ts
        if d.kind == "CAN":
            self.daq_can = d.values
            self.daq_can_ts = d.ts
            for k, v in d.values.items():
                self._set("usb.can_" + k, d.ts, v, "DAQ USB")
        elif d.kind == "BOOT":
            self.daq_boot.append(d.text)
            del self.daq_boot[:-30]
        elif d.kind == "TXFAIL":
            self.daq_tx_fail += 1
        else:
            for k, v in d.values.items():
                self._set("usb." + k, d.ts, v, "DAQ USB")

    def on_status(self, s: SourceStatus) -> None:
        if s.state:
            self.bus_state = s.state
        if s.detail:
            self.bus_detail = s.detail
        if s.error_frames is not None:
            self.error_frames = max(self.error_frames, s.error_frames)
        if s.dropped is not None:
            self.dropped = s.dropped

    # ---- lookups ------------------------------------------------------------

    def best(self, key: str, max_age: float = 3.0) -> Sig | None:
        newest = None
        for p in PREFIXES:
            s = self.signals.get(p + key)
            if s is None or s.value is None:
                continue
            if self.now - s.last_ts <= max_age and p == "":
                return s
            if newest is None or s.last_ts > newest.last_ts:
                newest = s
        return newest

    def value(self, key: str, max_age: float = 3.0):
        s = self.best(key, max_age)
        if s is None or self.now - s.last_ts > max_age:
            return None
        return s.value

    def fresh(self, key: str, max_age: float = 3.0) -> bool:
        s = self.signals.get(key)
        return bool(s and s.value is not None and self.now - s.last_ts <= max_age)

    def is_known(self, fs: FrameStat) -> bool:
        return bool(fs.device or fs.hint)

    def car_stationary(self) -> bool:
        rpm = self.value("rpm")
        speed = self.value("gps_speed")
        return (rpm is None or rpm < 50) and (speed is None or speed < 2.0)

    # ---- periodic work ------------------------------------------------------

    def tick(self, now: float) -> None:
        self.now = now
        if not self._win_start:
            self._win_start = now
        elapsed = now - self._win_start
        if elapsed >= 1.0:
            self.bus_load = min(100.0, 100.0 * self._win_bits / (self.bitrate * elapsed))
            self.frame_rate = self._win_frames / elapsed
            self._win_bits = self._win_frames = 0
            self._win_start = now
        if now - self.radio.last_ts > 3.0:
            la, lo = self.signals.get("daq.gps_lat"), self.signals.get("daq.gps_lon")
            fix = self.signals.get("daq.gps_fix")
            if la and lo and la.value is not None and lo.value is not None and la.last_ts > self._track_ts \
                    and (fix is None or fix.value):
                if la.last_ts - self._track_ts >= 0.2:
                    sp = self.signals.get("daq.gps_speed")
                    self._add_track(la.last_ts, la.value, lo.value, (sp.value if sp and sp.value else 0.0))
                    self._track_ts = la.last_ts
        self._update_devices(now)
        self._check_ecu(now)
        self._check_daq(now)
        self.alarms.evaluate(self, now)

    def _update_devices(self, now: float) -> None:
        waited = now - self.connected_since if self.connected_since else 0.0
        for key, dev in self.device_ids.items():
            st = self.devices[key]
            st.label, st.expected = dev["label"], dev["expected_hz"]
            ids = dev["ids"]
            st.total_ids = len(ids)
            if not ids:
                st.rate, st.age, st.seen_ids, st.missing = 0.0, None, 0, []
                if key == "screen":
                    daq = self.devices.get("daq")
                    if daq and daq.status in ("green", "amber"):
                        st.status = "green"
                        st.text = "Being sent data. The screen only listens, so tick what it shows in Car test."
                    else:
                        st.status, st.text = "grey", "Listens only. Needs the DAQ's 0x600-0x603 frames."
                else:
                    st.status, st.text = "grey", "ID not known yet. Set it in Settings."
                continue
            rates, last, missing = [], 0.0, []
            for i in ids:
                fs = self.frames.get((i, dev["extended"] or i > 0x7FF))
                if fs is None or not fs.count:
                    missing.append(i)
                    continue
                last = max(last, fs.last_ts)
                limit = min(6.0, max(2.5, 3.0 / fs.rate)) if fs.rate else 2.5
                if now - fs.last_ts > limit:
                    missing.append(i)
                else:
                    rates.append(fs.rate)
            st.seen_ids = len(ids) - len(missing)
            st.missing = missing
            st.last_seen = last
            st.age = (now - last) if last else None
            rates.sort()
            st.rate = rates[len(rates) // 2] if rates else 0.0
            exp = dev["expected_hz"]
            if not last:
                if not self.can_expected:
                    st.status, st.text = "grey", "Not connected"
                elif waited > 3.0:
                    st.status, st.text = "red", "Not seen on the bus"
                else:
                    st.status, st.text = "grey", "Waiting..."
            elif not rates:
                st.status, st.text = "red", f"Stopped {st.age:.0f} s ago"
            elif exp and st.rate < 0.5 * exp:
                st.status = "amber"
                st.text = f"Slow: {st.rate:.1f} Hz, expected about {exp:g} Hz"
            elif missing:
                st.status = "amber"
                st.text = f"{st.seen_ids} of {len(ids)} frames arriving"
            else:
                st.status = "green"
                st.text = f"{st.rate:.1f} Hz" + (f" (expected about {exp:g})" if exp else "")

    def _check_ecu(self, now: float) -> None:
        c = self.ecu_check
        ecu = self.devices.get("ecu")
        c.rows = []
        if ecu is None or not ecu.last_seen:
            c.status, c.text = "grey", "No ECU frames yet."
            return
        ids = self.device_ids["ecu"]["ids"]
        for i in ids:
            fs = self.frames.get((i, True))
            c.rows.append((fmt_id(i, True), fs.rate if fs else 0.0, fs.count if fs else 0))
        exp = ecu.expected or 10.0
        if ecu.status == "red":
            c.status, c.text = "red", "The ECU has stopped broadcasting. Is the ignition on?"
        elif ecu.rate < 0.5 * exp:
            about = "about 1 Hz" if 0.5 <= ecu.rate <= 1.6 else f"{ecu.rate:.1f} Hz"
            c.status = "amber"
            c.text = (f"The ECU is only broadcasting at {about} (expected about {exp:g} Hz). "
                      "Fix it in FTManager: Sensors and Calibrations > CAN communication, "
                      "then raise the simplified broadcast rate.")
        elif ecu.missing:
            miss = ", ".join(fmt_id(i, True) for i in ecu.missing)
            c.status, c.text = "amber", f"Rate is fine but these frames are missing: {miss}."
        else:
            c.status, c.text = "green", f"ECU is broadcasting all {len(ids)} frames at {ecu.rate:.1f} Hz."

    def _check_daq(self, now: float) -> None:
        c = self.daq_check
        daq = self.devices.get("daq")
        c.rows = []
        if daq is None or not daq.last_seen:
            if self.can_expected and self.devices.get("ecu") and self.devices["ecu"].last_seen:
                c.status = "red"
                c.text = ("No DAQ frames (0x600-0x603) on the bus. Is the DAQ powered and plugged in? "
                          "On DAQ USB, check the [CAN] line.")
            else:
                c.status, c.text = "grey", "No DAQ frames yet."
            return
        ecu_period = 1.0 / max(self.devices["ecu"].rate, 0.2) if "ecu" in self.devices else 1.0
        window = max(1.5, 2.5 * ecu_period)
        worst = "green"
        bad = []
        for label, key, factor, tol, units in COMPARE:
            e, d = self.signals.get(key), self.signals.get("daq." + key)
            if not e or not d or e.value is None or d.value is None:
                c.rows.append((label, None, None, units, "grey"))
                continue
            if now - e.last_ts > window or now - d.last_ts > 1.5:
                c.rows.append((label, e.value * factor, d.value, units, "grey"))
                continue
            ev = e.value * factor
            limit = max(tol, abs(ev) * 0.03)
            if abs(ev - d.value) > limit:
                since = self._mismatch_since.setdefault(key, now)
                state = "red" if now - since > 0.75 else "amber"
            else:
                self._mismatch_since.pop(key, None)
                state = "green"
            if state == "red":
                worst = "red"
                bad.append(label)
            c.rows.append((label, ev, d.value, units, state))
        if daq.status == "red":
            c.status, c.text = "red", "The DAQ has stopped sending its screen frames."
        elif worst == "red":
            c.status = "red"
            c.text = "DAQ is sending different values from the ECU: " + ", ".join(bad) + "."
        elif daq.status == "amber":
            c.status, c.text = "amber", f"DAQ frames are arriving but: {daq.text.lower()}."
        elif all(r[4] == "grey" for r in c.rows):
            c.status, c.text = "amber", "DAQ frames are arriving, but there's no fresh ECU data to compare with."
        else:
            c.status, c.text = "green", f"DAQ frames at {daq.rate:.0f} Hz and the values match the ECU."

    def daq_usb_health(self) -> tuple[str, str]:
        if not self.daq_can or self.now - self.daq_can_ts > 5:
            return "grey", "No [CAN] line from the DAQ yet."
        return explain_daq_can(self.daq_can)

    def bus_summary(self) -> tuple[str, str]:
        state = (self.bus_state or "").lower()
        if "off" in state:
            return "red", "Bus off: the adapter has stopped. Check wiring, termination and bit rate."
        if "passive" in state and "listen" not in state:
            return "red", "Error passive: lots of bus errors. Check termination (should read about 60 ohm)."
        if "warning" in state:
            return "amber", "Error warning: some bus errors. Check termination and connectors."
        if self.error_frames and self.frame_rate == 0:
            return "red", "Only error frames. Wrong bit rate, or nothing else is on the bus."
        if self.frame_rate > 0:
            return "green", "Bus OK"
        return "grey", "No frames"
