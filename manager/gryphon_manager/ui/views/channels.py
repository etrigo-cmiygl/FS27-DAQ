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


def _safe_int(value):
    try:
        return parse_int(value)
    except (TypeError, ValueError):
        return None


def _channel_combo(cfg, current: str) -> QComboBox:
    c = QComboBox()
    for ch in cfg.channels:
        c.addItem(f"{ch.get('name', ch.get('key'))}  ({ch.get('key')})", ch.get("key"))
    i = c.findData(current)
    if i >= 0:
        c.setCurrentIndex(i)
    return c


class ScreenSignalDialog(QDialog):
    def __init__(self, parent, cfg, frame: dict | None, sg: dict | None):
        super().__init__(parent)
        self.setWindowTitle("Screen frame signal")
        self.setMinimumWidth(480)
        self.orig = dict(sg or {})
        s = self.orig
        frames = cfg.data.get("screen_frames", []) or []
        self.names = {str(f.get("id")): f.get("name", "") for f in frames}
        self.frame = QComboBox()
        self.frame.setEditable(True)
        self.frame.addItems(list(self.names))
        self.frame.setToolTip("Pick a frame, or type a new ID (e.g. 0x604) to start a new one. "
                              "Check new IDs don't clash with the PDM.")
        if frame:
            self.frame.setCurrentText(str(frame.get("id")))
        self.frame_name = QLineEdit(frame.get("name", "") if frame else self.names.get(self.frame.currentText(), ""))
        self.frame.currentTextChanged.connect(lambda t: self.frame_name.setText(self.names.get(t, self.frame_name.text())))
        self.channel = _channel_combo(cfg, s.get("channel", ""))
        self.name = QLineEdit(s.get("name", ""))
        self.name.setPlaceholderText("Name in the screen project, e.g. Oil_Pressure")
        self.byte = QSpinBox()
        self.byte.setRange(0, 7)
        self.byte.setValue(int(s.get("byte", 0)))
        self.bits = QComboBox()
        for b in (8, 16, 32):
            self.bits.addItem(f"{b} bits", b)
        self.bits.setCurrentIndex(max(0, self.bits.findData(int(s.get("bits", 16)))))
        self.signed = QCheckBox("Can be negative (signed)")
        self.signed.setChecked(bool(s.get("signed", False)))
        self.scale = QLineEdit(str(s.get("scale", 0.1)))
        self.scale.setToolTip("The screen shows raw x scale. 0.1 means the DAQ sends the value x10.")
        self.units = QLineEdit(s.get("units", "") or "")
        self.vmin = QLineEdit("" if s.get("min") is None else str(s.get("min")))
        self.vmax = QLineEdit("" if s.get("max") is None else str(s.get("max")))
        f = QFormLayout()
        f.addRow("Frame ID", self.frame)
        f.addRow("Frame name", self.frame_name)
        f.addRow("Channel", self.channel)
        f.addRow("Signal name", self.name)
        f.addRow("Start byte", self.byte)
        f.addRow("Size", self.bits)
        f.addRow("", self.signed)
        f.addRow("Scale", self.scale)
        f.addRow("Units", self.units)
        f.addRow("Range", hbox(self.vmin, label("to"), self.vmax))
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        self.setLayout(vbox(f, box, margins=(18, 18, 18, 18)))

    def _ok(self):
        fid = self.frame.currentText().strip()
        cid = _safe_int(fid)
        try:
            scale = float(self.scale.text())
            vmin = float(self.vmin.text()) if self.vmin.text().strip() else None
            vmax = float(self.vmax.text()) if self.vmax.text().strip() else None
        except ValueError:
            QMessageBox.information(self, "Screen signal", "Scale and range must be numbers.")
            return
        if cid is None or not 0 <= cid <= 0x7FF or scale == 0 or not self.name.text().strip():
            QMessageBox.information(self, "Screen signal", "It needs a frame ID from 0x000 to 0x7FF, a signal "
                                                           "name, and a scale that isn't 0.")
            return
        sg = dict(self.orig)
        sg.update({"channel": self.channel.currentData(), "name": self.name.text().strip().replace(" ", "_"),
                   "byte": self.byte.value(), "bits": self.bits.currentData(), "signed": self.signed.isChecked(),
                   "scale": int(scale) if scale == int(scale) else scale, "units": self.units.text().strip()})
        for k, v in (("min", vmin), ("max", vmax)):
            if v is None:
                sg.pop(k, None)
            else:
                sg[k] = int(v) if v == int(v) else v
        self.fid = fid if fid.lower().startswith("0x") else f"0x{cid:03X}"
        self.fname = self.frame_name.text().strip().replace(" ", "_")
        self.sg = sg
        self.accept()


class PacketFieldDialog(QDialog):
    def __init__(self, parent, cfg, field: dict | None):
        super().__init__(parent)
        self.setWindowTitle("Radio packet field")
        self.setMinimumWidth(440)
        fld = field or {}
        self.channel = _channel_combo(cfg, fld.get("channel", ""))
        self.name = QLineEdit(fld.get("name", ""))
        self.name.setPlaceholderText("Name in the firmware struct (blank = the channel key)")
        self.ftype = QComboBox()
        for t, text in (("f32", "f32: decimal number, 4 bytes"), ("u16", "u16: 0 to 65535, 2 bytes"),
                        ("i16", "i16: -32768 to 32767, 2 bytes"), ("u8", "u8: 0 to 255, 1 byte"),
                        ("i8", "i8: -128 to 127, 1 byte"), ("u32", "u32: big whole number, 4 bytes"),
                        ("i32", "i32: big signed number, 4 bytes")):
            self.ftype.addItem(text, t)
        self.ftype.setCurrentIndex(max(0, self.ftype.findData(fld.get("type", "f32"))))
        f = QFormLayout()
        f.addRow("Channel", self.channel)
        f.addRow("Field name", self.name)
        f.addRow("Type", self.ftype)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        self.setLayout(vbox(f, box, margins=(18, 18, 18, 18)))

    def _ok(self):
        key = self.channel.currentData()
        name = self.name.text().strip().replace(" ", "_") or key
        if not name.replace("_", "").isalnum() or name[0].isdigit():
            QMessageBox.information(self, "Radio packet field", "The field name can only use letters, numbers "
                                                                "and underscores, and can't start with a number.")
            return
        self.field = {"name": name, "channel": key, "type": self.ftype.currentData()}
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
        self.root.addLayout(hbox(self.status, None, self.btn_save,
                                 button("Undo all changes", self._revert), self.btn_gen))
        from PySide6.QtWidgets import QWidget
        self.tabs = QTabWidget()
        t1 = QWidget()
        t1.setLayout(vbox(hbox(button("Add a channel", self._add, "primary"), button("Edit", self._edit),
                               button("Delete", self._delete), None), (self.table, 1), margins=(10, 10, 10, 10)))
        self.tabs.addTab(t1, "Channels")

        self.sf_model = SimpleTableModel(
            ["Frame", "Frame name", "Signal", "Channel", "Start byte", "Size", "Signed", "Scale", "Units"],
            ["CAN ID the DAQ sends", "", "Name the screen project uses", "Which channel's value goes here",
             "First data byte (0-7)", "", "", "Screen value = raw x scale", ""])
        self.sf_model.cell = self._sf_cell
        self.sf_table = QTableView()
        self.sf_table.setModel(self.sf_model)
        setup_table(self.sf_table, 3, {0: 80, 1: 170, 2: 170, 4: 90, 5: 80, 6: 70, 7: 90, 8: 80})
        self.sf_table.doubleClicked.connect(lambda *_: self._sf_edit())
        t2 = QWidget()
        t2.setLayout(vbox(
            label("What the DAQ sends to the steering wheel screen. Little-endian, up to 8 bytes a frame. "
                  "The screen project must be loaded with the generated gryphon_screen.dbc after any change here.",
                  "dim", wrap=True),
            hbox(button("Add a signal", self._sf_add, "primary"), button("Edit", self._sf_edit),
                 button("Delete", self._sf_delete), None,
                 label("To start a new frame, add a signal and type a new frame ID.", "dim")),
            (self.sf_table, 1), margins=(10, 10, 10, 10)))
        self.tabs.addTab(t2, "Screen frames")

        self.rp_model = SimpleTableModel(["#", "Offset", "Field", "Channel", "Type", "Bytes"],
                                         ["Order in the packet", "Byte position in the packet",
                                          "Name in the firmware struct", "Which channel's value goes here",
                                          "u8/u16/u32 whole numbers, i = signed, f32 = decimal", ""])
        self.rp_model.cell = lambda r, c: r[c]
        self.rp_table = QTableView()
        self.rp_table.setModel(self.rp_model)
        setup_table(self.rp_table, 3, {0: 50, 1: 70, 2: 200, 4: 80, 5: 70})
        self.rp_table.doubleClicked.connect(lambda *_: self._rp_edit())
        self.rp_info = label("", "dim", wrap=True)
        t3 = QWidget()
        t3.setLayout(vbox(
            self.rp_info,
            hbox(button("Add a field", self._rp_add, "primary"), button("Edit", self._rp_edit),
                 button("Remove", self._rp_delete), button("Move up", lambda: self._rp_move(-1)),
                 button("Move down", lambda: self._rp_move(1)), None),
            (self.rp_table, 1), margins=(10, 10, 10, 10)))
        self.tabs.addTab(t3, "Radio packet")
        self.root.addWidget(self.tabs, 1)
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
        self.sf_rows = [(fr, sg) for fr in self.cfg.data.get("screen_frames", []) or []
                        for sg in fr.get("signals", []) or []]
        self.sf_model.beginResetModel()
        self.sf_model.rows = self.sf_rows
        self.sf_model.endResetModel()
        from ...core.config import FIELD_TYPES
        import struct as _struct
        rows, off = [("", 0, "magic", "(fixed marker)", "u32", 4)], 4
        for i, f in enumerate(self._rp_fields()):
            size = _struct.calcsize("<" + FIELD_TYPES.get(f.get("type"), "B"))
            rows.append((i + 1, off, f.get("name", ""), self._ch_name(f.get("channel", "")), f.get("type", ""), size))
            off += size
        self.rp_model.beginResetModel()
        self.rp_model.rows = rows
        self.rp_model.endResetModel()
        self.rp_info.setText(
            f"The LoRa packet, in order: {off} bytes now (the firmware and receiver today expect 68). Changing "
            "this changes the generated struct, so the DAQ and receiver firmware must be rebuilt to match, "
            "and layout_version should go up.")
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

    # ---- screen frames and radio packet ----------------------------------------

    def _ch_name(self, key: str) -> str:
        ch = self.cfg.channel(key)
        return f"{ch.get('name', key)}  ({key})" if ch else f"{key}  (missing!)"

    def _rp_fields(self) -> list:
        return self.cfg.data.setdefault("radio_packet", {}).setdefault("fields", [])

    def _sf_cell(self, row, col):
        fr, sg = row
        if col == 0:
            return str(fr.get("id", ""))
        if col == 1:
            return fr.get("name", "")
        if col == 2:
            return sg.get("name", "")
        if col == 3:
            return self._ch_name(sg.get("channel", ""))
        if col == 4:
            return str(sg.get("byte", ""))
        if col == 5:
            return f"{sg.get('bits', '')} bits"
        if col == 6:
            return "yes" if sg.get("signed") else ""
        if col == 7:
            return f"{sg.get('scale', 1):g}"
        return sg.get("units", "")

    def _sel(self, table) -> int:
        idx = table.selectionModel().selectedRows()
        return idx[0].row() if idx else -1

    def _changed(self):
        self.dirty = True
        self._fill()

    def _sf_place(self, fid: str, fname: str, sg: dict) -> None:
        frames = self.cfg.data.setdefault("screen_frames", [])
        try:
            want = parse_int(fid)
        except ValueError:
            want = None
        fr = next((f for f in frames if want is not None and _safe_int(f.get("id")) == want), None)
        if fr is None:
            fr = {"id": fid, "name": fname or "GRYPHON_NEW", "signals": []}
            frames.append(fr)
        elif fname:
            fr["name"] = fname
        fr.setdefault("signals", []).append(sg)
        fr["signals"].sort(key=lambda x: x.get("byte", 0))

    def _sf_add(self):
        dlg = ScreenSignalDialog(self, self.cfg, None, None)
        if dlg.exec() == QDialog.Accepted:
            self._sf_place(dlg.fid, dlg.fname, dlg.sg)
            self._changed()

    def _sf_edit(self):
        row = self._sel(self.sf_table)
        if row < 0:
            self.hub.notice.emit("info", "Click a signal first, then Edit.")
            return
        fr, sg = self.sf_rows[row]
        dlg = ScreenSignalDialog(self, self.cfg, fr, sg)
        if dlg.exec() == QDialog.Accepted:
            fr["signals"].remove(sg)
            if not fr["signals"]:
                self.cfg.data["screen_frames"].remove(fr)
            self._sf_place(dlg.fid, dlg.fname, dlg.sg)
            self._changed()

    def _sf_delete(self):
        row = self._sel(self.sf_table)
        if row < 0:
            self.hub.notice.emit("info", "Click a signal first, then Delete.")
            return
        fr, sg = self.sf_rows[row]
        if QMessageBox.question(self, "Delete signal", f"Take '{sg.get('name')}' out of frame {fr.get('id')}?") \
                == QMessageBox.Yes:
            fr["signals"].remove(sg)
            if not fr["signals"]:
                self.cfg.data["screen_frames"].remove(fr)
            self._changed()

    def _rp_add(self):
        dlg = PacketFieldDialog(self, self.cfg, None)
        if dlg.exec() == QDialog.Accepted:
            self._rp_fields().append(dlg.field)
            self._changed()
            self.rp_table.selectRow(len(self._rp_fields()))

    def _rp_index(self) -> int:
        row = self._sel(self.rp_table)
        if row < 1:
            self.hub.notice.emit("info", "Click a field first (the magic marker at the top can't be changed).")
            return -1
        return row - 1

    def _rp_edit(self):
        i = self._rp_index()
        if i < 0:
            return
        dlg = PacketFieldDialog(self, self.cfg, self._rp_fields()[i])
        if dlg.exec() == QDialog.Accepted:
            self._rp_fields()[i] = dlg.field
            self._changed()
            self.rp_table.selectRow(i + 1)

    def _rp_delete(self):
        i = self._rp_index()
        if i < 0:
            return
        name = self._rp_fields()[i].get("name", "")
        if QMessageBox.question(self, "Remove field", f"Take '{name}' out of the radio packet?") == QMessageBox.Yes:
            del self._rp_fields()[i]
            self._changed()

    def _rp_move(self, step: int):
        i = self._rp_index()
        fields = self._rp_fields()
        j = i + step
        if i < 0 or not 0 <= j < len(fields):
            return
        fields[i], fields[j] = fields[j], fields[i]
        self._changed()
        self.rp_table.selectRow(j + 1)

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
