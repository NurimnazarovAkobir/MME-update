"""Narx nazorati: xarid narxi qanday o'zgargani va har 6 oyda bir marta ko'rib chiqish eslatmasi.

Masalan, sentabrda 100 000 so'mga olingan mahsulot oktyabrda 120 000 so'mga olinsa — +20 %.
Taqqoslash davr ichidagi birinchi va oxirgi xarid narxi bo'yicha; inventarizatsiya ortiqchasi,
boshlang'ich qoldiq va qaytarishlar xarid hisoblanmaydi.
"""

import calendar
from datetime import date, timedelta

from .driver import sqlite3
from .models import Period, PriceChange
from .settings import Settings
from .warehouse import INVENTORY_SURPLUS, OPENING_BALANCE

REVIEW_MONTHS = 6
REVIEWED_AT_KEY = "price_review_at"  # oxirgi narx nazorati sanasi; hamma kompyuterlar uchun bitta


def add_months(day: date, months: int) -> date:
    """`day` dan `months` oy keyingi (manfiy — oldingi) kun; oyda bunday kun bo'lmasa — oyning oxirgisi."""
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def review_period(end: date) -> Period:
    """`end` kuni bilan tugaydigan 6 oylik davr (masalan, 16.04 — 16.10)."""
    return Period(add_months(end, -REVIEW_MONTHS) + timedelta(days=1), end)


class PriceControl:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._settings = Settings(conn)

    def changes(self, period: Period, only_changed: bool = True) -> list[PriceChange]:
        """Davrda xarid qilingan mahsulotlar narxi, eng katta o'zgarishdan boshlab.

        `only_changed` — faqat narxi o'zgarganlar (davrda kamida ikki marta, turli narxda olinganlar).
        """
        rows = self._conn.execute(
            """
            SELECT m.product_id, p.name, p.unit, m.date, m.price, m.counterparty
            FROM movements m JOIN products p ON p.id = m.product_id
            WHERE m.kind = 'IN' AND NOT m.is_return AND m.deleted_at IS NULL AND m.price > 0
              AND m.counterparty NOT IN (?, ?) AND m.date BETWEEN ? AND ?
            ORDER BY m.product_id, m.date, m.id
            """,
            (INVENTORY_SURPLUS, OPENING_BALANCE, period.start.isoformat(), period.end.isoformat()),
        ).fetchall()
        purchases: dict[int, list[sqlite3.Row]] = {}
        for row in rows:
            purchases.setdefault(row["product_id"], []).append(row)
        found = []
        for product_rows in purchases.values():
            first, last = product_rows[0], product_rows[-1]
            prices = [row["price"] for row in product_rows]
            change = PriceChange(
                product_id=first["product_id"],
                name=first["name"],
                unit=first["unit"],
                first_date=date.fromisoformat(first["date"]),
                first_price=first["price"],
                last_date=date.fromisoformat(last["date"]),
                last_price=last["price"],
                min_price=min(prices),
                max_price=max(prices),
                purchases=len(product_rows),
                last_supplier=last["counterparty"],
            )
            if not only_changed or change.max_price - change.min_price > 0.005:
                found.append(change)
        return sorted(found, key=lambda change: (-abs(change.percent), change.name.casefold()))

    # --- Eslatma -----------------------------------------------------------

    @property
    def reviewed_at(self) -> date | None:
        value = self._settings.get(REVIEWED_AT_KEY)
        return date.fromisoformat(value) if value else None

    def next_review(self) -> date | None:
        """Keyingi nazorat sanasi; hali hech qachon o'tkazilmagan bo'lsa — None (ya'ni hozir)."""
        reviewed = self.reviewed_at
        return add_months(reviewed, REVIEW_MONTHS) if reviewed else None

    def is_due(self, today: date | None = None) -> bool:
        """Narxlarni ko'rib chiqish vaqti keldimi (oxirgisidan 6 oy o'tgan yoki hali o'tkazilmagan)."""
        upcoming = self.next_review()
        return upcoming is None or upcoming <= (today or date.today())

    def mark_reviewed(self, today: date | None = None) -> None:
        self._settings.set(REVIEWED_AT_KEY, (today or date.today()).isoformat())
