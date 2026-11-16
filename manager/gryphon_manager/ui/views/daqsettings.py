from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QFrame, QMessageBox, QSpinBox

from ... import theme
from ...core import daq_protocol as proto
from ..widgets import Card, View, button, hbox, label, vbox

NOT_CHECKED = ("Connect with 'DAQ over USB' (or the simulator), then press Check DAQ. It reads the DAQ's settings "
               "and unlocks this page. Nothing is changed until you press Send.")


class DaqSettingsView(View):
    title = "DAQ settings"
    subtitle = "Change how the DAQ behaves without reflashing it: GPS rate, radio rate, screen rate."
    refresh_every = 10

    def __init__(self, hub):
        super().__init__(hub)
        self.supported = False
        self.banner = QFrame()
        self.banner.setObjectName("card")
        self.banner_title = label("Not read from the DAQ yet", "h2")
        self.banner_text = label(NOT_CHECKED, "dim", wrap=True)
        self.check_btn = button("Check DAQ", self._check, "primary", tip="Read the settings from the connected DAQ")
        self.banner.setLayout(vbox(self.banner_title, self.banner_text, hbox(self.check_btn, None),
                                   margins=(14, 12, 14, 12)))
        self._banner_colour(theme.AMBER)

        self.form_card = Card("Rates")
        form = QFormLayout()
        form.setHorizontalSpacing(24)
        self.controls = {}
        for key, (_, text, kind, allowed, default, tip) in proto.SETTINGS.items():
            if kind == "choice":
                w = QComboBox()
                for a in allowed:
                    w.addItem(f"{a}", a)
                w.setCurrentIndex(allowed.index(default))
            else:
                w = QSpinBox()
                w.setRange(*allowed)
                w.setValue(default)
            w.setToolTip(tip)
            self.controls[key] = w
            form.addRow(label(text, tip=tip), w)
        self.form_card.add(form)
        self.apply_btn = button("Send to the DAQ", self._apply, "primary")
        self.factory_btn = button("Back to factory settings", self._factory)
        self.safety = label("", "dim", wrap=True)
        self.form_card.add(hbox(self.apply_btn, self.factory_btn, None))
        self.form_card.add(self.safety)
        self.form_card.lay.addStretch(1)

        self.layout_card = Card("What the DAQ is sending")
        self.summary = label("Press Check DAQ to see it.", wrap=True)
        self.layout_card.add(self.summary)
        self.layout_card.add(label(
            "The screen frames and the radio packet are edited in the Channels view. Press Send to DAQ there to "
            "load them into the DAQ.\n\n"
            "Every change is checked by the DAQ, saved to its flash with a checksum, then read back and compared. "
            "The DAQ refuses changes while the engine is running or the car is moving. Factory settings are "
            "exactly what the FS26 firmware sent: frames 0x600 to 0x603, a 68-byte radio packet twice a second, "
            "GPS at 5 Hz.\n\n"
            "The line format is written up in the repo wiki: DAQ-Settings-Protocol.", "dim", wrap=True))
        self.inputs_title = label("Spare inputs", "h2")
        self.inputs_text = label("None set up. Add a channel in the Channels view with 'Spare input on the DAQ', "
                                 "then Send to DAQ.", "dim", wrap=True)
        self.layout_card.add(self.inputs_title)
        self.layout_card.add(self.inputs_text)
        self.layout_card.lay.addStretch(1)
        self.inputs: list = []
        self._ticks = 0

        self.root.addWidget(self.banner)
        self.root.addLayout(hbox((self.form_card, 2), (self.layout_card, 3), spacing=12))
        self.root.addStretch(1)
        self._set_enabled(False)
        hub.daq_done.connect(self._done)
        hub.state_changed.connect(self._state_changed)

    def _banner_colour(self, colour: str) -> None:
        self.banner.setStyleSheet(f"QFrame#card {{ border: 1px solid {colour}; }}")

    def _set_enabled(self, on: bool) -> None:
        self.supported = on
        for w in self.controls.values():
            w.setEnabled(on)
        self.apply_btn.setEnabled(on)
        self.factory_btn.setEnabled(on)

    def _state_changed(self) -> None:
        if not self.hub.daq_can_talk() and self.supported:
            self._set_enabled(False)
            self.banner_title.setText("Not read from the DAQ yet")
            self.banner_text.setText(NOT_CHECKED)
            self._banner_colour(theme.AMBER)

    def values(self) -> dict:
        return {key: (w.currentData() if isinstance(w, QComboBox) else w.value()) for key, w in self.controls.items()}

    def _ready(self, changing: bool) -> bool:
        if not self.hub.daq_can_talk():
            self.hub.notice.emit("info", "Plug the DAQ in over USB, choose 'DAQ over USB' in the top bar and "
                                         "Connect. Then try again.")
            return False
        if not self.hub.daq_free():
            self.hub.notice.emit("info", "Still talking to the DAQ. Give it a second and try again.")
            return False
        if changing and not self.hub.engine.car_stationary():
            self.hub.notice.emit("warn", "Settings can only be changed when the car isn't moving and the engine "
                                         "is off.")
            return False
        return True

    def _check(self):
        if self._ready(False):
            self.check_btn.setEnabled(False)
            self.hub.daq.read()

    def _apply(self):
        if not self._ready(True):
            return
        values = self.values()
        problems = proto.validate(values)
        if problems:
            self.hub.notice.emit("warn", "Can't send: " + "; ".join(problems))
            return
        self.hub.daq.send_rates(values)

    def _factory(self, confirm: bool = True):
        if not self._ready(True):
            return
        if confirm and QMessageBox.question(
                self, "Factory settings", "Put the DAQ back to factory settings? That's the FS26 screen frames and "
                "radio packet, radio 2 a second, screen 20 a second, GPS 5 Hz.") != QMessageBox.Yes:
            return
        self.hub.daq.factory()

    def _show(self, result: dict) -> None:
        hello, val, layout = result["hello"] or {}, result["val"], result["layout"]
        if val:
            for key, w in self.controls.items():
                try:
                    v = int(val[key])
                except (KeyError, ValueError):
                    continue
                if isinstance(w, QComboBox):
                    w.setCurrentIndex(max(0, w.findData(v)))
                else:
                    w.setValue(v)
            lines = [f"Firmware {hello.get('fw', '?')}", f"Screen frames: {val.get('frames', '?')}",
                     f"Radio packet: {val.get('fields', '?')} fields, {val.get('packet', '?')} bytes, "
                     f"layout version {val.get('layout', '?')}"]
            if layout:
                ids = ", ".join(f"0x{fid:03X}" for fid, _ in layout["frames"])
                lines.insert(2, f"Frame IDs: {ids}")
            self.summary.setText("\n".join(lines))
        if layout:
            self.inputs = layout.get("inputs") or []
            self._show_inputs(None)

    def _input_owner(self, name: str) -> str:
        for ch in self.hub.cfg.channels:
            src = ch.get("source") or {}
            if src.get("type") == "daq_input" and src.get("input") == name:
                return f"{ch.get('name') or ch.get('key')}{(' (' + ch['units'] + ')') if ch.get('units') else ''}"
        return "not in the channel list"

    def _show_inputs(self, live) -> None:
        used = [(i, c) for i, c in enumerate(self.inputs) if c[0]]
        if not used:
            self.inputs_text.setText("None set up. Add a channel in the Channels view with 'Spare input on the "
                                     "DAQ', then Send to DAQ.")
            return
        kinds = {proto.IN_LINEAR: "straight line", proto.IN_THERMISTOR: "thermistor"}
        lines = []
        for i, c in used:
            name = proto.INPUT_NAMES[i]
            now = ""
            if live:
                fitted, values = live
                board = (i - 3) // 4 if name[0] == "X" else None
                if board is not None and not fitted & (1 << board):
                    now = "   board not fitted"
                elif i < len(values):
                    now = f"   now {values[i]:.2f}"
            lines.append(f"{name} ({proto.INPUT_PINS[name]}): {self._input_owner(name)}, {kinds.get(c[0], '?')}{now}")
        self.inputs_text.setText("\n".join(lines))

    def _done(self, result: dict):
        self.check_btn.setEnabled(True)
        if result["op"] == "layout":
            if result["ok"] and result["layout"]:
                self.inputs = result["layout"].get("inputs") or []
                self._show_inputs(None)
            return
        if result["op"] == "inputs":
            if result["ok"] and result["live"]:
                self._show_inputs(result["live"])
            return
        if not result["ok"]:
            if result["code"] == "old":
                self._set_enabled(False)
                self.banner_title.setText("This DAQ has the older firmware")
                self.banner_text.setText(result["error"] + " Everything else in the app works the same with it.")
                self._banner_colour(theme.AMBER)
            self.hub.notice.emit("warn" if result["code"] == "old" else "error",
                                 result["error"] if result["code"] == "old" else "The DAQ said no: " + result["error"])
            return
        self._show(result)
        self._set_enabled(True)
        val = result["val"] or {}
        hello = result["hello"] or {}
        saved = "saved in its flash" if hello.get("saved") == "1" or result["op"] != "read" else "factory, never changed"
        self.banner_title.setText("This DAQ supports settings")
        self.banner_text.setText(f"Firmware {hello.get('fw', '?')}. Settings are {saved}. "
                                 "Change what you need, then press Send to the DAQ.")
        self._banner_colour(theme.GREEN_BRIGHT)
        if result["op"] == "rates":
            self.hub.notice.emit("info", f"Sent, saved and read back the same: GPS {val.get('gps_hz')} Hz, radio "
                                         f"{val.get('radio_hz')} a second, screen {val.get('screen_hz')} a second.")
        elif result["op"] == "factory":
            self.hub.notice.emit("info", "The DAQ is back on factory settings.")

    def refresh(self) -> None:
        self._ticks += 1
        if (self.supported and self._ticks % 2 == 0 and any(c[0] for c in self.inputs) and not self.hub.daq.busy
                and self.hub.daq_can_talk()):
            self.hub.daq.read_inputs()
        if not self.supported:
            self.safety.setText("Greyed out until Check DAQ has read the settings.")
        elif not self.hub.engine.car_stationary():
            self.safety.setText("Locked: the car is moving or the engine is running.")
        else:
            self.safety.setText("Changes are only allowed when the car isn't moving (speed 0, RPM 0).")
