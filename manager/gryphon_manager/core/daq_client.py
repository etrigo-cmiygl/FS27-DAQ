"""Talks the settings protocol to a DAQ one line at a time, waiting for each answer. No Qt in here."""
from __future__ import annotations

from . import daq_protocol as proto

TERMINAL = ("OK", "ERR", "HELLO", "VAL")
OLD_FIRMWARE = ("The DAQ didn't answer, so it's running the older firmware that has no settings. "
                "Nothing was changed. Flash the v2 firmware from the Firmware view to use this.")


class DaqClient:
    timeout = 1.5

    def __init__(self):
        self.busy = False
        self.op = ""
        self.result: dict | None = None
        self._lines: list[str] = []
        self._pos = 0
        self._sent_at = 0.0
        self._waiting = False
        self._replies: list = []
        self._expect = None

    def _start(self, op: str, lines: list[str], expect=None) -> None:
        self.busy, self.op, self.result = True, op, None
        self._lines = [proto.build_line("HELLO")] + lines
        self._pos, self._waiting, self._replies, self._expect = 0, False, [], expect

    def read(self) -> None:
        self._start("read", [proto.build_line("GET"), proto.build_line("GETL")])

    def send_rates(self, values: dict) -> None:
        self._start("rates", [proto.build_line("SET", **values), proto.build_line("SAVE"), proto.build_line("GET"),
                              proto.build_line("GETL")], {"rates": {k: str(v) for k, v in values.items()}})

    def send_layout(self, layout: dict) -> None:
        self._start("layout", [proto.build_line("CANCEL")] + proto.layout_commands(layout)
                    + [proto.build_line("SAVE"), proto.build_line("GET"), proto.build_line("GETL")],
                    {"layout": layout})

    def factory(self) -> None:
        self._start("factory", [proto.build_line("FACTORY"), proto.build_line("GET"), proto.build_line("GETL")])

    def feed(self, line: str) -> None:
        if not self.busy or not self._waiting:
            return
        parsed = proto.parse_line(line)
        if not parsed:
            return
        self._replies.append(parsed)
        cmd, args = parsed
        if cmd == "ERR":
            self._finish(False, proto.ERRORS.get(args[0] if args else "", "the DAQ refused, with no reason given."),
                         args[0] if args else "")
        elif cmd in TERMINAL:
            self._waiting = False
            self._pos += 1

    def poll(self, now: float, write) -> dict | None:
        """Call often. Returns the result once, when the conversation is over."""
        if self.result is not None:
            out, self.result = self.result, None
            return out
        if not self.busy:
            return None
        if self._waiting:
            if now - self._sent_at > self.timeout:
                if self._pos == 0:
                    self._finish(False, OLD_FIRMWARE, "old")
                else:
                    self._finish(False, "The DAQ stopped answering part way through. Nothing was saved unless it "
                                        "says so when you press Check DAQ.", "timeout")
        elif self._pos >= len(self._lines):
            self._finish(True, "", "")
        else:
            try:
                write(self._lines[self._pos])
            except Exception as exc:
                self._finish(False, f"Couldn't write to the DAQ ({exc}).", "write")
            else:
                self._waiting, self._sent_at = True, now
        if self.result is not None and not self.busy:
            out, self.result = self.result, None
            return out
        return None

    def cancel(self) -> None:
        self.busy = False

    def _finish(self, ok: bool, error: str, code: str) -> None:
        hello = val = None
        for cmd, args in self._replies:
            if cmd == "HELLO":
                hello = proto.key_values(args)
            elif cmd == "VAL":
                val = proto.key_values(args)
        layout = proto.parse_layout(self._replies) if any(c == "RPN" for c, _ in self._replies) else None
        if ok and self._expect:
            want = self._expect
            if "rates" in want and (val is None or any(val.get(k) != v for k, v in want["rates"].items())
                                    or val.get("unsaved") != "0"):
                ok, error, code = False, "The DAQ answered, but read back different values to the ones sent.", "verify"
            if "layout" in want and (layout is None or not proto.same_layout(layout, want["layout"])
                                     or val is None or val.get("unsaved") != "0"):
                ok, error, code = False, "The DAQ answered, but read back a different layout to the one sent.", "verify"
        self._waiting = False
        self.result = {"op": self.op, "ok": ok, "error": error, "code": code, "hello": hello, "val": val,
                       "layout": layout}
        self.busy = False
