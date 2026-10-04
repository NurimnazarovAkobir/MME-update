"""Omborning asosiy amallari: mahsulotlar, kirim va chiqim."""

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from .catalog import display_name
from .costing import recalculate_costs
from .database import period_filter
from .errors import WarehouseError
from .formatting import fmt_qty
from .i18n import tr
from .models import ImportedProduct, Movement, MovementDetails, MovementKind, Period, Product, ProductStock

SUGGESTION_FIELDS = ("person", "counterparty")

# Dastur o'zi yaratadigan yozuvlarning «yetkazib beruvchi / obyekt» maydoni.
INVENTORY_SURPLUS = "Inventarizatsiya (ortiqcha)"
INVENTORY_SHORTAGE = "Inventarizatsiya (kamomad)"
OPENING_BALANCE = tr("Boshlang'ich qoldiq")


@dataclass(frozen=True)
class ImportResult:
    added: int
    skipped: list[str]  # bazada allaqachon bor bo'lgan nomlar


def _matches(search: str, *fields: str) -> bool:
    """Qidiruv matni maydonlardan birida uchraydimi (katta-kichik harf farqsiz, kirillcha ham)."""
    needle = search.strip().casefold()
    return not needle or any(needle in field.casefold() for field in fields)


def _to_product(row: sqlite3.Row) -> ProductStock:
    return ProductStock(**dict(row))


def _to_movement(row: sqlite3.Row) -> MovementDetails:
    values = dict(row)
    values["kind"] = MovementKind(values["kind"])
    values["date"] = date.fromisoformat(values["date"])
    return MovementDetails(**values)


class Warehouse:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # --- Mahsulotlar -------------------------------------------------------

    def products(self, search: str = "") -> list[ProductStock]:
        rows = self._conn.execute("SELECT * FROM product_stock ORDER BY name")
        return [p for p in map(_to_product, rows) if _matches(search, p.name, p.note)]

    def product(self, product_id: int) -> ProductStock:
        row = self._conn.execute("SELECT * FROM product_stock WHERE id = ?", (product_id,)).fetchone()
        if row is None:
            raise WarehouseError(tr("Mahsulot topilmadi."))
        return _to_product(row)

    def save_product(self, product: Product) -> int:
        """Yangi mahsulot qo'shadi yoki mavjudini yangilaydi; mahsulot id sini qaytaradi."""
        name = product.name.strip()
        if not name:
            raise WarehouseError(tr("Mahsulot nomini kiriting."))
        if not product.unit.strip():
            raise WarehouseError(tr("O'lchov birligini tanlang."))
        if product.min_stock < 0:
            raise WarehouseError(tr("Minimal qoldiq manfiy bo'lishi mumkin emas."))

        values = (
            name,
            product.unit.strip(),
            product.min_stock,
            product.note.strip(),
        )
        try:
            with self._conn:
                if product.id is None:
                    cursor = self._conn.execute(
                        "INSERT INTO products (name, unit, min_stock, note) VALUES (?, ?, ?, ?)",
                        values,
                    )
                    return cursor.lastrowid
                self._conn.execute(
                    "UPDATE products SET name = ?, unit = ?, min_stock = ?, note = ? WHERE id = ?",
                    (*values, product.id),
                )
                return product.id
        except sqlite3.IntegrityError as error:
            raise WarehouseError(tr("«{0}» nomli mahsulot allaqachon bor.").format(name)) from error

    def delete_product(self, product_id: int) -> None:
        try:
            with self._conn:
                self._conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        except sqlite3.IntegrityError as error:
            raise WarehouseError(
                tr("Bu mahsulot bo'yicha kirim yoki chiqim yozuvlari bor. Avval o'sha yozuvlarni o'chiring.")
            ) from error

    # --- Kirim va chiqim ---------------------------------------------------

    def movements(
        self,
        kind: MovementKind | None = None,
        period: Period = Period(),
        search: str = "",
        limit: int | None = None,
    ) -> list[MovementDetails]:
        """Yozuvlarni eng yangisidan boshlab qaytaradi; `kind` berilmasa — kirim ham, chiqim ham."""
        where, params = period_filter(period)
        if kind is not None:
            where += " AND kind = ?"
            params.append(kind.value)
        rows = self._conn.execute(f"SELECT * FROM movement_details WHERE {where} ORDER BY date DESC, id DESC", params)
        found = [
            m
            for m in map(_to_movement, rows)
            if _matches(
                search,
                m.product_name,
                m.person,
                m.counterparty,
                m.note,
                m.category,
                m.subcategory,
                display_name(m.category),
                display_name(m.subcategory),
            )
        ]
        return found[:limit] if limit else found

    def movement(self, movement_id: int) -> MovementDetails:
        row = self._conn.execute("SELECT * FROM movement_details WHERE id = ?", (movement_id,)).fetchone()
        if row is None:
            raise WarehouseError(tr("Yozuv topilmadi."))
        return _to_movement(row)

    def save_movement(self, movement: Movement) -> int:
        """Kirim/chiqimni qo'shadi yoki yangilaydi.

        Biror sanada ombordagidan ko'p chiqim hosil bo'lsa, rad etadi. Chiqim narxi
        kiritilmaydi — tannarx sifatida hisoblanadi (costing.py); `movement.price`
        faqat kirimda, `movement.sale_price` faqat chiqimda ishlatiladi.
        """
        if movement.quantity <= 0:
            raise WarehouseError(tr("Miqdor noldan katta bo'lishi kerak."))
        if movement.price < 0 or movement.sale_price < 0:
            raise WarehouseError(tr("Narx manfiy bo'lishi mumkin emas."))

        values = (
            movement.kind.value,
            movement.date.isoformat(),
            movement.product_id,
            movement.quantity,
            movement.price if movement.kind is MovementKind.IN else 0,
            movement.sale_price if movement.kind is MovementKind.OUT else 0,
            movement.category.strip(),
            movement.subcategory.strip(),
            movement.person.strip(),
            movement.counterparty.strip(),
            movement.note.strip(),
        )
        with self._conn:
            affected_products = {movement.product_id}
            if movement.id is None:
                cursor = self._conn.execute(
                    "INSERT INTO movements (kind, date, product_id, quantity, price, sale_price,"
                    " category, subcategory, person, counterparty, note, created_by)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (*values, movement.created_by),
                )
                movement_id = cursor.lastrowid
            else:
                affected_products.add(self.movement(movement.id).product_id)
                self._conn.execute(
                    "UPDATE movements SET kind = ?, date = ?, product_id = ?, quantity = ?, price = ?, sale_price = ?,"
                    " category = ?, subcategory = ?, person = ?, counterparty = ?, note = ? WHERE id = ?",
                    (*values, movement.id),
                )
                movement_id = movement.id
            self._recalculate(affected_products)
        return movement_id

    def delete_movement(self, movement_id: int) -> None:
        with self._conn:
            product_id = self.movement(movement_id).product_id
            self._conn.execute("DELETE FROM movements WHERE id = ?", (movement_id,))
            self._recalculate({product_id})

    def adjust_stock(self, product_id: int, actual: float, day: date, author: str, note: str = "") -> int | None:
        """Inventarizatsiya: hisobdagi qoldiqni sanalgan (`actual`) qoldiqqa tenglashtiradi.

        Farq ortiqcha bo'lsa kirim, kamomad bo'lsa chiqim yozuvi yaratiladi va uning
        id si qaytadi; farq bo'lmasa — None.
        """
        if actual < 0:
            raise WarehouseError(tr("Haqiqiy qoldiq manfiy bo'lishi mumkin emas."))
        product = self.product(product_id)
        difference = round(actual - product.stock, 6)
        if not difference:
            return None
        is_surplus = difference > 0
        details = tr("hisobda {0}, haqiqatda {1} {2}").format(fmt_qty(product.stock), fmt_qty(actual), product.unit)
        return self.save_movement(
            Movement(
                kind=MovementKind.IN if is_surplus else MovementKind.OUT,
                date=day,
                product_id=product_id,
                quantity=abs(difference),
                price=product.average_price,
                counterparty=INVENTORY_SURPLUS if is_surplus else INVENTORY_SHORTAGE,
                note=f"{note.strip()} ({details})" if note.strip() else details,
                created_by=author,
            )
        )

    def import_products(self, rows: Iterable[ImportedProduct], day: date, author: str) -> ImportResult:
        """Excel dan o'qilgan mahsulotlarni qo'shadi.

        Bazada bor yoki faylda takrorlangan nomlar o'tkazib yuboriladi. Qoldig'i
        ko'rsatilgan mahsulotga `day` sanasi bilan boshlang'ich kirim yoziladi.
        """
        existing = {product.name.casefold() for product in self.products()}
        added, skipped = 0, []
        for row in rows:
            key = row.name.strip().casefold()
            if key in existing:
                skipped.append(row.name)
                continue
            product_id = self.save_product(Product(row.name, row.unit, row.min_stock))
            existing.add(key)
            added += 1
            if row.stock > 0:
                self.save_movement(
                    Movement(
                        MovementKind.IN,
                        day,
                        product_id,
                        row.stock,
                        row.price,
                        counterparty=OPENING_BALANCE,
                        created_by=author,
                    )
                )
        return ImportResult(added, skipped)

    def last_group(self, product_id: int) -> tuple[str, str]:
        """Mahsulotning eng oxirgi yozuvidagi guruh va kichik guruh — yangi yozuvda qayta tanlamaslik uchun."""
        row = self._conn.execute(
            "SELECT category, subcategory FROM movements WHERE product_id = ? AND category <> ''"
            " ORDER BY id DESC LIMIT 1",
            (product_id,),
        ).fetchone()
        return (row["category"], row["subcategory"]) if row else ("", "")

    def suggestions(self, kind: MovementKind, field: str) -> list[str]:
        """Avval kiritilgan ismlar/obyektlar — qayta yozmaslik uchun."""
        if field not in SUGGESTION_FIELDS:
            raise ValueError(f"Noma'lum maydon: {field}")
        rows = self._conn.execute(
            f"SELECT DISTINCT {field} FROM movements WHERE kind = ? AND {field} <> '' ORDER BY {field}",
            (kind.value,),
        )
        return [row[0] for row in rows]

    def _recalculate(self, product_ids: set[int]) -> None:
        """Tranzaksiya ichida chaqiriladi: qoldiq yetmasa xato ko'tariladi va o'zgarishlar bekor bo'ladi."""
        for product_id in product_ids:
            recalculate_costs(self._conn, product_id)
