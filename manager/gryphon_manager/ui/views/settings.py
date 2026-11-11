from __future__ import annotations

import threading

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QLineEdit, QListWidget, QMessageBox, QScrollArea, QWidget)

from ... import REPO, __version__, theme
from ...core import firmware as fw
from ...core.model import parse_id_list
from ...core.paths import user_home
from ..widgets import View, button, hbox, label, vbox


class SettingsView(View):
    title = "Settings"
    subtitle = "Changes are saved straight away."
    refresh_every = 1000
    update_result = Signal(object)

    def __init__(self, hub):
        super().__init__(hub)
        s = hub.settings
        self._loading = True

        safety = QGroupBox("Safety")
        self.allow_tx = QCheckBox("Allow transmit (lets the app send CAN frames, for bench testing only)")
        self.allow_tx.setToolTip("Off by default. With this off the adapter is opened listen-only,\n"
                                 "so the app physically can't put anything on the car's bus.")
        self.allow_tx.setChecked(bool(s["allow_transmit"]))
        self.allow_tx.clicked.connect(self._tx_clicked)
        safety.setLayout(vbox(self.allow_tx, label(
            "Leave this off on the car. It only matters for the 'send a frame' tool under Raw frames > Advanced.",
            "dim", wrap=True)))

        adapter = QGroupBox("CAN adapter")
        self.pcan_channel = QComboBox()
        for i in range(1, 5):
            self.pcan_channel.addItem(f"PCAN_USBBUS{i}" + ("  (the usual one)" if i == 1 else ""), f"PCAN_USBBUS{i}")
        self.pcan_channel.setCurrentIndex(max(0, self.pcan_channel.findData(s["can_channel"])))
        self.pcan_channel.setToolTip("Only change this if more than one PEAK adapter is plugged in")
        self.baud = QComboBox()
        for b in (115200, 230400, 460800, 921600):
            self.baud.addItem(str(b), b)
        self.baud.setCurrentIndex(max(0, self.baud.findData(int(s["serial_baud"]))))
        self.baud.setToolTip("Serial speed of the receiver and the DAQ's USB port. Both use 115200.")
        af = QFormLayout()
        af.addRow("PEAK channel", self.pcan_channel)
        af.addRow("Receiver / DAQ serial speed", self.baud)
        adapter.setLayout(af)

        devices = QGroupBox("Device CAN IDs")
        self.ids = {}
        df = QFormLayout()
        hints = {"pdm": "e.g. 0x500-0x503", "lambda": "e.g. 0x460", "screen": "leave empty: the screen only listens"}
        for key, text in (("pdm", "PDM"), ("lambda", "Lambda unit"), ("screen", "Steering wheel screen")):
            ed = QLineEdit(str(s.get(f"{key}_ids") or ""))
            ed.setPlaceholderText(hints[key])
            ed.setToolTip("One or more IDs, separated by commas. Ranges like 0x500-0x503 work.\n"
                          "Not sure? In Raw frames, right-click an unknown ID and assign it.")
            ed.editingFinished.connect(self._save)
            self.ids[key] = ed
            df.addRow(text, ed)
        self.ecu_hz = QDoubleSpinBox()
        self.ecu_hz.setRange(1, 200)
        self.ecu_hz.setDecimals(0)
        self.ecu_hz.setSuffix(" Hz")
        self.ecu_hz.setValue(float(s["ecu_expected_hz"]))
        self.ecu_hz.setToolTip("How often the ECU should send each frame. Below half of this, the ECU light goes amber.")
        df.addRow("Expected ECU broadcast rate", self.ecu_hz)
        devices.setLayout(df)

        rec = QGroupBox("Recording")
        self.auto_rec = QCheckBox("Start recording automatically when I connect")
        self.auto_rec.setChecked(bool(s["auto_record"]))
        self.fmt = QComboBox()
        self.fmt.addItem("BLF (small, opens in SavvyCAN and Vector tools)", "blf")
        self.fmt.addItem("ASC (plain text, opens anywhere)", "asc")
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(s["log_format"])))
        self.driver = QLineEdit(s["driver"])
        self.driver.setPlaceholderText("Saved with each recording")
        rf = QFormLayout()
        rf.addRow(self.auto_rec)
        rf.addRow("CAN log format", self.fmt)
        rf.addRow("Driver / tester name", self.driver)
        rf.addRow(hbox(button("Open the recordings folder",
                              lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(user_home())))), None))
        rec.setLayout(rf)

        look = QGroupBox("Display")
        self.pressure = QComboBox()
        self.pressure.addItem("bar", "bar")
        self.pressure.addItem("psi", "psi")
        self.pressure.setCurrentIndex(max(0, self.pressure.findData(s["pressure_units"])))
        self.pit = QCheckBox("Pit wall mode: bigger numbers, no sidebar (F10)")
        self.pit.setChecked(bool(s["pit_wall"]))
        self.sound = QCheckBox("Play a sound when an alarm goes off")
        self.sound.setChecked(bool(s["alarm_sound"]))
        lf = QFormLayout()
        lf.addRow("Pressure units", self.pressure)
        lf.addRow("Temperatures", label("°C", "dim"))
        lf.addRow(self.pit)
        lf.addRow(self.sound)
        look.setLayout(lf)

        dbc = QGroupBox("Extra DBC files")
        self.dbc_list = QListWidget()
        self.dbc_list.setMaximumHeight(80)
        for p in s.get("extra_dbcs") or []:
            self.dbc_list.addItem(p)
        dbc.setLayout(vbox(label("Got a DBC for the PDM or lambda unit? Add it and its signals show up in "
                                 "Signals and Graphs.", "dim", wrap=True), self.dbc_list,
                           hbox(button("Add a DBC file...", self._add_dbc), button("Remove", self._remove_dbc), None)))

        upd = QGroupBox("Updates")
        self.check_upd = QCheckBox("Check GitHub for a newer version when the app starts")
        self.check_upd.setChecked(bool(s["check_updates"]))
        self.upd_text = label(f"You have version {__version__}.", "dim", wrap=True)
        upd.setLayout(vbox(self.check_upd, hbox(button("Check now", self.check_now), self.upd_text, None)))

        for w in (self.auto_rec, self.pit, self.sound, self.check_upd):
            w.clicked.connect(self._save)
        for w in (self.pcan_channel, self.baud, self.fmt, self.pressure):
            w.currentIndexChanged.connect(self._save)
        self.driver.editingFinished.connect(self._save)
        self.ecu_hz.editingFinished.connect(self._save)
        self.update_result.connect(self._on_update)

        left = vbox(safety, adapter, devices, None, spacing=12)
        right = vbox(rec, look, dbc, upd, None, spacing=12)
        inner = QWidget()
        inner.setLayout(hbox(left, right, spacing=18))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        self.root.addWidget(scroll, 1)
        self._loading = False

    def _tx_clicked(self):
        if self.allow_tx.isChecked():
            ok = QMessageBox.warning(
                self, "Allow transmit?",
                "With this on, the adapter is no longer listen-only and the app is able to send frames "
                "onto the CAN bus.\n\nOnly use it on a bench. Never on a running car.\n\nSwitch it on?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ok != QMessageBox.Yes:
                self.allow_tx.setChecked(False)
                return
        self._save()
        if self.hub.kind == "can" and self.hub.state != "disconnected":
            self.hub.notice.emit("info", "Disconnect and connect again for the transmit setting to take effect.")

    def _add_dbc(self):
        path, _ = QFileDialog.getOpenFileName(self, "Add a DBC file", str(user_home()), "DBC files (*.dbc)")
        if path:
            self.dbc_list.addItem(path)
            self._save()

    def _remove_dbc(self):
        row = self.dbc_list.currentRow()
        if row >= 0:
            self.dbc_list.takeItem(row)
            self._save()

    def _save(self, *_):
        if self._loading:
            return
        s = self.hub.settings
        for key, ed in self.ids.items():
            text = ed.text().strip()
            try:
                parse_id_list(text)
            except ValueError:
                self.hub.notice.emit("warn", f"'{text}' isn't a list of CAN IDs. Use e.g. 0x500, 0x501 or 0x500-0x503.")
                ed.setText(str(s.get(f"{key}_ids") or ""))
                continue
            s[f"{key}_ids"] = text
        s["allow_transmit"] = self.allow_tx.isChecked()
        s["can_channel"] = self.pcan_channel.currentData()
        s["serial_baud"] = self.baud.currentData()
        s["ecu_expected_hz"] = self.ecu_hz.value()
        s["auto_record"] = self.auto_rec.isChecked()
        s["log_format"] = self.fmt.currentData()
        s["driver"] = self.driver.text().strip()
        s["pressure_units"] = self.pressure.currentData()
        pit_changed = s["pit_wall"] != self.pit.isChecked()
        s["pit_wall"] = self.pit.isChecked()
        s["alarm_sound"] = self.sound.isChecked()
        s["check_updates"] = self.check_upd.isChecked()
        s["extra_dbcs"] = [self.dbc_list.item(i).text() for i in range(self.dbc_list.count())]
        self.hub.settings_changed()
        if pit_changed:
            self.window_ref.apply_pit_wall()

    def on_show(self):
        s = self.hub.settings
        self._loading = True
        for key, ed in self.ids.items():
            ed.setText(str(s.get(f"{key}_ids") or ""))
        self.pit.setChecked(bool(s["pit_wall"]))
        self.driver.setText(s["driver"])
        self._loading = False

    def check_now(self, quiet: bool = False):
        self.upd_text.setText("Checking...")

        def work():
            try:
                self.update_result.emit((fw.newer_manager(fw.list_releases()), quiet))
            except Exception as exc:
                self.update_result.emit((exc, quiet))
        threading.Thread(target=work, daemon=True).start()

    def _on_update(self, result):
        newer, quiet = result
        if isinstance(newer, Exception):
            self.upd_text.setText(f"Couldn't reach GitHub (no internet, or the repo is private). You have {__version__}.")
        elif newer:
            self.upd_text.setText(f"Update available: version {newer['version']}. Download the zip from "
                                  f"github.com/{REPO}/releases")
            self.hub.notice.emit("info", f"Update available: Gryphon Manager {newer['version']}. "
                                         f"Get the zip from github.com/{REPO}/releases")
        else:
            self.upd_text.setText(f"You're up to date (version {__version__}).")
