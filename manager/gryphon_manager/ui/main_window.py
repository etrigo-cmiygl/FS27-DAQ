from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFrame, QLabel, QMainWindow,
                               QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, theme
from ..core.simulator import FAULTS, MODES
from ..core.sources import list_serial_ports
from .hub import SOURCE_NAMES, Hub
from .widgets import Pill, button, hbox, label, restyle, vbox

NAV = [
    ("home", "Home"), ("garage", "Garage"), ("signals", "Signals"), ("raw", "Raw frames"),
    ("graphs", "Graphs"), ("telemetry", "Telemetry"), ("cartest", "Car test"), ("alarms", "Alarms"),
    ("sessions", "Sessions"), ("channels", "Channels"), ("daq", "DAQ settings"), ("firmware", "Firmware"),
    ("help", "Help"), ("settings", "Settings"),
]
NAV_TIPS = {
    "home": "Where you are, what's connected, quick buttons",
    "garage": "Test on the car with just the CAN cable",
    "signals": "Every decoded value in one table",
    "raw": "Every CAN frame on the bus, like PCAN-View",
    "graphs": "Live plots of any values",
    "telemetry": "Live data over the radio, with the track map",
    "cartest": "Step-by-step car check that saves a report",
    "alarms": "Warnings when something goes out of range",
    "sessions": "Recordings: replay, compare, export",
    "channels": "The master list of sensors and what goes where",
    "daq": "Change DAQ settings (needs newer DAQ firmware)",
    "firmware": "Put new firmware on the DAQ",
    "help": "Start here guide",
    "settings": "Adapter, units, device IDs, sounds",
}


def fmt_clock(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class MainWindow(QMainWindow):
    def __init__(self, hub: Hub):
        super().__init__()
        self.hub = hub
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        self.sidebar = self._build_sidebar()
        self.topbar = self._build_topbar()
        self.alarmbar = QFrame()
        self.alarmbar.setObjectName("alarmbar")
        self.alarm_label = QLabel("")
        self.alarm_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.alarm_label.setWordWrap(True)
        self.alarmbar.setLayout(hbox((self.alarm_label, 1),
                                     button("See alarms", lambda: self.show_view("alarms")),
                                     margins=(22, 8, 22, 8)))
        self.alarmbar.hide()
        self.noticebar = QFrame()
        self.noticebar.setObjectName("noticebar")
        self.notice_label = QLabel("")
        self.notice_label.setWordWrap(True)
        self.notice_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.noticebar.setLayout(hbox((self.notice_label, 1), button("Dismiss", self.noticebar.hide),
                                      margins=(22, 8, 22, 8)))
        self.noticebar.hide()
        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(self.noticebar.hide)

        self.stack = QStackedWidget()
        self.views: dict[str, QWidget] = {}
        self._build_views()

        right = vbox(self.topbar, self.alarmbar, self.noticebar, (self.stack, 1), spacing=0)
        root.setLayout(hbox(self.sidebar, (self._wrap(right), 1), spacing=0))

        hub.tick.connect(self._on_tick)
        hub.state_changed.connect(self._on_state)
        hub.notice.connect(self.show_notice)
        hub.alarm.connect(self._on_alarm)
        hub.config_changed.connect(self._on_config)
        hub.navigate.connect(self.show_view)
        self._shortcuts()
        self._sync_source_controls()
        self._on_state()
        last = int(hub.settings.get("last_view", 0) or 0)
        self.show_view(NAV[last if 0 <= last < len(NAV) else 0][0])
        self.apply_pit_wall()

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    # ---- building -----------------------------------------------------------

    def _build_sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(190)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 16, 12, 12)
        lay.setSpacing(2)
        from PySide6.QtGui import QPixmap
        from ..core.paths import asset_path
        logo = asset_path("logo_dark.png")
        if logo.exists():
            pic = QLabel()
            pic.setPixmap(QPixmap(str(logo)).scaledToWidth(162, Qt.SmoothTransformation))
            lay.addWidget(pic)
            lay.addSpacing(4)
        else:
            lay.addWidget(label("GRYPHON", "brand"))
        lay.addWidget(label("MANAGER", "brandsub"))
        lay.addSpacing(16)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = {}
        for i, (key, text) in enumerate(NAV):
            b = button(text, name="nav")
            b.setCheckable(True)
            tip = NAV_TIPS[key] + (f"  (Ctrl+{i + 1})" if i < 9 else "")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self.show_view(k))
            self.nav_group.addButton(b)
            self.nav_buttons[key] = b
            lay.addWidget(b)
            if key in ("graphs", "sessions", "firmware"):
                lay.addSpacing(8)
        lay.addStretch(1)
        ver = label(f"v{__version__}", "dim")
        ver.setStyleSheet("font-size: 11px;")
        lay.addWidget(ver)
        return side

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topbar")
        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(180)
        for key in ("can", "radio", "daq", "sim", "replay"):
            self.source_combo.addItem(SOURCE_NAMES[key], key)
        self.source_combo.setToolTip(
            "Where the data comes from.\n"
            "Car (CAN cable): the PCAN-USB on the debug port C41. Sees everything on the bus.\n"
            "Radio: the pit receiver (Rocky) over USB.\n"
            "DAQ over USB: the DAQ's own debug text.\n"
            "Simulator: a pretend car, for practice and demos.\n"
            "Replay: play back a recording.")
        self.detail_combo = QComboBox()
        self.detail_combo.setMinimumWidth(210)
        self.refresh_btn = button("Rescan", self._fill_detail, tip="Look again for adapters and COM ports")
        self.sim_mode = QComboBox()
        for k, v in MODES.items():
            self.sim_mode.addItem(v, k)
        self.sim_mode.setToolTip("What the pretend car is doing")
        self.sim_fault = QComboBox()
        for k, v in FAULTS.items():
            self.sim_fault.addItem(v, k)
        self.sim_fault.setToolTip("Give the pretend car a fault, to see how the app shows it")
        self.connect_btn = button("Connect", self._toggle_connect, "primary")
        self.pill = Pill("Not connected")
        self.pill.setMinimumWidth(150)
        self.listen_pill = Pill("Listen-only")
        self.listen_pill.setToolTip("The app only listens on the car's bus. It never sends anything\n"
                                    "unless 'Allow transmit' is switched on in Settings.")
        self.record_btn = button("●  Record", self.hub.toggle_recording, "record",
                                 "Start or stop recording (Space)")
        self.timer_label = label("00:00", "timer", tip="Time connected, or time recording")
        s = self.hub.settings
        self._set_combo(self.source_combo, s["source"])
        self._set_combo(self.sim_mode, s["sim_mode"])
        self._set_combo(self.sim_fault, s["sim_fault"])
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        self.sim_mode.currentIndexChanged.connect(self._sim_changed)
        self.sim_fault.currentIndexChanged.connect(self._sim_changed)
        bar.setLayout(hbox(self.source_combo, self.detail_combo, self.refresh_btn, self.sim_mode, self.sim_fault,
                           self.connect_btn, self.pill, self.listen_pill, None, self.record_btn,
                           self.timer_label, spacing=10, margins=(22, 10, 22, 10)))
        return bar

    def _build_views(self) -> None:
        from .views import (alarms, cartest, channels, daqsettings, firmware, garage, graphs, help, home, raw,
                            sessions, settings, signals, telemetry)
        classes = {"home": home.HomeView, "garage": garage.GarageView, "signals": signals.SignalsView,
                   "raw": raw.RawView, "graphs": graphs.GraphsView, "telemetry": telemetry.TelemetryView,
                   "cartest": cartest.CarTestView, "alarms": alarms.AlarmsView,
                   "sessions": sessions.SessionsView, "channels": channels.ChannelsView,
                   "daq": daqsettings.DaqSettingsView, "firmware": firmware.FirmwareView,
                   "help": help.HelpView, "settings": settings.SettingsView}
        for key, _ in NAV:
            view = classes[key](self.hub)
            view.window_ref = self
            self.views[key] = view
            self.stack.addWidget(view)

    def _shortcuts(self) -> None:
        for i, (key, _) in enumerate(NAV[:9]):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda k=key: self.show_view(k))
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self._space)
        QShortcut(QKeySequence(Qt.Key_F11), self, activated=self._fullscreen)
        QShortcut(QKeySequence(Qt.Key_F10), self, activated=self.toggle_pit_wall)
        QShortcut(QKeySequence(Qt.Key_F1), self, activated=lambda: self.show_view("help"))

    def _space(self) -> None:
        w = QApplication.focusWidget()
        from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QLineEdit, QPlainTextEdit, QTextEdit
        if isinstance(w, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)):
            return
        if isinstance(w, QAbstractButton) and w is not self.record_btn and w.objectName() != "nav":
            w.click()
            return
        self.hub.toggle_recording()

    def _fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def toggle_pit_wall(self) -> None:
        self.hub.settings["pit_wall"] = not self.hub.settings["pit_wall"]
        self.hub.settings.save()
        self.apply_pit_wall()

    def apply_pit_wall(self) -> None:
        on = bool(self.hub.settings["pit_wall"])
        self.sidebar.setVisible(not on)
        for v in self.views.values():
            if hasattr(v, "set_pit_wall"):
                v.set_pit_wall(on)

    # ---- source controls ----------------------------------------------------

    @staticmethod
    def _set_combo(combo: QComboBox, data) -> None:
        i = combo.findData(data)
        if i >= 0:
            combo.setCurrentIndex(i)

    def _source_changed(self) -> None:
        self.hub.settings["source"] = self.source_combo.currentData()
        self._sync_source_controls()

    def _sync_source_controls(self) -> None:
        kind = self.source_combo.currentData()
        self.sim_mode.setVisible(kind == "sim")
        self.sim_fault.setVisible(kind == "sim")
        self.detail_combo.setVisible(kind in ("can", "radio", "daq"))
        self.refresh_btn.setVisible(kind in ("can", "radio", "daq"))
        self._fill_detail()
        self._update_connect_text()

    def _fill_detail(self) -> None:
        kind = self.source_combo.currentData()
        s = self.hub.settings
        c = self.detail_combo
        c.blockSignals(True)
        c.clear()
        if kind == "can":
            c.addItem("PEAK PCAN-USB", ("pcan", s["can_channel"]))
            for dev, desc in list_serial_ports():
                c.addItem(f"Serial CAN adapter (slcan) on {desc}", ("slcan", dev))
            c.addItem("Virtual bus (for testing)", ("virtual", "gryphon"))
            want = (s["can_interface"], s["slcan_port"] if s["can_interface"] == "slcan" else s["can_channel"])
            for i in range(c.count()):
                if c.itemData(i)[0] == want[0] and (want[0] != "slcan" or c.itemData(i)[1] == want[1]):
                    c.setCurrentIndex(i)
                    break
            c.setToolTip("Which CAN adapter to use. The team's cable is the PEAK PCAN-USB.")
        elif kind in ("radio", "daq"):
            ports = list_serial_ports()
            if not ports:
                c.addItem("No COM ports found: plug it in, then Rescan", "")
            for dev, desc in ports:
                c.addItem(desc, dev)
            self._set_combo(c, s["receiver_port" if kind == "radio" else "daq_port"])
            c.setToolTip("The USB serial (COM) port of the " + ("receiver" if kind == "radio" else "DAQ"))
        c.blockSignals(False)

    def _sim_changed(self) -> None:
        s = self.hub.settings
        s["sim_mode"] = self.sim_mode.currentData()
        s["sim_fault"] = self.sim_fault.currentData()
        src = self.hub.source
        if self.hub.kind == "sim" and src is not None:
            src.set_mode(s["sim_mode"])
            src.set_fault(s["sim_fault"])

    def _toggle_connect(self) -> None:
        hub = self.hub
        if hub.state != "disconnected":
            hub.disconnect_source()
            return
        kind = self.source_combo.currentData()
        s = hub.settings
        if kind == "replay":
            self.show_view("sessions")
            self.show_notice("info", "Pick a recording below and press Replay.")
            return
        if kind == "can":
            iface, channel = self.detail_combo.currentData() or ("pcan", s["can_channel"])
            s["can_interface"] = iface
            if iface == "slcan":
                s["slcan_port"] = channel
            hub.connect_source("can", interface=iface, channel=channel)
        elif kind in ("radio", "daq"):
            port = self.detail_combo.currentData()
            if not port:
                what = "receiver" if kind == "radio" else "DAQ"
                self.show_notice("warn", f"No COM port found. Plug the {what} into USB, press Rescan, then Connect.")
                return
            s["receiver_port" if kind == "radio" else "daq_port"] = port
            hub.connect_source(kind, port=port)
        else:
            hub.connect_source("sim")
        s.save()

    def show_welcome(self) -> None:
        from .welcome import WelcomeWizard
        dlg = WelcomeWizard(self, self.hub)
        dlg.exec()
        self._set_combo(self.source_combo, self.hub.settings["source"])
        self._sync_source_controls()
        if getattr(dlg, "start_sim", False):
            self.connect_simulator()

    def connect_simulator(self) -> None:
        self._set_combo(self.source_combo, "sim")
        if self.hub.state != "disconnected":
            self.hub.disconnect_source()
        self._toggle_connect()

    def _update_connect_text(self) -> None:
        hub = self.hub
        if hub.state == "disconnected":
            text = "Choose recording" if self.source_combo.currentData() == "replay" else "Connect"
        else:
            text = "Disconnect"
        self.connect_btn.setText(text)
        self.connect_btn.setProperty("connected", "true" if hub.state != "disconnected" else "false")
        restyle(self.connect_btn)

    # ---- reacting -----------------------------------------------------------

    def show_view(self, key: str) -> None:
        view = self.views.get(key)
        if view is None:
            return
        self.stack.setCurrentWidget(view)
        self.nav_buttons[key].setChecked(True)
        self.hub.settings["last_view"] = [k for k, _ in NAV].index(key)
        view.on_show()
        view.refresh()

    def current_key(self) -> str:
        w = self.stack.currentWidget()
        return next((k for k, v in self.views.items() if v is w), "home")

    def show_notice(self, level: str, text: str) -> None:
        self.notice_label.setText(text)
        self.noticebar.setProperty("level", level)
        restyle(self.noticebar)
        self.noticebar.show()
        if level == "info":
            self.notice_timer.start(6000)
        else:
            self.notice_timer.stop()

    def _on_alarm(self, ev) -> None:
        if ev.raised and self.hub.settings["alarm_sound"]:
            rule = next((r for r in self.hub.engine.alarms.rules if r.get("name") == ev.name), {})
            if rule.get("sound", True):
                QApplication.beep()

    def _on_state(self) -> None:
        hub = self.hub
        locked = hub.state != "disconnected"
        for w in (self.source_combo, self.detail_combo, self.refresh_btn):
            w.setEnabled(not locked)
        if hub.kind in SOURCE_NAMES and locked:
            self._set_combo(self.source_combo, hub.kind)
            self._sync_visibility_only(hub.kind)
        self._update_connect_text()
        rec = hub.recorder.active
        self.record_btn.setText("■  Stop" if rec else "●  Record")
        self.record_btn.setProperty("recording", "true" if rec else "false")
        restyle(self.record_btn)
        show_listen = locked and hub.kind == "can"
        self.listen_pill.setVisible(show_listen)
        if show_listen:
            lo = getattr(hub.source, "listen_only", True)
            self.listen_pill.set("Listen-only" if lo else "TRANSMIT ALLOWED", "green" if lo else "red")
        for v in self.views.values():
            v.on_state()

    def _sync_visibility_only(self, kind: str) -> None:
        self.sim_mode.setVisible(kind == "sim")
        self.sim_fault.setVisible(kind == "sim")
        self.detail_combo.setVisible(kind in ("can", "radio", "daq"))
        self.refresh_btn.setVisible(kind in ("can", "radio", "daq"))

    def _on_config(self) -> None:
        for v in self.views.values():
            v.on_config()

    def _on_tick(self) -> None:
        hub = self.hub
        e = hub.engine
        if hub.state == "connecting":
            self.pill.set("Connecting...", "amber")
        elif hub.state == "connected":
            if hub.kind == "replay":
                self.pill.set("Replaying", "green")
            elif e.total_frames or e.radio.received or e.daq_can or hub.daq_log:
                quiet = hub.now() - hub.pipe.last_ts > 3.0 if hub.pipe.last_ts else True
                self.pill.set("Connected, no data" if quiet else "Connected", "amber" if quiet else "green")
            else:
                self.pill.set("Connected, no data yet", "amber")
        else:
            self.pill.set("Not connected", "grey")
        self.timer_label.setText(fmt_clock(hub.elapsed))
        active = e.alarms.active
        if active:
            self.alarm_label.setText("ALARM   " + "    |    ".join(f"{n}: {t}" for n, t in active.items()))
            if not self.alarmbar.isVisible():
                self.alarmbar.show()
        elif self.alarmbar.isVisible():
            self.alarmbar.hide()
        view = self.stack.currentWidget()
        if view is not None and hub.ticks % view.refresh_every == 0:
            view.refresh()

    def closeEvent(self, event) -> None:
        self.hub.shutdown()
        super().closeEvent(event)
