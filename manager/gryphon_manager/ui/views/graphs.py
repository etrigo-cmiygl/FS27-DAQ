from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QLineEdit, QListWidget, QListWidgetItem,
                               QSplitter, QWidget)

from ... import theme
from ...core.paths import user_home
from ..widgets import EmptyState, Switcher, View, button, fmt_num, hbox, label, vbox

MAX_PLOTS = 4


class GraphsView(View):
    title = "Graphs"
    subtitle = "Tick signals on the left. Values with the same units share a plot. Scroll to zoom, drag to pan."
    refresh_every = 2

    def __init__(self, hub):
        super().__init__(hub)
        self.selected: list[str] = list(hub.settings.get("graph_signals") or [])
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a signal")
        self.search.setClearButtonEnabled(True)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._item_changed)
        self.search.textChanged.connect(lambda *_: self._fill_list())
        self.window_combo = QComboBox()
        for text, secs in (("Last 10 seconds", 10), ("Last 30 seconds", 30), ("Last minute", 60),
                           ("Last 5 minutes", 300), ("Everything", 0)):
            self.window_combo.addItem(text, secs)
        self.window_combo.setCurrentIndex(1)
        self.pause = QCheckBox("Pause")
        self.pause.setToolTip("Freeze the plots so you can zoom in and read values. Data keeps recording.")
        self.readout = label("Move the mouse over a plot to read values.", "dim")
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground(theme.PANEL)
        self.empty = EmptyState("Nothing to plot yet", "Tick one or more signals on the left. "
                                "If the list is empty, connect to the car or the simulator first.")
        self.switch = Switcher(self.empty, self.glw)
        left = QWidget()
        left.setLayout(vbox(self.search, self.list, button("Untick all", self._clear), spacing=6))
        left.setMaximumWidth(290)
        right = QWidget()
        right.setLayout(vbox(hbox(self.window_combo, self.pause, None,
                                  button("Fit", self._fit, tip="Zoom back out to show everything in the window"),
                                  button("Save as PNG", self._export, tip="Save the plots as a picture")),
                             (self.switch, 1), self.readout, spacing=8))
        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        self.root.addWidget(split, 1)
        self.plots: list = []
        self.curves: dict[str, object] = {}
        self._known = 0
        self._layout_key = None
        self.proxy = pg.SignalProxy(self.glw.scene().sigMouseMoved, rateLimit=30, slot=self._mouse)
        self._cursor_x = None

    def add_signal(self, key: str) -> None:
        if key not in self.selected:
            self.selected.append(key)
            self._save()
            self._fill_list()

    def _save(self):
        self.hub.settings["graph_signals"] = list(self.selected)

    def _clear(self):
        self.selected = []
        self._save()
        self._fill_list()

    def _fit(self):
        self.pause.setChecked(False)
        for p in self.plots:
            p.enableAutoRange()

    def _export(self):
        default = str(user_home() / "graph.png")
        path, _ = QFileDialog.getSaveFileName(self, "Save graph", default, "PNG picture (*.png)")
        if path:
            self.glw.grab().save(path)
            self.hub.notice.emit("info", f"Graph saved to {path}")

    def _fill_list(self):
        e = self.hub.engine
        text = self.search.text().strip().lower()
        self.list.blockSignals(True)
        self.list.clear()
        sigs = [s for s in e.signals.values() if s.count or s.key in self.selected]
        sigs.sort(key=lambda s: (s.key not in self.selected, s.name.lower()))
        for s in sigs:
            if text and text not in f"{s.name} {s.key} {s.units}".lower():
                continue
            it = QListWidgetItem(f"{s.name}" + (f"  ({s.units})" if s.units else ""))
            it.setData(Qt.UserRole, s.key)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if s.key in self.selected else Qt.Unchecked)
            self.list.addItem(it)
        self.list.blockSignals(False)
        self._known = sum(1 for s in e.signals.values() if s.count)

    def _item_changed(self, item):
        key = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked and key not in self.selected:
            self.selected.append(key)
        elif item.checkState() != Qt.Checked and key in self.selected:
            self.selected.remove(key)
        self._save()

    def on_show(self):
        self._fill_list()

    def _rebuild(self, groups):
        self.glw.clear()
        self.plots, self.curves = [], {}
        self.vlines = []
        color_i = 0
        for row, (units, keys) in enumerate(groups):
            p = self.glw.addPlot(row=row, col=0)
            p.showGrid(x=True, y=True, alpha=0.15)
            p.setLabel("left", units or "value")
            p.addLegend(offset=(8, 4), labelTextColor=theme.TEXT, brush=pg.mkBrush(theme.PANEL))
            for ax in ("left", "bottom"):
                p.getAxis(ax).setPen(pg.mkPen(theme.BORDER))
                p.getAxis(ax).setTextPen(pg.mkPen(theme.TEXT_DIM))
            if row == len(groups) - 1:
                p.setLabel("bottom", "seconds ago")
            if self.plots:
                p.setXLink(self.plots[0])
            for key in keys:
                sig = self.hub.engine.signals.get(key)
                pen = pg.mkPen(theme.SERIES[color_i % len(theme.SERIES)], width=2)
                color_i += 1
                self.curves[key] = p.plot([], [], pen=pen, name=sig.name if sig else key)
            vl = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(theme.TEXT_DIM, style=Qt.DashLine))
            vl.hide()
            p.addItem(vl, ignoreBounds=True)
            self.vlines.append(vl)
            self.plots.append(p)

    def _mouse(self, evt):
        pos = evt[0]
        for p in self.plots:
            if p.sceneBoundingRect().contains(pos):
                x = p.vb.mapSceneToView(pos).x()
                self._cursor_x = x
                for vl in self.vlines:
                    vl.setPos(x)
                    vl.show()
                self._update_readout()
                return

    def _update_readout(self):
        x = self._cursor_x
        if x is None:
            return
        parts = [f"{-x:.1f} s ago" if x < 0 else "now"]
        for key, curve in self.curves.items():
            xs, ys = curve.getData()
            if xs is None or not len(xs):
                continue
            i = int(np.clip(np.searchsorted(xs, x), 0, len(xs) - 1))
            sig = self.hub.engine.signals.get(key)
            parts.append(f"{sig.name if sig else key}: {fmt_num(float(ys[i]))} {sig.units if sig else ''}")
        self.readout.setText("     ".join(parts))

    def refresh(self) -> None:
        e = self.hub.engine
        live = sum(1 for s in e.signals.values() if s.count)
        if live != self._known and not self.list.hasFocus():
            self._fill_list()
        keys = [k for k in self.selected if k in e.signals]
        self.switch.show_content(bool(keys))
        if not keys:
            return
        groups: dict[str, list[str]] = {}
        for k in keys:
            groups.setdefault(e.signals[k].units, []).append(k)
        glist = list(groups.items())
        if len(glist) > MAX_PLOTS:
            rest = [k for _, ks in glist[MAX_PLOTS - 1:] for k in ks]
            glist = glist[:MAX_PLOTS - 1] + [("mixed units", rest)]
        layout_key = tuple((u, tuple(ks)) for u, ks in glist)
        if layout_key != self._layout_key:
            self._layout_key = layout_key
            self._rebuild(glist)
        if self.pause.isChecked():
            return
        now = e.now
        window = self.window_combo.currentData()
        for key, curve in self.curves.items():
            sig = e.signals.get(key)
            if sig is None or not sig.ht:
                curve.setData([], [])
                continue
            t = np.fromiter(sig.ht, dtype=float, count=len(sig.ht)) - now
            v = np.fromiter(sig.hv, dtype=float, count=len(sig.hv))
            if window:
                i = int(np.searchsorted(t, -window))
                t, v = t[i:], v[i:]
            curve.setData(t, v)
        if window and self.plots:
            self.plots[0].setXRange(-window, 0, padding=0)
        if self._cursor_x is not None:
            self._update_readout()
