from __future__ import annotations

import copy
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QLineEdit, QListWidget, QMessageBox, QTableWidget, QTableWidgetItem)

from ... import theme
from ...core.alarms import DEFAULT_RULES, describe_rule
from ..widgets import Card, View, button, hbox, label, vbox

DEVICES = [("ecu", "ECU"), ("daq", "DAQ"), ("pdm", "PDM"), ("lambda", "Lambda unit")]


def _spin(value: float, lo=-1e6, hi=1e6, decimals=2) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setValue(float(value))
    return s


class RuleDialog(QDialog):
    def __init__(self, parent, hub, rule: dict):
        super().__init__(parent)
        self.setWindowTitle("Alarm rule")
        self.setMinimumWidth(460)
        self.rule = copy.deepcopy(rule)
        r = self.rule
        self.name = QLineEdit(r.get("name", ""))
        self.kind = QComboBox()
        self.kind.addItem("A value goes too high or too low", "signal")
        self.kind.addItem("A device goes missing", "device")
        self.kind.setCurrentIndex(0 if r.get("kind", "signal") == "signal" else 1)
        keys = sorted({k for k in hub.cfg.signal_defs if "." not in k} |
                      {c["key"] for c in hub.cfg.channels} | {"battery"})
        self.signal = QComboBox()
        self.cond_signal = QComboBox()
        self.cond_signal.addItem("(no extra condition)", "")
        for k in keys:
            ch = hub.cfg.channel(k) or {}
            text = f"{ch.get('name', k)}  ({ch.get('units', '')})" if ch.get("units") else ch.get("name", k)
            self.signal.addItem(text, k)
            self.cond_signal.addItem(text, k)
        self._set(self.signal, r.get("signal", "oil_pressure"))
        self._set(self.cond_signal, r.get("cond_signal", ""))
        self.op = QComboBox()
        self.cond_op = QComboBox()
        for c in (self.op, self.cond_op):
            c.addItem("is below", "<")
            c.addItem("is above", ">")
        self._set(self.op, r.get("op", "<"))
        self._set(self.cond_op, r.get("cond_op", ">"))
        self.value = _spin(r.get("value", 0))
        self.cond_value = _spin(r.get("cond_value", 0))
        self.hold = _spin(r.get("hold_s", 0.5), 0, 60, 1)
        self.hold.setSuffix(" s")
        self.hold.setToolTip("How long it must stay bad before the alarm goes off. Stops single glitches.")
        self.device = QComboBox()
        for k, text in DEVICES:
            self.device.addItem(text, k)
        self._set(self.device, r.get("device", "ecu"))
        self.seconds = _spin(r.get("seconds", 3), 0.5, 120, 1)
        self.seconds.setSuffix(" s")
        self.sound = QCheckBox("Play a sound")
        self.sound.setChecked(bool(r.get("sound", True)))
        self.form = QFormLayout()
        self.form.addRow("Name", self.name)
        self.form.addRow("Go off when", self.kind)
        self.form.addRow("Value", self.signal)
        self.form.addRow("", hbox(self.op, self.value))
        self.form.addRow("Only while", self.cond_signal)
        self.form.addRow("", hbox(self.cond_op, self.cond_value))
        self.form.addRow("For at least", self.hold)
        self.form.addRow("Device", self.device)
        self.form.addRow("Missing for", self.seconds)
        self.form.addRow("", self.sound)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        self.setLayout(vbox(self.form, box, margins=(18, 18, 18, 18)))
        self.kind.currentIndexChanged.connect(self._sync)
        self._sync()

    @staticmethod
    def _set(combo, data):
        i = combo.findData(data)
        if i >= 0:
            combo.setCurrentIndex(i)

    def _sync(self):
        sig = self.kind.currentData() == "signal"
        for row in (2, 3, 4, 5, 6):
            self.form.setRowVisible(row, sig)
        for row in (7, 8):
            self.form.setRowVisible(row, not sig)

    def _ok(self):
        if not self.name.text().strip():
            QMessageBox.information(self, "Alarm rule", "Give the alarm a name.")
            return
        r = self.rule
        r.update({"name": self.name.text().strip(), "kind": self.kind.currentData(),
                  "enabled": r.get("enabled", True), "sound": self.sound.isChecked()})
        if r["kind"] == "signal":
            r.update({"signal": self.signal.currentData(), "op": self.op.currentData(),
                      "value": self.value.value(), "cond_signal": self.cond_signal.currentData(),
                      "cond_op": self.cond_op.currentData(), "cond_value": self.cond_value.value(),
                      "hold_s": self.hold.value()})
        else:
            r.update({"device": self.device.currentData(), "seconds": self.seconds.value()})
        self.accept()


class AlarmsView(View):
    title = "Alarms"
    subtitle = "Rules that warn you with a red banner (and a sound) when something goes wrong."
    refresh_every = 4

    def __init__(self, hub):
        super().__init__(hub)
        self.now_card = Card("Right now")
        self.now_text = label("", wrap=True)
        self.now_text.setStyleSheet("font-size: 15px;")
        self.now_card.add(self.now_text)
        rules = Card("Rules")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["On", "Name", "Goes off when", "Sound"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(3, 70)
        self.table.horizontalHeader().setSectionResizeMode(2, self.table.horizontalHeader().ResizeMode.Stretch)
        self.table.itemChanged.connect(self._toggled)
        self.table.doubleClicked.connect(lambda *_: self._edit())
        rules.add(self.table, 1)
        rules.add(hbox(button("Add a rule", lambda: self.new_rule(), "primary"), button("Edit", self._edit),
                       button("Delete", self._delete), None,
                       button("Back to the standard rules", self._defaults)))
        log = Card("Alarm log", "Every alarm since you connected. Saved with the recording.")
        self.log = QListWidget()
        log.add(self.log, 1)
        self.root.addWidget(self.now_card)
        self.root.addLayout(hbox((rules, 3), (log, 2), spacing=12), 1)
        self._log_len = -1
        self._fill()

    def _rules(self) -> list:
        return self.hub.settings["alarms"]

    def _commit(self):
        self.hub.settings_changed()
        self._fill()

    def _fill(self):
        self.table.blockSignals(True)
        rules = self._rules()
        self.table.setRowCount(len(rules))
        for i, r in enumerate(rules):
            on = QTableWidgetItem()
            on.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            on.setCheckState(Qt.Checked if r.get("enabled", True) else Qt.Unchecked)
            self.table.setItem(i, 0, on)
            self.table.setItem(i, 1, QTableWidgetItem(r.get("name", "")))
            self.table.setItem(i, 2, QTableWidgetItem(self._describe(r)))
            self.table.setItem(i, 3, QTableWidgetItem("yes" if r.get("sound", True) else "no"))
        self.table.blockSignals(False)

    def _describe(self, r: dict) -> str:
        cfg = self.hub.cfg
        if r.get("kind") == "device":
            return f"{dict(DEVICES).get(r.get('device'), r.get('device'))} missing for more than {r.get('seconds', 3):g} s"

        def nm(key):
            ch = cfg.channel(key) or {}
            return ch.get("name", key), ch.get("units", "")
        n, u = nm(r.get("signal", ""))
        text = f"{n} {'below' if r.get('op') == '<' else 'above'} {r.get('value', 0):g} {u}".strip()
        if r.get("cond_signal"):
            cn, cu = nm(r["cond_signal"])
            text += f", while {cn} is {'below' if r.get('cond_op') == '<' else 'above'} {r.get('cond_value', 0):g} {cu}".rstrip()
        return text

    def _toggled(self, item):
        if item.column() == 0:
            self._rules()[item.row()]["enabled"] = item.checkState() == Qt.Checked
            self.hub.settings_changed()

    def new_rule(self, signal: str = ""):
        rule = {"name": "", "kind": "signal", "enabled": True, "signal": signal or "engine_temp", "op": ">",
                "value": 0.0, "cond_signal": "", "cond_op": ">", "cond_value": 0.0, "hold_s": 0.5, "sound": True}
        if signal:
            ch = self.hub.cfg.channel(signal.split(".")[-1]) or {}
            rule["signal"] = signal.split(".")[-1]
            rule["name"] = f"{ch.get('name', signal)} too high"
            if ch.get("max") is not None:
                rule["value"] = float(ch["max"])
        dlg = RuleDialog(self, self.hub, rule)
        if dlg.exec() == QDialog.Accepted:
            self._rules().append(dlg.rule)
            self._commit()

    def _edit(self):
        row = self.table.currentRow()
        if row < 0:
            self.hub.notice.emit("info", "Click a rule first, then Edit.")
            return
        dlg = RuleDialog(self, self.hub, self._rules()[row])
        if dlg.exec() == QDialog.Accepted:
            self._rules()[row] = dlg.rule
            self._commit()

    def _delete(self):
        row = self.table.currentRow()
        if row < 0:
            self.hub.notice.emit("info", "Click a rule first, then Delete.")
            return
        name = self._rules()[row].get("name", "")
        if QMessageBox.question(self, "Delete rule", f"Delete the alarm '{name}'?") == QMessageBox.Yes:
            del self._rules()[row]
            self._commit()

    def _defaults(self):
        if QMessageBox.question(self, "Standard rules", "Replace all rules with the standard set?") == QMessageBox.Yes:
            self.hub.settings["alarms"] = copy.deepcopy(DEFAULT_RULES)
            self._commit()

    def on_config(self):
        self._fill()

    def refresh(self) -> None:
        a = self.hub.engine.alarms
        if a.active:
            self.now_card.set_status("red")
            self.now_text.setText("\n".join(f"{n}: {t}" for n, t in a.active.items()))
        elif self.hub.state == "connected":
            self.now_card.set_status("green")
            self.now_text.setText("No alarms. All rules are happy.")
        else:
            self.now_card.set_status("grey")
            self.now_text.setText("Not connected. Alarms are checked whenever data is coming in, on any source.")
        if len(a.events) != self._log_len:
            self._log_len = len(a.events)
            self.log.clear()
            for ev in reversed(a.events[-200:]):
                t = datetime.fromtimestamp(ev.ts).strftime("%H:%M:%S")
                self.log.addItem(f"{t}   {'RAISED' if ev.raised else 'cleared'}   {ev.name}: {ev.text}")
                self.log.item(self.log.count() - 1).setForeground(
                    Qt.GlobalColor.white if not ev.raised else __import__("PySide6.QtGui", fromlist=["QColor"]).QColor(theme.RED_BRIGHT))
            if not a.events:
                self.log.addItem("Nothing yet. Alarms that go off will be listed here.")
