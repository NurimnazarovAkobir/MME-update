"""Chop etish (oldindan ko'rish oynasi bilan): jadvallar va nakladnoy."""

from datetime import datetime
from html import escape
from typing import Sequence

from PySide6.QtGui import QPageLayout, QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import QWidget

from ..config import APP_NAME, CURRENCY
from ..formatting import fmt_date, fmt_money, fmt_qty
from ..i18n import tr
from ..models import MovementDetails, MovementKind
from ..warehouse import display_counterparty
from .labels import KindLabels
from .widgets import Column, ColumnKind, DataTable

_NUMERIC_KINDS = (ColumnKind.QUANTITY, ColumnKind.MONEY)
# sana va sonlar ikki qatorga bo'linmaydi
_UNBREAKABLE_KINDS = (*_NUMERIC_KINDS, ColumnKind.DATE, ColumnKind.DATETIME)

_STYLE = """
body { font-family: 'Segoe UI'; font-size: 9pt; }
h2 { font-size: 13pt; margin-bottom: 2px; }
p { color: #555555; margin-top: 0; }
table { border-collapse: collapse; width: 100%; }
th { background: #e8ecf1; }
th, td { border: 1px solid #999999; padding: 3px 6px; }
"""
_WAYBILL_STYLE = """
body { font-family: 'Segoe UI'; font-size: 10pt; }
h2 { font-size: 14pt; margin-bottom: 4px; }
p { margin: 2px 0; }
table { border-collapse: collapse; width: 100%; margin-top: 10px; }
th { background: #e8ecf1; }
th, td { border: 1px solid #777777; padding: 4px 7px; }
"""


def table_html(table: DataTable, title: str) -> str:
    """Jadvalning ekrandagi ko'rinishini (saralash tartibi bilan) chop etiladigan HTML ga aylantiradi."""
    columns, rows = table.displayed_data()
    header = "".join(f"<th>{escape(column.title)}</th>" for column in columns)
    body = "".join(f"<tr>{''.join(_cell(column, text) for column, text in zip(columns, row))}</tr>" for row in rows)
    printed = tr("chop etildi: {0}").format(datetime.now().strftime("%d.%m.%Y %H:%M"))
    return (
        f"<html><head><style>{_STYLE}</style></head><body>"
        f"<h2>{escape(title)}</h2><p>{escape(APP_NAME)} · {escape(printed)}</p>"
        f"<table cellspacing='0'><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"
        "</body></html>"
    )


def waybill_html(movements: Sequence[MovementDetails], labels: KindLabels) -> str:
    """Bitta hujjat (nakladnoy): sarlavha, mahsulotlar jadvali, jami va imzo uchun joy.

    Chiqimda sotuv narxi, sotuv bo'lmasa (ichki rasxod) — tannarx ko'rsatiladi.
    """
    first = movements[0]
    title = tr("Kirim nakladnoyi") if first.kind is MovementKind.IN else tr("Chiqim nakladnoyi")
    if first.doc_number:
        title += f" № {first.doc_number}"

    def price_of(movement: MovementDetails) -> float:
        return movement.sale_price if movement.is_sale else movement.price

    lines, total = [], 0.0
    for number, movement in enumerate(movements, start=1):
        amount = movement.quantity * price_of(movement)
        total += amount
        cells = (
            ("right", str(number)),
            ("left", movement.product_name),
            ("left", movement.unit),
            ("right", fmt_qty(movement.quantity)),
            ("right", fmt_money(price_of(movement))),
            ("right", fmt_money(amount)),
        )
        lines.append("<tr>" + "".join(f"<td align='{align}'>{escape(text)}</td>" for align, text in cells) + "</tr>")

    headers = (
        "№",
        tr("Mahsulot"),
        tr("Birlik"),
        tr("Miqdor"),
        tr("Narxi"),
        tr("Summa, {0}").format(CURRENCY),
    )
    details = (
        (tr("Sana"), fmt_date(first.date)),
        (labels.counterparty, display_counterparty(first.counterparty)),
        (labels.person, first.person),
        (tr("Izoh"), first.note if len(movements) == 1 else ""),
    )
    return (
        f"<html><head><style>{_WAYBILL_STYLE}</style></head><body>"
        f"<h2>{escape(title)}</h2>"
        + "".join(f"<p><b>{escape(name)}:</b> {escape(value)}</p>" for name, value in details if value)
        + f"<table cellspacing='0'><thead><tr>{''.join(f'<th>{escape(text)}</th>' for text in headers)}</tr></thead>"
        f"<tbody>{''.join(lines)}"
        f"<tr><td colspan='5' align='right'><b>{escape(tr('Jami'))}</b></td>"
        f"<td align='right'><b>{escape(fmt_money(total))}</b></td></tr></tbody></table>"
        f"<br><br><table cellspacing='0' style='border: none'><tr>"
        f"<td style='border: none'>{escape(tr('Topshirdi'))}: ____________________</td>"
        f"<td style='border: none'>{escape(tr('Qabul qildi'))}: ____________________</td>"
        "</tr></table></body></html>"
    )


def print_table(parent: QWidget, table: DataTable, title: str) -> None:
    _preview(parent, table_html(table, title), title, QPageLayout.Orientation.Landscape)


def print_waybill(parent: QWidget, movements: Sequence[MovementDetails], labels: KindLabels) -> None:
    _preview(parent, waybill_html(movements, labels), tr("Nakladnoy"), QPageLayout.Orientation.Portrait)


def _preview(parent: QWidget, html: str, title: str, orientation: QPageLayout.Orientation) -> None:
    document = QTextDocument()
    document.setHtml(html)
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageOrientation(orientation)
    preview = QPrintPreviewDialog(printer, parent)
    preview.setWindowTitle(tr("Chop etish — {0}").format(title))
    preview.resize(1000, 700)
    preview.paintRequested.connect(document.print_)
    preview.exec()


def _cell(column: Column, text: str) -> str:
    alignment = "right" if column.kind in _NUMERIC_KINDS else "left"
    wrapping = "nowrap" if column.kind in _UNBREAKABLE_KINDS else "normal"
    return f"<td align='{alignment}' style='white-space: {wrapping}'>{escape(text)}</td>"
