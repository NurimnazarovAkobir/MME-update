"""Omborning asosiy amallari: mahsulotlar, kirim va chiqim, o'zgarishlar tarixi."""

from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Callable, Iterable, Sequence

from .catalog import display_name
from .config import CURRENCY
from .costing import recalculate_costs, warehouse_stocks
from .database import MAIN_WAREHOUSE_ID, MAIN_WAREHOUSE_NAME, period_filter
from .driver import sqlite3
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
    PurchaseLine,
    Store,
    Transfer,
)
from .settings import Settings

SUGGESTION_FIELDS = ("person", "counterparty")
# Raqamsiz kiritilgan hujjatga dastur o'zi raqam beradi: K-1, K-2… (kirim), CH-1, CH-2… (chiqim).
DOC_NUMBER_PREFIXES = {MovementKind.IN: "K-", MovementKind.OUT: "CH-"}
PURCHASE_TARGET = 2  # xarid ro'yxati: qoldiq minimal qoldiqning shuncha barobarigacha to'ldiriladi
GROUP_REQUIRED_KEY = "group_required"
PRODUCT_ENTITY = "product"
TRANSFER_ENTITY = "transfer"
HISTORY_ENTITY = "history"

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
    for flag in ("is_service", "is_return", "on_credit"):
        values[flag] = bool(values[flag])
    return MovementDetails(**values)


def store_name(name: str) -> str:
    """Ombor nomi; dastur o'zi yaratgan «Asosiy ombor» tanlangan tilda ko'rsatiladi."""
    return tr("Asosiy ombor") if name == MAIN_WAREHOUSE_NAME else name


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
        tr("Qaytarish") if m.is_return else "",
        tr("Qarzga") if m.on_credit else "",
        m.person,
        display_counterparty(m.counterparty),
    )
    return " · ".join(part for part in parts if part)


def _describe_product(product: Product) -> str:
    parts = (
        product.name,
        product.unit,
        tr("Xizmat") if product.is_service else "",
        " / ".join(display_name(name) for name in (product.category, product.subcategory) if name),
    )
    return " · ".join(part for part in parts if part)


class Warehouse:
    def __init__(self, conn: sqlite3.Connection, today: Callable[[], date] = date.today):
        self._conn = conn
        self._today = today
        self._settings = Settings(conn)
        self.actor = ""  # o'zgarishlar tarixiga yoziladigan foydalanuvchi; dasturga kirilgach o'rnatiladi
        self.actor_role = ""  # uning lavozimi (Role qiymati)

    # --- Mahsulotlar -------------------------------------------------------

    def products(
        self, search: str = "", warehouse_id: int | None = None, category: str = "", subcategory: str = ""
    ) -> list[ProductStock]:
        """Mahsulotlar; `warehouse_id` berilsa, qoldiq faqat shu ombor bo'yicha ko'rsatiladi.

        `category` / `subcategory` berilsa — faqat shu guruh (va uning shu kategoriyasi) mahsulotlari.
        """
        rows = self._conn.execute("SELECT * FROM product_stock ORDER BY name")
        found = [
            p
            for p in map(_to_product, rows)
            if (not category or p.category == category)
            and (not subcategory or p.subcategory == subcategory)
            and _matches(search, p.name, p.note, p.barcode, display_name(p.category), display_name(p.subcategory))
        ]
        if warehouse_id is not None:
            stocks = warehouse_stocks(self._conn, warehouse_id)
            for product in found:
                product.local_stock = stocks.get(product.id, 0.0)
        return found

    def product(self, product_id: int, warehouse_id: int | None = None) -> ProductStock:
        row = self._conn.execute("SELECT * FROM product_stock WHERE id = ?", (product_id,)).fetchone()
        if row is None:
            raise WarehouseError(tr("Mahsulot topilmadi."))
        product = _to_product(row)
        if warehouse_id is not None:
            product.local_stock = warehouse_stocks(self._conn, warehouse_id).get(product_id, 0.0)
        return product

    def product_by_barcode(self, barcode: str) -> ProductStock | None:
        """Shtrix-kod bo'yicha mahsulot (skaner o'qigan kod); topilmasa — None."""
        code = barcode.strip()
        row = self._conn.execute("SELECT * FROM product_stock WHERE barcode = ?", (code,)).fetchone() if code else None
        return _to_product(row) if row else None

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
        barcode, alt_unit = product.barcode.strip(), product.alt_unit.strip()
        if alt_unit and product.alt_factor <= 0:
            raise WarehouseError(tr("Qo'shimcha birlik necha asosiy birlikka tengligini kiriting."))
        if alt_unit.casefold() == product.unit.strip().casefold():
            alt_unit = ""
        owner = self.product_by_barcode(barcode)
        if owner is not None and owner.id != product.id:
            raise WarehouseError(tr("Bu shtrix-kod «{0}» mahsulotiga berilgan.").format(owner.name))

        values = (
            name,
            product.unit.strip(),
            0 if product.is_service else product.min_stock,
            product.note.strip(),
            int(product.is_service),
            barcode,
            alt_unit,
            product.alt_factor if alt_unit else 0,
            product.category.strip(),
            product.subcategory.strip() if product.category.strip() else "",
        )
        saved = replace(product, name=name, unit=product.unit.strip())
        try:
            with self._conn:
                if product.id is None:
                    cursor = self._conn.execute(
                        "INSERT INTO products (name, unit, min_stock, note, is_service, barcode, alt_unit, alt_factor,"
                        " category, subcategory) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    "UPDATE products SET name = ?, unit = ?, min_stock = ?, note = ?, is_service = ?,"
                    " barcode = ?, alt_unit = ?, alt_factor = ?, category = ?, subcategory = ? WHERE id = ?",
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
                self._conn.execute("DELETE FROM transfers WHERE product_id = ?", (product_id,))
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
        warehouse_id: int | None = None,
        returns: bool | None = None,
        product_id: int | None = None,
    ) -> list[MovementDetails]:
        """Yozuvlarni eng yangisidan boshlab qaytaradi; `kind` berilmasa — kirim ham, chiqim ham.

        `returns`: True — faqat qaytarishlar, False — qaytarishlarsiz, None — hammasi.
        `product_id` berilsa — faqat shu mahsulot yozuvlari.
        """
        where, params = period_filter(period)
        if product_id is not None:
            where += " AND product_id = ?"
            params.append(product_id)
        if returns is not None:
            where += " AND is_return" if returns else " AND NOT is_return"
        if kind is not None:
            where += " AND kind = ?"
            params.append(kind.value)
        if warehouse_id is not None:
            where += " AND warehouse_id = ?"
            params.append(warehouse_id)
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

    def save_movement(self, movement: Movement, require_group: bool = True) -> int:
        """Kirim/chiqimni qo'shadi yoki yangilaydi.

        Biror sanada ombordagidan ko'p chiqim hosil bo'lsa, rad etadi. Chiqim narxi
        kiritilmaydi — tannarx sifatida hisoblanadi (costing.py); `movement.price`
        faqat kirimda, `movement.sale_price` faqat chiqimda ishlatiladi.
        `require_group=False` — guruhini dastur o'zi to'ldiradigan yozuvlar uchun (obyektdan qaytish).
        """
        self._check_group(movement, require_group)
        return self._store(movement)

    def save_document(self, movements: Sequence[Movement], removed_ids: Sequence[int] = ()) -> list[int]:
        """Bitta hujjatdagi (nakladnoydagi) bir nechta yozuvni birga saqlaydi: yo hammasi, yo hech biri.

        `id` si bor yozuvlar yangilanadi, yo'qlari qo'shiladi; `removed_ids` — hujjatdan olib tashlangan
        yozuvlar (o'chiriladi). Hujjat raqami yozilmagan bo'lsa, dastur o'zi beradi (K-1, CH-1…).
        Xato qaysi qatorda ekani xabarda ko'rsatiladi.
        """
        if not movements:
            raise WarehouseError(tr("Kamida bitta mahsulot kiriting."))
        if not movements[0].doc_number.strip():
            number = self._next_doc_number(movements[0].kind)
            movements = [replace(movement, doc_number=number) for movement in movements]
        with self._conn:
            for movement_id in removed_ids:
                self._delete(movement_id)
            saved = []
            for number, movement in enumerate(movements, start=1):
                try:
                    self._check_group(movement)
                    saved.append(self._write(movement))
                except WarehouseError as error:
                    raise WarehouseError(tr("{0}-qator: {1}").format(number, error)) from error
        return saved

    def purchase_list(self) -> list[PurchaseLine]:
        """Kam qolgan va tugagan mahsulotlar: qancha olish kerakligi, oxirgi narxi va kimdan olingani.

        Tavsiya: qoldiqni minimal qoldiqning `PURCHASE_TARGET` barobarigacha to'ldirish
        (minimal qoldig'i belgilanmagan, tugagan mahsulot uchun — miqdor ko'rsatilmaydi).
        """
        lines = []
        for product in self.products():
            if not product.needs_attention:
                continue
            last = self._conn.execute(
                "SELECT price, counterparty FROM movements"
                " WHERE product_id = ? AND kind = 'IN' AND NOT is_return AND deleted_at IS NULL"
                " AND counterparty NOT IN (?, ?) ORDER BY date DESC, id DESC LIMIT 1",
                (product.id, INVENTORY_SURPLUS, OPENING_BALANCE),
            ).fetchone()
            quantity = max(product.min_stock * PURCHASE_TARGET - product.stock, 0.0)
            lines.append(PurchaseLine(product, round(quantity, 6), *(tuple(last) if last else (0.0, ""))))
        return lines

    def customers(self) -> list[str]:
        """Avval sotuv qilingan xaridorlar — sotuvda qayta yozmaslik uchun."""
        rows = self._conn.execute(
            "SELECT DISTINCT counterparty FROM movements"
            " WHERE kind = 'OUT' AND NOT is_return AND sale_price > 0 AND counterparty <> '' AND deleted_at IS NULL"
            " ORDER BY counterparty"
        )
        return [row[0] for row in rows]

    def delete_movement(self, movement_id: int) -> None:
        """Yozuvni hisobdan chiqaradi; u «O'chirilgan yozuvlar»da qoladi va tiklanishi mumkin."""
        with self._conn:
            self._delete(movement_id)

    def delete_document(self, movement_ids: Sequence[int]) -> None:
        """Hujjatning hamma yozuvini birga o'chiradi (tiklash mumkin); biri o'chmasa, hech biri o'chmaydi."""
        with self._conn:
            for movement_id in movement_ids:
                self._delete(movement_id)

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
            self._remember_site(movement)
            self._recalculate({movement.product_id})
            self._log(HistoryAction.RESTORE, movement.kind.value, movement_id, _describe_movement(movement))

    def adjust_stock(
        self,
        product_id: int,
        actual: float,
        day: date,
        author: str,
        note: str = "",
        warehouse_id: int = MAIN_WAREHOUSE_ID,
    ) -> int | None:
        """Inventarizatsiya: hisobdagi qoldiqni sanalgan (`actual`) qoldiqqa tenglashtiradi.

        Farq ortiqcha bo'lsa kirim, kamomad bo'lsa chiqim yozuvi yaratiladi va uning
        id si qaytadi; farq bo'lmasa — None.
        """
        if actual < 0:
            raise WarehouseError(tr("Haqiqiy qoldiq manfiy bo'lishi mumkin emas."))
        product = self.product(product_id, warehouse_id)
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
                warehouse_id=warehouse_id,
            )
        )

    def take_inventory(
        self,
        counted: dict[int, float],
        day: date,
        author: str,
        note: str = "",
        warehouse_id: int = MAIN_WAREHOUSE_ID,
    ) -> int:
        """Inventarizatsiya varag'i: `counted` — mahsulot id -> shu omborda sanalgan qoldiq.

        Tuzatilgan mahsulotlar sonini qaytaradi.
        """
        adjusted = [
            self.adjust_stock(product_id, actual, day, author, note, warehouse_id)
            for product_id, actual in counted.items()
        ]
        return sum(movement_id is not None for movement_id in adjusted)

    # --- Omborlar va ko'chirish ----------------------------------------------

    def stores(self) -> list[Store]:
        """Omborlar; birinchisi — har doim bor «Asosiy ombor»."""
        rows = self._conn.execute("SELECT id, name FROM warehouses ORDER BY id")
        return [Store(row["id"], store_name(row["name"])) for row in rows]

    def save_store(self, name: str, store_id: int | None = None) -> int:
        """Yangi ombor qo'shadi yoki mavjudining nomini o'zgartiradi."""
        name = name.strip()
        if not name:
            raise WarehouseError(tr("Ombor nomini kiriting."))
        try:
            with self._conn:
                if store_id is None:
                    return self._conn.execute("INSERT INTO warehouses (name) VALUES (?)", (name,)).lastrowid
                self._conn.execute("UPDATE warehouses SET name = ? WHERE id = ?", (name, store_id))
                return store_id
        except sqlite3.IntegrityError as error:
            raise WarehouseError(tr("«{0}» nomli ombor allaqachon bor.").format(name)) from error

    def delete_store(self, store_id: int) -> None:
        if store_id == MAIN_WAREHOUSE_ID:
            raise WarehouseError(tr("Asosiy omborni o'chirib bo'lmaydi."))
        used = self._conn.execute(
            "SELECT 1 FROM movements WHERE warehouse_id = :id"
            " UNION ALL SELECT 1 FROM transfers WHERE from_id = :id OR to_id = :id LIMIT 1",
            {"id": store_id},
        ).fetchone()
        if used:
            raise WarehouseError(tr("Bu ombor bo'yicha yozuvlar bor, shuning uchun uni o'chirib bo'lmaydi."))
        with self._conn:
            self._conn.execute("DELETE FROM warehouses WHERE id = ?", (store_id,))

    def transfer(self, transfer: Transfer) -> int:
        """Mahsulotni bir ombordan boshqasiga ko'chiradi; umumiy qoldiq va tannarx o'zgarmaydi."""
        if transfer.quantity <= 0:
            raise WarehouseError(tr("Miqdor noldan katta bo'lishi kerak."))
        if transfer.from_id == transfer.to_id:
            raise WarehouseError(tr("Boshqa omborni tanlang: mahsulot shu omborning o'zida turibdi."))
        if transfer.date > self._today():
            raise WarehouseError(tr("Sana bugundan keyin bo'lishi mumkin emas."))
        product = self.product(transfer.product_id)
        if product.is_service:
            raise WarehouseError(tr("Xizmatning qoldig'i yuritilmaydi."))
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO transfers (date, product_id, quantity, from_id, to_id, note, created_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    transfer.date.isoformat(),
                    transfer.product_id,
                    transfer.quantity,
                    transfer.from_id,
                    transfer.to_id,
                    transfer.note.strip(),
                    transfer.created_by,
                ),
            )
            self._recalculate({transfer.product_id})
            names = {store.id: store.name for store in self.stores()}
            summary = " · ".join(
                (
                    fmt_date(transfer.date),
                    product.name,
                    f"{fmt_qty(transfer.quantity)} {product.unit}",
                    f"{names[transfer.from_id]} → {names[transfer.to_id]}",
                )
            )
            self._log(HistoryAction.ADD, TRANSFER_ENTITY, cursor.lastrowid, summary)
        return cursor.lastrowid

    def transfers(self, period: Period = Period()) -> list[Transfer]:
        """Ko'chirishlar, eng yangisidan boshlab."""
        where, params = period_filter(period, "t.date")
        rows = self._conn.execute(
            f"""
            SELECT t.id, t.date, t.product_id, t.quantity, t.from_id, t.to_id, t.note, t.created_by,
                   p.name AS product_name, p.unit, f.name AS from_name, w.name AS to_name
            FROM transfers t
            JOIN products p ON p.id = t.product_id
            JOIN warehouses f ON f.id = t.from_id
            JOIN warehouses w ON w.id = t.to_id
            WHERE {where} ORDER BY t.date DESC, t.id DESC
            """,
            params,
        )
        return [
            Transfer(
                **{
                    **dict(row),
                    "date": date.fromisoformat(row["date"]),
                    "from_name": store_name(row["from_name"]),
                    "to_name": store_name(row["to_name"]),
                }
            )
            for row in rows
        ]

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

    def default_group(self, product_id: int) -> tuple[str, str]:
        """Yangi yozuvda taklif qilinadigan guruh va kategoriya: mahsulotning o'z guruhi,
        u berilmagan bo'lsa — mahsulotning eng oxirgi yozuvidagisi."""
        own = self._conn.execute("SELECT category, subcategory FROM products WHERE id = ?", (product_id,)).fetchone()
        if own is not None and own["category"]:
            return own["category"], own["subcategory"]
        row = self._conn.execute(
            "SELECT category, subcategory FROM movements"
            " WHERE product_id = ? AND category <> '' AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
            (product_id,),
        ).fetchone()
        return (row["category"], row["subcategory"]) if row else ("", "")

    def suggestions(self, kind: MovementKind, field: str) -> list[str]:
        """Avval kiritilgan ismlar/obyektlar — qayta yozmaslik uchun (dastur o'zi yozgan belgilarsiz).

        Chiqimning «obyekt» maydonida «Obyektlar» ro'yxatidagi hali ishlatilmagan nomlar ham taklif qilinadi.
        """
        if field not in SUGGESTION_FIELDS:
            raise ValueError(f"Noma'lum maydon: {field}")
        query = f"SELECT {field} FROM movements WHERE kind = ? AND {field} <> '' AND deleted_at IS NULL"
        if kind is MovementKind.OUT and field == "counterparty":
            query += " UNION SELECT name FROM sites"
        names = {row[0] for row in self._conn.execute(query, (kind.value,))}
        return sorted(names - _SYSTEM_COUNTERPARTIES.keys())

    # --- O'zgarishlar tarixi -----------------------------------------------

    def clear_history(self) -> int:
        """O'zgarishlar tarixini butunlay tozalaydi; o'chirilgan qatorlar sonini qaytaradi.

        Tarixda bitta yozuv qoladi: kim va qachon tozalagani — tozalashning o'zi izsiz qolmasligi uchun.
        Kirim, chiqim va o'chirilgan (tiklash mumkin bo'lgan) yozuvlarga tegilmaydi.
        """
        with self._conn:
            removed = self._conn.execute("DELETE FROM history").rowcount
            self._log(HistoryAction.CLEAR, HISTORY_ENTITY, None, tr("{0} ta yozuv o'chirildi").format(removed))
        return removed

    def history(self, period: Period = Period(), search: str = "", limit: int | None = None) -> list[HistoryEntry]:
        """Kim, qachon, nimani o'zgartirgani — eng yangisidan boshlab."""
        where, params = period_filter(period, "substr(at, 1, 10)")
        # Lavozim yozilmagan eski qatorlarda u foydalanuvchining hozirgi lavozimidan olinadi.
        rows = self._conn.execute(
            f"""
            SELECT id, at, actor, action, entity, entity_id, summary, previous,
                   COALESCE(NULLIF(actor_role, ''),
                            (SELECT role FROM users WHERE users.name = history.actor), '') AS actor_role
            FROM history WHERE {where} ORDER BY id DESC
            """,
            params,
        )
        found = [
            entry
            for entry in (
                HistoryEntry(
                    **{**dict(row), "at": datetime.fromisoformat(row["at"]), "action": HistoryAction(row["action"])}
                )
                for row in rows
            )
            if _matches(search, entry.actor, entry.role_title, entry.summary, entry.previous)
        ]
        return found[:limit] if limit else found

    # --- Ichki yordamchilar ------------------------------------------------

    def _next_doc_number(self, kind: MovementKind) -> str:
        prefix = DOC_NUMBER_PREFIXES[kind]
        rows = self._conn.execute(
            "SELECT doc_number FROM movements WHERE kind = ? AND doc_number LIKE ?", (kind.value, f"{prefix}%")
        )
        numbers = [int(row[0][len(prefix):]) for row in rows if row[0][len(prefix):].isdigit()]
        return f"{prefix}{max(numbers, default=0) + 1}"

    def _delete(self, movement_id: int) -> None:
        """Yozuvni o'chirilganlar qatoriga o'tkazadi. Tranzaksiya ichida chaqiriladi."""
        movement = self.movement(movement_id)
        self._conn.execute(
            "UPDATE movements SET deleted_at = ?, deleted_by = ? WHERE id = ?",
            (datetime.now().isoformat(sep=" ", timespec="seconds"), self.actor, movement_id),
        )
        self._recalculate({movement.product_id})
        self._log(HistoryAction.DELETE, movement.kind.value, movement_id, _describe_movement(movement))

    def _check_group(self, movement: Movement, required: bool = True) -> None:
        if required and self.group_required and not movement.category.strip():
            raise WarehouseError(tr("Guruhni tanlang."))

    def _store(self, movement: Movement) -> int:
        """Yozuvni o'z tranzaksiyasida saqlaydi; dastur o'zi yaratadigan yozuvlar ham shu yerdan o'tadi."""
        with self._conn:
            return self._write(movement)

    def _write(self, movement: Movement) -> int:
        """Yozuvni tekshiradi va yozadi. Tranzaksiya ichida chaqiriladi: xato bo'lsa, hammasi bekor bo'ladi."""
        if movement.quantity <= 0:
            raise WarehouseError(tr("Miqdor noldan katta bo'lishi kerak."))
        if movement.price < 0 or movement.sale_price < 0:
            raise WarehouseError(tr("Narx manfiy bo'lishi mumkin emas."))
        if movement.on_credit and not movement.counterparty.strip():
            raise WarehouseError(tr("Qarzga yozish uchun kimdan olingani yoki kimga berilgani ko'rsatilishi kerak."))
        # Sotuv narxi: chiqimda, shuningdek xaridordan qaytgan mahsulotda (qaytariladigan narx).
        keeps_sale_price = movement.kind is MovementKind.OUT or movement.is_return

        values = (
            movement.kind.value,
            movement.date.isoformat(),
            movement.product_id,
            movement.quantity,
            movement.price if movement.kind is MovementKind.IN else 0,
            movement.sale_price if keeps_sale_price else 0,
            movement.category.strip(),
            movement.subcategory.strip(),
            movement.person.strip(),
            movement.counterparty.strip(),
            movement.note.strip(),
            movement.doc_number.strip(),
            int(movement.is_return),
            int(movement.on_credit),
            movement.warehouse_id,
        )
        previous = self.movement(movement.id) if movement.id is not None else None
        # Eski yozuvning sanasi o'zgarmasa, uni tahrirlashga to'sqinlik qilinmaydi.
        if movement.date > self._today() and (previous is None or previous.date != movement.date):
            raise WarehouseError(tr("Sana bugundan keyin bo'lishi mumkin emas."))
        affected_products = {movement.product_id}
        if previous is None:
            cursor = self._conn.execute(
                "INSERT INTO movements (kind, date, product_id, quantity, price, sale_price,"
                " category, subcategory, person, counterparty, note, doc_number, is_return, on_credit,"
                " warehouse_id, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*values, movement.created_by),
            )
            movement_id = cursor.lastrowid
        else:
            affected_products.add(previous.product_id)
            self._conn.execute(
                "UPDATE movements SET kind = ?, date = ?, product_id = ?, quantity = ?, price = ?, sale_price = ?,"
                " category = ?, subcategory = ?, person = ?, counterparty = ?, note = ?, doc_number = ?,"
                " is_return = ?, on_credit = ?, warehouse_id = ? WHERE id = ?",
                (*values, movement.id),
            )
            movement_id = movement.id
        self._recalculate(affected_products)
        self._remember_site(movement)
        self._log(
            HistoryAction.ADD if previous is None else HistoryAction.EDIT,
            movement.kind.value,
            movement_id,
            _describe_movement(self.movement(movement_id)),
            _describe_movement(previous) if previous else "",
        )
        return movement_id

    def _remember_site(self, movement: Movement) -> None:
        """Chiqimda yozilgan yangi obyekt «Obyektlar» ro'yxatiga o'zi qo'shiladi (sotuvdagi xaridor — yo'q)."""
        name = movement.counterparty.strip()
        is_issue = movement.kind is MovementKind.OUT and not movement.is_return and not movement.sale_price
        if is_issue and name and name not in _SYSTEM_COUNTERPARTIES:
            self._conn.execute("INSERT OR IGNORE INTO sites (name) VALUES (?)", (name,))

    def _has_movements(self, product_id: int) -> bool:
        row = self._conn.execute("SELECT 1 FROM movements WHERE product_id = ? LIMIT 1", (product_id,)).fetchone()
        return row is not None

    def _log(self, action: HistoryAction, entity: str, entity_id: int | None, summary: str, previous: str = "") -> None:
        """Tranzaksiya ichida chaqiriladi: amal bekor bo'lsa, tarixdagi qator ham yozilmaydi."""
        self._conn.execute(
            "INSERT INTO history (actor, actor_role, action, entity, entity_id, summary, previous)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.actor, self.actor_role, action.value, entity, entity_id, summary, previous),
        )

    def _recalculate(self, product_ids: set[int]) -> None:
        """Tranzaksiya ichida chaqiriladi: qoldiq yetmasa xato ko'tariladi va o'zgarishlar bekor bo'ladi."""
        for product_id in product_ids:
            recalculate_costs(self._conn, product_id)
