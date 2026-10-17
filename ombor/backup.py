"""Zaxira nusxa: qo'lda saqlash, avtomatik kunlik nusxalar va zaxiradan tiklash."""

import shutil
from datetime import date, datetime
from pathlib import Path

from . import catalog
from .database import open_raw, prepare, schema_version
from .driver import sqlite3
from .errors import WarehouseError
from .i18n import tr
from .migrations import SCHEMA_VERSION
from .replication import FOLDER_STATE_TABLES, Replica
from .settings import Settings
from .vault import KEY_SUFFIX, Vault

REQUIRED_TABLES = {"products", "movements"}
# Tiklashda joriy holicha qoladigan jadvallar: eski zaxira dasturni eski yoki noma'lum parol bilan qulflab
# qo'ymasligi kerak; umumiy papka holati (qaysi fayllar o'qilgani, vaqt belgilari) ham eskirmasligi kerak.
PRESERVED_TABLES = ("settings", "users", *FOLDER_STATE_TABLES)
EXTRA_FOLDER_KEY = "backup_folder"
AUTO_FILE_PATTERN = "ombor-????-??-??.db"
AUTO_COPIES_KEPT = 30


def copy_before_upgrade(db_path: Path, folder: Path, key: str | None = None) -> Path | None:
    """Baza eski versiyada bo'lsa, yangi versiyaga o'tkazishdan oldin faylning nusxasini saqlaydi.

    Bazaga ulanishdan (ya'ni o'tkazishdan) oldin chaqiriladi; `key` — shifrlangan baza kaliti.
    Nusxa olingan bo'lsa, uning yo'lini qaytaradi.
    """
    if not db_path.exists():
        return None
    conn = open_raw(db_path, key)
    try:
        version = schema_version(conn)
    finally:
        conn.close()
    if version >= SCHEMA_VERSION:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"yangilashdan-oldin-v{version}.db"
    shutil.copy2(db_path, target)
    return target


def _check_tables(source: sqlite3.Connection) -> None:
    tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not REQUIRED_TABLES <= tables:
        raise WarehouseError(tr("Bu fayl ombor dasturining zaxira nusxasi emas."))


class Backup:
    def __init__(self, conn: sqlite3.Connection, auto_folder: Path, vault: Vault | None = None):
        """`auto_folder` — avtomatik nusxalar har doim yoziladigan papka.

        Baza shifrlangan bo'lsa (`vault`), nusxalar ham shu kalit bilan shifrlanadi va
        har birining yoniga kalit fayli (`.kalit`) qo'yiladi.
        """
        self._conn = conn
        self._settings = Settings(conn)
        self._vault = vault if vault is not None and vault.unlocked else None
        self.auto_folder = auto_folder

    @property
    def _key(self) -> str | None:
        return self._vault.key if self._vault else None

    # --- Qo'lda ------------------------------------------------------------

    def save_to(self, path: Path | str) -> None:
        Path(path).unlink(missing_ok=True)  # eski nusxa boshqa kalit bilan yozilgan bo'lishi mumkin
        target = open_raw(path, self._key)
        try:
            self._conn.backup(target)
        finally:
            target.close()
        if self._vault:
            self._vault.copy_key_file(Path(path).with_suffix(KEY_SUFFIX))

    def restore_from(self, path: Path | str) -> None:
        """Mahsulot va yozuvlarni zaxira fayldagilar bilan almashtiradi; foydalanuvchilar va sozlamalar qoladi.

        Markaziy server bilan sinxronlash yoqilgan bo'lsa, tiklangan holat serverga ham yuboriladi
        (boshqa kompyuterlarda ham shunday bo'ladi).
        """
        preserved = {table: self._dump(table) for table in PRESERVED_TABLES}
        was_synced = Replica(self._conn).enabled
        converted = Path(str(path) + ".shifrlangan")  # ochiq nusxani shifrlangan bazaga tiklashda kerak bo'ladi
        try:
            source = self._open_source(Path(path), converted)
            try:
                source.backup(self._conn)
            finally:
                source.close()
        except sqlite3.DatabaseError as error:
            raise WarehouseError(tr("Faylni o'qib bo'lmadi: u zaxira nusxa emas yoki buzilgan.")) from error
        finally:
            converted.unlink(missing_ok=True)
        prepare(self._conn)
        catalog.load(self._conn)
        with self._conn:
            for table, rows in preserved.items():
                self._conn.execute(f"DELETE FROM {table}")
                for row in rows:
                    placeholders = ", ".join("?" * len(row))
                    self._conn.execute(
                        f"INSERT INTO {table} ({', '.join(row.keys())}) VALUES ({placeholders})", tuple(row)
                    )
        if was_synced:
            Replica(self._conn).mark_restored()

    def _open_source(self, path: Path, converted: Path) -> sqlite3.Connection:
        """Zaxira faylni joriy baza bilan bir xil kalitda ochadi.

        Shifrlangan bazaga ochiq (shifrlash yoqilishidan oldingi) nusxa tiklanayotgan bo'lsa,
        u avval `converted` fayliga shu kalit bilan ko'chiriladi.
        """
        source = open_raw(path, self._key)
        try:
            _check_tables(source)
            return source
        except sqlite3.DatabaseError:
            source.close()
            if self._key is None:
                raise
        plain = open_raw(path)
        try:
            _check_tables(plain)
            converted.unlink(missing_ok=True)
            plain.execute(f"ATTACH DATABASE ? AS copy KEY \"x'{self._key}'\"", (str(converted),))
            plain.execute("SELECT sqlcipher_export('copy')")
            plain.execute(f"PRAGMA copy.user_version = {schema_version(plain)}")
            plain.execute("DETACH DATABASE copy")
        finally:
            plain.close()
        return open_raw(converted, self._key)

    # --- Avtomatik ---------------------------------------------------------

    @property
    def extra_folder(self) -> Path | None:
        """Qo'shimcha papka (masalan, fleshka yoki boshqa disk); tanlanmagan bo'lsa — None."""
        folder = self._settings.get(EXTRA_FOLDER_KEY)
        return Path(folder) if folder else None

    @extra_folder.setter
    def extra_folder(self, folder: Path | None) -> None:
        self._settings.set(EXTRA_FOLDER_KEY, str(folder) if folder else "")

    def run_automatic(self, today: date | None = None) -> list[Path]:
        """Bugungi nusxani har bir papkaga yozadi (bor bo'lsa — yangilaydi), eskilarini tozalaydi.

        Yetib bo'lmaydigan papka (masalan, fleshka chiqarib olingan) jim o'tkazib yuboriladi.
        Yozilgan fayllar ro'yxatini qaytaradi.
        """
        name = f"ombor-{today or date.today():%Y-%m-%d}.db"
        written = []
        for folder in filter(None, (self.auto_folder, self.extra_folder)):
            try:
                folder.mkdir(parents=True, exist_ok=True)
                self.save_to(folder / name)
                for old in sorted(folder.glob(AUTO_FILE_PATTERN))[:-AUTO_COPIES_KEPT]:
                    old.unlink()
                    old.with_suffix(KEY_SUFFIX).unlink(missing_ok=True)
            except (OSError, sqlite3.Error):
                continue
            written.append(folder / name)
        return written

    def last_automatic(self, folder: Path) -> datetime | None:
        """`folder` dagi eng oxirgi avtomatik nusxa qachon yozilgani."""
        try:
            times = [path.stat().st_mtime for path in folder.glob(AUTO_FILE_PATTERN)]
        except OSError:
            return None
        return datetime.fromtimestamp(max(times)) if times else None

    def _dump(self, table: str) -> list[sqlite3.Row]:
        return self._conn.execute(f"SELECT * FROM {table}").fetchall()
