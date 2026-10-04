"""Ma'lumotlar fayllarining joyi.

Alohida modulda: til o'rnatilishidan oldin (bazadan tilni o'qish uchun) kerak bo'ladi,
shuning uchun bu yerda tarjima qilinadigan matn bo'lmasligi kerak.
"""

import os
from pathlib import Path

# Papka nomi o'zgartirilmaydi: mavjud foydalanuvchilarning ma'lumotlari shu yerda.
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "MetallMontajExpert"
DB_PATH = DATA_DIR / "ombor.db"
BACKUP_DIR = DATA_DIR / "zaxira"  # avtomatik zaxira nusxalar
