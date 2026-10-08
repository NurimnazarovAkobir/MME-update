"""Kirim va chiqim sahifasi (ikkalasi uchun bitta sinf)."""

from datetime import date

from PySide6.QtWidgets import QDialog

from ..catalog import display_name
from ..config import CURRENCY
from ..formatting import fmt_compact, fmt_money
from ..i18n import tr
from ..models import MovementDetails, MovementKind
from ..session import Session
from ..sites import Sites
from ..warehouse import Warehouse, display_counterparty, store_name
from .dialogs import MovementDialog
from .document_dialog import DocumentDialog
from .icons import Glyph
from .labels import KindLabels
from .list_page import ListPage
from .printing import print_waybill
from .widgets import Column, ColumnKind, PeriodFilter, button

# Jadvalda bir vaqtda ko'rsatiladigan eng ko'p qator: juda katta bazada ham sahifa tez ochilishi uchun.
MAX_ROWS_SHOWN = 2000
STORE_COLUMN = 2  # bitta ombor bo'lsa, «Ombor» ustuni yashiriladi


def _columns(labels: KindLabels) -> tuple[Column, ...]:
    """Chiqimda xarid narxi o'rniga sotuv va foyda ustunlari bo'ladi (tannarx jami pastda ko'rinadi)."""
    start = (
        Column(tr("Sana"), ColumnKind.DATE, "recent"),
        Column(tr("Hujjat №")),
        Column(tr("Ombor")),
        Column(tr("Mahsulot"), style="strong"),
        Column(tr("Miqdor"), ColumnKind.QUANTITY, "strong"),
        Column(tr("Birlik")),
    )
    if labels.kind is MovementKind.IN:
        money = (Column(tr("Narxi"), ColumnKind.MONEY), Column(tr("Summa"), ColumnKind.MONEY, "strong"))
    else:
        money = (
            Column(tr("Sotuv narxi"), ColumnKind.MONEY),
            Column(tr("Sotuv summasi"), ColumnKind.MONEY, "strong"),
            Column(tr("Foyda"), ColumnKind.MONEY, "signed"),
        )
    end = (
        Column(tr("Guruh")),
        Column(tr("Kichik guruh")),
        Column(labels.person),
        Column(labels.counterparty),
        Column(tr("Belgi")),
        Column(tr("Izoh")),
        Column(tr("Kiritdi")),
    )
    return (*start, *money, *end)


def _marks(movement: MovementDetails) -> str:
    """Yozuvning alohida belgilari: qaytarish, qarzga."""
    marks = (tr("Qaytarish") if movement.is_return else "", tr("Qarzga") if movement.on_credit else "")
    return " · ".join(mark for mark in marks if mark)


def _row(movement: MovementDetails) -> tuple:
    m = movement
    start = (m.date, m.doc_number, store_name(m.warehouse_name), m.product_name, m.quantity, m.unit)
    money = (m.price, m.amount) if m.kind is MovementKind.IN else (m.sale_price, m.revenue, m.profit)
    groups = (display_name(m.category), display_name(m.subcategory))
    end = (m.person, display_counterparty(m.counterparty), _marks(m), m.note, m.created_by)
    return (*start, *money, *groups, *end)


class MovementsPage(ListPage):
    locked_message = tr("Omborchi faqat o'zi bugun kiritgan yozuvni o'zgartira oladi. Boshqasini rahbar tuzatadi.")

    def __init__(self, warehouse: Warehouse, sites: Sites, labels: KindLabels, session: Session):
        # Omborchida ham qator tugmalari bor, lekin faqat o'zi bugun kiritgan yozuvlarda.
        is_receipt = labels.kind is MovementKind.IN
        super().__init__(
            labels.title,
            labels.new_action,
            _columns(labels),
            session,
            row_actions=session.can_add,
            glyph=Glyph.RECEIPT if is_receipt else Glyph.ISSUE,
            subtitle=(
                tr("Omborga kelgan mahsulotlar va xarajatlar")
                if is_receipt
                else tr("Ombordan chiqqan mahsulotlar va sotuvlar")
            ),
        )
        self._warehouse = warehouse
        self._sites = sites
        self._labels = labels
        # Obyektdan qaytgan mahsulot kirim (xarid) emas: u «Vozvrat» bo'limida ko'rsatiladi.
        self._returns = False if is_receipt else None
        self.empty_hint = (
            tr("Hali kirim yo'q. Mahsulot kelganda «Yangi kirim» tugmasini bosing.")
            if is_receipt
            else tr("Hali chiqim yo'q. Mahsulot berilganda «Yangi chiqim» tugmasini bosing.")
        )
        # Hech bir yozuvda to'ldirilmagan bo'lsa, yashiriladigan ustunlar: jadval oynaga sig'ishi uchun.
        titles = [column.title for column in _columns(labels)]
        self._optional_columns = [
            titles.index(title) for title in (tr("Hujjat №"), tr("Guruh"), tr("Kichik guruh"), tr("Belgi"), tr("Izoh"))
        ]
        self._period = PeriodFilter()
        self._period.changed.connect(self.refresh)
        self.header_tools.addWidget(self._period)
        self._recent = self.add_recent_cards(self._period)

        waybill = button(tr("Nakladnoy"), glyph=Glyph.DOCUMENT)
        waybill.setToolTip(tr("Tanlangan yozuvning hujjatini chop etish (bir xil raqamli yozuvlar birga chiqadi)"))
        waybill.clicked.connect(self._print_waybill)
        self.toolbar_tools.addWidget(waybill)

    def refresh(self) -> None:
        movements = self._warehouse.movements(
            self._labels.kind, self._period.period(), self.search.text(), returns=self._returns
        )
        shown = movements[:MAX_ROWS_SHOWN]
        self.table.set_rows(
            [_row(m) for m in shown],
            ids=[m.id for m in shown],
            locked=[index for index, m in enumerate(shown) if not self.session.can_change(m)],
        )
        self.table.hide_empty_columns(self._optional_columns)
        self.table.hide_column(STORE_COLUMN, len(self._warehouse.stores()) < 2)
        self.footer.setText(self._totals(movements))
        self._show_recent()

    def _show_recent(self) -> None:
        """Bugun, shu hafta va shu oy bo'yicha jami (qidiruv va davr filtridan qat'i nazar)."""
        today = date.today()
        for stat, period_of in self._recent.items():
            found = self._warehouse.movements(self._labels.kind, period_of(today), returns=self._returns)
            amount = sum(m.amount if self._labels.kind is MovementKind.IN else (m.revenue or m.amount) for m in found)
            stat.set_value(fmt_compact(amount), tr("{0}  ·  {1} ta yozuv").format(CURRENCY, len(found)))

    def edit_dialog(self, item_id: int | None) -> QDialog:
        """Yangi yozuv — bir nechta mahsulotli hujjat; mavjudini tahrirlash — bitta yozuvning to'liq shakli."""
        if item_id is None:
            return DocumentDialog(self._warehouse, self._sites, self._labels, self.session.author, self)
        movement = self._warehouse.movement(item_id)
        return MovementDialog(self._warehouse, self._labels, self.session.author, movement, self)

    def delete_item(self, item_id: int) -> None:
        self._warehouse.delete_movement(item_id)

    def can_change(self, item_id: int) -> bool:
        return self.session.can_change(self._warehouse.movement(item_id))

    def _print_waybill(self) -> None:
        movement_id = self.selected_id()
        if movement_id is not None:
            print_waybill(self, self._warehouse.document(movement_id), self._labels)

    def _totals(self, movements: list[MovementDetails]) -> str:
        """Jami hamma topilgan yozuvlar bo'yicha hisoblanadi, jadvalga sig'maganlari ham kiradi."""
        count = tr("Jami: {0} ta yozuv").format(len(movements))
        if len(movements) > MAX_ROWS_SHOWN:
            count += tr(" (jadvalda oxirgi {0} tasi; qolganini ko'rish uchun davrni toraytiring)").format(
                MAX_ROWS_SHOWN
            )
        cost = sum(m.amount for m in movements)
        if self._labels.kind is MovementKind.IN:
            return f"{count}  ·  {fmt_money(cost)} {CURRENCY}"
        revenue = sum(m.revenue for m in movements)
        profit = sum(m.profit for m in movements)
        return tr("{0}  ·  tannarx {1}  ·  sotuv {2}  ·  foyda {3} {4}").format(
            count, fmt_money(cost), fmt_money(revenue), fmt_money(profit), CURRENCY
        )
