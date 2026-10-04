"""Dastur sozlamalari: bazadagi kalit-qiymat juftliklari."""

import sqlite3


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
