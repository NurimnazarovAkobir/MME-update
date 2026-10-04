"""Dastur sozlamalari: nomlar, fayl yo'llari va doimiy qiymatlar."""

from .i18n import tr
from .paths import BACKUP_DIR, DATA_DIR, DB_PATH  # noqa: F401 — boshqa modullar shu yerdan oladi

APP_NAME = "MME Ombor"
APP_VERSION = "1.7"
# Internetdagi yangilanishlar manzili (https://…/): shu yerda `versiya.txt` va `MME-Ombor.exe` turadi.
# Bo'sh bo'lsa, manzil «Sozlamalar»da kiritiladi. GitHub Releases uchun:
# https://github.com/<foydalanuvchi>/<repo>/releases/latest/download/
DEFAULT_UPDATE_URL = "https://github.com/NurimnazarovAkobir/MME-update/releases/latest/download/"

UNITS = (tr("dona"), tr("kg"), tr("tonna"), tr("metr"), tr("m²"), tr("list"), tr("litr"), tr("komplekt"), tr("quti"))
CURRENCY = tr("so'm")
