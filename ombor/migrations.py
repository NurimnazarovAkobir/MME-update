"""Eski versiyada yaratilgan bazani yangi versiyaga o'tkazish."""

import sqlite3

from .costing import recalculate_costs
from .models import Role

SCHEMA_VERSION = 3
LEGACY_PASSWORD_KEY = "password"
LEGACY_ADMIN_NAME = "Rahbar"


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return
    with conn:
        if version < 2:
            _fix_issue_costs(conn)
            _move_single_password_to_users(conn)
        _move_groups_to_movements(conn)
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
