from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QSpinBox, QWidget

from ... import theme
from ...core import daq_protocol as proto
from ..widgets import Card, View, button, hbox, label, vbox


class DaqSettingsView(View):
    title = "DAQ settings"
    subtitle = "Change how the DAQ behaves without reflashing it: GPS rate, radio rate, what goes where."
    refresh_every = 10

    def __init__(self, hub):
        super().__init__(hub)
        self.supported = False
        self.banner = QFrame()
        self.banner.setObjectName("card")
        self.banner_title = label("DAQ firmware doesn't support settings yet", "h2")
        self.banner_text = label(
            "This page is ready, but the FS27 DAQ firmware still has its settings fixed in the code "
            "(GPS 5 Hz, radio 2 packets a second, screen 20 frames a second). Once the firmware understands "
            "the settings protocol below, connect with 'DAQ over USB', press Check DAQ, and this page unlocks.",
            "dim", wrap=True)
        self.check_btn = button("Check DAQ", self._check, tip="Ask the connected DAQ whether it supports settings")
        self.banner.setLayout(vbox(self.banner_title, self.banner_text, hbox(self.check_btn, None),
                                   margins=(14, 12, 14, 12)))
        self.banner.setStyleSheet(f"QFrame#card {{ border: 1px solid {theme.AMBER}; }}")

        self.form_card = Card("Settings")
        form = QFormLayout()
        form.setHorizontalSpacing(24)
        self.controls = {}
        for key, (idx, text, kind, allowed, default, tip) in proto.SETTINGS.items():
            if kind == "bool":
                w = QCheckBox("On")
                w.setChecked(bool(default))
            elif kind == "choice":
                w = QComboBox()
                for a in allowed:
                    w.addItem(f"{a}", a)
                w.setCurrentIndex(allowed.index(default))
            else:
                w = QSpinBox()
                w.setRange(*allowed)
                w.setValue(default)
            w.setToolTip(tip)
            lb = label(text, tip=tip)
            self.controls[key] = w
            form.addRow(lb, w)
        self.form_card.add(form)
        self.form_card.add(label("Which channels go over the radio (off / slow / fast) is set per channel in the "
                                 "Channels view.", "dim", wrap=True))
        self.apply_btn = button("Send to the DAQ", self._apply, "primary")
        self.factory_btn = button("Back to factory settings", self._factory)
        self.safety = label("", "dim", wrap=True)
        self.form_card.add(hbox(self.apply_btn, self.factory_btn, None))
        self.form_card.add(self.safety)
        self.form_card.lay.addStretch(1)

        doc = Card("The protocol (for whoever updates the firmware)")
        text = label(
            "USB serial, one line each way:   $GM,<COMMAND>[,key=value...]*CS\n"
            "CS is the XOR of the characters between $ and *, as two hex digits (same idea as NMEA).\n\n"
            "To the DAQ:    HELLO     GET     SET,key=value,...     SAVE     FACTORY\n"
            "From the DAQ:  $GM,HELLO,fw=...,proto=1,settings=<n>     $GM,VAL,key=value,...\n"
            "               $GM,OK,settings=<n>     $GM,ERR,<reason>\n\n"
            "Keys: " + ", ".join(proto.SETTINGS) + ", and ch.<channel key>=off|slow|fast\n\n"
            f"Over CAN the same commands use ID 0x{proto.CAN_ID_REQUEST:03X} to the DAQ and "
            f"0x{proto.CAN_ID_REPLY:03X} back:\n"
            "byte 0 command, byte 1 setting number, bytes 2-5 value (little-endian), byte 6 sequence, "
            "byte 7 sum of bytes 0-6.\n\n"
            "Rules for the firmware: check the checksum and ranges, refuse changes while the car is moving "
            "(RPM above 0 or speed above 2 km/h), keep a factory copy, and reply with the settings version in use.\n"
            "The full write-up is in the repo wiki: DAQ-Settings-Protocol.", wrap=True)
        from PySide6.QtGui import QFontDatabase
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        text.setFont(mono)
        text.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        doc.add(text)
        doc.lay.addStretch(1)

        self.root.addWidget(self.banner)
        self.root.addLayout(hbox((self.form_card, 2), (doc, 3), spacing=12))
        self.root.addStretch(1)
        self._set_enabled(False)

    def _set_enabled(self, on: bool):
        self.supported = on
        for w in self.controls.values():
            w.setEnabled(on)
        self.apply_btn.setEnabled(on)
        self.factory_btn.setEnabled(on)

    def _values(self) -> dict:
        out = {}
        for key, w in self.controls.items():
            if isinstance(w, QCheckBox):
                out[key] = 1 if w.isChecked() else 0
            elif isinstance(w, QComboBox):
                out[key] = w.currentData()
            else:
                out[key] = w.value()
        return out

    def _daq_usb(self) -> bool:
        return self.hub.state == "connected" and self.hub.kind == "daq" and self.hub.source is not None

    def _check(self):
        if not self._daq_usb():
            self.hub.notice.emit("info", "Plug the DAQ in over USB, choose 'DAQ over USB' in the top bar and "
                                         "Connect. Then press Check DAQ.")
            return
        self._mark = len(self.hub.daq_log)
        self.hub.source.write_line(proto.build_line("HELLO"))
        self.check_btn.setEnabled(False)
        QTimer.singleShot(1500, self._check_done)

    def _replies(self) -> list:
        out = []
        for line in list(self.hub.daq_log)[-60:]:
            parsed = proto.parse_line(line)
            if parsed:
                out.append(parsed)
        return out

    def _check_done(self):
        self.check_btn.setEnabled(True)
        hello = [v for cmd, v in self._replies() if cmd == "HELLO"]
        if hello:
            self._set_enabled(True)
            self.banner_title.setText("This DAQ supports settings")
            self.banner_text.setText(f"Firmware {hello[-1].get('fw', '?')}, settings version "
                                     f"{hello[-1].get('settings', '?')}. Change what you need, then send.")
            self.banner.setStyleSheet(f"QFrame#card {{ border: 1px solid {theme.GREEN_BRIGHT}; }}")
        else:
            self.hub.notice.emit("warn", "The DAQ didn't answer, so its firmware doesn't support settings yet. "
                                         "Nothing was changed.")

    def _apply(self):
        if not self._daq_usb():
            self.hub.notice.emit("warn", "Connect with 'DAQ over USB' first.")
            return
        if not self.hub.engine.car_stationary():
            self.hub.notice.emit("warn", "Settings can only be changed when the car isn't moving and the engine is off.")
            return
        values = self._values()
        problems = proto.validate(values)
        if problems:
            self.hub.notice.emit("warn", "Can't send: " + "; ".join(problems))
            return
        self.hub.source.write_line(proto.build_line("SET", **values))
        self.hub.source.write_line(proto.build_line("SAVE"))
        QTimer.singleShot(1500, self._apply_done)

    def _apply_done(self):
        replies = self._replies()
        ok = [v for cmd, v in replies if cmd == "OK"]
        err = [v for cmd, v in replies if cmd == "ERR"]
        if err:
            self.hub.notice.emit("error", f"The DAQ refused: {err[-1].get('_', 'no reason given')}")
        elif ok:
            self.hub.notice.emit("info", f"The DAQ is now using settings version {ok[-1].get('settings', '?')}.")
        else:
            self.hub.notice.emit("warn", "No reply from the DAQ. The settings may not have been applied.")

    def _factory(self):
        if self._daq_usb() and self.hub.engine.car_stationary():
            self.hub.source.write_line(proto.build_line("FACTORY"))
            QTimer.singleShot(1500, self._apply_done)

    def refresh(self) -> None:
        if not self.supported:
            self.safety.setText("Greyed out until the DAQ firmware supports settings.")
        elif not self.hub.engine.car_stationary():
            self.safety.setText("Locked: the car is moving or the engine is running.")
        else:
            self.safety.setText("Changes are only allowed when the car isn't moving (speed 0, RPM 0).")
