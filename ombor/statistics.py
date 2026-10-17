"""Umumiy statistika: eng ko'p kirgan va chiqqan mahsulotlar, oyma-oy narx o'zgarishi, obyektlar rasxodi.

Kirim reytingiga faqat haqiqiy xaridlar kiradi: boshlang'ich qoldiq, inventarizatsiya ortiqchasi va
xaridordan qaytgan mahsulot — xarid emas. Chiqim reytingiga inventarizatsiya kamomadi va yetkazib beruvchiga
qaytarish kirmaydi. Summalar so'mda: turli birlikdagi mahsulotlarni solishtirishning yagona umumiy o'lchovi.
"""

from dataclasses import dataclass
from datetime import date

from .database import period_filter
from .driver import sqlite3
from .models import MovementKind, Period
from .sites import Sites
from .warehouse import INVENTORY_SHORTAGE, INVENTORY_SURPLUS, OPENING_BALANCE

TOP_LIMIT = 10
PRICE_TOLERANCE = 0.005  # bundan kichik farq narx o'zgarishi hisoblanmaydi

_IS_PURCHASE = "kind = 'IN' AND NOT is_return AND counterparty NOT IN (:surplus, :opening)"
_IS_CONSUMPTION = "kind = 'OUT' AND NOT is_return AND counterparty <> :shortage"
_SYSTEM = {"surplus": INVENTORY_SURPLUS, "opening": OPENING_BALANCE, "shortage": INVENTORY_SHORTAGE}


@dataclass(frozen=True)
class ProductRank:
    """Reyting qatori: mahsulot, jami miqdor va summa, nechta yozuv."""

    product_id: int
    name: str
    unit: str
    quantity: float
    amount: float
    operations: int


@dataclass(frozen=True)
class MonthlyPrice:
    """Mahsulotning bir oydagi o'rtacha xarid narxi va undan oldingi xarid oyidagi narxi."""

    product_id: int
    name: str
    unit: str
    month: date  # oyning birinchi kuni
    price: float  # shu oydagi o'rtacha narx (miqdor bo'yicha tortilgan)
    previous_month: date
    previous_price: float

    @property
    def difference(self) -> float:
        return self.price - self.previous_price

    @property
    def percent(self) -> float:
        return self.difference / self.previous_price * 100 if self.previous_price else 0.0


@dataclass(frozen=True)
class SiteExpense:
    name: str
    issued: float
    returned: float

    @property
    def net(self) -> float:
        """Obyektga ketgan sof rasxod: berilgan minus qaytgan (tannarx bo'yicha)."""
        return self.issued - self.returned


@dataclass(frozen=True)
class Overview:
    purchased: float  # davrda sotib olingan mahsulot summasi
    consumed: float  # davrda chiqim (tannarx bo'yicha)
    site_expense: float  # obyektlarga sof rasxod
    products_moved: int  # davrda harakati bo'lgan mahsulotlar soni
    price_rises: int  # narxi oshgan holatlar (mahsulot × oy)
    price_drops: int


class Statistics:
    def __init__(self, conn: sqlite3.Connection, sites: Sites):
        self._conn = conn
        self._sites = sites

    def top_products(self, kind: MovementKind, period: Period, limit: int = TOP_LIMIT) -> list[ProductRank]:
        """Davrda eng ko'p kirgan (`IN`) yoki chiqqan (`OUT`) mahsulotlar — summa bo'yicha kamayish tartibida."""
        where, params = period_filter(period)
        condition = _IS_PURCHASE if kind is MovementKind.IN else _IS_CONSUMPTION
        rows = self._conn.execute(
            f"""
            SELECT product_id, product_name AS name, unit, SUM(quantity) AS quantity,
                   SUM(amount) AS amount, COUNT(*) AS operations
            FROM movement_details
            WHERE {condition} AND NOT is_service AND {_named(where)}
            GROUP BY product_id ORDER BY amount DESC, quantity DESC, name LIMIT :limit
            """,
            {**_SYSTEM, **_named_params(params), "limit": limit},
        )
        return [ProductRank(**dict(row)) for row in rows]

    def price_changes(self, period: Period) -> list[MonthlyPrice]:
        """Davrdagi har bir oyda narxi oldingi xarid oyiga nisbatan o'zgargan mahsulotlar.

        Oldingi oy davrdan tashqarida bo'lishi ham mumkin (masalan, yanvardagi narx o'tgan yilning dekabri bilan
        solishtiriladi). Eng yangi oydan boshlab, oy ichida eng katta o'zgarishdan boshlab.
        """
        end = period.end.isoformat() if period.end else "9999-12-31"
        rows = self._conn.execute(
            f"""
            SELECT product_id, product_name AS name, unit, substr(date, 1, 7) || '-01' AS month,
                   SUM(quantity * price) / SUM(quantity) AS price
            FROM movement_details
            WHERE {_IS_PURCHASE} AND NOT is_service AND price > 0 AND date <= :end
            GROUP BY product_id, month ORDER BY product_id, month
            """,
            {**_SYSTEM, "end": end},
        ).fetchall()
        changes, previous = [], None
        for row in rows:
            month = date.fromisoformat(row["month"])
            same_product = previous is not None and previous["product_id"] == row["product_id"]
            if same_product and (period.start is None or month >= period.start.replace(day=1)):
                change = MonthlyPrice(
                    row["product_id"],
                    row["name"],
                    row["unit"],
                    month,
                    row["price"],
                    date.fromisoformat(previous["month"]),
                    previous["price"],
                )
                if abs(change.difference) > PRICE_TOLERANCE:
                    changes.append(change)
            previous = row
        return sorted(changes, key=lambda change: (-change.month.toordinal(), -abs(change.percent)))

    def site_expenses(self, period: Period) -> list[SiteExpense]:
        """Obyektlarga ketgan rasxod, eng kattasidan boshlab (harakati bo'lmagan obyektlarsiz)."""
        found = [
            SiteExpense(s.name, s.issued, s.returned) for s in self._sites.all(period=period) if s.issued or s.returned
        ]
        return sorted(found, key=lambda site: (-site.net, site.name.casefold()))

    def overview(self, period: Period) -> Overview:
        where, params = period_filter(period)
        row = self._conn.execute(
            f"""
            SELECT COALESCE(SUM(CASE WHEN {_IS_PURCHASE} THEN amount END), 0) AS purchased,
                   COALESCE(SUM(CASE WHEN {_IS_CONSUMPTION} THEN amount END), 0) AS consumed,
                   COUNT(DISTINCT CASE WHEN NOT is_service THEN product_id END) AS products_moved
            FROM movement_details WHERE {_named(where)}
            """,
            {**_SYSTEM, **_named_params(params)},
        ).fetchone()
        prices = self.price_changes(period)
        return Overview(
            purchased=row["purchased"],
            consumed=row["consumed"],
            site_expense=sum(site.net for site in self.site_expenses(period)),
            products_moved=row["products_moved"],
            price_rises=sum(change.difference > 0 for change in prices),
            price_drops=sum(change.difference < 0 for change in prices),
        )


def _named(where: str) -> str:
    """`period_filter` ning «?» o'rinbosarlarini nomlilariga almashtiradi (boshqa nomli parametrlar bilan birga)."""
    parts = where.split("?")
    return "".join(part + (f":p{index}" if index < len(parts) - 1 else "") for index, part in enumerate(parts))


def _named_params(params: list[str]) -> dict[str, str]:
    return {f"p{index}": value for index, value in enumerate(params)}
