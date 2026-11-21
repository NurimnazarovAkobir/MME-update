"""Yangi kirim yoki chiqim hujjati (nakladnoy): umumiy ma'lumot bir marta, mahsulotlar — qator-qator.

Qatorning ustunlari Excel hisobidagi kabi: nomi, o'lchov birligi, miqdori, narxi, summasi va guruhi. Narx
yoki summadan istalgani yoziladi — ikkinchisi o'zi hisoblanadi.
"""

from enum import Enum
from typing import Callable, Sequence

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QWidget,
)

from ..catalog import display_name, groups
from ..config import CURRENCY, UNITS
from ..errors import WarehouseError
from ..formatting import fmt_money, fmt_qty
from ..i18n import tr
from ..models import Movement, MovementDetails, MovementKind, Product, ProductStock
from ..sites import Sites
from ..warehouse import Warehouse
from .dialogs import (
    NO_GROUP,
    FormDialog,
    MovementDialog,
    PaymentFields,
    ProductDialog,
    captioned,
    product_box,
    side_by_side,
)
from .icons import Glyph
from .labels import KindLabels
from .printing import print_waybill
from .site_dialogs import SitePicker
from .widgets import button, confirm, date_input, label, number_input, suggestion_box

DIALOG_WIDTH = 1180
ROW_HEIGHT = 48  # son maydoni sig'ishi uchun
VISIBLE_ROWS = (2, 6)  # jadval bo'yi qatorlar soniga qarab shu oraliqda o'zgaradi; ko'pi aylantiriladi
# Jadval ustunlari (Excel hisobidagi tartibda) va (cho'ziladigan «Mahsulot»dan boshqa) ularning kengliklari.
PRODUCT, STOCK, UNIT, QUANTITY, PRICE, AMOUNT, GROUP, REMOVE = range(8)
COLUMN_WIDTHS = {STOCK: 100, UNIT: 105, QUANTITY: 105, PRICE: 125, AMOUNT: 140, GROUP: 195, REMOVE: 48}
EMPTY_NUMBER = " "  # 0 o'rniga bo'sh ko'rinadi: yozishni boshlash oson


class IssueTarget(Enum):
    """Chiqim kimga: obyektga (ichki rasxod), xaridorga (sotuv) yoki obyektsiz boshqa rasxod."""

    SITE = tr("Obyektga")
    SALE = tr("Sotuv (xaridorga)")
    OTHER = tr("Boshqa rasxod (obyektsiz)")


def can_edit_as_document(movements: Sequence[MovementDetails]) -> bool:
    """Yozuvlarni bitta nakladnoy oynasida tahrirlash mumkinmi.

    Bir nechta mahsulotli, qaytarishsiz va umumiy maydonlari (ombor, kimdan/kimga, kim, izoh, qarzga,
    to'lov turi va holati, sotuv yoki sotuv emasligi) bir xil hujjat — mumkin. Qolgani bittalab to'liq shaklda.
    """
    if len(movements) < 2 or any(movement.is_return for movement in movements):
        return False
    shared = {
        (m.warehouse_id, m.counterparty, m.person, m.note, m.on_credit, m.payment, m.unpaid, m.sale_price > 0)
        for m in movements
    }
    return len(shared) == 1


def lines_table(headers: Sequence[str], widths: dict[int, int], stretch: int) -> QTableWidget:
    """Hujjat qatorlari jadvali: har bir katakda maydon; `stretch` ustuni qolgan joyni egallaydi."""
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setShowGrid(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    for column, width in widths.items():
        table.setColumnWidth(column, width)
    fit_lines_height(table)
    return table


def fit_lines_height(table: QTableWidget) -> None:
    """Jadval bo'yi qatorlar soniga moslanadi: bo'sh joy qolmaydi, ko'p qator bo'lsa — aylantiriladi."""
    low, high = VISIBLE_ROWS
    rows = min(max(table.rowCount(), low), high)
    frame = 2 * table.frameWidth()
    table.setFixedHeight(table.horizontalHeader().sizeHint().height() + rows * ROW_HEIGHT + frame)


def group_box() -> QComboBox:
    """Guruh (Excel'dagi «группа расхода») tanlash ro'yxati."""
    box = QComboBox()
    box.addItem(NO_GROUP, "")
    for group in groups():
        box.addItem(group.name.display, group.name.ru)
    return box


class DocumentLine(QObject):
    """Hujjatning bitta qatori: mahsulot, birlik, miqdor, narx, summa va guruh maydonlari."""

    changed = Signal()

    def __init__(
        self,
        products: Sequence[ProductStock],
        suggests_price: bool,
        default_group: Callable[[int], tuple[str, str]],
        movement: MovementDetails | None = None,
    ):
        """`suggests_price` — kirimda: mahsulot tanlanganda uning oldingi o'rtacha narxi taklif qilinadi.

        `default_group` — mahsulot tanlanganda taklif qilinadigan guruh va kategoriya (mahsulot id bo'yicha).
        `movement` — tahrirlanayotgan hujjatning shu qatordagi yozuvi (yangi qatorda — None).
        """
        super().__init__()
        self.movement = movement
        self._suggests_price = suggests_price
        self._default_group = default_group
        self._suggested_price = 0.0
        self._suggested_subcategory = ("", "")  # (guruh, kategoriya): taklif qilingan guruhning kategoriyasi
        self._syncing = False  # narx ↔ summa bir-birini hisoblayotganda qayta chaqirilmasin
        self._shows_cost = False  # obyektga chiqimda: narx o'rnida tannarx (o'zgartirilmaydi)
        self.product = product_box()
        self.stock = label("", "muted")
        self.unit = QComboBox()
        self.quantity = number_input(3)
        self.price = number_input(2)
        self.amount = number_input(2)
        self.amount.setToolTip(tr("Summani yozsangiz, narx o'zi hisoblanadi"))
        for field in (self.quantity, self.price, self.amount):
            field.setSpecialValueText(EMPTY_NUMBER)
        self.group = group_box()
        self.remove = button("", "rowDelete", Glyph.DELETE)
        self.remove.setToolTip(tr("Qatorni olib tashlash"))
        self.remove.setAutoDefault(False)
        self.set_products(products)
        if movement is not None:
            self.select(movement.product_name)
            self._show_product()
            self.select_group(movement.category)
            self.quantity.setValue(movement.quantity)
            self.price.setValue(movement.sale_price if movement.kind is MovementKind.OUT else movement.price)
            self._price_changed()
        self.product.currentTextChanged.connect(self._on_product_changed)
        self.unit.currentIndexChanged.connect(self._on_unit_changed)
        self.quantity.valueChanged.connect(self._quantity_changed)
        self.price.valueChanged.connect(self._price_changed)
        self.amount.valueChanged.connect(self._amount_changed)

    @property
    def widgets(self) -> tuple[QWidget, ...]:
        """Maydonlar jadval ustunlari tartibida."""
        return (self.product, self.stock, self.unit, self.quantity, self.price, self.amount, self.group, self.remove)

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

    def select_group(self, category: str) -> None:
        """Guruhni tanlaydi; ro'yxatda yo'q (eski yoki o'chirilgan) guruh bo'lsa, uni ham qo'shadi."""
        if category and self.group.findData(category) < 0:
            self.group.addItem(display_name(category), category)
        self.group.setCurrentIndex(max(self.group.findData(category), 0))

    def category(self) -> str:
        return self.group.currentData() or ""

    def subcategory(self) -> str:
        """Kategoriya: yozuvniki yoki taklif qilingan guruhniki — guruh o'zgarmagan bo'lsa; aks holda bo'sh."""
        category = self.category()
        if self.movement is not None and self.movement.category == category:
            return self.movement.subcategory
        suggested_group, suggested_subcategory = self._suggested_subcategory
        return suggested_subcategory if category and category == suggested_group else ""

    def new_name(self) -> str:
        """Kirimda ro'yxatda yo'q, yozilgan mahsulot nomi (saqlashda yangi mahsulot bo'ladi); aks holda bo'sh."""
        name = " ".join(self.product.currentText().split())
        return name if self._suggests_price and name and self.selected() is None else ""

    def is_blank(self) -> bool:
        """Hech narsa kiritilmagan qator: saqlashda hisobga olinmaydi."""
        return not self.product.currentText().strip() and not self.quantity.value()

    def factor(self) -> float:
        """Tanlangan birlik necha asosiy birlikka teng (asosiy birlikning o'zi — 1)."""
        return self.unit.currentData() or 1.0

    def total(self) -> float:
        return self.amount.value()

    def show_cost(self, shown: bool) -> None:
        """Narxsiz chiqimda (obyektga, obyektsiz) narx o'rniga tannarx ko'rsatiladi — summasi ko'rinib tursin.

        Tannarxni dastur o'zi hisoblaydi, shuning uchun maydonlar o'zgartirilmaydi va u saqlanmaydi.
        """
        was_shown, self._shows_cost = self._shows_cost, shown
        for field in (self.price, self.amount):
            field.setReadOnly(shown)
            field.setFocusPolicy(Qt.FocusPolicy.NoFocus if shown else Qt.FocusPolicy.StrongFocus)
        if shown:
            self._show_cost()
        elif was_shown:
            self.price.setValue(0)  # tannarx sotuv narxi bo'lib qolmasin

    def unit_price(self) -> float:
        """1 asosiy birlik narxi; summa yozilgan bo'lsa — undan aniq hisoblanadi (narx maydoni yaxlitlangan)."""
        quantity = self.quantity.value() * self.factor()
        if self.amount.value() and quantity:
            return self.amount.value() / quantity
        return self.price.value() / self.factor()

    def _on_product_changed(self) -> None:
        self._show_product()
        product = self.selected()
        if product is not None:
            self._suggested_subcategory = self._default_group(product.id)
            self.select_group(self._suggested_subcategory[0])
        self.changed.emit()

    def _on_unit_changed(self) -> None:
        self._suggest_price()
        self._price_changed()

    def _quantity_changed(self) -> None:
        """Miqdor o'zgarsa: narx bor — summa qayta hisoblanadi; faqat summa bor — narx hisoblanadi."""
        if self.price.value() or not self.amount.value():
            self._price_changed()
        else:
            self._amount_changed()

    def _price_changed(self) -> None:
        self._set(self.amount, self.quantity.value() * self.price.value())

    def _amount_changed(self) -> None:
        if self.quantity.value():
            self._set(self.price, self.amount.value() / self.quantity.value())
        else:
            self.changed.emit()

    def _set(self, field, value: float) -> None:
        if not self._syncing:
            self._syncing = True
            try:
                field.setValue(value)
            finally:
                self._syncing = False
        self.changed.emit()

    def _show_product(self) -> None:
        """Tanlangan mahsulotning qoldig'i va birliklarini ko'rsatadi."""
        product = self.selected()
        previous_unit = self.unit.currentText()
        self.unit.blockSignals(True)
        self.unit.clear()
        if product is None and self.new_name():
            # Ro'yxatda yo'q nom (kirimda): saqlashda yangi mahsulot bo'ladi — birligi shu yerda tanlanadi.
            self.stock.setText(tr("yangi"))
            for unit in UNITS:
                self.unit.addItem(unit, 1.0)
            self.unit.setCurrentIndex(max(self.unit.findText(previous_unit), 0))
        elif product is None:
            self.stock.setText("")
        else:
            self.stock.setText(tr("Xizmat") if product.is_service else f"{fmt_qty(product.stock)} {product.unit}")
            self.unit.addItem(product.unit, 1.0)
            if product.has_alt_unit:
                self.unit.addItem(product.alt_unit, product.alt_factor)
        self.unit.blockSignals(False)
        self.unit.setEnabled(self.unit.count() > 1)
        self._suggest_price()

    def _show_cost(self) -> None:
        """1 birlik tannarxi: tahrirlanayotgan yozuvda — saqlangani, yangisida — hozirgi o'rtacha narx."""
        product = self.selected()
        if product is None:
            cost = 0.0
        elif self.movement is not None and self.movement.product_id == product.id:
            cost = self.movement.price
        else:
            cost = product.average_price
        self.price.setValue(round(cost * self.factor(), 2))

    def _suggest_price(self) -> None:
        """Kirimda oldingi o'rtacha narxni taklif qiladi; qo'lda yozilgan narxga tegmaydi."""
        if self._shows_cost:
            self._show_cost()
            return
        product = self.selected()
        if self._suggests_price and product is not None and self.price.value() in (0, self._suggested_price):
            self._suggested_price = round(product.average_price * self.factor(), 2)
            self.price.setValue(self._suggested_price)


class DocumentDialog(FormDialog):
    """Kirim yoki chiqim hujjati: sana, kimdan/kimga va to'lov bir marta, mahsulotlar jadvalda qator-qator.

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
        self._payment = PaymentFields(
            warehouse.suggestions(labels.kind, "payment"), warehouse.last_payment(labels.kind)
        )
        self._table = self._build_table()
        self._total = label("", "total")
        self._doc_number = QLineEdit()
        self._doc_number.setPlaceholderText(tr("Nakladnoy raqami (ixtiyoriy)"))
        self._person = suggestion_box(warehouse.suggestions(labels.kind, "person"))
        self._note = QLineEdit()

        # 1) Kimdan / qayerga va qachon; to'lov. 2) Mahsulotlar jadvali. 3) Qo'shimcha maydonlar (yig'iq).
        store = captioned(tr("Ombor"), self._store)
        store.setVisible(self._store.count() > 1)
        self._payment_fields = side_by_side(
            captioned(tr("To'lov turi"), self._payment.method), captioned(tr("Holati"), self._payment.status)
        )
        if self._is_receipt:
            self.form.addRow(
                side_by_side(
                    captioned(labels.counterparty, self._supplier),
                    captioned(tr("Sana"), self._date),
                    self._payment_fields,
                    store,
                    stretches=(3, 1, 2, 1),
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
                    self._payment_fields,
                    store,
                    stretches=(3, 3, 1, 2, 1),
                )
            )
            self.form.addRow(self._target)
        self.form.addRow(label(tr("Mahsulotlar"), "fieldCaption"))
        self.form.addRow(self._table)
        new_product = button(tr("Ro'yxatda yo'q mahsulot qo'shish"), "link", Glyph.ADD)
        new_product.setAutoDefault(False)
        new_product.clicked.connect(self._add_product)
        hint_text = (
            tr("Mahsulotni tanlang yoki yangi nomini yozing — saqlashda ro'yxatga qo'shiladi.")
            if self._is_receipt
            else tr("Mahsulotni tanlang yoki nomini yozing — ostidan yangi qator o'zi ochiladi.")
        )
        hint = label(hint_text, "muted")
        below = QWidget()
        below_row = QHBoxLayout(below)
        below_row.setContentsMargins(0, 0, 0, 0)
        below_row.addWidget(hint)
        below_row.addWidget(new_product)
        below_row.addStretch()
        below_row.addWidget(self._total)
        self.form.addRow(below)
        self.add_extra_row(
            "", side_by_side(captioned(tr("Hujjat №"), self._doc_number), captioned(labels.person, self._person))
        )
        self.add_extra_row("", captioned(tr("Izoh"), self._note))

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
        # Tahrirlanayotgan hujjatda qo'shimcha maydonlar to'ldirilgan bo'lsa — ochiq.
        self.show_extras(bool(document) and has_extras)
        self._store.currentIndexChanged.connect(self._reload_products)
        self._target.currentIndexChanged.connect(self._show_target)
        self._show_target()

    def accept(self) -> None:
        if self._select_by_barcode():
            return  # skaner koddan keyin Enter yuboradi: mahsulot tanlanadi, oyna yopilmaydi
        if not self._add_new_products():
            return
        super().accept()

    def _add_new_products(self) -> bool:
        """Kirimda ro'yxatda yo'q nomlar — so'rab, qatordagi birlik va guruh bilan yangi mahsulot qilib qo'shiladi.

        Excel'dagi kabi xarajatlarning ko'pi yangi nom (ковролин, диван…): alohida oyna ochish shart emas.
        Rad etilsa — False, oyna ochiq qoladi.
        """
        new: dict[str, DocumentLine] = {}
        for line in self._lines:
            if line.new_name():
                new.setdefault(line.new_name().casefold(), line)
        if not new:
            return True
        names = ", ".join(f"«{line.new_name()}»" for line in new.values())
        question = tr("Ro'yxatda yo'q: {0}. Yangi mahsulot sifatida qo'shilsinmi?").format(names)
        if not confirm(self, tr("Yangi mahsulot"), question, tr("Ha, qo'shish")):
            return False
        try:
            for line in new.values():
                self._warehouse.save_product(
                    Product(name=line.new_name(), unit=line.unit.currentText() or UNITS[0], category=line.category())
                )
        except WarehouseError as error:
            QMessageBox.warning(self, tr("Diqqat"), str(error))
            return False
        self._reload_products()
        return True

    def save(self) -> None:
        counterparty = self._counterparty()
        # To'lov holati — kirimda va sotuvda (tanlanmagan bo'lsa — xato); ichki rasxodda to'lov yo'q.
        unpaid = self._payment.unpaid() if self._has_prices() else False
        self.saved_ids = self._warehouse.save_document(
            [self._movement(line, counterparty, unpaid) for line in self._lines if not line.is_blank()],
            self._removed_ids,
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
        self._payment.select(first.payment, first.unpaid or first.on_credit)
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

    def _movement(self, line: DocumentLine, counterparty: str, unpaid: bool) -> Movement:
        product = line.selected()
        if product is None:
            raise WarehouseError(
                tr(
                    "«{0}» ro'yxatda yo'q. Mahsulotni ro'yxatdan tanlang yoki avval uni «Mahsulotlar»ga qo'shing."
                ).format(line.product.currentText().strip())
            )
        priced = self._has_prices()
        price = line.unit_price() if priced else 0.0
        if self._target_kind() is IssueTarget.SALE and not price:
            raise WarehouseError(tr("«{0}»: sotuv narxini kiriting.").format(product.name))
        category, subcategory = line.category(), line.subcategory()
        if not category and self._warehouse.group_required:
            raise WarehouseError(tr("«{0}»: guruhni tanlang.").format(product.name))
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
            warehouse_id=self._store.currentData(),
            id=line.movement.id if line.movement is not None else None,
            payment=self._payment.payment() if priced else "",
            unpaid=unpaid,
        )

    def _show_target(self) -> None:
        """Chiqim turiga qarab: obyekt yoki xaridor maydoni, narx yoki tannarx ustunlari, to'lov va jami."""
        target = self._target_kind()
        if not self._is_receipt:
            self._site_field.setVisible(target is IssueTarget.SITE)
            self._customer_field.setVisible(target is IssueTarget.SALE)
            for button_target, choice in self._target_choices.items():
                choice.setChecked(button_target is target)
        priced = self._has_prices()
        for line in self._lines:
            line.show_cost(not priced)
        self._payment_fields.setVisible(priced)
        price_title = tr("Narxi") if self._is_receipt else tr("Sotuv narxi") if priced else tr("Tannarx")
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
        headers = [tr("Mahsulot"), tr("Omborda"), tr("Birlik"), tr("Miqdor"), tr("Narxi"), tr("Summa"), tr("Guruh")]
        return lines_table([*headers, ""], COLUMN_WIDTHS, PRODUCT)

    def _products(self) -> list[ProductStock]:
        return self._warehouse.products(warehouse_id=self._store.currentData())

    def _add_line(self, movement: MovementDetails | None = None) -> DocumentLine:
        line = DocumentLine(self._products(), self._is_receipt, self._warehouse.default_group, movement)
        line.show_cost(not self._has_prices())
        row = self._table.rowCount()
        self._table.insertRow(row)
        for column, widget in enumerate(line.widgets):
            self._table.setCellWidget(row, column, widget)
        fit_lines_height(self._table)
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
        fit_lines_height(self._table)
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
        text = tr("Jami: {0} {1}") if self._has_prices() else tr("Tannarx jami: {0} {1}")
        self._total.setText(text.format(fmt_money(total), CURRENCY))

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
