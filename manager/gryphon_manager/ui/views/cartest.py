from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QMarginsF, QUrl
from PySide6.QtGui import QDesktopServices, QDoubleValidator, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QStackedWidget, QWidget)

from ... import theme
from ...core.cartest import RESULT_WORD, STEPS, build_report_html, evaluate, overall, suggest
from ...core.paths import reports_dir
from ..hub import SOURCE_NAMES
from ..widgets import Card, View, button, hbox, label, restyle, vbox

MARK = {"pass": "✔", "fail": "✘", "skip": "–", "pending": "○"}


def save_pdf(html: str, path: str) -> None:
    doc = QTextDocument()
    doc.setHtml(html)
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)
    writer.setTitle("Gryphon car test report")
    doc.print_(writer)


class CarTestView(View):
    title = "Car test"
    subtitle = "A guided check of the car. Work down the steps, then save a pass/fail report."
    refresh_every = 4

    def __init__(self, hub):
        super().__init__(hub)
        self.results: dict = {}
        self.inputs: dict = {}
        self.widgets: dict = {}
        self.report_dir: Path | None = None
        self.log_path = ""
        self.started = False
        self.index = 0

        self.steps = QListWidget()
        self.steps.setFixedWidth(290)
        self.steps.setStyleSheet("QListWidget { font-size: 14px; } QListWidget::item { padding: 9px 8px; }")
        for i, st in enumerate(STEPS, 1):
            self.steps.addItem(QListWidgetItem(f"○   {i}. {st.title}"))
        self.steps.addItem(QListWidgetItem("➜   Save the report"))
        self.steps.currentRowChanged.connect(self._goto)

        self.step_title = label("", "h1")
        self.step_intro = label("", wrap=True)
        self.step_intro.setStyleSheet("font-size: 14px;")
        self.inputs_box = QWidget()
        self.inputs_lay = vbox(spacing=8)
        self.inputs_box.setLayout(self.inputs_lay)
        self.checks_card = Card("Automatic checks", "Worked out live from what the app can see")
        self.checks_grid = QGridLayout()
        self.checks_grid.setHorizontalSpacing(14)
        self.checks_grid.setColumnStretch(2, 1)
        self.checks_card.add(self.checks_grid)
        self.check_rows: list = []
        self.suggestion = label("", "dim")
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Notes for this step (optional)")
        self.notes.setFixedHeight(64)
        self.notes.textChanged.connect(self._notes_changed)
        self.btn_pass = button("Pass", lambda: self._mark("pass"), "primary")
        self.btn_fail = button("Fail", lambda: self._mark("fail"), "danger")
        self.btn_skip = button("Skip", lambda: self._mark("skip"))
        self.btn_back = button("Back", lambda: self.steps.setCurrentRow(max(0, self.index - 1)))
        self.result_label = label("", "h2")
        step_page = QWidget()
        step_page.setLayout(vbox(self.step_title, self.step_intro, self.inputs_box, self.checks_card,
                                 self.suggestion, None, self.notes,
                                 hbox(self.btn_back, None, self.result_label, self.btn_skip, self.btn_fail,
                                      self.btn_pass), spacing=12))

        self.sum_title = label("Save the report", "h1")
        self.verdict = QLabel("")
        self.verdict.setStyleSheet("font-size: 26px; font-weight: 700;")
        self.sum_list = label("", wrap=True)
        self.sum_list.setStyleSheet("font-size: 14px;")
        self.tester = QLineEdit(hub.settings["driver"])
        self.tester.setPlaceholderText("Your name")
        self.car = QLineEdit("F27")
        self.overall_notes = QPlainTextEdit()
        self.overall_notes.setPlaceholderText("Overall notes (optional)")
        self.overall_notes.setFixedHeight(70)
        self.saved_label = label("", "dim", wrap=True)
        self.btn_open = button("Open the report", self._open_report)
        self.btn_open.hide()
        form = QGridLayout()
        form.addWidget(label("Tester"), 0, 0)
        form.addWidget(self.tester, 0, 1)
        form.addWidget(label("Car"), 1, 0)
        form.addWidget(self.car, 1, 1)
        form.setColumnStretch(2, 1)
        sum_page = QWidget()
        sum_page.setLayout(vbox(self.sum_title, self.verdict, self.sum_list, form, self.overall_notes,
                                hbox(button("Save report (HTML and PDF)", self._save, "primary"), self.btn_open,
                                     button("Start a new test", self._restart), None),
                                self.saved_label, None, spacing=12))

        self.pages = QStackedWidget()
        self.pages.addWidget(step_page)
        self.pages.addWidget(sum_page)
        self.banner = label("", "dim", wrap=True)
        body = hbox(self.steps, (self.pages, 1), spacing=18)
        self.root.addWidget(self.banner)
        self.root.addLayout(body, 1)
        self.steps.setCurrentRow(0)

    # ---- state --------------------------------------------------------------

    def _res(self, key: str) -> dict:
        return self.results.setdefault(key, {"result": "pending", "notes": "", "checks": [], "inputs": {}})

    def _restart(self):
        self.results, self.inputs = {}, {}
        self.report_dir, self.log_path, self.started = None, "", False
        self.saved_label.setText("")
        self.btn_open.hide()
        self.overall_notes.clear()
        self._update_list()
        self.steps.setCurrentRow(0)
        self._goto(0)

    def _ensure_started(self):
        hub = self.hub
        if self.started:
            return
        self.started = True
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.report_dir = reports_dir() / f"{stamp}_car_test"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        if hub.connected and hub.kind != "replay" and not hub.recorder.active:
            hub.start_recording("car test log", root=self.report_dir)
            self.log_path = str(hub.recorder.dir)
            self._own_recording = True
        else:
            self._own_recording = False
            if hub.recorder.active:
                self.log_path = str(hub.recorder.dir)

    def _goto(self, row: int):
        if row < 0:
            return
        self.index = row
        if row >= len(STEPS):
            self.pages.setCurrentIndex(1)
            self._update_summary()
            return
        self.pages.setCurrentIndex(0)
        step = STEPS[row]
        self.step_title.setText(f"Step {row + 1} of {len(STEPS)}: {step.title}")
        self.step_intro.setText(step.intro)
        while self.inputs_lay.count():
            item = self.inputs_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()
        self.widgets = {}
        for key, text, kind in step.inputs:
            if kind == "tick":
                cb = QCheckBox(text)
                cb.setChecked(bool(self.inputs.get(key)))
                cb.toggled.connect(lambda v, k=key: self._input(k, v))
                cb.setStyleSheet("font-size: 14px;")
                self.inputs_lay.addWidget(cb)
            else:
                ed = QLineEdit(str(self.inputs.get(key, "") or ""))
                ed.setValidator(QDoubleValidator())
                ed.setMaximumWidth(140)
                ed.setPlaceholderText("type a number")
                ed.textChanged.connect(lambda v, k=key: self._input(k, v))
                lb = label(text)
                lb.setMinimumWidth(260)
                self.inputs_lay.addLayout(hbox(lb, ed, None))
        self.inputs_box.setVisible(bool(step.inputs))
        self.notes.blockSignals(True)
        self.notes.setPlainText(self._res(step.key)["notes"])
        self.notes.blockSignals(False)
        self.refresh()

    def _input(self, key, value):
        self.inputs[key] = value
        self._ensure_started()
        self.refresh()

    def _notes_changed(self):
        if self.index < len(STEPS):
            self._res(STEPS[self.index].key)["notes"] = self.notes.toPlainText().strip()

    def _mark(self, result: str):
        if self.index >= len(STEPS):
            return
        self._ensure_started()
        step = STEPS[self.index]
        r = self._res(step.key)
        r["result"] = result
        r["checks"] = evaluate(step.key, self.hub.engine, self.inputs)
        r["inputs"] = {k: self.inputs.get(k) for k, _, _ in step.inputs}
        r["time"] = datetime.now().strftime("%H:%M:%S")
        self._update_list()
        self.steps.setCurrentRow(self.index + 1)

    def _update_list(self):
        for i, st in enumerate(STEPS):
            res = self.results.get(st.key, {}).get("result", "pending")
            item = self.steps.item(i)
            item.setText(f"{MARK[res]}   {i + 1}. {st.title}")
            from PySide6.QtGui import QColor
            item.setForeground(QColor({"pass": theme.GREEN_BRIGHT, "fail": theme.RED_BRIGHT,
                                       "skip": theme.TEXT_DIM, "pending": theme.TEXT}[res]))

    def _update_summary(self):
        v = overall(self.results)
        self.verdict.setText(f"Result so far: {v}")
        self.verdict.setStyleSheet("font-size: 26px; font-weight: 700; color: %s;" %
                                   {"PASS": theme.GREEN_BRIGHT, "FAIL": theme.RED_BRIGHT}.get(v, theme.AMBER))
        lines = []
        for i, st in enumerate(STEPS, 1):
            res = self.results.get(st.key, {}).get("result", "pending")
            lines.append(f"{MARK[res]}  {i}. {st.title}: {RESULT_WORD[res]}")
        self.sum_list.setText("\n".join(lines))

    def _save(self):
        self._ensure_started()
        hub = self.hub
        if getattr(self, "_own_recording", False) and hub.recorder.active:
            hub.stop_recording()
        self.hub.settings["driver"] = self.tester.text().strip() or self.hub.settings["driver"]
        meta = {"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "tester": self.tester.text().strip(),
                "car": self.car.text().strip(), "source": SOURCE_NAMES.get(hub.kind, "not connected"),
                "config_version": hub.cfg.version, "notes": self.overall_notes.toPlainText().strip(),
                "log": Path(self.log_path).name + " (in this folder)" if self.log_path else "not recorded"}
        html = build_report_html(meta, self.results)
        hp = self.report_dir / "report.html"
        hp.write_text(html, encoding="utf-8")
        pdf_ok = True
        try:
            save_pdf(html, str(self.report_dir / "report.pdf"))
        except Exception as exc:
            pdf_ok = False
            self.hub.notice.emit("warn", f"Saved the HTML report, but the PDF failed: {exc}")
        self.saved_path = hp
        self.saved_label.setText(f"Saved to {self.report_dir}\nreport.html" + (", report.pdf" if pdf_ok else "") +
                                 (" and the raw log." if self.log_path else "."))
        self.btn_open.show()
        if pdf_ok:
            self.hub.notice.emit("info", f"Car test report saved: {overall(self.results)}")
        return self.report_dir

    def _open_report(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.saved_path)))

    def on_state(self):
        self.refresh()

    def refresh(self) -> None:
        hub = self.hub
        if hub.state != "connected":
            self.banner.setText("Not connected yet. Step 1 starts with the power off, so that's fine: "
                                "you'll connect at the end of step 1. No car? Use the Simulator to practise.")
        elif hub.kind in ("radio", "daq"):
            self.banner.setText("This test needs the CAN cable (or the simulator). You're connected to "
                                + SOURCE_NAMES[hub.kind] + ", so most checks can't run.")
        else:
            rec = " The raw log is being recorded for the report." if (self.started and hub.recorder.active) else ""
            self.banner.setText(f"Connected: {SOURCE_NAMES.get(hub.kind, hub.kind)}.{rec}")
        if self.index >= len(STEPS):
            self._update_summary()
            return
        step = STEPS[self.index]
        checks = evaluate(step.key, hub.engine, self.inputs)
        while len(self.check_rows) < len(checks):
            row = len(self.check_rows)
            cells = (QLabel(""), QLabel(""), QLabel(""))
            cells[0].setStyleSheet("font-size: 14px;")
            cells[2].setStyleSheet(f"color: {theme.TEXT_DIM};")
            cells[2].setWordWrap(True)
            for c, cell in enumerate(cells):
                self.checks_grid.addWidget(cell, row, c)
            self.check_rows.append(cells)
        for i, cells in enumerate(self.check_rows):
            if i < len(checks):
                c = checks[i]
                mark, col = ("✔  OK", theme.GREEN_BRIGHT) if c.ok is True else (
                    ("✘  Fail", theme.RED_BRIGHT) if c.ok is False else ("…  Waiting", theme.TEXT_DIM))
                cells[0].setText(c.label)
                cells[1].setText(mark)
                cells[1].setStyleSheet(f"color: {col}; font-weight: 600; font-size: 14px;")
                cells[2].setText(c.detail)
                for cell in cells:
                    cell.show()
            else:
                for cell in cells:
                    cell.hide()
        s = suggest(checks)
        self.suggestion.setText({"pass": "Everything checks out. Press Pass.",
                                 "fail": "At least one check is failing. Fix it and watch it turn green, or press Fail to record it.",
                                 "pending": "Some checks can't be decided yet. You decide: Pass, Fail or Skip."}[s])
        res = self.results.get(step.key, {}).get("result", "pending")
        self.result_label.setText("" if res == "pending" else f"Marked: {RESULT_WORD[res]}")
