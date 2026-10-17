"""Yangi kirim yoki chiqim hujjati (nakladnoy): umumiy ma'lumot bir marta, mahsulotlar — qator-qator."""

from enum import Enum
from typing import Sequence

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QWidget,
)

from ..config import CURRENCY
from ..errors import WarehouseError
from ..formatting import fmt_money, fmt_qty
from ..i18n import tr
from ..models import Movement, MovementDetails, MovementKind, ProductStock
from ..sites import Sites
from ..warehouse import Warehouse
from .dialogs import FormDialog, GroupFields, MovementDialog, ProductDialog, captioned, product_box, side_by_side
from .icons import Glyph
from .labels import KindLabels
from .printing import print_waybill
from .site_dialogs import SitePicker
from .widgets import button, date_input, label, number_input, suggestion_box

DIALOG_WIDTH = 1080
LINES_HEIGHT = 250  # to'rtta qator ko'rinadi; ko'pi aylantiriladi
ROW_HEIGHT = 48  # son maydoni sig'ishi uchun
# Jadval ustunlari va (cho'ziladigan «Mahsulot»dan boshqa) ularning kengliklari.
PRODUCT, STOCK, QUANTITY, UNIT, PRICE, AMOUNT, REMOVE = range(7)
COLUMN_WIDTHS = {STOCK: 105, QUANTITY: 110, UNIT: 95, PRICE: 130, AMOUNT: 125, REMOVE: 48}
EMPTY_NUMBER = " "  # 0 o'rniga bo'sh ko'rinadi: yozishni boshlash oson


class IssueTarget(Enum):
    """Chiqim kimga: obyektga (ichki rasxod), xaridorga (sotuv) yoki obyektsiz boshqa rasxod."""

    SITE = tr("Obyektga")
    SALE = tr("Sotuv (xaridorga)")
    OTHER = tr("Boshqa rasxod (obyektsiz)")


def can_edit_as_document(movements: Sequence[MovementDetails]) -> bool:
    """Yozuvlarni bitta nakladnoy oynasida tahrirlash mumkinmi.

    Bir nechta mahsulotli, qaytarishsiz va umumiy maydonlari (ombor, kimdan/kimga, kim, izoh,
    qarzga, sotuv yoki sotuv emasligi) bir xil hujjat — mumkin. Qolgani bittalab to'liq shaklda.
    """
    if len(movements) < 2 or any(movement.is_return for movement in movements):
        return False
    shared = {(m.warehouse_id, m.counterparty, m.person, m.note, m.on_credit, m.sale_price > 0) for m in movements}
    return len(shared) == 1


class DocumentLine(QObject):
    """Hujjatning bitta qatori: mahsulot, miqdor, birlik va narx maydonlari."""

    changed = Signal()

    def __init__(self, products: Sequence[ProductStock], suggests_price: bool, movement: MovementDetails | None = None):
        """`suggests_price` — kirimda: mahsulot tanlanganda uning oldingi o'rtacha narxi taklif qilinadi.

        `movement` — tahrirlanayotgan hujjatning shu qatordagi yozuvi (yangi qatorda — None).
        """
        super().__init__()
        self.movement = movement
        self._suggests_price = suggests_price
        self._suggested_price = 0.0
        self.product = product_box()
        self.stock = label("", "muted")
        self.quantity = number_input(3)
        self.unit = QComboBox()
        self.price = number_input(2)
        for field in (self.quantity, self.price):
            field.setSpecialValueText(EMPTY_NUMBER)
        self.amount = label("", "muted")
        self.amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.remove = button("", "rowDelete", Glyph.DELETE)
        self.remove.setToolTip(tr("Qatorni olib tashlash"))
        self.remove.setAutoDefault(False)
        self.set_products(products)
        if movement is not None:
            self.select(movement.product_name)
            self._show_product()
            self.quantity.setValue(movement.quantity)
            self.price.setValue(movement.sale_price if movement.kind is MovementKind.OUT else movement.price)
            self._on_numbers_changed()
        self.product.currentTextChanged.connect(self._on_product_changed)
        self.unit.currentIndexChanged.connect(self._on_unit_changed)
        self.quantity.valueChanged.connect(self._on_numbers_changed)
        self.price.valueChanged.connect(self._on_numbers_changed)

    @property
    def widgets(self) -> tuple[QWidget, ...]:
        """Maydonlar jadval ustunlari tartibida."""
        return (self.product, self.stock, self.quantity, self.unit, self.price, self.amount, self.remove)

    def set_products(self, products: Sequence[ProductStock]) -> None:
        """Ro'yxatni (tanlangan ombordagi qoldiqlar bilan) yangilaydi; tanlangan mahsulot o'z joyida qoladi."""
        text = self.product.currentText()
        self.product.blockSignals(True)
        self.product.clear()
        for product in products:
            self.product.addItem(product.name, product)
        self.product.setCurrentIndex(-1)
        self.product.setEditText(text)
        self.product.blockSignals(False)
        self._show_product()

    def selected(self) -> ProductStock | None:
        index = self.product.findText(self.product.currentText().strip(), Qt.MatchFlag.MatchFixedString)
        return self.product.itemData(index) if index >= 0 else None

    def select(self, name: str) -> None:
        self.product.setCurrentIndex(self.product.findText(name, Qt.MatchFlag.MatchFixedString))

    def is_blank(self) -> bool:
        """Hech narsa kiritilmagan qator: saqlashda hisobga olinmaydi."""
        return not self.product.currentText().strip() and not self.quantity.value()

    def factor(self) -> float:
        """Tanlangan birlik necha asosiy birlikka teng (asosiy birlikning o'zi — 1)."""
        return self.unit.currentData() or 1.0

    def total(self) -> float:
        return self.quantity.value() * self.price.value()

    def _on_product_changed(self) -> None:
        self._show_product()
        self.changed.emit()

    def _on_unit_changed(self) -> None:
        self._suggest_price()
        self._on_numbers_changed()

    def _on_numbers_changed(self) -> None:
        self.amount.setText(fmt_money(self.total()) if self.total() else "")
        self.changed.emit()

    def _show_product(self) -> None:
        """Tanlangan mahsulotning qoldig'i va birliklarini ko'rsatadi."""
        product = self.selected()
        self.unit.blockSignals(True)
        self.unit.clear()
        if product is None:
            self.stock.setText("")
        else:
            self.stock.setText(tr("Xizmat") if product.is_service else f"{fmt_qty(product.stock)} {product.unit}")
            self.unit.addItem(product.unit, 1.0)
            if product.has_alt_unit:
                self.unit.addItem(product.alt_unit, product.alt_factor)
        self.unit.blockSignals(False)
        self.unit.setEnabled(self.unit.count() > 1)
        self._suggest_price()

    def _suggest_price(self) -> None:
        """Kirimda oldingi o'rtacha narxni taklif qiladi; qo'lda yozilgan narxga tegmaydi."""
        product = self.selected()
        if self._suggests_price and product is not None and self.price.value() in (0, self._suggested_price):
            self._suggested_price = round(product.average_price * self.factor(), 2)
            self.price.setValue(self._suggested_price)


class DocumentDialog(FormDialog):
    """Kirim yoki chiqim hujjati: sana va kimdan/kimga bir marta, mahsulotlar jadvalda qator-qator kiritiladi.

    Hammasi birga saqlanadi: biror qatorda xato bo'lsa, hech biri yozilmaydi. Mahsulot tanlangan
    zahoti ostidan yangi bo'sh qator ochiladi. Chiqimda obyekt ro'yxatdan tanlanadi; sotuv va
    obyektsiz rasxod — «Chiqim turi»da. Kam uchraydigan hollar (qaytarish) uchun — «To'liq shakl».
    `document` berilsa — o'sha hujjat tahrirlanadi (`can_edit_as_document` ga qarang).
    """

    def __init__(
        self,
        warehouse: Warehouse,
        sites: Sites,
        labels: KindLabels,
        author: str,
        parent: QWidget | None = None,
        document: Sequence[MovementDetails] = (),
    ):
        title = (
            tr("{0}ni tahrirlash").format(labels.title) if document else tr("Yangi {0}").format(labels.title.lower())
        )
        super().__init__(title, parent)
        self.setMinimumWidth(DIALOG_WIDTH)
        if labels.kind is MovementKind.IN:
            self.set_header(Glyph.RECEIPT, "Good", title, tr("Omborga mahsulot keldi: kimdan va nima keldi"))
        else:
            self.set_header(Glyph.ISSUE, "Out", title, tr("Ombordan mahsulot chiqdi: qayerga va nima ketdi"))
        self._warehouse = warehouse
        self._sites = sites
        self._labels = labels
        self._author = author
        self._is_receipt = labels.kind is MovementKind.IN
        self._lines: list[DocumentLine] = []
        self._removed_ids: list[int] = []  # tahrirlashda olib tashlangan qatorlar yozuvlari
        self._prints = False  # «Saqlash va chop etish» bosilgan
        self.saved_ids: list[int] = []

        self._date = date_input(document[0].date if document else None, allow_future=False)
        self._store = QComboBox()
        for store in warehouse.stores():
            self._store.addItem(store.name, store.id)
        self._target = QComboBox()
        for target in IssueTarget:
            self._target.addItem(target.value, target)
        self._site = SitePicker(sites)
        self._supplier = suggestion_box(warehouse.suggestions(MovementKind.IN, "counterparty"))
        self._customer = suggestion_box(warehouse.customers())
        self._table = self._build_table()
        self._total = label("", "total")
        self._doc_number = QLineEdit()
        self._doc_number.setPlaceholderText(tr("Nakladnoy raqami (ixtiyoriy)"))
        self._person = suggestion_box(warehouse.suggestions(labels.kind, "person"))
        self._groups = GroupFields()
        self._on_credit = QCheckBox(tr("Qarzga (to'lov keyin bo'ladi)"))
        self._on_credit.setToolTip(tr("Belgilansa, summa «Qarzlar» bo'limida shu kontragent hisobiga yoziladi."))
        self._note = QLineEdit()

        # 1) Kimdan / qayerga va qachon. 2) Mahsulotlar jadvali. 3) Qo'shimcha maydonlar (yig'iq).
        store = captioned(tr("Ombor"), self._store)
        store.setVisible(self._store.count() > 1)
        if self._is_receipt:
            self.form.addRow(
                side_by_side(
                    captioned(labels.counterparty, self._supplier),
                    captioned(tr("Sana"), self._date),
                    store,
                    stretches=(3, 1, 1),
                )
            )
        else:
            self._target.setVisible(False)  # o'rniga yaqqol tugmalar; ro'yxat holatni saqlaydi
            self.form.addRow(captioned(tr("Mahsulot qayerga ketyapti?"), self._target_buttons()))
            self._site_field = captioned(tr("Obyekt *"), self._site)
            self._customer_field = captioned(tr("Xaridor"), self._customer)
            self.form.addRow(
                side_by_side(
                    self._site_field,
                    self._customer_field,
                    captioned(tr("Sana"), self._date),
                    store,
                    stretches=(3, 3, 1, 1),
                )
            )
            self.form.addRow(self._target)
        self.form.addRow(label(tr("Mahsulotlar"), "fieldCaption"))
        self.form.addRow(self._table)
        new_product = button(tr("Ro'yxatda yo'q mahsulot qo'shish"), "link", Glyph.ADD)
        new_product.setAutoDefault(False)
        new_product.clicked.connect(self._add_product)
        hint = label(tr("Mahsulotni tanlang yoki nomini yozing — ostidan yangi qator o'zi ochiladi."), "muted")
        below = QWidget()
        below_row = QHBoxLayout(below)
        below_row.setContentsMargins(0, 0, 0, 0)
        below_row.addWidget(hint)
        below_row.addWidget(new_product)
        below_row.addStretch()
        below_row.addWidget(self._total)
        self.form.addRow(below)
        group_title = tr("Guruh *") if warehouse.group_required else tr("Guruh")
        self.add_extra_row(
            "", side_by_side(captioned(tr("Hujjat №"), self._doc_number), captioned(labels.person, self._person))
        )
        self.add_extra_row(
            "",
            side_by_side(
                captioned(group_title, self._groups.group), captioned(tr("Kategoriya"), self._groups.subgroup)
            ),
        )
        self.add_extra_row("", side_by_side(captioned(tr("Izoh"), self._note), captioned(" ", self._on_credit)))
        self._groups.group.setToolTip(tr("Tanlanmasa, har bir mahsulotning oxirgi yozuvidagi guruhi olinadi."))

        if not document:
            full_form = button(tr("Qaytarish yoki boshqa holat"), "link")
            full_form.setToolTip(
                tr("Bitta mahsulot uchun barcha maydonlar: qaytarish va boshqa kam uchraydigan hollar")
            )
            full_form.setAutoDefault(False)
            full_form.clicked.connect(self._open_full_form)
            self.extra_buttons.addWidget(full_form)
        save_and_print = button(tr("Saqlash va chop etish"), "print", Glyph.PRINT)
        save_and_print.setToolTip(tr("Saqlaydi va nakladnoyni chop etish oynasini ochadi"))
        save_and_print.setAutoDefault(False)
        save_and_print.clicked.connect(self._save_and_print)
        self.extra_buttons.addWidget(save_and_print)

        if document:
            self._fill(document)
        self._add_line()
        has_extras = any((self._doc_number.text(), self._person.currentText(), self._note.text()))
        # Guruh majburiy bo'lsa yoki tahrirlanayotgan hujjatda qo'shimcha maydonlar to'ldirilgan bo'lsa — ochiq.
        self.show_extras(warehouse.group_required or (bool(document) and has_extras))
        self._store.currentIndexChanged.connect(self._reload_products)
        self._target.currentIndexChanged.connect(self._show_target)
        self._show_target()

    def accept(self) -> None:
        if self._select_by_barcode():
            return  # skaner koddan keyin Enter yuboradi: mahsulot tanlanadi, oyna yopilmaydi
        super().accept()

    def save(self) -> None:
        counterparty = self._counterparty()
        self.saved_ids = self._warehouse.save_document(
            [self._movement(line, counterparty) for line in self._lines if not line.is_blank()], self._removed_ids
        )
        if self._prints:
            print_waybill(self, self._warehouse.document(self.saved_ids[0]), self._labels)

    def _save_and_print(self) -> None:
        self._prints = True
        try:
            self.accept()
        finally:
            self._prints = False

    def line(self, index: int) -> DocumentLine:
        return self._lines[index]

    # --- Hujjat maydonlari ---------------------------------------------------

    def _fill(self, document: Sequence[MovementDetails]) -> None:
        """Tahrirlanadigan hujjatning umumiy maydonlari va qatorlari."""
        first = document[0]
        self._store.setCurrentIndex(max(self._store.findData(first.warehouse_id), 0))
        if self._is_receipt:
            self._supplier.setCurrentText(first.counterparty)
        else:
            site = self._sites.find(first.counterparty) if first.counterparty else None
            target = IssueTarget.SALE if first.sale_price > 0 else IssueTarget.SITE if site else IssueTarget.OTHER
            self._target.setCurrentIndex(self._target.findData(target))
            if site is not None:
                self._site.select(site.id)
            self._customer.setCurrentText(first.counterparty if target is IssueTarget.SALE else "")
        self._doc_number.setText(first.doc_number)
        self._person.setCurrentText(first.person)
        self._on_credit.setChecked(first.on_credit)
        self._note.setText(first.note)
        for movement in document:
            self._add_line(movement)

    def _target_kind(self) -> IssueTarget | None:
        """Chiqim kimga; kirimda — None."""
        return None if self._is_receipt else self._target.currentData()

    def _has_prices(self) -> bool:
        """Narx kiritiladimi: kirimda — xarid narxi, sotuvda — sotuv narxi; ichki rasxodda narx yo'q."""
        return self._is_receipt or self._target_kind() is IssueTarget.SALE

    def _counterparty(self) -> str:
        if self._is_receipt:
            return self._supplier.currentText()
        target = self._target_kind()
        if target is IssueTarget.SITE:
            self._site.require_site_id()
            return self._site.site_name()
        return self._customer.currentText() if target is IssueTarget.SALE else ""

    def _movement(self, line: DocumentLine, counterparty: str) -> Movement:
        product = line.selected()
        if product is None:
            raise WarehouseError(
                tr(
                    "«{0}» ro'yxatda yo'q. Mahsulotni ro'yxatdan tanlang yoki avval uni «Mahsulotlar»ga qo'shing."
                ).format(line.product.currentText().strip())
            )
        price = line.price.value() / line.factor() if self._has_prices() else 0.0
        if self._target_kind() is IssueTarget.SALE and not price:
            raise WarehouseError(tr("«{0}»: sotuv narxini kiriting.").format(product.name))
        # Guruh: oynada tanlangani; tanlanmagan bo'lsa — qatorning o'z guruhi yoki mahsulotning oxirgi guruhi.
        category, subcategory = self._groups.category(), self._groups.subcategory()
        if not category and line.movement is not None:
            category, subcategory = line.movement.category, line.movement.subcategory
        if not category:
            category, subcategory = self._warehouse.default_group(product.id)
        return Movement(
            kind=self._labels.kind,
            date=self._date.date().toPython(),
            product_id=product.id,
            quantity=line.quantity.value() * line.factor(),
            price=price if self._is_receipt else 0.0,
            sale_price=0.0 if self._is_receipt else price,
            category=category,
            subcategory=subcategory,
            person=self._person.currentText(),
            counterparty=counterparty,
            note=self._note.text(),
            created_by=self._author,
            doc_number=self._doc_number.text(),
            on_credit=self._on_credit.isChecked(),
            warehouse_id=self._store.currentData(),
            id=line.movement.id if line.movement is not None else None,
        )

    def _show_target(self) -> None:
        """Chiqim turiga qarab: obyekt yoki xaridor maydoni, narx ustunlari va jami."""
        target = self._target_kind()
        if not self._is_receipt:
            self._site_field.setVisible(target is IssueTarget.SITE)
            self._customer_field.setVisible(target is IssueTarget.SALE)
            for button_target, choice in self._target_choices.items():
                choice.setChecked(button_target is target)
        priced = self._has_prices()
        for column in (PRICE, AMOUNT):
            self._table.setColumnHidden(column, not priced)
        self._total.setVisible(priced)
        price_title = tr("Narxi") if self._is_receipt else tr("Sotuv narxi")
        self._table.horizontalHeaderItem(PRICE).setText(price_title)
        self._show_total()
        self.adjustSize()

    def _target_buttons(self) -> QFrame:
        """Chiqim turi — uchta yaqqol tugma (ro'yxat o'rniga): bir bosishda tanlanadi."""
        bar = QFrame()
        bar.setObjectName("segmentBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(2)
        group = QButtonGroup(bar)
        self._target_choices: dict[IssueTarget, QPushButton] = {}
        for target in IssueTarget:
            choice = button(target.value, "segment")
            choice.setCheckable(True)
            choice.setAutoDefault(False)
            choice.clicked.connect(
                lambda _=False, target=target: self._target.setCurrentIndex(self._target.findData(target))
            )
            group.addButton(choice)
            row.addWidget(choice)
            self._target_choices[target] = choice
        row.addStretch()
        return bar

    def _add_product(self) -> None:
        """Ro'yxatda yo'q mahsulotni shu yerning o'zida qo'shadi va bo'sh qatorga tanlab qo'yadi."""
        dialog = ProductDialog(self._warehouse, parent=self)
        if not dialog.exec():
            return
        self._reload_products()
        name = self._warehouse.product(dialog.saved_id).name
        blank = next((line for line in self._lines if line.selected() is None), None) or self._add_line()
        blank.select(name)
        blank.quantity.setFocus()

    def _open_full_form(self) -> None:
        """Shu oyna o'rniga bitta yozuvning to'liq shaklini ochadi."""
        self.hide()
        full_form = MovementDialog(self._warehouse, self._labels, self._author, parent=self.parentWidget())
        self.done(full_form.exec())

    # --- Qatorlar ------------------------------------------------------------

    def _build_table(self) -> QTableWidget:
        table = QTableWidget(0, len(COLUMN_WIDTHS) + 1)
        table.setHorizontalHeaderLabels(
            [tr("Mahsulot"), tr("Omborda"), tr("Miqdor"), tr("Birlik"), tr("Narxi"), tr("Summa"), ""]
        )
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setShowGrid(False)
        table.setFixedHeight(LINES_HEIGHT)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(PRODUCT, QHeaderView.ResizeMode.Stretch)
        for column, width in COLUMN_WIDTHS.items():
            table.setColumnWidth(column, width)
        return table

    def _products(self) -> list[ProductStock]:
        return self._warehouse.products(warehouse_id=self._store.currentData())

    def _add_line(self, movement: MovementDetails | None = None) -> DocumentLine:
        line = DocumentLine(self._products(), self._is_receipt, movement)
        row = self._table.rowCount()
        self._table.insertRow(row)
        for column, widget in enumerate(line.widgets):
            self._table.setCellWidget(row, column, widget)
        self._lines.append(line)
        line.changed.connect(self._on_line_changed)
        line.remove.clicked.connect(lambda: self._remove_line(line))
        return line

    def _remove_line(self, line: DocumentLine) -> None:
        if line.movement is not None:
            self._removed_ids.append(line.movement.id)
        row = self._lines.index(line)
        self._lines.pop(row)
        self._table.removeRow(row)
        self._on_line_changed()

    def _on_line_changed(self) -> None:
        """Oxirgi qator to'ldirila boshlasa, ostidan yangi bo'sh qator ochiladi."""
        if not self._lines or not self._lines[-1].is_blank():
            self._add_line()
        self._show_total()

    def _reload_products(self) -> None:
        products = self._products()
        for line in self._lines:
            line.set_products(products)

    def _show_total(self) -> None:
        total = sum(line.total() for line in self._lines)
        self._total.setText(tr("Jami: {0} {1}").format(fmt_money(total), CURRENCY))

    def _select_by_barcode(self) -> bool:
        """Mahsulot maydoniga shtrix-kod yozilgan (o'qitilgan) qatorlarda shu mahsulotni tanlaydi."""
        found_any = False
        for line in list(self._lines):
            if line.selected() is not None:
                continue
            found = self._warehouse.product_by_barcode(line.product.currentText())
            if found is not None:
                line.select(found.name)
                line.quantity.setFocus()
                line.quantity.selectAll()
                found_any = True
        return found_any
