"""Dasturning ko'rinishi: tanlanadigan fonlar (palitralar) va umumiy uslub."""

import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from ..i18n import tr

BRAND_COLOR = "#2a78d6"  # dastur belgisi; fon almashtirilganda o'zgarmaydi
ARROW_SIZE = 20


@dataclass(frozen=True)
class Palette:
    title: str  # sozlamalarda ko'rinadigan nom
    page: str
    surface: str
    border: str
    control_border: str
    text: str
    muted: str
    disabled: str
    disabled_bg: str
    hover: str
    header: str
    alt_row: str
    selection: str
    warning_row: str
    sidebar: str
    sidebar_hover: str
    sidebar_text: str
    accent: str
    accent_dark: str
    danger: str
    good: str
    warning: str
    tooltip: str
    tile_out: str  # «Chiqim» katta tugmasi (diagrammadagi chiqim rangiga yaqin)
    tile_out_dark: str
    # Diagramma: kirim va chiqim har doim shu ikki rangda.
    series: tuple[str, str]
    grid: str
    axis: str
    violet: str = "#8b5cf6"  # to'rtinchi ko'rsatkich rangi


_LIGHT = Palette(
    title=tr("Och"),
    page="#f4f5f7",
    surface="#ffffff",
    border="#e1e3e8",
    control_border="#cfd4dc",
    text="#1b1f24",
    muted="#6b7280",
    disabled="#a0a6b0",
    disabled_bg="#eceef1",
    hover="#eef1f5",
    header="#eef1f5",
    alt_row="#f8f9fb",
    selection="#d6e6fa",
    warning_row="#fdf1e7",
    sidebar="#1f2a37",
    sidebar_hover="#2b3a4d",
    sidebar_text="#cbd5e1",
    accent="#2a78d6",
    accent_dark="#1c5cab",
    danger="#d03b3b",
    good="#0c8a0c",
    warning="#b97a00",
    tooltip="#1b1f24",
    tile_out="#c8541f",
    tile_out_dark="#a84418",
    series=("#2a78d6", "#eb6834"),
    grid="#e1e0d9",
    axis="#c3c2b7",
)

PALETTES = {
    "light": _LIGHT,
    "dark": Palette(
        title=tr("To'q ko'k (standart)"),
        page="#0b1424",
        surface="#111e33",
        border="#1f3150",
        control_border="#2a3f63",
        text="#e8eefb",
        muted="#9fb0cc",
        disabled="#566684",
        disabled_bg="#0f1a2d",
        hover="#172a47",
        header="#0f1b30",
        alt_row="#0f1a2d",
        selection="#1b3a66",
        warning_row="#3d2a17",
        sidebar="#0a1322",
        sidebar_hover="#13233d",
        sidebar_text="#b4c2dc",
        accent="#1f7af5",
        accent_dark="#1763cc",
        danger="#ff6b6b",
        good="#2fbf71",
        warning="#f5a524",
        tooltip="#000000",
        tile_out="#f07020",
        tile_out_dark="#d25f15",
        series=("#2f8cff", "#ff7a2f"),
        grid="#1c2c47",
        axis="#2f4468",
    ),
    "blue": Palette(
        title=tr("Ko'k"),
        page="#e9f0fa",
        surface="#ffffff",
        border="#d3deee",
        control_border="#bccbe0",
        text="#14233a",
        muted="#5b6b82",
        disabled="#9aa8bc",
        disabled_bg="#e4ebf5",
        hover="#e3ecf8",
        header="#dfe9f7",
        alt_row="#f5f8fd",
        selection="#cfe0f8",
        warning_row="#fdf1e7",
        sidebar="#14345f",
        sidebar_hover="#1f4780",
        sidebar_text="#c5d5ec",
        accent="#2468c2",
        accent_dark="#1a529c",
        danger="#d03b3b",
        good="#0c8a0c",
        warning="#b97a00",
        tooltip="#14233a",
        tile_out="#c8541f",
        tile_out_dark="#a84418",
        series=("#2a78d6", "#eb6834"),
        grid="#dbe3ef",
        axis="#b5c3d8",
    ),
    "green": Palette(
        title=tr("Yashil"),
        page="#eaf3ed",
        surface="#ffffff",
        border="#d2e3d8",
        control_border="#b9cfc1",
        text="#16261d",
        muted="#5a6e62",
        disabled="#9bada2",
        disabled_bg="#e3ede6",
        hover="#e2efe6",
        header="#dcebe1",
        alt_row="#f5faf6",
        selection="#cde8d6",
        warning_row="#fdf1e7",
        sidebar="#173b2a",
        sidebar_hover="#225239",
        sidebar_text="#c4dccd",
        accent="#1c7f52",
        accent_dark="#14633f",
        danger="#d03b3b",
        good="#0c8a0c",
        warning="#b97a00",
        tooltip="#16261d",
        tile_out="#c8541f",
        tile_out_dark="#a84418",
        series=("#2a78d6", "#eb6834"),
        grid="#dbe8df",
        axis="#b4cabb",
    ),
    "warm": Palette(
        title=tr("Iliq (krem)"),
        page="#f5efe4",
        surface="#fffdf9",
        border="#e4d9c6",
        control_border="#d3c5ad",
        text="#2a2118",
        muted="#7a6a57",
        disabled="#b3a591",
        disabled_bg="#eee6d8",
        hover="#efe6d6",
        header="#ece2d0",
        alt_row="#faf6ee",
        selection="#f0dcc0",
        warning_row="#fbe6d2",
        sidebar="#3a2c20",
        sidebar_hover="#4f3d2d",
        sidebar_text="#dccdb9",
        accent="#a85a14",
        accent_dark="#874710",
        danger="#c23a2e",
        good="#3d7a1c",
        warning="#a86a00",
        tooltip="#2a2118",
        tile_out="#c8541f",
        tile_out_dark="#a84418",
        series=("#2a78d6", "#eb6834"),
        grid="#e6dccb",
        axis="#c9bca6",
    ),
}
DEFAULT_THEME = "dark"
SOFT_RATIO = 0.18  # «yumshoq» fon: asosiy rangning shuncha qismi, qolgani — kartochka foni

_active = PALETTES[DEFAULT_THEME]


def palette() -> Palette:
    """Hozir tanlangan fon ranglari (o'zi chiziladigan elementlar shundan oladi)."""
    return _active


def apply(app: QApplication, name: str) -> None:
    """Fonni butun dasturga qo'llaydi; noma'lum nom berilsa — standart fon."""
    global _active
    _active = PALETTES.get(name, PALETTES[DEFAULT_THEME])
    colors = {key: value for key, value in asdict(_active).items() if isinstance(value, str)}
    colors["accent_light"] = QColor(colors["accent"]).lighter(128).name()
    for tone in ("accent", "good", "warning", "danger", "tile_out", "violet"):
        colors[f"{tone}_soft"] = soft(colors[tone]).name()
    arrow = _save_stroke(f"arrow-{name}", _ARROW_POINTS, _active.muted)
    check = _save_stroke("check", _CHECK_POINTS, "#ffffff")
    app.setStyleSheet(_STYLESHEET.format(arrow=arrow, check=check, **colors))


def soft(color: str | QColor) -> QColor:
    """Rangning kartochka foniga aralashtirilgan och varianti — yorliq va belgi fonlari uchun."""
    tint, base = QColor(color).getRgb()[:3], QColor(_active.surface).getRgb()[:3]
    return QColor(*(round(t * SOFT_RATIO + b * (1 - SOFT_RATIO)) for t, b in zip(tint, base)))


_ARROW_POINTS = ((3, 7), (10, 14), (17, 7))  # ro'yxat strelkasi
_CHECK_POINTS = ((4, 10), (8, 14), (16, 6))  # belgilash katagidagi «✓»


def _save_stroke(name: str, points: tuple[tuple[int, int], ...], color: str) -> str:
    """Chiziqli belgini (strelka, «✓») chizib, vaqtinchalik faylga saqlaydi (uslublar faqat fayldan o'qiydi)."""
    pixmap = QPixmap(ARROW_SIZE, ARROW_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawPolyline([QPointF(x, y) for x, y in points])
    painter.end()
    path = Path(tempfile.gettempdir()) / f"mme-ombor-{name}.png"
    pixmap.save(str(path), "PNG")
    return str(path).replace("\\", "/")


_STYLESHEET = """
* {{ font-family: "Segoe UI"; font-size: 11pt; color: {text}; }}
QMainWindow, QDialog, QScrollArea, #page {{ background: {page}; }}

#sidebar {{ background: transparent; border: none; outline: none; }}
#sidebar::item {{ color: {sidebar_text}; padding: 11px 10px; border-radius: 8px; margin: 2px 0; }}
#sidebar::item:hover {{ background: {sidebar_hover}; }}
#sidebar::item:selected {{ background: {accent}; color: white; font-weight: 600; }}
#sidebarPanel {{ background: {sidebar}; border-right: 1px solid {border}; }}
#logo {{ background: {accent}; color: white; font-size: 11pt; font-weight: 700; border-radius: 10px; }}
#brand {{ color: white; font-size: 13pt; font-weight: 600; }}
#firm {{ color: {sidebar_text}; font-size: 9pt; }}

#icon {{ font-family: "Segoe MDL2 Assets"; font-size: 11pt; color: {muted}; }}
#iconAccent {{ font-family: "Segoe MDL2 Assets"; font-size: 15pt; color: {accent}; }}
#chevron {{ font-family: "Segoe MDL2 Assets"; font-size: 10pt; color: {accent}; }}
#badgeAccent, #badgeGood, #badgeOut, #badgeWarning {{
    font-family: "Segoe MDL2 Assets"; font-size: 15pt; border-radius: 10px;
}}
#badgeAccent {{ color: {accent}; background: {accent_soft}; }}
#badgeGood {{ color: {good}; background: {good_soft}; }}
#badgeOut {{ color: {tile_out}; background: {tile_out_soft}; }}
#badgeWarning {{ color: {warning}; background: {warning_soft}; }}
#statusGood, #statusAccent {{
    font-family: "Segoe MDL2 Assets"; font-size: 24pt; border-radius: 32px;
}}
#statusGood {{ color: {good}; background: {good_soft}; }}
#statusAccent {{ color: {accent}; background: {accent_soft}; }}
#statusTitle {{ font-size: 15pt; font-weight: 600; }}
QProgressBar {{ background: {header}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}
#subtitle {{ color: {muted}; font-size: 10pt; }}
#dateText {{ font-size: 11pt; }}

#pageTitle {{ font-size: 18pt; font-weight: 600; }}
#sectionTitle {{ font-size: 12pt; font-weight: 600; }}
#muted {{ color: {muted}; }}
#error {{ color: {danger}; font-weight: 600; }}
#syncStatus {{ color: {sidebar_text}; font-size: 9pt; }}
#framelessRoot {{ background: {sidebar}; }}
#framelessRoot[framed="true"] {{ border: 1px solid {border}; }}
#titleBar {{ background: {sidebar}; }}
QPushButton#captionButton, QPushButton#closeButton {{
    background: transparent; border: none; border-radius: 0; padding: 0; color: {sidebar_text};
    font-family: "Segoe MDL2 Assets"; font-size: 8pt;
}}
QPushButton#captionButton:hover {{ background: {sidebar_hover}; color: #ffffff; }}
QPushButton#closeButton:hover {{ background: #e81123; color: #ffffff; }}
QDialog#lockScreen {{ background: {page}; }}
#lockTitle {{ font-size: 16pt; }}
#lockFieldTitle {{ color: {accent}; font-weight: 600; }}
QLineEdit#lockInput, QLineEdit#lockInput:focus {{
    background: transparent; border: none; border-bottom: 2px solid {accent}; border-radius: 0;
    padding: 6px 2px; font-size: 13pt;
}}
QPushButton#lockSubmit {{ font-size: 11pt; }}
#total {{ font-size: 12pt; font-weight: 600; }}

#card {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; }}
#notice {{ background: {accent_soft}; border: none; border-bottom: 1px solid {accent}; }}
#noticeText {{ font-weight: 600; }}
#card[clickable="true"]:hover {{ border-color: {accent}; }}
#cardTitle {{ color: {muted}; font-size: 10pt; }}
#cardValue {{ font-size: 19pt; font-weight: 600; }}
#cardHint {{ color: {muted}; font-size: 9pt; }}

QPushButton {{
    background: {surface}; border: 1px solid {control_border}; border-radius: 6px; padding: 8px 16px;
}}
QPushButton:hover {{ background: {hover}; }}
QPushButton:disabled {{ color: {disabled}; }}
QPushButton[role="primary"] {{ background: {accent}; border-color: {accent}; color: white; font-weight: 600; }}
QPushButton[role="primary"]:hover {{ background: {accent_dark}; }}
QPushButton[role="danger"] {{ color: {danger}; }}
QPushButton[role="link"] {{ background: transparent; border: none; color: {accent}; padding: 6px 8px; }}
QPushButton[role="link"]:hover {{ text-decoration: underline; }}
QPushButton[role="link"]:disabled {{ color: {disabled}; }}
QPushButton[role="segment"] {{ border-radius: 0; margin-left: -1px; padding: 7px 16px; }}
QPushButton[role="segment"]:checked {{
    background: {accent}; border-color: {accent}; color: white; font-weight: 600;
}}
QPushButton[role="rowEdit"], QPushButton[role="rowDelete"] {{
    padding: 0; font-size: 11pt; font-weight: 600; border-radius: 5px;
}}
QPushButton[role="rowEdit"] {{ color: {accent}; }}
QPushButton[role="rowEdit"]:hover {{ background: {accent}; border-color: {accent}; color: white; }}
QPushButton[role="rowDelete"] {{ color: {danger}; }}
QPushButton[role="rowDelete"]:hover {{ background: {danger}; border-color: {danger}; color: white; }}
QPushButton[role="tile"], QPushButton[role="tileIn"], QPushButton[role="tileOut"] {{ border-radius: 10px; padding: 0; }}
QPushButton[role="tile"] {{ border-color: {accent}; }}
#tileTitle {{ color: white; font-size: 14pt; font-weight: 600; }}
#tileTitleNeutral {{ font-size: 14pt; font-weight: 600; }}
#tileIcon {{
    font-family: "Segoe MDL2 Assets"; font-size: 14pt; color: white;
    background: rgba(255, 255, 255, 0.22); border-radius: 20px;
}}
#tileChevron {{ font-family: "Segoe MDL2 Assets"; font-size: 11pt; color: white; }}
QPushButton[role="tileIn"] {{ background: {accent}; border-color: {accent}; }}
QPushButton[role="tileIn"]:hover {{ background: {accent_dark}; }}
QPushButton[role="tileOut"] {{ background: {tile_out}; border-color: {tile_out}; }}
QPushButton[role="tileOut"]:hover {{ background: {tile_out_dark}; }}
#periodTitle {{ font-size: 12pt; font-weight: 600; }}

QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox, QPlainTextEdit, QTextBrowser {{
    background: {surface}; border: 1px solid {control_border}; border-radius: 6px; padding: 6px 8px;
    selection-background-color: {accent}; selection-color: white;
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{
    border-color: {accent};
}}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url("{arrow}"); width: 10px; height: 10px; }}
QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; background: {surface}; border: 1px solid {muted}; border-radius: 4px;
}}
QCheckBox::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; image: url("{check}"); }}
QCheckBox::indicator:disabled {{ border-color: {disabled}; }}
QLineEdit:disabled, QDateEdit:disabled {{ background: {disabled_bg}; color: {disabled}; }}
QComboBox QAbstractItemView, QCalendarWidget QAbstractItemView {{
    background: {surface}; border: 1px solid {control_border};
    selection-background-color: {accent}; selection-color: white;
}}
QCalendarWidget QWidget {{ background: {surface}; alternate-background-color: {header}; }}

QTableWidget {{
    background: {surface}; alternate-background-color: {alt_row}; border: 1px solid {border};
    border-radius: 8px; gridline-color: transparent;
    selection-background-color: {selection}; selection-color: {text};
}}
QTableWidget {{ font-size: 10pt; }}
QTableWidget::item {{ padding: 4px 6px; }}
QTreeWidget {{
    background: {surface}; border: 1px solid {border}; border-radius: 8px; font-size: 10pt;
    selection-background-color: {selection}; selection-color: {text};
}}
QTreeWidget::item {{ padding: 5px 4px; }}
QHeaderView::section {{
    background: {header}; border: none; border-bottom: 1px solid {border};
    padding: 8px 6px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {header}; border: none; }}
#flatTable {{ border: none; border-radius: 0; background: transparent; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; padding: 8px 16px; margin-right: 4px;
    border-bottom: 2px solid transparent; color: {muted};
}}
QTabBar::tab:selected {{ color: {accent}; border-bottom: 2px solid {accent}; font-weight: 600; }}

QToolTip {{ background: {tooltip}; color: white; border: none; padding: 6px 8px; font-size: 10pt; }}

/* ---- 2-ko'rinish: yumaloq kartochkalar, rangli ko'rsatkichlar, belgili tugma va yorliqlar ---- */
#pageIcon {{
    font-family: "Segoe MDL2 Assets"; font-size: 20pt; color: {accent};
    background: {accent_soft}; border-radius: 14px;
}}
#pageTitle {{ font-size: 19pt; font-weight: 700; }}
#card {{ border-radius: 14px; }}
#cardTitle {{ font-size: 10pt; color: {text}; }}
#cardValue {{ font-size: 21pt; font-weight: 700; }}
#statAccent, #statGood, #statOut, #statWarning, #statViolet {{ border-radius: 14px; border: 1px solid {border}; }}
#statAccent {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {accent_soft}, stop:1 {surface}); }}
#statGood {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {good_soft}, stop:1 {surface}); }}
#statOut {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {tile_out_soft}, stop:1 {surface}); }}
#statWarning {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {warning_soft}, stop:1 {surface}); }}
#statViolet {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {violet_soft}, stop:1 {surface}); }}
#statAccent[clickable="true"]:hover, #statGood[clickable="true"]:hover, #statOut[clickable="true"]:hover,
#statWarning[clickable="true"]:hover, #statViolet[clickable="true"]:hover {{ border-color: {accent}; }}
#badgeAccent, #badgeGood, #badgeOut, #badgeWarning, #badgeViolet {{ color: white; border-radius: 10px; }}
#badgeAccent {{ background: {accent}; }}
#badgeGood {{ background: {good}; }}
#badgeOut {{ background: {tile_out}; }}
#badgeWarning {{ background: {warning}; }}
#badgeViolet {{ font-family: "Segoe MDL2 Assets"; font-size: 15pt; background: {violet}; }}
#deltaUp {{ color: {good}; font-size: 9pt; font-weight: 600; }}
#deltaDown {{ color: {danger}; font-size: 9pt; font-weight: 600; }}

QPushButton {{ border-radius: 10px; padding: 9px 16px; }}
QPushButton[role="primary"] {{
    border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {accent}, stop:1 {accent_light});
}}
QPushButton[role="primary"]:hover {{ background: {accent}; }}
QPushButton[role="primary"]:disabled {{ background: {disabled_bg}; color: {disabled}; }}
#segmentBar {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
QPushButton[role="segment"] {{
    background: transparent; border: none; border-radius: 9px; margin: 0; padding: 7px 18px; color: {muted};
}}
QPushButton[role="segment"]:hover {{ background: {hover}; color: {text}; }}
QPushButton[role="segment"]:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {accent}, stop:1 {accent_light});
    color: white; font-weight: 600;
}}
QPushButton[role="page"] {{ padding: 6px; min-width: 22px; border-radius: 9px; }}
QPushButton[role="page"]:disabled {{ border-color: {border}; }}
#pagePosition {{
    background: {accent}; color: white; font-weight: 600; border-radius: 9px; padding: 6px 12px; min-width: 40px;
}}
QPushButton[role="rowEdit"], QPushButton[role="rowDelete"] {{ border-radius: 8px; padding: 0; }}
QPushButton[role="rowEdit"]:hover {{ background: {accent_soft}; border-color: {accent}; }}
QPushButton[role="rowDelete"]:hover {{ background: {danger_soft}; border-color: {danger}; }}

QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox, QPlainTextEdit {{ border-radius: 10px; padding: 7px 10px; }}

QTabBar::tab {{ padding: 10px 14px; margin-right: 2px; border-bottom: 3px solid transparent; }}
QTabBar::tab:selected {{ border-bottom: 3px solid {accent}; }}
QTabBar::tab:hover {{ color: {text}; }}
QTableWidget {{ border-radius: 12px; alternate-background-color: {surface}; }}
QTableWidget::item {{ border-bottom: 1px solid {border}; }}
QTableWidget::item:selected {{ background: {selection}; }}
QHeaderView::section {{ background: transparent; color: {muted}; border-bottom: 1px solid {border}; }}
#flatTable {{ background: transparent; border: none; }}
QTableWidget {{ outline: none; }}  /* tanlangan katak atrofidagi oq ramka kerak emas */
QTableWidget::item:focus {{ outline: none; border: none; border-bottom: 1px solid {border}; }}

#sidebar::item {{ padding: 7px 12px; margin: 1px 0; border-radius: 10px; border-left: 3px solid transparent; }}
#sidebar::item:selected {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {accent}, stop:1 {accent_dark});
    border-left: 3px solid {accent_light};
}}
#sidebarCard {{ background: {sidebar_hover}; border: 1px solid {border}; border-radius: 12px; }}
#sidebarCardTitle {{ color: white; font-weight: 600; font-size: 10pt; }}

/* Chop etish va Excel tugmalari o'z rangida: bir qarashda ajraladi. */
QPushButton[role="print"] {{ color: {violet}; border-color: {violet}; background: {violet_soft}; font-weight: 600; }}
QPushButton[role="print"]:hover {{ background: {violet}; color: white; }}
QPushButton[role="excel"] {{ color: {good}; border-color: {good}; background: {good_soft}; font-weight: 600; }}
QPushButton[role="excel"]:hover {{ background: {good}; color: white; }}
QTableWidget {{ font-size: 10.5pt; }}
#fieldTitle {{ font-weight: 600; }}
#infoPanel {{ background: {header}; border: 1px solid {border}; border-radius: 10px; }}
#sectionTitle {{ font-size: 12.5pt; font-weight: 700; }}
"""
