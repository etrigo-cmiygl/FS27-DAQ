from __future__ import annotations

from .config import MasterConfig
from .engine import Engine
from .model import Frame, SourceStatus
from .radio import ReceiverParser, parse_daq_line


class Pipeline:
    """Feeds source items into the engine. Shared by the live app, replay, export and tests."""

    def __init__(self, cfg: MasterConfig, settings: dict | None = None, history: int = 20000):
        self.engine = Engine(cfg, settings, history)
        self.rx = ReceiverParser(cfg)
        self.last_ts = 0.0

    def reset(self) -> None:
        self.engine.reset()
        self.rx = ReceiverParser(self.engine.cfg)
        self.last_ts = 0.0

    def feed(self, kind: str, payload) -> None:
        e = self.engine
        if kind == "frame":
            e.on_frame(payload)
            self.last_ts = payload.ts
        elif kind == "rxline":
            ts, line = payload
            pkt = self.rx.feed(line, ts)
            if pkt is not None:
                e.radio.format = self.rx.format or ""
                e.on_packet(pkt)
            self.last_ts = ts
        elif kind == "daqline":
            ts, line = payload
            d = parse_daq_line(line, ts)
            if d is not None:
                e.on_daq_line(d)
            self.last_ts = ts
        elif kind == "status":
            e.on_status(payload)

    def run(self, items, tick_every: float = 0.05) -> None:
        next_tick = None
        for kind, payload in items:
            self.feed(kind, payload)
            if next_tick is None:
                next_tick = self.last_ts
            while self.last_ts >= next_tick:
                self.engine.tick(next_tick)
                next_tick += tick_every
        if self.last_ts:
            self.engine.tick(self.last_ts)
