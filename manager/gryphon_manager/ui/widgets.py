from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QStackedLayout, QVBoxLayout, QWidget)

from .. import theme


def restyle(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


def label(text: str = "", name: str = "", wrap: bool = False, tip: str = "") -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    if tip:
        lb.setToolTip(tip)
    return lb


def button(text: str, on_click=None, name: str = "", tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if tip:
        b.setToolTip(tip)
    if on_click:
        b.clicked.connect(lambda *_: on_click())
    b.setCursor(Qt.PointingHandCursor)
    return b


def hbox(*items, spacing: int = 8, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    _fill(lay, items)
    return lay


def vbox(*items, spacing: int = 8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    _fill(lay, items)
    return lay


def _fill(lay, items) -> None:
    for it in items:
        if it is None:
            lay.addStretch(1)
        elif isinstance(it, int):
            lay.addSpacing(it)
        elif isinstance(it, QWidget):
            lay.addWidget(it)
        elif isinstance(it, tuple):
            lay.addWidget(it[0], it[1])
        else:
            lay.addLayout(it)


class Dot(QWidget):
    def __init__(self, size: int = 12):
        super().__init__()
        self._color = QColor(theme.GREY)
        self.setFixedSize(size, size)

    def set_status(self, status: str) -> None:
        c = QColor(theme.STATUS.get(status, theme.GREY))
        if c != self._color:
            self._color = c
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(1, 1, self.width() - 2, self.height() - 2)


class Card(QFrame):
    def __init__(self, title: str = "", tip: str = ""):
        super().__init__()
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 12, 14, 12)
        self.lay.setSpacing(8)
        self.dot = None
        self.title = None
        if title:
            self.dot = Dot()
            self.title = label(title, "h2", tip=tip)
            self.lay.addLayout(hbox(self.dot, self.title, None))
            self.dot.hide()

    def set_status(self, status: str) -> None:
        if self.dot:
            self.dot.show()
            self.dot.set_status(status)

    def add(self, item, stretch: int = 0):
        if isinstance(item, QWidget):
            self.lay.addWidget(item, stretch)
        else:
            self.lay.addLayout(item, stretch)
        return item


class Tile(QFrame):
    """One big readable number."""

    def __init__(self, caption: str, units: str = "", decimals: int = 0, tip: str = "", size: int = 34,
                 min_width: int = 150):
        super().__init__()
        self.setObjectName("tile")
        self.decimals = decimals
        self.base_size = size
        self._state = ""
        self._text = None
        self._color = None
        self.setMinimumSize(min_width, 104)
        self.setMaximumHeight(int(size * 5.2))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if tip:
            self.setToolTip(tip)
        self.caption = label(caption.upper(), "caption")
        self.value = QLabel("--")
        self.value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.units = label(units, "dim")
        self.foot = label("", "dim")
        self.foot.setStyleSheet("font-size: 11px;")
        self.set_scale(1.0)
        lay = vbox(hbox(self.caption, None, self.units, spacing=6), (self.value, 1), self.foot, spacing=2,
                   margins=(14, 10, 14, 10))
        self.setLayout(lay)

    def set_scale(self, scale: float) -> None:
        self._css = f"font-size: {int(self.base_size * scale)}px; font-weight: 600;"
        self._color = None
        self.value.setStyleSheet(self._css)
        self.units.setStyleSheet(f"font-size: {int(12 * scale)}px; color: {theme.TEXT_DIM};")
        self.setMaximumHeight(int(self.base_size * scale * 5.2))

    def set(self, value, state: str = "", foot: str = "", stale: bool = False, units: str | None = None) -> None:
        if value is None:
            text = "--"
        elif isinstance(value, str):
            text = value
        else:
            text = f"{value:.{self.decimals}f}"
        if text != self._text:
            self._text = text
            self.value.setText(text)
        if units is not None and units != self.units.text():
            self.units.setText(units)
        color = theme.GREY if (stale or value is None) else theme.TEXT
        if color != self._color:
            self._color = color
            self.value.setStyleSheet(self._css + f" color: {color};")
        if foot != self.foot.text():
            self.foot.setText(foot)
        if state != self._state:
            self._state = state
            self.setProperty("state", state)
            restyle(self)


class Chip(QFrame):
    """Device health light: dot, name, one line of status, one line of detail."""

    def __init__(self, title: str, tip: str = ""):
        super().__init__()
        self.setObjectName("chip")
        if tip:
            self.setToolTip(tip)
        self.dot = Dot(14)
        self.title = label(title, "h2")
        self.line1 = label("Not connected")
        self.line2 = label("", "dim")
        self.line2.setStyleSheet("font-size: 11px;")
        self.line1.setWordWrap(True)
        self.setLayout(vbox(hbox(self.dot, self.title, None), self.line1, self.line2, spacing=3,
                            margins=(12, 10, 12, 10)))
        self.setMinimumHeight(86)

    def set(self, status: str, line1: str, line2: str = "") -> None:
        self.dot.set_status(status)
        if line1 != self.line1.text():
            self.line1.setText(line1)
        if line2 != self.line2.text():
            self.line2.setText(line2)


class EmptyState(QFrame):
    """Shown instead of a blank screen: says what to do next."""

    def __init__(self, title: str, text: str, action: str = "", on_action=None, action2: str = "",
                 on_action2=None):
        super().__init__()
        self.setObjectName("empty")
        self.title = label(title, "emptytitle")
        self.title.setAlignment(Qt.AlignCenter)
        self.text = label(text, "dim", wrap=True)
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setMaximumWidth(560)
        self.text.setStyleSheet("font-size: 14px;")
        btns = hbox(None, spacing=10)
        self.btn = self.btn2 = None
        if action:
            self.btn = button(action, on_action, "primary")
            btns.addWidget(self.btn)
        if action2:
            self.btn2 = button(action2, on_action2)
            btns.addWidget(self.btn2)
        btns.addStretch(1)
        inner = vbox(None, self.title, 6, hbox(None, self.text, None), 14, btns, None, spacing=4,
                     margins=(30, 30, 30, 30))
        self.setLayout(inner)

    def set_text(self, title: str, text: str) -> None:
        self.title.setText(title)
        self.text.setText(text)


class Switcher(QWidget):
    """Shows the empty state until there's something to show."""

    def __init__(self, empty: QWidget, content: QWidget):
        super().__init__()
        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(empty)
        self.stack.addWidget(content)

    def show_content(self, yes: bool) -> None:
        i = 1 if yes else 0
        if self.stack.currentIndex() != i:
            self.stack.setCurrentIndex(i)


class Pill(QLabel):
    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setObjectName("pill")
        self._state = None
        self.setAlignment(Qt.AlignCenter)

    def set(self, text: str, state: str = "grey") -> None:
        if text != self.text():
            self.setText(text)
        if state != self._state:
            self._state = state
            self.setProperty("state", state)
            restyle(self)


class View(QWidget):
    """Base class for the main screens."""

    title = ""
    subtitle = ""
    refresh_every = 1

    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(22, 18, 22, 18)
        self.root.setSpacing(12)
        self.header = hbox(spacing=10)
        self.h1 = label(self.title, "h1")
        self.sub = label(self.subtitle, "dim")
        self.header.addLayout(vbox(self.h1, self.sub, spacing=2))
        self.header.addStretch(1)
        self.root.addLayout(self.header)

    def refresh(self) -> None:
        pass

    def on_show(self) -> None:
        pass

    def on_state(self) -> None:
        pass

    def on_config(self) -> None:
        pass


class SimpleTableModel(QAbstractTableModel):
    """A table backed by a list of rows; views swap the rows and call refresh()."""

    def __init__(self, headers: list[str], tips: list[str] | None = None):
        super().__init__()
        self.headers = headers
        self.tips = tips or []
        self.rows: list = []
        self.cell = lambda row, col: ""
        self.fg = lambda row, col: None
        self.bg = lambda row, col: None
        self.tip = lambda row, col: None
        self.align = lambda col: None

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return self.headers[section]
            if role == Qt.ToolTipRole and section < len(self.tips):
                return self.tips[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        row, col = self.rows[index.row()], index.column()
        if role == Qt.DisplayRole:
            return self.cell(row, col)
        if role == Qt.ForegroundRole:
            c = self.fg(row, col)
            return QColor(c) if c else None
        if role == Qt.BackgroundRole:
            c = self.bg(row, col)
            return QColor(c) if c else None
        if role == Qt.ToolTipRole:
            return self.tip(row, col)
        if role == Qt.TextAlignmentRole:
            return self.align(col)
        return None

    def set_rows(self, rows: list) -> None:
        if len(rows) != len(self.rows):
            self.beginResetModel()
            self.rows = rows
            self.endResetModel()
        else:
            self.rows = rows
            if rows:
                self.dataChanged.emit(self.index(0, 0), self.index(len(rows) - 1, len(self.headers) - 1))


def setup_table(table, stretch_col: int | None = None, widths: dict | None = None) -> None:
    from PySide6.QtWidgets import QAbstractItemView, QHeaderView
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(28)
    table.setShowGrid(False)
    table.setWordWrap(False)
    hh = table.horizontalHeader()
    hh.setHighlightSections(False)
    hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    for col, w in (widths or {}).items():
        table.setColumnWidth(col, w)
    if stretch_col is not None:
        hh.setSectionResizeMode(stretch_col, QHeaderView.Stretch)


def age_text(age: float | None) -> str:
    if age is None:
        return "never seen"
    if age < 1.0:
        return "live"
    if age < 90:
        return f"last seen {age:.0f} s ago"
    return f"last seen {age / 60:.0f} min ago"


def fmt_num(v, decimals: int | None = None) -> str:
    if v is None:
        return "--"
    if decimals is not None:
        return f"{v:.{decimals}f}"
    a = abs(v)
    if v == int(v) and a < 1e7:
        return f"{int(v)}"
    if a >= 1000:
        return f"{v:.0f}"
    if a >= 10:
        return f"{v:.1f}"
    if a >= 1:
        return f"{v:.2f}"
    return f"{v:.3f}"
