"""Obyektlar sahifasi: mahsulot beriladigan joylar ro'yxati va har biriga berilgan/qaytgan mahsulotlar."""

from PySide6.QtWidgets import QDialog

from ..config import CURRENCY
from ..formatting import fmt_compact
from ..i18n import tr
from ..session import Session
from ..sites import Sites
from .icons import Glyph
from .list_page import ListPage
from .site_dialogs import SiteDialog, TableDialog
from .widgets import Column, ColumnKind, StatCard, button

_COLUMNS = (
    Column(tr("Obyekt"), style="strong"),
    Column(tr("Manzil")),
    Column(tr("Mas'ul shaxs")),
    Column(tr("Berilgan"), ColumnKind.MONEY),
    Column(tr("Qaytgan"), ColumnKind.MONEY),
    Column(tr("Obyektda"), ColumnKind.MONEY, "strong"),
    Column(tr("Izoh")),
)
_OPTIONAL_COLUMNS = (1, 2, 6)  # hech bir obyektda to'ldirilmagan bo'lsa, yashiriladi
_PRODUCT_COLUMNS = (
    Column(tr("Mahsulot"), style="strong"),
    Column(tr("Birlik")),
    Column(tr("Berilgan"), ColumnKind.QUANTITY),
    Column(tr("Qaytgan"), ColumnKind.QUANTITY),
    Column(tr("Obyektda"), ColumnKind.QUANTITY, "strong"),
)


class SitesPage(ListPage):
    delete_question = tr("Bu obyekt ro'yxatdan o'chirilsinmi?")

    def __init__(self, sites: Sites, session: Session):
        super().__init__(
            tr("Obyektlar"),
            tr("+ Yangi obyekt"),
            _COLUMNS,
            session,
            glyph=Glyph.PIN,
            subtitle=tr("Mahsulot beriladigan joylar: har biriga qancha berilgan va qanchasi qaytgan"),
        )
        self._sites = sites
        self.empty_hint = tr("Hali obyekt yo'q. «Yangi obyekt» tugmasi bilan qo'shing — chiqimda shu ro'yxatdan tanlanadi.")
        self._count = StatCard(tr("Obyektlar"), Glyph.PIN, "Accent")
        self._issued = StatCard(tr("Berilgan"), Glyph.ISSUE, "Out")
        self._returned = StatCard(tr("Qaytgan"), Glyph.UNDO, "Good")
        self._remaining = StatCard(tr("Obyektlarda"), Glyph.BOX, "Violet")
        for stat in (self._count, self._issued, self._returned, self._remaining):
            self.summary.addWidget(stat)

        products = button(tr("Mahsulotlari"), glyph=Glyph.BOX)
        products.setToolTip(tr("Tanlangan obyektga qaysi mahsulotdan qancha berilgani va qanchasi qaytgani"))
        products.clicked.connect(self._show_products)
        self.toolbar_tools.addWidget(products)

    def refresh(self) -> None:
        sites = self._sites.all(self.search.text())
        self.table.set_rows(
            [(s.name, s.address, s.manager, s.issued, s.returned, s.remaining, s.note) for s in sites],
            ids=[s.id for s in sites],
        )
        self.table.hide_empty_columns(_OPTIONAL_COLUMNS)
        self.footer.setText(tr("Jami: {0} ta obyekt").format(len(sites)))
        everything = self._sites.all()
        self._count.set_value(str(len(everything)), tr("ta obyekt"))
        for stat, amount in (
            (self._issued, sum(site.issued for site in everything)),
            (self._returned, sum(site.returned for site in everything)),
            (self._remaining, sum(site.remaining for site in everything)),
        ):
            stat.set_value(fmt_compact(amount), CURRENCY)

    def edit_dialog(self, item_id: int | None) -> QDialog:
        return SiteDialog(self._sites, self._sites.get(item_id) if item_id is not None else None, self)

    def delete_item(self, item_id: int) -> None:
        self._sites.delete(item_id)

    def _show_products(self) -> None:
        site_id = self.selected_id()
        if site_id is None:
            return
        site = self._sites.get(site_id)
        rows = [(p.product_name, p.unit, p.issued, p.returned, p.remaining) for p in self._sites.products(site_id)]
        TableDialog(
            tr("{0} — mahsulotlar").format(site.name),
            tr("Obyektga berilgan va undan omborga qaytgan mahsulotlar (butun davr bo'yicha)"),
            _PRODUCT_COLUMNS,
            rows,
            self,
        ).exec()
