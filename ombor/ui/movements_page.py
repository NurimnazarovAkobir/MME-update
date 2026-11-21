"""Kirim va chiqim sahifasi (ikkalasi uchun bitta sinf)."""

from datetime import date
from typing import Callable

from PySide6.QtWidgets import QComboBox, QDialog, QMessageBox

from ..catalog import display_name
from ..config import CURRENCY
from ..excel_export import LEDGER_HEADERS, ledger_rows
from ..formatting import fmt_compact, fmt_money
from ..i18n import tr
from ..models import MovementDetails, MovementKind
from ..payments import method_title, status_title
from ..session import Session
from ..sites import Sites
from ..warehouse import Warehouse, display_counterparty, has_payment, store_name
from .dialogs import MovementDialog
from .document_dialog import DocumentDialog, can_edit_as_document
from .icons import Glyph
from .labels import KindLabels
from .list_page import ListPage
from .printing import print_waybill
from .widgets import Column, ColumnKind, PeriodFilter, button, confirm, save_to_excel

# Jadvalda bir vaqtda ko'rsatiladigan eng ko'p qator: juda katta bazada ham sahifa tez ochilishi uchun.
MAX_ROWS_SHOWN = 2000
STORE_COLUMN = 2  # bitta ombor bo'lsa, «Ombor» ustuni yashiriladi


def _columns(labels: KindLabels) -> tuple[Column, ...]:
    """Chiqimda xarid narxi o'rniga sotuv va foyda ustunlari bo'ladi (tannarx jami pastda ko'rinadi)."""
    start = (
        Column(tr("Sana"), ColumnKind.DATE, "recent"),
        Column(tr("Hujjat №")),
        Column(tr("Ombor")),
        Column(tr("Mahsulot"), style="strong"),
        Column(tr("Birlik")),
        Column(tr("Miqdor"), ColumnKind.QUANTITY, "strong"),
    )
    if labels.kind is MovementKind.IN:
        money = (Column(tr("Narxi"), ColumnKind.MONEY), Column(tr("Summa"), ColumnKind.MONEY, "strong"))
    else:
        money = (
            Column(tr("Sotuv narxi"), ColumnKind.MONEY),
            Column(tr("Sotuv summasi"), ColumnKind.MONEY, "strong"),
            Column(tr("Foyda"), ColumnKind.MONEY, "signed"),
        )
    end = (
        Column(tr("To'lov turi")),
        Column(tr("Holati"), style="strong"),
        Column(tr("Guruh / kategoriya")),
        Column(labels.person),
        Column(labels.counterparty),
        Column(tr("Belgi")),
        Column(tr("Izoh")),
        Column(tr("Kiritdi")),
    )
    return (*start, *money, *end)


def _marks(movement: MovementDetails) -> str:
    """Yozuvning alohida belgilari: qaytarish, qarzga."""
    marks = (tr("Qaytarish") if movement.is_return else "", tr("Qarzga") if movement.on_credit else "")
    return " · ".join(mark for mark in marks if mark)


def _is_unpaid(movement: MovementDetails) -> bool:
    return has_payment(movement) and (movement.unpaid or movement.on_credit)


def _payment_amount(movement: MovementDetails) -> float:
    return movement.amount if movement.kind is MovementKind.IN else movement.revenue


def _row(movement: MovementDetails) -> tuple:
    m = movement
    start = (m.date, m.doc_number, store_name(m.warehouse_name), m.product_name, m.unit, m.quantity)
    money = (m.price, m.amount) if m.kind is MovementKind.IN else (m.sale_price, m.revenue, m.profit)
    payment = (method_title(m.payment), status_title(_is_unpaid(m))) if has_payment(m) else ("", "")
    group = " / ".join(display_name(name) for name in (m.category, m.subcategory) if name)
    end = (m.person, display_counterparty(m.counterparty), _marks(m), m.note, m.created_by)
    return (*start, *money, *payment, group, *end)


class MovementsPage(ListPage):
    def __init__(self, warehouse: Warehouse, sites: Sites, labels: KindLabels, session: Session):
        # Tahrirlash va o'chirish tugmalari — faqat rahbarda; omborchi faqat qo'shadi.
        is_receipt = labels.kind is MovementKind.IN
        super().__init__(
            labels.title,
            labels.new_action,
            _columns(labels),
            session,
            row_actions=session.can_modify,
            glyph=Glyph.RECEIPT if is_receipt else Glyph.ISSUE,
            subtitle=(
                tr("Omborga kelgan mahsulotlar va xarajatlar")
                if is_receipt
                else tr("Ombordan chiqqan mahsulotlar va sotuvlar")
            ),
        )
        self._warehouse = warehouse
        self._sites = sites
        self._labels = labels
        # Obyektdan qaytgan mahsulot kirim (xarid) emas: u «Vozvrat» bo'limida ko'rsatiladi.
        self._returns = False if is_receipt else None
        self.empty_hint = (
            tr("Hali kirim yo'q. Mahsulot kelganda «Yangi kirim» tugmasini bosing.")
            if is_receipt
            else tr("Hali chiqim yo'q. Mahsulot berilganda «Yangi chiqim» tugmasini bosing.")
        )
        # Hech bir yozuvda to'ldirilmagan bo'lsa, yashiriladigan ustunlar: jadval oynaga sig'ishi uchun.
        titles = [column.title for column in _columns(labels)]
        self._optional_columns = [
            titles.index(title)
            for title in (
                tr("Hujjat №"),
                tr("To'lov turi"),
                tr("Holati"),
                tr("Guruh / kategoriya"),
                tr("Belgi"),
                tr("Izoh"),
            )
        ]
        # «Holati» — rangli yorliq: to'langan yashil, to'lanmagan qizil.
        self.table.set_badges(titles.index(tr("Holati")), {status_title(False): "good", status_title(True): "danger"})
        self._period = PeriodFilter()
        self._period.changed.connect(self.refresh)
        # To'lov bo'yicha filtrlar: masalan, faqat to'lanmaganlar va ularning jami.
        self._status_filter = QComboBox()
        self._status_filter.setToolTip(tr("To'lov holati bo'yicha"))
        self._status_filter.addItem(tr("Barcha holatlar"), None)
        self._status_filter.addItem(status_title(True), True)
        self._status_filter.addItem(status_title(False), False)
        self._method_filter = QComboBox()
        self._method_filter.setToolTip(tr("To'lov turi bo'yicha"))
        for combo in (self._status_filter, self._method_filter):
            combo.currentIndexChanged.connect(self.refresh)
            self.header_tools.addWidget(combo)
        self.header_tools.addWidget(self._period)
        self._recent = self.add_recent_cards(self._period)

        if session.can_modify:
            mark_paid = button(tr("To'landi"), glyph=Glyph.CHECK)
            mark_paid.setToolTip(tr("Tanlangan yozuv (va uning nakladnoyi) to'langan deb belgilanadi; qarzi yopiladi"))
            mark_paid.clicked.connect(self._mark_paid)
            self.toolbar_tools.addWidget(mark_paid)

        self._found: list[MovementDetails] = []  # filtrlardan o'tgan barcha yozuvlar (jadvalga sig'maganlari ham)
        if is_receipt:
            ledger = button(tr("Xarajatlar jadvali"), "excel", Glyph.EXPORT)
            ledger.setToolTip(
                tr("Ro'yxatdagi kirimlarni Excel'dagi xarajatlar jadvali shaklida saqlash: № … «Группа расхода»")
            )
            ledger.clicked.connect(self._export_ledger)
            self.toolbar_tools.addWidget(ledger)

        waybill = button(tr("Nakladnoy"), glyph=Glyph.DOCUMENT)
        waybill.setToolTip(tr("Tanlangan yozuvning hujjatini chop etish (bir xil raqamli yozuvlar birga chiqadi)"))
        waybill.clicked.connect(self._print_waybill)
        self.toolbar_tools.addWidget(waybill)

    def refresh(self) -> None:
        self._fill_methods()
        movements = self._filtered(
            self._warehouse.movements(
                self._labels.kind, self._period.period(), self.search.text(), returns=self._returns
            )
        )
        self._found = movements
        shown = movements[:MAX_ROWS_SHOWN]
        self.table.set_rows(
            [_row(m) for m in shown],
            ids=[m.id for m in shown],
            locked=[index for index, m in enumerate(shown) if not self.session.can_change(m)],
        )
        self.table.hide_empty_columns(self._optional_columns)
        self.table.hide_column(STORE_COLUMN, len(self._warehouse.stores()) < 2)
        self.footer.setText(self._totals(movements))
        self._show_recent()

    def _filtered(self, movements: list[MovementDetails]) -> list[MovementDetails]:
        """Holat va to'lov turi filtrlari bo'yicha."""
        status, method = self._status_filter.currentData(), self._method_filter.currentData()
        if status is not None:
            movements = [m for m in movements if has_payment(m) and _is_unpaid(m) == status]
        if method:
            movements = [m for m in movements if m.payment == method]
        return movements

    def _fill_methods(self) -> None:
        """To'lov turi filtri: shu bo'limda ishlatilgan turlar (tanlangani o'z joyida qoladi)."""
        selected = self._method_filter.currentData()
        self._method_filter.blockSignals(True)
        self._method_filter.clear()
        self._method_filter.addItem(tr("Barcha to'lov turlari"), "")
        for method in self._warehouse.suggestions(self._labels.kind, "payment"):
            self._method_filter.addItem(method_title(method), method)
        self._method_filter.setCurrentIndex(max(self._method_filter.findData(selected), 0))
        self._method_filter.blockSignals(False)
        self._method_filter.setVisible(self._method_filter.count() > 1)

    def _export_ledger(self) -> None:
        """Filtrlangan kirimlar — rahbarning Excel jadvali ustunlarida; bu fayl qayta yuklansa ham tanilinadi."""
        save_to_excel(self, tr("Xarajatlar jadvali"), LEDGER_HEADERS, ledger_rows(self._found))

    def _mark_paid(self) -> None:
        movement_id = self.selected_id()
        if movement_id is None:
            QMessageBox.information(self, tr("To'landi"), tr("Avval jadvaldan yozuvni tanlang."))
            return
        unpaid = [m.id for m in self._warehouse.document(movement_id) if _is_unpaid(m)]
        if not unpaid:
            QMessageBox.information(self, tr("To'landi"), tr("Bu yozuv allaqachon to'langan."))
            return
        question = tr("{0} ta yozuv «To'langan» deb belgilansinmi? Qarzga yozilgan bo'lsa, qarzi ham yopiladi.")
        if confirm(self, tr("To'landi"), question.format(len(unpaid)), tr("Ha, to'landi")):
            self._warehouse.mark_paid(unpaid)
            self.refresh()

    def _show_recent(self) -> None:
        """Bugun, shu hafta va shu oy bo'yicha jami (qidiruv va davr filtridan qat'i nazar)."""
        today = date.today()
        for stat, period_of in self._recent.items():
            found = self._warehouse.movements(self._labels.kind, period_of(today), returns=self._returns)
            amount = sum(m.amount if self._labels.kind is MovementKind.IN else (m.revenue or m.amount) for m in found)
            stat.set_value(fmt_compact(amount), tr("{0}  ·  {1} ta yozuv").format(CURRENCY, len(found)))

    def edit_dialog(self, item_id: int | None) -> QDialog:
        """Yangi yozuv va bir nechta mahsulotli hujjat — nakladnoy oynasida; qolgani — bitta yozuvning to'liq shakli."""
        if item_id is None:
            return DocumentDialog(self._warehouse, self._sites, self._labels, self.session.author, self)
        document = self._changeable_document(item_id)
        if document:
            return DocumentDialog(self._warehouse, self._sites, self._labels, self.session.author, self, document)
        movement = self._warehouse.movement(item_id)
        return MovementDialog(self._warehouse, self._labels, self.session.author, movement, self)

    def ask_delete(self, item_id: int) -> Callable[[], None] | None:
        """Yozuv bir nechta mahsulotli nakladnoyga tegishli bo'lsa, butun nakladnoyni ham o'chirishni taklif qiladi."""
        document = self._changeable_document(item_id)
        if not document:
            return super().ask_delete(item_id)
        box = QMessageBox(
            QMessageBox.Icon.Question,
            tr("O'chirish"),
            tr("Bu yozuv {0} ta mahsulotli nakladnoyga tegishli. Nimani o'chiramiz?").format(len(document)),
            parent=self,
        )
        whole = box.addButton(tr("Butun nakladnoyni"), QMessageBox.ButtonRole.AcceptRole)
        single = box.addButton(tr("Faqat shu qatorni"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Bekor qilish"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is whole:
            return lambda: self._warehouse.delete_document([movement.id for movement in document])
        if box.clickedButton() is single:
            return lambda: self.delete_item(item_id)
        return None

    def _changeable_document(self, item_id: int) -> list[MovementDetails]:
        """Yozuv tegishli nakladnoy — uni butunligicha tahrirlash yoki o'chirish mumkin bo'lsa; aks holda bo'sh."""
        document = self._warehouse.document(item_id)
        if can_edit_as_document(document) and all(self.session.can_change(m) for m in document):
            return document
        return []

    def delete_item(self, item_id: int) -> None:
        self._warehouse.delete_movement(item_id)

    def can_change(self, item_id: int) -> bool:
        return self.session.can_change(self._warehouse.movement(item_id))

    def _print_waybill(self) -> None:
        movement_id = self.selected_id()
        if movement_id is not None:
            print_waybill(self, self._warehouse.document(movement_id), self._labels)

    def _totals(self, movements: list[MovementDetails]) -> str:
        """Jami hamma topilgan yozuvlar bo'yicha hisoblanadi, jadvalga sig'maganlari ham kiradi."""
        count = tr("Jami: {0} ta yozuv").format(len(movements))
        if len(movements) > MAX_ROWS_SHOWN:
            count += tr(" (jadvalda oxirgi {0} tasi; qolganini ko'rish uchun davrni toraytiring)").format(
                MAX_ROWS_SHOWN
            )
        cost = sum(m.amount for m in movements)
        unpaid = sum(_payment_amount(m) for m in movements if _is_unpaid(m))
        # To'lanmagan qismi — oxirida, alohida: «Qarzlar» bilan solishtirish oson bo'lsin.
        unpaid_text = tr("  ·  to'lanmagan: {0} {1}").format(fmt_money(unpaid), CURRENCY) if unpaid else ""
        if self._labels.kind is MovementKind.IN:
            return f"{count}  ·  {fmt_money(cost)} {CURRENCY}{unpaid_text}"
        revenue = sum(m.revenue for m in movements)
        profit = sum(m.profit for m in movements)
        totals = tr("{0}  ·  tannarx {1}  ·  sotuv {2}  ·  foyda {3} {4}").format(
            count, fmt_money(cost), fmt_money(revenue), fmt_money(profit), CURRENCY
        )
        return totals + unpaid_text
