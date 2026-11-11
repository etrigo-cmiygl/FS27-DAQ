from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel

from ... import theme
from ...core.engine import SOURCE_LABEL
from ...core.model import fmt_id
from ..widgets import Card, Chip, EmptyState, Switcher, Tile, View, age_text, button, fmt_num, hbox, label, vbox

BAR_TO_PSI = 14.5038

TILES = [
    ("rpm", "RPM", "rpm", 0, "Engine speed from the ECU"),
    ("tps", "Throttle", "%", 1, "Throttle position (TPS)"),
    ("engine_temp", "Engine temp", "°C", 1, "Coolant temperature"),
    ("oil_pressure", "Oil pressure", "bar", 2, "Should rise as soon as the engine runs"),
    ("fuel_pressure", "Fuel pressure", "bar", 2, "Fuel rail pressure"),
    ("water_pressure", "Water press.", "bar", 2, "Coolant (water) pressure"),
    ("map", "MAP", "kPa", 1, "Manifold absolute pressure. About 101 kPa with the engine off."),
    ("air_temp", "Air temp", "°C", 1, "Intake air temperature"),
    ("lambda", "Lambda", "λ", 3, "Exhaust oxygen. 1.000 is the ideal mixture, lower is richer."),
    ("battery", "Battery", "V", 2, "Battery voltage, sent by the DAQ in frame 0x601"),
]


class GarageView(View):
    title = "Garage"
    subtitle = "Testing on the car with just the CAN cable on the debug port. No antenna needed."

    def __init__(self, hub):
        super().__init__(hub)
        self.empty = EmptyState(
            "Plug the PCAN into C41 and press Connect",
            "1. Plug the PEAK PCAN-USB into the laptop and into the car's debug port (C41, the 9-pin plug).\n"
            "2. Switch the car's ignition on.\n"
            "3. Choose 'Car (CAN cable)' in the top bar and press Connect.\n\n"
            "The app only listens, so it can't upset the car.",
            "Try it in the simulator", lambda: self.window_ref.connect_simulator(),
            "Wiring help", lambda: hub.navigate.emit("help"))
        content = self._build()
        self.switch = Switcher(self.empty, content)
        self.root.addWidget(self.switch, 1)

    def _build(self):
        from PySide6.QtWidgets import QWidget
        w = QWidget()
        self.chips = {}
        chips = hbox(spacing=10)
        tips = {
            "ecu": "The FuelTech FT550 Lite. Sends 9 frames (0x14080600 to 0x14080608).",
            "daq": "Ryland. Sends frames 0x600 to 0x603 for the steering wheel screen, 20 times a second.",
            "pdm": "Power distribution module. Its CAN IDs aren't known yet: set them in Settings.",
            "lambda": "Lambda (oxygen sensor) unit. Its CAN IDs aren't known yet: set them in Settings.",
            "screen": "The Winstar steering wheel screen. It only listens, so it can't be seen directly.",
        }
        for key in ("ecu", "daq", "pdm", "lambda", "screen"):
            chip = Chip(key, tips[key])
            self.chips[key] = chip
            chips.addWidget(chip, 1)

        grid = QGridLayout()
        grid.setSpacing(10)
        self.tiles = {}
        for i, (key, cap, units, dec, tip) in enumerate(TILES):
            t = Tile(cap, units, dec, tip, size=40)
            self.tiles[key] = t
            grid.addWidget(t, i // 5, i % 5)

        self.bus = Card("Bus health", "How healthy the CAN bus itself is")
        self.bus_text = label("", wrap=True)
        self.bus_grid = QGridLayout()
        self.bus_grid.setHorizontalSpacing(18)
        self.bus_vals = {}
        rows = [("load", "Bus load", "How full the bus is. Under 50 % is comfortable."),
                ("fps", "Frames a second", "Everything on the bus, from all devices"),
                ("err", "Error frames", "Should stay at 0. Climbing means wiring, termination or bit rate."),
                ("state", "Adapter state", "OK, error warning, error passive or bus off"),
                ("drop", "Dropped frames", "Frames the adapter couldn't keep up with. Should be 0.")]
        for r, (k, name, tip) in enumerate(rows):
            self.bus_grid.addWidget(label(name, "dim", tip=tip), r, 0)
            v = QLabel("--")
            v.setStyleSheet("font-size: 15px; font-weight: 600;")
            self.bus_vals[k] = v
            self.bus_grid.addWidget(v, r, 1)
        self.bus_grid.setColumnStretch(2, 1)
        self.bus.add(self.bus_text)
        self.bus.add(self.bus_grid)
        self.usb_text = label("", "dim", wrap=True)
        self.bus.add(self.usb_text)

        self.ecu = Card("ECU broadcast rate", "How often the FT550 sends each of its 9 frames")
        self.ecu_text = label("", wrap=True)
        self.ecu_rates = label("", "dim", wrap=True)
        self.ecu.add(self.ecu_text)
        self.ecu.add(self.ecu_rates)

        self.daq = Card("DAQ check", "Are the DAQ's frames for the screen there, and do they match the ECU?")
        self.daq_text = label("", wrap=True)
        self.daq_grid = QGridLayout()
        self.daq_grid.setHorizontalSpacing(16)
        for c, head in enumerate(("", "ECU says", "DAQ sends", "")):
            self.daq_grid.addWidget(label(head, "caption"), 0, c)
        self.daq_cells = []
        for r in range(5):
            cells = [QLabel(""), QLabel("--"), QLabel("--"), QLabel("")]
            cells[1].setMinimumWidth(96)
            cells[2].setMinimumWidth(96)
            for c, cell in enumerate(cells):
                self.daq_grid.addWidget(cell, r + 1, c)
            self.daq_cells.append(cells)
        self.daq_grid.setColumnStretch(4, 1)
        self.daq.add(self.daq_text)
        self.daq.add(self.daq_grid)

        self.trend = Card("Last 60 seconds", "RPM and throttle, so you can see blips and dropouts at a glance")
        import pyqtgraph as pg
        self.trend_plot = pg.GraphicsLayoutWidget()
        self.trend_plot.setBackground(theme.PANEL)
        self.trend_curves = {}
        for row, (key, name, color) in enumerate((("rpm", "RPM", theme.GREEN_BRIGHT),
                                                  ("tps", "Throttle %", theme.RED_BRIGHT))):
            p = self.trend_plot.addPlot(row=row, col=0)
            p.showGrid(x=False, y=True, alpha=0.12)
            p.setMouseEnabled(False, False)
            p.hideButtons()
            p.setMenuEnabled(False)
            p.setLabel("left", name)
            p.setXRange(-60, 0, padding=0)
            for ax in ("left", "bottom"):
                p.getAxis(ax).setPen(pg.mkPen(theme.BORDER))
                p.getAxis(ax).setTextPen(pg.mkPen(theme.TEXT_DIM))
            p.getAxis("left").setWidth(52)
            if row == 0:
                p.hideAxis("bottom")
            else:
                p.setLabel("bottom", "seconds ago")
                p.setYRange(0, 100, padding=0.05)
            self.trend_curves[key] = p.plot([], [], pen=pg.mkPen(color, width=2))
        self.trend.add(self.trend_plot, 1)
        side = vbox(self.bus, self.ecu, self.daq, None, spacing=10)
        left = vbox(grid, (self.trend, 1), spacing=10)
        self.side_widget = self._w(side)
        body = hbox((self._w(left), 3), (self.side_widget, 2), spacing=12)
        w.setLayout(vbox(chips, (self._w(body), 1), spacing=12))
        return w

    @staticmethod
    def _w(layout):
        from PySide6.QtWidgets import QWidget
        w = QWidget()
        w.setLayout(layout)
        return w

    def set_pit_wall(self, on: bool) -> None:
        self.side_widget.setVisible(not on)
        for t in self.tiles.values():
            t.set_scale(1.7 if on else 1.0)

    def refresh(self) -> None:
        hub, e = self.hub, self.hub.engine
        has_data = hub.state == "connected" and (hub.kind != "radio")
        if hub.state == "connected" and hub.kind == "radio":
            self.empty.set_text("This view is for the CAN cable",
                                "You're connected to the radio receiver. Live radio data is in the Telemetry "
                                "view. To test on the car, disconnect and choose 'Car (CAN cable)'.")
        elif hub.state != "connected":
            self.empty.set_text(
                "Plug the PCAN into C41 and press Connect",
                "1. Plug the PEAK PCAN-USB into the laptop and into the car's debug port (C41, the 9-pin plug).\n"
                "2. Switch the car's ignition on.\n"
                "3. Choose 'Car (CAN cable)' in the top bar and press Connect.\n\n"
                "The app only listens, so it can't upset the car.")
        self.switch.show_content(has_data)
        if not has_data:
            return
        now = e.now
        usb_only = not e.can_expected and (hub.kind == "daq" or bool(e.daq_can))
        for key, chip in self.chips.items():
            d = e.devices.get(key)
            if d is None:
                continue
            chip.title.setText(d.label)
            if usb_only:
                if key == "daq":
                    st, text = e.daq_usb_health()
                    chip.set(st, text.split(". ")[0] + ".", "from the DAQ's own [CAN] line")
                elif key == "ecu":
                    rx = e.daq_can.get("rx")
                    if rx is None:
                        chip.set("grey", "Waiting for the DAQ...", "")
                    elif e.daq_rx_rate > 0:
                        chip.set("green", f"The DAQ is decoding it: {e.daq_rx_rate / 9:.1f} Hz",
                                 f"{rx} ECU frames decoded so far")
                    else:
                        chip.set("red", "The DAQ isn't receiving ECU frames", f"count stuck at {rx}")
                else:
                    chip.set("grey", "Can't be seen over USB", "use the CAN cable")
                continue
            line1 = d.text
            if d.total_ids:
                line2 = age_text(d.age)
                if d.expected and d.last_seen:
                    line2 = f"measured {d.rate:.1f} Hz, expected {d.expected:g} Hz, {line2}"
                if d.status == "green":
                    line1 = f"OK: all {d.total_ids} frames arriving" if d.total_ids > 1 else "OK"
            else:
                line2 = ""
            chip.set(d.status, line1, line2)

        psi = hub.settings["pressure_units"] == "psi"
        for key, cap, units, dec, tip in TILES:
            tile = self.tiles[key]
            sig = e.best(key)
            if sig is None or sig.value is None:
                tile.set(None, foot="no data yet")
                continue
            v = sig.value
            u = units
            if key == "map" and not sig.key.startswith("daq."):
                v *= 100.0
            if units == "bar" and psi:
                v, u = v * BAR_TO_PSI, "psi"
            age = now - sig.last_ts
            stale = age > 3.0
            prefix = sig.key[: len(sig.key) - len(key)]
            foot = f"from {SOURCE_LABEL.get(prefix, 'ECU')}"
            state = ""
            if stale:
                foot = f"stale: {age_text(age)}"
            elif sig.out_of_range:
                state, foot = "amber", "outside the expected range"
            if key == "battery" and v == 0 and not stale:
                state, foot = "amber", "reads 0: not measured yet (see Help)"
            if key in ("oil_pressure",) and "Low oil pressure" in e.alarms.active:
                state = "red"
            if key == "engine_temp" and "Engine too hot" in e.alarms.active:
                state = "red"
            tile.set(v, state, foot, stale, u)

        if hub.ticks % 4 == 0:
            import numpy as np
            for key, curve in self.trend_curves.items():
                sig = e.best(key)
                if sig is None or not sig.ht:
                    curve.setData([], [])
                    continue
                t = np.fromiter(sig.ht, dtype=float, count=len(sig.ht)) - now
                v = np.fromiter(sig.hv, dtype=float, count=len(sig.hv))
                i = int(np.searchsorted(t, -60.0))
                curve.setData(t[i:], v[i:])
        st, text = e.bus_summary()
        if usb_only:
            st, text = e.daq_usb_health()
            self.bus.title.setText("DAQ's CAN status (from its USB debug line)")
        else:
            self.bus.title.setText("Bus health")
        self.bus.set_status(st)
        self.bus_text.setText(text)
        if usb_only:
            c = e.daq_can
            self.bus_vals["load"].setText("--")
            self.bus_vals["fps"].setText(f"{c.get('rx', 0)} ECU frames decoded" if c else "--")
            self.bus_vals["err"].setText(f"TEC {c.get('tec', 0)} / REC {c.get('rec', 0)}" if c else "--")
            self.bus_vals["state"].setText(f"EFLG 0x{c.get('eflg', 0):02X}  TXB0CTRL 0x{c.get('txb0ctrl', 0):02X}"
                                           if c else "--")
            self.bus_vals["drop"].setText(f"{e.daq_tx_fail} radio sends failed")
            self.usb_text.setText("Over USB you see what the DAQ sees, not the bus itself. "
                                  "Use the CAN cable for bus load, device rates and the DAQ check.")
        else:
            self.bus_vals["load"].setText(f"{e.bus_load:.1f} %")
            self.bus_vals["fps"].setText(f"{e.frame_rate:.0f}")
            self.bus_vals["err"].setText(str(e.error_frames))
            self.bus_vals["err"].setStyleSheet("font-size: 15px; font-weight: 600; color: %s;" %
                                               (theme.RED_BRIGHT if e.error_frames else theme.TEXT))
            self.bus_vals["state"].setText(e.bus_state or "--")
            self.bus_vals["drop"].setText(str(e.dropped))
            self.usb_text.setText(e.bus_detail)

        if usb_only:
            rate = e.daq_rx_rate / 9.0
            exp = e.devices["ecu"].expected or 10.0
            self.ecu.set_status("grey" if not e.daq_can else ("green" if rate >= 0.5 * exp else "amber"))
            self.ecu_text.setText(
                "Waiting for the DAQ's [CAN] line." if not e.daq_can else
                f"Going by the DAQ's receive counter, each ECU frame arrives about {rate:.1f} times a second "
                f"(expected about {exp:g})." + ("" if rate >= 0.5 * exp else
                                                " Fix it in FTManager: Sensors and Calibrations > CAN communication."))
            self.ecu_rates.setText("")
            self.daq.set_status("grey")
            self.daq_text.setText("This check needs the CAN cable. Over USB the app can't see the frames the DAQ "
                                  "puts on the bus, only whether its sends are being acknowledged (see above).")
            for cells in self.daq_cells:
                for c in cells:
                    c.setText("")
            return
        self.ecu.set_status(e.ecu_check.status)
        self.ecu_text.setText(e.ecu_check.text)
        if e.ecu_check.rows:
            self.ecu_rates.setText("   ".join(f"…{i[-3:]}: {r:.1f} Hz" for i, r, _ in e.ecu_check.rows))
        else:
            self.ecu_rates.setText("")
        self.daq.set_status(e.daq_check.status)
        self.daq_text.setText(e.daq_check.text)
        rows = e.daq_check.rows
        for r, cells in enumerate(self.daq_cells):
            if r < len(rows):
                name, ev, dv, units, state = rows[r]
                cells[0].setText(name)
                dec = 0 if units == "rpm" else 1
                cells[1].setText(f"{fmt_num(ev, dec)} {units}" if ev is not None else "--")
                cells[2].setText(f"{fmt_num(dv, dec)} {units}" if dv is not None else "--")
                word = {"green": "match", "amber": "checking", "red": "MISMATCH", "grey": "waiting"}[state]
                cells[3].setText(word)
                cells[3].setStyleSheet(f"color: {theme.STATUS[state]}; font-weight: 600;")
            else:
                for c in cells:
                    c.setText("")
