"""Vozvrat hujjati: obyektdan omborga qaytgan mahsulotlar — kirim/chiqim nakladnoyi kabi qator-qator.

Obyekt tanlangach, mahsulotlar ro'yxatida avval shu obyektda turganlari chiqadi va har bir qatorda obyektda
qancha qolgani ko'rinadi. Narx kiritilmaydi: mahsulot omborga obyektga berilgandagi tannarxda qaytadi.
"""

from typing import Callable, Sequence

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from ..config import CURRENCY
from ..errors import WarehouseError
from ..formatting import fmt_money, fmt_qty
from ..i18n import tr
from ..models import MovementDetails, MovementKind, ProductStock, SiteProduct, SiteReturn
from ..sites import Sites
from ..warehouse import Warehouse
from .dialogs import FormDialog, captioned, product_box, side_by_side
from .document_dialog import EMPTY_NUMBER, fit_lines_height, lines_table
from .icons import Glyph
from .site_dialogs import SitePicker
from .widgets import button, confirm, date_input, label, number_input, section_header, suggestion_box

DIALOG_WIDTH = 1000
PRODUCT, AT_SITE, UNIT, QUANTITY, PRICE, AMOUNT, REMOVE = range(7)
COLUMN_WIDTHS = {AT_SITE: 150, UNIT: 90, QUANTITY: 110, PRICE: 120, AMOUNT: 130, REMOVE: 48}


class ReturnLine(QObject):
    """Vozvrat qatori: mahsulot, obyektda qancha turgani, birlik, miqdor; tannarx va summa — o'zi hisoblanadi."""

    changed = Signal()

    def __init__(
        self,
        products: Sequence[ProductStock],
        at_site: Callable[[int], SiteProduct | None],
        cost: Callable[[int], float],
        movement: MovementDetails | None = None,
    ):
        """`at_site` — tanlangan obyektda shu mahsulotdan qancha berilgani/qaytgani; `cost` — 1 birlik tannarxi."""
        super().__init__()
        self.movement = movement
        self._at_site = at_site
        self._cost = cost
        self.product = product_box(tr("Tanlang yoki nomini yozing"))
        self.at_site = label("", "muted")
        self.unit = QComboBox()
        self.quantity = number_input(3)
        self.quantity.setSpecialValueText(EMPTY_NUMBER)
        self.price = label("", "muted")
        self.amount = label("", "muted")
        for field in (self.price, self.amount):
            field.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.remove = button("", "rowDelete", Glyph.DELETE)
        self.remove.setToolTip(tr("Qatorni olib tashlash"))
        self.remove.setAutoDefault(False)
        self.set_products(products)
        if movement is not None:
            self.select(movement.product_name)
            self.quantity.setValue(movement.quantity)
        self.refresh()
        self.product.currentTextChanged.connect(self._on_product_changed)
        self.unit.currentIndexChanged.connect(self._show_amount)
        self.quantity.valueChanged.connect(self._show_amount)

    @property
    def widgets(self) -> tuple[QWidget, ...]:
        return (self.product, self.at_site, self.unit, self.quantity, self.price, self.amount, self.remove)

    def set_products(self, products: Sequence[ProductStock]) -> None:
        """Ro'yxatni yangilaydi; tanlangan (yoki yozilgan) mahsulot o'z joyida qoladi."""
        text = self.product.currentText()
        self.product.blockSignals(True)
        self.product.clear()
        for product in products:
            self.product.addItem(product.name, product)
        self.product.setCurrentIndex(-1)
        self.product.setEditText(text)
        self.product.blockSignals(False)

    def selected(self) -> ProductStock | None:
        index = self.product.findText(self.product.currentText().strip(), Qt.MatchFlag.MatchFixedString)
        return self.product.itemData(index) if index >= 0 else None

    def select(self, name: str) -> None:
        self.product.setCurrentIndex(self.product.findText(name, Qt.MatchFlag.MatchFixedString))

    def is_blank(self) -> bool:
        return not self.product.currentText().strip() and not self.quantity.value()

    def base_quantity(self) -> float:
        """Miqdor asosiy birlikda (qo'shimcha birlik tanlangan bo'lsa — aylantirilgan)."""
        return self.quantity.value() * (self.unit.currentData() or 1.0)

    def remaining(self) -> float | None:
        """Obyektda qolgani (asosiy birlikda); mahsulot obyektga berilmagan bo'lsa — None."""
        product = self.selected()
        row = self._at_site(product.id) if product else None
        if row is None:
            return None
        # Tahrirlanayotgan qaytarish obyektdagi qoldiqdan allaqachon ayirilgan: u qaytadan qo'shiladi.
        same = self.movement is not None and self.movement.product_id == product.id
        return row.remaining + (self.movement.quantity if same else 0)

    def total(self) -> float:
        product = self.selected()
        return self.base_quantity() * self._cost(product.id) if product else 0.0

    def refresh(self) -> None:
        """Obyekt yoki mahsulot o'zgarganda: obyektdagi qoldiq, birliklar, tannarx va summa."""
        product = self.selected()
        unit = self.unit.currentIndex()
        self.unit.blockSignals(True)
        self.unit.clear()
        if product is not None:
            self.unit.addItem(product.unit, 1.0)
            if product.has_alt_unit:
                self.unit.addItem(product.alt_unit, product.alt_factor)
            self.unit.setCurrentIndex(max(min(unit, self.unit.count() - 1), 0))
        self.unit.blockSignals(False)
        self.unit.setEnabled(self.unit.count() > 1)
        remaining = self.remaining()
        if product is None:
            self.at_site.setText("")
        elif remaining is None:
            self.at_site.setText(tr("berilmagan"))
        else:
            self.at_site.setText(f"{fmt_qty(remaining)} {product.unit}")
        self._show_amount()

    def _on_product_changed(self) -> None:
        self.refresh()
        self.changed.emit()

    def _show_amount(self) -> None:
        product = self.selected()
        cost = self._cost(product.id) if product else 0.0
        self.price.setText(fmt_money(cost * (self.unit.currentData() or 1.0)) if product else "")
        self.amount.setText(fmt_money(self.total()) if self.total() else "")
        self.changed.emit()


class ReturnDialog(FormDialog):
    """Obyektdan qaytgan mahsulotlar (vozvrat hujjati); `movement` berilsa — u tegishli hujjat tahrirlanadi.

    Hammasi birga saqlanadi: biror qatorda xato bo'lsa, hech biri yozilmaydi.
    """

    def __init__(
        self,
        sites: Sites,
        warehouse: Warehouse,
        author: str,
        movement: MovementDetails | None = None,
        parent: QWidget | None = None,
    ):
        title = tr("Vozvratni tahrirlash") if movement else tr("Yangi vozvrat")
        super().__init__(title, parent)
        self.setMinimumWidth(DIALOG_WIDTH)
        self.set_header(Glyph.UNDO, "Accent", title, tr("Obyektdan omborga qaytgan mahsulotlar"))
        self._sites = sites
        self._warehouse = warehouse
        self._author = author
        self._lines: list[ReturnLine] = []
        self._removed_ids: list[int] = []
        self._at_site: dict[int, SiteProduct] = {}  # tanlangan obyektdagi mahsulotlar: id -> berilgan/qaytgan
        self.saved_ids: list[int] = []
        document = self._document(movement) if movement is not None else []
        first = document[0] if document else None

        self._date = date_input(first.date if first else None, allow_future=False)
        self._store = QComboBox()
        for store in warehouse.stores():
            self._store.addItem(store.name, store.id)
        self._store.setCurrentIndex(max(self._store.findData(first.warehouse_id if first else None), 0))
        current = sites.find(first.counterparty) if first else None
        self._site = SitePicker(sites, current.id if current else None)
        self._table = lines_table(
            [tr("Mahsulot"), tr("Obyektda"), tr("Birlik"), tr("Miqdor"), tr("Tannarx"), tr("Summa"), ""],
            COLUMN_WIDTHS,
            PRODUCT,
        )
        self._total = label("", "total")
        self._doc_number = QLineEdit(first.doc_number if first else "")
        self._doc_number.setPlaceholderText(tr("Nakladnoy raqami (ixtiyoriy)"))
        self._person = suggestion_box(warehouse.suggestions(MovementKind.IN, "person"), first.person if first else "")
        self._note = QLineEdit(first.note if first else "")

        store = captioned(tr("Qaysi omborga"), self._store)
        store.setVisible(self._store.count() > 1)

        top_card = QFrame()
        top_card.setObjectName("card")
        top_layout = QVBoxLayout(top_card)
        top_layout.setContentsMargins(16, 14, 16, 14)
        top_layout.setSpacing(12)
        top_layout.addWidget(
            side_by_side(
                captioned(tr("Obyekt *"), self._site), captioned(tr("Sana"), self._date), store, stretches=(3, 1, 1)
            )
        )

        self.form.addRow(top_card)
        self.form.addRow(section_header(Glyph.BOX, tr("Mahsulotlar")))
        self.form.addRow(self._table)
        hint = label(tr("Avval obyektni tanlang: unda turgan mahsulotlar ro'yxat boshida chiqadi."), "muted")
        below = QWidget()
        below_row = QHBoxLayout(below)
        below_row.setContentsMargins(0, 0, 0, 0)
        below_row.addWidget(hint)
        below_row.addStretch()
        below_row.addWidget(self._total)
        self.form.addRow(below)
        self.add_extra_row(
            "",
            side_by_side(captioned(tr("Hujjat №"), self._doc_number), captioned(tr("Kim olib keldi"), self._person)),
        )
        self.add_extra_row("", captioned(tr("Izoh"), self._note))

        self._load_site()
        for line_movement in document:
            self._add_line(line_movement)
        self._add_line()
        self.show_extras(bool(first and (first.doc_number or first.person or first.note)))
        self._site.changed.connect(self._on_site_changed)

    def line(self, index: int) -> ReturnLine:
        return self._lines[index]

    def accept(self) -> None:
        if self._quantities_accepted():
            super().accept()

    def save(self) -> None:
        site_id = self._site.require_site_id()
        returns = []
        for line in self._lines:
            if line.is_blank():
                continue
            product = line.selected()
            if product is None:
                raise WarehouseError(
                    tr("«{0}» ro'yxatda yo'q. Mahsulotni ro'yxatdan tanlang.").format(line.product.currentText().strip())
                )
            returns.append(
                SiteReturn(
                    date=self._date.date().toPython(),
                    site_id=site_id,
                    product_id=product.id,
                    quantity=line.base_quantity(),
                    person=self._person.currentText(),
                    note=self._note.text(),
                    doc_number=self._doc_number.text(),
                    created_by=self._author,
                    warehouse_id=self._store.currentData(),
                    id=line.movement.id if line.movement is not None else None,
                )
            )
        self.saved_ids = self._sites.save_returns(returns, self._removed_ids)

    # --- Ichki yordamchilar ------------------------------------------------

    def _document(self, movement: MovementDetails) -> list[MovementDetails]:
        """Yozuv tegishli vozvrat hujjati: shu obyektdan, shu kuni, shu raqam bilan qaytganlar."""
        site = movement.counterparty.casefold()
        document = [
            m for m in self._warehouse.document(movement.id) if m.is_return and m.counterparty.casefold() == site
        ]
        return document or [movement]

    def _quantities_accepted(self) -> bool:
        """Obyektda turganidan ko'p qaytarilayotgan mahsulotlar bo'lsa, tasdiq so'raydi."""
        if self._site.site_id() is None:
            return True
        too_many = [
            line.selected().name
            for line in self._lines
            if line.selected() is not None
            and line.base_quantity() > 0
            and line.base_quantity() > (line.remaining() or 0) + 1e-9
        ]
        if not too_many:
            return True
        return confirm(
            self,
            tr("Vozvrat"),
            tr("Obyektda turganidan ko'p qaytarilmoqda: {0}. Shunday saqlansinmi?").format(", ".join(too_many)),
            tr("Ha, saqlash"),
        )

    def _cost(self, product_id: int) -> float:
        site = self._site.site_name()
        return self._sites.issue_cost(site, product_id) if site else 0.0

    def _products(self) -> list[ProductStock]:
        """Mahsulotlar: avval tanlangan obyektda turganlari, keyin qolganlari (xizmatlarsiz)."""
        products = [product for product in self._warehouse.products() if not product.is_service]

        def remaining(product: ProductStock) -> float:
            row = self._at_site.get(product.id)
            return row.remaining if row else 0.0

        return sorted(products, key=lambda product: (remaining(product) <= 0, product.name.casefold()))

    def _load_site(self) -> None:
        site_id = self._site.site_id()
        self._at_site = {row.product_id: row for row in self._sites.products(site_id)} if site_id else {}

    def _on_site_changed(self) -> None:
        self._load_site()
        products = self._products()
        for line in self._lines:
            line.set_products(products)
            line.refresh()
        self._show_total()

    def _add_line(self, movement: MovementDetails | None = None) -> ReturnLine:
        # Obyekt o'zgarganda `_at_site` yangi lug'at bo'ladi: qator har safar joriysidan o'qiydi.
        line = ReturnLine(self._products(), lambda product_id: self._at_site.get(product_id), self._cost, movement)
        row = self._table.rowCount()
        self._table.insertRow(row)
        for column, widget in enumerate(line.widgets):
            self._table.setCellWidget(row, column, widget)
        fit_lines_height(self._table)
        self._lines.append(line)
        line.changed.connect(self._on_line_changed)
        line.remove.clicked.connect(lambda: self._remove_line(line))
        self._show_total()
        return line

    def _remove_line(self, line: ReturnLine) -> None:
        if line.movement is not None:
            self._removed_ids.append(line.movement.id)
        row = self._lines.index(line)
        self._lines.pop(row)
        self._table.removeRow(row)
        fit_lines_height(self._table)
        self._on_line_changed()

    def _on_line_changed(self) -> None:
        """Oxirgi qator to'ldirila boshlasa, ostidan yangi bo'sh qator ochiladi."""
        if not self._lines or not self._lines[-1].is_blank():
            self._add_line()
        self._show_total()

    def _show_total(self) -> None:
        total = sum(line.total() for line in self._lines)
        self._total.setText(tr("Jami: {0} {1}").format(fmt_money(total), CURRENCY))
