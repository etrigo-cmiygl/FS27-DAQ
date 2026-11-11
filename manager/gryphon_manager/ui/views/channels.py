from __future__ import annotations

import copy
import difflib
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QSpinBox, QTableView,
                               QTabWidget)

from ... import theme
from ...core.config import RADIO_RATES
from ...core.model import fmt_id, parse_int
from ..widgets import Card, SimpleTableModel, View, button, fmt_num, hbox, label, setup_table, vbox

SOURCE_TEXT = {"ecu": "ECU frame (FT550)", "can": "Another CAN frame", "gps": "GPS (read by the DAQ)",
               "daq": "Made by the DAQ", "daq_input": "Spare input on the DAQ"}
GPS_FIELDS = ["latitude", "longitude", "speed_kph", "altitude", "satellites", "fix_valid"]
DAQ_FIELDS = ["battery_voltage", "tx_count", "can_frame_count"]


def source_summary(ch: dict) -> str:
    src = ch.get("source") or {}
    t = src.get("type")
    try:
        if t == "ecu":
            return f"ECU {fmt_id(parse_int(src.get('id')), True)} value {int(src.get('slot', 0)) + 1} of 4"
        if t == "can":
            cid = parse_int(src.get("id"))
            return (f"CAN {fmt_id(cid, bool(src.get('extended', cid > 0x7FF)))} byte {src.get('byte', 0)}, "
                    f"{src.get('bits', 16)} bits, {src.get('order', 'little')}-endian")
    except (TypeError, ValueError):
        return "not set"
    if t == "gps":
        return f"GPS: {src.get('field', '')}"
    if t == "daq":
        return f"DAQ: {src.get('field', '')}"
    if t == "daq_input":
        return f"DAQ input {src.get('input', '')}"
    return "not set"


class ChannelDialog(QDialog):
    def __init__(self, parent, ch: dict, is_new: bool):
        super().__init__(parent)
        self.setWindowTitle("Add a channel" if is_new else "Edit channel")
        self.setMinimumWidth(520)
        self.ch = copy.deepcopy(ch)
        c, src = self.ch, self.ch.get("source") or {}
        self.key = QLineEdit(c.get("key", ""))
        self.key.setPlaceholderText("short_name_no_spaces")
        self.key.setToolTip("The short name used in the firmware and files. Letters, numbers, underscores.")
        self.name = QLineEdit(c.get("name", ""))
        self.name.setPlaceholderText("What people see, e.g. Steering angle")
        self.group = QComboBox()
        self.group.setEditable(True)
        self.group.addItems(["Engine", "Pressures", "Wheels", "Dynamics", "Suspension", "Fuel", "Electrics",
                             "GPS", "DAQ", "Driver"])
        self.group.setCurrentText(c.get("group", "Engine"))
        self.stype = QComboBox()
        for k, text in SOURCE_TEXT.items():
            self.stype.addItem(text, k)
        self.stype.setCurrentIndex(max(0, self.stype.findData(src.get("type", "can"))))
        self.ecu_id = QComboBox()
        for i in range(9):
            self.ecu_id.addItem(f"0x1408060{i}", f"0x1408060{i}")
        self.ecu_id.setCurrentIndex(max(0, self.ecu_id.findData(str(src.get("id", "")))))
        self.slot = QSpinBox()
        self.slot.setRange(1, 4)
        self.slot.setValue(int(src.get("slot", 0)) + 1)
        self.slot.setToolTip("Each FT550 frame holds four values. Which one is this?")
        self.can_id = QLineEdit(str(src.get("id", "0x500")) if src.get("type") == "can" else "0x500")
        self.can_ext = QCheckBox("Extended (29-bit) ID")
        self.can_ext.setChecked(bool(src.get("extended", False)))
        self.byte = QSpinBox()
        self.byte.setRange(0, 7)
        self.byte.setValue(int(src.get("byte", 0)))
        self.byte.setToolTip("Which data byte the value starts at (0 is the first)")
        self.bits = QComboBox()
        for b in (8, 16, 32):
            self.bits.addItem(f"{b} bits", b)
        self.bits.setCurrentIndex(max(0, self.bits.findData(int(src.get("bits", 16)))))
        self.order = QComboBox()
        self.order.addItem("Little-endian (low byte first)", "little")
        self.order.addItem("Big-endian (high byte first)", "big")
        self.order.setCurrentIndex(max(0, self.order.findData(src.get("order", "little"))))
        self.signed = QCheckBox("Can be negative (signed)")
        self.signed.setChecked(bool(src.get("signed", c.get("signed", False))))
        self.field = QComboBox()
        self.field.setEditable(True)
        self.input = QComboBox()
        self.input.setEditable(True)
        self.input.addItems(["A0", "A1", "A2", "A3", "F0", "F1"])
        self.input.setCurrentText(str(src.get("input", "A0")))
        self.scale = QLineEdit(str(c.get("scale", 1)))
        self.scale.setToolTip("Real value = raw number x scale. e.g. raw 650 x 0.1 = 65.0 %")
        self.units = QLineEdit(c.get("units", "") or "")
        self.vmin = QLineEdit("" if c.get("min") is None else str(c.get("min")))
        self.vmax = QLineEdit("" if c.get("max") is None else str(c.get("max")))
        for w in (self.vmin, self.vmax):
            w.setPlaceholderText("optional")
            w.setToolTip("Expected range. Values outside it are flagged amber.")
        self.radio = QComboBox()
        self.radio.addItem("Off: not sent over the radio", "off")
        self.radio.addItem("Slow: sent in rotation", "slow")
        self.radio.addItem("Fast: in every packet", "fast")
        self.radio.setCurrentIndex(max(0, self.radio.findData(c.get("radio", "off"))))
        self.screen = QCheckBox("Sent to the steering wheel screen")
        self.screen.setChecked(bool(c.get("screen", False)))
        self.note = QLineEdit(c.get("note", "") or "")
        self.form = QFormLayout()
        f = self.form
        f.addRow("Key", self.key)
        f.addRow("Name", self.name)
        f.addRow("Group", self.group)
        f.addRow("Comes from", self.stype)
        self.rows = {
            "ecu": [f.rowCount(), f.rowCount() + 1],
        }
        f.addRow("ECU frame", self.ecu_id)
        f.addRow("Value number", self.slot)
        self.rows["can"] = list(range(f.rowCount(), f.rowCount() + 5))
        f.addRow("CAN ID", hbox(self.can_id, self.can_ext))
        f.addRow("Start byte", self.byte)
        f.addRow("Size", self.bits)
        f.addRow("Byte order", self.order)
        f.addRow("", self.signed)
        self.rows["field"] = [f.rowCount()]
        f.addRow("Field", self.field)
        self.rows["daq_input"] = [f.rowCount()]
        f.addRow("Input", self.input)
        f.addRow("Scale", self.scale)
        f.addRow("Units", self.units)
        f.addRow("Expected range", hbox(self.vmin, label("to"), self.vmax))
        f.addRow("Radio", self.radio)
        f.addRow("", self.screen)
        f.addRow("Note", self.note)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        self.setLayout(vbox(self.form, box, margins=(18, 18, 18, 18)))
        self.stype.currentIndexChanged.connect(self._sync)
        self._field_value = str(src.get("field", ""))
        self._sync()

    def _sync(self):
        t = self.stype.currentData()
        for key, rows in self.rows.items():
            show = (key == t) or (key == "field" and t in ("gps", "daq"))
            for r in rows:
                self.form.setRowVisible(r, show)
        if t in ("gps", "daq"):
            self.field.clear()
            self.field.addItems(GPS_FIELDS if t == "gps" else DAQ_FIELDS)
            if self._field_value:
                self.field.setCurrentText(self._field_value)

    @staticmethod
    def _float(text: str):
        text = text.strip()
        if not text:
            return None
        v = float(text)
        return int(v) if v == int(v) and "." not in text and "e" not in text.lower() else v

    def _ok(self):
        try:
            scale = self._float(self.scale.text())
            vmin, vmax = self._float(self.vmin.text()), self._float(self.vmax.text())
            if scale is None:
                raise ValueError
        except ValueError:
            QMessageBox.information(self, "Channel", "Scale and range must be numbers.")
            return
        t = self.stype.currentData()
        if t == "ecu":
            src = {"type": "ecu", "id": self.ecu_id.currentData(), "slot": self.slot.value() - 1}
        elif t == "can":
            src = {"type": "can", "id": self.can_id.text().strip(), "extended": self.can_ext.isChecked(),
                   "byte": self.byte.value(), "bits": self.bits.currentData(),
                   "order": self.order.currentData(), "signed": self.signed.isChecked()}
        elif t in ("gps", "daq"):
            src = {"type": t, "field": self.field.currentText().strip()}
        else:
            src = {"type": "daq_input", "input": self.input.currentText().strip()}
        out = {"key": self.key.text().strip(), "name": self.name.text().strip(),
               "group": self.group.currentText().strip(), "source": src}
        if t == "ecu":
            out["signed"] = bool(self.ch.get("signed", True))
        out.update({"scale": scale, "units": self.units.text().strip()})
        if vmin is not None:
            out["min"] = vmin
        if vmax is not None:
            out["max"] = vmax
        out.update({"radio": self.radio.currentData(), "screen": self.screen.isChecked()})
        if self.note.text().strip():
            out["note"] = self.note.text().strip()
        self.ch = out
        self.accept()


class DiffDialog(QDialog):
    def __init__(self, parent, changes: list[tuple[str, str, str]], out_dir: Path):
        super().__init__(parent)
        self.setWindowTitle("Check the changes before writing")
        self.resize(900, 640)
        tabs = QTabWidget()
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        changed = 0
        for name, old, new in changes:
            view = QPlainTextEdit()
            view.setReadOnly(True)
            view.setFont(mono)
            view.setLineWrapMode(QPlainTextEdit.NoWrap)
            if old == new:
                view.setPlainText("No changes: this file is already up to date.")
                tabs.addTab(view, f"{name}  (same)")
                continue
            changed += 1
            diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), "current", "new", lineterm="", n=2))
            cur = view.textCursor()
            for line in diff if old else ["This file is new.", ""] + new.splitlines():
                fmt = QTextCharFormat()
                if old and line.startswith("+") and not line.startswith("+++"):
                    fmt.setForeground(QColor(theme.GREEN_BRIGHT))
                elif old and line.startswith("-") and not line.startswith("---"):
                    fmt.setForeground(QColor(theme.RED_BRIGHT))
                elif line.startswith("@@"):
                    fmt.setForeground(QColor(theme.AMBER))
                cur.insertText(line + "\n", fmt)
            view.moveCursor(QTextCursor.Start)
            tabs.addTab(view, f"{name}  ({'new' if not old else 'changed'})")
        self.changed = changed
        info = label(f"{changed} of {len(changes)} files will change. Green lines are added, red lines removed.\n"
                     f"Files are written to {out_dir}", "dim", wrap=True)
        box = QDialogButtonBox()
        ok = box.addButton("Write the files", QDialogButtonBox.AcceptRole)
        ok.setObjectName("primary")
        ok.setEnabled(changed > 0)
        box.addButton(QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self.setLayout(vbox(info, (tabs, 1), box, margins=(16, 16, 16, 16)))


class ChannelsView(View):
    title = "Channels"
    subtitle = ("The master list of every value on the car. Edit it here, then Generate rewrites the DBC files, "
                "the firmware header and the app's own list from it.")
    refresh_every = 20

    def __init__(self, hub):
        super().__init__(hub)
        self.cfg = hub.cfg.copy()
        self.dirty = False
        self.model = SimpleTableModel(
            ["Name", "Key", "Group", "Comes from", "Scale", "Units", "Range", "Radio", "Screen", "Note"],
            ["What people see", "Short name used in firmware and files", "", "Where the value comes from",
             "Real value = raw x scale", "", "Expected range", "Sent over the radio: off, slow or fast",
             "Sent to the steering wheel screen", "Anything to watch out for"])
        self.model.cell = self._cell
        self.model.fg = lambda ch, c: theme.AMBER if c == 9 else (theme.GREEN_BRIGHT if c == 7 and ch.get("radio") != "off" else None)
        self.model.tip = lambda ch, c: ch.get("note") or None
        self.table = QTableView()
        self.table.setModel(self.model)
        setup_table(self.table, 9, {0: 190, 1: 130, 2: 90, 3: 250, 4: 60, 5: 60, 6: 90, 7: 55, 8: 60})
        self.table.doubleClicked.connect(lambda *_: self._edit())
        self.problems = QListWidget()
        self.problems.setMaximumHeight(110)
        self.status = label("", "dim")
        self.path_label = label("", "dim")
        self.btn_save = button("Save", self._save, tip="Save the master config file")
        self.btn_gen = button("Generate files...", self._generate, "primary",
                              "Write the team DBC, screen DBC, firmware header and signal list. Shows a diff first.")
        self.root.addLayout(hbox(button("Add a channel", self._add, "primary"), button("Edit", self._edit),
                                 button("Delete", self._delete), None, self.status, self.btn_save,
                                 button("Undo all changes", self._revert), self.btn_gen))
        self.root.addWidget(self.table, 1)
        pc = Card("Checks", "Problems that would break the generated files")
        pc.add(self.problems)
        self.root.addWidget(pc)
        self.root.addWidget(self.path_label)
        self._fill()

    def _cell(self, ch, col):
        if col == 0:
            return ch.get("name", "")
        if col == 1:
            return ch.get("key", "")
        if col == 2:
            return ch.get("group", "")
        if col == 3:
            return source_summary(ch)
        if col == 4:
            return f"{ch.get('scale', 1):g}" if isinstance(ch.get("scale", 1), (int, float)) else str(ch.get("scale"))
        if col == 5:
            return ch.get("units", "")
        if col == 6:
            lo, hi = ch.get("min"), ch.get("max")
            return "" if lo is None and hi is None else f"{'' if lo is None else lo} to {'' if hi is None else hi}"
        if col == 7:
            return ch.get("radio", "off")
        if col == 8:
            return "yes" if ch.get("screen") else ""
        return ch.get("note", "")

    def _fill(self):
        self.cfg.compile()
        self.model.beginResetModel()
        self.model.rows = self.cfg.channels
        self.model.endResetModel()
        probs = self.cfg.validate()
        self.problems.clear()
        if probs:
            for p in probs:
                self.problems.addItem("✘  " + p)
                self.problems.item(self.problems.count() - 1).setForeground(QColor(theme.RED_BRIGHT))
        else:
            self.problems.addItem("✔  No problems. Nothing overlaps and nothing is missing.")
            self.problems.item(0).setForeground(QColor(theme.GREEN_BRIGHT))
        self.valid = not probs
        n_radio = sum(1 for c in self.cfg.channels if c.get("radio") != "off")
        self.status.setText(f"{len(self.cfg.channels)} channels, {n_radio} on the radio, radio packet "
                            f"{self.cfg.radio_size} bytes" + ("   (unsaved changes)" if self.dirty else ""))
        self.btn_save.setEnabled(self.dirty)
        self.path_label.setText(f"Master config: {self.hub.config_path}")

    def _row(self) -> int:
        idx = self.table.selectionModel().selectedRows()
        return idx[0].row() if idx else -1

    def _add(self):
        dlg = ChannelDialog(self, {"source": {"type": "can", "id": "0x500"}, "scale": 1, "radio": "off"}, True)
        if dlg.exec() == QDialog.Accepted:
            self.cfg.channels.append(dlg.ch)
            self.dirty = True
            self._fill()
            self.table.selectRow(len(self.cfg.channels) - 1)
            self.table.scrollToBottom()

    def _edit(self):
        row = self._row()
        if row < 0:
            self.hub.notice.emit("info", "Click a channel first, then Edit.")
            return
        old_key = self.cfg.channels[row].get("key")
        dlg = ChannelDialog(self, self.cfg.channels[row], False)
        if dlg.exec() == QDialog.Accepted:
            self.cfg.channels[row] = dlg.ch
            new_key = dlg.ch.get("key")
            if new_key != old_key:
                for fr in self.cfg.data.get("screen_frames", []) or []:
                    for sg in fr.get("signals", []) or []:
                        if sg.get("channel") == old_key:
                            sg["channel"] = new_key
                for f in (self.cfg.data.get("radio_packet") or {}).get("fields", []) or []:
                    if f.get("channel") == old_key:
                        f["channel"] = new_key
            self.dirty = True
            self._fill()
            self.table.selectRow(row)

    def _delete(self):
        row = self._row()
        if row < 0:
            self.hub.notice.emit("info", "Click a channel first, then Delete.")
            return
        ch = self.cfg.channels[row]
        if QMessageBox.question(self, "Delete channel", f"Delete '{ch.get('name', ch.get('key'))}'?") == QMessageBox.Yes:
            del self.cfg.channels[row]
            self.dirty = True
            self._fill()

    def _revert(self):
        self.cfg = self.hub.cfg.copy()
        self.dirty = False
        self._fill()

    def _save(self) -> bool:
        if not self.valid:
            ok = QMessageBox.question(self, "Save with problems?",
                                      "The checks found problems. Save anyway? (Generate stays blocked until "
                                      "they're fixed.)")
            if ok != QMessageBox.Yes:
                return False
        if self.hub.connected:
            ok = QMessageBox.question(self, "Save", "Saving reloads the config, so live values start again "
                                                    "from empty. Carry on?")
            if ok != QMessageBox.Yes:
                return False
        try:
            self.cfg.save(self.hub.config_path)
        except OSError as exc:
            self.hub.notice.emit("error", f"Couldn't save the config: {exc}")
            return False
        self.dirty = False
        self.hub.reload_config()
        self.cfg = self.hub.cfg.copy()
        self._fill()
        self.hub.notice.emit("info", "Config saved.")
        return True

    def out_dir(self) -> Path:
        return Path(self.hub.config_path).parent / "generated"

    def _generate(self):
        if not self.valid:
            QMessageBox.information(self, "Generate", "Fix the problems listed under Checks first.")
            return
        if self.dirty and not self._save():
            return
        files = self.cfg.generate()
        out = self.out_dir()
        changes = []
        for name, new in files.items():
            p = out / name
            old = p.read_text(encoding="utf-8") if p.exists() else ""
            changes.append((name, old, new))
        dlg = DiffDialog(self, changes, out)
        if dlg.exec() == QDialog.Accepted:
            out.mkdir(parents=True, exist_ok=True)
            for name, _, new in changes:
                (out / name).write_text(new, encoding="utf-8")
            self.hub.notice.emit(
                "info", f"Wrote {len(changes)} files to {out}. Copy gryphon_channels.h into the firmware and "
                        "load gryphon_screen.dbc into the Winstar builder if the screen frames changed.")

    def on_config(self):
        if not self.dirty:
            self.cfg = self.hub.cfg.copy()
            self._fill()
