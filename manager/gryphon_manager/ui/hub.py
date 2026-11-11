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

    def connect_source(self, kind: str, **opts) -> None:
        self.disconnect_source()
        s = self.settings
        self.q = queue.Queue()
        self.kind = kind
        self.last_error = ""
        self.pipe.reset()
        self.trace.clear()
        self.daq_log.clear()
        self.engine.set_sim_devices(SIM_DEVICES if kind == "sim" else {})
        if kind == "can":
            iface = opts.get("interface") or s["can_interface"]
            channel = opts.get("channel") or (s["slcan_port"] if iface == "slcan" else s["can_channel"])
            self.source = CanSource(self.q, iface, channel, self.engine.bitrate,
                                    listen_only=not s["allow_transmit"])
        elif kind in ("radio", "daq"):
            port = opts.get("port") or s["receiver_port" if kind == "radio" else "daq_port"]
            self.source = SerialSource(self.q, port, int(s["serial_baud"]), kind)
        elif kind == "sim":
            self.source = SimSource(self.q, self.cfg, parts=opts.get("parts", s["sim_parts"]),
                                    mode=opts.get("mode", s["sim_mode"]), fault=opts.get("fault", s["sim_fault"]),
                                    stress_fps=opts.get("stress_fps", 0), warmup=opts.get("warmup", 0.0))
        elif kind == "replay":
            self.source = ReplaySource(self.q, opts["path"], opts.get("speed", 1.0))
        else:
            return
        self.state = "connecting"
        self.source.start()
        self.state_changed.emit()

    def disconnect_source(self) -> None:
        if self.recorder.active:
            self.stop_recording()
        src, self.source = self.source, None
        if src is not None:
            src.stop()
            src.join(1.5)
        if self.state != "disconnected":
            self.state = "disconnected"
            self.engine.can_expected = False
            self.engine.connected_since = 0.0
            self.state_changed.emit()

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
                self.notice.emit("info", f"Recording saved: {path.name}")
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
                self.state = "connected"
                self.label = payload
                self.connected_at = time.time()
                self.engine.mark_connected(self.now(), self.source.can_expected if self.source else False)
                if self.settings["auto_record"] and self.kind != "replay":
                    self.start_recording()
                self.state_changed.emit()
            elif kind == "error":
                self.last_error = payload
                self.notice.emit("error", payload)
            elif kind == "ended":
                if self.recorder.active:
                    self.stop_recording()
                self.source = None
                self.state = "disconnected"
                self.engine.can_expected = False
                self.engine.connected_since = 0.0
                self.state_changed.emit()
            elif kind == "reset":
                pipe.reset()
                self._after_reset()
            elif kind == "finished":
                self.replay_finished.emit()
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
