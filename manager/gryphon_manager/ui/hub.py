from __future__ import annotations

import queue
import time
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.config import MasterConfig
from ..core.paths import active_config_path
from ..core.pipeline import Pipeline
from ..core.recorder import Recorder
from ..core.settings import Settings
from ..core.simulator import SIM_DEVICES
from ..core.sources import CanSource, ReplaySource, SerialSource, SimSource

SOURCE_NAMES = {"can": "Car (CAN cable)", "radio": "Radio (pit receiver)", "daq": "DAQ over USB",
                "sim": "Simulator", "replay": "Replay a recording"}


class Hub(QObject):
    """The one object every view talks to: owns the engine, the data source and the recorder."""

    tick = Signal()
    state_changed = Signal()
    notice = Signal(str, str)
    alarm = Signal(object)
    config_changed = Signal()
    replay_finished = Signal()
    navigate = Signal(str)

    def __init__(self, settings: Settings | None = None, config_path=None):
        super().__init__()
        self.settings = settings or Settings()
        self.config_path = config_path or active_config_path()
        self.cfg = MasterConfig.load(self.config_path)
        self.pipe = Pipeline(self.cfg, self.settings.data)
        self.engine = self.pipe.engine
        self._load_extra_dbcs()
        self.q: queue.Queue = queue.Queue()
        self.source = None
        self.kind = ""
        self.state = "disconnected"
        self.label = ""
        self.last_error = ""
        self.connected_at = 0.0
        self.recorder = Recorder()
        self._wanted = None
        self._was_connected = False
        self._resume_recording = False
        self._retry_at = 0.0
        self.retry_seconds = 2.0
        self.trace: deque = deque(maxlen=4000)
        self.trace_enabled = False
        self.trace_serial = 0
        self.daq_log: deque = deque(maxlen=400)
        self.ticks = 0
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._on_timer)
        self.timer.start()

    # ---- config and settings ------------------------------------------------

    def _load_extra_dbcs(self) -> None:
        import cantools
        dbs = []
        for path in self.settings.get("extra_dbcs") or []:
            try:
                dbs.append(cantools.database.load_file(path))
            except Exception as exc:
                self.last_error = f"Couldn't load DBC {path}: {exc}"
        self.engine.extra_dbs = dbs

    def reload_config(self) -> None:
        self.cfg = MasterConfig.load(self.config_path)
        self.engine.set_config(self.cfg)
        self.pipe.reset()
        self._load_extra_dbcs()
        self._after_reset()
        self.config_changed.emit()

    def settings_changed(self) -> None:
        self.settings.save()
        self.engine.apply_settings(self.settings.data)
        self._load_extra_dbcs()
        self.config_changed.emit()

    def _after_reset(self) -> None:
        self.engine.set_sim_devices(SIM_DEVICES if self.kind == "sim" else {})
        if self.source is not None and self.state == "connected":
            self.engine.mark_connected(self.source.now(), self.source.can_expected)

    # ---- connecting ---------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self.state == "connected"

    def _make_source(self, kind: str, opts: dict):
        s = self.settings
        if kind == "can":
            iface = opts.get("interface") or s["can_interface"]
            channel = opts.get("channel") or (s["slcan_port"] if iface == "slcan" else s["can_channel"])
            return CanSource(self.q, iface, channel, self.engine.bitrate, listen_only=not s["allow_transmit"])
        if kind in ("radio", "daq"):
            port = opts.get("port") or s["receiver_port" if kind == "radio" else "daq_port"]
            return SerialSource(self.q, port, int(s["serial_baud"]), kind)
        if kind == "sim":
            return SimSource(self.q, self.cfg, parts=opts.get("parts", s["sim_parts"]),
                             mode=opts.get("mode", s["sim_mode"]), fault=opts.get("fault", s["sim_fault"]),
                             stress_fps=opts.get("stress_fps", 0), warmup=opts.get("warmup", 0.0))
        if kind == "replay":
            return ReplaySource(self.q, opts["path"], opts.get("speed", 1.0))
        return None

    def connect_source(self, kind: str, **opts) -> None:
        self.disconnect_source()
        self.q = queue.Queue()
        self.kind = kind
        self.last_error = ""
        self.pipe.reset()
        self.trace.clear()
        self.daq_log.clear()
        self.engine.set_sim_devices(SIM_DEVICES if kind == "sim" else {})
        self.source = self._make_source(kind, opts)
        if self.source is None:
            return
        self._wanted = (kind, dict(opts))
        self._was_connected = False
        self._resume_recording = False
        self.state = "connecting"
        self.source.start()
        self.state_changed.emit()

    def disconnect_source(self) -> None:
        self._wanted = None
        if self.recorder.active:
            self.stop_recording()
        src, self.source = self.source, None
        if src is not None:
            src.stop()
            src.join(1.5)
        self.engine.alarms.active.clear()
        if self.state != "disconnected":
            self.state = "disconnected"
            self.engine.can_expected = False
            self.engine.connected_since = 0.0
            self.state_changed.emit()

    def _source_ended(self) -> None:
        """The source stopped by itself: unplugged, or it never opened."""
        was_recording = self.recorder.active
        if was_recording:
            self.stop_recording()
        self.source = None
        self.engine.can_expected = False
        self.engine.connected_since = 0.0
        self.engine.alarms.active.clear()
        wanted = self._wanted
        if wanted and wanted[0] in ("can", "radio", "daq") and self._was_connected:
            if self.state != "reconnecting":
                self._resume_recording = was_recording
                self.notice.emit("error", (self.last_error.split("\n")[0] or "The connection was lost.")
                                 + " Trying to reconnect: plug it back in, or press Disconnect to stop."
                                 + (" The recording up to this point is saved." if was_recording else ""))
            self.state = "reconnecting"
            self._retry_at = time.time() + self.retry_seconds
        else:
            self._wanted = None
            self.state = "disconnected"
        self.state_changed.emit()

    def _retry(self) -> None:
        kind, opts = self._wanted
        self._retry_at = 0.0
        self.source = self._make_source(kind, opts)
        self.source.start()

    def now(self) -> float:
        return self.source.now() if self.source is not None else time.time()

    @property
    def elapsed(self) -> float:
        if self.recorder.active:
            return time.time() - self.recorder.started
        if self.connected and self.connected_at:
            return time.time() - self.connected_at
        return 0.0

    # ---- recording ----------------------------------------------------------

    def start_recording(self, name: str = "", notes: str = "", root=None) -> None:
        if self.recorder.active:
            return
        meta = {"name": name, "driver": self.settings["driver"], "notes": notes,
                "source": SOURCE_NAMES.get(self.kind, self.kind), "config_version": self.cfg.version}
        self.recorder.start(meta, self.settings["log_format"], root)
        self.state_changed.emit()

    def stop_recording(self):
        if not self.recorder.active:
            return None
        e = self.engine
        extra = {"laps": [round(l.time, 3) for l in e.laps.laps]}
        if e.laps.gate:
            extra["gate"] = list(e.laps.gate)
        path = self.recorder.stop(extra)
        self.state_changed.emit()
        return path

    def toggle_recording(self) -> None:
        if self.recorder.active:
            path = self.stop_recording()
            if path:
                self.notice.emit("info", f"Recording saved: {path.name}. Name it and add notes in Sessions.")
        elif self.connected and self.kind != "replay":
            self.start_recording()
        else:
            self.notice.emit("warn", "Connect to the car, the receiver or the simulator first, then record.")

    # ---- the 20 Hz heartbeat ------------------------------------------------

    def _on_timer(self) -> None:
        q, pipe, rec = self.q, self.pipe, self.recorder
        recording = rec.active
        trace = self.trace if self.trace_enabled else None
        for _ in range(40000):
            try:
                kind, payload = q.get_nowait()
            except queue.Empty:
                break
            if kind == "frame":
                pipe.feed(kind, payload)
                if recording:
                    rec.on_item(kind, payload)
                if trace is not None:
                    trace.append(payload)
                    self.trace_serial += 1
            elif kind in ("rxline", "daqline"):
                pipe.feed(kind, payload)
                if recording:
                    rec.on_item(kind, payload)
                if kind == "daqline":
                    self.daq_log.append(payload[1])
            elif kind == "status":
                pipe.feed(kind, payload)
            elif kind == "opened":
                if self.state == "reconnecting":
                    self.notice.emit("info", "Reconnected.")
                    if self._resume_recording:
                        self.start_recording("after reconnect")
                self._was_connected = True
                self.state = "connected"
                self.label = payload
                self.connected_at = time.time()
                self.engine.mark_connected(self.now(), self.source.can_expected if self.source else False)
                if self.settings["auto_record"] and self.kind != "replay":
                    self.start_recording()
                self.state_changed.emit()
            elif kind == "error":
                self.last_error = payload
                losing = (self._was_connected and self._wanted is not None
                          and self._wanted[0] in ("can", "radio", "daq") and not payload.startswith("Couldn't send"))
                if not losing:
                    self.notice.emit("error", payload)
            elif kind == "ended":
                if self._wanted is not None or self.state != "disconnected":
                    self._source_ended()
            elif kind == "reset":
                pipe.reset()
                self._after_reset()
            elif kind == "finished":
                self.replay_finished.emit()
        if self.state == "reconnecting" and self.source is None and self._retry_at and time.time() >= self._retry_at:
            self._retry()
        self.engine.tick(self.now())
        new = self.engine.alarms.take_new()
        for ev in new:
            if recording:
                rec.on_alarm(ev)
            self.alarm.emit(ev)
        self.ticks += 1
        self.tick.emit()

    def shutdown(self) -> None:
        self.timer.stop()
        self.disconnect_source()
        self.settings.save()
