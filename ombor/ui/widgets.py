"""Sahifalar bo'ylab qayta ishlatiladigan umumiy elementlar."""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence

from PySide6.QtCore import QDate, QRectF, QStandardPaths, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter
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
from .icons import Glyph, icon_label

DATE_DISPLAY_FORMAT = "dd.MM.yyyy"
DATE_INPUT_WIDTH = 130
MAX_NUMBER = 1e12
ROW_HEIGHT = 38
MIN_COLUMN_WIDTH = 44
HEADER_HEIGHT = 52  # ikki qatorli sarlavha sig'adi
CARD_BADGE_SIZE = 44
BADGE_HEIGHT, BADGE_PADDING, BADGE_RADIUS = 24, 12, 6
NO_SORTING = -1  # jadval ochilganda qatorlar berilgan tartibda turadi
ACTIONS_TITLE = tr("Amallar")
ACTION_BUTTON_SIZE = (38, 30)


# --- Kichik yordamchilar ---------------------------------------------------


def label(text: str, object_name: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(object_name)
    return widget


def button(text: str, role: str = "") -> QPushButton:
    """`role`: 'primary' — asosiy amal, 'danger' — o'chirish, 'segment' — tanlov tugmasi,
    'rowEdit' / 'rowDelete' — jadval qatoridagi kichik tugmalar, 'tile…' — bosh sahifadagi katta tugmalar,
    bo'sh — oddiy."""
    widget = QPushButton(text)
    widget.setProperty("role", role)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
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
    """Son maydoni: «25,000» ming deb o'qilmasligi uchun ortiqcha nollarni ko'rsatmaydi."""

    def textFromValue(self, value: float) -> str:
        text = self.locale().toString(value, "f", self.decimals())
        decimal_point = self.locale().decimalPoint()
        return text.rstrip("0").rstrip(decimal_point) if decimal_point in text else text


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


class StatCard(QFrame):
    """Bitta asosiy raqam: belgi, sarlavha, qiymat va izoh.

    `tone` — belgi rangi ('Accent', 'Good', 'Out', 'Warning'). `clickable` bo'lsa,
    kartochka bosilganda `clicked` signali chiqadi va o'ngda strelka ko'rinadi.
    """

    clicked = Signal()

    def __init__(self, title: str, glyph: str = "", tone: str = "Accent", clickable: bool = False):
        super().__init__()
        self.setObjectName("card")
        self._clickable = clickable
        self._value = label("—", "cardValue")
        self._hint = label("", "cardHint")

        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(label(title, "cardTitle"))
        texts.addWidget(self._value)
        texts.addWidget(self._hint)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)
        if glyph:
            badge = icon_label(glyph, f"badge{tone}")
            badge.setFixedSize(CARD_BADGE_SIZE, CARD_BADGE_SIZE)
            layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(texts, stretch=1)
        if clickable:
            self.setProperty("clickable", "true")
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.addWidget(icon_label(Glyph.CHEVRON, "chevron"))

    def set_value(self, value: str, hint: str = "") -> None:
        self._value.setText(value)
        self._hint.setText(hint)

    def mouseReleaseEvent(self, event) -> None:
        if self._clickable and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


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
    title: str
    kind: ColumnKind = ColumnKind.TEXT


class _SortableItem(QTableWidgetItem):
    """Katak: ekrandagi matn bo'yicha emas, asl qiymat bo'yicha saralanadi (10 < 9 bo'lib qolmasligi uchun)."""

    def __init__(self, text: str, value):
        super().__init__(text)
        self._sort_key = value.casefold() if isinstance(value, str) else value

    def __lt__(self, other: "_SortableItem") -> bool:
        return self._sort_key < other._sort_key


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

    Ustun sarlavhasi bosilsa, jadval shu ustun bo'yicha saralanadi.
    `row_actions` yoqilsa, har bir qator boshida «tahrirlash» va «o'chirish» tugmalari bo'ladi
    (Delete tugmasi ham tanlangan qatorni o'chirishni so'raydi).
    """

    row_activated = Signal(int)  # ikki marta bosilgan qatorning id si
    edit_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, columns: Sequence[Column], row_actions: bool = False):
        self._offset = 1 if row_actions else 0  # ma'lumot ustunlaridan oldingi «Amallar» ustuni
        super().__init__(0, len(columns) + self._offset)
        self._columns = tuple(columns)
        self._rows: list[Sequence] = []

        titles = [column.title for column in columns]
        self.setHorizontalHeaderLabels([ACTIONS_TITLE, *titles] if row_actions else titles)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
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
        for index, column in enumerate(columns):
            # Tor ustunda sarlavha kesilmasdan ikki qatorga bo'linadi.
            self.horizontalHeaderItem(index + self._offset).setTextAlignment(
                self._alignment(column) | Qt.TextFlag.TextWordWrap
            )

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
        self._rows = list(rows)
        flagged, locked = set(flagged), set(locked)
        # To'ldirish paytida saralash o'chiriladi, aks holda qatorlar yozilayotganda joyidan siljiydi.
        self.setSortingEnabled(False)
        self.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            if self._offset and ids:
                self._add_actions(row_index, ids[row_index], is_locked=row_index in locked)
            for column_index, (column, value) in enumerate(zip(self._columns, row), start=self._offset):
                item = _SortableItem(_FORMATTERS[column.kind](value), value)
                item.setTextAlignment(self._alignment(column))
                if column.kind is ColumnKind.TEXT and item.text():
                    item.setToolTip(item.text())  # ustun toraytirilganda matn qisqarib ko'rinadi
                if ids:
                    item.setData(Qt.ItemDataRole.UserRole, ids[row_index])
                if row_index in flagged:
                    item.setBackground(QColor(theme.palette().warning_row))
                self.setItem(row_index, column_index, item)
        self.setSortingEnabled(True)
        self._fit_columns()

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

    def export_data(self) -> tuple[list[str], list[Sequence]]:
        """Ustun nomlari va formatlanmagan qiymatlar — Excelga chiqarish uchun."""
        return [column.title for column in self._columns], self._rows

    def displayed_data(self) -> tuple[list[Column], list[list[str]]]:
        """Ustunlar va ekrandagi matnlar, ekrandagi tartibda — chop etish uchun."""
        rows = [
            [self.item(row, column).text() for column in range(self._offset, self.columnCount())]
            for row in range(self.rowCount())
        ]
        return list(self._columns), rows

    def keyPressEvent(self, event) -> None:
        item_id = self.selected_id()
        if self._offset and event.key() == Qt.Key.Key_Delete and item_id is not None:
            self.delete_requested.emit(item_id)
        else:
            super().keyPressEvent(event)

    def _add_actions(self, row: int, item_id: int, is_locked: bool = False) -> None:
        """Qator boshiga tahrirlash va o'chirish tugmalarini qo'yadi; `is_locked` qatorda katak bo'sh qoladi."""
        holder = _SortableItem("", 0)  # tugmalar ostidagi katak: qator tanlanishi va saralash uchun
        holder.setData(Qt.ItemDataRole.UserRole, item_id)
        self.setItem(row, 0, holder)
        if is_locked:
            self.removeCellWidget(row, 0)  # jadval qayta to'ldirilganda oldingi qatorning tugmalari qolmasin
            return

        edit = button("✎", "rowEdit")
        edit.setToolTip(tr("Tahrirlash"))
        edit.clicked.connect(lambda: self.edit_requested.emit(item_id))
        delete = button("✕", "rowDelete")
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
        widths = {column: max(content[column], header.sectionSizeHint(column)) for column in visible}
        available = self.viewport().width()
        extra = available - sum(widths.values())
        if extra >= 0:
            widths[visible[-1]] += extra
        else:
            flexible = [column for column in visible if self._is_text_column(column)]
            fixed = {column: content[column] for column in visible if column not in flexible}
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

    def _is_text_column(self, column: int) -> bool:
        index = column - self._offset
        return index >= 0 and self._columns[index].kind is ColumnKind.TEXT

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.rowCount() == 0:
            painter = QPainter(self.viewport())
            painter.setPen(QColor(theme.palette().muted))
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, tr("Hozircha ma'lumot yo'q"))

    @staticmethod
    def _alignment(column: Column) -> Qt.AlignmentFlag:
        horizontal = Qt.AlignmentFlag.AlignRight if column.kind in _NUMERIC_KINDS else Qt.AlignmentFlag.AlignLeft
        return horizontal | Qt.AlignmentFlag.AlignVCenter

    def _emit_activated(self, item: QTableWidgetItem) -> None:
        item_id = item.data(Qt.ItemDataRole.UserRole)
        if item_id is not None:
            self.row_activated.emit(item_id)


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
CUSTOM_PERIOD = tr("Tanlangan davr")

_PRESETS = {
    ALL_TIME: lambda today: Period(),
    tr("Bugun"): Period.day_of,
    tr("Shu hafta"): Period.week_of,
    tr("Shu oy"): Period.month_of,
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
        modes = QHBoxLayout()
        modes.setSpacing(0)
        for granularity in (*Granularity, None):
            mode = button(granularity.value if granularity else tr("Boshqa davr"), "segment")
            mode.setCheckable(True)
            mode.setChecked(granularity is default)
            mode.clicked.connect(lambda _=False, granularity=granularity: self._set_granularity(granularity))
            self._modes.addButton(mode)
            modes.addWidget(mode)

        self._previous = button("◀")
        self._previous.setToolTip(tr("Oldingi davr"))
        self._previous.clicked.connect(lambda: self._step(-1))
        self._next = button("▶")
        self._next.setToolTip(tr("Keyingi davr"))
        self._next.clicked.connect(lambda: self._step(1))
        self._title = label("", "periodTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setMinimumWidth(200)
        self._start = date_input()
        self._dash = label("—")
        self._end = date_input()
        self._start.dateChanged.connect(lambda _: self.changed.emit())
        self._end.dateChanged.connect(lambda _: self.changed.emit())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(modes)
        layout.addSpacing(12)
        for widget in (self._previous, self._title, self._next, self._start, self._dash, self._end):
            layout.addWidget(widget)
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
        for widget in (self._previous, self._title, self._next):
            widget.setVisible(not is_custom)
        for widget in (self._start, self._dash, self._end):
            widget.setVisible(is_custom)
        self._title.setText(self.title())
