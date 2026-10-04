"""Hisobotlar: kunlik, haftalik, oylik, yillik yoki ixtiyoriy davr bo'yicha."""

from dataclasses import dataclass
from typing import Callable, Sequence

from PySide6.QtWidgets import QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from ..analytics import Analytics
from ..catalog import display_name
from ..config import CURRENCY
from ..formatting import fmt_money, fmt_period
from ..i18n import tr
from ..models import Granularity, MovementKind, Period
from ..reports import UNNAMED, GroupBy, Reports
from ..warehouse import Warehouse
from .labels import LABELS
from .printing import print_table
from .widgets import Column, ColumnKind, DataTable, PeriodNavigator, StatCard, button, export_to_excel, label

# «Davrlar bo'yicha» hisobotida tanlangan davr qanday bo'laklarga bo'linishi.
_BREAKDOWN = {
    Granularity.DAY: Granularity.DAY,
    Granularity.WEEK: Granularity.DAY,
    Granularity.MONTH: Granularity.DAY,
    Granularity.YEAR: Granularity.MONTH,
}
CUSTOM_PERIOD_BREAKDOWN = Granularity.MONTH


@dataclass(frozen=True)
class ReportTab:
    """Bitta hisobot: nomi, ustunlari va davr bo'yicha qatorlarni beruvchi funksiya."""

    title: str
    columns: Sequence[Column]
    rows: Callable[[Period], list[tuple]]


def _group_columns(name: str, operations: str) -> tuple[Column, ...]:
    return (
        Column(name),
        Column(operations, ColumnKind.QUANTITY),
        Column(tr("Summa, {0}").format(CURRENCY), ColumnKind.MONEY),
    )


class ReportsPage(QWidget):
    def __init__(self, reports: Reports, analytics: Analytics, warehouse: Warehouse):
        super().__init__()
        self._warehouse = warehouse
        self.setObjectName("page")
        self._reports = reports
        self._analytics = analytics

        self._period = PeriodNavigator()
        self._period.changed.connect(self.refresh)
        self._amount_in = StatCard(tr("Kirim summasi"))
        self._amount_out = StatCard(tr("Chiqim (rasxod) summasi"))
        self._stock_value = StatCard(tr("Ombordagi mahsulot qiymati (hozir)"))
        self._net_profit = StatCard(tr("Sof foyda"))

        self._report_tabs = self._build_report_tabs()
        self._tabs = QTabWidget()
        for tab in self._report_tabs:
            self._tabs.addTab(DataTable(tab.columns), tab.title)

        print_button = button(tr("Chop etish"))
        print_button.clicked.connect(lambda: print_table(self, *self._current_report()))
        excel = button(tr("Excelga chiqarish"))
        excel.clicked.connect(lambda: export_to_excel(self, *self._current_report()))

        header = QHBoxLayout()
        header.addWidget(label(tr("Hisobotlar"), "pageTitle"))
        header.addStretch()
        header.addWidget(print_button)
        header.addWidget(excel)

        cards = QHBoxLayout()
        cards.setSpacing(14)
        for stat in (self._amount_in, self._amount_out, self._net_profit, self._stock_value):
            cards.addWidget(stat)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)
        layout.addLayout(header)
        layout.addWidget(self._period)
        layout.addLayout(cards)
        layout.addWidget(self._tabs, stretch=1)

    def refresh(self) -> None:
        period = self._period.period()
        totals = self._reports.totals(period)
        self._amount_in.set_value(
            fmt_money(totals.amount_in), tr("{0}  ·  {1} ta kirim").format(CURRENCY, totals.count_in)
        )
        self._amount_out.set_value(
            fmt_money(totals.amount_out), tr("{0}  ·  {1} ta chiqim").format(CURRENCY, totals.count_out)
        )
        self._stock_value.set_value(fmt_money(self._reports.stock_value()), CURRENCY)
        profit = self._analytics.summary(period)
        self._net_profit.set_value(
            fmt_money(profit.net_profit),
            tr("sotuvdan foyda {0} − xizmat va xarajatlar {1}").format(
                fmt_money(profit.profit), fmt_money(profit.expenses)
            ),
        )
        for index, tab in enumerate(self._report_tabs):
            self._tabs.widget(index).set_rows(tab.rows(period))

    def _build_report_tabs(self) -> tuple[ReportTab, ...]:
        incoming, outgoing = LABELS[MovementKind.IN], LABELS[MovementKind.OUT]

        def grouped(kind: MovementKind, group: GroupBy) -> Callable[[Period], list[tuple]]:
            return lambda period: [
                (row.name, row.operations, row.amount) for row in self._reports.by_group(kind, group, period)
            ]

        return (
            ReportTab(
                tr("Aylanma qaydnoma"),
                (
                    Column(tr("Mahsulot")),
                    Column(tr("Birlik")),
                    Column(tr("Boshlang'ich qoldiq"), ColumnKind.QUANTITY),
                    Column(tr("Kirim"), ColumnKind.QUANTITY),
                    Column(tr("Chiqim"), ColumnKind.QUANTITY),
                    Column(tr("Oxirgi qoldiq"), ColumnKind.QUANTITY),
                    Column(tr("Kirim summasi, {0}").format(CURRENCY), ColumnKind.MONEY),
                    Column(tr("Chiqim summasi, {0}").format(CURRENCY), ColumnKind.MONEY),
                ),
                lambda period: [
                    (r.name, r.unit, r.opening, r.qty_in, r.qty_out, r.closing, r.amount_in, r.amount_out)
                    for r in self._reports.turnover(period)
                ],
            ),
            ReportTab(
                tr("Davrlar bo'yicha"),
                (
                    Column(tr("Davr")),
                    Column(tr("Kirimlar soni"), ColumnKind.QUANTITY),
                    Column(tr("Kirim summasi, {0}").format(CURRENCY), ColumnKind.MONEY),
                    Column(tr("Chiqimlar soni"), ColumnKind.QUANTITY),
                    Column(tr("Chiqim summasi, {0}").format(CURRENCY), ColumnKind.MONEY),
                ),
                self._dynamics_rows,
            ),
            ReportTab(
                tr("Guruhlar bo'yicha"),
                (
                    Column(tr("Guruh")),
                    Column(tr("Kichik guruh")),
                    Column(tr("Kirim summasi, {0}").format(CURRENCY), ColumnKind.MONEY),
                    Column(tr("Chiqim summasi, {0}").format(CURRENCY), ColumnKind.MONEY),
                ),
                lambda period: [
                    (
                        display_name(row.category) or UNNAMED,
                        display_name(row.subcategory),
                        row.amount_in,
                        row.amount_out,
                    )
                    for row in self._reports.by_category(period)
                ],
            ),
            ReportTab(
                tr("Foyda"),
                (
                    Column(tr("Mahsulot")),
                    Column(tr("Sotilgan miqdor"), ColumnKind.QUANTITY),
                    Column(tr("Birlik")),
                    Column(tr("Tushum, {0}").format(CURRENCY), ColumnKind.MONEY),
                    Column(tr("Tannarx, {0}").format(CURRENCY), ColumnKind.MONEY),
                    Column(tr("Foyda, {0}").format(CURRENCY), ColumnKind.MONEY),
                    Column(tr("Rentabellik, %"), ColumnKind.QUANTITY),
                ),
                lambda period: [
                    (p.name, p.quantity, p.unit, p.revenue, p.cost, p.profit, round(p.margin * 100, 1))
                    for p in self._analytics.by_product(period)
                ],
            ),
            ReportTab(
                incoming.person,
                _group_columns(incoming.person, tr("Kirimlar soni")),
                grouped(MovementKind.IN, GroupBy.PERSON),
            ),
            ReportTab(
                tr("Yetkazib beruvchilar"),
                _group_columns(incoming.counterparty, tr("Kirimlar soni")),
                grouped(MovementKind.IN, GroupBy.COUNTERPARTY),
            ),
            ReportTab(
                outgoing.person,
                _group_columns(outgoing.person, tr("Chiqimlar soni")),
                grouped(MovementKind.OUT, GroupBy.PERSON),
            ),
            ReportTab(
                tr("Ko'chirishlar"),
                (
                    Column(tr("Sana"), ColumnKind.DATE),
                    Column(tr("Mahsulot")),
                    Column(tr("Miqdor"), ColumnKind.QUANTITY),
                    Column(tr("Birlik")),
                    Column(tr("Qaysi ombordan")),
                    Column(tr("Qaysi omborga")),
                    Column(tr("Izoh")),
                    Column(tr("Kiritdi")),
                ),
                lambda period: [
                    (t.date, t.product_name, t.quantity, t.unit, t.from_name, t.to_name, t.note, t.created_by)
                    for t in self._warehouse.transfers(period)
                ],
            ),
            ReportTab(
                tr("Obyektlar bo'yicha rasxod"),
                _group_columns(tr("Obyekt"), tr("Chiqimlar soni")),
                grouped(MovementKind.OUT, GroupBy.COUNTERPARTY),
            ),
        )

    def _dynamics_rows(self, period: Period) -> list[tuple]:
        """Hafta va oy — kunma-kun, yil va ixtiyoriy davr — oyma-oy."""
        step = _BREAKDOWN.get(self._period.granularity(), CUSTOM_PERIOD_BREAKDOWN)
        return [
            (fmt_period(step, total.start), total.count_in, total.amount_in, total.count_out, total.amount_out)
            for total in self._reports.dynamics(period, step)
        ]

    def _current_report(self) -> tuple[DataTable, str]:
        """Ochiq turgan hisobot jadvali va uning davr ko'rsatilgan sarlavhasi."""
        index = self._tabs.currentIndex()
        return self._tabs.widget(index), f"{self._report_tabs[index].title} ({self._period.title()})"
