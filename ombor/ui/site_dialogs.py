"""Obyektlar va vozvrat oynalari: obyekt, obyektdan qaytgan mahsulot va obyektlar kesimidagi jadval."""

from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from ..errors import WarehouseError
from ..formatting import fmt_qty
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


class SiteDialog(FormDialog):
    """Yangi obyekt yoki mavjudini tahrirlash."""

    def __init__(self, sites: Sites, site: Site | None = None, parent: QWidget | None = None):
        super().__init__(tr("Obyektni tahrirlash") if site else tr("Yangi obyekt"), parent)
        self._sites = sites
        self._site_id = site.id if site else None
        self.saved_id: int | None = None

        self._name = QLineEdit(site.name if site else "")
        self._name.setPlaceholderText(tr("Masalan: Chilonzor, 12-uy"))
        self._address = QLineEdit(site.address if site else "")
        self._manager = QLineEdit(site.manager if site else "")
        self._manager.setPlaceholderText(tr("Masalan: prorab ismi va telefoni"))
        self._note = QLineEdit(site.note if site else "")

        self.form.addRow(tr("Nomi *"), self._name)
        self.form.addRow(tr("Manzil"), self._address)
        self.form.addRow(tr("Mas'ul shaxs"), self._manager)
        self.form.addRow(tr("Izoh"), self._note)

    def save(self) -> None:
        self.saved_id = self._sites.save(
            Site(self._name.text(), self._address.text(), self._manager.text(), self._note.text(), self._site_id)
        )


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
        self._site = QComboBox()
        self._site.setPlaceholderText(tr("Obyektni tanlang"))
        new_site = button(tr("Yangi obyekt"), glyph=Glyph.ADD)
        new_site.setAutoDefault(False)
        new_site.clicked.connect(self._add_site)
        self._product = product_box(tr("Tanlang yoki nomini yozing"))
        self._balance_hint = label("", "muted")
        self._quantity = number_input(3, movement.quantity if movement else 0)
        self._person = suggestion_box(
            warehouse.suggestions(MovementKind.IN, "person"), movement.person if movement else ""
        )
        self._note = QLineEdit(movement.note if movement else "")

        site_row = QHBoxLayout()
        site_row.addWidget(self._site, stretch=1)
        site_row.addWidget(new_site)

        self.form.addRow(tr("Sana *"), self._date)
        self.form.addRow(tr("Hujjat №"), self._doc_number)
        self.form.addRow(tr("Qaysi omborga"), self._store)
        self.form.setRowVisible(self._store, self._store.count() > 1)
        self.form.addRow(tr("Obyekt *"), site_row)
        self.form.addRow(tr("Mahsulot *"), self._product)
        self.form.addRow("", self._balance_hint)
        self.form.addRow(tr("Qaytgan miqdor *"), self._quantity)
        self.form.addRow(tr("Kim olib keldi"), self._person)
        self.form.addRow(tr("Izoh"), self._note)

        self._saved_hint = label("", "muted")
        if movement is None:
            another = button(tr("Saqlash va yana qo'shish"))
            another.setAutoDefault(False)
            another.clicked.connect(self._save_and_continue)
            self.extra_buttons.addWidget(another)
            self.extra_buttons.addWidget(self._saved_hint)

        current = sites.find(movement.counterparty) if movement else None
        self._load_sites(current.id if current else None)
        self._load_products(movement.product_id if movement else None)
        self._site.currentIndexChanged.connect(self._on_site_changed)
        self._product.currentTextChanged.connect(self._show_balance)
        self._show_balance()

    def accept(self) -> None:
        if self._quantity_accepted():
            super().accept()

    def save(self) -> None:
        if self._site.currentData() is None:
            raise WarehouseError(
                tr("Obyektni tanlang. Ro'yxatda bo'lmasa, «Yangi obyekt» tugmasi bilan qo'shing.")
            )
        product = self._selected_product()
        if product is None:
            raise WarehouseError(tr("Mahsulotni ro'yxatdan tanlang."))
        self._sites.save_return(
            SiteReturn(
                date=self._date.date().toPython(),
                site_id=self._site.currentData(),
                product_id=product.id,
                quantity=self._quantity.value(),
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
        self._show_balance()
        self._product.setFocus()

    def _add_site(self) -> None:
        dialog = SiteDialog(self._sites, parent=self)
        if dialog.exec():
            self._load_sites(dialog.saved_id)

    def _load_sites(self, select_id: int | None) -> None:
        self._site.blockSignals(True)
        self._site.clear()
        for site in self._sites.all():
            self._site.addItem(site.name, site.id)
        self._site.setCurrentIndex(self._site.findData(select_id))
        self._site.blockSignals(False)
        self._on_site_changed()

    def _on_site_changed(self) -> None:
        selected = self._selected_product()
        self._load_products(selected.id if selected else None)
        self._show_balance()

    def _load_products(self, select_id: int | None) -> None:
        """Mahsulotlar ro'yxati: avval tanlangan obyektda turganlari, keyin qolganlari."""
        site_id = self._site.currentData()
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
        """Tanlangan obyektda shu mahsulotdan qancha turibdi (berilgan minus qaytgan)."""
        row = self._at_site.get(product_id)
        return row.remaining if row else 0.0

    def _quantity_accepted(self) -> bool:
        """Yangi vozvratda miqdor obyektda turganidan ko'p bo'lsa, tasdiq so'raydi (tahrirlashda tekshirilmaydi)."""
        product = self._selected_product()
        if self._movement_id is not None or product is None or self._site.currentData() is None:
            return True
        if self._quantity.value() <= self._remaining(product.id):
            return True
        return confirm(
            self,
            tr("Vozvrat"),
            tr("Obyektda turganidan ko'p mahsulot qaytarilmoqda. Shunday saqlansinmi?"),
            tr("Ha, saqlash"),
        )

    def _show_balance(self) -> None:
        product = self._selected_product()
        self._quantity.setSuffix(f" {product.unit}" if product else "")
        if product is None or self._site.currentData() is None:
            self._balance_hint.setText("")
            return
        row = self._at_site.get(product.id)
        if row is None:
            self._balance_hint.setText(tr("Bu mahsulot shu obyektga berilmagan"))
            return
        self._balance_hint.setText(
            tr("Berilgan: {0}  ·  qaytgan: {1}  ·  obyektda: {2} {3}").format(
                fmt_qty(row.issued), fmt_qty(row.returned), fmt_qty(row.remaining), product.unit
            )
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
