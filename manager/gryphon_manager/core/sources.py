from __future__ import annotations

import queue
import threading
import time

from .model import Frame, SourceStatus

PEAK_DRIVER_URL = "https://www.peak-system.com/Drivers.523.0.html?&L=1"


def friendly_can_error(interface: str, exc: Exception) -> str:
    text = str(exc)
    low = text.lower()
    if interface == "pcan":
        if "pcanbasic" in low or "library" in low or "dll" in low or "could not be loaded" in low \
                or isinstance(exc, (ImportError, OSError, NotImplementedError)):
            return ("The PEAK driver isn't installed, so Windows can't talk to the PCAN-USB.\n"
                    f"Download and run the 'Device driver setup' from {PEAK_DRIVER_URL} "
                    "(leave PCAN-Basic ticked), then unplug the adapter, plug it back in and press Connect.")
        return ("Couldn't open the PCAN-USB. Is it plugged in, and not open in PCAN-View or another app? "
                "In Parallels, check Devices > USB so the adapter is given to Windows.\n"
                f"(Details: {text})")
    if interface == "slcan":
        return f"Couldn't open the serial CAN adapter. Check the COM port is right and not in use.\n(Details: {text})"
    return f"Couldn't open the CAN adapter.\n(Details: {text})"


class Source(threading.Thread):
    kind = ""
    label = ""
    can_expected = False

    def __init__(self, out: queue.Queue):
        super().__init__(daemon=True)
        self.out = out
        self._stop_evt = threading.Event()
        self.listen_only = True

    def stop(self) -> None:
        self._stop_evt.set()

    def now(self) -> float:
        return time.time()

    def emit(self, kind: str, payload) -> None:
        self.out.put((kind, payload))


class CanSource(Source):
    kind = "can"
    can_expected = True

    def __init__(self, out, interface: str, channel: str, bitrate: int = 1000000, listen_only: bool = True):
        super().__init__(out)
        self.interface, self.channel, self.bitrate = interface, channel, bitrate
        self.listen_only = listen_only
        self.bus = None
        self.label = {"pcan": "PCAN-USB", "slcan": "Serial CAN adapter", "virtual": "Virtual bus"}.get(
            interface, interface)
        self._tx: queue.Queue = queue.Queue()

    def _open(self):
        import can
        kw = {"interface": self.interface, "channel": self.channel, "bitrate": self.bitrate}
        if self.interface == "pcan":
            kw["state"] = can.BusState.PASSIVE if self.listen_only else can.BusState.ACTIVE
        elif self.interface == "slcan":
            kw["listen_only"] = self.listen_only
        elif self.interface == "virtual":
            kw.pop("bitrate")
        return can.Bus(**kw)

    def send(self, can_id: int, ext: bool, data: bytes) -> bool:
        if self.listen_only:
            return False
        self._tx.put((can_id, ext, data))
        return True

    def _status(self) -> SourceStatus:
        import can
        st = SourceStatus(time.time())
        bus = self.bus
        try:
            if self.interface == "pcan":
                code = int(bus.status())
                if code & 0x10:
                    st.state = "Bus off"
                elif code & 0x40008:
                    st.state = "Error passive"
                elif code & 0x04:
                    st.state = "Error warning"
                else:
                    st.state = "OK (listen-only)" if self.listen_only else "OK"
                if code & 0x202:
                    st.detail = "The adapter's receive queue overflowed: some frames were dropped."
                    self._dropped += 1
                    st.dropped = self._dropped
            else:
                state = bus.state
                st.state = {can.BusState.ACTIVE: "OK", can.BusState.PASSIVE: "OK (listen-only)",
                            can.BusState.ERROR: "Error"}.get(state, "OK")
                if self.listen_only and st.state == "OK":
                    st.state = "OK (listen-only)"
        except Exception:
            st.state = "OK (listen-only)" if self.listen_only else "OK"
        return st

    def run(self) -> None:
        import can
        self._dropped = 0
        try:
            self.bus = self._open()
        except Exception as exc:
            self.emit("error", friendly_can_error(self.interface, exc))
            self.emit("ended", None)
            return
        self.emit("opened", self.label + (" (listen-only)" if self.listen_only else " (transmit allowed)"))
        offset = None
        last_status = 0.0
        try:
            while not self._stop_evt.is_set():
                try:
                    msg = self.bus.recv(0.1)
                except can.CanError as exc:
                    self.emit("error", f"The CAN adapter stopped responding. Was it unplugged?\n(Details: {exc})")
                    break
                now = time.time()
                if msg is not None:
                    if offset is None or abs(msg.timestamp + offset - now) > 2.0:
                        offset = now - msg.timestamp
                    self.emit("frame", Frame(msg.timestamp + offset, msg.arbitration_id,
                                             bool(msg.is_extended_id), bytes(msg.data),
                                             bool(msg.is_error_frame)))
                while not self._tx.empty():
                    cid, ext, data = self._tx.get()
                    try:
                        self.bus.send(can.Message(arbitration_id=cid, is_extended_id=ext, data=data))
                    except can.CanError as exc:
                        self.emit("error", f"Couldn't send the frame.\n(Details: {exc})")
                if now - last_status > 0.5:
                    last_status = now
                    self.emit("status", self._status())
        finally:
            try:
                self.bus.shutdown()
            except Exception:
                pass
            self.emit("ended", None)


class SerialSource(Source):
    def __init__(self, out, port: str, baud: int, kind: str):
        super().__init__(out)
        self.port, self.baud = port, baud
        self.kind = kind
        self.item = "rxline" if kind == "radio" else "daqline"
        self.label = ("Receiver" if kind == "radio" else "DAQ USB") + f" on {port}"
        self.ser = None
        self._tx: queue.Queue = queue.Queue()

    def write_line(self, text: str) -> None:
        self._tx.put(text)

    def run(self) -> None:
        import serial
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
        except Exception as exc:
            self.emit("error", f"Couldn't open {self.port}. Is it plugged in, and not open in another program "
                               f"(a serial monitor, the old dashboard)?\n(Details: {exc})")
            self.emit("ended", None)
            return
        self.emit("opened", self.label)
        buf = b""
        try:
            while not self._stop_evt.is_set():
                try:
                    chunk = self.ser.read(4096)
                    while not self._tx.empty():
                        self.ser.write((self._tx.get() + "\n").encode("ascii", "replace"))
                except Exception as exc:
                    self.emit("error", f"Lost {self.port}. Was it unplugged?\n(Details: {exc})")
                    break
                if not chunk:
                    continue
                buf += chunk
                now = time.time()
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    line = raw.decode("utf-8", "replace").rstrip("\r")
                    if line.strip():
                        self.emit(self.item, (now, line))
                if len(buf) > 65536:
                    buf = b""
        finally:
            try:
                self.ser.close()
            except Exception:
                pass
            self.emit("ended", None)


class SimSource(Source):
    kind = "sim"
    label = "Simulator"

    def __init__(self, out, cfg, parts: str = "all", mode: str = "drive", fault: str = "none",
                 ecu_hz: float = 10.0, stress_fps: int = 0, receiver_format: str = "box"):
        super().__init__(out)
        from .simulator import SimCar
        self.car = SimCar(cfg, mode=mode, fault=fault, ecu_hz=ecu_hz, stress_fps=stress_fps,
                          receiver_format=receiver_format)
        self.parts = parts
        self.can_expected = parts in ("all", "can")

    def set_mode(self, mode: str) -> None:
        self.car.mode = mode

    def set_fault(self, fault: str) -> None:
        self.car.fault = fault

    def wanted(self, kind: str) -> bool:
        p = self.parts
        if p == "all":
            return True
        return {"frame": "can", "rxline": "radio", "daqline": "daq"}.get(kind) == p

    def run(self) -> None:
        base = time.time()
        self.emit("opened", self.label)
        t_prev = 0.0
        last_status = 0.0
        while not self._stop_evt.is_set():
            time.sleep(0.02)
            t = time.time() - base
            for kind, payload in self.car.step(t_prev, t, base):
                if self.wanted(kind):
                    self.emit(kind, payload)
            t_prev = t
            if self.can_expected and t - last_status > 0.5:
                last_status = t
                state = "Error passive" if self.car.fault == "bus_errors" else "OK (listen-only)"
                self.emit("status", SourceStatus(base + t, state))
        self.emit("ended", None)


class ReplaySource(Source):
    kind = "replay"

    def __init__(self, out, session_path: str, speed: float = 1.0):
        super().__init__(out)
        self.session_path = session_path
        self.speed = speed
        self.paused = False
        self.events: list = []
        self.pos = 0
        self.t0 = 0.0
        self.duration = 0.0
        self.clock = 0.0
        self._seek: float | None = None
        self.loaded = threading.Event()
        self.finished = False
        self.label = "Replay"

    def now(self) -> float:
        return self.clock or time.time()

    def seek(self, seconds: float) -> None:
        self._seek = max(0.0, min(self.duration, seconds))

    @property
    def position(self) -> float:
        return max(0.0, self.clock - self.t0) if self.t0 else 0.0

    def run(self) -> None:
        from .recorder import load_events
        try:
            self.events = load_events(self.session_path)
        except Exception as exc:
            self.emit("error", f"Couldn't open that recording.\n(Details: {exc})")
            self.emit("ended", None)
            return
        if not self.events:
            self.emit("error", "That recording is empty.")
            self.emit("ended", None)
            return
        self.t0 = self.events[0][0]
        self.duration = self.events[-1][0] - self.t0
        self.clock = self.t0
        self.can_expected = any(k == "frame" for _, k, _ in self.events[:2000])
        self.loaded.set()
        self.emit("opened", self.label)
        last = time.time()
        n = len(self.events)
        while not self._stop_evt.is_set():
            time.sleep(0.01)
            now = time.time()
            dt, last = now - last, now
            if self._seek is not None:
                target = self.t0 + self._seek
                self._seek = None
                self.emit("reset", None)
                lo, hi = 0, n
                while lo < hi:
                    mid = (lo + hi) // 2
                    if self.events[mid][0] < target:
                        lo = mid + 1
                    else:
                        hi = mid
                self.pos = lo
                self.clock = target
                self.finished = False
                continue
            if self.paused or self.finished:
                continue
            self.clock += dt * self.speed
            while self.pos < n and self.events[self.pos][0] <= self.clock:
                _, kind, payload = self.events[self.pos]
                self.emit(kind, payload)
                self.pos += 1
            if self.pos >= n:
                self.finished = True
                self.clock = self.t0 + self.duration
                self.emit("finished", None)
        self.emit("ended", None)


def list_serial_ports() -> list[tuple[str, str]]:
    try:
        from serial.tools import list_ports
        return [(p.device, f"{p.device}  {p.description}") for p in list_ports.comports()]
    except Exception:
        return []
