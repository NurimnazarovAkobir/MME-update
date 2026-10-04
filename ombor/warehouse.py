"""Omborning asosiy amallari: mahsulotlar, kirim va chiqim, o'zgarishlar tarixi."""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Iterable

from .catalog import display_name
from .config import CURRENCY
from .costing import recalculate_costs
from .database import period_filter
from .errors import WarehouseError
from .formatting import fmt_date, fmt_money, fmt_qty
from .i18n import tr
from .models import (
    HistoryAction,
    HistoryEntry,
    ImportedProduct,
    Movement,
    MovementDetails,
    MovementKind,
    Period,
    Product,
    ProductStock,
)
from .settings import Settings

SUGGESTION_FIELDS = ("person", "counterparty")
GROUP_REQUIRED_KEY = "group_required"
PRODUCT_ENTITY = "product"

# Dastur o'zi yaratadigan yozuvlarning «yetkazib beruvchi / obyekt» maydoni. Bazada shu
# (o'zbekcha) ko'rinishda saqlanadi, ekranda esa tanlangan tilda ko'rsatiladi.
INVENTORY_SURPLUS = "Inventarizatsiya (ortiqcha)"
INVENTORY_SHORTAGE = "Inventarizatsiya (kamomad)"
OPENING_BALANCE = "Boshlang'ich qoldiq"
_SYSTEM_COUNTERPARTIES = {
    INVENTORY_SURPLUS: tr("Inventarizatsiya (ortiqcha)"),
    INVENTORY_SHORTAGE: tr("Inventarizatsiya (kamomad)"),
    OPENING_BALANCE: tr("Boshlang'ich qoldiq"),
}


def display_counterparty(value: str) -> str:
    """Dastur o'zi yozgan belgilar tanlangan tilda, qo'lda kiritilganlari — o'z holicha."""
    return _SYSTEM_COUNTERPARTIES.get(value, value)


@dataclass(frozen=True)
class ImportResult:
    added: int
    skipped: list[str]  # bazada allaqachon bor bo'lgan nomlar


def _matches(search: str, *fields: str) -> bool:
    """Qidiruv matni maydonlardan birida uchraydimi (katta-kichik harf farqsiz, kirillcha ham)."""
    needle = search.strip().casefold()
    return not needle or any(needle in field.casefold() for field in fields)


def _to_product(row: sqlite3.Row) -> ProductStock:
    values = dict(row)
    values["is_service"] = bool(values["is_service"])
    return ProductStock(**values)


def _to_movement(row: sqlite3.Row) -> MovementDetails:
    values = dict(row)
    values["kind"] = MovementKind(values["kind"])
    values["date"] = date.fromisoformat(values["date"])
    values["is_service"] = bool(values["is_service"])
    return MovementDetails(**values)


def _describe_movement(movement: MovementDetails) -> str:
    """Tarixga yoziladigan qisqa ta'rif: sana, mahsulot, miqdor, narx va kimdan/kimga."""
    m = movement
    price = m.price if m.kind is MovementKind.IN else m.sale_price
    parts = (
        fmt_date(m.date),
        m.product_name,
        f"{fmt_qty(m.quantity)} {m.unit}",
        f"{fmt_money(price)} {CURRENCY}" if price else "",
        f"№ {m.doc_number}" if m.doc_number else "",
        m.person,
        display_counterparty(m.counterparty),
    )
    return " · ".join(part for part in parts if part)


def _describe_product(product: Product) -> str:
    return " · ".join(part for part in (product.name, product.unit, tr("Xizmat") if product.is_service else "") if part)


class Warehouse:
    def __init__(self, conn: sqlite3.Connection, today: Callable[[], date] = date.today):
        self._conn = conn
        self._today = today
        self._settings = Settings(conn)
        self.actor = ""  # o'zgarishlar tarixiga yoziladigan foydalanuvchi; dasturga kirilgach o'rnatiladi

    # --- Mahsulotlar -------------------------------------------------------

    def products(self, search: str = "") -> list[ProductStock]:
        rows = self._conn.execute("SELECT * FROM product_stock ORDER BY name")
        return [p for p in map(_to_product, rows) if _matches(search, p.name, p.note)]

    def product(self, product_id: int) -> ProductStock:
        row = self._conn.execute("SELECT * FROM product_stock WHERE id = ?", (product_id,)).fetchone()
        if row is None:
            raise WarehouseError(tr("Mahsulot topilmadi."))
        return _to_product(row)

    def attention_count(self) -> int:
        """Kam qolgan yoki tugagan mahsulotlar soni."""
        return sum(product.needs_attention for product in self.products())

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
            0 if product.is_service else product.min_stock,
            product.note.strip(),
            int(product.is_service),
        )
        saved = Product(name, product.unit.strip(), is_service=product.is_service)
        try:
            with self._conn:
                if product.id is None:
                    cursor = self._conn.execute(
                        "INSERT INTO products (name, unit, min_stock, note, is_service) VALUES (?, ?, ?, ?, ?)",
                        values,
                    )
                    self._log(HistoryAction.ADD, PRODUCT_ENTITY, cursor.lastrowid, _describe_product(saved))
                    return cursor.lastrowid
                previous = self.product(product.id)
                if previous.is_service != product.is_service and self._has_movements(product.id):
                    raise WarehouseError(
                        tr("Bu mahsulot bo'yicha yozuvlar bor, shuning uchun uning turini o'zgartirib bo'lmaydi.")
                    )
                self._conn.execute(
                    "UPDATE products SET name = ?, unit = ?, min_stock = ?, note = ?, is_service = ? WHERE id = ?",
                    (*values, product.id),
                )
                self._log(
                    HistoryAction.EDIT,
                    PRODUCT_ENTITY,
                    product.id,
                    _describe_product(saved),
                    _describe_product(previous),
                )
                return product.id
        except sqlite3.IntegrityError as error:
            raise WarehouseError(tr("«{0}» nomli mahsulot allaqachon bor.").format(name)) from error

    def delete_product(self, product_id: int) -> None:
        """Mahsulotni o'chiradi; uning avval o'chirilgan (tiklanmagan) yozuvlari ham butunlay yo'qoladi."""
        try:
            with self._conn:
                product = self.product(product_id)
                self._conn.execute(
                    "DELETE FROM movements WHERE product_id = ? AND deleted_at IS NOT NULL", (product_id,)
                )
                self._conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
                self._log(HistoryAction.DELETE, PRODUCT_ENTITY, product_id, _describe_product(product))
        except sqlite3.IntegrityError as error:
            raise WarehouseError(
                tr("Bu mahsulot bo'yicha kirim yoki chiqim yozuvlari bor. Avval o'sha yozuvlarni o'chiring.")
            ) from error

    # --- Kirim va chiqim ---------------------------------------------------

    @property
    def group_required(self) -> bool:
        """Kirim va chiqimda guruh tanlash majburiymi (sozlamalarda yoqiladi)."""
        return self._settings.get(GROUP_REQUIRED_KEY) == "1"

    @group_required.setter
    def group_required(self, required: bool) -> None:
        self._settings.set(GROUP_REQUIRED_KEY, "1" if required else "")

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
                m.doc_number,
                m.person,
                m.counterparty,
                display_counterparty(m.counterparty),
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

    def document(self, movement_id: int) -> list[MovementDetails]:
        """Yozuv bilan bir hujjatga kiruvchi barcha yozuvlar: turi, sanasi va hujjat raqami bir xil bo'lganlar.

        Hujjat raqami yozilmagan bo'lsa — faqat shu yozuvning o'zi.
        """
        movement = self.movement(movement_id)
        if not movement.doc_number:
            return [movement]
        rows = self._conn.execute(
            "SELECT * FROM movement_details WHERE kind = ? AND date = ? AND doc_number = ? ORDER BY id",
            (movement.kind.value, movement.date.isoformat(), movement.doc_number),
        )
        return [_to_movement(row) for row in rows]

    def save_movement(self, movement: Movement) -> int:
        """Kirim/chiqimni qo'shadi yoki yangilaydi.

        Biror sanada ombordagidan ko'p chiqim hosil bo'lsa, rad etadi. Chiqim narxi
        kiritilmaydi — tannarx sifatida hisoblanadi (costing.py); `movement.price`
        faqat kirimda, `movement.sale_price` faqat chiqimda ishlatiladi.
        """
        if self.group_required and not movement.category.strip():
            raise WarehouseError(tr("Guruhni tanlang."))
        return self._store(movement)

    def delete_movement(self, movement_id: int) -> None:
        """Yozuvni hisobdan chiqaradi; u «O'chirilgan yozuvlar»da qoladi va tiklanishi mumkin."""
        with self._conn:
            movement = self.movement(movement_id)
            self._conn.execute(
                "UPDATE movements SET deleted_at = ?, deleted_by = ? WHERE id = ?",
                (datetime.now().isoformat(sep=" ", timespec="seconds"), self.actor, movement_id),
            )
            self._recalculate({movement.product_id})
            self._log(HistoryAction.DELETE, movement.kind.value, movement_id, _describe_movement(movement))

    def deleted_movements(self) -> list[MovementDetails]:
        """O'chirilgan yozuvlar, eng oxirgi o'chirilganidan boshlab."""
        rows = self._conn.execute("SELECT * FROM deleted_movements ORDER BY deleted_at DESC, id DESC")
        return [_to_movement(row) for row in rows]

    def restore_movement(self, movement_id: int) -> None:
        """O'chirilgan yozuvni qaytaradi; natijada biror sanada qoldiq yetmay qolsa, rad etadi."""
        with self._conn:
            row = self._conn.execute("SELECT * FROM deleted_movements WHERE id = ?", (movement_id,)).fetchone()
            if row is None:
                raise WarehouseError(tr("Yozuv topilmadi."))
            movement = _to_movement(row)
            self._conn.execute("UPDATE movements SET deleted_at = NULL, deleted_by = '' WHERE id = ?", (movement_id,))
            self._recalculate({movement.product_id})
            self._log(HistoryAction.RESTORE, movement.kind.value, movement_id, _describe_movement(movement))

    def adjust_stock(self, product_id: int, actual: float, day: date, author: str, note: str = "") -> int | None:
        """Inventarizatsiya: hisobdagi qoldiqni sanalgan (`actual`) qoldiqqa tenglashtiradi.

        Farq ortiqcha bo'lsa kirim, kamomad bo'lsa chiqim yozuvi yaratiladi va uning
        id si qaytadi; farq bo'lmasa — None.
        """
        if actual < 0:
            raise WarehouseError(tr("Haqiqiy qoldiq manfiy bo'lishi mumkin emas."))
        product = self.product(product_id)
        if product.is_service:
            raise WarehouseError(tr("Xizmatning qoldig'i yuritilmaydi."))
        difference = round(actual - product.stock, 6)
        if not difference:
            return None
        is_surplus = difference > 0
        details = tr("hisobda {0}, haqiqatda {1} {2}").format(fmt_qty(product.stock), fmt_qty(actual), product.unit)
        return self._store(
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

    def take_inventory(self, counted: dict[int, float], day: date, author: str, note: str = "") -> int:
        """Inventarizatsiya varag'i: `counted` — mahsulot id -> sanalgan qoldiq. Tuzatilgan mahsulotlar sonini qaytaradi."""
        adjusted = [self.adjust_stock(product_id, actual, day, author, note) for product_id, actual in counted.items()]
        return sum(movement_id is not None for movement_id in adjusted)

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
                self._store(
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
            "SELECT category, subcategory FROM movements"
            " WHERE product_id = ? AND category <> '' AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
            (product_id,),
        ).fetchone()
        return (row["category"], row["subcategory"]) if row else ("", "")

    def suggestions(self, kind: MovementKind, field: str) -> list[str]:
        """Avval kiritilgan ismlar/obyektlar — qayta yozmaslik uchun (dastur o'zi yozgan belgilarsiz)."""
        if field not in SUGGESTION_FIELDS:
            raise ValueError(f"Noma'lum maydon: {field}")
        rows = self._conn.execute(
            f"SELECT DISTINCT {field} FROM movements"
            f" WHERE kind = ? AND {field} <> '' AND deleted_at IS NULL ORDER BY {field}",
            (kind.value,),
        )
        return [row[0] for row in rows if row[0] not in _SYSTEM_COUNTERPARTIES]

    # --- O'zgarishlar tarixi -----------------------------------------------

    def history(self, period: Period = Period(), search: str = "", limit: int | None = None) -> list[HistoryEntry]:
        """Kim, qachon, nimani o'zgartirgani — eng yangisidan boshlab."""
        where, params = period_filter(period, "substr(at, 1, 10)")
        rows = self._conn.execute(f"SELECT * FROM history WHERE {where} ORDER BY id DESC", params)
        found = [
            entry
            for entry in (
                HistoryEntry(
                    **{**dict(row), "at": datetime.fromisoformat(row["at"]), "action": HistoryAction(row["action"])}
                )
                for row in rows
            )
            if _matches(search, entry.actor, entry.summary, entry.previous)
        ]
        return found[:limit] if limit else found

    # --- Ichki yordamchilar ------------------------------------------------

    def _store(self, movement: Movement) -> int:
        """Yozuvni tekshiradi va saqlaydi; dastur o'zi yaratadigan yozuvlar ham shu yerdan o'tadi."""
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
            movement.doc_number.strip(),
        )
        with self._conn:
            previous = self.movement(movement.id) if movement.id is not None else None
            # Eski yozuvning sanasi o'zgarmasa, uni tahrirlashga to'sqinlik qilinmaydi.
            if movement.date > self._today() and (previous is None or previous.date != movement.date):
                raise WarehouseError(tr("Sana bugundan keyin bo'lishi mumkin emas."))
            affected_products = {movement.product_id}
            if previous is None:
                cursor = self._conn.execute(
                    "INSERT INTO movements (kind, date, product_id, quantity, price, sale_price,"
                    " category, subcategory, person, counterparty, note, doc_number, created_by)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (*values, movement.created_by),
                )
                movement_id = cursor.lastrowid
            else:
                affected_products.add(previous.product_id)
                self._conn.execute(
                    "UPDATE movements SET kind = ?, date = ?, product_id = ?, quantity = ?, price = ?, sale_price = ?,"
                    " category = ?, subcategory = ?, person = ?, counterparty = ?, note = ?, doc_number = ?"
                    " WHERE id = ?",
                    (*values, movement.id),
                )
                movement_id = movement.id
            self._recalculate(affected_products)
            self._log(
                HistoryAction.ADD if previous is None else HistoryAction.EDIT,
                movement.kind.value,
                movement_id,
                _describe_movement(self.movement(movement_id)),
                _describe_movement(previous) if previous else "",
            )
        return movement_id

    def _has_movements(self, product_id: int) -> bool:
        row = self._conn.execute("SELECT 1 FROM movements WHERE product_id = ? LIMIT 1", (product_id,)).fetchone()
        return row is not None

    def _log(self, action: HistoryAction, entity: str, entity_id: int | None, summary: str, previous: str = "") -> None:
        """Tranzaksiya ichida chaqiriladi: amal bekor bo'lsa, tarixdagi qator ham yozilmaydi."""
        self._conn.execute(
            "INSERT INTO history (actor, action, entity, entity_id, summary, previous) VALUES (?, ?, ?, ?, ?, ?)",
            (self.actor, action.value, entity, entity_id, summary, previous),
        )

    def _recalculate(self, product_ids: set[int]) -> None:
        """Tranzaksiya ichida chaqiriladi: qoldiq yetmasa xato ko'tariladi va o'zgarishlar bekor bo'ladi."""
        for product_id in product_ids:
            recalculate_costs(self._conn, product_id)
