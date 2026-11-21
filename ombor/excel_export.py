"""Jadvallarni Excel (.xlsx) fayliga chiqarish."""

from pathlib import Path
from typing import Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import payments
from .i18n import tr
from .models import MovementDetails
from .units import russian_unit

NUMBER_FORMAT = "#,##0.###"
DATE_FORMAT = "DD.MM.YYYY"
HEADER_FILL = PatternFill("solid", start_color="DCE6F2")
MAX_COLUMN_WIDTH = 50
# Rahbarning Excel'dagi xarajatlar jadvali ustunlari — aynan shunday (rus tilida), shu fayl qayta yuklansa ham tanilsin.
LEDGER_HEADERS = (
    "№",
    "дата",
    "Наименование расхода",
    "ед изм",
    "кол-во",
    "цена",
    "сумма",
    "вид оплаты",
    "статус",
    "Группа расхода",
)


def write_table(path: Path | str, title: str, headers: Sequence[str], rows: Sequence[Sequence]) -> None:
    """Sarlavha, ustun nomlari va qatorlardan iborat bitta varaqli fayl yozadi."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = tr("Hisobot")

    sheet.append([title])
    sheet["A1"].font = Font(bold=True, size=14)
    sheet.append([])
    sheet.append(list(headers))
    header_row = sheet.max_row
    for cell in sheet[header_row]:
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center")

    for row in rows:
        sheet.append(list(row))
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, (int, float)):
                cell.number_format = NUMBER_FORMAT
            elif cell.is_date:
                cell.number_format = DATE_FORMAT

    for index, header in enumerate(headers, start=1):
        longest = max([len(str(header)), *(len(str(row[index - 1])) for row in rows)])
        sheet.column_dimensions[get_column_letter(index)].width = min(longest + 4, MAX_COLUMN_WIDTH)
    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)

    workbook.save(path)


def ledger_rows(movements: Sequence[MovementDetails]) -> list[tuple]:
    """Kirimlar xarajatlar jadvali ko'rinishida (`LEDGER_HEADERS`): sana tartibida, raqamlangan, rus tilida."""
    ordered = sorted(movements, key=lambda m: (m.date, m.id or 0))
    return [
        (
            number,
            m.date,
            m.product_name,
            russian_unit(m.unit),
            m.quantity,
            round(m.price, 2),
            round(m.amount, 2),
            payments.method_russian(m.payment),
            payments.status_russian(m.unpaid or m.on_credit),
            m.category,  # guruhning ruscha nomi saqlanadi (catalog.py)
        )
        for number, m in enumerate(ordered, start=1)
    ]
