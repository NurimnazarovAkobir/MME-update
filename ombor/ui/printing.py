"""Jadvallarni chop etish (oldindan ko'rish oynasi bilan)."""

from datetime import datetime
from html import escape

from PySide6.QtGui import QPageLayout, QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import QWidget

from ..config import APP_NAME
from ..i18n import tr
from .widgets import Column, ColumnKind, DataTable

_NUMERIC_KINDS = (ColumnKind.QUANTITY, ColumnKind.MONEY)
_UNBREAKABLE_KINDS = (*_NUMERIC_KINDS, ColumnKind.DATE)  # sana va sonlar ikki qatorga bo'linmaydi

_STYLE = """
body { font-family: 'Segoe UI'; font-size: 9pt; }
h2 { font-size: 13pt; margin-bottom: 2px; }
p { color: #555555; margin-top: 0; }
table { border-collapse: collapse; width: 100%; }
th { background: #e8ecf1; }
th, td { border: 1px solid #999999; padding: 3px 6px; }
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


def print_table(parent: QWidget, table: DataTable, title: str) -> None:
    document = QTextDocument()
    document.setHtml(table_html(table, title))
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    preview = QPrintPreviewDialog(printer, parent)
    preview.setWindowTitle(tr("Chop etish — {0}").format(title))
    preview.resize(1000, 700)
    preview.paintRequested.connect(document.print_)
    preview.exec()


def _cell(column: Column, text: str) -> str:
    alignment = "right" if column.kind in _NUMERIC_KINDS else "left"
    wrapping = "nowrap" if column.kind in _UNBREAKABLE_KINDS else "normal"
    return f"<td align='{alignment}' style='white-space: {wrapping}'>{escape(text)}</td>"
