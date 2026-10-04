"""Dastur tili: o'zbekcha (asosiy) va ruscha.

Koddagi matnlar o'zbek tilida yoziladi va `tr()` ga o'raladi; ruscha tarjimalar
translations_ru.py da. Til dastur ishga tushganda, boshqa modullar yuklanishidan
oldin o'rnatiladi (main.py ga qarang), shuning uchun tilni almashtirish dasturni
qayta ochishni talab qiladi.
"""

import sqlite3
from pathlib import Path

UZBEK, RUSSIAN = "uz", "ru"
LANGUAGES = {UZBEK: "O'zbekcha", RUSSIAN: "Русский"}
LANGUAGE_KEY = "language"  # sozlamalar jadvalidagi kalit

_language = UZBEK
_catalog: dict[str, str] = {}


def language() -> str:
    return _language


def set_language(code: str) -> None:
    """Tilni o'rnatadi; noma'lum kod berilsa — o'zbekcha."""
    global _language, _catalog
    if code == RUSSIAN:
        from .translations_ru import TRANSLATIONS

        _language, _catalog = RUSSIAN, TRANSLATIONS
    else:
        _language, _catalog = UZBEK, {}


def tr(text: str) -> str:
    """Matnning tanlangan tildagi ko'rinishi; tarjimasi bo'lmasa — o'zi."""
    return _catalog.get(text, text)


def stored_language(db_path: Path) -> str:
    """Bazada saqlangan til. Baza hali yo'q yoki eski bo'lsa — o'zbekcha."""
    if not db_path.exists():
        return UZBEK
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (LANGUAGE_KEY,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return UZBEK
    return row[0] if row and row[0] in LANGUAGES else UZBEK
