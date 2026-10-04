"""Bosh sahifa: eng ko'p ishlatiladigan amallar, asosiy raqamlar, diagramma va so'nggi amallar."""

from datetime import date
from enum import Enum

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ..analytics import Analytics
from ..config import CURRENCY
from ..formatting import MONTH_NAMES, fmt_compact, fmt_long_date, fmt_qty
from ..i18n import tr
from ..models import MovementKind, Period
from ..reports import Reports
from ..warehouse import Warehouse
from .chart import BarChart
from .icons import Glyph, icon_label
from .labels import LABELS
from .widgets import Column, ColumnKind, DataTable, StatCard, card, label, section_header

RECENT_LIMIT = 10
CHART_MONTHS = 6
TILE_HEIGHT = 72
CHART_MIN_HEIGHT = 150  # so'nggi amallar jadvaliga ham joy qolishi uchun
TILE_ICON_SIZE = 40
KIND_COLUMN = 1
# So'nggi amallar jadvalidagi «Turi» yorlig'i ranglari (palitradagi rang nomi).
KIND_TONES = {LABELS[MovementKind.IN].title: "good", LABELS[MovementKind.OUT].title: "tile_out"}


class Destination(Enum):
    """Bosh sahifadagi kartochka bosilganda ochiladigan bo'lim."""

    RECEIPTS = "receipts"
    ISSUES = "issues"
    PRODUCTS = "products"
    REPORTS = "reports"


class DashboardPage(QWidget):
    """Yangi yozuv yoki boshqa bo'lim so'ralganda signal chiqaradi; ularni asosiy oyna bajaradi."""

    movement_requested = Signal(MovementKind)
    product_requested = Signal()
    page_requested = Signal(Destination)

    def __init__(self, warehouse: Warehouse, reports: Reports, analytics: Analytics):
        super().__init__()
        self.setObjectName("page")
        self._warehouse = warehouse
        self._reports = reports
        self._analytics = analytics

        self._today = label("", "dateText")
        self._stock_value = self._stat(tr("Ombor qiymati"), Glyph.MONEY, "Accent", Destination.PRODUCTS)
        self._month_in = self._stat(tr("Bu oy kirim"), Glyph.ARROW_DOWN, "Good", Destination.RECEIPTS)
        self._month_out = self._stat(tr("Bu oy chiqim"), Glyph.ARROW_UP, "Out", Destination.ISSUES)
        self._month_profit = self._stat(tr("Bu oy sotuvdan foyda"), Glyph.CHART, "Good", Destination.REPORTS)
        self._chart = BarChart([LABELS[MovementKind.IN].title, LABELS[MovementKind.OUT].title], unit=CURRENCY)
        self._chart.setMinimumHeight(CHART_MIN_HEIGHT)
        self._chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._recent = DataTable(
            (
                Column(tr("Sana"), ColumnKind.DATE),
                Column(tr("Turi")),
                Column(tr("Mahsulot")),
                Column(tr("Miqdor"), ColumnKind.QUANTITY),
                Column(tr("Birlik")),
                Column(tr("Summa"), ColumnKind.MONEY),
                Column(tr("Kim")),
            )
        )
        self._recent.setObjectName("flatTable")
        self._recent.set_badges(KIND_COLUMN, KIND_TONES)

        cards = QHBoxLayout()
        cards.setSpacing(14)
        for stat in (self._stock_value, self._month_in, self._month_out, self._month_profit):
            cards.addWidget(stat, stretch=1)

        chart_title = tr("Oxirgi {0} oy: kirim va chiqim, {1}").format(CHART_MONTHS, CURRENCY)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 16)
        layout.setSpacing(14)
        layout.addLayout(self._header())
        layout.addLayout(self._tiles())
        layout.addLayout(cards)
        layout.addWidget(card(section_header(Glyph.CHART, chart_title), self._chart), stretch=2)
        layout.addWidget(card(section_header(Glyph.CLOCK, tr("So'nggi amallar")), self._recent), stretch=3)

    def refresh(self) -> None:
        today = date.today()
        month = Period.month_of(today)
        totals = self._reports.totals(month)
        profit = self._analytics.summary(month)
        recent = self._warehouse.movements(limit=RECENT_LIMIT)

        self._today.setText(fmt_long_date(today))
        self._stock_value.set_value(fmt_compact(self._reports.stock_value()), CURRENCY)
        self._month_in.set_value(
            fmt_compact(totals.amount_in), tr("{0}  ·  {1} ta kirim").format(CURRENCY, totals.count_in)
        )
        self._month_out.set_value(
            fmt_compact(totals.amount_out), tr("{0}  ·  {1} ta chiqim").format(CURRENCY, totals.count_out)
        )
        self._month_profit.set_value(
            fmt_compact(profit.profit),
            tr("{0}  ·  rentabellik {1}%").format(CURRENCY, fmt_qty(round(profit.margin * 100, 1))),
        )
        self._chart.set_data(
            [
                (MONTH_NAMES[m.start.month - 1], (m.amount_in, m.amount_out))
                for m in self._reports.monthly(CHART_MONTHS, today)
            ]
        )
        self._recent.set_rows(
            [(m.date, LABELS[m.kind].title, m.product_name, m.quantity, m.unit, m.amount, m.person) for m in recent]
        )

    def _stat(self, title: str, glyph: str, tone: str, destination: Destination) -> StatCard:
        """Bosilganda tegishli bo'limni ochadigan ko'rsatkich kartochkasi."""
        stat = StatCard(title, glyph, tone, clickable=True)
        stat.clicked.connect(lambda: self.page_requested.emit(destination))
        return stat

    def _header(self) -> QHBoxLayout:
        subtitle = QHBoxLayout()
        subtitle.setSpacing(8)
        subtitle.addWidget(icon_label(Glyph.HOME))
        subtitle.addWidget(label(tr("Umumiy ko'rsatkichlar"), "subtitle"))
        subtitle.addStretch()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(tr("Bosh sahifa"), "pageTitle"))
        titles.addLayout(subtitle)

        header = QHBoxLayout()
        header.addLayout(titles)
        header.addStretch()
        header.addWidget(icon_label(Glyph.CALENDAR))
        header.addWidget(self._today)
        return header

    def _tiles(self) -> QHBoxLayout:
        """Uchta katta tugma: kundalik ishning deyarli hammasi shulardan boshlanadi."""
        receipt = _tile(LABELS[MovementKind.IN].title, Glyph.ADD, "tileIn", tr("Yangi kirim (F2)"))
        receipt.clicked.connect(lambda: self.movement_requested.emit(MovementKind.IN))
        issue = _tile(LABELS[MovementKind.OUT].title, Glyph.REMOVE, "tileOut", tr("Yangi chiqim (F3)"))
        issue.clicked.connect(lambda: self.movement_requested.emit(MovementKind.OUT))
        product = _tile(tr("Yangi mahsulot"), Glyph.GRID, "tile", tr("Yangi mahsulot (F4)"))
        product.clicked.connect(self.product_requested.emit)
        tiles = QHBoxLayout()
        tiles.setSpacing(14)
        for tile in (receipt, issue, product):
            tiles.addWidget(tile)
        return tiles


def _tile(title: str, glyph: str, role: str, tooltip: str) -> QPushButton:
    """Katta tugma: belgi, nom va o'ngda strelka. `role` — 'tileIn', 'tileOut' yoki 'tile' (rangsiz)."""
    is_neutral = role == "tile"
    tile = QPushButton()
    tile.setProperty("role", role)
    tile.setToolTip(tooltip)
    tile.setCursor(Qt.CursorShape.PointingHandCursor)
    tile.setFixedHeight(TILE_HEIGHT)

    icon = icon_label(glyph, "badgeAccent" if is_neutral else "tileIcon")
    icon.setFixedSize(TILE_ICON_SIZE, TILE_ICON_SIZE)
    name = label(title, "tileTitleNeutral" if is_neutral else "tileTitle")
    name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    layout = QHBoxLayout(tile)
    layout.setContentsMargins(22, 0, 22, 0)
    layout.setSpacing(16)
    layout.addWidget(icon)
    layout.addWidget(name)
    layout.addStretch()
    layout.addWidget(icon_label(Glyph.CHEVRON, "chevron" if is_neutral else "tileChevron"))
    return tile
