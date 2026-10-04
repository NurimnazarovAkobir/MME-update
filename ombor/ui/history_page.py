"""Tarix: kim nimani o'zgartirgani va o'chirilgan yozuvlarni tiklash (faqat rahbarga)."""

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QMessageBox, QTabWidget, QVBoxLayout, QWidget

from ..debts import PAYMENT_ENTITY
from ..errors import WarehouseError
from ..i18n import tr
from ..models import HistoryEntry, MovementKind
from ..session import Session
from ..warehouse import PRODUCT_ENTITY, TRANSFER_ENTITY, Warehouse
from .labels import LABELS
from .printing import print_table
from .widgets import Column, ColumnKind, DataTable, PeriodFilter, button, export_to_excel, label

MAX_ROWS_SHOWN = 2000
SEARCH_WIDTH = 220
_ENTITY_TITLES = {
    MovementKind.IN.value: LABELS[MovementKind.IN].title,
    MovementKind.OUT.value: LABELS[MovementKind.OUT].title,
    PRODUCT_ENTITY: tr("Mahsulot"),
    TRANSFER_ENTITY: tr("Ko'chirish"),
    f"{PAYMENT_ENTITY}:IN": tr("Biz to'ladik"),
    f"{PAYMENT_ENTITY}:OUT": tr("Bizga to'landi"),
}


def _change_row(entry: HistoryEntry) -> tuple:
    return (
        entry.at,
        entry.actor,
        entry.role_title,
        entry.action.title,
        _ENTITY_TITLES.get(entry.entity, entry.entity),
        entry.summary,
        entry.previous,
    )


class HistoryPage(QWidget):
    def __init__(self, warehouse: Warehouse, session: Session):
        """Tarixni hamma ko'radi; o'chirilgan yozuvlar va ularni tiklash — faqat rahbarga."""
        super().__init__()
        self.setObjectName("page")
        self._warehouse = warehouse
        self._can_restore = session.can_modify

        self._changes = DataTable(
            (
                Column(tr("Vaqti"), ColumnKind.DATETIME),
                Column(tr("Kim")),
                Column(tr("Lavozimi")),
                Column(tr("Amal")),
                Column(tr("Turi")),
                Column(tr("Yozuv")),
                Column(tr("Avvalgi holati")),
            )
        )
        self._deleted = DataTable(
            (
                Column(tr("Sana"), ColumnKind.DATE),
                Column(tr("Turi")),
                Column(tr("Mahsulot")),
                Column(tr("Miqdor"), ColumnKind.QUANTITY),
                Column(tr("Birlik")),
                Column(tr("Summa"), ColumnKind.MONEY),
                Column(tr("Kiritdi")),
                Column(tr("O'chirdi")),
                Column(tr("O'chirilgan vaqti")),
            )
        )
        self._tabs = QTabWidget()
        self._tabs.addTab(self._changes, tr("O'zgarishlar"))
        if self._can_restore:
            self._tabs.addTab(self._deleted, tr("O'chirilgan yozuvlar"))

        self._period = PeriodFilter()
        self._period.changed.connect(self.refresh)
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("Qidirish…"))
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(SEARCH_WIDTH)
        self._search.textChanged.connect(self.refresh)
        self._footer = label("", "total")

        restore = button(tr("Tanlangan yozuvni tiklash"), "primary")
        restore.setToolTip(tr("«O'chirilgan yozuvlar»da tanlangan yozuvni hisobga qaytaradi"))
        restore.clicked.connect(self._restore)
        print_button = button(tr("Chop etish"))
        print_button.clicked.connect(lambda: print_table(self, *self._current()))
        excel = button(tr("Excelga chiqarish"))
        excel.clicked.connect(lambda: export_to_excel(self, *self._current()))

        header = QHBoxLayout()
        header.addWidget(label(tr("Tarix"), "pageTitle"))
        header.addStretch()
        header.addWidget(self._period)
        toolbar = QHBoxLayout()
        if self._can_restore:
            toolbar.addWidget(restore)
        toolbar.addStretch()
        for widget in (self._search, print_button, excel):
            toolbar.addWidget(widget)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)
        layout.addLayout(header)
        layout.addLayout(toolbar)
        layout.addWidget(self._tabs, stretch=1)
        layout.addWidget(self._footer)

    def refresh(self) -> None:
        changes = self._warehouse.history(self._period.period(), self._search.text())
        self._changes.set_rows([_change_row(entry) for entry in changes[:MAX_ROWS_SHOWN]])
        deleted = self._warehouse.deleted_movements()
        self._deleted.set_rows(
            [
                (
                    m.date,
                    LABELS[m.kind].title,
                    m.product_name,
                    m.quantity,
                    m.unit,
                    m.amount,
                    m.created_by,
                    m.deleted_by,
                    (m.deleted_at or "")[:16],
                )
                for m in deleted
            ],
            ids=[m.id for m in deleted],
        )
        self._footer.setText(
            tr("O'zgarishlar: {0} ta  ·  o'chirilgan yozuvlar: {1} ta").format(len(changes), len(deleted))
        )

    def _restore(self) -> None:
        self._tabs.setCurrentWidget(self._deleted)
        movement_id = self._deleted.selected_id()
        if movement_id is None:
            QMessageBox.information(self, tr("Tarix"), tr("Avval «O'chirilgan yozuvlar» jadvalidan yozuvni tanlang."))
            return
        try:
            self._warehouse.restore_movement(movement_id)
        except WarehouseError as error:
            QMessageBox.warning(self, tr("Tiklab bo'lmadi"), str(error))
        self.refresh()

    def _current(self) -> tuple[DataTable, str]:
        index = self._tabs.currentIndex()
        return self._tabs.widget(index), f"{tr('Tarix')} — {self._tabs.tabText(index)}"
