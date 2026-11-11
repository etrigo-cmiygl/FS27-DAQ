from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QMenu, QTableView

from ... import theme
from ..widgets import EmptyState, SimpleTableModel, Switcher, View, button, fmt_num, hbox, label, setup_table, vbox


class SignalsView(View):
    title = "Signals"
    subtitle = "Every decoded value. Right-click a row to graph it or set an alarm on it."
    refresh_every = 4

    def __init__(self, hub):
        super().__init__(hub)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name, unit or ID (e.g. temp, bar, 0x600)")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(380)
        self.search.setMaximumWidth(460)
        self.only_live = QCheckBox("Only signals with data")
        self.only_live.setChecked(True)
        self.only_live.setToolTip("Untick to see every signal in the config, even ones not arriving yet")
        self.count = label("", "dim")
        self.model = SimpleTableModel(
            ["Name", "Value", "Units", "Min", "Max", "Rate", "Source", "Note"],
            ["", "Latest value", "", "Lowest since connecting", "Highest since connecting",
             "Updates a second", "CAN ID or where it came from", "Anything to watch out for"])
        self.model.cell = self._cell
        self.model.fg = self._fg
        self.model.tip = lambda s, c: s.note if s.note else None
        self.model.align = lambda c: int(Qt.AlignRight | Qt.AlignVCenter) if c in (1, 3, 4, 5) else None
        self.table = QTableView()
        self.table.setModel(self.model)
        setup_table(self.table, 7, {0: 250, 1: 110, 2: 70, 3: 90, 4: 90, 5: 80, 6: 120})
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.empty = EmptyState("No signals yet", "Connect to the car, the receiver or the simulator and the "
                                "decoded values will list here.", "Try it in the simulator",
                                lambda: self.window_ref.connect_simulator())
        self.switch = Switcher(self.empty, self.table)
        self.root.addLayout(hbox(self.search, self.only_live, None, self.count,
                                 button("Reset min/max", self._reset, tip="Start min and max again from now")))
        self.root.addWidget(self.switch, 1)
        self.search.textChanged.connect(lambda *_: self.refresh())
        self.only_live.toggled.connect(lambda *_: self.refresh())

    def _cell(self, s, col):
        if col == 0:
            return s.name
        if col == 1:
            return fmt_num(s.value)
        if col == 2:
            return s.units
        if col == 3:
            return fmt_num(s.vmin)
        if col == 4:
            return fmt_num(s.vmax)
        if col == 5:
            stale = self.hub.engine.now - s.last_ts > 3.0
            return "stale" if (stale and s.count) else (f"{s.rate:.1f} Hz" if s.count else "--")
        if col == 6:
            return s.source
        return s.note

    def _fg(self, s, col):
        if s.count and self.hub.engine.now - s.last_ts > 3.0:
            return theme.GREY
        if col == 1 and s.out_of_range:
            return theme.AMBER
        if col == 7:
            return theme.AMBER
        return None

    def _reset(self):
        for s in self.hub.engine.signals.values():
            s.reset_stats()

    def _menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        sig = self.model.rows[idx.row()]
        m = QMenu(self)
        m.addAction("Add to Graphs", lambda: self._graph(sig))
        m.addAction("Make an alarm for this...", lambda: self._alarm(sig))
        m.addSeparator()
        m.addAction("Copy value", lambda: QApplication.clipboard().setText(f"{sig.name}: {fmt_num(sig.value)} {sig.units}"))
        m.addAction("Reset this min/max", sig.reset_stats)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _graph(self, sig):
        self.window_ref.views["graphs"].add_signal(sig.key)
        self.hub.navigate.emit("graphs")

    def _alarm(self, sig):
        self.hub.navigate.emit("alarms")
        self.window_ref.views["alarms"].new_rule(sig.key)

    def refresh(self) -> None:
        e = self.hub.engine
        text = self.search.text().strip().lower()
        live = self.only_live.isChecked()
        rows = []
        for s in e.signals.values():
            if live and not s.count:
                continue
            if text and text not in f"{s.name} {s.key} {s.units} {s.source}".lower():
                continue
            rows.append(s)
        any_data = any(s.count for s in e.signals.values())
        self.switch.show_content(any_data or not live)
        self.model.set_rows(rows)
        self.count.setText(f"{len(rows)} signals")
