from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QInputDialog, QLineEdit, QMenu,
                               QMessageBox, QPlainTextEdit, QStackedWidget, QTableView)

from ... import theme
from ...core.model import fmt_id, parse_int
from ..widgets import (Card, EmptyState, SimpleTableModel, Switcher, View, button, hbox, label, setup_table,
                       vbox)

DEVICE_NAMES = {"ecu": "ECU", "daq": "DAQ", "pdm": "PDM", "lambda": "Lambda", "screen": "Screen"}


class RawView(View):
    title = "Raw frames"
    subtitle = "Every CAN frame on the bus. Unknown IDs are highlighted so you can work out what sends them."
    refresh_every = 2

    def __init__(self, hub):
        super().__init__(hub)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by ID or device (e.g. 600, ecu, unknown)")
        self.filter.setClearButtonEnabled(True)
        self.filter.setMinimumWidth(340)
        self.filter.setMaximumWidth(400)
        self.mode = QComboBox()
        self.mode.addItem("Fixed: one row per ID", "fixed")
        self.mode.addItem("Scrolling: every frame as it arrives", "scroll")
        self.mode.setToolTip("Fixed is best for watching values. Scrolling shows the order frames arrive in.")
        self.pause = QCheckBox("Pause")
        self.count = label("", "dim")
        heads = ["ID", "Type", "Len"] + [f"B{i}" for i in range(8)] + ["Count", "Period ms", "Rate", "Device", "Decodes to"]
        self.model = SimpleTableModel(heads, ["CAN identifier", "Standard (11-bit) or extended (29-bit)",
                                              "Number of data bytes"] + ["Data byte (hex)"] * 8 +
                                      ["Frames seen", "Time since the previous one", "Frames a second",
                                       "Who sends it", "What the app decodes from it"])
        self.model.cell = self._cell
        self.model.fg = self._fg
        self.model.bg = self._bg
        self.table = QTableView()
        self.table.setModel(self.model)
        widths = {0: 110, 1: 50, 2: 40, 11: 80, 12: 80, 13: 70, 14: 140}
        widths.update({i: 34 for i in range(3, 11)})
        setup_table(self.table, 15, widths)
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        mono.setPointSize(10)
        self.table.setFont(mono)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.scroll = QPlainTextEdit()
        self.scroll.setReadOnly(True)
        self.scroll.setMaximumBlockCount(1500)
        self.scroll.setFont(mono)
        self.scroll.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.table)
        self.pages.addWidget(self.scroll)
        self.empty = EmptyState("No frames yet", "Connect with the CAN cable (or the simulator) and every frame on "
                                "the bus will show here.\nNothing at all on the real car? Check the ignition is on, "
                                "then see Help > Troubleshooting.", "Try it in the simulator",
                                lambda: self.window_ref.connect_simulator())
        self.switch = Switcher(self.empty, self.pages)

        self.adv = Card("Advanced: send a frame (bench testing only)")
        self.adv_note = label("", "dim", wrap=True)
        self.tx_id = QLineEdit("0x123")
        self.tx_id.setMaximumWidth(120)
        self.tx_data = QLineEdit("00 00 00 00 00 00 00 00")
        self.tx_data.setMaximumWidth(260)
        self.tx_ext = QCheckBox("Extended ID")
        self.tx_btn = button("Send once", self._send, "danger")
        self.adv.add(self.adv_note)
        self.adv.add(hbox(label("ID"), self.tx_id, label("Data (hex)"), self.tx_data, self.tx_ext, self.tx_btn, None))
        self.adv_toggle = button("Show advanced tools", self._toggle_adv, "link")
        self.adv.hide()

        self.root.addLayout(hbox(self.filter, self.mode, self.pause, None, self.count,
                                 button("Clear", self._clear, tip="Forget the counts and start again")))
        self.root.addWidget(self.switch, 1)
        self.root.addLayout(hbox(self.adv_toggle, None))
        self.root.addWidget(self.adv)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._serial = 0

    def _mode_changed(self):
        scroll = self.mode.currentData() == "scroll"
        self.pages.setCurrentIndex(1 if scroll else 0)
        self.hub.trace_enabled = scroll
        self._serial = self.hub.trace_serial
        self.scroll.clear()

    def on_show(self):
        self.hub.trace_enabled = self.mode.currentData() == "scroll"
        self._serial = self.hub.trace_serial

    def _toggle_adv(self):
        self.adv.setVisible(not self.adv.isVisible())
        self.adv_toggle.setText("Hide advanced tools" if self.adv.isVisible() else "Show advanced tools")
        self.on_state()

    def on_state(self):
        hub = self.hub
        can_tx = (hub.state == "connected" and hub.kind == "can"
                  and not getattr(hub.source, "listen_only", True))
        self.tx_btn.setEnabled(can_tx)
        if can_tx:
            self.adv_note.setText("Transmit is allowed. Only use this on a bench, never with the car running.")
        elif hub.settings["allow_transmit"]:
            self.adv_note.setText("Connect with the CAN cable to send. (Reconnect if you just changed the setting.)")
        else:
            self.adv_note.setText("Sending is off. The app is listen-only on the car's bus. To send a frame for "
                                  "bench testing, switch on 'Allow transmit' in Settings, then reconnect.")

    def _send(self):
        try:
            cid = parse_int(self.tx_id.text())
            data = bytes.fromhex(self.tx_data.text().replace(" ", ""))
            if len(data) > 8:
                raise ValueError("more than 8 bytes")
        except ValueError as exc:
            self.hub.notice.emit("warn", f"That frame isn't valid: {exc}")
            return
        ext = self.tx_ext.isChecked() or cid > 0x7FF
        ok = QMessageBox.question(
            self, "Send a frame onto the bus?",
            f"This puts {fmt_id(cid, ext)} [{data.hex(' ').upper()}] on the CAN bus.\n\n"
            "Only do this on a bench. Never with the car running.\n\nSend it?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ok == QMessageBox.Yes and self.hub.source is not None:
            if self.hub.source.send(cid, ext, data):
                self.hub.notice.emit("info", f"Sent {fmt_id(cid, ext)}.")

    def _clear(self):
        self.hub.engine.frames.clear()
        self.scroll.clear()

    def _device(self, fs) -> str:
        if fs.device:
            return DEVICE_NAMES.get(fs.device, fs.device)
        name = (self.hub.settings.get("id_labels") or {}).get(fmt_id(fs.id, fs.ext))
        if name:
            return name
        return "" if fs.hint else "Unknown device"

    def _cell(self, fs, col):
        if col == 0:
            return fmt_id(fs.id, fs.ext)
        if col == 1:
            return "Ext" if fs.ext else "Std"
        if col == 2:
            return str(len(fs.data))
        if 3 <= col <= 10:
            i = col - 3
            return f"{fs.data[i]:02X}" if i < len(fs.data) else ""
        if col == 11:
            return str(fs.count)
        if col == 12:
            return f"{fs.period_ms:.1f}"
        if col == 13:
            return f"{fs.rate:.1f}"
        if col == 14:
            return self._device(fs)
        return fs.hint

    def _unknown(self, fs) -> bool:
        return not fs.device and not fs.hint and \
            fmt_id(fs.id, fs.ext) not in (self.hub.settings.get("id_labels") or {})

    def _fg(self, fs, col):
        if self.hub.engine.now - fs.last_ts > 3.0:
            return theme.GREY
        if self._unknown(fs) and col in (0, 14):
            return theme.AMBER
        if 3 <= col <= 10 and self.hub.engine.now - fs.change_ts[col - 3] < 1.0:
            return theme.TEXT
        if 3 <= col <= 10:
            return theme.TEXT_DIM
        return None

    def _bg(self, fs, col):
        if 3 <= col <= 10 and self.hub.engine.now - fs.change_ts[col - 3] < 1.0:
            return theme.GREEN
        return None

    def _menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        fs = self.model.rows[idx.row()]
        fid = fmt_id(fs.id, fs.ext)
        m = QMenu(self)
        m.addAction("Copy this row", lambda: QApplication.clipboard().setText(
            f"{fid} [{len(fs.data)}] {fs.data.hex(' ').upper()}"))
        if not fs.device:
            m.addSeparator()
            for key in ("pdm", "lambda", "screen"):
                m.addAction(f"This ID comes from the {DEVICE_NAMES[key]}", lambda k=key: self._assign(fs, k))
            m.addAction("Give this ID a name...", lambda: self._name(fs))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _assign(self, fs, key):
        s = self.hub.settings
        cur = [p.strip() for p in str(s.get(f"{key}_ids") or "").split(",") if p.strip()]
        fid = fmt_id(fs.id, fs.ext)
        if fid not in cur:
            cur.append(fid)
        s[f"{key}_ids"] = ", ".join(cur)
        self.hub.settings_changed()
        self.hub.notice.emit("info", f"{fid} is now counted as the {DEVICE_NAMES[key]}. Change it in Settings.")

    def _name(self, fs):
        fid = fmt_id(fs.id, fs.ext)
        text, ok = QInputDialog.getText(self, "Name this ID", f"What sends {fid}?")
        if ok and text.strip():
            labels = dict(self.hub.settings.get("id_labels") or {})
            labels[fid] = text.strip()
            self.hub.settings["id_labels"] = labels
            self.hub.settings.save()

    def refresh(self) -> None:
        hub, e = self.hub, self.hub.engine
        self.switch.show_content(bool(e.frames))
        if self.pause.isChecked():
            return
        text = self.filter.text().strip().lower()
        if self.mode.currentData() == "scroll":
            new = hub.trace_serial - self._serial
            self._serial = hub.trace_serial
            if new > 0:
                frames = list(hub.trace)[-min(new, 400):]
                t0 = e.first_ts
                lines = []
                for f in frames:
                    fid = fmt_id(f.id, f.ext)
                    if text and text not in fid.lower():
                        continue
                    lines.append(f"{f.ts - t0:10.3f}  {fid:>10}  [{len(f.data)}]  {f.data.hex(' ').upper()}")
                if lines:
                    self.scroll.appendPlainText("\n".join(lines))
            self.count.setText(f"{e.frame_rate:.0f} frames a second")
            return
        rows = []
        for key in sorted(e.frames):
            fs = e.frames[key]
            if text:
                hay = f"{fmt_id(fs.id, fs.ext)} {self._device(fs)} {fs.hint}".lower()
                if text not in hay:
                    continue
            rows.append(fs)
        self.model.set_rows(rows)
        unknown = sum(1 for fs in e.frames.values() if self._unknown(fs))
        self.count.setText(f"{len(e.frames)} IDs, {unknown} unknown   {e.frame_rate:.0f} frames a second")
