"""Mahsulotlar ro'yxatini Excel (.xlsx) faylidan o'qish."""

from pathlib import Path
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils.exceptions import InvalidFileException

from .errors import WarehouseError
from .i18n import tr
from .models import ImportedProduct

# Fayldagi ustunlar tartibi; birinchi qator — sarlavha.
COLUMNS = (tr("Nomi"), tr("Birlik"), tr("Minimal qoldiq"), tr("Qoldiq"), tr("Narxi"))
SAMPLE_ROWS = (
    ("Truba 40x40x2", tr("metr"), 100, 250, 32000),
    ("Benzin AI-92", tr("litr"), 200, 0, 0),
)
DEFAULT_UNIT = tr("dona")


def write_template(path: Path | str) -> None:
    """To'ldirish uchun namuna fayl yozadi."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = tr("Mahsulotlar")
    sheet.append(COLUMNS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in SAMPLE_ROWS:
        sheet.append(row)
    for column in "ABCDE":
        sheet.column_dimensions[column].width = 20
    workbook.save(path)


def read_products(path: Path | str) -> list[ImportedProduct]:
    """Birinchi varaqni o'qiydi; nomi bo'sh qatorlar o'tkazib yuboriladi."""
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except (InvalidFileException, BadZipFile, OSError, KeyError, ValueError) as error:
        raise WarehouseError(tr("Faylni o'qib bo'lmadi. Excel (.xlsx) faylini tanlang.")) from error

    try:
        rows = workbook.active.iter_rows(min_row=2, max_col=len(COLUMNS), values_only=True)
        products = [_to_product(row, number) for number, row in enumerate(rows, start=2) if _has_name(row)]
    finally:
        workbook.close()
    if not products:
        raise WarehouseError(tr("Faylda mahsulot topilmadi. Ro'yxat 2-qatordan, «Nomi» ustunidan boshlanishi kerak."))
    return products


def _has_name(row: tuple) -> bool:
    return bool(row) and row[0] is not None and bool(str(row[0]).strip())


def _to_product(row: tuple, row_number: int) -> ImportedProduct:
    name, unit, min_stock, stock, price = (*row, *[None] * len(COLUMNS))[: len(COLUMNS)]
    return ImportedProduct(
        name=str(name).strip(),
        unit=str(unit).strip() if unit else DEFAULT_UNIT,
        min_stock=_number(min_stock, row_number, tr("Minimal qoldiq")),
        stock=_number(stock, row_number, tr("Qoldiq")),
        price=_number(price, row_number, tr("Narxi")),
    )


def _number(value, row_number: int, column: str) -> float:
    if value is None or value == "":
        return 0.0
    try:
        number = float(str(value).replace(" ", "").replace(",", "."))
    except ValueError:
        raise WarehouseError(tr("{0}-qator, «{1}» ustuni: «{2}» son emas.").format(row_number, column, value)) from None
    if number < 0:
        raise WarehouseError(tr("{0}-qator, «{1}» ustuni: manfiy son bo'lishi mumkin emas.").format(row_number, column))
    return number
