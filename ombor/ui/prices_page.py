"""Narx nazorati: 6 oy ichida xarid narxi o'zgargan mahsulotlar va har yarim yilda ko'rib chiqish eslatmasi."""

from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from ..config import CURRENCY
from ..formatting import fmt_date, fmt_range
from ..i18n import tr
from ..models import PriceChange
from ..pricing import REVIEW_MONTHS, PriceControl, add_months, review_period
from ..session import Session
from ..warehouse import display_counterparty
from .icons import Glyph
from .printing import print_table
from .widgets import Column, ColumnKind, DataTable, StatCard, button, export_to_excel, label, page_header, table_card

_COLUMNS = (
    Column(tr("Mahsulot"), style="strong"),
    Column(tr("Birlik")),
    Column(tr("Birinchi xarid"), ColumnKind.DATE),
    Column(tr("Birinchi narx"), ColumnKind.MONEY),
    Column(tr("Oxirgi xarid"), ColumnKind.DATE),
    Column(tr("Oxirgi narx"), ColumnKind.MONEY, "strong"),
    Column(tr("Eng past"), ColumnKind.MONEY),
    Column(tr("Eng yuqori"), ColumnKind.MONEY),
    Column(tr("O'zgarish, %"), style="strong"),
    Column(tr("Farq (1 birlik)"), ColumnKind.MONEY),
    Column(tr("Xaridlar soni"), ColumnKind.QUANTITY),
    Column(tr("Oxirgi yetkazib beruvchi")),
)


def fmt_percent(value: float) -> str:
    return f"{value:+.1f} %".replace(".", ",")


class PricesPage(QWidget):
    review_changed = Signal()  # narxlar ko'rib chiqildi — menyudagi eslatma yangilanadi

    def __init__(self, prices: PriceControl, session: Session):
        super().__init__()
        self.setObjectName("page")
        self._prices = prices
        self._session = session
        self._end = date.today()

        header, tools = page_header(
            Glyph.TAG,
            tr("Narx nazorati"),
            tr("Har {0} oyda bir marta: xarid narxi oldingisidan farq qiladimi").format(REVIEW_MONTHS),
        )
        previous = button("", "page", Glyph.PREVIOUS)
        previous.setToolTip(tr("Oldingi {0} oy").format(REVIEW_MONTHS))
        previous.clicked.connect(lambda: self._shift(-1))
        self._next = button("", "page", Glyph.NEXT)
        self._next.setToolTip(tr("Keyingi {0} oy").format(REVIEW_MONTHS))
        self._next.clicked.connect(lambda: self._shift(1))
        self._period_title = label("", "periodTitle")
        for widget in (previous, self._period_title, self._next):
            tools.addWidget(widget)

        self._status = StatCard(tr("Narx nazorati"), Glyph.CALENDAR, "Warning")
        self._raised = StatCard(tr("Narxi oshganlar"), Glyph.ARROW_UP, "Out")
        self._lowered = StatCard(tr("Narxi tushganlar"), Glyph.ARROW_DOWN, "Good")
        summary = QHBoxLayout()
        summary.setSpacing(14)
        for stat in (self._status, self._raised, self._lowered):
            summary.addWidget(stat)

        self._only_changed = QCheckBox(tr("Faqat narxi o'zgarganlar"))
        self._only_changed.setChecked(True)
        self._only_changed.toggled.connect(self.refresh)
        self._reviewed = button(tr("Ko'rib chiqildi"), "primary", Glyph.CHECK)
        self._reviewed.setToolTip(
            tr("Narxlar tekshirilganini belgilash: keyingi eslatma {0} oydan keyin").format(REVIEW_MONTHS)
        )
        self._reviewed.clicked.connect(self._mark_reviewed)
        self._reviewed.setVisible(session.is_admin)
        print_button = button(tr("Chop etish"), "print", Glyph.PRINT)
        print_button.clicked.connect(lambda: print_table(self, self._table, self._export_title()))
        excel = button(tr("Excelga chiqarish"), "excel", Glyph.EXPORT)
        excel.clicked.connect(lambda: export_to_excel(self, self._table, self._export_title()))
        toolbar = QHBoxLayout()
        toolbar.addWidget(self._reviewed)
        toolbar.addWidget(self._only_changed)
        toolbar.addStretch()
        toolbar.addWidget(print_button)
        toolbar.addWidget(excel)

        self._table = DataTable(_COLUMNS)
        self._table.empty_text = tr("Bu davrda narxi o'zgargan xarid yo'q")
        self._footer = label("", "muted")
        self._footer.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)
        layout.addLayout(header)
        layout.addLayout(summary)
        layout.addLayout(toolbar)
        layout.addWidget(table_card(self._table), stretch=1)
        layout.addWidget(self._footer)

    def refresh(self) -> None:
        period = review_period(self._end)
        self._period_title.setText(fmt_range(period.start, period.end))
        self._next.setEnabled(self._end < date.today())
        changes = self._prices.changes(period, self._only_changed.isChecked())
        self._table.set_rows(
            [self._row(change) for change in changes],
            ids=[change.product_id for change in changes],
            flagged=[index for index, change in enumerate(changes) if change.percent > 0.05],
        )
        raised = [change for change in changes if change.difference > 0.005]
        lowered = [change for change in changes if change.difference < -0.005]
        self._raised.set_value(str(len(raised)), tr("ta mahsulot"))
        self._lowered.set_value(str(len(lowered)), tr("ta mahsulot"))
        self._show_review_status()
        self._footer.setText(
            tr(
                "Davrdagi birinchi va oxirgi xarid narxi solishtiriladi (1 birlik uchun, {0}). Boshlang'ich qoldiq, "
                "inventarizatsiya va qaytarishlar hisobga olinmaydi."
            ).format(CURRENCY)
        )

    @staticmethod
    def _row(change: PriceChange) -> tuple:
        return (
            change.name,
            change.unit,
            change.first_date,
            change.first_price,
            change.last_date,
            change.last_price,
            change.min_price,
            change.max_price,
            fmt_percent(change.percent),
            change.difference,
            change.purchases,
            display_counterparty(change.last_supplier),
        )

    def _show_review_status(self) -> None:
        reviewed, upcoming = self._prices.reviewed_at, self._prices.next_review()
        if reviewed is None:
            self._status.set_value(tr("Vaqti keldi"), tr("hali o'tkazilmagan"))
        elif self._prices.is_due():
            self._status.set_value(tr("Vaqti keldi"), tr("oxirgisi: {0}").format(fmt_date(reviewed)))
        else:
            self._status.set_value(fmt_date(upcoming), tr("oxirgisi: {0}").format(fmt_date(reviewed)))

    def _shift(self, direction: int) -> None:
        self._end = min(add_months(self._end, direction * REVIEW_MONTHS), date.today())
        self.refresh()

    def _export_title(self) -> str:
        period = review_period(self._end)
        return f"{tr('Narx nazorati')} — {fmt_range(period.start, period.end)}"

    def _mark_reviewed(self) -> None:
        self._prices.mark_reviewed()
        self.refresh()
        self.review_changed.emit()
        QMessageBox.information(
            self,
            tr("Narx nazorati"),
            tr("Narxlar ko'rib chiqildi. Keyingi nazorat: {0}.").format(fmt_date(self._prices.next_review())),
        )
