"""Obyektlar va vozvrat oynalari: obyekt, obyektdan qaytgan mahsulot va obyektlar kesimidagi jadval."""

import threading
from typing import Sequence

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..errors import WarehouseError
from ..formatting import fmt_qty
from .. import geo
from ..geo import FoundPlace, LookupFailed, parse_location
from ..i18n import tr
from ..models import MovementDetails, MovementKind, ProductStock, Site, SiteProduct, SiteReturn
from ..sites import Sites
from ..warehouse import Warehouse
from .dialogs import FormDialog, product_box
from .icons import Glyph
from .printing import print_table
from .widgets import (
    Column,
    DataTable,
    button,
    confirm,
    date_input,
    export_to_excel,
    label,
    number_input,
    suggestion_box,
    table_card,
)

TABLE_DIALOG_SIZE = (860, 520)
UNIT_WIDTH = 90


class AddressFinder(QObject):
    """Manzil bo'yicha joyni internetdan fonda qidiradi; oyna bu paytda qotib qolmaydi."""

    # Qidirilgan matn va natija: FoundPlace — topildi, None — topilmadi, LookupFailed — ulanib bo'lmadi.
    finished = Signal(str, object)

    def find(self, address: str) -> None:
        def run() -> None:
            try:
                result = geo.find_address(address)
            except LookupFailed as failure:
                result = failure
            try:
                self.finished.emit(address, result)
            except RuntimeError:
                pass  # oyna yopilib bo'lgan: natijani yetkazadigan joy qolmagan

        threading.Thread(target=run, daemon=True).start()


class SiteDialog(FormDialog):
    """Yangi obyekt yoki mavjudini tahrirlash.

    Joylashuv bo'sh bo'lsa, u manzil (manzil yozilmagan bo'lsa — nom) bo'yicha internetdan o'zi
    topiladi: maydondan chiqilganda yoki «Saqlash» bosilganda. Internet bo'lmasa, obyekt
    joylashuvsiz saqlanadi — koordinatani keyin qo'lda kiritish mumkin.
    """

    def __init__(self, sites: Sites, site: Site | None = None, parent: QWidget | None = None):
        super().__init__(tr("Obyektni tahrirlash") if site else tr("Yangi obyekt"), parent)
        self._sites = sites
        self._site_id = site.id if site else None
        self.saved_id: int | None = None
        self._finder = AddressFinder(self)
        self._finder.finished.connect(self._on_place_found)
        self._searched = ""  # oxirgi qidirilgan matn: bir xil manzil qayta-qayta so'ralmaydi
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
        find.setToolTip(tr("Joylashuvni manzil bo'yicha internetdan topadi"))
        find.setAutoDefault(False)
        find.clicked.connect(lambda: self._find_location(replace=True))
        location_row = QHBoxLayout()
        location_row.addWidget(self._location, stretch=1)
        location_row.addWidget(find)
        self._location_hint = label(
            tr(
                "Manzil yozilsa, joylashuv internetdan o'zi topiladi. Qo'lda kiritish ham mumkin: "
                "Google Maps'da joyni o'ng tugma bilan bosing va birinchi qatorni (koordinatani) nusxalang."
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

    def _place_query(self) -> str:
        """Qidiriladigan matn: manzil, u yozilmagan bo'lsa — obyekt nomi."""
        return " ".join((self._address.text().strip() or self._name.text()).split())

    def _find_location(self, replace: bool = False) -> bool:
        """Joylashuvni fonda qidirishni boshlaydi; boshlangan bo'lsa — True.

        O'zi (maydondan chiqilganda) faqat joylashuv bo'sh yoki avval qidiruv yozgan bo'lsa qidiradi;
        `replace` — «Topish» tugmasi: foydalanuvchi yozgan koordinata ham almashtiriladi.
        """
        query = self._place_query()
        is_ours = self._location.text().strip() in ("", self._found_text)
        if not query or (not replace and (not is_ours or query == self._searched)):
            return False
        self._searched = query
        self._is_searching = True
        self._location_hint.setText(tr("Joylashuv qidirilmoqda…"))
        self._finder.find(query)
        return True

    def _on_place_found(self, query: str, result: FoundPlace | LookupFailed | None) -> None:
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
                    "Bu manzil xaritadan topilmadi. Aniqroq yozing (masalan: Toshkent, Yakkasaroy, 12) "
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


class ReturnDialog(FormDialog):
    """Obyektdan omborga qaytgan mahsulot (vozvrat); `movement` berilsa — tahrirlash.

    Obyekt tanlangach, mahsulotlar ro'yxatida avval shu obyektda turganlari chiqadi va
    qancha berilgani, qancha qaytgani ko'rsatiladi. Narx kiritilmaydi: dastur o'zi hisoblaydi.
    """

    def __init__(
        self,
        sites: Sites,
        warehouse: Warehouse,
        author: str,
        movement: MovementDetails | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(tr("Vozvratni tahrirlash") if movement else tr("Yangi vozvrat"), parent)
        self._sites = sites
        self._warehouse = warehouse
        self._author = author
        self._movement_id = movement.id if movement else None
        self._at_site: dict[int, SiteProduct] = {}  # tanlangan obyektdagi mahsulotlar: id -> berilgan/qaytgan
        self.saved_count = 0  # «Saqlash va yana qo'shish» bilan kiritilgan yozuvlar soni

        self._date = date_input(movement.date if movement else None, allow_future=False)
        self._doc_number = QLineEdit(movement.doc_number if movement else "")
        self._doc_number.setPlaceholderText(tr("Nakladnoy raqami (ixtiyoriy)"))
        self._store = QComboBox()
        for store in warehouse.stores():
            self._store.addItem(store.name, store.id)
        self._store.setCurrentIndex(max(self._store.findData(movement.warehouse_id if movement else None), 0))
        current = sites.find(movement.counterparty) if movement else None
        self._site = SitePicker(sites, current.id if current else None)
        self._product = product_box(tr("Tanlang yoki nomini yozing"))
        self._balance_hint = label("", "muted")
        self._quantity = number_input(3, movement.quantity if movement else 0)
        self._unit = QComboBox()  # mahsulotning qo'shimcha birligi bo'lsa, miqdorni shu birlikda kiritish mumkin
        self._unit.setMinimumWidth(UNIT_WIDTH)
        self._person = suggestion_box(
            warehouse.suggestions(MovementKind.IN, "person"), movement.person if movement else ""
        )
        self._note = QLineEdit(movement.note if movement else "")

        quantity_row = QHBoxLayout()
        quantity_row.addWidget(self._quantity, stretch=1)
        quantity_row.addWidget(self._unit)

        self.form.addRow(tr("Sana *"), self._date)
        self.form.addRow(tr("Qaysi omborga"), self._store)
        self.form.setRowVisible(self._store, self._store.count() > 1)
        self.form.addRow(tr("Obyekt *"), self._site)
        self.form.addRow(tr("Mahsulot *"), self._product)
        self.form.addRow("", self._balance_hint)
        self.form.addRow(tr("Qaytgan miqdor *"), quantity_row)
        self.add_extra_row(tr("Hujjat №"), self._doc_number)
        self.add_extra_row(tr("Kim olib keldi"), self._person)
        self.add_extra_row(tr("Izoh"), self._note)
        self.show_extras(movement is not None)

        self._saved_hint = label("", "muted")
        if movement is None:
            another = button(tr("Saqlash va yana qo'shish"))
            another.setAutoDefault(False)
            another.clicked.connect(self._save_and_continue)
            self.extra_buttons.addWidget(another)
            self.extra_buttons.addWidget(self._saved_hint)

        self._load_products(movement.product_id if movement else None)
        self._site.changed.connect(self._on_site_changed)
        self._product.currentTextChanged.connect(self._on_product_changed)
        self._on_product_changed()

    def accept(self) -> None:
        if self._quantity_accepted():
            super().accept()

    def save(self) -> None:
        site_id = self._site.require_site_id()
        product = self._selected_product()
        if product is None:
            raise WarehouseError(tr("Mahsulotni ro'yxatdan tanlang."))
        self._sites.save_return(
            SiteReturn(
                date=self._date.date().toPython(),
                site_id=site_id,
                product_id=product.id,
                quantity=self._base_quantity(),
                person=self._person.currentText(),
                note=self._note.text(),
                doc_number=self._doc_number.text(),
                created_by=self._author,
                warehouse_id=self._store.currentData(),
                id=self._movement_id,
            )
        )

    def _save_and_continue(self) -> None:
        """Yozuvni saqlab, oynani shu obyektning keyingi mahsuloti uchun ochiq qoldiradi."""
        if not self._quantity_accepted():
            return
        try:
            self.save()
        except WarehouseError as error:
            QMessageBox.warning(self, tr("Diqqat"), str(error))
            return
        self.saved_count += 1
        self._saved_hint.setText(tr("Saqlandi: {0} ta").format(self.saved_count))
        self._quantity.setValue(0)
        self._note.clear()
        self._load_products(None)
        self._on_product_changed()
        self._product.setFocus()

    def _on_site_changed(self) -> None:
        selected = self._selected_product()
        self._load_products(selected.id if selected else None)
        self._on_product_changed()

    def _load_products(self, select_id: int | None) -> None:
        """Mahsulotlar ro'yxati: avval tanlangan obyektda turganlari, keyin qolganlari."""
        site_id = self._site.site_id()
        self._at_site = {row.product_id: row for row in self._sites.products(site_id)} if site_id else {}
        products = [product for product in self._warehouse.products() if not product.is_service]
        products.sort(key=lambda product: (self._remaining(product.id) <= 0, product.name.casefold()))
        self._product.blockSignals(True)
        self._product.clear()
        for product in products:
            self._product.addItem(product.name, product)
        ids = [product.id for product in products]
        self._product.setCurrentIndex(ids.index(select_id) if select_id in ids else -1)
        self._product.blockSignals(False)

    def _selected_product(self) -> ProductStock | None:
        index = self._product.findText(self._product.currentText().strip(), Qt.MatchFlag.MatchFixedString)
        return self._product.itemData(index) if index >= 0 else None

    def _remaining(self, product_id: int) -> float:
        """Tanlangan obyektda shu mahsulotdan qancha turibdi (berilgan minus qaytgan), asosiy birlikda."""
        row = self._at_site.get(product_id)
        return row.remaining if row else 0.0

    def _base_quantity(self) -> float:
        """Kiritilgan miqdor asosiy birlikda (qo'shimcha birlik tanlangan bo'lsa — aylantirilgan)."""
        return self._quantity.value() * (self._unit.currentData() or 1.0)

    def _quantity_accepted(self) -> bool:
        """Yangi vozvratda miqdor obyektda turganidan ko'p bo'lsa, tasdiq so'raydi (tahrirlashda tekshirilmaydi)."""
        product = self._selected_product()
        if self._movement_id is not None or product is None or self._site.site_id() is None:
            return True
        if self._base_quantity() <= self._remaining(product.id):
            return True
        return confirm(
            self,
            tr("Vozvrat"),
            tr("Obyektda turganidan ko'p mahsulot qaytarilmoqda. Shunday saqlansinmi?"),
            tr("Ha, saqlash"),
        )

    def _on_product_changed(self) -> None:
        product = self._selected_product()
        self._unit.clear()
        if product is not None:
            self._unit.addItem(product.unit, 1.0)
            # Tahrirlashda miqdor asosiy birlikda saqlangan holicha ko'rsatiladi.
            if product.has_alt_unit and self._movement_id is None:
                self._unit.addItem(product.alt_unit, product.alt_factor)
        self._unit.setVisible(self._unit.count() > 1)
        self._quantity.setSuffix(f" {product.unit}" if product and self._unit.count() == 1 else "")
        self._balance_hint.setText(self._balance_text(product))

    def _balance_text(self, product: ProductStock | None) -> str:
        if product is None or self._site.site_id() is None:
            return ""
        row = self._at_site.get(product.id)
        if row is None:
            return tr("Bu mahsulot shu obyektga berilmagan")
        return tr("Berilgan: {0}  ·  qaytgan: {1}  ·  obyektda: {2} {3}").format(
            fmt_qty(row.issued), fmt_qty(row.returned), fmt_qty(row.remaining), product.unit
        )


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
