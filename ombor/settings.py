"""Dastur sozlamalari: bazadagi kalit-qiymat juftliklari."""

from .driver import sqlite3

FIRM_NAME_KEY = "firm_name"  # dastur sarlavhasida ko'rinadigan ombor (firma) nomi; hamma kompyuterlar uchun bitta
MAX_FIRM_NAME = 40


class Settings:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def get(self, key: str, default: str = "") -> str:
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def firm_name(self, default: str) -> str:
        """Rahbar bergan ombor nomi; berilmagan bo'lsa — `default` (dastur nomi)."""
        return self.get(FIRM_NAME_KEY).strip() or default

    def set_firm_name(self, name: str) -> str:
        """Ombor nomini saqlaydi (bo'sh nom — dastur nomiga qaytish); saqlangan nomni qaytaradi."""
        name = " ".join(name.split())[:MAX_FIRM_NAME]
        self.set(FIRM_NAME_KEY, name)
        return name
