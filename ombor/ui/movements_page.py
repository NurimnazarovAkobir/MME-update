"""Kirim va chiqim sahifasi (ikkalasi uchun bitta sinf)."""

from PySide6.QtWidgets import QDialog

from ..catalog import display_name
from ..config import CURRENCY
from ..formatting import fmt_money
from ..i18n import tr
from ..models import MovementDetails, MovementKind
from ..session import Session
from ..warehouse import Warehouse
from .dialogs import MovementDialog
from .labels import KindLabels
from .list_page import ListPage
from .widgets import Column, ColumnKind, PeriodFilter


def _columns(labels: KindLabels) -> tuple[Column, ...]:
    """Chiqimda xarid narxi o'rniga sotuv va foyda ustunlari bo'ladi (tannarx jami pastda ko'rinadi)."""
    start = (
        Column(tr("Sana"), ColumnKind.DATE),
        Column(tr("Mahsulot")),
        Column(tr("Miqdor"), ColumnKind.QUANTITY),
        Column(tr("Birlik")),
    )
    if labels.kind is MovementKind.IN:
        money = (Column(tr("Narxi"), ColumnKind.MONEY), Column(tr("Summa"), ColumnKind.MONEY))
    else:
        money = (
            Column(tr("Sotuv narxi"), ColumnKind.MONEY),
            Column(tr("Sotuv summasi"), ColumnKind.MONEY),
            Column(tr("Foyda"), ColumnKind.MONEY),
        )
    end = (
        Column(tr("Guruh")),
        Column(tr("Kichik guruh")),
        Column(labels.person),
        Column(labels.counterparty),
        Column(tr("Izoh")),
        Column(tr("Kiritdi")),
    )
    return (*start, *money, *end)


def _row(movement: MovementDetails) -> tuple:
    m = movement
    start = (m.date, m.product_name, m.quantity, m.unit)
    money = (m.price, m.amount) if m.kind is MovementKind.IN else (m.sale_price, m.revenue, m.profit)
    groups = (display_name(m.category), display_name(m.subcategory))
    return (*start, *money, *groups, m.person, m.counterparty, m.note, m.created_by)


class MovementsPage(ListPage):
    def __init__(self, warehouse: Warehouse, labels: KindLabels, session: Session):
        super().__init__(labels.title, labels.new_action, _columns(labels), session)
        self._warehouse = warehouse
        self._labels = labels
        self._session = session
        self._period = PeriodFilter()
        self._period.changed.connect(self.refresh)
        self.header_tools.addWidget(self._period)

    def refresh(self) -> None:
        movements = self._warehouse.movements(self._labels.kind, self._period.period(), self.search.text())
        self.table.set_rows([_row(m) for m in movements], ids=[m.id for m in movements])
        self.footer.setText(self._totals(movements))

    def edit_dialog(self, item_id: int | None) -> QDialog:
        movement = self._warehouse.movement(item_id) if item_id is not None else None
        return MovementDialog(self._warehouse, self._labels, self._session.author, movement, self)

    def delete_item(self, item_id: int) -> None:
        self._warehouse.delete_movement(item_id)

    def _totals(self, movements: list[MovementDetails]) -> str:
        count = tr("Jami: {0} ta yozuv").format(len(movements))
        cost = sum(m.amount for m in movements)
        if self._labels.kind is MovementKind.IN:
            return f"{count}  ·  {fmt_money(cost)} {CURRENCY}"
        revenue = sum(m.revenue for m in movements)
        profit = sum(m.profit for m in movements)
        return tr("{0}  ·  tannarx {1}  ·  sotuv {2}  ·  foyda {3} {4}").format(
            count, fmt_money(cost), fmt_money(revenue), fmt_money(profit), CURRENCY
        )
