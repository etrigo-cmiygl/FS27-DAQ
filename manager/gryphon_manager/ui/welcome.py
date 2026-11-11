from __future__ import annotations

import queue

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QButtonGroup, QDialog, QLabel, QRadioButton, QStackedWidget, QWidget

from .. import theme
from ..core.sources import CanSource
from .widgets import button, hbox, label, vbox

TOUR = [
    ("Garage", "Test on the car with just the CAN cable: live values, a light per device, bus health."),
    ("Telemetry", "The pit screen: live radio data, the track map and lap times."),
    ("Car test", "A guided check that saves a pass/fail report."),
    ("Sessions", "Press Record (or Space) any time. Replay, compare and export later."),
    ("Channels", "The master list of sensors. It generates the DBC files and the firmware header."),
    ("Help", "Wiring, the pinout, how to add a sensor, troubleshooting. F1 opens it."),
]


class WelcomeWizard(QDialog):
    def __init__(self, parent, hub):
        super().__init__(parent)
        self.hub = hub
        self.setWindowTitle("Welcome to Gryphon Manager")
        self.setMinimumSize(680, 480)
        self.setModal(True)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._welcome())
        self.pages.addWidget(self._adapter())
        self.pages.addWidget(self._test())
        self.pages.addWidget(self._tour())
        self.back = button("Back", self._back)
        self.next = button("Next", self._next, "primary")
        self.skip = button("Skip", self._finish, "link")
        self.step = label("", "dim")
        self.setLayout(vbox((self.pages, 1), hbox(self.skip, None, self.step, self.back, self.next),
                            margins=(28, 26, 28, 20), spacing=16))
        self._test_src = None
        self._sync()

    @staticmethod
    def _page(title: str, *items) -> QWidget:
        w = QWidget()
        t = label(title, "h1")
        t.setStyleSheet("font-size: 24px; font-weight: 600;")
        w.setLayout(vbox(t, 8, *items, None, spacing=10))
        return w

    def _welcome(self):
        txt = label(
            "This is the one app for the car's data: live values in the garage, telemetry in the pits, "
            "recordings, alarms, and the car's channel list.\n\n"
            "Three things worth knowing before you start:\n\n"
            "•  It only listens. On the car's CAN bus the app can't send anything unless you deliberately "
            "switch that on in Settings.\n\n"
            "•  There's a built-in simulator: a pretend car you can connect to right now, with faults you "
            "can switch on. Use it to learn your way around.\n\n"
            "•  Every empty screen tells you what to do next, and hovering over anything explains it.",
            wrap=True)
        txt.setStyleSheet("font-size: 14px;")
        return self._page("Welcome to Gryphon Manager", txt)

    def _adapter(self):
        self.group = QButtonGroup(self)
        self.r_pcan = QRadioButton("PEAK PCAN-USB (the team's cable)")
        self.r_slcan = QRadioButton("Another USB-CAN adapter (slcan type, e.g. CANable)")
        self.r_none = QRadioButton("Nothing plugged in yet: I'll use the simulator for now")
        for i, r in enumerate((self.r_pcan, self.r_slcan, self.r_none)):
            r.setStyleSheet("font-size: 14px;")
            self.group.addButton(r, i)
        iface = self.hub.settings["can_interface"]
        (self.r_slcan if iface == "slcan" else self.r_pcan).setChecked(True)
        note = label("The PCAN-USB needs PEAK's driver on Windows. If it isn't installed, the next step tells "
                     "you where to get it. You can change the adapter any time in the top bar.", "dim", wrap=True)
        return self._page("Which CAN adapter do you have?", self.r_pcan, self.r_slcan, self.r_none, 8, note)

    def _test(self):
        self.test_text = label("", wrap=True)
        self.test_text.setStyleSheet("font-size: 14px;")
        self.test_btn = button("Test the adapter", self._run_test, "primary")
        self.sim_btn = button("Start the simulator instead", self._start_sim)
        self.test_result = label("", wrap=True)
        self.test_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return self._page("Test the connection", self.test_text, hbox(self.test_btn, self.sim_btn, None),
                          self.test_result)

    def _tour(self):
        rows = []
        for name, text in TOUR:
            n = label(name, "h2")
            n.setFixedWidth(110)
            rows.append(hbox(n, (label(text, wrap=True), 1), spacing=12))
        tip = label("Space records. F11 is full screen. F10 is pit wall mode. Ctrl+1 to Ctrl+9 switch views.",
                    "dim", wrap=True)
        return self._page("A quick tour", *rows, 8, tip)

    def _sync(self):
        i = self.pages.currentIndex()
        self.back.setVisible(i > 0)
        self.next.setText("Finish" if i == self.pages.count() - 1 else "Next")
        self.step.setText(f"Step {i + 1} of {self.pages.count()}")
        if i == 2:
            none = self.r_none.isChecked()
            self.test_btn.setVisible(not none)
            self.test_text.setText(
                "No adapter yet, so there's nothing to test. Start the simulator to have a look around."
                if none else
                "Plug the adapter into the laptop (it doesn't need to be on the car), then press Test. "
                "This opens it in listen-only mode for a moment.")

    def _apply_choice(self):
        s = self.hub.settings
        if self.r_pcan.isChecked():
            s["can_interface"], s["source"] = "pcan", "can"
        elif self.r_slcan.isChecked():
            s["can_interface"], s["source"] = "slcan", "can"
        else:
            s["source"] = "sim"

    def _next(self):
        i = self.pages.currentIndex()
        if i == 1:
            self._apply_choice()
        if i == self.pages.count() - 1:
            self._finish()
            return
        self.pages.setCurrentIndex(i + 1)
        self._sync()

    def _back(self):
        self.pages.setCurrentIndex(max(0, self.pages.currentIndex() - 1))
        self._sync()

    def _run_test(self):
        s = self.hub.settings
        iface = s["can_interface"]
        channel = s["slcan_port"] if iface == "slcan" else s["can_channel"]
        if iface == "slcan" and not channel:
            self._show_result("amber", "Pick the adapter's COM port in the top bar first (source 'Car (CAN cable)'), "
                                       "then press Connect there.")
            return
        self._q = queue.Queue()
        self._test_src = CanSource(self._q, iface, channel, 1000000, listen_only=True)
        self._test_src.start()
        self.test_btn.setEnabled(False)
        self.test_result.setText("Testing...")
        QTimer.singleShot(1800, self._test_done)

    def _test_done(self):
        src, self._test_src = self._test_src, None
        if src is not None:
            src.stop()
        frames, error, opened = 0, "", False
        while True:
            try:
                kind, payload = self._q.get_nowait()
            except queue.Empty:
                break
            if kind == "frame":
                frames += 1
            elif kind == "error":
                error = payload
            elif kind == "opened":
                opened = True
        self.test_btn.setEnabled(True)
        if error:
            self._show_result("red", error)
        elif opened and frames:
            self._show_result("green", f"The adapter works and the bus is alive: {frames} frames in under 2 seconds.")
        elif opened:
            self._show_result("green", "The adapter works. No frames were seen, which is normal if it isn't plugged "
                                       "into the car or the ignition is off.")
        else:
            self._show_result("amber", "The adapter didn't answer in time. Try again.")

    def _show_result(self, state: str, text: str):
        self.test_result.setText(text)
        self.test_result.setStyleSheet(f"font-size: 14px; color: {theme.STATUS[state]};")

    def _start_sim(self):
        self.hub.settings["source"] = "sim"
        self.start_sim = True
        self._show_result("green", "The simulator will start when you finish this tour.")

    def _finish(self):
        if self._test_src is not None:
            self._test_src.stop()
        self.hub.settings["first_run_done"] = True
        self.hub.settings.save()
        self.accept()
