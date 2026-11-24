"""Dastur sozlamalari: nomlar, fayl yo'llari va doimiy qiymatlar."""

from .i18n import tr
from .paths import BACKUP_DIR, DATA_DIR, DB_PATH  # noqa: F401 — boshqa modullar shu yerdan oladi

APP_NAME = "MME Ombor"
APP_VERSION = "1.38"
# Internetdagi yangilanishlar manzili (https://…/): shu yerda `versiya.txt` va `MME-Ombor.exe` turadi.
# Bo'sh bo'lsa, manzil «Sozlamalar»da kiritiladi. GitHub Releases uchun:
# https://github.com/<foydalanuvchi>/<repo>/releases/latest/download/
DEFAULT_UPDATE_URL = "https://github.com/NurimnazarovAkobir/MME-update/releases/latest/download/"

# Birinchi to'qqiztasi — asl ro'yxat; qolganlari xarajatlar hisobida uchraydiganlari (sayt bilan bir xil nomlar).
UNITS = (
    tr("dona"),
    tr("kg"),
    tr("tonna"),
    tr("metr"),
    tr("m²"),
    tr("list"),
    tr("litr"),
    tr("komplekt"),
    tr("quti"),
    tr("gramm"),
    tr("m³"),
    tr("santimetr"),
    tr("millimetr"),
    tr("kilometr"),
    tr("qop"),
    tr("rulon"),
    tr("pachka"),
    tr("juft"),
    tr("reys"),
    tr("soat"),
    tr("mashina-soat"),
    tr("kun"),
    tr("oy"),
    tr("xizmat"),
)
CURRENCY = tr("so'm")
