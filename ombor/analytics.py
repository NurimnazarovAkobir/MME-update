"""Foyda va zarar tahlili uchun hisob-kitoblar.

Sotuv — sotuv narxi kiritilgan chiqim. Narxsiz chiqim ichki rasxod hisoblanadi
va foydaga kirmaydi; inventarizatsiya kamomadi alohida zarar sifatida ko'rsatiladi.
"""

import sqlite3
from dataclasses import dataclass

from .database import period_filter
from .models import Period
from .warehouse import INVENTORY_SHORTAGE


@dataclass(frozen=True)
class ProfitSummary:
    revenue: float  # sotuv tushumi
    cost: float  # sotilgan mahsulot tannarxi
    profit: float
    sales_count: int
    below_cost_loss: float  # tannarxdan past sotilgan yozuvlardagi zarar
    shortage: float  # inventarizatsiya kamomadi
    internal_use: float  # sotuv narxisiz chiqimlar tannarxi

    @property
    def margin(self) -> float:
        """Rentabellik: tushumning qancha qismi foyda (0…1)."""
        return self.profit / self.revenue if self.revenue else 0.0


@dataclass(frozen=True)
class ProductProfit:
    name: str
    unit: str
    quantity: float
    revenue: float
    cost: float
    profit: float

    @property
    def margin(self) -> float:
        return self.profit / self.revenue if self.revenue else 0.0


class Analytics:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def summary(self, period: Period = Period()) -> ProfitSummary:
        where, params = period_filter(period)
        row = self._conn.execute(
            f"""
            SELECT COALESCE(SUM(CASE WHEN sale_price > 0 THEN revenue END), 0) AS revenue,
                   COALESCE(SUM(CASE WHEN sale_price > 0 THEN amount END), 0) AS cost,
                   COALESCE(SUM(profit), 0) AS profit,
                   COUNT(CASE WHEN sale_price > 0 THEN 1 END) AS sales_count,
                   COALESCE(SUM(CASE WHEN profit < 0 THEN -profit END), 0) AS below_cost_loss,
                   COALESCE(SUM(CASE WHEN counterparty = ? THEN amount END), 0) AS shortage,
                   COALESCE(SUM(CASE WHEN sale_price = 0 AND counterparty <> ? THEN amount END), 0) AS internal_use
            FROM movement_details WHERE kind = 'OUT' AND {where}
            """,
            [INVENTORY_SHORTAGE, INVENTORY_SHORTAGE, *params],
        ).fetchone()
        return ProfitSummary(**dict(row))

    def by_product(self, period: Period = Period()) -> list[ProductProfit]:
        """Sotilgan mahsulotlar, eng ko'p foyda keltirganidan boshlab."""
        where, params = period_filter(period)
        rows = self._conn.execute(
            f"""
            SELECT product_name AS name, unit, SUM(quantity) AS quantity,
                   SUM(revenue) AS revenue, SUM(amount) AS cost, SUM(profit) AS profit
            FROM movement_details WHERE kind = 'OUT' AND sale_price > 0 AND {where}
            GROUP BY product_id ORDER BY profit DESC, product_name
            """,
            params,
        )
        return [ProductProfit(**dict(row)) for row in rows]
