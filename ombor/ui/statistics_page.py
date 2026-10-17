"""Umumiy statistika: qaysi mahsulot ko'p kirdi va chiqdi, qaysi oyda narx oshdi yoki tushdi, obyektlar rasxodi."""

from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..config import CURRENCY
from ..formatting import MONTH_NAMES, fmt_money, fmt_period, fmt_qty
from ..i18n import tr
from ..models import Granularity, MovementKind
from ..reports import Reports
from ..statistics import ProductRank, Statistics
from . import theme
from .chart import BarChart, RankingChart
from .icons import Glyph
from .labels import LABELS
from .widgets import (
    Column,
    ColumnKind,
    DataTable,
    PeriodNavigator,
    StatCard,
    button,
    card,
    export_to_excel,
    page_header,
    section_header,
)

CHART_HEIGHT = 260
PRICE_TABLE_HEIGHT = 330
# Diagrammada tanlangan davr qanday bo'laklarga bo'linadi: yil — oylar, oy va hafta — kunlar.
_BREAKDOWN = {
    Granularity.YEAR: Granularity.MONTH,
    Granularity.MONTH: Granularity.DAY,
    Granularity.WEEK: Granularity.DAY,
}
_PRICE_COLUMNS = (
    Column(tr("Oy")),
    Column(tr("Mahsulot"), style="strong"),
    Column(tr("Birlik")),
    Column(tr("Oldingi xarid oyi")),
    Column(tr("Oldingi narx"), ColumnKind.MONEY),
    Column(tr("Yangi narx"), ColumnKind.MONEY, "strong"),
    Column(tr("Farq (1 birlik)")),
    Column(tr("O'zgarish, %"), style="strong"),
)


def _panel(glyph: str, title: str, body: QWidget) -> QFrame:
    """Sarlavhali kartochka; mazmuni tepaga yopishadi (yonidagi kartochka balandroq bo'lsa ham)."""
    frame = card(section_header(glyph, title), body)
    frame.layout().addStretch()
    return frame


def fmt_percent(value: float) -> str:
    return f"{value:+.1f} %".replace(".", ",")


def _rank_rows(ranks: list[ProductRank]) -> list[tuple[str, float, str]]:
    return [
        (
            rank.name,
            rank.amount,
            tr("{0} {1}  ·  {2} {3}  ·  {4} ta yozuv").format(
                fmt_qty(rank.quantity), rank.unit, fmt_money(rank.amount), CURRENCY, rank.operations
            ),
        )
        for rank in ranks
    ]


class StatisticsPage(QWidget):
    def __init__(self, statistics: Statistics, reports: Reports):
        super().__init__()
        self.setObjectName("page")
        self._statistics = statistics
        self._reports = reports

        self._period = PeriodNavigator(Granularity.YEAR)
        self._period.changed.connect(self.refresh)
        self._purchased = StatCard(tr("Sotib olindi"), Glyph.RECEIPT, "Good")
        self._consumed = StatCard(tr("Chiqim (rasxod)"), Glyph.ISSUE, "Out")
        self._sites_total = StatCard(tr("Obyektlarga rasxod"), Glyph.PIN, "Violet")
        self._prices = StatCard(tr("Narx o'zgarishi"), Glyph.TAG, "Warning")

        colors = theme.palette()
        self._chart = BarChart([LABELS[MovementKind.IN].title, LABELS[MovementKind.OUT].title], unit=CURRENCY)
        self._chart.setMinimumHeight(CHART_HEIGHT)
        self._top_out = RankingChart(colors.tile_out, tr("Bu davrda chiqim bo'lmagan"))
        self._top_in = RankingChart(colors.good, tr("Bu davrda xarid bo'lmagan"))
        self._sites = RankingChart(colors.violet, tr("Bu davrda obyektlarga rasxod bo'lmagan"))
        self._price_table = DataTable(_PRICE_COLUMNS)
        self._price_table.setObjectName("flatTable")
        self._price_table.setMinimumHeight(PRICE_TABLE_HEIGHT)
        self._price_table.empty_text = tr("Bu davrda xarid narxi o'zgarmagan")
        price_excel = button(tr("Excelga chiqarish"), "excel", Glyph.EXPORT)
        price_title = tr("Narx o'zgarishi")
        price_excel.clicked.connect(
            lambda: export_to_excel(self, self._price_table, f"{price_title} ({self._period.title()})")
        )

        header, _tools = page_header(
            Glyph.CHART,
            tr("Statistika"),
            tr("Qaysi mahsulot ko'p kirdi va chiqdi, narx qachon o'zgardi, obyektlarga qancha ketdi"),
        )
        cards = QHBoxLayout()
        cards.setSpacing(14)
        for stat in (self._purchased, self._consumed, self._sites_total, self._prices):
            cards.addWidget(stat)

        price_header = QHBoxLayout()
        price_header.addWidget(section_header(Glyph.TAG, tr("Qaysi oyda narx oshdi yoki tushdi")), stretch=1)
        price_header.addWidget(price_excel)
        price_section = QWidget()
        price_layout = QVBoxLayout(price_section)
        price_layout.setContentsMargins(0, 0, 0, 0)
        price_layout.addLayout(price_header)
        price_layout.addWidget(self._price_table)

        grid = QGridLayout()
        grid.setSpacing(14)
        grid.addWidget(_panel(Glyph.CHART, tr("Kirim va chiqim dinamikasi"), self._chart), 0, 0, 1, 2)
        grid.addWidget(_panel(Glyph.ISSUE, tr("Eng ko'p chiqqan mahsulotlar"), self._top_out), 1, 0)
        grid.addWidget(_panel(Glyph.RECEIPT, tr("Eng ko'p kirgan (sotib olingan) mahsulotlar"), self._top_in), 1, 1)
        grid.addWidget(_panel(Glyph.PIN, tr("Obyektlar bo'yicha rasxod"), self._sites), 2, 0, 1, 2)
        grid.addWidget(card(price_section), 3, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        content = QWidget()
        content.setObjectName("page")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)
        layout.addLayout(header)
        layout.addWidget(self._period)
        layout.addLayout(cards)
        layout.addLayout(grid)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def refresh(self) -> None:
        period = self._period.period()
        overview = self._statistics.overview(period)
        self._purchased.set_value(fmt_money(overview.purchased), CURRENCY)
        self._consumed.set_value(
            fmt_money(overview.consumed),
            tr("{0}  ·  {1} ta mahsulot harakatda").format(CURRENCY, overview.products_moved),
        )
        self._sites_total.set_value(
            fmt_money(overview.site_expense), tr("{0}  ·  sof (qaytgani ayirilgan)").format(CURRENCY)
        )
        self._prices.set_value(
            f"↑ {overview.price_rises}   ↓ {overview.price_drops}", tr("oshgan va tushgan holatlar (mahsulot × oy)")
        )

        step = _BREAKDOWN.get(self._period.granularity(), Granularity.MONTH)
        self._chart.set_data(
            [
                (_short_label(step, total.start), (total.amount_in, total.amount_out))
                for total in self._reports.dynamics(period, step)
            ]
        )
        self._top_out.set_rows(_rank_rows(self._statistics.top_products(MovementKind.OUT, period)))
        self._top_in.set_rows(_rank_rows(self._statistics.top_products(MovementKind.IN, period)))
        self._sites.set_rows(
            [
                (
                    site.name,
                    site.net,
                    tr("berilgan {0}  ·  qaytgan {1}  ·  sof {2} {3}").format(
                        fmt_money(site.issued), fmt_money(site.returned), fmt_money(site.net), CURRENCY
                    ),
                )
                for site in self._statistics.site_expenses(period)[:10]
            ]
        )
        changes = self._statistics.price_changes(period)
        self._price_table.set_rows(
            [
                (
                    fmt_period(Granularity.MONTH, change.month),
                    change.name,
                    change.unit,
                    fmt_period(Granularity.MONTH, change.previous_month),
                    change.previous_price,
                    change.price,
                    f"{'+' if change.difference > 0 else '−'}{fmt_money(abs(change.difference))}",
                    fmt_percent(change.percent),
                )
                for change in changes
            ],
            ids=[change.product_id for change in changes],
            flagged=[index for index, change in enumerate(changes) if change.difference > 0],
        )


def _short_label(step: Granularity, day) -> str:
    """Diagramma ostidagi qisqa yozuv: oyda — oy nomi, kunda — sana (kun.oy)."""
    return MONTH_NAMES[day.month - 1] if step is Granularity.MONTH else f"{day:%d.%m}"
