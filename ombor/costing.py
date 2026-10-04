"""Chiqim tannarxi: sirpanuvchi o'rtacha narx usuli.

Mahsulot yozuvlari sana tartibida ko'rib chiqiladi. Har bir chiqim o'sha
paytdagi qoldiqning o'rtacha narxida baholanadi va bu narx yozuvda saqlanadi,
shuning uchun keyingi kirimlar o'tgan davrlarning rasxod summasini o'zgartirmaydi.
"""

import sqlite3
from datetime import date

from .errors import WarehouseError
from .formatting import fmt_date, fmt_qty
from .i18n import tr

EPSILON = 1e-9


def recalculate_costs(conn: sqlite3.Connection, product_id: int, strict: bool = True) -> None:
    """Mahsulotning barcha chiqimlari narxini qayta hisoblaydi.

    `strict` rejimida biror sanada ombordagidan ko'p chiqim uchrasa, WarehouseError
    ko'tariladi (chaqiruvchi tranzaksiyani bekor qiladi). `strict=False` eski
    versiyadan qolgan ma'lumotlar uchun: bunday chiqim o'z joyida qoladi va
    mavjud qoldiq narxida (qoldiq bo'lmasa — nolda) baholanadi.
    """
    # Bir kundagi kirimlar chiqimlardan oldin hisoblanadi ('IN' < 'OUT').
    rows = conn.execute(
        "SELECT id, kind, date, quantity, price FROM movements WHERE product_id = ? ORDER BY date, kind, id",
        (product_id,),
    ).fetchall()

    quantity = value = 0.0
    for row in rows:
        if row["kind"] == "IN":
            quantity += row["quantity"]
            value += row["quantity"] * row["price"]
            continue

        if strict and row["quantity"] > quantity + EPSILON:
            raise _insufficient_stock(conn, product_id, row["date"], available=quantity, needed=row["quantity"])
        cost = value / quantity if quantity > EPSILON else 0.0
        if cost != row["price"]:
            conn.execute("UPDATE movements SET price = ? WHERE id = ?", (cost, row["id"]))
        quantity = max(quantity - row["quantity"], 0.0)
        value = max(value - row["quantity"] * cost, 0.0) if quantity > EPSILON else 0.0


def _insufficient_stock(
    conn: sqlite3.Connection, product_id: int, day: str, available: float, needed: float
) -> WarehouseError:
    name, unit = conn.execute("SELECT name, unit FROM products WHERE id = ?", (product_id,)).fetchone()
    return WarehouseError(
        tr("«{0}» {1} sanasida omborda yetarli emas: mavjud {2} {3}, kerak {4} {5}.").format(
            name, fmt_date(date.fromisoformat(day)), fmt_qty(max(available, 0)), unit, fmt_qty(needed), unit
        )
    )
