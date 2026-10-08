"""Ro'yxatli sahifalar uchun umumiy asos."""

from datetime import date
from typing import Callable, Sequence

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from ..errors import WarehouseError
from ..i18n import tr
from ..models import Period
from ..session import Session
from .icons import Glyph
from .printing import print_table
from .widgets import (
    THIS_MONTH,
    THIS_WEEK,
    TODAY,
    Column,
    DataTable,
    PeriodFilter,
    StatCard,
    button,
    confirm,
    export_to_excel,
    label,
    page_header,
    table_card,
)

SEARCH_WIDTH = (130, 220)  # tor oynada qidiruv maydoni torayadi, tugmalar kesilmaydi


class ListPage(QWidget):
    """Jadval, qidiruv va «qo'shish / chop etish / Excel» tugmalari; tahrirlash va o'chirish — har bir qatorda.

    Voris sinf `refresh`, `edit_dialog` va `delete_item` ni yozadi; qo'shimcha filtrlarni sarlavha
    yonidagi `self.header_tools` ga, qo'shimcha tugmalarni «qo'shish» yonidagi `self.toolbar_tools` ga joylaydi.
    «Qo'shish» tugmasi kuzatuvchiga ko'rinmaydi. Qatordagi tugmalar `row_actions` yoqilgan bo'lsa chiqadi
    (odatda — faqat rahbarga); aniq bir qatorni o'zgartirish mumkinligini `can_change` hal qiladi.
    Tahrirlash: qatordagi ✎ yoki ikki marta bosish. O'chirish: qatordagi ✕ yoki Delete tugmasi.
    """

    delete_question = tr("Bu yozuv o'chirilsinmi?")
    locked_message = tr("Bu yozuvni faqat rahbar o'zgartira oladi.")
    empty_hint = ""  # jadval bo'sh turganda ko'rsatiladigan yo'l-yo'riq (voris sinf yozadi)

    def __init__(
        self,
        title: str,
        new_action: str,
        columns: Sequence[Column],
        session: Session,
        row_actions: bool | None = None,
        glyph: str = Glyph.DOCUMENT,
        subtitle: str = "",
    ):
        super().__init__()
        self.setObjectName("page")
        self._title = title
        self.session = session
        has_actions = session.can_modify if row_actions is None else row_actions

        self.table = DataTable(columns, row_actions=has_actions)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Qidirish…"))
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(SEARCH_WIDTH[0])
        self.search.setMaximumWidth(SEARCH_WIDTH[1])
        self.search.textChanged.connect(self._show_empty_text)
        self.search.textChanged.connect(self.refresh)
        self.footer = label("", "total")

        self.toolbar_tools = QHBoxLayout()
        toolbar = QHBoxLayout()
        if session.can_add:
            add = button(new_action.lstrip("+ "), "primary", Glyph.ADD)
            add.clicked.connect(lambda: self._open(None))
            toolbar.addWidget(add)
        toolbar.addLayout(self.toolbar_tools)
        if has_actions:
            self.table.edit_requested.connect(self._open)
            self.table.row_activated.connect(self._open)
            self.table.delete_requested.connect(self._delete)

        print_button = button(tr("Chop etish"), "print", Glyph.PRINT)
        print_button.clicked.connect(lambda: print_table(self, self.table, self.export_title()))
        excel = button(tr("Excelga chiqarish"), "excel", Glyph.EXPORT)
        excel.clicked.connect(lambda: export_to_excel(self, self.table, self.export_title()))
        toolbar.addStretch()
        for widget in (self.search, print_button, excel):
            toolbar.addWidget(widget)

        header, self.header_tools = page_header(glyph, title, subtitle)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)
        layout.addLayout(header)
        self.summary = QHBoxLayout()  # voris sinf ko'rsatkich kartochkalarini shu qatorga qo'yadi
        self.summary.setSpacing(14)
        layout.addLayout(self.summary)
        layout.addLayout(toolbar)
        self.body = QHBoxLayout()  # jadval; voris sinf uning yoniga qo'shimcha panel qo'yishi mumkin
        self.body.setSpacing(14)
        self.body.addWidget(table_card(self.table), stretch=3)
        layout.addLayout(self.body, stretch=1)
        layout.addWidget(self.footer)

    def add_recent_cards(self, period: PeriodFilter) -> dict[StatCard, Callable[[date], Period]]:
        """«Bugun», «Shu hafta», «Shu oy» kartochkalari — jadvaldagi sanalar bilan bir xil ranglarda.

        Kartochka bosilsa, `period` filtri shu davrga o'tadi. Qaytgan lug'at: kartochka -> uning davri.
        """
        cards = {}
        for preset, glyph, tone, period_of in (
            (TODAY, Glyph.CLOCK, "Good", Period.day_of),
            (THIS_WEEK, Glyph.CALENDAR, "Accent", Period.week_of),
            (THIS_MONTH, Glyph.CHART, "Violet", Period.month_of),
        ):
            stat = StatCard(preset, glyph, tone, clickable=True)
            stat.setToolTip(tr("Bosilsa, jadvalda faqat shu davr yozuvlari qoladi"))
            stat.clicked.connect(lambda preset=preset: period.select(preset))
            cards[stat] = period_of
            self.summary.addWidget(stat)
        return cards

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._show_empty_text()

    def _show_empty_text(self) -> None:
        """Bo'sh jadvalda: qidiruv bo'lsa — «topilmadi», aks holda sahifaning yo'l-yo'rig'i."""
        searching = bool(self.search.text().strip())
        self.table.empty_text = tr("Hech narsa topilmadi") if searching else self.empty_hint

    def refresh(self) -> None:
        raise NotImplementedError

    def edit_dialog(self, item_id: int | None) -> QDialog:
        """Yangi yozuv (`item_id` — None) yoki mavjudini tahrirlash oynasi."""
        raise NotImplementedError

    def delete_item(self, item_id: int) -> None:
        raise NotImplementedError

    def can_change(self, item_id: int) -> bool:
        """Joriy foydalanuvchi shu qatorni tahrirlashi yoki o'chirishi mumkinmi."""
        return self.session.can_modify

    def export_title(self) -> str:
        """Chop etilgan varaq va Excel faylining sarlavhasi."""
        return self._title

    def selected_id(self) -> int | None:
        """Tanlangan qatorning id si; hech narsa tanlanmagan bo'lsa, eslatma ko'rsatadi."""
        item_id = self.table.selected_id()
        if item_id is None:
            QMessageBox.information(self, self._title, tr("Avval jadvaldan kerakli qatorni tanlang."))
        return item_id

    def _is_allowed(self, item_id: int) -> bool:
        if self.can_change(item_id):
            return True
        QMessageBox.information(self, self._title, self.locked_message)
        return False

    def _open(self, item_id: int | None) -> None:
        if item_id is not None and not self._is_allowed(item_id):
            return
        self.edit_dialog(item_id).exec()
        self.refresh()  # oyna «Bekor qilish» bilan yopilsa ham, undan oldin saqlangan yozuvlar bo'lishi mumkin

    def _delete(self, item_id: int) -> None:
        if not self._is_allowed(item_id):
            return
        if not confirm(self, tr("O'chirish"), self.delete_question, tr("Ha, o'chirish")):
            return
        try:
            self.delete_item(item_id)
        except WarehouseError as error:
            QMessageBox.warning(self, tr("O'chirib bo'lmadi"), str(error))
        self.refresh()
