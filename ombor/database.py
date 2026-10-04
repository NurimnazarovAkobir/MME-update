"""SQLite bazasi: ulanish va sxema."""

import sqlite3
from pathlib import Path

from .migrations import migrate
from .models import Period

TABLES = """
CREATE TABLE IF NOT EXISTS products (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    unit      TEXT NOT NULL,
    min_stock REAL NOT NULL DEFAULT 0,
    note      TEXT NOT NULL DEFAULT ''
);

-- `price`: kirimda — sotib olish narxi; chiqimda — o'sha paytdagi o'rtacha
-- tannarx (dastur o'zi hisoblab qo'yadi, costing.py ga qarang).
-- `sale_price`: chiqim sotuv bo'lsa — sotuv narxi; 0 — ichki rasxod (foyda hisoblanmaydi).
CREATE TABLE IF NOT EXISTS movements (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('IN', 'OUT')),
    date         TEXT NOT NULL,
    product_id   INTEGER NOT NULL REFERENCES products(id),
    quantity     REAL NOT NULL CHECK (quantity > 0),
    price        REAL NOT NULL DEFAULT 0 CHECK (price >= 0),
    sale_price   REAL NOT NULL DEFAULT 0 CHECK (sale_price >= 0),
    category     TEXT NOT NULL DEFAULT '',  -- guruh (catalog.py); ruscha nomi saqlanadi
    subcategory  TEXT NOT NULL DEFAULT '',  -- kichik guruh
    person       TEXT NOT NULL DEFAULT '',
    counterparty TEXT NOT NULL DEFAULT '',
    note         TEXT NOT NULL DEFAULT '',
    created_by   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password TEXT NOT NULL,
    role     TEXT NOT NULL CHECK (role IN ('admin', 'keeper'))
);

CREATE INDEX IF NOT EXISTS idx_movements_product ON movements(product_id);
CREATE INDEX IF NOT EXISTS idx_movements_date ON movements(date);
"""

# Eski versiyada yaratilgan bazalarga qo'shiladigan ustunlar: jadval -> {ustun: ta'rifi}.
ADDED_COLUMNS = {
    "movements": {
        "created_by": "TEXT NOT NULL DEFAULT ''",
        "sale_price": "REAL NOT NULL DEFAULT 0",
        "category": "TEXT NOT NULL DEFAULT ''",
        "subcategory": "TEXT NOT NULL DEFAULT ''",
    },
}

VIEWS = """
DROP VIEW IF EXISTS movement_details;
DROP VIEW IF EXISTS product_stock;

CREATE VIEW product_stock AS
SELECT p.id, p.name, p.unit, p.min_stock, p.note,
       COALESCE(SUM(CASE WHEN m.kind = 'IN' THEN m.quantity END), 0) AS qty_in,
       COALESCE(SUM(CASE WHEN m.kind = 'OUT' THEN m.quantity END), 0) AS qty_out,
       COALESCE(SUM(CASE WHEN m.kind = 'IN' THEN m.quantity * m.price END), 0) AS amount_in,
       COALESCE(SUM(CASE WHEN m.kind = 'OUT' THEN m.quantity * m.price END), 0) AS amount_out
FROM products p
LEFT JOIN movements m ON m.product_id = p.id
GROUP BY p.id;

CREATE VIEW movement_details AS
SELECT m.id, m.kind, m.date, m.product_id, m.quantity, m.price, m.sale_price,
       m.category, m.subcategory, m.person, m.counterparty, m.note, m.created_by,
       p.name AS product_name, p.unit,
       m.quantity * m.price AS amount,
       m.quantity * m.sale_price AS revenue,
       CASE WHEN m.sale_price > 0 THEN m.quantity * (m.sale_price - m.price) ELSE 0 END AS profit
FROM movements m
JOIN products p ON p.id = m.product_id;
"""


def connect(path: Path | str) -> sqlite3.Connection:
    """Bazaga ulanadi va sxemani tayyorlaydi. `path` uchun ':memory:' ham bo'ladi."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    prepare(conn)
    return conn


def prepare(conn: sqlite3.Connection) -> None:
    """Sxemani joriy versiyaga keltiradi; eski bazada ham, yangisida ham xavfsiz ishlaydi."""
    conn.executescript(TABLES)
    for table, columns in ADDED_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, definition in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.executescript(VIEWS)
    migrate(conn)


def period_filter(period: Period, column: str = "date") -> tuple[str, list[str]]:
    """Davr uchun SQL sharti va uning parametrlarini qaytaradi."""
    clauses, params = [], []
    if period.start:
        clauses.append(f"{column} >= ?")
        params.append(period.start.isoformat())
    if period.end:
        clauses.append(f"{column} <= ?")
        params.append(period.end.isoformat())
    return " AND ".join(clauses) or "1 = 1", params
