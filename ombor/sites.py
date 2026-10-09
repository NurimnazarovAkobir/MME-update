"""Obyektlar: mahsulot beriladigan joylar va ulardan omborga qaytgan mahsulotlar (vozvrat).

Obyekt yozuvlar bilan nomi orqali bog'lanadi (katta-kichik harf farqsiz):
- obyektga berilgan — `counterparty` shu nom bo'lgan chiqim;
- obyektdan qaytgan — `counterparty` shu nom bo'lgan, «qaytarish» belgili kirim.
"""

from .database import period_filter
from .driver import sqlite3
from .errors import WarehouseError
from .i18n import tr
from .models import (
    HistoryAction,
    Movement,
    MovementDetails,
    MovementKind,
    Period,
    Site,
    SiteProduct,
    SiteReturn,
    SiteTotals,
)
from .warehouse import Warehouse

SITE_ENTITY = "site"
_SITE_COLUMNS = "id, name, address, manager, note, latitude, longitude"

_IS_ISSUE = "(m.kind = 'OUT' AND NOT m.is_return AND m.sale_price = 0)"  # sotuv — obyektga berish emas
_IS_RETURN = "(m.kind = 'IN' AND m.is_return)"
_BELONGS_TO_SITE = f"m.counterparty = s.name COLLATE NOCASE AND ({_IS_ISSUE} OR {_IS_RETURN})"


def _describe(site: Site) -> str:
    return " · ".join(part for part in (site.name, site.address, site.manager) if part)


class Sites:
    def __init__(self, conn: sqlite3.Connection, warehouse: Warehouse):
        self._conn = conn
        self._warehouse = warehouse
        self.actor = ""  # o'zgarishlar tarixiga yoziladigan foydalanuvchi
        self.actor_role = ""

    # --- Obyektlar ro'yxati --------------------------------------------------

    def all(self, search: str = "", period: Period = Period()) -> list[SiteTotals]:
        """Obyektlar, nomi bo'yicha; har birida `period` ichida berilgan va qaytgan mahsulotlar tannarxi."""
        in_period, params = period_filter(period, "m.date")
        rows = self._conn.execute(
            f"""
            SELECT s.id, s.name, s.address, s.manager, s.note, s.latitude, s.longitude,
                   COALESCE(SUM(CASE WHEN {_IS_ISSUE} THEN m.quantity * m.price END), 0) AS issued,
                   COALESCE(SUM(CASE WHEN {_IS_RETURN} THEN m.quantity * m.price END), 0) AS returned
            FROM sites s
            LEFT JOIN movements m ON {_BELONGS_TO_SITE} AND m.deleted_at IS NULL AND {in_period}
            GROUP BY s.id ORDER BY s.name
            """,
            params,
        )
        needle = search.strip().casefold()
        found = [SiteTotals(**dict(row)) for row in rows]
        return [
            site
            for site in found
            if any(needle in field.casefold() for field in (site.name, site.address, site.manager, site.note))
        ]

    def get(self, site_id: int) -> Site:
        row = self._conn.execute(f"SELECT {_SITE_COLUMNS} FROM sites WHERE id = ?", (site_id,)).fetchone()
        if row is None:
            raise WarehouseError(tr("Obyekt topilmadi."))
        return Site(**dict(row))

    def find(self, name: str) -> Site | None:
        """Shu nomli obyekt (katta-kichik harf farqsiz); bo'lmasa — None."""
        row = self._conn.execute(f"SELECT {_SITE_COLUMNS} FROM sites WHERE name = ?", (name.strip(),)).fetchone()
        return Site(**dict(row)) if row else None

    def save(self, site: Site) -> int:
        """Yangi obyekt qo'shadi yoki mavjudini yangilaydi; nomi o'zgarsa, yozuvlardagi nom ham almashadi."""
        name = " ".join(site.name.split())
        if not name:
            raise WarehouseError(tr("Obyekt nomini kiriting."))
        values = (name, site.address.strip(), site.manager.strip(), site.note.strip(), site.latitude, site.longitude)
        saved = Site(name, site.address.strip(), site.manager.strip())
        try:
            with self._conn:
                if site.id is None:
                    cursor = self._conn.execute(
                        "INSERT INTO sites (name, address, manager, note, latitude, longitude)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        values,
                    )
                    self._log(HistoryAction.ADD, cursor.lastrowid, _describe(saved))
                    return cursor.lastrowid
                previous = self.get(site.id)
                self._conn.execute(
                    "UPDATE sites SET name = ?, address = ?, manager = ?, note = ?, latitude = ?, longitude = ?"
                    " WHERE id = ?",
                    (*values, site.id),
                )
                if previous.name != name:
                    self._rename_in_records(previous.name, name)
                self._log(HistoryAction.EDIT, site.id, _describe(saved), _describe(previous))
                return site.id
        except sqlite3.IntegrityError as error:
            raise WarehouseError(tr("«{0}» nomli obyekt allaqachon bor.").format(name)) from error

    def delete(self, site_id: int) -> None:
        """Obyektni ro'yxatdan o'chiradi; unga mahsulot berilgan yoki undan qaytgan bo'lsa, rad etadi."""
        site = self.get(site_id)
        used = self._conn.execute(
            f"SELECT 1 FROM sites s JOIN movements m ON {_BELONGS_TO_SITE} AND m.deleted_at IS NULL"
            " WHERE s.id = ? LIMIT 1",
            (site_id,),
        ).fetchone()
        if used:
            raise WarehouseError(tr("Bu obyekt bo'yicha yozuvlar bor, shuning uchun uni o'chirib bo'lmaydi."))
        with self._conn:
            self._conn.execute("DELETE FROM sites WHERE id = ?", (site_id,))
            self._log(HistoryAction.DELETE, site_id, _describe(site))

    # --- Berilgan va qaytgan mahsulotlar -------------------------------------

    def products(
        self, site_id: int | None = None, period: Period = Period(), product_id: int | None = None
    ) -> list[SiteProduct]:
        """Obyektlar kesimida mahsulotlar: `period` ichida qancha berilgan va qancha qaytgan.

        `site_id` berilmasa — barcha obyektlar bo'yicha; `product_id` berilsa — faqat shu mahsulot.
        """
        where, params = period_filter(period, "m.date")
        if site_id is not None:
            where += " AND s.id = ?"
            params.append(site_id)
        if product_id is not None:
            where += " AND m.product_id = ?"
            params.append(product_id)
        rows = self._conn.execute(
            f"""
            SELECT s.name AS site, m.product_id, m.product_name, m.unit,
                   SUM(CASE WHEN {_IS_ISSUE} THEN m.quantity ELSE 0 END) AS issued,
                   SUM(CASE WHEN {_IS_RETURN} THEN m.quantity ELSE 0 END) AS returned,
                   SUM(CASE WHEN {_IS_ISSUE} THEN m.amount ELSE 0 END) AS issued_amount,
                   SUM(CASE WHEN {_IS_RETURN} THEN m.amount ELSE 0 END) AS returned_amount
            FROM sites s
            JOIN movement_details m ON {_BELONGS_TO_SITE}
            WHERE {where}
            GROUP BY s.id, m.product_id ORDER BY s.name, m.product_name
            """,
            params,
        )
        return [SiteProduct(**dict(row)) for row in rows]

    def returns(self, period: Period = Period(), search: str = "") -> list[MovementDetails]:
        """Qaytgan mahsulotlar yozuvlari, eng yangisidan boshlab."""
        return self._warehouse.movements(MovementKind.IN, period, search, returns=True)

    def save_return(self, site_return: SiteReturn) -> int:
        """Obyektdan qaytgan mahsulotni omborga kirim qiladi (yoki shunday yozuvni yangilaydi).

        Narxi — mahsulot shu obyektga berilgandagi o'rtacha tannarx: qaytgan mahsulot omborga
        o'sha qiymatda qaytadi. Guruhi mahsulotning oxirgi yozuvidan olinadi.
        """
        site = self.get(site_return.site_id)
        category, subcategory = self._warehouse.last_group(site_return.product_id)
        return self._warehouse.save_movement(
            Movement(
                kind=MovementKind.IN,
                date=site_return.date,
                product_id=site_return.product_id,
                quantity=site_return.quantity,
                price=self._issue_cost(site.name, site_return.product_id),
                category=category,
                subcategory=subcategory,
                person=site_return.person,
                counterparty=site.name,
                note=site_return.note,
                created_by=site_return.created_by,
                doc_number=site_return.doc_number,
                is_return=True,
                warehouse_id=site_return.warehouse_id,
                id=site_return.id,
            ),
            require_group=False,
        )

    # --- Ichki yordamchilar ------------------------------------------------

    def _issue_cost(self, site_name: str, product_id: int) -> float:
        """Mahsulot obyektga berilgandagi o'rtacha tannarx; berilmagan bo'lsa — hozirgi o'rtacha narxi."""
        row = self._conn.execute(
            "SELECT SUM(quantity * price) / SUM(quantity) FROM movements m"
            f" WHERE {_IS_ISSUE} AND deleted_at IS NULL AND product_id = ? AND counterparty = ? COLLATE NOCASE",
            (product_id, site_name),
        ).fetchone()
        return row[0] if row[0] is not None else self._warehouse.product(product_id).average_price

    def _rename_in_records(self, old: str, new: str) -> None:
        """Obyekt nomi o'zgarganda: unga tegishli yozuvlar va to'lovlar yangi nomga o'tadi."""
        self._conn.execute(
            f"UPDATE movements AS m SET counterparty = ? WHERE counterparty = ? COLLATE NOCASE"
            f" AND ({_IS_ISSUE} OR {_IS_RETURN})",
            (new, old),
        )
        self._conn.execute(
            "UPDATE payments SET counterparty = ? WHERE counterparty = ? AND kind = 'OUT'", (new, old)
        )

    def _log(self, action: HistoryAction, site_id: int, summary: str, previous: str = "") -> None:
        self._conn.execute(
            "INSERT INTO history (actor, actor_role, action, entity, entity_id, summary, previous)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.actor, self.actor_role, action.value, SITE_ENTITY, site_id, summary, previous),
        )
