"""Chiqim tannarxi: sirpanuvchi o'rtacha narx usuli.

Mahsulot yozuvlari sana tartibida ko'rib chiqiladi. Har bir chiqim o'sha
paytdagi qoldiqning o'rtacha narxida baholanadi va bu narx yozuvda saqlanadi,
shuning uchun keyingi kirimlar o'tgan davrlarning rasxod summasini o'zgartirmaydi.
"""

from datetime import date

from .driver import sqlite3
from .errors import WarehouseError
from .formatting import fmt_date, fmt_qty
from .i18n import tr

EPSILON = 1e-9


def recalculate_costs(conn: sqlite3.Connection, product_id: int, strict: bool = True) -> None:
    """Mahsulotning barcha chiqimlari narxini qayta hisoblaydi va har bir ombordagi qoldiqni tekshiradi.

    O'rtacha tannarx barcha omborlar uchun bitta; qoldiq esa har bir omborda alohida yuritiladi,
    ombordan omborga ko'chirish tannarxni o'zgartirmaydi.

    `strict` rejimida biror sanada biror ombordagidan ko'p chiqim yoki ko'chirish uchrasa,
    WarehouseError ko'tariladi (chaqiruvchi tranzaksiyani bekor qiladi). `strict=False` eski
    versiyadan qolgan ma'lumotlar uchun: bunday chiqim o'z joyida qoladi va
    mavjud qoldiq narxida (qoldiq bo'lmasa — nolda) baholanadi.
    """
    if conn.execute("SELECT is_service FROM products WHERE id = ?", (product_id,)).fetchone()[0]:
        return  # xizmatning qoldig'i ham, tannarxi ham yo'q
    # Bir kunda: avval kirimlar, keyin ko'chirishlar, oxirida chiqimlar. O'chirilgan yozuvlar hisobga kirmaydi.
    rows = conn.execute(
        """
        SELECT id, kind, date, quantity, price, warehouse_id AS source, NULL AS target,
               CASE kind WHEN 'IN' THEN 0 ELSE 2 END AS step
        FROM movements WHERE product_id = :product AND deleted_at IS NULL
        UNION ALL
        SELECT id, 'MOVE', date, quantity, 0, from_id, to_id, 1 FROM transfers WHERE product_id = :product
        ORDER BY date, step, id
        """,
        {"product": product_id},
    ).fetchall()

    quantity = value = 0.0
    stocks: dict[int, float] = {}  # ombor id -> qoldiq
    for row in rows:
        source, amount = row["source"], row["quantity"]
        if row["kind"] == "IN":
            quantity += amount
            value += amount * row["price"]
            stocks[source] = stocks.get(source, 0.0) + amount
            continue

        available = stocks.get(source, 0.0)
        if strict and amount > available + EPSILON:
            raise _insufficient_stock(conn, product_id, row["date"], available=available, needed=amount)
        stocks[source] = max(available - amount, 0.0)
        if row["kind"] == "MOVE":
            stocks[row["target"]] = stocks.get(row["target"], 0.0) + min(amount, available)
            continue

        cost = value / quantity if quantity > EPSILON else 0.0
        if cost != row["price"]:
            conn.execute("UPDATE movements SET price = ? WHERE id = ?", (cost, row["id"]))
        quantity = max(quantity - amount, 0.0)
        value = max(value - amount * cost, 0.0) if quantity > EPSILON else 0.0


def warehouse_stocks(conn: sqlite3.Connection, warehouse_id: int) -> dict[int, float]:
    """Bitta ombordagi qoldiqlar: mahsulot id -> miqdor."""
    rows = conn.execute(
        """
        SELECT product_id, SUM(delta) AS stock FROM (
            SELECT product_id, CASE kind WHEN 'IN' THEN quantity ELSE -quantity END AS delta
            FROM movements WHERE deleted_at IS NULL AND warehouse_id = :id
            UNION ALL SELECT product_id, quantity FROM transfers WHERE to_id = :id
            UNION ALL SELECT product_id, -quantity FROM transfers WHERE from_id = :id
        ) GROUP BY product_id
        """,
        {"id": warehouse_id},
    )
    return {row["product_id"]: round(row["stock"], 6) for row in rows}


def _insufficient_stock(
    conn: sqlite3.Connection, product_id: int, day: str, available: float, needed: float
) -> WarehouseError:
    name, unit = conn.execute("SELECT name, unit FROM products WHERE id = ?", (product_id,)).fetchone()
    return WarehouseError(
        tr("«{0}» {1} sanasida omborda yetarli emas: mavjud {2} {3}, kerak {4} {5}.").format(
            name, fmt_date(date.fromisoformat(day)), fmt_qty(max(available, 0)), unit, fmt_qty(needed), unit
        )
    )
