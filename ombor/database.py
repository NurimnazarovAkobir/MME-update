"""SQLite bazasi: ulanish va sxema."""

from pathlib import Path

from . import catalog
from .driver import sqlite3
from .migrations import SCHEMA_VERSION, migrate
from .models import Period

TABLES = """
CREATE TABLE IF NOT EXISTS products (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    unit      TEXT NOT NULL,
    min_stock REAL NOT NULL DEFAULT 0,
    note      TEXT NOT NULL DEFAULT '',
    is_service INTEGER NOT NULL DEFAULT 0,  -- xizmat yoki xarajat: omborda qoldig'i yuritilmaydi
    barcode    TEXT NOT NULL DEFAULT '',
    alt_unit   TEXT NOT NULL DEFAULT '',    -- qo'shimcha o'lchov birligi (masalan, tonna)
    alt_factor REAL NOT NULL DEFAULT 0      -- 1 qo'shimcha birlik = shuncha asosiy birlik
);

CREATE TABLE IF NOT EXISTS warehouses (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

-- `price`: kirimda — sotib olish narxi; chiqimda — o'sha paytdagi o'rtacha
-- tannarx (dastur o'zi hisoblab qo'yadi, costing.py ga qarang).
-- `sale_price`: chiqim sotuv bo'lsa — sotuv narxi; 0 — ichki rasxod (foyda hisoblanmaydi).
-- `deleted_at`: o'chirilgan yozuv bazada qoladi (tiklash mumkin), lekin hisob-kitobga kirmaydi.
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
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    doc_number   TEXT NOT NULL DEFAULT '',  -- hujjat (nakladnoy) raqami
    deleted_at   TEXT,
    deleted_by   TEXT NOT NULL DEFAULT '',
    is_return    INTEGER NOT NULL DEFAULT 0,  -- kirimda: xaridordan qaytdi; chiqimda: yetkazib beruvchiga qaytarildi
    on_credit    INTEGER NOT NULL DEFAULT 0,  -- qarzga: summasi kontragent bilan hisob-kitobga tushadi
    warehouse_id INTEGER NOT NULL DEFAULT 1 REFERENCES warehouses(id)
);

-- Obyektlar: mahsulot beriladigan va undan qaytadigan joylar. Yozuvlar bilan nomi orqali bog'lanadi:
-- chiqimning (va obyektdan qaytgan kirimning) `counterparty` maydoni — obyekt nomi.
CREATE TABLE IF NOT EXISTS sites (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    address TEXT NOT NULL DEFAULT '',
    manager TEXT NOT NULL DEFAULT '',  -- mas'ul shaxs
    note    TEXT NOT NULL DEFAULT ''
);

-- Mahsulotni bir ombordan boshqasiga ko'chirish: umumiy qoldiq va tannarx o'zgarmaydi.
CREATE TABLE IF NOT EXISTS transfers (
    id         INTEGER PRIMARY KEY,
    date       TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity   REAL NOT NULL CHECK (quantity > 0),
    from_id    INTEGER NOT NULL REFERENCES warehouses(id),
    to_id      INTEGER NOT NULL REFERENCES warehouses(id),
    note       TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- To'lovlar: kind = 'IN' — yetkazib beruvchiga to'ladik; 'OUT' — xaridor bizga to'ladi.
CREATE TABLE IF NOT EXISTS payments (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('IN', 'OUT')),
    date         TEXT NOT NULL,
    counterparty TEXT NOT NULL COLLATE NOCASE,
    amount       REAL NOT NULL CHECK (amount > 0),
    note         TEXT NOT NULL DEFAULT '',
    created_by   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Tovar guruhlari (parent_id bo'sh) va kichik guruhlari. `ru` — yozuvlarda saqlanadigan nom.
CREATE TABLE IF NOT EXISTS groups (
    id        INTEGER PRIMARY KEY,
    parent_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
    ru        TEXT NOT NULL,
    uz        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password TEXT NOT NULL,
    role     TEXT NOT NULL
);

-- O'zgarishlar tarixi: kim, qachon, qaysi yozuvni qo'shdi, o'zgartirdi, o'chirdi yoki tikladi.
CREATE TABLE IF NOT EXISTS history (
    id        INTEGER PRIMARY KEY,
    at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    actor     TEXT NOT NULL DEFAULT '',
    actor_role TEXT NOT NULL DEFAULT '',  -- amal bajarilgan paytdagi lavozimi (models.Role)
    action    TEXT NOT NULL,  -- models.HistoryAction
    entity    TEXT NOT NULL,  -- 'IN', 'OUT' yoki 'product'
    entity_id INTEGER,
    summary   TEXT NOT NULL DEFAULT '',  -- amaldan keyingi holat
    previous  TEXT NOT NULL DEFAULT ''   -- tahrirlashda: oldingi holat
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
        "doc_number": "TEXT NOT NULL DEFAULT ''",
        "deleted_at": "TEXT",
        "deleted_by": "TEXT NOT NULL DEFAULT ''",
        "is_return": "INTEGER NOT NULL DEFAULT 0",
        "on_credit": "INTEGER NOT NULL DEFAULT 0",
        "warehouse_id": "INTEGER NOT NULL DEFAULT 1",
    },
    "history": {"actor_role": "TEXT NOT NULL DEFAULT ''"},
    "products": {
        "is_service": "INTEGER NOT NULL DEFAULT 0",
        "barcode": "TEXT NOT NULL DEFAULT ''",
        "alt_unit": "TEXT NOT NULL DEFAULT ''",
        "alt_factor": "REAL NOT NULL DEFAULT 0",
    },
}

# `revenue`, `cost_of_sales`, `profit` — faqat sotuvlar bo'yicha: sotuv narxli chiqim qo'shadi,
# xaridordan qaytgan mahsulot (qaytarish belgili kirim) ayiradi. Yetkazib beruvchiga qaytarish sotuv emas.
_IS_SALE = "(m.kind = 'OUT' AND NOT m.is_return AND m.sale_price > 0)"
_IS_SALE_RETURN = "(m.kind = 'IN' AND m.is_return AND m.sale_price > 0)"
_MOVEMENT_DETAILS = f"""
SELECT m.id, m.kind, m.date, m.product_id, m.quantity, m.price, m.sale_price,
       m.category, m.subcategory, m.person, m.counterparty, m.note, m.created_by, m.doc_number,
       m.created_at, m.deleted_at, m.deleted_by, m.is_return, m.on_credit, m.warehouse_id,
       p.name AS product_name, p.unit, p.is_service, w.name AS warehouse_name,
       m.quantity * m.price AS amount,
       CASE WHEN {_IS_SALE} THEN m.quantity * m.sale_price
            WHEN {_IS_SALE_RETURN} THEN -m.quantity * m.sale_price ELSE 0 END AS revenue,
       CASE WHEN {_IS_SALE} THEN m.quantity * m.price
            WHEN {_IS_SALE_RETURN} THEN -m.quantity * m.price ELSE 0 END AS cost_of_sales,
       CASE WHEN {_IS_SALE} THEN m.quantity * (m.sale_price - m.price)
            WHEN {_IS_SALE_RETURN} THEN -m.quantity * (m.sale_price - m.price) ELSE 0 END AS profit
FROM movements m
JOIN products p ON p.id = m.product_id
JOIN warehouses w ON w.id = m.warehouse_id
"""

VIEW_NAMES = ("movement_details", "deleted_movements", "product_stock")
VIEWS = f"""
DROP VIEW IF EXISTS movement_details;
DROP VIEW IF EXISTS deleted_movements;
DROP VIEW IF EXISTS product_stock;

CREATE VIEW product_stock AS
SELECT p.id, p.name, p.unit, p.min_stock, p.note, p.is_service, p.barcode, p.alt_unit, p.alt_factor,
       COALESCE(SUM(CASE WHEN m.kind = 'IN' THEN m.quantity END), 0) AS qty_in,
       COALESCE(SUM(CASE WHEN m.kind = 'OUT' THEN m.quantity END), 0) AS qty_out,
       COALESCE(SUM(CASE WHEN m.kind = 'IN' THEN m.quantity * m.price END), 0) AS amount_in,
       COALESCE(SUM(CASE WHEN m.kind = 'OUT' THEN m.quantity * m.price END), 0) AS amount_out
FROM products p
LEFT JOIN movements m ON m.product_id = p.id AND m.deleted_at IS NULL
GROUP BY p.id;

CREATE VIEW movement_details AS {_MOVEMENT_DETAILS} WHERE m.deleted_at IS NULL;

CREATE VIEW deleted_movements AS {_MOVEMENT_DETAILS} WHERE m.deleted_at IS NOT NULL;
"""

MAIN_WAREHOUSE_ID = 1
MAIN_WAREHOUSE_NAME = "Asosiy ombor"
# Tarmoqdagi umumiy bazada boshqa kompyuter yozayotgan bo'lsa, shuncha soniya kutiladi.
BUSY_TIMEOUT_SECONDS = 20


class NewerDatabaseError(Exception):
    """Baza dasturning yangiroq versiyasida yaratilgan: bu (eski) dastur uni ocha olmaydi."""


def connect(path: Path | str, key: str | None = None) -> sqlite3.Connection:
    """Bazaga ulanadi va sxemani tayyorlaydi. `path` uchun ':memory:' ham bo'ladi.

    `key` — shifrlangan baza kaliti (64 ta o'n oltilik belgi); oddiy baza uchun berilmaydi.
    """
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = open_raw(path, key)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        prepare(conn)
        catalog.load(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def open_raw(path: Path | str, key: str | None = None) -> sqlite3.Connection:
    """Sxemaga tegmasdan ulanadi (zaxira nusxa va tekshiruvlar uchun)."""
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    if key:
        conn.execute(f"PRAGMA key = \"x'{key}'\"")
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def prepare(conn: sqlite3.Connection) -> None:
    """Sxemani joriy versiyaga keltiradi; eski bazada ham, yangisida ham xavfsiz ishlaydi.

    Baza allaqachon joriy versiyada bo'lsa, unga hech narsa yozilmaydi: tarmoqda boshqa
    kompyuterlar ishlab turganda dasturni ochish ularga xalaqit bermaydi.
    """
    version = schema_version(conn)
    if version > SCHEMA_VERSION:
        raise NewerDatabaseError(version)
    views = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'")}
    if version == SCHEMA_VERSION and views >= set(VIEW_NAMES):
        return
    conn.executescript(TABLES)
    for table, columns in ADDED_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, definition in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.execute("INSERT OR IGNORE INTO warehouses (id, name) VALUES (?, ?)", (MAIN_WAREHOUSE_ID, MAIN_WAREHOUSE_NAME))
    conn.commit()
    conn.executescript(f"BEGIN IMMEDIATE;{VIEWS}COMMIT;")
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
