"""Obyekt oynalari: obyekt, obyekt tanlash va obyektlar kesimidagi jadval (vozvrat — return_dialog.py)."""

import threading
from typing import Sequence

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..errors import WarehouseError
from .. import geo
from ..geo import FoundPlace, LookupFailed, parse_location
from ..i18n import tr
from ..models import Site
from ..sites import Sites
from .dialogs import FormDialog
from .icons import Glyph
from .printing import print_table
from .widgets import Column, DataTable, button, export_to_excel, label, table_card

TABLE_DIALOG_SIZE = (860, 520)


class PlaceFinder(QObject):
    """Obyektni nomi va manzili bo'yicha internetdan fonda qidiradi; oyna bu paytda qotib qolmaydi."""

    # Qidirilgan (nom, manzil) va natija: FoundPlace — topildi, None — topilmadi, LookupFailed — ulanib bo'lmadi.
    finished = Signal(object, object)

    def find(self, name: str, address: str) -> None:
        def run() -> None:
            try:
                result = geo.find_place(name, address)
            except LookupFailed as failure:
                result = failure
            try:
                self.finished.emit((name, address), result)
            except RuntimeError:
                pass  # oyna yopilib bo'lgan: natijani yetkazadigan joy qolmagan

        threading.Thread(target=run, daemon=True).start()


class SiteDialog(FormDialog):
    """Yangi obyekt yoki mavjudini tahrirlash.

    Joylashuv bo'sh bo'lsa, u nom va manzil bo'yicha internetdan o'zi topiladi (qanday matn
    qidirilishi — `geo.place_queries` da): maydondan chiqilganda yoki «Saqlash» bosilganda.
    Internet bo'lmasa, obyekt joylashuvsiz saqlanadi — koordinatani keyin qo'lda kiritish mumkin.
    """

    def __init__(self, sites: Sites, site: Site | None = None, parent: QWidget | None = None):
        super().__init__(tr("Obyektni tahrirlash") if site else tr("Yangi obyekt"), parent)
        self._sites = sites
        self._site_id = site.id if site else None
        self.saved_id: int | None = None
        self._finder = PlaceFinder(self)
        self._finder.finished.connect(self._on_place_found)
        self._searched = ("", "")  # oxirgi qidirilgan (nom, manzil): bir xili qayta-qayta so'ralmaydi
        self._is_searching = False  # shu matn bo'yicha javob hali kelmagan
        self._found_text = ""  # qidiruv yozgan koordinata: foydalanuvchi o'zi yozganiga tegilmaydi
        self._saves_when_found = False  # «Saqlash» qidiruv tugashini kutyapti

        self._name = QLineEdit(site.name if site else "")
        self._name.setPlaceholderText(tr("Masalan: Chilonzor, 12-uy"))
        self._address = QLineEdit(site.address if site else "")
        self._manager = QLineEdit(site.manager if site else "")
        self._manager.setPlaceholderText(tr("Masalan: prorab ismi va telefoni"))
        self._note = QLineEdit(site.note if site else "")
        self._location = QLineEdit(str(site.location) if site and site.location else "")
        self._location.setPlaceholderText(tr("41.2856, 69.2034 yoki xarita havolasi (ixtiyoriy)"))
        find = button(tr("Topish"), glyph=Glyph.PIN)
        find.setToolTip(tr("Joylashuvni nom va manzil bo'yicha internetdan qayta topadi"))
        find.setAutoDefault(False)
        find.clicked.connect(lambda: self._find_location(replace=True))
        location_row = QHBoxLayout()
        location_row.addWidget(self._location, stretch=1)
        location_row.addWidget(find)
        self._location_hint = label(
            tr(
                "Joylashuv nom va manzil bo'yicha internetdan o'zi topiladi — shahar va tumanni ham yozing. "
                "Qo'lda: Google Maps'da joyni o'ng tugma bilan bosib, birinchi qatorni (koordinatani) nusxalang."
            ),
            "muted",
        )
        self._location_hint.setWordWrap(True)

        self.form.addRow(tr("Nomi *"), self._name)
        self.form.addRow(tr("Manzil"), self._address)
        self.form.addRow(tr("Joylashuv"), location_row)
        self.form.addRow("", self._location_hint)
        self.form.addRow(tr("Mas'ul shaxs"), self._manager)
        self.form.addRow(tr("Izoh"), self._note)
        self._name.editingFinished.connect(self._find_location)
        self._address.editingFinished.connect(self._find_location)

    def accept(self) -> None:
        """Joylashuv hali topilmagan bo'lsa, avval qidiradi va natija kelgach saqlaydi."""
        if self._find_location() or self._is_searching:
            self._saves_when_found = True
            self.setEnabled(False)
            return
        super().accept()

    def _find_location(self, replace: bool = False) -> bool:
        """Joylashuvni fonda qidirishni boshlaydi; boshlangan bo'lsa — True.

        O'zi (maydondan chiqilganda) faqat joylashuv bo'sh yoki avval qidiruv yozgan bo'lsa qidiradi;
        `replace` — «Topish» tugmasi: foydalanuvchi yozgan koordinata ham almashtiriladi.
        """
        query = (self._name.text().strip(), self._address.text().strip())
        is_ours = self._location.text().strip() in ("", self._found_text)
        if not any(query) or (not replace and (not is_ours or query == self._searched)):
            return False
        self._searched = query
        self._is_searching = True
        self._location_hint.setText(tr("Joylashuv qidirilmoqda…"))
        self._finder.find(*query)
        return True

    def _on_place_found(self, query: tuple[str, str], result: FoundPlace | LookupFailed | None) -> None:
        if query != self._searched:
            return  # shu orada manzil o'zgargan: bu eski javob, yangisi hali keladi
        self._is_searching = False
        self._show_place(result)
        if self._saves_when_found:
            self._saves_when_found = False
            self.setEnabled(True)
            super().accept()

    def _show_place(self, result: FoundPlace | LookupFailed | None) -> None:
        if isinstance(result, FoundPlace):
            self._found_text = str(result.location)
            self._location.setText(self._found_text)
            self._location_hint.setText(tr("Topildi: {0}").format(result.title))
        elif result is None:
            self._location_hint.setText(
                tr(
                    "Xaritadan topilmadi. Manzilni aniqroq yozing (masalan: Toshkent, Chilonzor 12-kvartal) "
                    "yoki koordinatani qo'lda kiriting."
                )
            )
        else:
            self._location_hint.setText(
                tr("Internetga ulanib bo'lmadi — joylashuv topilmadi. Koordinatani qo'lda kiritish mumkin.")
            )

    def save(self) -> None:
        location = parse_location(self._location.text())
        self.saved_id = self._sites.save(
            Site(
                name=self._name.text(),
                address=self._address.text(),
                manager=self._manager.text(),
                note=self._note.text(),
                id=self._site_id,
                latitude=location.latitude if location else None,
                longitude=location.longitude if location else None,
            )
        )


class SitePicker(QWidget):
    """Obyekt tanlash: ro'yxat va yonida «Yangi obyekt» tugmasi.

    Nom qo'lda yozilmaydi — shuning uchun bitta obyekt imlo xatosi bilan ikki xil bo'lib qolmaydi.
    """

    changed = Signal()

    def __init__(self, sites: Sites, selected_id: int | None = None):
        super().__init__()
        self._sites = sites
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)  # oyna cho'zilsa ham bo'yi o'smaydi
        self.combo = QComboBox()
        self.combo.setPlaceholderText(tr("Obyektni tanlang"))
        new_site = button(tr("Yangi obyekt"), glyph=Glyph.ADD)
        new_site.setAutoDefault(False)
        new_site.clicked.connect(self.add_site)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo, stretch=1)
        layout.addWidget(new_site)
        self._load(selected_id)
        self.combo.currentIndexChanged.connect(lambda: self.changed.emit())

    def site_id(self) -> int | None:
        return self.combo.currentData()

    def require_site_id(self) -> int:
        """Tanlangan obyekt; tanlanmagan bo'lsa — foydalanuvchiga tushunarli xato."""
        if self.site_id() is None:
            raise WarehouseError(tr("Obyektni tanlang. Ro'yxatda bo'lmasa, «Yangi obyekt» tugmasi bilan qo'shing."))
        return self.site_id()

    def site_name(self) -> str:
        return self.combo.currentText() if self.site_id() is not None else ""

    def select(self, site_id: int) -> None:
        self.combo.setCurrentIndex(self.combo.findData(site_id))

    def add_site(self) -> None:
        dialog = SiteDialog(self._sites, parent=self)
        if dialog.exec():
            self._load(dialog.saved_id)
            self.changed.emit()

    def _load(self, select_id: int | None) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        for site in self._sites.all():
            self.combo.addItem(site.name, site.id)
        self.combo.setCurrentIndex(self.combo.findData(select_id))
        self.combo.blockSignals(False)


class TableDialog(QDialog):
    """Faqat ko'rish uchun jadvalli oyna: sarlavha, izoh, jadval va «chop etish / Excel» tugmalari."""

    def __init__(
        self,
        title: str,
        subtitle: str,
        columns: Sequence[Column],
        rows: Sequence[Sequence],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(*TABLE_DIALOG_SIZE)
        self.table = DataTable(columns)
        self.table.set_rows(rows)

        print_button = button(tr("Chop etish"), "print", Glyph.PRINT)
        print_button.clicked.connect(lambda: print_table(self, self.table, title))
        excel = button(tr("Excelga chiqarish"), "excel", Glyph.EXPORT)
        excel.clicked.connect(lambda: export_to_excel(self, self.table, title))
        close = button(tr("Yopish"), "primary")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(print_button)
        buttons.addWidget(excel)
        buttons.addStretch()
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label(title, "sectionTitle"))
        layout.addWidget(label(subtitle, "muted"))
        layout.addWidget(table_card(self.table, paged=False), stretch=1)
        layout.addLayout(buttons)
