"""Ro'yxatli sahifalar uchun umumiy asos."""

from typing import Sequence

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from ..errors import WarehouseError
from ..i18n import tr
from ..session import Session
from .printing import print_table
from .widgets import Column, DataTable, button, confirm, export_to_excel, label

SEARCH_WIDTH = 220


class ListPage(QWidget):
    """Jadval, qidiruv va «qo'shish / chop etish / Excel» tugmalari; tahrirlash va o'chirish — har bir qatorda.

    Voris sinf `refresh`, `edit_dialog` va `delete_item` ni yozadi; qo'shimcha
    tugma va filtrlarni sarlavha yonidagi `self.header_tools` qatoriga joylaydi.
    Tahrirlash va o'chirish faqat `session` ruxsat bergan bo'lsa (rahbarga) ko'rinadi.
    Tahrirlash: qatordagi ✎ yoki ikki marta bosish. O'chirish: qatordagi ✕ yoki Delete tugmasi.
    """

    delete_question = tr("Bu yozuv o'chirilsinmi?")

    def __init__(self, title: str, new_action: str, columns: Sequence[Column], session: Session):
        super().__init__()
        self.setObjectName("page")
        self._title = title

        self.table = DataTable(columns, row_actions=session.can_modify)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Qidirish…"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(SEARCH_WIDTH)
        self.search.textChanged.connect(self.refresh)
        self.footer = label("", "total")

        toolbar = QHBoxLayout()
        add = button(new_action, "primary")
        add.clicked.connect(lambda: self._open(None))
        toolbar.addWidget(add)
        if session.can_modify:
            self.table.edit_requested.connect(self._open)
            self.table.row_activated.connect(self._open)
            self.table.delete_requested.connect(self._delete)

        print_button = button(tr("Chop etish"))
        print_button.clicked.connect(lambda: print_table(self, self.table, self.export_title()))
        excel = button(tr("Excelga chiqarish"))
        excel.clicked.connect(lambda: export_to_excel(self, self.table, self.export_title()))
        toolbar.addStretch()
        for widget in (self.search, print_button, excel):
            toolbar.addWidget(widget)

        self.header_tools = QHBoxLayout()
        header = QHBoxLayout()
        header.addWidget(label(title, "pageTitle"))
        header.addStretch()
        header.addLayout(self.header_tools)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)
        layout.addLayout(header)
        layout.addLayout(toolbar)
        layout.addWidget(self.table)
        layout.addWidget(self.footer)

    def refresh(self) -> None:
        raise NotImplementedError

    def edit_dialog(self, item_id: int | None) -> QDialog:
        """Yangi yozuv (`item_id` — None) yoki mavjudini tahrirlash oynasi."""
        raise NotImplementedError

    def delete_item(self, item_id: int) -> None:
        raise NotImplementedError

    def export_title(self) -> str:
        """Chop etilgan varaq va Excel faylining sarlavhasi."""
        return self._title

    def selected_id(self) -> int | None:
        """Tanlangan qatorning id si; hech narsa tanlanmagan bo'lsa, eslatma ko'rsatadi."""
        item_id = self.table.selected_id()
        if item_id is None:
            QMessageBox.information(self, self._title, tr("Avval jadvaldan kerakli qatorni tanlang."))
        return item_id

    def _open(self, item_id: int | None) -> None:
        if self.edit_dialog(item_id).exec():
            self.refresh()

    def _delete(self, item_id: int) -> None:
        if not confirm(self, tr("O'chirish"), self.delete_question, tr("Ha, o'chirish")):
            return
        try:
            self.delete_item(item_id)
        except WarehouseError as error:
            QMessageBox.warning(self, tr("O'chirib bo'lmadi"), str(error))
        self.refresh()
