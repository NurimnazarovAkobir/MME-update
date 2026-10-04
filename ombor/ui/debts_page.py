"""Qarzlar: yetkazib beruvchilarga qarzimiz, xaridorlarning qarzi va to'lovlar."""

from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QTabWidget, QVBoxLayout, QWidget

from ..config import CURRENCY
from ..debts import Debts
from ..errors import WarehouseError
from ..formatting import fmt_money
from ..i18n import tr
from ..models import MovementKind
from ..session import Session
from .extra_dialogs import PaymentDialog
from .printing import print_table
from .widgets import Column, ColumnKind, DataTable, button, confirm, export_to_excel, label

# Ikkala tomon: jadval sarlavhasi va «qarzga olingan/berilgan» ustuni nomi.
_SIDES = (
    (MovementKind.IN, tr("Biz qarzmiz (yetkazib beruvchilar)"), tr("Yetkazib beruvchi"), tr("Qarzga olingan")),
    (MovementKind.OUT, tr("Bizga qarz (xaridorlar)"), tr("Xaridor / obyekt"), tr("Qarzga berilgan")),
)
_PAYMENT_TITLES = {MovementKind.IN: tr("Biz to'ladik"), MovementKind.OUT: tr("Bizga to'landi")}


class DebtsPage(QWidget):
    def __init__(self, debts: Debts, session: Session):
        super().__init__()
        self.setObjectName("page")
        self._debts = debts
        self._session = session

        self._tabs = QTabWidget()
        self._balances: dict[MovementKind, DataTable] = {}
        for kind, title, name, credited in _SIDES:
            table = DataTable(
                (
                    Column(name),
                    Column(credited, ColumnKind.MONEY),
                    Column(tr("Qaytarilgan"), ColumnKind.MONEY),
                    Column(tr("To'langan"), ColumnKind.MONEY),
                    Column(tr("Qolgan qarz"), ColumnKind.MONEY),
                )
            )
            self._balances[kind] = table
            self._tabs.addTab(table, title)
        self._payments = DataTable(
            (
                Column(tr("Sana"), ColumnKind.DATE),
                Column(tr("Turi")),
                Column(tr("Kontragent")),
                Column(tr("Summa"), ColumnKind.MONEY),
                Column(tr("Izoh")),
                Column(tr("Kiritdi")),
            )
        )
        self._tabs.addTab(self._payments, tr("To'lovlar"))
        self._footer = label("", "total")

        toolbar = QHBoxLayout()
        if session.can_add:
            pay = button(tr("+ To'lov yozish"), "primary")
            pay.setToolTip(tr("Tanlangan kontragent bo'yicha to'lovni yozish"))
            pay.clicked.connect(self._add_payment)
            toolbar.addWidget(pay)
        if session.can_modify:
            remove = button(tr("To'lovni o'chirish"), "danger")
            remove.clicked.connect(self._delete_payment)
            toolbar.addWidget(remove)
        toolbar.addStretch()
        print_button = button(tr("Chop etish"))
        print_button.clicked.connect(lambda: print_table(self, *self._current()))
        excel = button(tr("Excelga chiqarish"))
        excel.clicked.connect(lambda: export_to_excel(self, *self._current()))
        toolbar.addWidget(print_button)
        toolbar.addWidget(excel)

        hint = label(
            tr(
                "Qarz kirim yoki chiqimda «Qarzga» belgisi qo'yilgan yozuvlardan hosil bo'ladi; to'lov uni kamaytiradi."
            ),
            "muted",
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)
        layout.addWidget(label(tr("Qarzlar"), "pageTitle"))
        layout.addWidget(hint)
        layout.addLayout(toolbar)
        layout.addWidget(self._tabs, stretch=1)
        layout.addWidget(self._footer)

    def refresh(self) -> None:
        totals = {}
        for kind, table in self._balances.items():
            balances = self._debts.balances(kind)
            table.set_rows(
                [(b.counterparty, b.credited, b.returned, b.paid, b.debt) for b in balances],
                ids=list(range(len(balances))),
            )
            totals[kind] = sum(balance.debt for balance in balances)
        payments = self._debts.payments()
        self._payments.set_rows(
            [(p.date, _PAYMENT_TITLES[p.kind], p.counterparty, p.amount, p.note, p.created_by) for p in payments],
            ids=[p.id for p in payments],
        )
        self._footer.setText(
            tr("Biz qarzmiz: {0} {2}  ·  bizga qarz: {1} {2}").format(
                fmt_money(totals[MovementKind.IN]), fmt_money(totals[MovementKind.OUT]), CURRENCY
            )
        )

    def _current_kind(self) -> MovementKind | None:
        """Ochiq turgan jadval qaysi tomonniki; «To'lovlar»da — None."""
        index = self._tabs.currentIndex()
        return _SIDES[index][0] if index < len(_SIDES) else None

    def _add_payment(self) -> None:
        kind = self._current_kind()
        counterparty = ""
        if kind is None:
            kind = MovementKind.IN
        else:
            row = self._balances[kind].currentRow()
            item = self._balances[kind].item(row, 0) if row >= 0 else None
            counterparty = item.text() if item else ""
        if PaymentDialog(self._debts, kind, self._session.author, counterparty, self).exec():
            self.refresh()

    def _delete_payment(self) -> None:
        self._tabs.setCurrentWidget(self._payments)
        payment_id = self._payments.selected_id()
        if payment_id is None:
            QMessageBox.information(self, tr("Qarzlar"), tr("Avval «To'lovlar» jadvalidan to'lovni tanlang."))
            return
        if not confirm(self, tr("O'chirish"), tr("Bu to'lov o'chirilsinmi?"), tr("Ha, o'chirish")):
            return
        try:
            self._debts.delete_payment(payment_id)
        except WarehouseError as error:
            QMessageBox.warning(self, tr("O'chirib bo'lmadi"), str(error))
        self.refresh()

    def _current(self) -> tuple[DataTable, str]:
        index = self._tabs.currentIndex()
        return self._tabs.widget(index), f"{tr('Qarzlar')} — {self._tabs.tabText(index)}"
