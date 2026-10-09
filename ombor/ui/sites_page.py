"""Obyektlar sahifasi: mahsulot beriladigan joylar ro'yxati va har biriga berilgan/qaytgan mahsulotlar."""

import threading
import time
from dataclasses import replace

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QMessageBox, QVBoxLayout

from ..config import CURRENCY
from ..formatting import fmt_compact
from .. import geo
from ..geo import FoundPlace, LookupFailed, maps_url
from ..models import Site
from ..i18n import tr
from ..session import Session
from ..sites import Sites
from .icons import Glyph
from .list_page import ListPage
from .site_dialogs import SiteDialog, TableDialog
from .site_map import MapPoint, SiteMap
from .tile_loader import TileLoader
from .widgets import Column, ColumnKind, StatCard, button, confirm, section_header

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
class BulkPlaceFinder(QObject):
    """Bir nechta obyektning joylashuvini internetdan fonda, birma-bir qidiradi."""

    found = Signal(int, object)  # obyekt id si va FoundPlace (topilmasa — None)
    finished = Signal(bool)  # True — hammasi ko'rib chiqildi; False — internetga ulanib bo'lmadi

    def find(self, sites: list[Site]) -> None:
        def run() -> None:
            completed = True
            for number, site in enumerate(sites):
                if number:
                    time.sleep(geo.LOOKUP_PAUSE_SECONDS)  # xizmat qoidasi: so'rovlar orasida tanaffus
                try:
                    self.found.emit(site.id, geo.find_place(site.name, site.address))
                except LookupFailed:
                    completed = False
                    break
                except RuntimeError:
                    return  # sahifa yopilgan
            try:
                self.finished.emit(completed)
            except RuntimeError:
                pass

        threading.Thread(target=run, daemon=True).start()


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
        self._find_places = button(tr("Joylashuvlarni topish"), glyph=Glyph.SEARCH)
        self._find_places.setToolTip(tr("Joylashuvi yozilmagan obyektlarni nomi va manzili bo'yicha internetdan topadi"))
        self._find_places.clicked.connect(self._find_missing_places)
        self._finder = BulkPlaceFinder(self)
        self._finder.found.connect(self._on_place_found)
        self._finder.finished.connect(self._on_places_done)
        self._searching: list[Site] = []  # joylashuvi qidirilayotgan obyektlar
        self._located = 0  # shu qidiruvda joylashuvi topilganlari
        if session.can_modify:
            self.header_tools.addWidget(self._find_places)
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
        if not self._searching:
            self._find_places.setVisible(any(site.location is None for site in sites))
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
        show_all = button("", "link", Glyph.FIT)
        show_all.setToolTip(tr("Hamma obyektni ko'rsatish"))
        show_all.clicked.connect(self._map.show_all)
        header = QHBoxLayout()
        title = section_header(Glyph.PIN, tr("Xarita"))
        title.setToolTip(tr("Surish — sichqoncha bilan; kattalashtirish — g'ildirak yoki ikki marta bosish"))
        header.addWidget(title, stretch=1)
        header.addWidget(show_all)
        header.addWidget(open_button)
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self._map, stretch=1)
        return panel

    def _find_missing_places(self) -> None:
        """Joylashuvi yo'q obyektlarni internetdan qidiradi; topilganlari darhol xaritaga tushadi."""
        missing = [site for site in self._sites.all() if site.location is None]
        if not missing:
            return
        question = tr(
            "Joylashuvi yozilmagan {0} ta obyekt nomi va manzili bo'yicha internetdan qidiriladi "
            "(har biriga taxminan 1–2 soniya). Davom etilsinmi?"
        ).format(len(missing))
        if not confirm(self, tr("Joylashuvlarni topish"), question, tr("Ha, qidirish")):
            return
        self._searching, self._located = missing, 0
        self._find_places.setEnabled(False)
        self._show_search_progress(0)
        self._finder.find(missing)

    def _on_place_found(self, site_id: int, place: FoundPlace | None) -> None:
        done = next(index for index, site in enumerate(self._searching) if site.id == site_id) + 1
        self._show_search_progress(done)
        if place is None:
            return
        site = self._sites.get(site_id)
        self._sites.save(replace(site, latitude=place.location.latitude, longitude=place.location.longitude))
        self._located += 1
        self.refresh()

    def _on_places_done(self, completed: bool) -> None:
        total, located = len(self._searching), self._located
        self._searching = []
        self._find_places.setEnabled(True)
        self._find_places.setText(tr("Joylashuvlarni topish"))
        self.refresh()
        message = tr("{0} ta obyektdan {1} tasining joylashuvi topildi.").format(total, located)
        if located < total:
            message += " " + tr(
                "Topilmaganlarini ochib, manzilini aniqroq yozing (shahar, tuman, ko'cha) va «Topish»ni bosing."
            )
        if not completed:
            message = tr("Internetga ulanib bo'lmadi. {0}").format(message)
        QMessageBox.information(self, tr("Joylashuvlarni topish"), message)

    def _show_search_progress(self, done: int) -> None:
        self._find_places.setText(tr("Qidirilmoqda: {0} / {1}").format(done, len(self._searching)))

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
