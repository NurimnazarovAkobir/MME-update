"""Dastur sozlamalari: nomlar, fayl yo'llari va doimiy qiymatlar."""

from .i18n import tr
from .paths import BACKUP_DIR, DATA_DIR, DB_PATH  # noqa: F401 — boshqa modullar shu yerdan oladi

APP_NAME = "MME Ombor"

UNITS = (tr("dona"), tr("kg"), tr("tonna"), tr("metr"), tr("m²"), tr("list"), tr("litr"), tr("komplekt"), tr("quti"))
CURRENCY = tr("so'm")
