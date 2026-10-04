"""Ma'lumotlar fayllarining joyi.

Alohida modulda: til o'rnatilishidan oldin kerak bo'ladi, shuning uchun bu yerda
tarjima qilinadigan matn bo'lmasligi kerak.

`LOCAL_DIR` — har doim shu kompyuterning o'zida: shaxsiy sozlamalar (til, fon, baza joyi)
va avtomatik zaxira nusxalar. `DATA_DIR` — baza turgan papka: odatda o'sha joyning o'zi,
tarmoqda ishlashda esa hamma kompyuterlar uchun umumiy papka.
"""

import json
import os
from pathlib import Path

# Papka nomi o'zgartirilmaydi: mavjud foydalanuvchilarning ma'lumotlari shu yerda.
LOCAL_DIR = Path(os.environ.get("APPDATA", Path.home())) / "MetallMontajExpert"
PREFS_PATH = LOCAL_DIR / "sozlama.json"
DATA_DIR_KEY = "data_dir"
DB_NAME = "ombor.db"


def read_prefs(path: Path = PREFS_PATH) -> dict:
    """Shu kompyuterning shaxsiy sozlamalari; fayl yo'q yoki buzilgan bo'lsa — bo'sh."""
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return values if isinstance(values, dict) else {}


DATA_DIR = Path(read_prefs().get(DATA_DIR_KEY) or LOCAL_DIR)
DB_PATH = DATA_DIR / DB_NAME
BACKUP_DIR = LOCAL_DIR / "zaxira"  # avtomatik zaxira nusxalar (baza tarmoqda bo'lsa ham shu kompyuterda)
