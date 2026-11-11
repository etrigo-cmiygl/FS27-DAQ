from __future__ import annotations

import csv
import json
import re
import time
from datetime import datetime
from pathlib import Path

import can

from .config import MasterConfig
from .model import Frame
from .paths import sessions_dir
from .pipeline import Pipeline


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip()).strip("_")[:40]


class Recorder:
    """Writes one session folder: raw CAN (.blf or .asc), raw radio/DAQ lines, alarms, meta.json."""

    def __init__(self):
        self.dir: Path | None = None
        self.started = 0.0
        self.meta: dict = {}
        self._can = None
        self._files: dict = {}
        self.counts = {"frames": 0, "radio_lines": 0, "daq_lines": 0, "alarms": 0}

    @property
    def active(self) -> bool:
        return self.dir is not None

    def start(self, meta: dict, log_format: str = "blf", root: Path | None = None) -> Path:
        self.stop()
        now = datetime.now()
        name = now.strftime("%Y-%m-%d_%H%M%S")
        if meta.get("name"):
            name += "_" + safe_name(meta["name"])
        d = (root or sessions_dir()) / name
        d.mkdir(parents=True, exist_ok=True)
        self.dir = d
        self.started = time.time()
        self.log_format = "asc" if log_format == "asc" else "blf"
        self.meta = dict(meta)
        self.meta.setdefault("name", now.strftime("Session %H:%M"))
        self.meta["date"] = now.isoformat(timespec="seconds")
        self.counts = {k: 0 for k in self.counts}
        self._write_meta()
        return d

    def _write_meta(self, final: bool = False) -> None:
        if not self.dir:
            return
        meta = dict(self.meta)
        meta.update(self.counts)
        meta["duration_s"] = round(time.time() - self.started, 1)
        meta["finished"] = final
        (self.dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def _text(self, name: str):
        fh = self._files.get(name)
        if fh is None:
            fh = self._files[name] = open(self.dir / name, "a", encoding="utf-8", newline="\n")
        return fh

    def on_item(self, kind: str, payload) -> None:
        if not self.dir:
            return
        if kind == "frame":
            f: Frame = payload
            if self._can is None:
                path = str(self.dir / f"can.{self.log_format}")
                self._can = can.ASCWriter(path) if self.log_format == "asc" else can.BLFWriter(path)
            self._can.on_message_received(can.Message(
                timestamp=f.ts, arbitration_id=f.id, is_extended_id=f.ext, data=f.data,
                is_error_frame=f.is_error, is_rx=True, channel=0))
            self.counts["frames"] += 1
        elif kind == "rxline":
            ts, line = payload
            self._text("radio.log").write(f"{ts:.4f}\t{line}\n")
            self.counts["radio_lines"] += 1
        elif kind == "daqline":
            ts, line = payload
            self._text("daq.log").write(f"{ts:.4f}\t{line}\n")
            self.counts["daq_lines"] += 1

    def on_alarm(self, event) -> None:
        if not self.dir:
            return
        self._text("alarms.jsonl").write(json.dumps(event.as_dict()) + "\n")
        self.counts["alarms"] += 1

    def stop(self, extra_meta: dict | None = None) -> Path | None:
        d = self.dir
        if not d:
            return None
        if self._can is not None:
            self._can.stop()
            self._can = None
        for fh in self._files.values():
            fh.close()
        self._files = {}
        if extra_meta:
            self.meta.update(extra_meta)
        self._write_meta(final=True)
        self.dir = None
        return d


def list_sessions(root: Path | None = None) -> list[dict]:
    out = []
    root = root or sessions_dir()
    for d in sorted(root.iterdir(), reverse=True) if root.exists() else []:
        mp = d / "meta.json"
        if not d.is_dir() or not mp.exists():
            continue
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        meta["path"] = str(d)
        meta["folder"] = d.name
        out.append(meta)
    return out


def update_meta(session: Path | str, changes: dict) -> None:
    mp = Path(session) / "meta.json"
    meta = json.loads(mp.read_text(encoding="utf-8"))
    meta.update(changes)
    mp.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def load_events(session: Path | str) -> list[tuple[float, str, object]]:
    """Reads a session (or a single .blf/.asc file) back as a time-ordered list of source items."""
    p = Path(session)
    events: list[tuple[float, str, object]] = []
    can_files = [p] if p.is_file() else [p / "can.blf", p / "can.asc"]
    for cf in can_files:
        if not cf.exists():
            continue
        reader = can.LogReader(str(cf), relative_timestamp=False)
        try:
            for m in reader:
                events.append((m.timestamp, "frame", Frame(m.timestamp, m.arbitration_id,
                                                           bool(m.is_extended_id), bytes(m.data),
                                                           bool(m.is_error_frame))))
        finally:
            reader.stop()
    if p.is_dir():
        for name, kind in (("radio.log", "rxline"), ("daq.log", "daqline")):
            fp = p / name
            if not fp.exists():
                continue
            with open(fp, "r", encoding="utf-8") as fh:
                for row in fh:
                    ts, _, line = row.rstrip("\n").partition("\t")
                    try:
                        events.append((float(ts), kind, (float(ts), line)))
                    except ValueError:
                        continue
    events.sort(key=lambda e: e[0])
    return events


def load_alarms(session: Path | str) -> list[dict]:
    fp = Path(session) / "alarms.jsonl"
    out = []
    if fp.exists():
        for row in fp.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(row))
            except ValueError:
                pass
    return out


def analyse(session: Path | str, cfg: MasterConfig, settings: dict | None = None, gate=None) -> dict:
    """Decodes a whole session. Returns {t0, duration, series: {key: (times, values)}, stats, laps, names}."""
    events = load_events(session)
    pipe = Pipeline(cfg, settings, history=5_000_000)
    if gate:
        pipe.engine.laps.set_gate(*gate)
    pipe.run(((k, p) for _, k, p in events))
    e = pipe.engine
    t0 = events[0][0] if events else 0.0
    series, stats, names = {}, {}, {}
    for key, sig in e.signals.items():
        if not sig.count:
            continue
        ts = [t - t0 for t in sig.ht]
        vs = list(sig.hv)
        series[key] = (ts, vs)
        names[key] = (sig.name, sig.units)
        stats[key] = {"min": min(vs), "max": max(vs), "avg": sum(vs) / len(vs), "samples": sig.count}
    return {"t0": t0, "duration": (events[-1][0] - t0) if events else 0.0, "series": series,
            "stats": stats, "names": names, "events": len(events),
            "laps": [(l.number, l.start_ts - t0, l.end_ts - t0) for l in e.laps.laps],
            "track": [(t - t0, la, lo, sp) for t, la, lo, sp in e.track]}


def export_csv(session: Path | str, cfg: MasterConfig, out_path: Path | str, step: float = 0.1,
               settings: dict | None = None) -> int:
    """Decoded signals on a fixed time grid (default 10 rows a second), one column per signal."""
    data = analyse(session, cfg, settings)
    keys = sorted(data["series"])
    idx = {k: 0 for k in keys}
    last: dict = {k: "" for k in keys}
    rows = 0
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["time_s"] + [f"{k} [{data['names'][k][1]}]" if data["names"][k][1] else k for k in keys])
        t = 0.0
        while t <= data["duration"] + 1e-9:
            for k in keys:
                ts, vs = data["series"][k]
                i = idx[k]
                while i < len(ts) and ts[i] <= t:
                    last[k] = round(vs[i], 6)
                    i += 1
                idx[k] = i
            w.writerow([round(t, 3)] + [last[k] for k in keys])
            rows += 1
            t += step
    return rows
