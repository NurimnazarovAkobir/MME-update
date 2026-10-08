"""Obyektlar sahifasi: mahsulot beriladigan joylar ro'yxati va har biriga berilgan/qaytgan mahsulotlar."""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QMessageBox, QVBoxLayout

from ..config import CURRENCY
from ..formatting import fmt_compact
from ..geo import maps_url
from ..i18n import tr
from ..session import Session
from ..sites import Sites
from .icons import Glyph
from .list_page import ListPage
from .site_dialogs import SiteDialog, TableDialog
from .site_map import MapPoint, SiteMap
from .tile_loader import TileLoader
from .widgets import Column, ColumnKind, StatCard, button, section_header

_COLUMNS = (
    Column(tr("Obyekt"), style="strong"),
    Column(tr("Manzil")),
    Column(tr("Mas'ul shaxs")),
    Column(tr("Berilgan"), ColumnKind.MONEY),
    Column(tr("Qaytgan"), ColumnKind.MONEY),
    Column(tr("Obyektda"), ColumnKind.MONEY, "strong"),
    Column(tr("Izoh")),
)
_DETAIL_COLUMNS = (1, 2, 6)  # manzil, mas'ul shaxs, izoh: bo'sh bo'lsa yoki xarita ochiq tursa, yashiriladi
_PRODUCT_COLUMNS = (
    Column(tr("Mahsulot"), style="strong"),
    Column(tr("Birlik")),
    Column(tr("Berilgan"), ColumnKind.QUANTITY),
    Column(tr("Qaytgan"), ColumnKind.QUANTITY),
    Column(tr("Obyektda"), ColumnKind.QUANTITY, "strong"),
)


class SitesPage(ListPage):
    delete_question = tr("Bu obyekt ro'yxatdan o'chirilsinmi?")

    def __init__(self, sites: Sites, session: Session, tiles: TileLoader | None = None):
        """`tiles` — xarita rasmlarini yuklovchi; berilmasa, xaritada faqat masofa to'ri va belgilar bo'ladi."""
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

        self._map = SiteMap(tiles)
        self._map.selected.connect(self.table.select_id)
        self._map.opened.connect(self._open_in_maps)
        self.table.itemSelectionChanged.connect(lambda: self._map.select(self.table.selected_id()))
        self._map_panel = self._build_map_panel()
        self.body.addWidget(self._map_panel, stretch=2)
        self._show_map = button(tr("Xarita"), "segment")
        self._show_map.setCheckable(True)
        self._show_map.setChecked(True)
        self._show_map.setToolTip(tr("Obyektlar xaritasini ko'rsatish yoki yashirish"))
        self._show_map.toggled.connect(self._on_map_toggled)
        self.header_tools.addWidget(self._show_map)

    def refresh(self) -> None:
        sites = self._sites.all(self.search.text())
        self.table.set_rows(
            [(s.name, s.address, s.manager, s.issued, s.returned, s.remaining, s.note) for s in sites],
            ids=[s.id for s in sites],
        )
        self._show_detail_columns()
        self.footer.setText(tr("Jami: {0} ta obyekt").format(len(sites)))
        self._map.set_points([MapPoint(s.id, s.name, s.location, s.address) for s in sites if s.location])
        self._map.select(self.table.selected_id())
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

    def _on_map_toggled(self, shown: bool) -> None:
        self._map_panel.setVisible(shown)
        self._show_detail_columns()

    def _show_detail_columns(self) -> None:
        """Xarita ochiq turganda jadval tor: asosiy ustunlar qoladi, manzil va izoh xarita yopilganda ko'rinadi."""
        if self._show_map.isChecked():
            for column in _DETAIL_COLUMNS:
                self.table.hide_column(column, True)
        else:
            self.table.hide_empty_columns(_DETAIL_COLUMNS)

    def _build_map_panel(self) -> QFrame:
        """Jadval yonidagi kartochka: internetsiz xarita va tanlangan obyektni Google Maps'da ochish tugmasi."""
        open_button = button(tr("Google Maps'da ochish"), "link")
        open_button.setToolTip(tr("Tanlangan obyektni internetdagi xaritada ochadi (internet kerak)"))
        open_button.clicked.connect(self._open_selected_in_maps)
        header = QHBoxLayout()
        title = section_header(Glyph.PIN, tr("Xarita"))
        title.setToolTip(tr("Surish — sichqoncha bilan; kattalashtirish — g'ildirak yoki ikki marta bosish"))
        header.addWidget(title, stretch=1)
        header.addWidget(open_button)
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self._map, stretch=1)
        return panel

    def _open_selected_in_maps(self) -> None:
        site_id = self.selected_id()
        if site_id is not None:
            self._open_in_maps(site_id)

    def _open_in_maps(self, site_id: int) -> None:
        """Obyektni Google Maps'da ochadi: koordinatasi bo'yicha, u yo'q bo'lsa — manzili bo'yicha."""
        site = self._sites.get(site_id)
        url = maps_url(site.location, site.address)
        if url is None:
            QMessageBox.information(
                self,
                site.name,
                tr("Bu obyektning joylashuvi ham, manzili ham yozilmagan. Obyektni tahrirlab, ularni kiriting."),
            )
            return
        QDesktopServices.openUrl(QUrl(url))

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
