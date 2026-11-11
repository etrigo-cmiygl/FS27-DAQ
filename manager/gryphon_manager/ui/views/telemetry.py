from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QTableWidget, QTableWidgetItem, QWidget

from ... import theme
from ...core.laps import EARTH_R, fmt_lap
from ..widgets import Card, EmptyState, Switcher, Tile, View, age_text, button, fmt_num, hbox, label, vbox

TILES = [
    ("gps_speed", "Speed", "km/h", 0, "GPS speed"),
    ("rpm", "RPM", "rpm", 0, ""),
    ("tps", "Throttle", "%", 0, ""),
    ("engine_temp", "Engine temp", "°C", 1, ""),
    ("oil_pressure", "Oil pressure", "bar", 2, ""),
    ("fuel_pressure", "Fuel pressure", "bar", 2, ""),
    ("battery", "Battery", "V", 2, ""),
    ("gps_sats", "Satellites", "", 0, "GPS satellites in use. 6 or more is a solid fix."),
]


def speed_color(frac: float):
    frac = max(0.0, min(1.0, frac))
    if frac < 0.5:
        a, b, f = (224, 69, 58), (224, 162, 58), frac * 2
    else:
        a, b, f = (224, 162, 58), (47, 163, 107), (frac - 0.5) * 2
    return tuple(int(a[i] + (b[i] - a[i]) * f) for i in range(3))


class TelemetryView(View):
    title = "Telemetry"
    subtitle = "Live data over the radio from the pit receiver, with the track map and lap times."
    refresh_every = 2

    def __init__(self, hub):
        super().__init__(hub)
        self.empty = EmptyState(
            "Plug in the receiver and press Connect",
            "1. Plug the pit receiver (Rocky) into USB and put its antenna up high.\n"
            "2. Choose 'Radio (pit receiver)' in the top bar, pick its COM port and press Connect.\n"
            "3. Power the car. Packets arrive about twice a second.\n\n"
            "The map draws itself from GPS, so it works with no internet.",
            "Try it in the simulator", lambda: self.window_ref.connect_simulator())
        self.switch = Switcher(self.empty, self._build())
        self.root.addWidget(self.switch, 1)
        self._track_len = -1
        self._arming = False
        self._origin = None

    def _build(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout()
        grid.setSpacing(10)
        self.tiles = {}
        for i, (key, cap, units, dec, tip) in enumerate(TILES):
            t = Tile(cap, units, dec, tip, size=30, min_width=110)
            self.tiles[key] = t
            grid.addWidget(t, 0, i)

        self.plot = pg.PlotWidget()
        self.plot.setBackground(theme.PANEL)
        self.plot.setAspectLocked(True)
        self.plot.hideAxis("left")
        self.plot.hideAxis("bottom")
        self.plot.setMenuEnabled(False)
        self.plot.setToolTip("The car's path from GPS, coloured by speed (red slow, green fast).\n"
                             "Red crosses mark where radio packets were lost.")
        self.track_item = pg.ScatterPlotItem(size=5, pen=None)
        self.loss_item = pg.ScatterPlotItem(size=11, symbol="x", pen=pg.mkPen(theme.RED_BRIGHT, width=2),
                                            brush=pg.mkBrush(theme.RED_BRIGHT))
        self.gate_item = pg.PlotCurveItem(pen=pg.mkPen(theme.TEXT, width=4))
        self.car_item = pg.ScatterPlotItem(size=16, pen=pg.mkPen(theme.BG, width=2), brush=pg.mkBrush(theme.TEXT))
        for it in (self.track_item, self.loss_item, self.gate_item, self.car_item):
            self.plot.addItem(it)
        self.plot.scene().sigMouseClicked.connect(self._clicked)
        self.map_hint = label("", "dim")
        self.gate_btn = button("Set start/finish line", self._arm,
                               tip="Click this, then click the track where the start/finish line is")
        map_card = Card("Track map")
        map_card.add(self.plot, 1)
        map_card.add(hbox(self.gate_btn, button("Clear laps", self._clear_laps),
                          button("Clear map", self._clear_map), None, self.map_hint))

        self.link = Card("Radio link", "How good the radio connection to the car is")
        self.link_text = label("", wrap=True)
        lg = QGridLayout()
        lg.setHorizontalSpacing(18)
        self.link_vals = {}
        rows = [("pps", "Packets a second", "The DAQ sends 2 a second"),
                ("lost", "Packets lost", "Worked out from gaps in the DAQ's packet counter"),
                ("age", "Last packet", "How long since the last packet arrived"),
                ("rssi", "Signal strength (RSSI)", "Closer to 0 is stronger. Below about -100 dBm is marginal."),
                ("snr", "Signal to noise (SNR)", "Higher is better. Below 0 dB is marginal."),
                ("fmt", "Receiver format", "The text format the receiver is sending")]
        for r, (k, name, tip) in enumerate(rows):
            lg.addWidget(label(name, "dim", tip=tip), r, 0)
            v = QLabel("--")
            v.setStyleSheet("font-size: 15px; font-weight: 600;")
            self.link_vals[k] = v
            lg.addWidget(v, r, 1)
        lg.setColumnStretch(2, 1)
        self.link.add(self.link_text)
        self.link.add(lg)

        self.laps = Card("Lap times")
        self.lap_now = QLabel("--:--.--")
        self.lap_now.setStyleSheet("font-size: 30px; font-weight: 600;")
        self.lap_best = label("Best --:--.--     Last --:--.--", "dim")
        self.lap_table = QTableWidget(0, 3)
        self.lap_table.setHorizontalHeaderLabels(["Lap", "Time", "Gap to best"])
        self.lap_table.verticalHeader().hide()
        self.lap_table.setShowGrid(False)
        self.lap_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.lap_table.horizontalHeader().setStretchLastSection(True)
        self.lap_table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lap_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lap_table.setColumnWidth(0, 60)
        self.lap_table.setColumnWidth(1, 110)
        self.lap_hint = label("", "dim", wrap=True)
        self.laps.add(self.lap_now)
        self.laps.add(self.lap_best)
        self.laps.add(self.lap_hint)
        self.laps.add(self.lap_table, 1)

        side = QWidget()
        side.setLayout(vbox(self.link, (self.laps, 1), spacing=10))
        side.setMaximumWidth(380)
        body = hbox((map_card, 1), side, spacing=12)
        w.setLayout(vbox(grid, (self._w(body), 1), spacing=12))
        return w

    @staticmethod
    def _w(layout):
        w = QWidget()
        w.setLayout(layout)
        return w

    def set_pit_wall(self, on: bool) -> None:
        for t in self.tiles.values():
            t.set_scale(1.4 if on else 1.0)

    def _xy(self, lat, lon):
        lat0, lon0 = self._origin
        return (math.radians(lon - lon0) * EARTH_R * math.cos(math.radians(lat0)),
                math.radians(lat - lat0) * EARTH_R)

    def _arm(self):
        if not self.hub.engine.track:
            self.hub.notice.emit("warn", "There's no track on the map yet. Wait for the car to drive a bit first.")
            return
        self._arming = True
        self.gate_btn.setText("Now click the track...")

    def _clicked(self, ev):
        if not self._arming or self._origin is None:
            return
        self._arming = False
        self.gate_btn.setText("Set start/finish line")
        p = self.plot.plotItem.vb.mapSceneToView(ev.scenePos())
        lat0, lon0 = self._origin
        lat = lat0 + math.degrees(p.y() / EARTH_R)
        lon = lon0 + math.degrees(p.x() / (EARTH_R * math.cos(math.radians(lat0))))
        e = self.hub.engine
        if e.laps.set_gate_from_track(lat, lon, e.track):
            self.hub.notice.emit("info", "Start/finish line set. Lap times start from the next time the car crosses it.")
        else:
            self.hub.notice.emit("warn", "Couldn't work out which way the track runs there. Try another spot.")
        self._track_len = -1

    def _clear_laps(self):
        self.hub.engine.laps.reset()

    def _clear_map(self):
        e = self.hub.engine
        e.track.clear()
        e.radio.loss_points.clear()
        self._track_len = -1

    def refresh(self) -> None:
        hub, e = self.hub, self.hub.engine
        show = hub.state == "connected" and (e.radio.received > 0 or bool(e.track) or hub.kind in ("radio", "sim", "replay"))
        if hub.state == "connected" and not show:
            self.empty.set_text("No radio data on this connection",
                                "You're connected with the CAN cable or DAQ USB. The map fills in if the DAQ has "
                                "a GPS fix. For live radio data, connect to 'Radio (pit receiver)'.")
        self.switch.show_content(show)
        if not show:
            return
        now = e.now
        radio_live = now - e.radio.last_ts < 3.0
        for key, cap, units, dec, tip in TILES:
            sig = e.signals.get("radio." + key) if radio_live else e.best(key)
            if sig is None or sig.value is None:
                self.tiles[key].set(None, foot="no data yet")
                continue
            age = now - sig.last_ts
            stale = age > 3.0
            foot = age_text(age) if stale else ("via radio" if sig.key.startswith("radio.") else "via cable")
            state = "amber" if (key == "battery" and sig.value == 0 and not stale) else ""
            self.tiles[key].set(sig.value, state, foot, stale)

        r = e.radio
        if r.received:
            age = now - r.last_ts
            if age > 3.0:
                st, text = "red", f"Signal lost {age:.0f} s ago. Is the car out of range or switched off?"
            elif r.rate < 1.2 or (r.rssi is not None and r.rssi < -100):
                st, text = "amber", "Weak link: packets are being lost."
            else:
                st, text = "green", "Good link."
            self.link.set_status(st)
            self.link_text.setText(text)
            self.link_vals["pps"].setText(f"{r.rate:.1f}")
            self.link_vals["lost"].setText(f"{r.lost}  ({r.loss_pct:.0f} %)")
            self.link_vals["age"].setText(f"{age:.1f} s ago")
            self.link_vals["rssi"].setText(f"{r.rssi:.0f} dBm" if r.rssi is not None else "not sent by receiver")
            self.link_vals["snr"].setText(f"{r.snr:.0f} dB" if r.snr is not None else "not sent by receiver")
            self.link_vals["fmt"].setText(r.format or "--")
        else:
            self.link.set_status("grey")
            self.link_text.setText("No radio packets yet." if hub.kind in ("radio", "sim", "replay")
                                   else "Not connected to the receiver. The map is drawn from the CAN cable.")
            for v in self.link_vals.values():
                v.setText("--")

        track = e.track
        n = len(track)
        if n and n != self._track_len:
            self._track_len = n
            pts = list(track)[-6000:]
            if self._origin is None or n < 3:
                self._origin = (pts[0][1], pts[0][2])
            xs, ys, speeds = [], [], []
            for _, la, lo, sp in pts:
                x, y = self._xy(la, lo)
                xs.append(x)
                ys.append(y)
                speeds.append(sp)
            top = max(max(speeds), 30.0)
            brushes = [pg.mkBrush(*speed_color(s / top)) for s in speeds]
            self.track_item.setData(x=xs, y=ys, brush=brushes)
            self.car_item.setData(x=[xs[-1]], y=[ys[-1]])
            lp = [self._xy(la, lo) for la, lo in r.loss_points[-400:]]
            self.loss_item.setData(x=[p[0] for p in lp], y=[p[1] for p in lp])
            gl = e.laps.gate_line()
            if gl:
                a, b = self._xy(*gl[0]), self._xy(*gl[1])
                self.gate_item.setData([a[0], b[0]], [a[1], b[1]])
            else:
                self.gate_item.setData([], [])
            self.map_hint.setText(f"{n} GPS points, top speed {top:.0f} km/h, {len(r.loss_points) // 2} signal drops")
        elif not n:
            if self._track_len != 0:
                self._track_len = 0
                self._origin = None
                for it in (self.track_item, self.loss_item, self.car_item):
                    it.setData(x=[], y=[])
                self.gate_item.setData([], [])
            self.map_hint.setText("Waiting for a GPS fix. The GPS needs a clear view of the sky.")

        laps = e.laps
        if not laps.gate:
            self.lap_hint.setText("To time laps: press 'Set start/finish line', then click the track.")
            self.lap_now.setText("--:--.--")
        else:
            self.lap_hint.setText("")
            self.lap_now.setText(fmt_lap(laps.current_time(now)))
        best = laps.best
        last = laps.laps[-1] if laps.laps else None
        self.lap_best.setText(f"Best {fmt_lap(best.time if best else None)}     "
                              f"Last {fmt_lap(last.time if last else None)}")
        if self.lap_table.rowCount() != len(laps.laps):
            self.lap_table.setRowCount(len(laps.laps))
            for i, lap in enumerate(reversed(laps.laps)):
                gap = lap.time - best.time
                for c, text in enumerate((str(lap.number), fmt_lap(lap.time),
                                          "best" if gap < 1e-6 else f"+{gap:.2f} s")):
                    item = QTableWidgetItem(text)
                    if gap < 1e-6:
                        item.setForeground(pg.mkColor(theme.GREEN_BRIGHT))
                    self.lap_table.setItem(i, c, item)
