"""Ma'lumot kiritish oynalari: mahsulot va kirim/chiqim."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..catalog import GROUPS, display_name, find_group
from ..config import CURRENCY, UNITS
from ..errors import WarehouseError
from ..formatting import fmt_money, fmt_qty
from ..i18n import tr
from ..models import Movement, MovementKind, Product, ProductStock
from ..warehouse import Warehouse
from .labels import KindLabels
from .widgets import button, date_input, label, number_input, suggestion_box

NO_GROUP = tr("Tanlanmagan")


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
        for group in GROUPS:
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

        self.form.addRow(tr("Nomi *"), self._name)
        self.form.addRow(tr("O'lchov birligi *"), self._unit)
        self.form.addRow(tr("Minimal qoldiq"), self._min_stock)
        self.form.addRow(tr("Izoh"), self._note)

    def save(self) -> None:
        self.saved_id = self._warehouse.save_product(
            Product(
                name=self._name.text(),
                unit=self._unit.currentText(),
                min_stock=self._min_stock.value(),
                note=self._note.text(),
                id=self._product_id,
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

        self._date = date_input(movement.date if movement else None)
        self._product = self._build_product_box()
        self._stock_hint = label("", "muted")
        self._quantity = number_input(3, movement.quantity if movement else 0)
        self._price = number_input(2, movement.price if movement else 0)
        self._price.setSuffix(f" {CURRENCY}")
        self._amount = label("", "total")
        self._sale_price = number_input(2, movement.sale_price if movement else 0)
        self._sale_price.setSuffix(f" {CURRENCY}")
        self._sale_price.setToolTip(tr("Bo'sh (0) qoldirilsa, chiqim ichki rasxod hisoblanadi va foydaga kirmaydi."))
        self._profit_hint = label("", "muted")
        self._groups = GroupFields()
        if movement:
            self._groups.select(movement.category, movement.subcategory)
        self._person = suggestion_box(warehouse.suggestions(labels.kind, "person"), movement.person if movement else "")
        self._counterparty = suggestion_box(
            warehouse.suggestions(labels.kind, "counterparty"), movement.counterparty if movement else ""
        )
        self._note = QLineEdit(movement.note if movement else "")

        self.form.addRow(tr("Sana *"), self._date)
        self.form.addRow(tr("Mahsulot *"), self._product)
        self.form.addRow("", self._stock_hint)
        self.form.addRow(tr("Miqdor *"), self._quantity)
        if self._has_price:
            self.form.addRow(tr("Narxi (1 birlik)"), self._price)
            self.form.addRow(tr("Summa"), self._amount)
        else:
            self.form.addRow(tr("Sotuv narxi (1 birlik)"), self._sale_price)
            self.form.addRow("", self._profit_hint)
        self.form.addRow(tr("Guruh"), self._groups.group)
        self.form.addRow(tr("Kichik guruh"), self._groups.subgroup)
        self.form.addRow(labels.person, self._person)
        self.form.addRow(labels.counterparty, self._counterparty)
        self.form.addRow(tr("Izoh"), self._note)

        self._load_products(movement.product_id if movement else None)
        self._product.currentTextChanged.connect(self._on_product_changed)
        self._quantity.valueChanged.connect(self._update_amount)
        self._price.valueChanged.connect(self._update_amount)
        self._sale_price.valueChanged.connect(self._update_amount)
        self._on_product_changed()

    def save(self) -> None:
        product = self._selected_product()
        if product is None:
            raise WarehouseError(
                tr("Mahsulotni ro'yxatdan tanlang. Ro'yxatda bo'lmasa, avval «Yangi mahsulot» tugmasi bilan qo'shing.")
            )
        self._warehouse.save_movement(
            Movement(
                kind=self._kind,
                date=self._date.date().toPython(),
                product_id=product.id,
                quantity=self._quantity.value(),
                price=self._price.value(),
                sale_price=self._sale_price.value(),
                category=self._groups.category(),
                subcategory=self._groups.subcategory(),
                person=self._person.currentText(),
                counterparty=self._counterparty.currentText(),
                note=self._note.text(),
                created_by=self._author,
                id=self._movement_id,
            )
        )

    @staticmethod
    def _build_product_box() -> QComboBox:
        """Yozib qidirsa bo'ladigan ro'yxat; ro'yxatda yo'q nom qabul qilinmaydi."""
        box = QComboBox()
        box.setEditable(True)
        box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        box.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        box.completer().setCompletionMode(box.completer().CompletionMode.PopupCompletion)
        box.lineEdit().setPlaceholderText(tr("Tanlang yoki nomini yozing"))
        return box

    def _load_products(self, select_id: int | None) -> None:
        self._product.blockSignals(True)
        self._product.clear()
        for product in self._warehouse.products():
            self._product.addItem(product.name, product)
        ids = [self._product.itemData(index).id for index in range(self._product.count())]
        self._product.setCurrentIndex(ids.index(select_id) if select_id in ids else -1)
        self._product.blockSignals(False)

    def _selected_product(self) -> ProductStock | None:
        index = self._product.findText(self._product.currentText().strip(), Qt.MatchFlag.MatchFixedString)
        return self._product.itemData(index) if index >= 0 else None

    def _on_product_changed(self) -> None:
        product = self._selected_product()
        if product is None:
            self._stock_hint.setText("")
            self._quantity.setSuffix("")
        else:
            self._stock_hint.setText(tr("Omborda: {0} {1}").format(fmt_qty(product.stock), product.unit))
            self._quantity.setSuffix(f" {product.unit}")
            self._suggest_price(product)
            if self._movement_id is None:  # yangi yozuvda shu mahsulotning oxirgi guruhi taklif qilinadi
                self._groups.select(*self._warehouse.last_group(product.id))
        self._update_amount()

    def _suggest_price(self, product: ProductStock) -> None:
        """Yangi kirimda oldingi o'rtacha narxni taklif qiladi; qo'lda yozilgan narxga tegmaydi."""
        if not self._has_price or self._movement_id is not None:
            return
        if self._price.value() in (0, self._suggested_price):
            self._suggested_price = round(product.average_price, 2)
            self._price.setValue(self._suggested_price)

    def _update_amount(self) -> None:
        self._amount.setText(f"{fmt_money(self._quantity.value() * self._price.value())} {CURRENCY}")
        self._profit_hint.setText(self._profit_text())

    def _profit_text(self) -> str:
        """Chiqim oynasida: tannarx va kutilayotgan foyda (yoki zarar)."""
        product = self._selected_product()
        if product is None:
            return ""
        cost = self._stored_cost if self._stored_cost is not None else product.average_price
        text = tr("Tannarxi: {0} {1}").format(fmt_money(cost), CURRENCY)
        if not self._sale_price.value():
            return tr("{0}  ·  sotuv narxi kiritilmasa — ichki rasxod").format(text)
        profit = self._quantity.value() * (self._sale_price.value() - cost)
        result = tr("Foyda") if profit >= 0 else tr("ZARAR")
        return f"{text}  ·  {result}: {fmt_money(abs(profit))} {CURRENCY}"


class InventoryDialog(FormDialog):
    """Inventarizatsiya: sanab chiqilgan haqiqiy qoldiq kiritiladi, farqni dastur o'zi yozadi."""

    def __init__(self, warehouse: Warehouse, product: ProductStock, author: str, parent: QWidget | None = None):
        super().__init__(tr("Inventarizatsiya — {0}").format(product.name), parent)
        self._warehouse = warehouse
        self._product = product
        self._author = author

        self._date = date_input()
        self._actual = number_input(3, product.stock)
        self._actual.setSuffix(f" {product.unit}")
        self._note = QLineEdit()
        explanation = label(
            tr("Farq bo'lsa, dastur o'zi «Inventarizatsiya» nomli kirim (ortiqcha) yoki chiqim (kamomad) yozadi."),
            "muted",
        )
        explanation.setWordWrap(True)

        self.form.addRow(tr("Sana *"), self._date)
        self.form.addRow(tr("Hisobdagi qoldiq"), label(f"{fmt_qty(product.stock)} {product.unit}", "total"))
        self.form.addRow(tr("Haqiqiy qoldiq *"), self._actual)
        self.form.addRow(tr("Izoh"), self._note)
        self.form.addRow(explanation)

    def save(self) -> None:
        self._warehouse.adjust_stock(
            self._product.id, self._actual.value(), self._date.date().toPython(), self._author, self._note.text()
        )
