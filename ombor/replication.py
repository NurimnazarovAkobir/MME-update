"""Markaziy baza bilan sinxronlash: shu kompyuterdagi o'zgarishlarni kuzatish va serverdagilarni qo'llash.

Har bir kompyuter o'z bazasida ishlaydi (internet bo'lmasa ham). Sinxronlash yoqilgach:

- har bir sinxronlanadigan qatorga butun dunyo bo'yicha yagona `uid` beriladi (trigger orqali, o'zi);
- har bir qo'shish, o'zgartirish va o'chirish triggerlar orqali `sync_outbox` navbatiga yoziladi —
  dasturning qolgan kodi bundan bexabar ishlayveradi;
- internet bo'lganda navbatdagi qatorlarning joriy holati serverga yuboriladi (sync.py),
  serverdan esa boshqa kompyuterlardagi o'zgarishlar olinib, shu yerda qo'llanadi.

Ziddiyat bo'lsa, serverga oxirgi yetib kelgan o'zgarish g'olib (last-writer-wins). Serverdan kelgan
o'zgarishlar navbatga yozilmaydi (aks holda ular qaytib ketaverardi).
"""

import json
from dataclasses import dataclass, field

from .costing import recalculate_costs
from .driver import sqlite3
from .sync_protocol import LOCAL_SETTINGS, MAIN_WAREHOUSE_UID, TABLES, TABLES_BY_NAME, Change, TableSpec

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS sync_state (
        id        INTEGER PRIMARY KEY CHECK (id = 1),
        tracking  INTEGER NOT NULL DEFAULT 0,  -- 1: sinxronlash yoqilgan, o'zgarishlar navbatga yoziladi
        last_seq  INTEGER NOT NULL DEFAULT 0,  -- serverdan olingan oxirgi o'zgarishning tartib raqami
        republish INTEGER NOT NULL DEFAULT 0   -- 1: zaxiradan tiklangan; serverdagi ortiqcha qatorlar o'chiriladi
    )
    """,
    "INSERT OR IGNORE INTO sync_state (id) VALUES (1)",
    # Serverga yuborilishi kerak bo'lgan qatorlar: jadval va uid (holati yuborish paytida o'qiladi).
    "CREATE TABLE IF NOT EXISTS sync_outbox (id INTEGER PRIMARY KEY, tbl TEXT NOT NULL, uid TEXT NOT NULL)",
    # Serverdan kelgan, lekin bog'langan qatori (masalan, mahsuloti) hali kelmagan o'zgarishlar.
    "CREATE TABLE IF NOT EXISTS sync_pending (id INTEGER PRIMARY KEY, change TEXT NOT NULL)",
)
_TRACKING = "(SELECT tracking FROM sync_state WHERE id = 1) = 1"
_NEW_UID = "lower(hex(randomblob(16)))"
_LOCAL_KEYS = ", ".join(f"'{key}'" for key in sorted(LOCAL_SETTINGS))


def _shared(spec: TableSpec, row: str) -> str:
    """SQL sharti: `row` (NEW yoki OLD) qatori boshqa kompyuterlarga yuboriladimi."""
    shared = f"{row}.{spec.key} IS NOT NULL"
    if spec.name == "settings":
        shared += f" AND {row}.key NOT IN ({_LOCAL_KEYS})"
    return shared


def install(conn: sqlite3.Connection, main_warehouse_id: int) -> None:
    """Sinxronlash jadvallari, `uid` ustunlari va triggerlarni yaratadi. Sxema yangilanganda chaqiriladi."""
    for statement in _SCHEMA:
        conn.execute(statement)
    for spec in TABLES:
        if spec.key == "uid":
            _add_uid(conn, spec.name)
        _create_triggers(conn, spec)
    conn.execute("UPDATE warehouses SET uid = ? WHERE id = ?", (MAIN_WAREHOUSE_UID, main_warehouse_id))
    for spec in TABLES:
        if spec.key == "uid":
            conn.execute(f"UPDATE {spec.name} SET uid = {_NEW_UID} WHERE uid IS NULL")


def _add_uid(conn: sqlite3.Connection, table: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if "uid" not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN uid TEXT")
    conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_uid ON {table}(uid)")


def _create_triggers(conn: sqlite3.Connection, spec: TableSpec) -> None:
    table, key = spec.name, spec.key
    queue = f"INSERT INTO sync_outbox (tbl, uid) SELECT '{table}', "
    new, old = _shared(spec, "NEW"), _shared(spec, "OLD")
    triggers = {
        f"sync_insert_{table}": f"""
            AFTER INSERT ON {table} WHEN {new} AND {_TRACKING}
            BEGIN {queue}NEW.{key}; END""",
        # Kalit o'zgarsa (uid berilishi yoki sozlama nomi), eskisi ham navbatga tushadi: serverda u o'chiriladi.
        f"sync_update_{table}": f"""
            AFTER UPDATE ON {table} WHEN {_TRACKING}
            BEGIN
                {queue}OLD.{key} WHERE {old} AND OLD.{key} IS NOT NEW.{key};
                {queue}NEW.{key} WHERE {new};
            END""",
        f"sync_delete_{table}": f"""
            AFTER DELETE ON {table} WHEN {old} AND {_TRACKING}
            BEGIN {queue}OLD.{key}; END""",
    }
    if key == "uid":
        triggers[f"sync_uid_{table}"] = f"""
            AFTER INSERT ON {table} WHEN NEW.uid IS NULL
            BEGIN UPDATE {table} SET uid = {_NEW_UID} WHERE id = NEW.id; END"""
    for name, body in triggers.items():
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
        conn.execute(f"CREATE TRIGGER {name} {body}")


@dataclass
class _Applier:
    """Serverdan kelgan o'zgarishlarni bitta tranzaksiya ichida qo'llaydi."""

    conn: sqlite3.Connection
    products: set[int] = field(default_factory=set)  # tannarxi qayta hisoblanadigan mahsulotlar
    _columns: dict[str, set[str]] = field(default_factory=dict)

    def apply(self, change: Change) -> bool:
        """O'zgarishni qo'llaydi; bog'langan qatori hali yo'q bo'lsa — False (keyinroq qayta uriniladi)."""
        spec = TABLES_BY_NAME[change.table]
        if spec.name == "settings" and change.uid in LOCAL_SETTINGS:
            return True
        current = self._find(spec, change.uid)
        if change.deleted:
            if current is not None:
                self._delete(spec, change.uid, current)
            return True
        values = self._local_values(spec, change.data)
        if values is None:
            return False
        self._make_room(spec, change.uid, values)
        if current is None:
            self._insert(spec, change.uid, values)
        else:
            self._remember_products(spec, current)
            assignments = ", ".join(f"{column} = ?" for column in values)
            self.conn.execute(
                f"UPDATE {spec.name} SET {assignments} WHERE {spec.key} = ?", (*values.values(), change.uid)
            )
        self._remember_products(spec, self._find(spec, change.uid))
        return True

    def recalculate(self) -> None:
        existing = {row[0] for row in self.conn.execute("SELECT id FROM products")}
        for product_id in self.products & existing:
            recalculate_costs(self.conn, product_id, strict=False)

    def _find(self, spec: TableSpec, uid: str) -> sqlite3.Row | None:
        return self.conn.execute(f"SELECT * FROM {spec.name} WHERE {spec.key} = ?", (uid,)).fetchone()

    def _local_values(self, spec: TableSpec, data: dict) -> dict | None:
        """Kelgan ma'lumotni shu bazadagi ustunlarga moslaydi; bog'lanishlar uid dan shu bazadagi id ga o'giriladi.

        Shu dastur versiyasida yo'q ustunlar (yangiroq versiyadan kelgan) tashlab ketiladi.
        """
        columns = self._table_columns(spec.name)
        values = {column: value for column, value in data.items() if column in columns}
        for column, target in spec.references.items():
            uid = values.get(column)
            if uid is None:
                continue
            row = self.conn.execute(f"SELECT id FROM {target} WHERE uid = ?", (uid,)).fetchone()
            if row is None:
                return None
            values[column] = row[0]
        return values

    def _insert(self, spec: TableSpec, uid: str, values: dict) -> None:
        if spec.key == "uid":
            values = {**values, "uid": uid}
        if spec.name == "warehouses" and uid == MAIN_WAREHOUSE_UID:
            values = {**values, "id": 1}  # «Asosiy ombor» har bir bazada id = 1
        names = ", ".join(values)
        placeholders = ", ".join("?" * len(values))
        self.conn.execute(f"INSERT INTO {spec.name} ({names}) VALUES ({placeholders})", tuple(values.values()))

    def _make_room(self, spec: TableSpec, uid: str, values: dict) -> None:
        """Kelgan nom shu yerda boshqa qatorda band bo'lsa, o'sha qator vaqtincha boshqa nom oladi.

        Serverda nomlar takrorlanmaydi, shuning uchun bu faqat bir to'plam ichidagi tartib tufayli bo'ladi
        (masalan, «Sement» boshqa qatorga o'tgan, eskisi esa « (2)» bo'lib keyinroq keladi): o'sha qatorning
        o'z yangi nomi shu to'plamda keladi va vaqtinchalik nom almashadi.
        """
        if not spec.unique or values.get(spec.unique) is None:
            return
        self.conn.execute(
            f"UPDATE {spec.name} SET {spec.unique} = {spec.unique} || ' ~' || substr({spec.key}, 1, 8)"
            f" WHERE {spec.unique} = ? AND {spec.key} <> ?",
            (values[spec.unique], uid),
        )

    def _delete(self, spec: TableSpec, uid: str, current: sqlite3.Row) -> None:
        """O'chiradi; shu yerda unga hali bog'langan yozuvlar bo'lsa, qator qoladi va serverga qaytadan yuboriladi."""
        self._remember_products(spec, current)
        try:
            self.conn.execute("SAVEPOINT sync_delete")
            self.conn.execute(f"DELETE FROM {spec.name} WHERE {spec.key} = ?", (uid,))
            self.conn.execute("RELEASE sync_delete")
        except sqlite3.IntegrityError:
            self.conn.execute("ROLLBACK TO sync_delete")
            self.conn.execute("RELEASE sync_delete")
            self.conn.execute("INSERT INTO sync_outbox (tbl, uid) VALUES (?, ?)", (spec.name, uid))

    def _remember_products(self, spec: TableSpec, row: sqlite3.Row | None) -> None:
        if row is None:
            return
        if spec.name == "products":
            self.products.add(row["id"])
        elif spec.name in ("movements", "transfers"):
            self.products.add(row["product_id"])

    def _table_columns(self, table: str) -> set[str]:
        if table not in self._columns:
            names = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            self._columns[table] = names - {"id", "uid"}
        return self._columns[table]


class Replica:
    """Shu kompyuterdagi bazaning sinxronlash holati: navbat, oxirgi olingan o'zgarish va qo'llash."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # --- Holat -------------------------------------------------------------

    def _state(self) -> sqlite3.Row:
        return self._conn.execute("SELECT tracking, last_seq, republish FROM sync_state WHERE id = 1").fetchone()

    @property
    def enabled(self) -> bool:
        return bool(self._state()["tracking"])

    @property
    def last_seq(self) -> int:
        return self._state()["last_seq"]

    @property
    def needs_republish(self) -> bool:
        return bool(self._state()["republish"])

    def pending_count(self) -> int:
        """Serverga hali yuborilmagan o'zgargan qatorlar soni."""
        return self._conn.execute("SELECT COUNT(*) FROM (SELECT 1 FROM sync_outbox GROUP BY tbl, uid)").fetchone()[0]

    def enable(self, publish_all: bool) -> None:
        """Sinxronlashni yoqadi. `publish_all` — bazadagi hamma narsa serverga yuboriladi (birinchi kompyuter)."""
        with self._conn:
            self._conn.execute("UPDATE sync_state SET tracking = 1, last_seq = 0, republish = 0")
            self._conn.execute("DELETE FROM sync_outbox")
            self._conn.execute("DELETE FROM sync_pending")
            if publish_all:
                self._enqueue_all()

    def disable(self) -> None:
        with self._conn:
            self._conn.execute("UPDATE sync_state SET tracking = 0, last_seq = 0, republish = 0")
            self._conn.execute("DELETE FROM sync_outbox")
            self._conn.execute("DELETE FROM sync_pending")

    def mark_restored(self) -> None:
        """Zaxiradan tiklangach: tiklangan holat to'liq serverga yuboriladi, serverdagi ortiqchasi o'chiriladi."""
        with self._conn:
            self._conn.execute("UPDATE sync_state SET tracking = 1, last_seq = 0, republish = 1")
            self._conn.execute("DELETE FROM sync_outbox")
            self._conn.execute("DELETE FROM sync_pending")
            self._enqueue_all()

    def _enqueue_all(self) -> None:
        for spec in TABLES:  # jadvallar va qatorlar yaratilgan tartibda: bog'langan qator oldin boradi
            self._conn.execute(
                f"INSERT INTO sync_outbox (tbl, uid) SELECT ?, {spec.key} FROM {spec.name} AS NEW"
                f" WHERE {_shared(spec, 'NEW')} ORDER BY rowid",
                (spec.name,),
            )

    # --- Yuborish ----------------------------------------------------------

    def outgoing(self, limit: int) -> tuple[int, list[Change]]:
        """Navbatdagi qatorlarning joriy holati, navbatga tushgan tartibda (bog'langan qator oldin).

        Qaytadi: (navbatning shu paytdagi oxirgi raqami, o'zgarishlar). Yuborilgach — `acknowledge`.
        """
        last_id = self._conn.execute("SELECT COALESCE(MAX(id), 0) FROM sync_outbox").fetchone()[0]
        rows = self._conn.execute(
            "SELECT tbl, uid FROM sync_outbox WHERE id <= ? GROUP BY tbl, uid ORDER BY MIN(id) LIMIT ?",
            (last_id, limit),
        ).fetchall()
        return last_id, [self._snapshot(TABLES_BY_NAME[table], uid) for table, uid in rows]

    def acknowledge(self, last_id: int, changes: list[Change]) -> None:
        """Serverga yetib borgan qatorlarni navbatdan olib tashlaydi (keyin yana o'zgarganlari qoladi)."""
        with self._conn:
            self._conn.executemany(
                "DELETE FROM sync_outbox WHERE tbl = ? AND uid = ? AND id <= ?",
                [(change.table, change.uid, last_id) for change in changes],
            )

    def all_keys(self) -> dict[str, list[str]]:
        """Bazadagi barcha sinxronlanadigan qatorlar kalitlari: zaxiradan tiklangach serverni tozalash uchun."""
        return {
            spec.name: [
                row[0]
                for row in self._conn.execute(f"SELECT {spec.key} FROM {spec.name} AS NEW WHERE {_shared(spec, 'NEW')}")
            ]
            for spec in TABLES
        }

    def republished(self) -> None:
        with self._conn:
            self._conn.execute("UPDATE sync_state SET republish = 0")

    def _snapshot(self, spec: TableSpec, uid: str) -> Change:
        row = self._conn.execute(f"SELECT * FROM {spec.name} WHERE {spec.key} = ?", (uid,)).fetchone()
        if row is None:
            return Change(spec.name, uid, None, deleted=True)
        data = {column: row[column] for column in row.keys() if column not in ("id", "uid")}
        for column, target in spec.references.items():
            if data.get(column) is not None:
                found = self._conn.execute(f"SELECT uid FROM {target} WHERE id = ?", (data[column],)).fetchone()
                data[column] = found[0] if found else None
        return Change(spec.name, uid, data)

    # --- Qabul qilish ------------------------------------------------------

    def apply_remote(self, changes: list[Change], head: int) -> bool:
        """Serverdan kelgan o'zgarishlarni qo'llaydi va `head` ni eslab qoladi.

        Shu orada bu kompyuterda yangi (hali yuborilmagan) o'zgarish paydo bo'lgan bo'lsa, hech narsa
        qilinmaydi va False qaytadi: avval u yuboriladi, keyin qayta olinadi — shunda server bilan bir xil
        tartib saqlanadi.
        """
        self._begin()
        try:
            if self._conn.execute("SELECT 1 FROM sync_outbox LIMIT 1").fetchone():
                self._conn.rollback()
                return False
            self._apply(changes)
            self._conn.execute("UPDATE sync_state SET last_seq = MAX(last_seq, ?)", (head,))
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        return True

    def replace_all(self, changes: list[Change], head: int) -> None:
        """Shu kompyuterdagi ma'lumotlarni serverdagi bilan butunlay almashtiradi (serverga ulanganda).

        Bitta tranzaksiyada: xato bo'lsa, eski ma'lumotlar o'z holicha qoladi.
        """
        self._begin()
        try:
            self._conn.execute("UPDATE sync_state SET tracking = 0")
            for spec in reversed(TABLES):  # avval bog'langan yozuvlar, keyin ular bog'langan qatorlar
                kept = f"uid = '{MAIN_WAREHOUSE_UID}'" if spec.name == "warehouses" else f"NOT ({_shared(spec, 'OLD')})"
                self._conn.execute(f"DELETE FROM {spec.name} AS OLD WHERE NOT ({kept})")
            self._conn.execute("DELETE FROM sync_outbox")
            self._conn.execute("DELETE FROM sync_pending")
            self._apply(changes)
            self._conn.execute("UPDATE sync_state SET tracking = 1, last_seq = ?, republish = 0", (head,))
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise

    def _begin(self) -> None:
        if self._conn.in_transaction:
            self._conn.commit()
        self._conn.execute("BEGIN IMMEDIATE")

    def _apply(self, changes: list[Change]) -> None:
        """Tranzaksiya ichida: triggerlar o'chirib turiladi, bog'langan qatori kelmaganlar kutishga qo'yiladi."""
        tracking = self._state()["tracking"]
        self._conn.execute("UPDATE sync_state SET tracking = 0")
        applier = _Applier(self._conn)
        queue = [Change.from_json(json.loads(row[0])) for row in self._conn.execute("SELECT change FROM sync_pending")]
        self._conn.execute("DELETE FROM sync_pending")
        queue += changes
        waiting: list[Change] = []
        while queue:  # bog'langan qatori shu to'plamda keyinroq kelgan bo'lishi mumkin: yana bir aylanish
            waiting = []
            for change in queue:
                if applier.apply(change):
                    # Shu qatorning kutib turgan eskiroq holati endi kerak emas: yangisi qo'llandi.
                    waiting = [old for old in waiting if (old.table, old.uid) != (change.table, change.uid)]
                else:
                    waiting.append(change)
            if len(waiting) == len(queue):
                break
            queue = waiting
        self._conn.executemany(
            "INSERT INTO sync_pending (change) VALUES (?)", [(json.dumps(change.to_json()),) for change in waiting]
        )
        applier.recalculate()
        self._conn.execute("UPDATE sync_state SET tracking = ?", (tracking,))
