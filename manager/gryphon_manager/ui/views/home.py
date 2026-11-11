from __future__ import annotations

from PySide6.QtWidgets import QGridLayout

from ... import theme
from ...core.recorder import list_sessions
from ..hub import SOURCE_NAMES
from ..widgets import Card, Chip, Dot, View, button, hbox, label, vbox


class HomeView(View):
    title = "Home"
    subtitle = "What's connected right now, and where to go next."
    refresh_every = 4

    def __init__(self, hub):
        super().__init__(hub)
        self.status = Card("Connection")
        self.status_text = label("", wrap=True)
        self.status_text.setStyleSheet("font-size: 15px;")
        self.status_hint = label("", "dim", wrap=True)
        self.status.add(self.status_text)
        self.status.add(self.status_hint)

        quick = Card("Quick start")
        quick.add(label("Pick what you want to do. Everything works in the simulator too, so you can practise "
                        "without the car.", "dim", wrap=True))
        self.btn_test = button("Car test", lambda: hub.navigate.emit("cartest"), "primary",
                               "Guided check of the car that saves a pass/fail report")
        self.btn_garage = button("Open Garage view", lambda: hub.navigate.emit("garage"),
                                 tip="Live values and health with the CAN cable")
        self.btn_rec = button("Start recording", hub.toggle_recording, tip="Record everything coming in (Space)")
        self.btn_replay = button("Open replay", lambda: hub.navigate.emit("sessions"),
                                 tip="Play back or export a recording")
        self.btn_sim = button("Try the simulator", lambda: self.window_ref.connect_simulator(),
                              tip="Connect to a pretend car")
        quick.add(hbox(self.btn_test, self.btn_garage, self.btn_rec, self.btn_replay, self.btn_sim, None))

        self.devices = Card("Devices on the car")
        grid = QGridLayout()
        grid.setSpacing(10)
        self.chips = {}
        for i, key in enumerate(("ecu", "daq", "pdm", "lambda", "screen")):
            chip = Chip(hub.engine.device_ids.get(key, {}).get("label", key))
            self.chips[key] = chip
            grid.addWidget(chip, 0, i)
        self.devices.add(grid)

        self.last = Card("Last recording")
        self.last_text = label("", wrap=True)
        self.last.add(self.last_text)
        self.last.add(hbox(button("See all recordings", lambda: hub.navigate.emit("sessions")), None))

        tips = Card("Good to know")
        tips.add(label(
            "• On the car's bus the app only listens. It can't send anything unless you switch on "
            "'Allow transmit' in Settings.\n"
            "• Space starts and stops recording. F11 is full screen. F10 is pit wall mode (big numbers). "
            "Ctrl+1 to Ctrl+9 switch views.\n"
            "• Stuck? The Help view has the wiring, the pinout and a troubleshooting list.",
            "dim", wrap=True))

        self.root.addWidget(self.status)
        self.root.addWidget(quick)
        self.root.addWidget(self.devices)
        self.root.addLayout(hbox((self.last, 1), (tips, 1), spacing=12))
        self.root.addStretch(1)
        self._sessions_at = -1

    def on_show(self) -> None:
        sessions = list_sessions()
        if sessions:
            m = sessions[0]
            dur = m.get("duration_s", 0)
            self.last_text.setText(f"{m.get('name', m['folder'])}\n{m.get('date', '').replace('T', '  ')}   "
                                   f"{dur:.0f} s   {m.get('source', '')}"
                                   + (f"\nDriver: {m['driver']}" if m.get("driver") else ""))
        else:
            self.last_text.setText("Nothing recorded yet. Connect, then press Record (or Space).")

    def on_state(self) -> None:
        self.btn_rec.setText("Stop recording" if self.hub.recorder.active else "Start recording")
        self.on_show()

    def refresh(self) -> None:
        hub, e = self.hub, self.hub.engine
        if hub.state == "connected":
            self.status.set_status("green")
            what = SOURCE_NAMES.get(hub.kind, hub.kind)
            self.status_text.setText(f"Connected: {what}" + (f"  ({hub.label})" if hub.label and hub.label != what else ""))
            bits = []
            if e.total_frames:
                bits.append(f"{e.frame_rate:.0f} CAN frames a second, bus load {e.bus_load:.1f} %")
            if e.radio.received:
                bits.append(f"radio {e.radio.rate:.1f} packets a second, {e.radio.loss_pct:.0f} % lost")
            if hub.recorder.active:
                bits.append("recording")
            self.status_hint.setText("   |   ".join(bits) if bits else "Waiting for data...")
        elif hub.state == "connecting":
            self.status.set_status("amber")
            self.status_text.setText("Connecting...")
            self.status_hint.setText("")
        else:
            self.status.set_status("grey")
            self.status_text.setText("Not connected")
            self.status_hint.setText(
                hub.last_error.split("\n")[0] if hub.last_error else
                "Pick a source in the top bar and press Connect. On the car: plug the PCAN-USB into the debug "
                "port (C41), choose 'Car (CAN cable)', Connect. No car? Choose 'Simulator'.")
        for key, chip in self.chips.items():
            d = e.devices.get(key)
            if d is None:
                continue
            chip.title.setText(d.label)
            if hub.state != "connected":
                chip.set("grey", "Not connected")
            else:
                chip.set(d.status, d.text)
