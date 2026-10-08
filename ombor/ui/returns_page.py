"""Vozvrat sahifasi: obyektlardan omborga qaytgan mahsulotlar."""

from datetime import date

from PySide6.QtWidgets import QDialog

from ..config import CURRENCY
from ..formatting import fmt_compact, fmt_money
from ..i18n import tr
from ..models import MovementDetails, MovementKind
from ..session import Session
from ..sites import Sites
from ..warehouse import Warehouse, display_counterparty, store_name
from .dialogs import MovementDialog
from .icons import Glyph
from .labels import LABELS
from .list_page import ListPage
from .site_dialogs import ReturnDialog, TableDialog
from .widgets import Column, ColumnKind, PeriodFilter, button

_COLUMNS = (
    Column(tr("Sana"), ColumnKind.DATE, "recent"),
    Column(tr("Hujjat №")),
    Column(tr("Obyekt"), style="strong"),
    Column(tr("Mahsulot"), style="strong"),
    Column(tr("Miqdor"), ColumnKind.QUANTITY, "strong"),
    Column(tr("Birlik")),
    Column(tr("Summa"), ColumnKind.MONEY),
    Column(tr("Kim olib keldi")),
    Column(tr("Ombor")),
    Column(tr("Izoh")),
)
_OPTIONAL_COLUMNS = (1, 7, 9)  # hech bir yozuvda to'ldirilmagan bo'lsa, yashiriladi
_STORE_COLUMN = 8  # bitta ombor bo'lsa, yashiriladi
_BY_SITE_COLUMNS = (
    Column(tr("Obyekt"), style="strong"),
    Column(tr("Mahsulot"), style="strong"),
    Column(tr("Birlik")),
    Column(tr("Berilgan"), ColumnKind.QUANTITY),
    Column(tr("Qaytgan"), ColumnKind.QUANTITY, "strong"),
    Column(tr("Qaytgan summa"), ColumnKind.MONEY),
)


def _row(movement: MovementDetails) -> tuple:
    m = movement
    return (
        m.date,
        m.doc_number,
        display_counterparty(m.counterparty),
        m.product_name,
        m.quantity,
        m.unit,
        m.amount,
        m.person,
        store_name(m.warehouse_name),
        m.note,
    )


class ReturnsPage(ListPage):
    delete_question = tr("Bu vozvrat o'chirilsinmi? Mahsulot ombor qoldig'idan chiqariladi.")
    locked_message = tr("Omborchi faqat o'zi bugun kiritgan yozuvni o'zgartira oladi. Boshqasini rahbar tuzatadi.")

    def __init__(self, sites: Sites, warehouse: Warehouse, session: Session):
        super().__init__(
            tr("Vozvrat"),
            tr("+ Yangi vozvrat"),
            _COLUMNS,
            session,
            row_actions=session.can_add,  # omborchi — faqat o'zi bugun kiritgan yozuvlarda
            glyph=Glyph.UNDO,
            subtitle=tr("Obyektlardan omborga qaytgan mahsulotlar"),
        )
        self._sites = sites
        self._warehouse = warehouse
        self._period = PeriodFilter()
        self._period.changed.connect(self.refresh)
        self.header_tools.addWidget(self._period)
        self._recent = self.add_recent_cards(self._period)

        by_site = button(tr("Obyektlar bo'yicha"), glyph=Glyph.PIN)
        by_site.setToolTip(tr("Tanlangan davrda qaysi obyektdan qaysi mahsulot qancha qaytgani"))
        by_site.clicked.connect(self._show_by_site)
        self.toolbar_tools.addWidget(by_site)

    def refresh(self) -> None:
        returns = self._sites.returns(self._period.period(), self.search.text())
        self.table.set_rows(
            [_row(m) for m in returns],
            ids=[m.id for m in returns],
            locked=[index for index, m in enumerate(returns) if not self.session.can_change(m)],
        )
        self.table.hide_empty_columns(_OPTIONAL_COLUMNS)
        self.table.hide_column(_STORE_COLUMN, len(self._warehouse.stores()) < 2)
        self.footer.setText(
            tr("Jami: {0} ta yozuv  ·  {1} {2}").format(
                len(returns), fmt_money(sum(m.amount for m in returns)), CURRENCY
            )
        )
        today = date.today()
        for stat, period_of in self._recent.items():
            found = self._sites.returns(period_of(today))
            stat.set_value(
                fmt_compact(sum(m.amount for m in found)), tr("{0}  ·  {1} ta yozuv").format(CURRENCY, len(found))
            )

    def edit_dialog(self, item_id: int | None) -> QDialog:
        movement = self._warehouse.movement(item_id) if item_id is not None else None
        if movement is not None and self._sites.find(movement.counterparty) is None:
            # «Kirim» bo'limida kiritilgan, obyektga bog'lanmagan qaytarish o'sha oynada ochiladi.
            return MovementDialog(self._warehouse, LABELS[MovementKind.IN], self.session.author, movement, self)
        return ReturnDialog(self._sites, self._warehouse, self.session.author, movement, self)

    def delete_item(self, item_id: int) -> None:
        self._warehouse.delete_movement(item_id)

    def can_change(self, item_id: int) -> bool:
        return self.session.can_change(self._warehouse.movement(item_id))

    def _show_by_site(self) -> None:
        returned = [row for row in self._sites.products(period=self._period.period()) if row.returned > 0]
        TableDialog(
            tr("Vozvrat — obyektlar bo'yicha"),
            tr("Tanlangan davrda qaysi obyektdan qaysi mahsulot qancha qaytgani"),
            _BY_SITE_COLUMNS,
            [(r.site, r.product_name, r.unit, r.issued, r.returned, r.returned_amount) for r in returned],
            self,
        ).exec()
