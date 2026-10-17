"""Eski versiyada yaratilgan bazani yangi versiyaga o'tkazish."""

from . import catalog
from .costing import recalculate_costs
from .driver import sqlite3
from .models import Role

SCHEMA_VERSION = 12  # 11: buxgalteriya sinxronlashdan chiqarildi; 12: umumiy papka orqali almashish jadvallari
LEGACY_PASSWORD_KEY = "password"
LEGACY_ADMIN_NAME = "Rahbar"
# 3-versiyagacha «boshlang'ich qoldiq» belgisi o'sha paytdagi tilda yozilgan; endi bitta ko'rinishda saqlanadi.
LEGACY_OPENING_BALANCE = "Начальный остаток"
OPENING_BALANCE = "Boshlang'ich qoldiq"
INVENTORY_SHORTAGE = "Inventarizatsiya (kamomad)"  # dastur o'zi yozadigan chiqim — obyekt emas


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return
    with conn:
        if version < 2:
            _fix_issue_costs(conn)
            _move_single_password_to_users(conn)
        _move_groups_to_movements(conn)
        _allow_new_roles(conn)
        catalog.seed(conn)
        _collect_sites(conn)
        _drop_customer_sites(conn)
        _give_products_groups(conn)
        conn.execute(
            "UPDATE movements SET counterparty = ? WHERE counterparty = ?", (OPENING_BALANCE, LEGACY_OPENING_BALANCE)
        )
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _give_products_groups(conn: sqlite3.Connection) -> None:
    """10-versiyagacha mahsulotning o'z guruhi bo'lmagan: oxirgi yozuvidagi guruh va kategoriya olinadi."""
    conn.execute("""
        UPDATE products SET
            category = (SELECT m.category FROM movements m WHERE m.product_id = products.id
                        AND m.category <> '' AND m.deleted_at IS NULL ORDER BY m.id DESC LIMIT 1),
            subcategory = (SELECT m.subcategory FROM movements m WHERE m.product_id = products.id
                           AND m.category <> '' AND m.deleted_at IS NULL ORDER BY m.id DESC LIMIT 1)
        WHERE category = '' AND EXISTS (SELECT 1 FROM movements m WHERE m.product_id = products.id
                                        AND m.category <> '' AND m.deleted_at IS NULL)
        """)


def _collect_sites(conn: sqlite3.Connection) -> None:
    """7-versiyagacha obyektlar ro'yxati bo'lmagan: chiqimlarda yozilgan nomlardan yig'iladi."""
    conn.execute(
        "INSERT OR IGNORE INTO sites (name) SELECT DISTINCT counterparty FROM movements"
        " WHERE kind = 'OUT' AND NOT is_return AND sale_price = 0 AND deleted_at IS NULL"
        " AND counterparty NOT IN ('', ?)",
        (INVENTORY_SHORTAGE,),
    )


def _drop_customer_sites(conn: sqlite3.Connection) -> None:
    """7-versiyada sotuvdagi xaridorlar ham obyekt bo'lib yig'ilgan: ular ro'yxatdan chiqariladi.

    Faqat ma'lumoti to'ldirilmagan va obyekt sifatida ishlatilmagan (ichki chiqimi ham, vozvrati ham yo'q) nomlar.
    """
    conn.execute(
        """
        DELETE FROM sites
        WHERE address = '' AND manager = '' AND note = ''
          AND EXISTS (SELECT 1 FROM movements m WHERE m.counterparty = sites.name COLLATE NOCASE
                      AND m.kind = 'OUT' AND NOT m.is_return AND m.sale_price > 0)
          AND NOT EXISTS (SELECT 1 FROM movements m WHERE m.counterparty = sites.name COLLATE NOCASE
                          AND ((m.kind = 'OUT' AND NOT m.is_return AND m.sale_price = 0)
                               OR (m.kind = 'IN' AND m.is_return)))
        """
    )


def _fix_issue_costs(conn: sqlite3.Connection) -> None:
    """1-versiyada chiqim narxi saqlanmagan: endi sana tartibida hisoblab yoziladi."""
    for (product_id,) in conn.execute("SELECT id FROM products").fetchall():
        recalculate_costs(conn, product_id, strict=False)


def _move_single_password_to_users(conn: sqlite3.Connection) -> None:
    """1-versiyadagi yagona parol «Rahbar» nomli foydalanuvchining paroliga aylanadi."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (LEGACY_PASSWORD_KEY,)).fetchone()
    if row is None:
        return
    has_users = conn.execute("SELECT 1 FROM users").fetchone() is not None
    if not has_users:
        conn.execute(
            "INSERT INTO users (name, password, role) VALUES (?, ?, ?)",
            (LEGACY_ADMIN_NAME, row["value"], Role.ADMIN.value),
        )
    conn.execute("DELETE FROM settings WHERE key = ?", (LEGACY_PASSWORD_KEY,))


def _move_groups_to_movements(conn: sqlite3.Connection) -> None:
    """2-versiyada guruh mahsulotga berilgan edi; endi har bir kirim/chiqim yozuvida saqlanadi."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(products)")}
    if "category" not in columns:
        return
    subcategory = "p.subcategory" if "subcategory" in columns else "''"
    conn.execute(f"""
        UPDATE movements SET
            category = (SELECT p.category FROM products p WHERE p.id = movements.product_id),
            subcategory = (SELECT {subcategory} FROM products p WHERE p.id = movements.product_id)
        WHERE category = ''
        """)


def _allow_new_roles(conn: sqlite3.Connection) -> None:
    """3-versiyagacha `users` jadvali faqat ikki lavozimga ruxsat bergan; cheklovsiz qayta yaratiladi."""
    definition = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'").fetchone()[0]
    if "CHECK" not in definition:
        return
    conn.execute("ALTER TABLE users RENAME TO users_old")
    conn.execute("""
        CREATE TABLE users (
            id       INTEGER PRIMARY KEY,
            name     TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password TEXT NOT NULL,
            role     TEXT NOT NULL
        )
        """)
    conn.execute("INSERT INTO users (id, name, password, role) SELECT id, name, password, role FROM users_old")
    conn.execute("DROP TABLE users_old")
