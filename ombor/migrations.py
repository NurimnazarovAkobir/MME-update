"""Eski versiyada yaratilgan bazani yangi versiyaga o'tkazish."""

from . import catalog
from .costing import recalculate_costs
from .driver import sqlite3
from .models import Role

SCHEMA_VERSION = 5
LEGACY_PASSWORD_KEY = "password"
LEGACY_ADMIN_NAME = "Rahbar"
# 3-versiyagacha «boshlang'ich qoldiq» belgisi o'sha paytdagi tilda yozilgan; endi bitta ko'rinishda saqlanadi.
LEGACY_OPENING_BALANCE = "Начальный остаток"
OPENING_BALANCE = "Boshlang'ich qoldiq"


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
        conn.execute(
            "UPDATE movements SET counterparty = ? WHERE counterparty = ?", (OPENING_BALANCE, LEGACY_OPENING_BALANCE)
        )
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


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
