from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QLineEdit,
                               QMessageBox, QPlainTextEdit, QSlider, QTableView, QTabWidget, QWidget)

from ... import theme
from ...core.laps import fmt_lap
from ...core.paths import sessions_dir, user_home
from ...core.recorder import analyse, export_csv, list_sessions, load_alarms, update_meta
from ..main_window import fmt_clock
from ..widgets import (Card, EmptyState, SimpleTableModel, Switcher, View, button, fmt_num, hbox, label,
                       setup_table, vbox)


class DetailsDialog(QDialog):
    def __init__(self, parent, meta: dict):
        super().__init__(parent)
        self.setWindowTitle("Recording details")
        self.setMinimumWidth(420)
        self.name = QLineEdit(meta.get("name", ""))
        self.driver = QLineEdit(meta.get("driver", ""))
        self.notes = QPlainTextEdit(meta.get("notes", ""))
        self.notes.setFixedHeight(90)
        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Driver", self.driver)
        form.addRow("Notes", self.notes)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self.setLayout(vbox(form, box, margins=(18, 18, 18, 18)))

    def values(self) -> dict:
        return {"name": self.name.text().strip(), "driver": self.driver.text().strip(),
                "notes": self.notes.toPlainText().strip()}


class SessionsView(View):
    title = "Sessions"
    subtitle = "Your recordings. Replay one through every view, compare two, or export to CSV."
    refresh_every = 4

    def __init__(self, hub):
        super().__init__(hub)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.cache: dict[str, dict] = {}
        self.jobs: dict[str, object] = {}
        self.sessions: list[dict] = []
        self.replay_alarms: list = []

        self.model = SimpleTableModel(["Name", "Date", "Length", "Driver", "Source", "Notes"])
        self.model.cell = self._cell
        self.table = QTableView()
        self.table.setModel(self.model)
        setup_table(self.table, 5, {0: 230, 1: 150, 2: 80, 3: 110, 4: 150})
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._selected())
        self.table.doubleClicked.connect(lambda *_: self._replay())
        self.empty = EmptyState("No recordings yet",
                                "Connect to the car, the receiver or the simulator, then press Record in the top "
                                "bar (or Space). Recordings are kept in Documents / Gryphon Manager / sessions.",
                                "Try it in the simulator", lambda: self.window_ref.connect_simulator(),
                                "Open a log file...", self._open_file)
        self.switch = Switcher(self.empty, self.table)

        self.btn_replay = button("Replay", self._replay, "primary", "Play this recording back through every view")
        buttons = hbox(self.btn_replay,
                       button("Export CSV", self._export, tip="Decoded values, 10 rows a second, for Excel or MATLAB"),
                       button("Edit details", self._edit), button("Open folder", self._folder),
                       button("Delete", self._delete), None,
                       button("Open a log file...", self._open_file, tip="Replay a .blf or .asc from somewhere else"))

        self.bar = QFrame()
        self.bar.setObjectName("card")
        self.play_btn = button("Pause", self._play_pause)
        self.speed = QComboBox()
        for sp in (0.5, 1, 2, 4, 8):
            self.speed.addItem(f"{sp:g}x", float(sp))
        self.speed.setCurrentIndex(1)
        self.speed.currentIndexChanged.connect(self._speed)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderReleased.connect(self._seek)
        self.pos_label = label("00:00 / 00:00")
        self.bar.setLayout(hbox(label("Replaying", "h2"), self.play_btn, self.speed, (self.slider, 1),
                                self.pos_label,
                                button("Jump to next alarm", self._jump_alarm,
                                       tip="Skip to two seconds before the next alarm in this recording"),
                                button("Stop replay", self.hub.disconnect_source), margins=(14, 10, 14, 10)))
        self.bar.hide()

        self.tabs = QTabWidget()
        self.stats_model = SimpleTableModel(["Signal", "Min", "Max", "Average", "Units", "Samples"])
        self.stats_model.cell = lambda r, c: r[c]
        self.stats_model.align = lambda c: int(Qt.AlignRight | Qt.AlignVCenter) if c in (1, 2, 3, 5) else None
        self.stats = QTableView()
        self.stats.setModel(self.stats_model)
        setup_table(self.stats, 0, {1: 100, 2: 100, 3: 100, 4: 80, 5: 90})
        self.stats_hint = label("Click a recording to see its min, max and average values.", "dim")
        sw = QWidget()
        sw.setLayout(vbox(self.stats_hint, (self.stats, 1), margins=(10, 10, 10, 10)))
        self.tabs.addTab(sw, "Summary")

        self.cmp_signal = QComboBox()
        self.cmp_signal.setMinimumWidth(220)
        self.cmp_other = QComboBox()
        self.cmp_other.setMinimumWidth(220)
        self.cmp_lap_a = QComboBox()
        self.cmp_lap_b = QComboBox()
        for c in (self.cmp_signal, self.cmp_other, self.cmp_lap_a, self.cmp_lap_b):
            c.currentIndexChanged.connect(lambda *_: self._draw_compare())
        self.cmp_other.currentIndexChanged.connect(lambda *_: self._other_changed())
        self.cmp_plot = pg.PlotWidget()
        self.cmp_plot.setBackground(theme.PANEL)
        self.cmp_plot.showGrid(x=True, y=True, alpha=0.15)
        self.cmp_plot.addLegend(offset=(8, 4), labelTextColor=theme.TEXT)
        self.cmp_plot.setLabel("bottom", "seconds from the start")
        self.cmp_hint = label("", "dim")
        cw = QWidget()
        cw.setLayout(vbox(hbox(label("Signal"), self.cmp_signal, label("This recording"), self.cmp_lap_a,
                               label("compared with"), self.cmp_other, self.cmp_lap_b, None),
                          (self.cmp_plot, 1), self.cmp_hint, margins=(10, 10, 10, 10)))
        self.tabs.addTab(cw, "Compare")

        self.root.addWidget(self.bar)
        self.root.addWidget(self.switch, 3)
        self.root.addLayout(buttons)
        self.root.addWidget(self.tabs, 4)
        hub.replay_finished.connect(lambda: self.play_btn.setText("Play again"))

    # ---- table --------------------------------------------------------------

    @staticmethod
    def _cell(m, col):
        if col == 0:
            return m.get("name") or m.get("folder", "")
        if col == 1:
            return str(m.get("date", "")).replace("T", "  ")
        if col == 2:
            return fmt_clock(m.get("duration_s", 0))
        if col == 3:
            return m.get("driver", "")
        if col == 4:
            return m.get("source", "")
        return (m.get("notes", "") or "").replace("\n", " ")

    def reload(self):
        keep = self._current()
        self.sessions = list_sessions()
        self.model.set_rows(self.sessions)
        self.switch.show_content(bool(self.sessions))
        self.cmp_other.blockSignals(True)
        self.cmp_other.clear()
        self.cmp_other.addItem("(nothing)", "")
        for m in self.sessions:
            self.cmp_other.addItem(f"{m.get('name', m['folder'])}  {str(m.get('date', ''))[:16].replace('T', ' ')}",
                                   m["path"])
        self.cmp_other.blockSignals(False)
        if self.sessions:
            row = next((i for i, m in enumerate(self.sessions) if keep and m["path"] == keep["path"]), 0)
            self.table.selectRow(row)

    def on_show(self):
        self.reload()

    def _current(self) -> dict | None:
        idx = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if idx and idx[0].row() < len(self.sessions):
            return self.sessions[idx[0].row()]
        return None

    def _need(self) -> dict | None:
        m = self._current()
        if m is None:
            self.hub.notice.emit("info", "Click a recording in the list first.")
        return m

    # ---- analysis -----------------------------------------------------------

    def _analysis(self, path: str, gate=None):
        if path in self.cache:
            return self.cache[path]
        if path not in self.jobs:
            cfg, settings = self.hub.cfg.copy(), dict(self.hub.settings.data)
            self.jobs[path] = self.pool.submit(analyse, path, cfg, settings, tuple(gate) if gate else None)
        return None

    def _selected(self):
        m = self._current()
        if m is None:
            return
        self._analysis(m["path"], m.get("gate"))
        self._show_stats()

    def _show_stats(self):
        m = self._current()
        if m is None:
            return
        a = self.cache.get(m["path"])
        if a is None:
            self.stats_hint.setText("Working out the summary...")
            self.stats_model.set_rows([])
            return
        if isinstance(a, Exception):
            self.stats_hint.setText(f"Couldn't read this recording: {a}")
            return
        rows = []
        for key in sorted(a["stats"], key=lambda k: a["names"][k][0].lower()):
            s = a["stats"][key]
            name, units = a["names"][key]
            rows.append((name, fmt_num(s["min"]), fmt_num(s["max"]), fmt_num(s["avg"]), units, str(s["samples"])))
        self.stats_model.set_rows(rows)
        laps = a.get("laps") or []
        lap_text = ""
        if laps:
            best = min(e - s for _, s, e in laps)
            lap_text = f"   {len(laps)} laps, best {fmt_lap(best)}"
        self.stats_hint.setText(f"{len(rows)} signals over {fmt_clock(a['duration'])}.{lap_text}")
        self.cmp_signal.blockSignals(True)
        cur = self.cmp_signal.currentData()
        self.cmp_signal.clear()
        for key in sorted(a["series"], key=lambda k: a["names"][k][0].lower()):
            self.cmp_signal.addItem(a["names"][key][0], key)
        i = self.cmp_signal.findData(cur if cur else "rpm")
        self.cmp_signal.setCurrentIndex(max(0, i))
        self.cmp_signal.blockSignals(False)
        self._fill_laps(self.cmp_lap_a, a)
        self._draw_compare()

    @staticmethod
    def _fill_laps(combo, a):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("whole recording", None)
        for n, s, e in (a.get("laps") or []) if isinstance(a, dict) else []:
            combo.addItem(f"lap {n}  ({fmt_lap(e - s)})", (s, e))
        combo.blockSignals(False)

    def _other_changed(self):
        path = self.cmp_other.currentData()
        if path:
            meta = next((m for m in self.sessions if m["path"] == path), {})
            a = self._analysis(path, meta.get("gate"))
            self._fill_laps(self.cmp_lap_b, a)
        self._draw_compare()

    def _draw_compare(self):
        self.cmp_plot.clear()
        m = self._current()
        key = self.cmp_signal.currentData()
        if m is None or not key:
            return
        a = self.cache.get(m["path"])
        if not isinstance(a, dict):
            return
        units = a["names"].get(key, ("", ""))[1]
        self.cmp_plot.setLabel("left", units or "value")

        def cut(an, window):
            ts, vs = an["series"].get(key, ([], []))
            if window:
                s, e = window
                pairs = [(t - s, v) for t, v in zip(ts, vs) if s <= t <= e]
                return [p[0] for p in pairs], [p[1] for p in pairs]
            return ts, vs

        ts, vs = cut(a, self.cmp_lap_a.currentData())
        self.cmp_plot.plot(ts, vs, pen=pg.mkPen(theme.GREEN_BRIGHT, width=2), name=m.get("name", "this recording"))
        other = self.cmp_other.currentData()
        hint = "Pick a second recording to overlay it. If a start/finish line was set, you can pick single laps."
        if other:
            b = self.cache.get(other)
            if isinstance(b, dict):
                if key in b["series"]:
                    ts2, vs2 = cut(b, self.cmp_lap_b.currentData())
                    self.cmp_plot.plot(ts2, vs2, pen=pg.mkPen(theme.RED_BRIGHT, width=2),
                                       name=self.cmp_other.currentText())
                    hint = "Green is the selected recording, red is the one it's compared with."
                else:
                    hint = "The other recording doesn't have that signal."
            else:
                hint = "Reading the other recording..."
        self.cmp_hint.setText(hint)

    # ---- actions ------------------------------------------------------------

    def _replay(self, path: str | None = None):
        if not path:
            m = self._need()
            if m is None:
                return
            path = m["path"]
        self.replay_alarms = load_alarms(path) if Path(path).is_dir() else []
        self.hub.connect_source("replay", path=path, speed=float(self.speed.currentData()))
        self.play_btn.setText("Pause")
        self.hub.notice.emit("info", "Replaying. Open any view (Garage, Graphs, Telemetry...) to watch it.")

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open a CAN log", str(user_home()),
                                              "CAN logs (*.blf *.asc)")
        if path:
            self._replay(path)

    def _play_pause(self):
        src = self.hub.source
        if self.hub.kind != "replay" or src is None:
            return
        if src.finished:
            src.seek(0.0)
            src.paused = False
            self.play_btn.setText("Pause")
            return
        src.paused = not src.paused
        self.play_btn.setText("Play" if src.paused else "Pause")

    def _speed(self):
        src = self.hub.source
        if self.hub.kind == "replay" and src is not None:
            src.speed = float(self.speed.currentData())

    def _seek(self):
        src = self.hub.source
        if self.hub.kind == "replay" and src is not None:
            src.seek(src.duration * self.slider.value() / 1000.0)
            self.play_btn.setText("Play" if src.paused else "Pause")

    def _jump_alarm(self):
        src = self.hub.source
        if self.hub.kind != "replay" or src is None:
            return
        pos = src.position
        nxt = [a["ts"] - src.t0 for a in self.replay_alarms if a.get("raised") and a["ts"] - src.t0 > pos + 2.5]
        if not nxt:
            self.hub.notice.emit("info", "No more alarms in this recording.")
            return
        src.seek(max(0.0, min(nxt) - 2.0))

    def _export(self):
        m = self._need()
        if m is None:
            return
        default = str(Path(m["path"]) / "decoded.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Export decoded values", default, "CSV (*.csv)")
        if not path:
            return
        try:
            rows = export_csv(m["path"], self.hub.cfg, path, settings=self.hub.settings.data)
            self.hub.notice.emit("info", f"Exported {rows} rows to {path}")
        except Exception as exc:
            self.hub.notice.emit("error", f"Couldn't export: {exc}")

    def _edit(self):
        m = self._need()
        if m is None:
            return
        dlg = DetailsDialog(self, m)
        if dlg.exec() == QDialog.Accepted:
            update_meta(m["path"], dlg.values())
            self.reload()

    def _folder(self):
        m = self._current()
        QDesktopServices.openUrl(QUrl.fromLocalFile(m["path"] if m else str(sessions_dir())))

    def _delete(self):
        m = self._need()
        if m is None:
            return
        if self.hub.kind == "replay":
            self.hub.disconnect_source()
        ok = QMessageBox.question(self, "Delete recording",
                                  f"Delete '{m.get('name', m['folder'])}' for good? This can't be undone.",
                                  QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ok == QMessageBox.Yes:
            shutil.rmtree(m["path"], ignore_errors=True)
            self.cache.pop(m["path"], None)
            self.reload()

    def on_state(self):
        self.bar.setVisible(self.hub.kind == "replay" and self.hub.state != "disconnected")
        if not self.hub.recorder.active and self.isVisible():
            self.reload()

    def refresh(self) -> None:
        done = [p for p, f in self.jobs.items() if f.done()]
        for p in done:
            f = self.jobs.pop(p)
            try:
                self.cache[p] = f.result()
            except Exception as exc:
                self.cache[p] = exc
        if done:
            self._show_stats()
            if self.cmp_other.currentData() in done:
                self._fill_laps(self.cmp_lap_b, self.cache.get(self.cmp_other.currentData()))
                self._draw_compare()
        src = self.hub.source
        if self.hub.kind == "replay" and src is not None and src.duration:
            if not self.slider.isSliderDown():
                self.slider.setValue(int(1000 * src.position / src.duration))
            self.pos_label.setText(f"{fmt_clock(src.position)} / {fmt_clock(src.duration)}")
