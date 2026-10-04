"""Zaxira nusxa: qo'lda saqlash, avtomatik kunlik nusxalar va zaxiradan tiklash."""

import shutil
from datetime import date, datetime
from pathlib import Path

from .database import prepare
from .driver import sqlite3
from .errors import WarehouseError
from .i18n import tr
from .migrations import SCHEMA_VERSION
from .settings import Settings

REQUIRED_TABLES = {"products", "movements"}
# Tiklashda joriy holicha qoladigan jadvallar: eski zaxira dasturni eski yoki
# noma'lum parol bilan qulflab qo'ymasligi kerak.
PRESERVED_TABLES = ("settings", "users")
EXTRA_FOLDER_KEY = "backup_folder"
AUTO_FILE_PATTERN = "ombor-????-??-??.db"
AUTO_COPIES_KEPT = 30


def copy_before_upgrade(db_path: Path, folder: Path) -> Path | None:
    """Baza eski versiyada bo'lsa, yangi versiyaga o'tkazishdan oldin faylning nusxasini saqlaydi.

    Bazaga ulanishdan (ya'ni o'tkazishdan) oldin chaqiriladi. Nusxa olingan bo'lsa, uning yo'lini qaytaradi.
    """
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    if version >= SCHEMA_VERSION:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"yangilashdan-oldin-v{version}.db"
    shutil.copy2(db_path, target)
    return target


class Backup:
    def __init__(self, conn: sqlite3.Connection, auto_folder: Path):
        """`auto_folder` — avtomatik nusxalar har doim yoziladigan papka."""
        self._conn = conn
        self._settings = Settings(conn)
        self.auto_folder = auto_folder

    # --- Qo'lda ------------------------------------------------------------

    def save_to(self, path: Path | str) -> None:
        target = sqlite3.connect(path)
        try:
            self._conn.backup(target)
        finally:
            target.close()

    def restore_from(self, path: Path | str) -> None:
        """Mahsulot va yozuvlarni zaxira fayldagilar bilan almashtiradi; foydalanuvchilar va sozlamalar qoladi."""
        preserved = {table: self._dump(table) for table in PRESERVED_TABLES}
        source = sqlite3.connect(path)
        try:
            tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if not REQUIRED_TABLES <= tables:
                raise WarehouseError(tr("Bu fayl ombor dasturining zaxira nusxasi emas."))
            source.backup(self._conn)
        except sqlite3.DatabaseError as error:
            raise WarehouseError(tr("Faylni o'qib bo'lmadi: u zaxira nusxa emas yoki buzilgan.")) from error
        finally:
            source.close()
        prepare(self._conn)
        with self._conn:
            for table, rows in preserved.items():
                self._conn.execute(f"DELETE FROM {table}")
                for row in rows:
                    placeholders = ", ".join("?" * len(row))
                    self._conn.execute(
                        f"INSERT INTO {table} ({', '.join(row.keys())}) VALUES ({placeholders})", tuple(row)
                    )

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
