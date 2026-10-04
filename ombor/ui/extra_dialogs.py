"""Qo'shimcha oynalar: ombordan omborga ko'chirish, to'lov, guruhlar va nom kiritish."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import catalog
from ..catalog import GroupCatalog
from ..config import CURRENCY
from ..debts import Debts
from ..errors import WarehouseError
from ..formatting import fmt_money, fmt_qty
from ..i18n import tr
from ..models import MovementKind, Payment, Transfer
from ..warehouse import Warehouse
from .dialogs import FormDialog
from .widgets import button, confirm, date_input, label, number_input, suggestion_box

GROUPS_TREE_SIZE = (520, 420)


class NameDialog(FormDialog):
    """Bitta yoki ikkita (o'zbekcha va ruscha) nom so'raydigan oyna; natija — `names()`."""

    def __init__(self, title: str, fields: dict[str, str], parent: QWidget | None = None):
        """`fields` — maydon yorlig'i -> boshlang'ich qiymat."""
        super().__init__(title, parent)
        self.allow_empty = False  # bo'sh qiymat ham qabul qilinadimi (masalan, manzilni olib tashlash uchun)
        self._inputs = [QLineEdit(value) for value in fields.values()]
        for title_text, field in zip(fields, self._inputs):
            self.form.addRow(title_text, field)

    def names(self) -> list[str]:
        return [field.text().strip() for field in self._inputs]

    def save(self) -> None:
        if not self.allow_empty and not any(self.names()):
            raise WarehouseError(tr("Nomini kiriting."))


class TransferDialog(FormDialog):
    """Mahsulotni bir ombordan boshqasiga ko'chirish."""

    def __init__(self, warehouse: Warehouse, author: str, product_id: int | None = None, parent: QWidget | None = None):
        super().__init__(tr("Ombordan omborga ko'chirish"), parent, save_text=tr("Ko'chirish"))
        self._warehouse = warehouse
        self._author = author

        self._date = date_input(allow_future=False)
        self._product = QComboBox()
        for product in warehouse.products():
            if not product.is_service:
                self._product.addItem(product.name, product.id)
        self._product.setCurrentIndex(max(self._product.findData(product_id), 0))
        self._source, self._target = QComboBox(), QComboBox()
        for store in warehouse.stores():
            self._source.addItem(store.name, store.id)
            self._target.addItem(store.name, store.id)
        self._target.setCurrentIndex(min(1, self._target.count() - 1))
        self._quantity = number_input(3)
        self._stock_hint = label("", "muted")
        self._note = QLineEdit()

        self.form.addRow(tr("Sana *"), self._date)
        self.form.addRow(tr("Mahsulot *"), self._product)
        self.form.addRow(tr("Qaysi ombordan *"), self._source)
        self.form.addRow("", self._stock_hint)
        self.form.addRow(tr("Qaysi omborga *"), self._target)
        self.form.addRow(tr("Miqdor *"), self._quantity)
        self.form.addRow(tr("Izoh"), self._note)

        self._product.currentIndexChanged.connect(self._update_hint)
        self._source.currentIndexChanged.connect(self._update_hint)
        self._update_hint()

    def save(self) -> None:
        if self._product.currentData() is None:
            raise WarehouseError(tr("Mahsulotni tanlang."))
        self._warehouse.transfer(
            Transfer(
                date=self._date.date().toPython(),
                product_id=self._product.currentData(),
                quantity=self._quantity.value(),
                from_id=self._source.currentData(),
                to_id=self._target.currentData(),
                note=self._note.text(),
                created_by=self._author,
            )
        )

    def _update_hint(self) -> None:
        if self._product.currentData() is None:
            self._stock_hint.setText("")
            return
        product = self._warehouse.product(self._product.currentData(), self._source.currentData())
        self._stock_hint.setText(tr("Shu omborda: {0} {1}").format(fmt_qty(product.stock), product.unit))
        self._quantity.setSuffix(f" {product.unit}")


class PaymentDialog(FormDialog):
    """To'lov yozish: yetkazib beruvchiga to'ladik yoki xaridor bizga to'ladi."""

    def __init__(
        self, debts: Debts, kind: MovementKind, author: str, counterparty: str = "", parent: QWidget | None = None
    ):
        is_supplier = kind is MovementKind.IN
        super().__init__(tr("Yetkazib beruvchiga to'lov") if is_supplier else tr("Xaridordan to'lov"), parent)
        self._debts = debts
        self._kind = kind
        self._author = author

        self._date = date_input(allow_future=False)
        self._counterparty = suggestion_box(debts.counterparties(kind), counterparty)
        self._debt_hint = label("", "muted")
        self._amount = number_input(2)
        self._amount.setSuffix(f" {CURRENCY}")
        self._note = QLineEdit()

        self.form.addRow(tr("Sana *"), self._date)
        self.form.addRow(tr("Kimga *") if is_supplier else tr("Kimdan *"), self._counterparty)
        self.form.addRow("", self._debt_hint)
        self.form.addRow(tr("Summa *"), self._amount)
        self.form.addRow(tr("Izoh"), self._note)

        self._counterparty.currentTextChanged.connect(self._update_hint)
        self._update_hint()

    def save(self) -> None:
        self._debts.add_payment(
            Payment(
                kind=self._kind,
                date=self._date.date().toPython(),
                counterparty=self._counterparty.currentText(),
                amount=self._amount.value(),
                note=self._note.text(),
                created_by=self._author,
            )
        )

    def _update_hint(self) -> None:
        name = self._counterparty.currentText().strip().casefold()
        debts = {b.counterparty.casefold(): b.debt for b in self._debts.balances(self._kind, include_settled=True)}
        self._debt_hint.setText(
            tr("Hozirgi qarz: {0} {1}").format(fmt_money(debts[name]), CURRENCY) if name in debts else ""
        )


class GroupsDialog(FormDialog):
    """Guruh va kichik guruhlarni qo'shish, nomini o'zgartirish va o'chirish. O'zgarish darhol saqlanadi."""

    def __init__(self, groups: GroupCatalog, parent: QWidget | None = None):
        super().__init__(tr("Guruhlar"), parent, save_text=tr("Yopish"), cancel_text=tr("Bekor qilish"))
        self._groups = groups
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels([tr("O'zbekcha"), tr("Ruscha")])
        self._tree.setMinimumSize(*GROUPS_TREE_SIZE)
        self._tree.setColumnWidth(0, GROUPS_TREE_SIZE[0] // 2)

        actions = (
            (tr("+ Guruh"), self._add_group, "primary"),
            (tr("+ Kichik guruh"), self._add_subgroup, ""),
            (tr("Nomini o'zgartirish"), self._rename, ""),
            (tr("O'chirish"), self._delete, "danger"),
        )
        buttons = QHBoxLayout()
        for text, handler, role in actions:
            action = button(text, role)
            action.setAutoDefault(False)
            action.clicked.connect(handler)
            buttons.addWidget(action)
        buttons.addStretch()
        hint = label(
            tr(
                "Nom o'zgartirilsa, shu guruh yozilgan kirim va chiqimlar ham yangi nomga o'tadi. "
                "O'chirilgan guruh eski yozuvlarda o'z nomi bilan qoladi."
            ),
            "muted",
        )
        hint.setWordWrap(True)
        content = QVBoxLayout()
        content.addLayout(buttons)
        content.addWidget(self._tree)
        content.addWidget(hint)
        self.form.addRow(content)
        self._fill()

    def save(self) -> None:
        """Har bir o'zgarish o'sha zahoti saqlangan; «Yopish» shunchaki oynani yopadi."""

    def _fill(self) -> None:
        self._tree.clear()
        for group in catalog.groups():
            item = QTreeWidgetItem([group.name.uz, group.name.ru])
            item.setData(0, Qt.ItemDataRole.UserRole, group.id)
            for subgroup in group.subgroups:
                child = QTreeWidgetItem([subgroup.uz, subgroup.ru])
                child.setData(0, Qt.ItemDataRole.UserRole, subgroup.id)
                item.addChild(child)
            self._tree.addTopLevelItem(item)

    def _selected(self) -> QTreeWidgetItem | None:
        item = self._tree.currentItem()
        if item is None:
            QMessageBox.information(self, tr("Guruhlar"), tr("Avval ro'yxatdan guruhni tanlang."))
        return item

    def _ask_names(self, title: str, uz: str = "", ru: str = "") -> list[str] | None:
        dialog = NameDialog(title, {tr("O'zbekcha nomi"): uz, tr("Ruscha nomi"): ru}, self)
        return dialog.names() if dialog.exec() else None

    def _apply(self, change) -> None:
        try:
            change()
        except WarehouseError as error:
            QMessageBox.warning(self, tr("Diqqat"), str(error))
        self._fill()

    def _add_group(self) -> None:
        names = self._ask_names(tr("Yangi guruh"))
        if names:
            self._apply(lambda: self._groups.add(*names))

    def _add_subgroup(self) -> None:
        item = self._selected()
        if item is None:
            return
        parent = item.parent() or item
        names = self._ask_names(tr("Yangi kichik guruh — {0}").format(parent.text(0)))
        if names:
            self._apply(lambda: self._groups.add(*names, parent_id=parent.data(0, Qt.ItemDataRole.UserRole)))

    def _rename(self) -> None:
        item = self._selected()
        if item is None:
            return
        names = self._ask_names(tr("Nomini o'zgartirish"), item.text(0), item.text(1))
        if names:
            self._apply(lambda: self._groups.rename(item.data(0, Qt.ItemDataRole.UserRole), *names))

    def _delete(self) -> None:
        item = self._selected()
        if item is None:
            return
        question = tr("«{0}» ro'yxatdan o'chirilsinmi?").format(item.text(0))
        if confirm(self, tr("O'chirish"), question, tr("Ha, o'chirish")):
            self._apply(lambda: self._groups.delete(item.data(0, Qt.ItemDataRole.UserRole)))
