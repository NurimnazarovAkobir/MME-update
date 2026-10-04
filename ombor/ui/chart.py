"""Ustunli diagramma: har bir guruhda (masalan, oyda) bir nechta qator yonma-yon."""

import math
from typing import Sequence

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ..formatting import fmt_compact, fmt_money
from ..i18n import tr
from . import theme

MARGIN_LEFT, MARGIN_TOP, MARGIN_RIGHT, MARGIN_BOTTOM = 70, 34, 12, 28
GRID_LINES = 4
MAX_BAR_WIDTH = 26
BAR_GAP = 2
BAR_RADIUS = 4
GROUP_FILL = 0.6  # guruh kengligining ustunlar egallaydigan qismi
SWATCH = 10


def _nice_ceiling(value: float) -> float:
    """Qiymatdan katta eng yaqin 'chiroyli' son: 1, 2, 2.5, 5 yoki 10 × 10ⁿ."""
    if value <= 0:
        return 0.0
    magnitude = 10 ** math.floor(math.log10(value))
    return next(step * magnitude for step in (1, 2, 2.5, 5, 10) if value <= step * magnitude)


class BarChart(QWidget):
    def __init__(self, series: Sequence[str], unit: str = ""):
        """`series` — qatorlar nomlari (ranglari tanlangan fondan olinadi); `unit` — qiymat birligi."""
        super().__init__()
        self._series = tuple(series)
        self._unit = unit
        self._groups: list[tuple[str, Sequence[float]]] = []
        self._hover_areas: list[tuple[QRectF, str]] = []
        self.setMinimumHeight(220)
        self.setMouseTracking(True)

    def set_data(self, groups: Sequence[tuple[str, Sequence[float]]]) -> None:
        """`groups` — (yorliq, har bir qator uchun qiymatlar) ro'yxati."""
        self._groups = list(groups)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._hover_areas = []
        self._draw_legend(painter)

        plot = QRectF(
            MARGIN_LEFT,
            MARGIN_TOP,
            self.width() - MARGIN_LEFT - MARGIN_RIGHT,
            self.height() - MARGIN_TOP - MARGIN_BOTTOM,
        )
        top_value = _nice_ceiling(max((v for _, values in self._groups for v in values), default=0))
        if not top_value:
            painter.setPen(QColor(theme.palette().muted))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, tr("Hozircha ma'lumot yo'q"))
            return
        self._draw_grid(painter, plot, top_value)
        self._draw_bars(painter, plot, top_value)

    def mouseMoveEvent(self, event) -> None:
        for area, text in self._hover_areas:
            if area.contains(event.position()):
                QToolTip.showText(event.globalPosition().toPoint(), text, self)
                return
        QToolTip.hideText()

    def _draw_legend(self, painter: QPainter) -> None:
        x = MARGIN_LEFT
        for name, color in zip(self._series, theme.palette().series):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(x, 8, SWATCH, SWATCH), 2, 2)
            painter.setPen(QColor(theme.palette().text))
            text_width = painter.fontMetrics().horizontalAdvance(name)
            painter.drawText(QRectF(x + SWATCH + 6, 2, text_width + 2, 22), Qt.AlignmentFlag.AlignVCenter, name)
            x += SWATCH + 6 + text_width + 20

    def _draw_grid(self, painter: QPainter, plot: QRectF, top_value: float) -> None:
        for line in range(GRID_LINES + 1):
            y = plot.bottom() - plot.height() * line / GRID_LINES
            painter.setPen(QPen(QColor(theme.palette().axis if line == 0 else theme.palette().grid), 1))
            painter.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))
            painter.setPen(QColor(theme.palette().muted))
            painter.drawText(
                QRectF(0, y - 10, MARGIN_LEFT - 8, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                fmt_compact(top_value * line / GRID_LINES),
            )

    def _draw_bars(self, painter: QPainter, plot: QRectF, top_value: float) -> None:
        count = len(self._series)
        group_width = plot.width() / len(self._groups)
        bar_width = min(MAX_BAR_WIDTH, (group_width * GROUP_FILL - BAR_GAP * (count - 1)) / count)
        bars_width = bar_width * count + BAR_GAP * (count - 1)

        for group_index, (group_label, values) in enumerate(self._groups):
            group_left = plot.left() + group_width * group_index
            x = group_left + (group_width - bars_width) / 2

            # Ustunning pastki burchaklari to'g'ri qolishi uchun o'q chizig'idan pasti kesiladi.
            painter.save()
            painter.setClipRect(plot)
            painter.setPen(Qt.PenStyle.NoPen)
            for color, value in zip(theme.palette().series, values):
                height = plot.height() * value / top_value
                painter.setBrush(QColor(color))
                painter.drawRoundedRect(
                    QRectF(x, plot.bottom() - height, bar_width, height + BAR_RADIUS), BAR_RADIUS, BAR_RADIUS
                )
                x += bar_width + BAR_GAP
            painter.restore()

            painter.setPen(QColor(theme.palette().muted))
            painter.drawText(
                QRectF(group_left, plot.bottom() + 4, group_width, 20), Qt.AlignmentFlag.AlignCenter, group_label
            )
            self._hover_areas.append(
                (QRectF(group_left, plot.top(), group_width, plot.height()), self._tooltip(group_label, values))
            )

    def _tooltip(self, group_label: str, values: Sequence[float]) -> str:
        lines = [f"{name}: {fmt_money(value)} {self._unit}".rstrip() for name, value in zip(self._series, values)]
        return "\n".join([group_label, *lines])
