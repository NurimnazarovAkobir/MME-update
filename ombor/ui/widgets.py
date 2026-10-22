"""Sahifalar bo'ylab qayta ishlatiladigan umumiy elementlar."""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence

from PySide6.QtCore import QDate, QLocale, QPointF, QRectF, QSize, QStandardPaths, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..excel_export import write_table
from ..formatting import fmt_date, fmt_money, fmt_period, fmt_qty, fmt_range
from ..i18n import tr
from ..models import Granularity, Period
from . import theme
from .icons import Glyph, glyph_icon, icon_label

DATE_DISPLAY_FORMAT = "dd.MM.yyyy"
DATE_INPUT_WIDTH = 130
MAX_NUMBER = 1e12
ROW_HEIGHT = 44
BUTTON_ICON_SIZE = 18
PAGE_SIZES = (10, 25, 50, 100)
DEFAULT_PAGE_SIZE = 25
SPARKLINE_SIZE = (96, 44)
MIN_COLUMN_WIDTH = 44
HEADER_HEIGHT = 52  # ikki qatorli sarlavha sig'adi
CARD_BADGE_SIZE = 40
PAGE_ICON_SIZE = 48
BADGE_HEIGHT, BADGE_PADDING, BADGE_RADIUS = 24, 12, 6
NO_SORTING = -1  # jadval ochilganda qatorlar berilgan tartibda turadi
ACTIONS_TITLE = tr("Amallar")
ACTION_BUTTON_SIZE = (38, 30)


# --- Kichik yordamchilar ---------------------------------------------------


def label(text: str, object_name: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(object_name)
    return widget


def button(text: str, role: str = "", glyph: str = "") -> QPushButton:
    """`role`: 'primary' — asosiy amal, 'danger' — o'chirish, 'segment' — tanlov tugmasi,
    'rowEdit' / 'rowDelete' — jadval qatoridagi kichik tugmalar, 'tile…' — bosh sahifadagi katta tugmalar,
    'page' — sahifalash tugmasi, bo'sh — oddiy. `glyph` — matn oldidagi belgi."""
    widget = QPushButton(text)
    widget.setProperty("role", role)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if glyph:
        colors = theme.palette()
        tints = {
            "primary": "#ffffff",
            "danger": colors.danger,
            "rowDelete": colors.danger,
            "rowEdit": colors.accent,
            "print": colors.violet,
            "excel": colors.good,
        }
        tint = tints.get(role, colors.text)
        widget.setIcon(glyph_icon(glyph, tint))
        widget.setIconSize(QSize(BUTTON_ICON_SIZE, BUTTON_ICON_SIZE))
    return widget


def date_input(day: date | None = None, allow_future: bool = True) -> QDateEdit:
    """`allow_future=False` — bugundan keyingi sanani tanlab bo'lmaydi (yozuv sanalari uchun)."""
    today = date.today()
    widget = QDateEdit(QDate(day or today))
    widget.setCalendarPopup(True)
    widget.setDisplayFormat(DATE_DISPLAY_FORMAT)
    widget.setMinimumWidth(DATE_INPUT_WIDTH)
    if not allow_future:
        widget.setMaximumDate(QDate(max(day or today, today)))  # eski yozuvning sanasi o'z holicha ochiladi
    return widget


class NumberInput(QDoubleSpinBox):
    """Son maydoni, ro'yxatlardagi kabi yoziladi: «1 250 000», «78 714,29» (ortiqcha nollarsiz).

    Kasr qismi vergul bilan ham, nuqta bilan ham yozilaveradi; minglar orasiga oddiy bo'sh joy ham bo'ladi.
    """

    def __init__(self):
        super().__init__()
        self.setLocale(NUMBER_LOCALE)

    def textFromValue(self, value: float) -> str:
        text = self.locale().toString(value, "f", self.decimals())
        decimal_point = self.locale().decimalPoint()
        return text.rstrip("0").rstrip(decimal_point) if decimal_point in text else text

    def validate(self, text: str, position: int):
        return super().validate(_as_locale_number(text), position)

    def valueFromText(self, text: str) -> float:
        return super().valueFromText(_as_locale_number(text))


# Minglar orasida bo'sh joy, kasr — vergul bilan (fmt_qty, fmt_money bilan bir xil).
NUMBER_LOCALE = QLocale(QLocale.Language.Russian, QLocale.Country.Russia)


def _as_locale_number(text: str) -> str:
    """Nuqtani vergulga, oddiy bo'sh joyni NUMBER_LOCALE ning minglar ajratgichiga almashtiradi."""
    return text.replace(".", NUMBER_LOCALE.decimalPoint()).replace(" ", NUMBER_LOCALE.groupSeparator())


def number_input(decimals: int, value: float = 0.0) -> NumberInput:
    widget = NumberInput()
    widget.setDecimals(decimals)
    widget.setRange(0, MAX_NUMBER)
    widget.setGroupSeparatorShown(True)
    widget.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    widget.setValue(value)
    return widget


def suggestion_box(suggestions: Iterable[str], current: str = "") -> QComboBox:
    """Erkin yozish mumkin bo'lgan maydon; avval kiritilgan qiymatlarni taklif qiladi."""
    widget = QComboBox()
    widget.setEditable(True)
    widget.addItems(list(suggestions))
    widget.setCurrentText(current)
    return widget


def confirm(parent: QWidget, title: str, text: str, action_text: str) -> bool:
    box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=parent)
    action = box.addButton(action_text, QMessageBox.ButtonRole.AcceptRole)
    box.addButton(tr("Bekor qilish"), QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is action


def card(*widgets: QWidget) -> QFrame:
    """Oq fonli ramka; ichiga berilgan elementlarni ustma-ust joylaydi."""
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    for widget in widgets:
        layout.addWidget(widget)
    return frame


# --- Ko'rsatkich kartochkasi -----------------------------------------------


class Sparkline(QWidget):
    """Kichik chiziqli diagramma: ko'rsatkichning davr ichidagi o'zgarishi (o'qsiz, raqamsiz)."""

    def __init__(self, color: str):
        super().__init__()
        self._color = QColor(color)
        self._values: list[float] = []
        self.setFixedSize(*SPARKLINE_SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_values(self, values: Sequence[float]) -> None:
        self._values = list(values)
        self.update()

    def paintEvent(self, event) -> None:
        if len(self._values) < 2 or max(self._values) == min(self._values):
            return  # bitta nuqta yoki o'zgarishsiz qator hech narsa aytmaydi
        low, high = min(self._values), max(self._values)
        width, height, margin = self.width(), self.height(), 4
        step = (width - 2 * margin) / (len(self._values) - 1)
        points = [
            QPointF(margin + index * step, height - margin - (value - low) / (high - low) * (height - 2 * margin))
            for index, value in enumerate(self._values)
        ]
        line = QPainterPath(points[0])
        for point in points[1:]:
            line.lineTo(point)
        area = QPainterPath(line)
        area.lineTo(points[-1].x(), height)
        area.lineTo(points[0].x(), height)
        fill = QLinearGradient(0, 0, 0, height)
        top, bottom = QColor(self._color), QColor(self._color)
        top.setAlpha(90)
        bottom.setAlpha(0)
        fill.setColorAt(0, top)
        fill.setColorAt(1, bottom)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillPath(area, fill)
        painter.setPen(
            QPen(self._color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        )
        painter.drawPath(line)


# Kartochka rangi (`tone`) -> palitradagi rang nomi.
_TONE_COLORS = {"Accent": "accent", "Good": "good", "Out": "tile_out", "Warning": "warning", "Violet": "violet"}


class StatCard(QFrame):
    """Bitta asosiy raqam: rangli belgi, sarlavha, qiymat, izoh va (bo'lsa) kichik diagramma.

    `tone` — rang ('Accent', 'Good', 'Out', 'Warning', 'Violet'). `clickable` bo'lsa,
    kartochka bosilganda `clicked` signali chiqadi va o'ngda strelka ko'rinadi.
    """

    clicked = Signal()

    def __init__(self, title: str, glyph: str = "", tone: str = "Accent", clickable: bool = False):
        super().__init__()
        self.setObjectName(f"stat{tone}")
        self._clickable = clickable
        self._value = label("—", "cardValue")
        self._hint = label("", "cardHint")
        self._delta = label("", "cardHint")
        self._spark = Sparkline(getattr(theme.palette(), _TONE_COLORS.get(tone, "accent")))

        top = QHBoxLayout()
        top.setSpacing(12)
        if glyph:
            badge = icon_label(glyph, f"badge{tone}")
            badge.setFixedSize(CARD_BADGE_SIZE, CARD_BADGE_SIZE)
            top.addWidget(badge)
        top.addWidget(label(title, "cardTitle"), stretch=1)
        if clickable:
            self.setProperty("clickable", "true")
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            top.addWidget(icon_label(Glyph.CHEVRON, "chevron"))

        middle = QHBoxLayout()
        middle.addWidget(self._value, stretch=1)
        middle.addWidget(self._spark)
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(self._delta)
        bottom.addWidget(self._hint, stretch=1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(6)
        layout.addLayout(top)
        layout.addLayout(middle)
        layout.addLayout(bottom)

    def set_value(self, value: str, hint: str = "", change: float | None = None, series: Sequence[float] = ()) -> None:
        """`change` — oldingi davrga nisbatan o'zgarish ulushi (0.12 = +12%); None — ko'rsatilmaydi.
        `series` — kichik diagramma uchun qiymatlar qatori."""
        self._value.setText(value)
        self._hint.setText(hint)
        self._spark.set_values(series)
        self._spark.setVisible(bool(series))
        self._delta.setVisible(change is not None)
        if change is not None:
            arrow = "↑" if change >= 0 else "↓"
            self._delta.setText(f"{arrow} {abs(change) * 100:.0f}%")
            self._delta.setObjectName("deltaUp" if change >= 0 else "deltaDown")
            self._delta.style().unpolish(self._delta)
            self._delta.style().polish(self._delta)

    def mouseReleaseEvent(self, event) -> None:
        if self._clickable and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def page_header(glyph: str, title: str, subtitle: str) -> tuple[QHBoxLayout, QHBoxLayout]:
    """Sahifa sarlavhasi: katta belgi, nom va izoh. Ikkinchi qaytgan qator — o'ngdagi tugma va filtrlar uchun."""
    titles = QVBoxLayout()
    titles.setSpacing(0)
    titles.addWidget(label(title, "pageTitle"))
    titles.addWidget(label(subtitle, "subtitle"))
    tools = QHBoxLayout()
    tools.setSpacing(10)
    header = QHBoxLayout()
    header.setSpacing(14)
    icon = icon_label(glyph, "pageIcon")
    icon.setFixedSize(PAGE_ICON_SIZE, PAGE_ICON_SIZE)
    header.addWidget(icon)
    header.addLayout(titles)
    header.addStretch()
    header.addLayout(tools)
    return header, tools


def section_header(glyph: str, title: str) -> QWidget:
    """Kartochka sarlavhasi: belgi va nom."""
    header = QWidget()
    layout = QHBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    layout.addWidget(icon_label(glyph, "iconAccent"))
    layout.addWidget(label(title, "sectionTitle"))
    layout.addStretch()
    return header


# --- Jadval ----------------------------------------------------------------


class ColumnKind(Enum):
    TEXT = "text"
    QUANTITY = "quantity"
    MONEY = "money"
    DATE = "date"
    DATETIME = "datetime"


_FORMATTERS = {
    ColumnKind.TEXT: str,
    ColumnKind.QUANTITY: fmt_qty,
    ColumnKind.MONEY: fmt_money,
    ColumnKind.DATE: fmt_date,
    ColumnKind.DATETIME: lambda moment: f"{moment:%d.%m.%Y %H:%M}",
}
_NUMERIC_KINDS = (ColumnKind.QUANTITY, ColumnKind.MONEY)


@dataclass(frozen=True)
class Column:
    """`style` — katakning ko'rinishi: 'strong' — qalin; 'signed' — musbat yashil, manfiy qizil;
    'recent' — sana bugun, shu hafta yoki shu oyga tegishli bo'lsa, rangli yorliq bo'lib chiziladi."""

    title: str
    kind: ColumnKind = ColumnKind.TEXT
    style: str = ""


class BadgeDelegate(QStyledItemDelegate):
    """Katak matnini rangli yorliq (masalan, yashil «Kirim», to'q sariq «Chiqim») qilib chizadi."""

    def __init__(self, tones: dict[str, str], parent: QWidget):
        """`tones` — matn -> palitradagi rang nomi (masalan {'Kirim': 'good'})."""
        super().__init__(parent)
        self._tones = tones

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        cell = QStyleOptionViewItem(option)
        self.initStyleOption(cell, index)
        text, cell.text = cell.text, ""
        cell.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, cell, painter, cell.widget)  # fon

        color = QColor(getattr(theme.palette(), self._tones.get(text, "muted")))
        font = QFont(cell.font)
        font.setWeight(QFont.Weight.DemiBold)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(font)
        width = painter.fontMetrics().horizontalAdvance(text) + 2 * BADGE_PADDING
        badge = QRectF(cell.rect.left() + 10, cell.rect.center().y() - BADGE_HEIGHT / 2 + 1, width, BADGE_HEIGHT)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.soft(color))
        painter.drawRoundedRect(badge, BADGE_RADIUS, BADGE_RADIUS)
        painter.setPen(color)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index):
        size = super().sizeHint(option, index)
        size.setWidth(size.width() + 2 * BADGE_PADDING)
        return size


# Sananing yaqinligi -> palitradagi rang: kirim/chiqim sahifasidagi «Bugun / Shu hafta / Shu oy»
# kartochkalari ham shu ranglarda.
RECENCY_TONES = {"today": "good", "week": "accent", "month": "violet"}
RECENCY_ROLE = Qt.ItemDataRole.UserRole + 2


def recency(day: date, today: date | None = None) -> str:
    """'today', 'week', 'month' yoki bo'sh (undan eski)."""
    today = today or date.today()
    if day == today:
        return "today"
    if Period.week_of(today).start <= day <= today:
        return "week"
    if (day.year, day.month) == (today.year, today.month):
        return "month"
    return ""


class RecencyDelegate(QStyledItemDelegate):
    """Sana katagini yaqinligiga qarab rangli yorliq qilib chizadi: bugun, shu hafta, shu oy."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        tone = RECENCY_TONES.get(index.data(RECENCY_ROLE))
        if tone is None:
            super().paint(painter, option, index)
            return
        cell = QStyleOptionViewItem(option)
        self.initStyleOption(cell, index)
        text, cell.text = cell.text, ""
        cell.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, cell, painter, cell.widget)  # fon

        color = QColor(getattr(theme.palette(), tone))
        font = QFont(cell.font)
        font.setWeight(QFont.Weight.DemiBold)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(font)
        width = min(painter.fontMetrics().horizontalAdvance(text) + 2 * BADGE_PADDING, cell.rect.width() - 6)
        badge = QRectF(cell.rect.left() + 4, cell.rect.center().y() - BADGE_HEIGHT / 2 + 1, width, BADGE_HEIGHT)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.soft(color))
        painter.drawRoundedRect(badge, BADGE_RADIUS, BADGE_RADIUS)
        painter.setPen(color)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index):
        size = super().sizeHint(option, index)
        size.setWidth(size.width() + 2 * BADGE_PADDING)
        return size


def _shrink(widths: dict[int, int], room: int) -> dict[int, int]:
    """Kengliklarni jami `room` ga sig'adigan qilib qisqartiradi: faqat eng keng ustunlar torayadi.

    Shunday chegara topiladiki, undan keng ustunlar shu chegaragacha qisqaradi, torroqlari esa
    o'z kengligida qoladi — qisqa ustunlar («Birlik», «Turi») uzun izoh tufayli kesilib ketmaydi.
    """
    remaining, left = room, len(widths)
    result: dict[int, int] = {}
    for column, width in sorted(widths.items(), key=lambda item: item[1]):
        result[column] = max(min(width, remaining // left), 1)  # navbatdagi eng tor ustun teng ulushdan oshmaydi
        remaining -= result[column]
        left -= 1
    return result


class DataTable(QTableWidget):
    """Faqat o'qish uchun jadval. Qiymatlar ustun turiga qarab formatlanadi.

    Ustun sarlavhasi bosilsa, butun ro'yxat (hamma sahifalari bilan) shu ustun bo'yicha saralanadi.
    `enable_paging` chaqirilsa, qatorlar sahifalarga bo'lib ko'rsatiladi (`Pager` bilan boshqariladi).
    `row_actions` yoqilsa, har bir qator boshida «tahrirlash» va «o'chirish» tugmalari bo'ladi
    (Delete tugmasi ham tanlangan qatorni o'chirishni so'raydi).
    """

    row_activated = Signal(int)  # ikki marta bosilgan qatorning id si
    edit_requested = Signal(int)
    delete_requested = Signal(int)
    pages_changed = Signal()  # sahifalar soni yoki joriy sahifa o'zgardi

    def __init__(self, columns: Sequence[Column], row_actions: bool = False):
        self._offset = 1 if row_actions else 0  # ma'lumot ustunlaridan oldingi «Amallar» ustuni
        super().__init__(0, len(columns) + self._offset)
        self._columns = tuple(columns)
        self._rows: list[Sequence] = []
        # Har bir qator: (qiymatlar, id, e'tibor talab qiladimi, tugmasizmi) — saralashda birga ko'chadi.
        self._records: list[tuple[Sequence, int | None, bool, bool]] = []
        self._page_size: int | None = None  # None — hamma qatorlar bitta sahifada
        self.empty_text = ""  # jadval bo'sh turganda ko'rsatiladigan matn; bo'sh bo'lsa — umumiy yozuv
        self._page = 0
        self._sort_column: int | None = None
        self._sort_descending = False
        # Asosiy ustunlari ajratilgan jadvalda qolgan matn xiraroq ko'rsatiladi.
        self._dims_plain_text = any(column.style for column in columns)

        titles = [column.title for column in columns]
        self.setHorizontalHeaderLabels([ACTIONS_TITLE, *titles] if row_actions else titles)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)  # uzun matn keyingi qatorga o'tmaydi, oxiri «…» bilan qisqaradi
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)

        header = self.horizontalHeader()
        header.setHighlightSections(False)
        # Har bir ustun o'z mazmunicha keng; hammasi sig'masa — gorizontal aylantirish chiqadi.
        # Ustun kengliklarini `_fit_columns` o'zi belgilaydi: jadval har doim oynaga sig'adi, gorizontal
        # aylantirish yo'q. Joy yetmasa, matnli ustunlar torayadi (to'liq matn — sichqoncha ustida).
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setMinimumSectionSize(1)
        header.setFixedHeight(HEADER_HEIGHT)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header.setSortIndicator(NO_SORTING, Qt.SortOrder.AscendingOrder)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._sort_by)
        for index, column in enumerate(columns):
            # Tor ustunda sarlavha kesilmasdan ikki qatorga bo'linadi.
            self.horizontalHeaderItem(index + self._offset).setTextAlignment(
                self._alignment(column) | Qt.TextFlag.TextWordWrap
            )

        for index, column in enumerate(columns):
            if column.style == "recent":
                self.setItemDelegateForColumn(index + self._offset, RecencyDelegate(self))
        self.itemDoubleClicked.connect(self._emit_activated)

    def set_rows(
        self,
        rows: Sequence[Sequence],
        ids: Sequence[int] = (),
        flagged: Iterable[int] = (),
        locked: Iterable[int] = (),
    ) -> None:
        """`ids` — qatorlarning id lari; `flagged` — e'tibor talab qiladigan qatorlar indekslari;
        `locked` — tahrirlash va o'chirish tugmalari qo'yilmaydigan qatorlar indekslari."""
        flagged, locked = set(flagged), set(locked)
        self._records = [
            (row, ids[index] if ids else None, index in flagged, index in locked) for index, row in enumerate(rows)
        ]
        self._apply_sorting()
        self._page = min(self._page, self.page_count() - 1)
        self._render()

    # --- Sahifalash va saralash ----------------------------------------------

    def enable_paging(self, page_size: int = DEFAULT_PAGE_SIZE) -> None:
        self.set_page_size(page_size)

    def set_page_size(self, page_size: int | None) -> None:
        self._page_size, self._page = page_size, 0
        self._render()

    def page_size(self) -> int | None:
        return self._page_size

    def page(self) -> int:
        return self._page

    def page_count(self) -> int:
        if not self._page_size:
            return 1
        return max((len(self._records) + self._page_size - 1) // self._page_size, 1)

    def total_rows(self) -> int:
        """Hamma sahifalardagi qatorlar soni."""
        return len(self._records)

    def set_page(self, page: int) -> None:
        self._page = min(max(page, 0), self.page_count() - 1)
        self._render()

    def _sort_by(self, section: int) -> None:
        column = section - self._offset
        if column < 0:
            return  # «Amallar» ustuni bo'yicha saralanmaydi
        self._sort_descending = column == self._sort_column and not self._sort_descending
        self._sort_column = column
        self._apply_sorting()
        self._page = 0
        self._render()

    def _apply_sorting(self) -> None:
        """Butun ro'yxatni tanlangan ustunning asl qiymati bo'yicha saralaydi (10 < 9 bo'lib qolmasligi uchun)."""
        if self._sort_column is not None:
            column = self._sort_column

            def key(record):
                value = record[0][column]
                return value.casefold() if isinstance(value, str) else value

            self._records.sort(key=key, reverse=self._sort_descending)
            order = Qt.SortOrder.DescendingOrder if self._sort_descending else Qt.SortOrder.AscendingOrder
            self.horizontalHeader().setSortIndicatorShown(True)
            self.horizontalHeader().setSortIndicator(column + self._offset, order)
        self._rows = [record[0] for record in self._records]

    def _render(self) -> None:
        """Joriy sahifadagi qatorlarni jadvalga yozadi."""
        start = self._page * self._page_size if self._page_size else 0
        shown = self._records[start : start + self._page_size] if self._page_size else self._records
        self.setRowCount(len(shown))
        for row_index, (row, item_id, is_flagged, is_locked) in enumerate(shown):
            if self._offset and item_id is not None:
                self._add_actions(row_index, item_id, is_locked=is_locked)
            for column_index, (column, value) in enumerate(zip(self._columns, row), start=self._offset):
                item = QTableWidgetItem(_FORMATTERS[column.kind](value))
                item.setTextAlignment(self._alignment(column))
                if column.kind is ColumnKind.TEXT and item.text():
                    item.setToolTip(item.text())  # ustun toraytirilganda matn qisqarib ko'rinadi
                if item_id is not None:
                    item.setData(Qt.ItemDataRole.UserRole, item_id)
                self._apply_style(item, column, value)
                if is_flagged:
                    item.setBackground(QColor(theme.palette().warning_row))
                self.setItem(row_index, column_index, item)
        if self._offset:
            # Sahifadagi hech bir qatorda tugma bo'lmasa (masalan, omborchi boshqalar yozuvini ko'rayotganda),
            # bo'sh «Amallar» ustuni ko'rsatilmaydi.
            has_buttons = any(item_id is not None and not is_locked for _, item_id, _, is_locked in shown)
            self.setColumnHidden(0, not has_buttons)
        self._fit_columns()
        self.pages_changed.emit()

    def _apply_style(self, item: QTableWidgetItem, column: Column, value) -> None:
        """Muhim ustunlarni ajratadi: qalin nom va summalar, rangli foyda, yaqin sanalar."""
        if column.style in ("strong", "signed"):
            font = item.font()
            font.setWeight(QFont.Weight.DemiBold)
            item.setFont(font)
        if column.style == "signed" and value:
            colors = theme.palette()
            item.setForeground(QColor(colors.good if value > 0 else colors.danger))
        elif column.style == "recent":
            item.setData(RECENCY_ROLE, recency(value))
        elif self._dims_plain_text and not column.style and column.kind is ColumnKind.TEXT:
            item.setForeground(QColor(theme.palette().muted))  # ikkinchi darajali matn xiraroq

    def set_badges(self, column: int, tones: dict[str, str]) -> None:
        """`column` ustunidagi matnlarni rangli yorliq qilib ko'rsatadi (`tones`: matn -> palitra rangi)."""
        self.setItemDelegateForColumn(column + self._offset, BadgeDelegate(tones, self))

    def hide_column(self, column: int, hidden: bool) -> None:
        """Ma'lumot ustunini (tartib raqami bo'yicha) yashiradi yoki ko'rsatadi."""
        self.setColumnHidden(column + self._offset, hidden)
        self._fit_columns()

    def hide_empty_columns(self, columns: Iterable[int]) -> None:
        """`columns` dagi ustunlardan hech bir qatorda qiymati yo'qlarini yashiradi (joyni tejash uchun)."""
        for column in columns:
            is_empty = not any(str(row[column]).strip() for row in self._rows)
            self.setColumnHidden(column + self._offset, is_empty)
        self._fit_columns()

    def selected_id(self) -> int | None:
        item = self.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item and item.isSelected() else None

    def select_id(self, item_id: int) -> None:
        """Shu id li qatorni tanlaydi; u boshqa sahifada bo'lsa, o'sha sahifani ochadi."""
        ids = [record[1] for record in self._records]
        if item_id not in ids:
            return
        index = ids.index(item_id)
        if self._page_size:
            self.set_page(index // self._page_size)
            index %= self._page_size
        self.selectRow(index)

    def export_data(self) -> tuple[list[str], list[Sequence]]:
        """Ustun nomlari va formatlanmagan qiymatlar — Excelga chiqarish uchun."""
        return [column.title for column in self._columns], self._rows

    def displayed_data(self) -> tuple[list[Column], list[list[str]]]:
        """Ustunlar va formatlangan matnlar, ekrandagi tartibda, hamma sahifalari bilan — chop etish uchun."""
        rows = [[_FORMATTERS[column.kind](value) for column, value in zip(self._columns, row)] for row in self._rows]
        return list(self._columns), rows

    def keyPressEvent(self, event) -> None:
        item_id = self.selected_id()
        if self._offset and event.key() == Qt.Key.Key_Delete and item_id is not None:
            self.delete_requested.emit(item_id)
        else:
            super().keyPressEvent(event)

    def _add_actions(self, row: int, item_id: int, is_locked: bool = False) -> None:
        """Qator boshiga tahrirlash va o'chirish tugmalarini qo'yadi; `is_locked` qatorda katak bo'sh qoladi."""
        holder = QTableWidgetItem("")  # tugmalar ostidagi katak: qator tanlanishi uchun
        holder.setData(Qt.ItemDataRole.UserRole, item_id)
        self.setItem(row, 0, holder)
        if is_locked:
            self.removeCellWidget(row, 0)  # jadval qayta to'ldirilganda oldingi qatorning tugmalari qolmasin
            return

        edit = button("", "rowEdit", Glyph.EDIT)
        edit.setToolTip(tr("Tahrirlash"))
        edit.clicked.connect(lambda: self.edit_requested.emit(item_id))
        delete = button("", "rowDelete", Glyph.DELETE)
        delete.setToolTip(tr("O'chirish"))
        delete.clicked.connect(lambda: self.delete_requested.emit(item_id))

        actions = QWidget()
        layout = QHBoxLayout(actions)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(6)
        for action in (edit, delete):
            action.setFixedSize(*ACTION_BUTTON_SIZE)
            layout.addWidget(action)
        self.setCellWidget(row, 0, actions)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_columns()

    def _fit_columns(self) -> None:
        """Ustun kengliklarini jadval eniga moslaydi — gorizontal aylantirish bo'lmaydi.

        Hammasi sig'sa — har biri o'z mazmunicha, ortgan joy oxirgi ustunga. Sig'masa — son, sana va
        tugmalar ustunlari mazmuni to'liq ko'rinadigan kenglikda qoladi (sarlavhasi ikki qatorga bo'linadi),
        matnli ustunlarning eng uzunlari qisqaradi (to'liq matn — sichqoncha ustida).
        """
        header = self.horizontalHeader()
        visible = [column for column in range(self.columnCount()) if not self.isColumnHidden(column)]
        if not visible:
            return
        content = {column: max(self.sizeHintForColumn(column), MIN_COLUMN_WIDTH) for column in visible}
        for column in visible:
            if self._is_text_column(column) and self._columns[column - self._offset].style:
                # Asosiy ustunning (masalan, «Mahsulot») sarlavhasi ham kesilmasin.
                content[column] = max(content[column], header.sectionSizeHint(column))
        widths = {column: max(content[column], header.sectionSizeHint(column)) for column in visible}
        available = self.viewport().width()
        extra = available - sum(widths.values())
        if extra >= 0:
            # Ortgan joy ma'lumot ustunlari orasida teng bo'linadi: jadval butun enini egallaydi.
            data = [column for column in visible if column >= self._offset] or visible
            for column in data:
                widths[column] += extra // len(data)
            widths[data[-1]] += extra % len(data)
        else:
            flexible = [column for column in visible if self._is_text_column(column)]
            fixed = {
                column: max(content[column], self._header_word_width(column))
                for column in visible
                if column not in flexible
            }
            if self._offset and 0 in fixed:
                fixed[0] = widths[0]  # «Amallar» sarlavhasi kesilmasin
            room = available - sum(fixed.values())
            if flexible and room >= MIN_COLUMN_WIDTH * len(flexible):
                # Matnli ustunlar mazmuniga qarab bo'linadi (sarlavhasi ikki qatorga sig'adi); ortgan joy teng ulashiladi.
                shrunk = _shrink({column: content[column] for column in flexible}, room)
                spare = (room - sum(shrunk.values())) // len(flexible)
                widths = {**fixed, **{column: width + spare for column, width in shrunk.items()}}
            else:
                widths = _shrink(content, available)  # juda tor oyna: eng keng ustunlar torayadi
        for column, width in widths.items():
            header.resizeSection(column, width)

    def _header_word_width(self, column: int) -> int:
        """Sarlavhaning eng uzun so'zi sig'adigan kenglik: ikki qatorga bo'linganda ham so'z kesilmaydi."""
        header = self.horizontalHeader()
        title = self.horizontalHeaderItem(column).text()
        metrics = header.fontMetrics()
        longest = max((metrics.horizontalAdvance(word) for word in title.split()), default=0)
        return header.sectionSizeHint(column) - metrics.horizontalAdvance(title) + longest

    def _is_text_column(self, column: int) -> bool:
        index = column - self._offset
        return index >= 0 and self._columns[index].kind is ColumnKind.TEXT

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.rowCount() == 0:
            painter = QPainter(self.viewport())
            painter.setPen(QColor(theme.palette().muted))
            text = self.empty_text or tr("Hozircha ma'lumot yo'q")
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)

    @staticmethod
    def _alignment(column: Column) -> Qt.AlignmentFlag:
        horizontal = Qt.AlignmentFlag.AlignRight if column.kind in _NUMERIC_KINDS else Qt.AlignmentFlag.AlignLeft
        return horizontal | Qt.AlignmentFlag.AlignVCenter

    def _emit_activated(self, item: QTableWidgetItem) -> None:
        item_id = item.data(Qt.ItemDataRole.UserRole)
        if item_id is not None:
            self.row_activated.emit(item_id)


class Pager(QWidget):
    """Jadval ostidagi panel: nechta qator ko'rsatish va sahifadan sahifaga o'tish."""

    def __init__(self, table: DataTable):
        super().__init__()
        self._table = table
        self._sizes = QComboBox()
        for size in PAGE_SIZES:
            self._sizes.addItem(str(size), size)
        self._sizes.setCurrentIndex(max(self._sizes.findData(table.page_size()), 0))
        self._sizes.currentIndexChanged.connect(lambda: table.set_page_size(self._sizes.currentData()))
        self._previous = button("", "page", Glyph.PREVIOUS)
        self._next = button("", "page", Glyph.NEXT)
        self._previous.clicked.connect(lambda: table.set_page(table.page() - 1))
        self._next.clicked.connect(lambda: table.set_page(table.page() + 1))
        self._position = label("", "pagePosition")
        self._position.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(label(tr("Ko'rsatish:"), "muted"))
        layout.addWidget(self._sizes)
        layout.addStretch()
        for widget in (self._previous, self._position, self._next):
            layout.addWidget(widget)
        table.pages_changed.connect(self._update)
        self._update()

    def _update(self) -> None:
        page, count = self._table.page(), self._table.page_count()
        self._position.setText(f"{page + 1} / {count}")
        self._previous.setEnabled(page > 0)
        self._next.setEnabled(page < count - 1)


def table_card(table: DataTable, paged: bool = True) -> QFrame:
    """Jadvalni kartochka ichiga joylaydi; `paged` bo'lsa, ostiga sahifalash panelini qo'shadi."""
    table.setObjectName("flatTable")
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 10, 14, 12)
    layout.setSpacing(6)
    layout.addWidget(table, stretch=1)
    if paged:
        table.enable_paging()
        layout.addWidget(Pager(table))
    return frame


def export_to_excel(parent: QWidget, table: DataTable, title: str) -> None:
    """Fayl nomini so'raydi, jadvalni saqlaydi va faylni ochadi."""
    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    default_path = Path(documents) / f"{title} {date.today():%d.%m.%Y}.xlsx"
    path, _ = QFileDialog.getSaveFileName(parent, tr("Excelga saqlash"), str(default_path), tr("Excel fayli (*.xlsx)"))
    if not path:
        return
    try:
        write_table(path, title, *table.export_data())
    except OSError:
        QMessageBox.warning(
            parent,
            tr("Saqlab bo'lmadi"),
            tr("Faylni saqlab bo'lmadi. Agar u Excelda ochiq bo'lsa, yoping va qayta urinib ko'ring."),
        )
        return
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


# --- Davr tanlash ----------------------------------------------------------

ALL_TIME = tr("Barcha vaqt")
TODAY, THIS_WEEK, THIS_MONTH = tr("Bugun"), tr("Shu hafta"), tr("Shu oy")
CUSTOM_PERIOD = tr("Tanlangan davr")

_PRESETS = {
    ALL_TIME: lambda today: Period(),
    TODAY: Period.day_of,
    THIS_WEEK: Period.week_of,
    THIS_MONTH: Period.month_of,
    tr("O'tgan oy"): Period.previous_month_of,
    tr("Shu yil"): Period.year_of,
}


class PeriodFilter(QWidget):
    """Tayyor davrlar ro'yxati; 'Tanlangan davr'da sanalarni qo'lda kiritish mumkin."""

    changed = Signal()

    def __init__(self, default: str = ALL_TIME):
        super().__init__()
        self._presets = QComboBox()
        self._presets.addItems([*_PRESETS, CUSTOM_PERIOD])
        self._presets.setCurrentText(default)
        self._start = date_input()
        self._dash = label("—")
        self._end = date_input()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for widget in (self._presets, self._start, self._dash, self._end):
            layout.addWidget(widget)

        self._apply_preset()
        self._presets.currentTextChanged.connect(self._on_preset_changed)
        self._start.dateChanged.connect(lambda _: self.changed.emit())
        self._end.dateChanged.connect(lambda _: self.changed.emit())

    def select(self, preset: str) -> None:
        """Tayyor davrni nomi bo'yicha tanlaydi (masalan, «Bugun»)."""
        self._presets.setCurrentText(preset)

    def period(self) -> Period:
        name = self._presets.currentText()
        if name == CUSTOM_PERIOD:
            return Period(self._start.date().toPython(), self._end.date().toPython())
        return _PRESETS[name](date.today())

    def _on_preset_changed(self) -> None:
        self._apply_preset()
        self.changed.emit()

    def _apply_preset(self) -> None:
        """Sana maydonlari faqat 'Tanlangan davr'da ko'rinadi; oldingi davr sanalari ularda qoladi."""
        is_custom = self._presets.currentText() == CUSTOM_PERIOD
        for widget in (self._start, self._dash, self._end):
            widget.setVisible(is_custom)
        if is_custom:
            return
        period = self.period()
        if period.start and period.end:
            _set_dates_silently(self._start, self._end, period)


def _set_dates_silently(start: QDateEdit, end: QDateEdit, period: Period) -> None:
    """Sana maydonlarini `dateChanged` signalini chiqarmasdan to'ldiradi."""
    for edit, day in ((start, period.start), (end, period.end)):
        edit.blockSignals(True)
        edit.setDate(QDate(day))
        edit.blockSignals(False)


class PeriodNavigator(QWidget):
    """Hisobot davri: «Kunlik / Haftalik / Oylik / Yillik» va ◀ ▶ bilan oldingi-keyingi davr.

    «Boshqa davr»da sanalar qo'lda kiritiladi.
    """

    changed = Signal()

    def __init__(self, default: Granularity = Granularity.MONTH):
        super().__init__()
        self._granularity: Granularity | None = default
        self._anchor = date.today()  # tanlangan davr ichidagi kun

        self._modes = QButtonGroup(self)
        segment_bar = QFrame()
        segment_bar.setObjectName("segmentBar")
        modes = QHBoxLayout(segment_bar)
        modes.setContentsMargins(4, 4, 4, 4)
        modes.setSpacing(2)
        for granularity in (*Granularity, None):
            mode = button(granularity.value if granularity else tr("Boshqa davr"), "segment")
            mode.setCheckable(True)
            mode.setChecked(granularity is default)
            mode.clicked.connect(lambda _=False, granularity=granularity: self._set_granularity(granularity))
            self._modes.addButton(mode)
            modes.addWidget(mode)

        self._previous = button("", "page", Glyph.PREVIOUS)
        self._previous.setToolTip(tr("Oldingi davr"))
        self._previous.clicked.connect(lambda: self._step(-1))
        self._next = button("", "page", Glyph.NEXT)
        self._next.setToolTip(tr("Keyingi davr"))
        self._next.clicked.connect(lambda: self._step(1))
        self._title = label("", "periodTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setMinimumWidth(150)
        self._calendar = icon_label(Glyph.CALENDAR)
        self._start = date_input()
        self._dash = label("—")
        self._end = date_input()
        self._start.dateChanged.connect(lambda _: self.changed.emit())
        self._end.dateChanged.connect(lambda _: self.changed.emit())

        period_bar = QFrame()
        period_bar.setObjectName("segmentBar")
        period = QHBoxLayout(period_bar)
        period.setContentsMargins(4, 4, 8, 4)
        period.setSpacing(6)
        for widget in (self._previous, self._calendar, self._title, self._next, self._start, self._dash, self._end):
            period.addWidget(widget)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(segment_bar)
        layout.addWidget(period_bar)
        layout.addStretch()
        self._update_view()

    def granularity(self) -> Granularity | None:
        """Tanlangan davr turi; «Boshqa davr»da — None."""
        return self._granularity

    def period(self) -> Period:
        if self._granularity is None:
            return Period(self._start.date().toPython(), self._end.date().toPython())
        return self._granularity.period_of(self._anchor)

    def previous_period(self) -> Period | None:
        """Tanlangan davrdan bitta oldingi davr (solishtirish uchun); «Boshqa davr»da — None."""
        if self._granularity is None:
            return None
        return self._granularity.period_of(self._granularity.shift(self._anchor, -1))

    def title(self) -> str:
        if self._granularity is None:
            period = self.period()
            return fmt_range(period.start, period.end)
        return fmt_period(self._granularity, self._anchor)

    def _set_granularity(self, granularity: Granularity | None) -> None:
        if granularity is None:
            _set_dates_silently(self._start, self._end, self.period())
        self._granularity = granularity
        self._update_view()
        self.changed.emit()

    def _step(self, direction: int) -> None:
        self._anchor = self._granularity.shift(self._anchor, direction)
        self._update_view()
        self.changed.emit()

    def _update_view(self) -> None:
        is_custom = self._granularity is None
        for widget in (self._previous, self._calendar, self._title, self._next):
            widget.setVisible(not is_custom)
        for widget in (self._start, self._dash, self._end):
            widget.setVisible(is_custom)
        self._title.setText(self.title())
