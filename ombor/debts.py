"""Qarzlar hisobi: yetkazib beruvchilarga qarzimiz va xaridorlarning bizdan qarzi.

Qarz «qarzga» belgisi qo'yilgan yozuvlardan hosil bo'ladi:
- kirim (qarzga) — yetkazib beruvchiga qarzimiz oshadi; unga qaytarilgan mahsulot (qarzga) kamaytiradi;
- chiqim-sotuv (qarzga) — xaridorning qarzi oshadi; undan qaytgan mahsulot (qarzga) kamaytiradi.
To'lovlar qarzni so'ndiradi. Kontragentlar nomi bo'yicha (katta-kichik harf farqsiz) birlashtiriladi.
"""

from datetime import date

from .config import CURRENCY
from .driver import sqlite3
from .errors import WarehouseError
from .formatting import fmt_date, fmt_money
from .i18n import tr
from .models import Balance, HistoryAction, MovementKind, Payment

PAYMENT_ENTITY = "payment"

# Har bir tomon uchun: qarzni oshiradigan va kamaytiradigan (qaytarish) yozuvlar summasi.
_SIDES = {
    MovementKind.IN: (
        "kind = 'IN' AND NOT is_return",
        "quantity * price",
        "kind = 'OUT' AND is_return",
        "quantity * sale_price",
    ),
    MovementKind.OUT: (
        "kind = 'OUT' AND NOT is_return",
        "quantity * sale_price",
        "kind = 'IN' AND is_return",
        "quantity * sale_price",
    ),
}


class Debts:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self.actor = ""  # o'zgarishlar tarixiga yoziladigan foydalanuvchi
        self.actor_role = ""

    def balances(self, kind: MovementKind, include_settled: bool = False) -> list[Balance]:
        """Kontragentlar bilan hisob-kitob, eng katta qarzdan boshlab.

        `kind`: IN — yetkazib beruvchilar (biz qarzmiz); OUT — xaridorlar (bizga qarz).
        Qarzi nolga teng bo'lganlar faqat `include_settled` da ko'rsatiladi.
        """
        credit_when, credit_sum, return_when, return_sum = _SIDES[kind]
        rows = self._conn.execute(
            f"""
            SELECT MIN(name) AS counterparty, SUM(credited) AS credited, SUM(returned) AS returned, SUM(paid) AS paid
            FROM (
                SELECT counterparty AS name, {credit_sum} AS credited, 0 AS returned, 0 AS paid
                FROM movements WHERE deleted_at IS NULL AND on_credit AND {credit_when}
                UNION ALL
                SELECT counterparty, 0, {return_sum}, 0
                FROM movements WHERE deleted_at IS NULL AND on_credit AND {return_when}
                UNION ALL
                SELECT counterparty, 0, 0, amount FROM payments WHERE kind = ?
            )
            GROUP BY name COLLATE NOCASE
            """,
            (kind.value,),
        )
        found = [Balance(**dict(row)) for row in rows]
        if not include_settled:
            found = [balance for balance in found if abs(balance.debt) >= 0.005]
        return sorted(found, key=lambda balance: (-balance.debt, balance.counterparty.casefold()))

    def total(self, kind: MovementKind) -> float:
        return sum(balance.debt for balance in self.balances(kind))

    def payments(self, kind: MovementKind | None = None) -> list[Payment]:
        """To'lovlar, eng yangisidan boshlab."""
        where, params = ("kind = ?", [kind.value]) if kind else ("1 = 1", [])
        rows = self._conn.execute(
            f"SELECT id, kind, date, counterparty, amount, note, created_by FROM payments"
            f" WHERE {where} ORDER BY date DESC, id DESC",
            params,
        )
        return [
            Payment(**{**dict(row), "kind": MovementKind(row["kind"]), "date": date.fromisoformat(row["date"])})
            for row in rows
        ]

    def add_payment(self, payment: Payment) -> int:
        counterparty = payment.counterparty.strip()
        if not counterparty:
            raise WarehouseError(tr("Kimga yoki kimdan to'lov ekanini kiriting."))
        if payment.amount <= 0:
            raise WarehouseError(tr("To'lov summasi noldan katta bo'lishi kerak."))
        if payment.date > date.today():
            raise WarehouseError(tr("Sana bugundan keyin bo'lishi mumkin emas."))
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO payments (kind, date, counterparty, amount, note, created_by) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    payment.kind.value,
                    payment.date.isoformat(),
                    counterparty,
                    payment.amount,
                    payment.note.strip(),
                    payment.created_by,
                ),
            )
            self._log(HistoryAction.ADD, cursor.lastrowid, payment)
        return cursor.lastrowid

    def delete_payment(self, payment_id: int) -> None:
        with self._conn:
            found = [payment for payment in self.payments() if payment.id == payment_id]
            if not found:
                raise WarehouseError(tr("To'lov topilmadi."))
            self._conn.execute("DELETE FROM payments WHERE id = ?", (payment_id,))
            self._log(HistoryAction.DELETE, payment_id, found[0])

    def counterparties(self, kind: MovementKind) -> list[str]:
        """Shu tomondagi barcha kontragentlar (to'lov oynasida taklif qilish uchun)."""
        return [balance.counterparty for balance in self.balances(kind, include_settled=True)]

    def _log(self, action: HistoryAction, payment_id: int, payment: Payment) -> None:
        summary = " · ".join(
            (fmt_date(payment.date), payment.counterparty.strip(), f"{fmt_money(payment.amount)} {CURRENCY}")
        )
        self._conn.execute(
            "INSERT INTO history (actor, actor_role, action, entity, entity_id, summary) VALUES (?, ?, ?, ?, ?, ?)",
            (self.actor, self.actor_role, action.value, f"{PAYMENT_ENTITY}:{payment.kind.value}", payment_id, summary),
        )
