"""Mahsulot kartochkasi: qoldig'i, butun harakat tarixi va qaysi obyektlarda turgani."""

from PySide6.QtWidgets import QDialog, QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from ..config import CURRENCY
from ..formatting import fmt_money, fmt_qty
from ..i18n import tr
from ..models import MovementDetails, MovementKind
from ..sites import Sites
from ..warehouse import Warehouse, display_counterparty, store_name
from .icons import Glyph
from .printing import print_table
from .widgets import Column, ColumnKind, DataTable, StatCard, button, card, export_to_excel, label

CARD_SIZE = (980, 640)
KIND_COLUMN = 1
# Harakat turi va uning rangli yorlig'i (palitradagi rang nomi).
RECEIPT, ISSUE, SALE, SITE_RETURN, SUPPLIER_RETURN = (
    tr("Kirim"),
    tr("Chiqim"),
    tr("Sotuv"),
    tr("Vozvrat"),
    tr("Qaytarildi"),
)
KIND_TONES = {RECEIPT: "good", ISSUE: "tile_out", SALE: "accent", SITE_RETURN: "violet", SUPPLIER_RETURN: "warning"}

_MOVEMENT_COLUMNS = (
    Column(tr("Sana"), ColumnKind.DATE, "recent"),
    Column(tr("Turi")),
    Column(tr("Hujjat №")),
    Column(tr("Miqdor"), ColumnKind.QUANTITY, "strong"),
    Column(tr("Narxi"), ColumnKind.MONEY),
    Column(tr("Summa"), ColumnKind.MONEY),
    Column(tr("Kimdan / kimga"), style="strong"),
    Column(tr("Ombor")),
    Column(tr("Kiritdi")),
)
_SITE_COLUMNS = (
    Column(tr("Obyekt"), style="strong"),
    Column(tr("Berilgan"), ColumnKind.QUANTITY),
    Column(tr("Qaytgan"), ColumnKind.QUANTITY),
    Column(tr("Obyektda"), ColumnKind.QUANTITY, "strong"),
)


def movement_kind(movement: MovementDetails) -> str:
    """Harakatning odamga tushunarli turi: kirim, chiqim, sotuv, obyektdan vozvrat yoki yetkazib beruvchiga qaytarish."""
    if movement.kind is MovementKind.IN:
        return SITE_RETURN if movement.is_return else RECEIPT
    if movement.is_return:
        return SUPPLIER_RETURN
    return SALE if movement.is_sale else ISSUE


def _row(movement: MovementDetails) -> tuple:
    m = movement
    price = m.sale_price if m.is_sale else m.price
    return (
        m.date,
        movement_kind(m),
        m.doc_number,
        m.quantity,
        price,
        m.quantity * price,
        display_counterparty(m.counterparty),
        store_name(m.warehouse_name),
        m.created_by,
    )


class ProductCardDialog(QDialog):
    """Bitta mahsulot haqida hamma narsa: ko'rsatkichlar, harakatlar tarixi va obyektlardagi qoldig'i."""

    def __init__(self, warehouse: Warehouse, sites: Sites, product_id: int, parent: QWidget | None = None):
        super().__init__(parent)
        product = warehouse.product(product_id)
        self.setWindowTitle(tr("Mahsulot kartochkasi — {0}").format(product.name))
        self.resize(*CARD_SIZE)
        movements = warehouse.movements(product_id=product_id)
        at_sites = [row for row in sites.products(product_id=product_id) if row.issued or row.returned]
        unit = product.unit

        details = [unit]
        if product.min_stock:
            details.append(tr("minimal qoldiq {0}").format(fmt_qty(product.min_stock)))
        if product.barcode:
            details.append(tr("shtrix-kod {0}").format(product.barcode))
        if product.note:
            details.append(product.note)

        received = sum(m.quantity for m in movements if m.kind is MovementKind.IN and not m.is_return)
        issued = sum(m.quantity for m in movements if m.kind is MovementKind.OUT and not m.is_return)
        stats = (
            (tr("Qoldiq"), Glyph.BOX, "Accent", f"{fmt_qty(product.stock)} {unit}", product.status.value),
            (
                tr("O'rtacha narx"),
                Glyph.MONEY,
                "Good",
                fmt_money(product.average_price),
                tr("{0}  ·  qiymati {1}").format(CURRENCY, fmt_money(product.value)),
            ),
            (tr("Jami kelgan"), Glyph.RECEIPT, "Good", f"{fmt_qty(received)} {unit}", tr("vozvratsiz")),
            (tr("Jami berilgan"), Glyph.ISSUE, "Out", f"{fmt_qty(issued)} {unit}", ""),
            (
                tr("Obyektlarda"),
                Glyph.PIN,
                "Violet",
                f"{fmt_qty(sum(row.remaining for row in at_sites))} {unit}",
                tr("{0} ta obyekt").format(len(at_sites)),
            ),
        )
        cards = QHBoxLayout()
        cards.setSpacing(12)
        for title, glyph, tone, value, hint in stats:
            stat = StatCard(title, glyph, tone)
            stat.set_value(value, hint)
            cards.addWidget(stat)

        self._history = DataTable(_MOVEMENT_COLUMNS)
        self._history.set_badges(KIND_COLUMN, KIND_TONES)
        self._history.set_rows([_row(m) for m in movements])
        self._history.empty_text = tr("Bu mahsulot bo'yicha hali yozuv yo'q")
        self._site_table = DataTable(_SITE_COLUMNS)
        self._site_table.set_rows([(row.site, row.issued, row.returned, row.remaining) for row in at_sites])
        self._site_table.empty_text = tr("Bu mahsulot hali hech bir obyektga berilmagan")
        self._tabs = QTabWidget()
        for table, title in (
            (self._history, tr("Harakatlar ({0})").format(len(movements))),
            (self._site_table, tr("Obyektlarda ({0})").format(len(at_sites))),
        ):
            table.setObjectName("flatTable")
            self._tabs.addTab(table, title)

        title = tr("{0} — kartochka").format(product.name)
        print_button = button(tr("Chop etish"), "print", Glyph.PRINT)
        print_button.clicked.connect(lambda: print_table(self, self._tabs.currentWidget(), title))
        excel = button(tr("Excelga chiqarish"), "excel", Glyph.EXPORT)
        excel.clicked.connect(lambda: export_to_excel(self, self._tabs.currentWidget(), title))
        close = button(tr("Yopish"), "primary")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(print_button)
        buttons.addWidget(excel)
        buttons.addStretch()
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label(product.name, "pageTitle"))
        layout.addWidget(label("  ·  ".join(details), "subtitle"))
        layout.addLayout(cards)
        layout.addWidget(card(self._tabs), stretch=1)
        layout.addLayout(buttons)
