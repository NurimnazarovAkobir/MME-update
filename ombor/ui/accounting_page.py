"""Buxgalteriya: xodimlar va oyliklar (perechisleniye, karta, naqd). Bo'limga alohida parol bilan kiriladi."""

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..auth import Auth
from ..config import CURRENCY
from ..errors import WarehouseError
from ..formatting import fmt_money, fmt_period
from ..i18n import tr
from ..models import Employee, Granularity, PaymentMethod, SalaryPayment
from ..payroll import Payroll
from ..session import Session
from .dialogs import FormDialog
from .icons import Glyph, icon_label
from .printing import print_table
from .widgets import (
    Column,
    ColumnKind,
    DataTable,
    StatCard,
    button,
    card,
    confirm,
    date_input,
    export_to_excel,
    label,
    number_input,
    page_header,
)

MONTH_FORMAT = "MM.yyyy"
LOCK_CARD_WIDTH = 440
LOCK_ICON_SIZE = 56
SHEET_TAB, PAYMENTS_TAB, EMPLOYEES_TAB = range(3)


def first_of_month(day: date) -> date:
    return day.replace(day=1)


def month_input(day: date) -> QDateEdit:
    """Oy tanlash maydoni («10.2026»)."""
    widget = QDateEdit(QDate(first_of_month(day)))
    widget.setDisplayFormat(MONTH_FORMAT)
    widget.setCalendarPopup(True)
    return widget


class AccountingPasswordDialog(FormDialog):
    """Rahbar «Buxgalteriya» bo'limi parolini o'rnatadi yoki almashtiradi."""

    def __init__(self, auth: Auth, parent: QWidget | None = None):
        super().__init__(tr("Buxgalteriya paroli"), parent)
        self._auth = auth
        self._new, self._repeat = _password_input(), _password_input()
        hint = label(
            tr("Bu parol foydalanuvchilar parolidan alohida: uni faqat buxgalteriya bilan ishlaydiganlarga ayting."),
            "muted",
        )
        hint.setWordWrap(True)
        self.form.addRow(hint)
        self.form.addRow(tr("Yangi parol"), self._new)
        self.form.addRow(tr("Parolni takrorlang"), self._repeat)

    def save(self) -> None:
        if self._new.text() != self._repeat.text():
            raise WarehouseError(tr("Parollar bir xil emas. Qaytadan kiriting."))
        self._auth.set_accounting_password(self._new.text())


def _password_input() -> QLineEdit:
    widget = QLineEdit()
    widget.setEchoMode(QLineEdit.EchoMode.Password)
    return widget


class EmployeeDialog(FormDialog):
    def __init__(self, payroll: Payroll, employee: Employee | None = None, parent: QWidget | None = None):
        super().__init__(tr("Xodimni tahrirlash") if employee else tr("Yangi xodim"), parent)
        self._payroll = payroll
        self._employee_id = employee.id if employee else None
        self._name = QLineEdit(employee.name if employee else "")
        self._name.setPlaceholderText(tr("Familiya va ism"))
        self._position = QLineEdit(employee.position if employee else "")
        self._salary = number_input(2, employee.salary if employee else 0)
        self._salary.setSuffix(f" {CURRENCY}")
        self._note = QLineEdit(employee.note if employee else "")
        self._active = QCheckBox(tr("Ishlayapti (belgi olib tashlansa — ishdan ketgan, ro'yxatda yashiriladi)"))
        self._active.setChecked(employee.active if employee else True)

        self.form.addRow(tr("Ismi *"), self._name)
        self.form.addRow(tr("Lavozimi"), self._position)
        self.form.addRow(tr("Oylik maoshi"), self._salary)
        self.form.addRow(tr("Izoh"), self._note)
        if employee:
            self.form.addRow("", self._active)

    def save(self) -> None:
        self._payroll.save_employee(
            Employee(
                name=self._name.text(),
                position=self._position.text(),
                salary=self._salary.value(),
                note=self._note.text(),
                active=self._active.isChecked(),
                id=self._employee_id,
            )
        )


class SalaryPaymentDialog(FormDialog):
    """Oylik to'lovi: kimga, qaysi oy uchun, qancha va qanday usulda (perechisleniye, karta, naqd)."""

    def __init__(
        self,
        payroll: Payroll,
        author: str,
        month: date,
        payment: SalaryPayment | None = None,
        employee_id: int | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(tr("To'lovni tahrirlash") if payment else tr("Oylik to'lash"), parent)
        self._payroll = payroll
        self._author = author
        self._payment_id = payment.id if payment else None
        self._amount_edited = payment is not None  # qo'lda yozilgan summaga tegilmaydi

        self._employee = QComboBox()
        current = payment.employee_id if payment else employee_id
        for employee in payroll.employees(include_inactive=True):
            if employee.active or employee.id == current:
                self._employee.addItem(
                    f"{employee.name} — {employee.position}" if employee.position else employee.name, employee.id
                )
        self._employee.setCurrentIndex(max(self._employee.findData(current), 0))
        self._month = month_input(payment.month if payment else month)
        self._date = date_input(payment.date if payment else None, allow_future=False)
        self._method = QComboBox()
        for method in PaymentMethod:
            self._method.addItem(method.title, method)
        self._method.setCurrentIndex(
            max(self._method.findData(payment.method if payment else PaymentMethod.TRANSFER), 0)
        )
        self._amount = number_input(2, payment.amount if payment else 0)
        self._amount.setSuffix(f" {CURRENCY}")
        self._amount.valueChanged.connect(self._mark_edited)
        self._hint = label("", "muted")
        self._note = QLineEdit(payment.note if payment else "")

        self.form.addRow(tr("Xodim *"), self._employee)
        self.form.addRow(tr("Qaysi oy uchun *"), self._month)
        self.form.addRow("", self._hint)
        self.form.addRow(tr("To'lov usuli *"), self._method)
        self.form.addRow(tr("Summa *"), self._amount)
        self.form.addRow(tr("To'langan sana *"), self._date)
        self.form.addRow(tr("Izoh"), self._note)

        self._employee.currentIndexChanged.connect(self._update_hint)
        self._month.dateChanged.connect(self._update_hint)
        self._update_hint()

    def save(self) -> None:
        if self._employee.currentData() is None:
            raise WarehouseError(tr("Avval «Xodimlar» bo'limida xodim qo'shing."))
        self._payroll.save_payment(
            SalaryPayment(
                employee_id=self._employee.currentData(),
                date=self._date.date().toPython(),
                month=first_of_month(self._month.date().toPython()),
                amount=self._amount.value(),
                method=self._method.currentData(),
                note=self._note.text(),
                created_by=self._author,
                id=self._payment_id,
            )
        )

    def _mark_edited(self) -> None:
        if self._amount.hasFocus():
            self._amount_edited = True

    def _update_hint(self) -> None:
        """Tanlangan oy uchun xodimning oyligi va qolgani; yangi to'lovda summa sifatida qolgani taklif qilinadi."""
        employee_id = self._employee.currentData()
        if employee_id is None:
            self._hint.setText("")
            return
        month = first_of_month(self._month.date().toPython())
        line = next((line for line in self._payroll.month_sheet(month) if line.employee_id == employee_id), None)
        if line is None:
            self._hint.setText("")
            return
        self._hint.setText(
            tr("Oylik: {0}  ·  berilgan: {1}  ·  qolgan: {2} {3}").format(
                fmt_money(line.salary), fmt_money(line.total_paid), fmt_money(max(line.remaining, 0)), CURRENCY
            )
        )
        if not self._amount_edited:
            self._amount.blockSignals(True)
            self._amount.setValue(max(line.remaining, 0))
            self._amount.blockSignals(False)


class MonthNavigator(QWidget):
    """◀ Oktabr 2026 ▶ — oyma-oy o'tish."""

    def __init__(self, on_change):
        super().__init__()
        self.month = first_of_month(date.today())
        self._on_change = on_change
        previous = button("", "page", Glyph.PREVIOUS)
        previous.setToolTip(tr("Oldingi oy"))
        previous.clicked.connect(lambda: self._step(-1))
        following = button("", "page", Glyph.NEXT)
        following.setToolTip(tr("Keyingi oy"))
        following.clicked.connect(lambda: self._step(1))
        self._title = label("", "periodTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setMinimumWidth(150)
        bar = QFrame()
        bar.setObjectName("segmentBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(6)
        for widget in (previous, icon_label(Glyph.CALENDAR), self._title, following):
            row.addWidget(widget)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(bar)
        self._show()

    def _step(self, direction: int) -> None:
        self.month = Granularity.MONTH.shift(self.month, direction)
        self._show()
        self._on_change()

    def _show(self) -> None:
        self._title.setText(fmt_period(Granularity.MONTH, self.month))


class AccountingPage(QWidget):
    """Parol so'raydigan qulf oynasi va uning ortida — oylik vedomosti, to'lovlar, xodimlar.

    Bo'lim boshqa sahifaga o'tilganda yana qulflanadi.
    """

    def __init__(self, payroll: Payroll, auth: Auth, session: Session):
        super().__init__()
        self.setObjectName("page")
        self._payroll = payroll
        self._auth = auth
        self._session = session
        self._unlocked = False

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_lock())
        self._stack.addWidget(self._build_content())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

    @property
    def is_unlocked(self) -> bool:
        return self._unlocked

    def refresh(self) -> None:
        self._stack.setCurrentIndex(1 if self._unlocked else 0)
        if not self._unlocked:
            self._show_lock_state()
            return
        self._fill()

    def unlock(self, password: str) -> bool:
        try:
            self._auth.check_accounting_password(password)
        except WarehouseError as error:
            self._lock_error.setText(str(error))
            return False
        self._unlocked = True
        self._password.clear()
        self._lock_error.setText("")
        self.refresh()
        return True

    def lock(self) -> None:
        self._unlocked = False
        self.refresh()

    def hideEvent(self, event) -> None:
        """Boshqa bo'limga o'tilganda bo'lim qulflanadi (oyna kichraytirilganda — yo'q)."""
        super().hideEvent(event)
        if not event.spontaneous() and self._unlocked:
            self._unlocked = False
            self._stack.setCurrentIndex(0)

    # --- Qulf ------------------------------------------------------------------

    def _build_lock(self) -> QWidget:
        badge = icon_label(Glyph.WALLET, "pageIcon")
        badge.setFixedSize(LOCK_ICON_SIZE, LOCK_ICON_SIZE)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._password = _password_input()
        self._password.setPlaceholderText(tr("Buxgalteriya paroli"))
        self._password.returnPressed.connect(lambda: self.unlock(self._password.text()))
        self._open_button = button(tr("Ochish"), "primary")
        self._open_button.clicked.connect(lambda: self.unlock(self._password.text()))
        self._lock_text = label("", "muted")
        self._lock_text.setWordWrap(True)
        self._lock_error = label("", "error")
        self._set_password = button(tr("Parol o'rnatish"), "primary")
        self._set_password.clicked.connect(self._create_password)
        field = QHBoxLayout()
        field.addWidget(self._password, stretch=1)
        field.addWidget(self._open_button)
        frame = card(badge, label(tr("Buxgalteriya"), "pageTitle"), self._lock_text)
        frame.layout().addLayout(field)
        frame.layout().addWidget(self._lock_error)
        frame.layout().addWidget(self._set_password)
        frame.layout().setSpacing(10)
        frame.setFixedWidth(LOCK_CARD_WIDTH)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        layout.addWidget(frame, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(2)
        return page

    def _show_lock_state(self) -> None:
        has_password = self._auth.has_accounting_password()
        if has_password:
            self._lock_text.setText(tr("Oyliklar va xodimlar bo'limi. Kirish uchun buxgalteriya parolini kiriting."))
        elif self._session.is_admin:
            self._lock_text.setText(tr("Bo'limga kirish uchun avval buxgalteriya parolini o'rnating."))
        else:
            self._lock_text.setText(tr("Buxgalteriya paroli hali o'rnatilmagan. Uni rahbar «Sozlamalar»da o'rnatadi."))
        for widget in (self._password, self._open_button):
            widget.setVisible(has_password)
        self._set_password.setVisible(not has_password and self._session.is_admin)

    def _create_password(self) -> None:
        if AccountingPasswordDialog(self._auth, self).exec():
            self.refresh()

    # --- Mazmuni ---------------------------------------------------------------

    def _build_content(self) -> QWidget:
        self._month = MonthNavigator(self._fill)
        header, tools = page_header(
            Glyph.WALLET, tr("Buxgalteriya"), tr("Oyliklar: perechisleniye, karta va naqd pul orqali to'lovlar")
        )
        tools.addWidget(self._month)
        lock = button(tr("Qulflash"), glyph=Glyph.LOCK)
        lock.setToolTip(tr("Bo'limni yopish: qayta kirish uchun parol so'raladi"))
        lock.clicked.connect(self.lock)
        tools.addWidget(lock)

        self._cards = {
            "salary": StatCard(tr("Hisoblangan oylik"), Glyph.PEOPLE, "Accent"),
            PaymentMethod.TRANSFER: StatCard(PaymentMethod.TRANSFER.title, Glyph.SWITCH, "Violet"),
            PaymentMethod.CARD: StatCard(PaymentMethod.CARD.title, Glyph.WALLET, "Good"),
            PaymentMethod.CASH: StatCard(PaymentMethod.CASH.title, Glyph.MONEY, "Warning"),
            "remaining": StatCard(tr("Berilishi kerak"), Glyph.CLOCK, "Out"),
        }
        summary = QHBoxLayout()
        summary.setSpacing(14)
        for stat in self._cards.values():
            summary.addWidget(stat)

        methods = [Column(method.title, ColumnKind.MONEY) for method in PaymentMethod]
        self._sheet = DataTable(
            (
                Column(tr("Xodim"), style="strong"),
                Column(tr("Lavozimi")),
                Column(tr("Oylik"), ColumnKind.MONEY),
                *methods,
                Column(tr("Jami berildi"), ColumnKind.MONEY, "strong"),
                Column(tr("Qolgan"), ColumnKind.MONEY, "signed"),
            )
        )
        self._payments = DataTable(
            (
                Column(tr("Sana"), ColumnKind.DATE),
                Column(tr("Xodim"), style="strong"),
                Column(tr("Oy")),
                Column(tr("Usul")),
                Column(tr("Summa"), ColumnKind.MONEY, "strong"),
                Column(tr("Izoh")),
                Column(tr("Kiritdi")),
            ),
            row_actions=True,
        )
        self._payments.edit_requested.connect(self._edit_payment)
        self._payments.row_activated.connect(self._edit_payment)
        self._payments.delete_requested.connect(self._delete_payment)
        self._employees = DataTable(
            (
                Column(tr("Ismi"), style="strong"),
                Column(tr("Lavozimi")),
                Column(tr("Oylik maoshi"), ColumnKind.MONEY),
                Column(tr("Holati")),
                Column(tr("Izoh")),
            ),
            row_actions=True,
        )
        self._employees.edit_requested.connect(self._edit_employee)
        self._employees.row_activated.connect(self._edit_employee)
        self._employees.delete_requested.connect(self._delete_employee)
        self._tabs = QTabWidget()
        for table, title in (
            (self._sheet, tr("Oylik vedomosti")),
            (self._payments, tr("To'lovlar")),
            (self._employees, tr("Xodimlar")),
        ):
            table.setObjectName("flatTable")
            self._tabs.addTab(table, title)

        pay = button(tr("Oylik to'lash"), "primary", Glyph.ADD)
        pay.clicked.connect(self._add_payment)
        add_employee = button(tr("Yangi xodim"), glyph=Glyph.PERSON)
        add_employee.clicked.connect(lambda: self._edit_employee(None))
        print_button = button(tr("Chop etish"), "print", Glyph.PRINT)
        print_button.clicked.connect(lambda: print_table(self, *self._current_table()))
        excel = button(tr("Excelga chiqarish"), "excel", Glyph.EXPORT)
        excel.clicked.connect(lambda: export_to_excel(self, *self._current_table()))
        toolbar = QHBoxLayout()
        for widget in (pay, add_employee):
            toolbar.addWidget(widget)
        toolbar.addStretch()
        toolbar.addWidget(print_button)
        toolbar.addWidget(excel)
        self._footer = label("", "total")

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)
        layout.addLayout(header)
        layout.addLayout(summary)
        layout.addLayout(toolbar)
        layout.addWidget(card(self._tabs), stretch=1)
        layout.addWidget(self._footer)
        return page

    def _fill(self) -> None:
        if not self._unlocked:
            return
        month = self._month.month
        lines = self._payroll.month_sheet(month)
        self._sheet.set_rows(
            [
                (
                    line.name,
                    line.position,
                    line.salary,
                    *(line.paid.get(method, 0.0) for method in PaymentMethod),
                    line.total_paid,
                    line.remaining,
                )
                for line in lines
            ],
            ids=[line.employee_id for line in lines],
            flagged=[index for index, line in enumerate(lines) if line.remaining > 0.005],
        )
        payments = self._payroll.payments(month)
        self._payments.set_rows(
            [
                (p.date, p.employee_name, f"{p.month:%m.%Y}", p.method.title, p.amount, p.note, p.created_by)
                for p in payments
            ],
            ids=[p.id for p in payments],
        )
        employees = self._payroll.employees(include_inactive=True)
        self._employees.set_rows(
            [
                (e.name, e.position, e.salary, tr("Ishlayapti") if e.active else tr("Ishdan ketgan"), e.note)
                for e in employees
            ],
            ids=[e.id for e in employees],
        )

        totals = self._payroll.totals_by_method(month)
        salary = sum(line.salary for line in lines)
        remaining = sum(max(line.remaining, 0) for line in lines)
        self._cards["salary"].set_value(fmt_money(salary), tr("{0} ta xodim").format(len(lines)))
        for method in PaymentMethod:
            self._cards[method].set_value(fmt_money(totals[method]), CURRENCY)
        self._cards["remaining"].set_value(fmt_money(remaining), CURRENCY)
        self._footer.setText(
            tr("{0}: jami berildi {1} {2}").format(
                fmt_period(Granularity.MONTH, month), fmt_money(sum(totals.values())), CURRENCY
            )
        )

    def _current_table(self) -> tuple[DataTable, str]:
        index = self._tabs.currentIndex()
        title = (
            f"{tr('Buxgalteriya')} — {self._tabs.tabText(index)} ({fmt_period(Granularity.MONTH, self._month.month)})"
        )
        return self._tabs.widget(index), title

    def _add_payment(self) -> None:
        if not self._payroll.employees():
            QMessageBox.information(self, tr("Buxgalteriya"), tr("Avval «Xodimlar» bo'limida xodim qo'shing."))
            self._tabs.setCurrentIndex(EMPLOYEES_TAB)
            return
        employee_id = self._sheet.selected_id() if self._tabs.currentIndex() == SHEET_TAB else None
        dialog = SalaryPaymentDialog(
            self._payroll, self._session.author, self._month.month, employee_id=employee_id, parent=self
        )
        if dialog.exec():
            self._fill()

    def _edit_payment(self, payment_id: int) -> None:
        payment = self._payroll.payment(payment_id)
        if SalaryPaymentDialog(self._payroll, self._session.author, payment.month, payment, parent=self).exec():
            self._fill()

    def _delete_payment(self, payment_id: int) -> None:
        if confirm(self, tr("O'chirish"), tr("Bu to'lov o'chirilsinmi?"), tr("Ha, o'chirish")):
            self._apply(lambda: self._payroll.delete_payment(payment_id))

    def _edit_employee(self, employee_id: int | None) -> None:
        employee = self._payroll.employee(employee_id) if employee_id is not None else None
        if EmployeeDialog(self._payroll, employee, self).exec():
            self._fill()

    def _delete_employee(self, employee_id: int) -> None:
        question = tr("{0} ro'yxatdan o'chirilsinmi?").format(self._payroll.employee(employee_id).name)
        if confirm(self, tr("O'chirish"), question, tr("Ha, o'chirish")):
            self._apply(lambda: self._payroll.delete_employee(employee_id))

    def _apply(self, change) -> None:
        try:
            change()
        except WarehouseError as error:
            QMessageBox.warning(self, tr("Diqqat"), str(error))
        self._fill()
