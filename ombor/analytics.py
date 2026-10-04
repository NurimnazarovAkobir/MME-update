"""Foyda va zarar tahlili uchun hisob-kitoblar.

Sotuv — sotuv narxi kiritilgan chiqim. Narxsiz chiqim ichki rasxod hisoblanadi
va foydaga kirmaydi; inventarizatsiya kamomadi alohida zarar sifatida ko'rsatiladi.
Xaridordan qaytgan mahsulot tushum va foydani kamaytiradi; yetkazib beruvchiga
qaytarilgan mahsulot sotuv hisoblanmaydi.
"""

from dataclasses import dataclass

from .database import period_filter
from .driver import sqlite3
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
    expenses: float  # xizmat va xarajatlar (xizmat turidagi mahsulotlarning kirimi)

    @property
    def net_profit(self) -> float:
        """Sof foyda: sotuvdan foyda minus xizmat va xarajatlar."""
        return self.profit - self.expenses

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
            SELECT COALESCE(SUM(revenue), 0) AS revenue,
                   COALESCE(SUM(cost_of_sales), 0) AS cost,
                   COALESCE(SUM(profit), 0) AS profit,
                   COUNT(CASE WHEN kind = 'OUT' AND NOT is_return AND sale_price > 0 THEN 1 END) AS sales_count,
                   COALESCE(SUM(CASE WHEN kind = 'OUT' AND profit < 0 THEN -profit END), 0) AS below_cost_loss,
                   COALESCE(SUM(CASE WHEN kind = 'OUT' AND counterparty = ? THEN amount END), 0) AS shortage,
                   COALESCE(SUM(CASE WHEN kind = 'OUT' AND NOT is_return AND sale_price = 0 AND counterparty <> ?
                       THEN amount END), 0) AS internal_use,
                   COALESCE(SUM(CASE WHEN kind = 'IN' AND is_service THEN amount END), 0) AS expenses
            FROM movement_details WHERE {where}
            """,
            [INVENTORY_SHORTAGE, INVENTORY_SHORTAGE, *params],
        ).fetchone()
        return ProfitSummary(**dict(row))

    def by_product(self, period: Period = Period()) -> list[ProductProfit]:
        """Sotilgan mahsulotlar, eng ko'p foyda keltirganidan boshlab; xaridordan qaytganlari ayirilgan."""
        where, params = period_filter(period)
        rows = self._conn.execute(
            f"""
            SELECT product_name AS name, unit,
                   SUM(CASE WHEN kind = 'OUT' THEN quantity ELSE -quantity END) AS quantity,
                   SUM(revenue) AS revenue, SUM(cost_of_sales) AS cost, SUM(profit) AS profit
            FROM movement_details WHERE revenue <> 0 AND {where}
            GROUP BY product_id ORDER BY profit DESC, product_name
            """,
            params,
        )
        return [ProductProfit(**dict(row)) for row in rows]
