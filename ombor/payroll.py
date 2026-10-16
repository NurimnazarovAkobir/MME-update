"""Buxgalteriya: xodimlar va oyliklar (perechisleniye, karta yoki naqd).

Har bir oy uchun xodimning hisoblangan oyligi — uning joriy oylik maoshi; to'lovlar shu oy
uchun berilgan summalar yig'indisi. Bir oy oyligini bir necha qismda va turli usulda berish mumkin.
"""

from datetime import date

from .config import CURRENCY
from .driver import sqlite3
from .errors import WarehouseError
from .formatting import fmt_date, fmt_money
from .i18n import tr
from .models import Employee, HistoryAction, PaymentMethod, SalaryLine, SalaryPayment

EMPLOYEE_ENTITY = "employee"
SALARY_ENTITY = "salary"


def month_key(day: date) -> str:
    """Bazada saqlanadigan oy: 'YYYY-MM'."""
    return f"{day:%Y-%m}"


def _month_of(key: str) -> date:
    return date.fromisoformat(f"{key}-01")


class Payroll:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self.actor = ""  # o'zgarishlar tarixiga yoziladigan foydalanuvchi
        self.actor_role = ""

    # --- Xodimlar ----------------------------------------------------------

    def employees(self, include_inactive: bool = False) -> list[Employee]:
        where = "" if include_inactive else "WHERE active"
        rows = self._conn.execute(
            f"SELECT id, name, position, salary, note, active FROM employees {where} ORDER BY active DESC, name"
        )
        return [Employee(**{**dict(row), "active": bool(row["active"])}) for row in rows]

    def employee(self, employee_id: int) -> Employee:
        found = [employee for employee in self.employees(include_inactive=True) if employee.id == employee_id]
        if not found:
            raise WarehouseError(tr("Xodim topilmadi."))
        return found[0]

    def save_employee(self, employee: Employee) -> int:
        name = " ".join(employee.name.split())
        if not name:
            raise WarehouseError(tr("Xodimning ismini kiriting."))
        if employee.salary < 0:
            raise WarehouseError(tr("Oylik manfiy bo'lishi mumkin emas."))
        values = (name, employee.position.strip(), employee.salary, employee.note.strip(), int(employee.active))
        summary = " · ".join(part for part in (name, employee.position.strip(), _money(employee.salary)) if part)
        try:
            with self._conn:
                if employee.id is None:
                    employee_id = self._conn.execute(
                        "INSERT INTO employees (name, position, salary, note, active) VALUES (?, ?, ?, ?, ?)", values
                    ).lastrowid
                    self._log(HistoryAction.ADD, EMPLOYEE_ENTITY, employee_id, summary)
                    return employee_id
                self._conn.execute(
                    "UPDATE employees SET name = ?, position = ?, salary = ?, note = ?, active = ? WHERE id = ?",
                    (*values, employee.id),
                )
                self._log(HistoryAction.EDIT, EMPLOYEE_ENTITY, employee.id, summary)
                return employee.id
        except sqlite3.IntegrityError as error:
            raise WarehouseError(tr("«{0}» ismli xodim allaqachon bor.").format(name)) from error

    def delete_employee(self, employee_id: int) -> None:
        """To'lovi yo'q xodimni o'chiradi; to'lovi bo'lsa — «ishdan ketgan» deb belgilash taklif qilinadi."""
        employee = self.employee(employee_id)
        if self._conn.execute("SELECT 1 FROM salary_payments WHERE employee_id = ? LIMIT 1", (employee_id,)).fetchone():
            raise WarehouseError(
                tr("{0} uchun oylik to'lovlari bor. O'chirish o'rniga uni «Ishdan ketgan» deb belgilang.").format(
                    employee.name
                )
            )
        with self._conn:
            self._conn.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
            self._log(HistoryAction.DELETE, EMPLOYEE_ENTITY, employee_id, employee.name)

    # --- To'lovlar ---------------------------------------------------------

    def payments(self, month: date | None = None, employee_id: int | None = None) -> list[SalaryPayment]:
        """To'lovlar, eng yangisidan boshlab; `month` berilsa — faqat shu oy uchun."""
        clauses, params = [], []
        if month is not None:
            clauses.append("s.month = ?")
            params.append(month_key(month))
        if employee_id is not None:
            clauses.append("s.employee_id = ?")
            params.append(employee_id)
        rows = self._conn.execute(
            f"""
            SELECT s.id, s.employee_id, s.date, s.month, s.amount, s.method, s.note, s.created_by,
                   e.name AS employee_name
            FROM salary_payments s JOIN employees e ON e.id = s.employee_id
            WHERE {" AND ".join(clauses) or "1 = 1"} ORDER BY s.date DESC, s.id DESC
            """,
            params,
        )
        return [
            SalaryPayment(
                **{
                    **dict(row),
                    "date": date.fromisoformat(row["date"]),
                    "month": _month_of(row["month"]),
                    "method": PaymentMethod(row["method"]),
                }
            )
            for row in rows
        ]

    def payment(self, payment_id: int) -> SalaryPayment:
        found = [payment for payment in self.payments() if payment.id == payment_id]
        if not found:
            raise WarehouseError(tr("To'lov topilmadi."))
        return found[0]

    def save_payment(self, payment: SalaryPayment, today: date | None = None) -> int:
        if payment.amount <= 0:
            raise WarehouseError(tr("To'lov summasi noldan katta bo'lishi kerak."))
        if payment.date > (today or date.today()):
            raise WarehouseError(tr("Sana bugundan keyin bo'lishi mumkin emas."))
        employee = self.employee(payment.employee_id)
        values = (
            payment.employee_id,
            payment.date.isoformat(),
            month_key(payment.month),
            payment.amount,
            payment.method.value,
            payment.note.strip(),
        )
        summary = " · ".join(
            (
                fmt_date(payment.date),
                employee.name,
                f"{payment.month:%m.%Y}",
                _money(payment.amount),
                payment.method.title,
            )
        )
        with self._conn:
            if payment.id is None:
                payment_id = self._conn.execute(
                    "INSERT INTO salary_payments (employee_id, date, month, amount, method, note, created_by)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (*values, payment.created_by),
                ).lastrowid
                self._log(HistoryAction.ADD, SALARY_ENTITY, payment_id, summary)
                return payment_id
            self._conn.execute(
                "UPDATE salary_payments SET employee_id = ?, date = ?, month = ?, amount = ?, method = ?, note = ?"
                " WHERE id = ?",
                (*values, payment.id),
            )
            self._log(HistoryAction.EDIT, SALARY_ENTITY, payment.id, summary)
            return payment.id

    def delete_payment(self, payment_id: int) -> None:
        payment = self.payment(payment_id)
        with self._conn:
            self._conn.execute("DELETE FROM salary_payments WHERE id = ?", (payment_id,))
            self._log(
                HistoryAction.DELETE,
                SALARY_ENTITY,
                payment_id,
                " · ".join((fmt_date(payment.date), payment.employee_name, _money(payment.amount))),
            )

    # --- Hisob-kitob -------------------------------------------------------

    def month_sheet(self, month: date) -> list[SalaryLine]:
        """Oylik vedomosti: faol xodimlar va shu oy uchun to'lov olgan (ishdan ketgan) xodimlar."""
        paid: dict[int, dict[PaymentMethod, float]] = {}
        for payment in self.payments(month):
            by_method = paid.setdefault(payment.employee_id, {})
            by_method[payment.method] = by_method.get(payment.method, 0.0) + payment.amount
        return [
            SalaryLine(employee.id, employee.name, employee.position, employee.salary, paid.get(employee.id, {}))
            for employee in self.employees(include_inactive=True)
            if employee.active or employee.id in paid
        ]

    def remaining(self, employee_id: int, month: date) -> float:
        """Xodimga shu oy uchun yana qancha berilishi kerak (oyna ochilganda summa sifatida taklif qilinadi)."""
        line = next((line for line in self.month_sheet(month) if line.employee_id == employee_id), None)
        return max(line.remaining, 0.0) if line else 0.0

    def totals_by_method(self, month: date) -> dict[PaymentMethod, float]:
        """Shu oy uchun har bir usulda jami qancha berilgan."""
        totals = {method: 0.0 for method in PaymentMethod}
        for payment in self.payments(month):
            totals[payment.method] += payment.amount
        return totals

    def _log(self, action: HistoryAction, entity: str, entity_id: int, summary: str) -> None:
        self._conn.execute(
            "INSERT INTO history (actor, actor_role, action, entity, entity_id, summary) VALUES (?, ?, ?, ?, ?, ?)",
            (self.actor, self.actor_role, action.value, entity, entity_id, summary),
        )


def _money(amount: float) -> str:
    return f"{fmt_money(amount)} {CURRENCY}"
