"""Ma'lumot kiritish oynalari: mahsulot va kirim/chiqim."""

from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..catalog import display_name, find_group, groups
from ..config import CURRENCY, UNITS
from ..database import MAIN_WAREHOUSE_ID
from ..errors import WarehouseError
from ..formatting import fmt_money, fmt_qty
from ..i18n import tr
from ..models import Movement, MovementKind, Product, ProductStock, Store
from ..warehouse import Warehouse
from .labels import KindLabels
from .widgets import NumberInput, button, date_input, label, number_input, suggestion_box

NO_GROUP = tr("Tanlanmagan")


def product_box(placeholder: str = tr("Tanlang, nomini yozing yoki shtrix-kodni o'qiting")) -> QComboBox:
    """Mahsulot tanlash: yozib qidirsa bo'ladigan ro'yxat; ro'yxatda yo'q nom qabul qilinmaydi."""
    box = QComboBox()
    box.setEditable(True)
    box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    box.completer().setFilterMode(Qt.MatchFlag.MatchContains)
    box.completer().setCompletionMode(box.completer().CompletionMode.PopupCompletion)
    box.lineEdit().setPlaceholderText(placeholder)
    return box


class FormDialog(QDialog):
    """Maydonlar va «Saqlash / Bekor qilish» tugmalaridan iborat oyna.

    Voris sinf maydonlarni `self.form` ga qo'shadi va `save()` ni yozadi.
    `save()` WarehouseError ko'tarsa, xabar ko'rsatiladi va oyna ochiq qoladi.
    """

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        save_text: str = tr("Saqlash"),
        cancel_text: str = tr("Bekor qilish"),
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)

        self.form = QFormLayout()
        self.form.setVerticalSpacing(12)
        self.form.setHorizontalSpacing(16)

        save = button(save_text, "primary")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        cancel = button(cancel_text)
        cancel.clicked.connect(self.reject)
        self.extra_buttons = QHBoxLayout()  # chap tomonda, voris sinf qo'shimcha tugma qo'yishi uchun
        buttons = QHBoxLayout()
        buttons.addLayout(self.extra_buttons)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(20)
        layout.addLayout(self.form)
        layout.addLayout(buttons)

    def save(self) -> None:
        raise NotImplementedError

    def accept(self) -> None:
        try:
            self.save()
        except WarehouseError as error:
            QMessageBox.warning(self, tr("Diqqat"), str(error))
            return
        super().accept()


class GroupFields:
    """Guruh va kichik guruh tanlash maydonlari: ikkinchisining ro'yxati birinchisiga bog'liq."""

    def __init__(self):
        self.group = QComboBox()
        self.subgroup = QComboBox()
        self.group.addItem(NO_GROUP, "")
        for group in groups():
            self.group.addItem(group.name.display, group.name.ru)
        self.group.currentIndexChanged.connect(lambda: self._fill_subgroups(""))
        self._fill_subgroups("")

    def select(self, category: str, subcategory: str) -> None:
        """Berilgan qiymatlarni tanlaydi; ro'yxatda yo'q (eski) qiymat bo'lsa, uni ham qo'shadi."""
        if category and self.group.findData(category) < 0:
            self.group.addItem(display_name(category), category)
        self.group.setCurrentIndex(max(self.group.findData(category), 0))
        self._fill_subgroups(subcategory)

    def category(self) -> str:
        return self.group.currentData()

    def subcategory(self) -> str:
        return self.subgroup.currentData() or ""

    def _fill_subgroups(self, selected: str) -> None:
        """Tanlangan guruhning kichik guruhlari; guruh tanlanmagan bo'lsa, ro'yxat o'chiq turadi."""
        group = find_group(self.group.currentData())
        self.subgroup.clear()
        for subgroup in group.subgroups if group else ():
            self.subgroup.addItem(subgroup.display, subgroup.ru)
        if selected and self.subgroup.findData(selected) < 0:
            self.subgroup.addItem(display_name(selected), selected)
        self.subgroup.setCurrentIndex(max(self.subgroup.findData(selected), 0))
        self.subgroup.setEnabled(self.subgroup.count() > 0)


class ProductDialog(FormDialog):
    def __init__(self, warehouse: Warehouse, product: Product | None = None, parent: QWidget | None = None):
        super().__init__(tr("Mahsulotni tahrirlash") if product else tr("Yangi mahsulot"), parent)
        self._warehouse = warehouse
        self._product_id = product.id if product else None
        self.saved_id: int | None = None

        self._name = QLineEdit(product.name if product else "")
        self._name.setPlaceholderText(tr("Masalan: Truba 40x40x2"))
        self._unit = suggestion_box(UNITS, product.unit if product else UNITS[0])
        self._min_stock = number_input(3, product.min_stock if product else 0)
        self._min_stock.setToolTip(tr("Qoldiq shu miqdorga tushganda mahsulot «Kam qoldi» deb belgilanadi."))
        self._note = QLineEdit(product.note if product else "")
        self._barcode = QLineEdit(product.barcode if product else "")
        self._barcode.setPlaceholderText(tr("Skaner bilan o'qiting yoki yozing (ixtiyoriy)"))
        self._alt_unit = suggestion_box(("", *UNITS), product.alt_unit if product else "")
        self._alt_factor = number_input(4, product.alt_factor if product else 0)
        self._alt_factor.setToolTip(
            tr(
                "Masalan: asosiy birlik kg, qo'shimcha birlik tonna bo'lsa — 1000. Kirim-chiqimda ikkalasida ham kiritish mumkin."
            )
        )
        alt_row = QHBoxLayout()
        alt_row.addWidget(self._alt_unit, stretch=1)
        alt_row.addWidget(label(tr("1 tasi =")))
        alt_row.addWidget(self._alt_factor, stretch=1)
        alt_row.addWidget(label(tr("asosiy birlik")))
        self._is_service = QCheckBox(tr("Bu xizmat yoki xarajat (omborda qoldig'i yuritilmaydi)"))
        self._is_service.setToolTip(
            tr("Masalan: yuk tashish, kommunal to'lov, ijara. Kirimi xarajat sifatida hisobotga tushadi.")
        )
        self._is_service.setChecked(bool(product and product.is_service))
        self._is_service.toggled.connect(lambda checked: self._min_stock.setEnabled(not checked))
        self._min_stock.setEnabled(not self._is_service.isChecked())

        self.form.addRow(tr("Nomi *"), self._name)
        self.form.addRow(tr("O'lchov birligi *"), self._unit)
        self.form.addRow(tr("Qo'shimcha birlik"), alt_row)
        self.form.addRow(tr("Minimal qoldiq"), self._min_stock)
        self.form.addRow(tr("Shtrix-kod"), self._barcode)
        self.form.addRow(tr("Izoh"), self._note)
        self.form.addRow("", self._is_service)

    def keyPressEvent(self, event) -> None:
        # Skaner koddan keyin Enter yuboradi: u oynani saqlab yubormasligi kerak.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._barcode.hasFocus():
            self._note.setFocus()
            return
        super().keyPressEvent(event)

    def save(self) -> None:
        self.saved_id = self._warehouse.save_product(
            Product(
                name=self._name.text(),
                unit=self._unit.currentText(),
                min_stock=self._min_stock.value(),
                note=self._note.text(),
                id=self._product_id,
                is_service=self._is_service.isChecked(),
                barcode=self._barcode.text(),
                alt_unit=self._alt_unit.currentText(),
                alt_factor=self._alt_factor.value(),
            )
        )


class MovementDialog(FormDialog):
    """Kirim yoki chiqim yozuvi; `movement` berilsa — tahrirlash. `author` — yozuvni kiritayotgan foydalanuvchi."""

    def __init__(
        self,
        warehouse: Warehouse,
        labels: KindLabels,
        author: str,
        movement: Movement | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(
            tr("{0}ni tahrirlash").format(labels.title) if movement else tr("Yangi {0}").format(labels.title.lower()),
            parent,
        )
        self._warehouse = warehouse
        self._kind = labels.kind
        self._author = author
        self._movement_id = movement.id if movement else None
        self._has_price = labels.kind is MovementKind.IN
        self._suggested_price = 0.0
        # Tahrirlashda — yozuvda saqlangan tannarx; yangi chiqimda — mahsulotning joriy o'rtacha narxi.
        self._stored_cost = movement.price if movement else None
        self.saved_count = 0  # «Saqlash va yana qo'shish» bilan kiritilgan yozuvlar soni

        self._date = date_input(movement.date if movement else None, allow_future=False)
        self._doc_number = QLineEdit(movement.doc_number if movement else "")
        self._doc_number.setPlaceholderText(tr("Nakladnoy raqami (ixtiyoriy)"))
        self._doc_number.setToolTip(
            tr("Bir nakladnoydagi bir nechta mahsulotni bir xil raqam bilan kiriting — ular birga chop etiladi.")
        )
        self._store = QComboBox()
        for store in warehouse.stores():
            self._store.addItem(store.name, store.id)
        self._store.setCurrentIndex(max(self._store.findData(movement.warehouse_id if movement else None), 0))
        self._product = product_box()
        self._stock_hint = label("", "muted")
        self._quantity = number_input(3, movement.quantity if movement else 0)
        self._unit = QComboBox()  # mahsulotning qo'shimcha birligi bo'lsa, miqdor va narx shu birlikda kiritiladi
        self._unit.setMinimumWidth(90)
        self._price = number_input(2, movement.price if movement else 0)
        self._price.setSuffix(f" {CURRENCY}")
        self._amount = label("", "total")
        self._sale_price = number_input(2, movement.sale_price if movement else 0)
        self._sale_price.setSuffix(f" {CURRENCY}")
        self._sale_price.setToolTip(tr("Bo'sh (0) qoldirilsa, chiqim ichki rasxod hisoblanadi va foydaga kirmaydi."))
        self._profit_hint = label("", "muted")
        self._is_return = QCheckBox(
            tr("Qaytarish: xaridordan qaytgan mahsulot")
            if self._has_price
            else tr("Qaytarish: yetkazib beruvchiga qaytarilmoqda")
        )
        self._is_return.setChecked(bool(movement and movement.is_return))
        self._on_credit = QCheckBox(tr("Qarzga (to'lov keyin bo'ladi)"))
        self._on_credit.setToolTip(tr("Belgilansa, summa «Qarzlar» bo'limida shu kontragent hisobiga yoziladi."))
        self._on_credit.setChecked(bool(movement and movement.on_credit))
        self._groups = GroupFields()
        if movement:
            self._groups.select(movement.category, movement.subcategory)
        self._person = suggestion_box(warehouse.suggestions(labels.kind, "person"), movement.person if movement else "")
        self._counterparty = suggestion_box(
            warehouse.suggestions(labels.kind, "counterparty"), movement.counterparty if movement else ""
        )
        self._note = QLineEdit(movement.note if movement else "")

        quantity_row = QHBoxLayout()
        quantity_row.addWidget(self._quantity, stretch=1)
        quantity_row.addWidget(self._unit)

        self.form.addRow(tr("Sana *"), self._date)
        self.form.addRow(tr("Hujjat №"), self._doc_number)
        self.form.addRow(tr("Ombor"), self._store)
        self.form.setRowVisible(self._store, self._store.count() > 1)
        self.form.addRow(tr("Mahsulot *"), self._product)
        self.form.addRow("", self._stock_hint)
        self.form.addRow(tr("Miqdor *"), quantity_row)
        if self._has_price:
            self.form.addRow(tr("Narxi (1 birlik)"), self._price)
            self.form.addRow(tr("Summa"), self._amount)
            self.form.addRow("", self._is_return)
            self.form.addRow(tr("Xaridorga qaytariladigan narx"), self._sale_price)
        else:
            self.form.addRow(tr("Sotuv narxi (1 birlik)"), self._sale_price)
            self.form.addRow("", self._profit_hint)
            self.form.addRow("", self._is_return)
        self.form.addRow("", self._on_credit)
        self.form.addRow(tr("Guruh *") if warehouse.group_required else tr("Guruh"), self._groups.group)
        self.form.addRow(tr("Kichik guruh"), self._groups.subgroup)
        self.form.addRow(labels.person, self._person)
        self.form.addRow(labels.counterparty, self._counterparty)
        self.form.addRow(tr("Izoh"), self._note)

        self._saved_hint = label("", "muted")
        if movement is None:
            # Bir nakladnoyda bir nechta mahsulot bo'lsa: sana, raqam va kimdan kelgani qayta yozilmaydi.
            another = button(tr("Saqlash va yana qo'shish"))
            another.setAutoDefault(False)
            another.clicked.connect(self._save_and_continue)
            self.extra_buttons.addWidget(another)
            self.extra_buttons.addWidget(self._saved_hint)

        self._load_products(movement.product_id if movement else None)
        self._product.currentTextChanged.connect(self._on_product_changed)
        self._store.currentIndexChanged.connect(self._on_store_changed)
        self._unit.currentIndexChanged.connect(self._on_unit_changed)
        self._quantity.valueChanged.connect(self._update_amount)
        self._price.valueChanged.connect(self._update_amount)
        self._sale_price.valueChanged.connect(self._update_amount)
        self._is_return.toggled.connect(self._on_return_toggled)
        self._on_product_changed()
        self._on_return_toggled()

    def accept(self) -> None:
        if self._select_by_barcode():
            return  # skaner koddan keyin Enter yuboradi: mahsulot tanlanadi, oyna yopilmaydi
        super().accept()

    def save(self) -> None:
        product = self._selected_product()
        if product is None:
            raise WarehouseError(
                tr("Mahsulotni ro'yxatdan tanlang. Ro'yxatda bo'lmasa, avval «Yangi mahsulot» tugmasi bilan qo'shing.")
            )
        factor = self._factor()
        self._warehouse.save_movement(
            Movement(
                kind=self._kind,
                date=self._date.date().toPython(),
                product_id=product.id,
                quantity=self._quantity.value() * factor,
                price=self._price.value() / factor,
                sale_price=self._sale_price.value() / factor,
                category=self._groups.category(),
                subcategory=self._groups.subcategory(),
                person=self._person.currentText(),
                counterparty=self._counterparty.currentText(),
                note=self._note.text(),
                created_by=self._author,
                doc_number=self._doc_number.text(),
                is_return=self._is_return.isChecked(),
                on_credit=self._on_credit.isChecked(),
                warehouse_id=self._store.currentData(),
                id=self._movement_id,
            )
        )

    def _save_and_continue(self) -> None:
        """Yozuvni saqlab, oynani keyingi mahsulot uchun ochiq qoldiradi; umumiy maydonlar o'z holicha turadi."""
        try:
            self.save()
        except WarehouseError as error:
            QMessageBox.warning(self, tr("Diqqat"), str(error))
            return
        self.saved_count += 1
        self._saved_hint.setText(tr("Saqlandi: {0} ta").format(self.saved_count))
        self._suggested_price = 0.0
        for field in (self._quantity, self._price, self._sale_price):
            field.setValue(0)
        self._note.clear()
        self._load_products(None)  # qoldiqlar yangilanadi, mahsulot maydoni bo'shaydi
        self._on_product_changed()
        self._product.setFocus()

    def _load_products(self, select_id: int | None) -> None:
        """Ro'yxatni tanlangan ombordagi qoldiqlar bilan to'ldiradi."""
        self._product.blockSignals(True)
        self._product.clear()
        for product in self._warehouse.products(warehouse_id=self._store.currentData()):
            self._product.addItem(product.name, product)
        ids = [self._product.itemData(index).id for index in range(self._product.count())]
        self._product.setCurrentIndex(ids.index(select_id) if select_id in ids else -1)
        self._product.blockSignals(False)

    def _selected_product(self) -> ProductStock | None:
        index = self._product.findText(self._product.currentText().strip(), Qt.MatchFlag.MatchFixedString)
        return self._product.itemData(index) if index >= 0 else None

    def _select_by_barcode(self) -> bool:
        """Mahsulot maydoniga shtrix-kod yozilgan (o'qitilgan) bo'lsa, shu mahsulotni tanlaydi."""
        if self._selected_product() is not None:
            return False
        found = self._warehouse.product_by_barcode(self._product.currentText())
        if found is None:
            return False
        self._product.setCurrentIndex(self._product.findText(found.name, Qt.MatchFlag.MatchFixedString))
        self._quantity.setFocus()
        self._quantity.selectAll()
        return True

    def _factor(self) -> float:
        """Tanlangan birlik necha asosiy birlikka teng (asosiy birlikning o'zi — 1)."""
        return self._unit.currentData() or 1.0

    def _on_store_changed(self) -> None:
        selected = self._selected_product()
        self._load_products(selected.id if selected else None)
        self._on_product_changed()

    def _on_unit_changed(self) -> None:
        product = self._selected_product()
        if product is not None:
            self._suggest_price(product)
        self._update_amount()

    def _on_return_toggled(self) -> None:
        """Kirimda «xaridorga qaytariladigan narx» faqat qaytarishda ko'rinadi."""
        if self._has_price:
            self.form.setRowVisible(self._sale_price, self._is_return.isChecked())

    def _on_product_changed(self) -> None:
        product = self._selected_product()
        self._unit.blockSignals(True)
        self._unit.clear()
        if product is None:
            self._stock_hint.setText("")
        else:
            self._stock_hint.setText(
                tr("Xizmat yoki xarajat — qoldig'i yuritilmaydi")
                if product.is_service
                else tr("Omborda: {0} {1}").format(fmt_qty(product.stock), product.unit)
            )
            self._unit.addItem(product.unit, 1.0)
            # Tahrirlashda miqdor asosiy birlikda saqlangan holicha ko'rsatiladi.
            if product.has_alt_unit and self._movement_id is None:
                self._unit.addItem(product.alt_unit, product.alt_factor)
        self._unit.blockSignals(False)
        self._unit.setVisible(self._unit.count() > 1)
        self._quantity.setSuffix(f" {product.unit}" if product and self._unit.count() == 1 else "")
        if product is not None:
            self._suggest_price(product)
            if self._movement_id is None:  # yangi yozuvda shu mahsulotning oxirgi guruhi taklif qilinadi
                self._groups.select(*self._warehouse.last_group(product.id))
        self._update_amount()

    def _suggest_price(self, product: ProductStock) -> None:
        """Yangi kirimda oldingi o'rtacha narxni taklif qiladi; qo'lda yozilgan narxga tegmaydi."""
        if not self._has_price or self._movement_id is not None:
            return
        if self._price.value() in (0, self._suggested_price):
            self._suggested_price = round(product.average_price * self._factor(), 2)
            self._price.setValue(self._suggested_price)

    def _update_amount(self) -> None:
        self._amount.setText(f"{fmt_money(self._quantity.value() * self._price.value())} {CURRENCY}")
        self._profit_hint.setText(self._profit_text())

    def _profit_text(self) -> str:
        """Chiqim oynasida: tannarx va kutilayotgan foyda (yoki zarar)."""
        product = self._selected_product()
        if product is None:
            return ""
        cost = (self._stored_cost if self._stored_cost is not None else product.average_price) * self._factor()
        text = tr("Tannarxi: {0} {1}").format(fmt_money(cost), CURRENCY)
        if not self._sale_price.value():
            return tr("{0}  ·  sotuv narxi kiritilmasa — ichki rasxod").format(text)
        profit = self._quantity.value() * (self._sale_price.value() - cost)
        result = tr("Foyda") if profit >= 0 else tr("ZARAR")
        return f"{text}  ·  {result}: {fmt_money(abs(profit))} {CURRENCY}"


class InventoryDialog(FormDialog):
    """Inventarizatsiya varag'i: har bir mahsulotning sanab chiqilgan haqiqiy qoldig'i kiritiladi.

    Farqni dastur o'zi «Inventarizatsiya» nomli kirim (ortiqcha) yoki chiqim (kamomad) qilib yozadi;
    qoldig'i o'zgartirilmagan mahsulotlarga tegilmaydi.
    """

    SHEET_SIZE = (720, 420)
    ROW_HEIGHT = 46  # son maydoni sig'ishi uchun
    ACTUAL_WIDTH = 180

    def __init__(
        self,
        warehouse: Warehouse,
        products: Sequence[ProductStock],
        author: str,
        parent: QWidget | None = None,
        store: Store | None = None,
    ):
        """`products` — `store` omboridagi qoldiqlari bilan; `store` berilmasa — asosiy ombor."""
        super().__init__(tr("Inventarizatsiya — {0}").format(store.name) if store else tr("Inventarizatsiya"), parent)
        self._store_id = store.id if store else MAIN_WAREHOUSE_ID
        self._warehouse = warehouse
        self._products = [product for product in products if not product.is_service]
        self._author = author
        self.adjusted = 0  # saqlangandan keyin: qoldig'i tuzatilgan mahsulotlar soni

        self._date = date_input(allow_future=False)
        self._note = QLineEdit()
        self._actual: list[NumberInput] = []
        self._sheet = QTableWidget(len(self._products), 4)
        self._sheet.setHorizontalHeaderLabels(
            [tr("Mahsulot"), tr("Birlik"), tr("Hisobdagi qoldiq"), tr("Haqiqiy qoldiq")]
        )
        self._sheet.verticalHeader().hide()
        self._sheet.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._sheet.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._sheet.verticalHeader().setDefaultSectionSize(self.ROW_HEIGHT)
        header = self._sheet.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._sheet.setColumnWidth(3, self.ACTUAL_WIDTH)
        self._sheet.setMinimumSize(*self.SHEET_SIZE)
        for row, product in enumerate(self._products):
            actual = number_input(3, product.stock)
            self._actual.append(actual)
            self._sheet.setItem(row, 0, QTableWidgetItem(product.name))
            self._sheet.setItem(row, 1, QTableWidgetItem(product.unit))
            self._sheet.setItem(row, 2, QTableWidgetItem(fmt_qty(product.stock)))
            self._sheet.setCellWidget(row, 3, actual)
        explanation = label(
            tr(
                "Sanab chiqilgan haqiqiy qoldiqni yozing. Farq bo'lsa, dastur o'zi «Inventarizatsiya» nomli "
                "kirim (ortiqcha) yoki chiqim (kamomad) yozadi; o'zgartirilmagan mahsulotlarga tegilmaydi."
            ),
            "muted",
        )
        explanation.setWordWrap(True)

        self.form.addRow(tr("Sana *"), self._date)
        self.form.addRow(tr("Izoh"), self._note)
        self.form.addRow(self._sheet)
        self.form.addRow(explanation)

    def save(self) -> None:
        counted = {product.id: actual.value() for product, actual in zip(self._products, self._actual)}
        self.adjusted = self._warehouse.take_inventory(
            counted, self._date.date().toPython(), self._author, self._note.text(), self._store_id
        )
