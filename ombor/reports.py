"""Statistika va hisobotlar."""

from dataclasses import dataclass
from datetime import date
from enum import Enum

from .database import period_filter
from .driver import sqlite3
from .i18n import tr
from .models import Granularity, MovementKind, Period
from .warehouse import display_counterparty

UNNAMED = tr("(ko'rsatilmagan)")

# Davr chegarasi berilmaganda ishlatiladigan, har qanday sanadan kichik/katta qiymatlar.
EARLIEST_DATE = ""
LATEST_DATE = "9999-12-31"

# «Kirim» summalariga qaytgan mahsulot (vozvrat) kirmaydi: u xarid emas va o'z bo'limida ko'rsatiladi.
_IS_RECEIPT = "kind = 'IN' AND NOT is_return"

# Har bir yozuv sanasidan o'sha davrning birinchi kunini beruvchi SQL ifodalari.
_BUCKET_START = {
    Granularity.DAY: "date",
    Granularity.WEEK: "date(date, 'weekday 0', '-6 days')",
    Granularity.MONTH: "substr(date, 1, 7) || '-01'",
    Granularity.YEAR: "substr(date, 1, 4) || '-01-01'",
}


class GroupBy(Enum):
    """Hisobotni guruhlash maydoni; qiymati — jadvaldagi ustun nomi."""

    PERSON = "person"
    COUNTERPARTY = "counterparty"


@dataclass(frozen=True)
class Totals:
    amount_in: float
    amount_out: float
    count_in: int
    count_out: int


@dataclass(frozen=True)
class ProductTurnover:
    """Aylanma qaydnoma qatori: davr boshidagi qoldiq va davr ichidagi harakat."""

    name: str
    unit: str
    opening: float
    qty_in: float
    amount_in: float
    qty_out: float
    amount_out: float

    @property
    def closing(self) -> float:
        return round(self.opening + self.qty_in - self.qty_out, 6)


@dataclass(frozen=True)
class CategoryTotal:
    """Tovar guruhi va kategoriyasi bo'yicha jami."""

    category: str
    subcategory: str
    amount_in: float
    amount_out: float


@dataclass(frozen=True)
class GroupTotal:
    name: str
    operations: int
    amount: float


@dataclass(frozen=True)
class PaymentTotal:
    """Xaridlar (kirim) bitta to'lov turi bo'yicha: qanchasi to'langan, qanchasi to'lanmagan."""

    method: str  # bazadagi nomi (payments.py); bo'sh — ko'rsatilmagan
    operations: int
    paid: float
    unpaid: float

    @property
    def total(self) -> float:
        return self.paid + self.unpaid


@dataclass(frozen=True)
class PeriodTotal:
    """Bitta kun, hafta, oy yoki yil bo'yicha jami."""

    start: date  # davrning birinchi kuni
    amount_in: float = 0.0
    amount_out: float = 0.0
    count_in: int = 0
    count_out: int = 0
    profit: float = 0.0  # sotuvdan foyda


class Reports:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def totals(self, period: Period = Period()) -> Totals:
        where, params = period_filter(period)
        row = self._conn.execute(
            f"""
            SELECT COALESCE(SUM(CASE WHEN {_IS_RECEIPT} THEN amount END), 0) AS amount_in,
                   COALESCE(SUM(CASE WHEN kind = 'OUT' THEN amount END), 0) AS amount_out,
                   COUNT(CASE WHEN {_IS_RECEIPT} THEN 1 END) AS count_in,
                   COUNT(CASE WHEN kind = 'OUT' THEN 1 END) AS count_out
            FROM movement_details WHERE {where}
            """,
            params,
        ).fetchone()
        return Totals(**dict(row))

    def stock_value(self) -> float:
        """Hozir omborda turgan barcha mahsulotning qiymati."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount_in - amount_out), 0) FROM product_stock"
            " WHERE NOT is_service AND qty_in - qty_out > 1e-9"
        ).fetchone()
        return row[0]

    def turnover(self, period: Period = Period()) -> list[ProductTurnover]:
        """Aylanma qaydnoma: boshlang'ich qoldiq, kirim, chiqim (oxirgi qoldiq shulardan chiqadi).

        Davrda harakati ham, boshlang'ich qoldig'i ham bo'lmagan mahsulotlar va xizmatlar kiritilmaydi.
        """
        rows = self._conn.execute(
            """
            SELECT product_name AS name, unit,
                   ROUND(COALESCE(SUM(CASE WHEN date < :start
                       THEN CASE WHEN kind = 'IN' THEN quantity ELSE -quantity END END), 0), 6) AS opening,
                   COALESCE(SUM(CASE WHEN date >= :start AND kind = 'IN' THEN quantity END), 0) AS qty_in,
                   COALESCE(SUM(CASE WHEN date >= :start AND kind = 'IN' THEN amount END), 0) AS amount_in,
                   COALESCE(SUM(CASE WHEN date >= :start AND kind = 'OUT' THEN quantity END), 0) AS qty_out,
                   COALESCE(SUM(CASE WHEN date >= :start AND kind = 'OUT' THEN amount END), 0) AS amount_out
            FROM movement_details WHERE date <= :end AND NOT is_service
            GROUP BY product_id
            HAVING opening <> 0 OR qty_in <> 0 OR qty_out <> 0
            ORDER BY product_name
            """,
            {
                "start": period.start.isoformat() if period.start else EARLIEST_DATE,
                "end": period.end.isoformat() if period.end else LATEST_DATE,
            },
        )
        return [ProductTurnover(**dict(row)) for row in rows]

    def by_group(self, kind: MovementKind, group: GroupBy, period: Period = Period()) -> list[GroupTotal]:
        """Masalan: kim qancha olib keldi yoki qaysi obyektga qancha rasxod bo'ldi."""
        where, params = period_filter(period)
        column = group.value
        rows = self._conn.execute(
            f"""
            SELECT {column} AS name, COUNT(*) AS operations, COALESCE(SUM(amount), 0) AS amount
            FROM movement_details WHERE kind = ? AND NOT (kind = 'IN' AND is_return) AND {where}
            GROUP BY {column} ORDER BY amount DESC, name
            """,
            [kind.value, *params],
        )
        return [
            GroupTotal(display_counterparty(row["name"]) or UNNAMED, row["operations"], row["amount"]) for row in rows
        ]

    def by_category(self, period: Period = Period()) -> list[CategoryTotal]:
        """Kirim va chiqim summalari tovar guruhlari va kategoriyalari kesimida."""
        where, params = period_filter(period)
        rows = self._conn.execute(
            f"""
            SELECT category, subcategory,
                   COALESCE(SUM(CASE WHEN {_IS_RECEIPT} THEN amount END), 0) AS amount_in,
                   COALESCE(SUM(CASE WHEN kind = 'OUT' THEN amount END), 0) AS amount_out
            FROM movement_details WHERE {where}
            GROUP BY category, subcategory ORDER BY category, subcategory
            """,
            params,
        )
        return [CategoryTotal(**dict(row)) for row in rows]

    def by_payment(self, period: Period = Period()) -> list[PaymentTotal]:
        """Xaridlar to'lov turlari kesimida (masalan, KPK bilan qancha, naqd qancha; to'langan va to'lanmagan)."""
        where, params = period_filter(period)
        rows = self._conn.execute(
            f"""
            SELECT payment AS method, COUNT(*) AS operations,
                   COALESCE(SUM(CASE WHEN unpaid OR on_credit THEN 0 ELSE amount END), 0) AS paid,
                   COALESCE(SUM(CASE WHEN unpaid OR on_credit THEN amount ELSE 0 END), 0) AS unpaid
            FROM movement_details WHERE {_IS_RECEIPT} AND {where}
            GROUP BY payment ORDER BY paid + unpaid DESC, payment
            """,
            params,
        )
        return [PaymentTotal(**dict(row)) for row in rows]

    def dynamics(self, period: Period, step: Granularity) -> list[PeriodTotal]:
        """Davrni `step` bo'laklariga (kun, hafta, oy, yil) bo'lib, har biri bo'yicha jami.

        Faqat harakat bo'lgan bo'laklar qaytariladi, eskisidan yangisiga qarab.
        """
        where, params = period_filter(period)
        rows = self._conn.execute(
            f"""
            SELECT {_BUCKET_START[step]} AS start,
                   COALESCE(SUM(CASE WHEN {_IS_RECEIPT} THEN amount END), 0) AS amount_in,
                   COALESCE(SUM(CASE WHEN kind = 'OUT' THEN amount END), 0) AS amount_out,
                   COUNT(CASE WHEN {_IS_RECEIPT} THEN 1 END) AS count_in,
                   COUNT(CASE WHEN kind = 'OUT' THEN 1 END) AS count_out,
                   COALESCE(SUM(profit), 0) AS profit
            FROM movement_details WHERE {where}
            GROUP BY start ORDER BY start
            """,
            params,
        )
        return [PeriodTotal(**{**dict(row), "start": date.fromisoformat(row["start"])}) for row in rows]

    def monthly(self, months: int = 6, today: date | None = None) -> list[PeriodTotal]:
        """Oxirgi `months` oy (joriy oy bilan birga); harakatsiz oylar ham nol bilan kiradi."""
        current = (today or date.today()).replace(day=1)
        recent = [Granularity.MONTH.shift(current, -back) for back in range(months - 1, -1, -1)]
        by_month = {total.start: total for total in self.dynamics(Period(recent[0], None), Granularity.MONTH)}
        return [by_month.get(month, PeriodTotal(month)) for month in recent]
