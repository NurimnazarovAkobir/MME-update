"""Shu kompyuterning shaxsiy sozlamalari: til, fon va baza joyi.

Bazada emas, alohida faylda turadi: baza tarmoqda umumiy yoki shifrlangan bo'lishi mumkin,
bu sozlamalar esa dasturga kirishdan oldin kerak va har bir kompyuterda o'ziniki.
"""

import json
from pathlib import Path

from .paths import DATA_DIR_KEY, DB_NAME, LOCAL_DIR, read_prefs


class LocalPrefs:
    """Kalit-qiymat sozlamalari (`Settings` bilan bir xil ko'rinishda); `path` berilmasa — faqat xotirada."""

    def __init__(self, path: Path | None = None):
        self._path = path
        self._values = read_prefs(path) if path else {}

    def get(self, key: str, default: str = "") -> str:
        return self._values.get(key) or default

    def set(self, key: str, value: str) -> None:
        self._values[key] = value
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._values, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- Baza joyi -----------------------------------------------------------

    @property
    def data_dir(self) -> Path:
        """Baza turgan papka: tanlanmagan bo'lsa — shu kompyuterdagi odatiy joy."""
        return Path(self.get(DATA_DIR_KEY) or LOCAL_DIR)

    @property
    def uses_shared_folder(self) -> bool:
        return bool(self.get(DATA_DIR_KEY))

    def use_folder(self, folder: Path | None) -> None:
        """Bazani `folder` dan ochadigan qiladi (None — odatiy joyga qaytish). Dastur qayta ochilgach kuchga kiradi."""
        self.set(DATA_DIR_KEY, str(folder) if folder else "")

    @staticmethod
    def has_database(folder: Path) -> bool:
        return (folder / DB_NAME).is_file()
