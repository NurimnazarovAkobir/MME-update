"""Obyektlar xaritasi: internetsiz chiziladigan sxema — obyektlar bir-biriga nisbatan haqiqiy joylashuvida.

Ko'cha va uylar yo'q (ular internetdagi xaritada): bu yerda obyektlar nuqta bo'lib, masofa
to'ri va masshtab bilan ko'rinadi. Shimol — yuqorida. Nuqta bosilsa — tanlanadi, ikki marta
bosilsa — haqiqiy xaritada ochish so'raladi.
"""

import math
from dataclasses import dataclass
from typing import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ..geo import Location
from ..i18n import tr
from . import theme

MIN_SIZE = (280, 240)
PADDING = 44  # chetdagi nuqtalar va ularning yozuvlari sig'ishi uchun
MIN_SPAN_KM = 1.0  # bitta obyekt (yoki juda yaqin obyektlar) bo'lsa ham, xarita shuncha joyni ko'rsatadi
GRID_CELLS = 4  # xarita eniga taxminan shuncha to'r katagi
PIN_RADIUS, PIN_HEIGHT = 8, 22  # nuqta belgisining boshi va uchigacha bo'lgan balandligi
SELECTED_SCALE = 1.3
HIT_RADIUS = 16
LABEL_GAP = 6
CORNER_RADIUS = 12
SCALE_MARGIN = 14
COMPASS_MARGIN = 20


@dataclass(frozen=True)
class MapPoint:
    id: int
    name: str
    location: Location
    details: str = ""  # sichqoncha ustida ko'rinadigan qo'shimcha matn (masalan, manzil)


def _nice_step(value: float) -> float:
    """Qiymatga eng yaqin (undan katta bo'lmagan) «chiroyli» qadam: 1, 2 yoki 5 × 10ⁿ."""
    magnitude = 10 ** math.floor(math.log10(value))
    return max(step * magnitude for step in (1, 2, 5) if step * magnitude <= value)


def _distance_text(km: float) -> str:
    return tr("{0} km").format(f"{km:g}") if km >= 1 else tr("{0} m").format(f"{km * 1000:g}")


class SiteMap(QWidget):
    selected = Signal(int)  # nuqta bosildi: obyekt id si
    opened = Signal(int)  # nuqta ikki marta bosildi

    def __init__(self):
        super().__init__()
        self._points: list[MapPoint] = []
        self._selected_id: int | None = None
        self._positions: dict[int, QPointF] = {}  # oxirgi chizilgan holatda nuqtalarning ekrandagi o'rni
        self.setMinimumSize(*MIN_SIZE)
        self.setMouseTracking(True)

    def set_points(self, points: Sequence[MapPoint]) -> None:
        self._points = list(points)
        self.update()

    def select(self, point_id: int | None) -> None:
        self._selected_id = point_id
        self.update()

    # --- Chizish ---------------------------------------------------------------

    def paintEvent(self, event) -> None:
        colors = theme.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        frame = QPainterPath()
        frame.addRoundedRect(area, CORNER_RADIUS, CORNER_RADIUS)
        painter.fillPath(frame, QColor(colors.alt_row))
        painter.setClipPath(frame)
        self._positions = {}
        if not self._points:
            painter.setPen(QColor(colors.muted))
            painter.drawText(
                area.adjusted(PADDING / 2, 0, -PADDING / 2, 0),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                tr("Joylashuvi yozilgan obyekt yo'q.\nObyektni tahrirlab, «Joylashuv» maydoniga koordinatasini kiriting."),
            )
        else:
            center, pixels_per_km = self._view()
            self._draw_grid(painter, colors, pixels_per_km)
            for point in self._points:
                east, north = point.location.offset_km(center)
                middle = area.center()
                self._positions[point.id] = QPointF(
                    middle.x() + east * pixels_per_km, middle.y() - north * pixels_per_km
                )
            # Tanlangan nuqta eng oxirida chiziladi — boshqalarining ustida turadi.
            for point in sorted(self._points, key=lambda point: point.id == self._selected_id):
                self._draw_point(painter, colors, point)
            self._draw_compass(painter, colors)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(colors.border), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(frame)

    def _view(self) -> tuple[Location, float]:
        """Hamma nuqtalar sig'adigan ko'rinish: markaz va bir kilometrga to'g'ri keladigan piksellar soni."""
        latitudes = [point.location.latitude for point in self._points]
        longitudes = [point.location.longitude for point in self._points]
        center = Location((min(latitudes) + max(latitudes)) / 2, (min(longitudes) + max(longitudes)) / 2)
        offsets = [point.location.offset_km(center) for point in self._points]
        half_width = max(max(abs(east) for east, _ in offsets), MIN_SPAN_KM / 2)
        half_height = max(max(abs(north) for _, north in offsets), MIN_SPAN_KM / 2)
        scale = min((self.width() / 2 - PADDING) / half_width, (self.height() / 2 - PADDING) / half_height)
        return center, max(scale, 0.001)

    def _draw_grid(self, painter: QPainter, colors, pixels_per_km: float) -> None:
        """Masofa to'ri (markazdan boshlab) va chap pastda masshtab chizig'i."""
        step_km = _nice_step(self.width() / pixels_per_km / GRID_CELLS)
        step = step_km * pixels_per_km
        middle = QRectF(self.rect()).center()
        painter.setPen(QPen(QColor(colors.grid), 1))
        for index in range(-int(middle.x() // step) - 1, int(middle.x() // step) + 2):
            x = middle.x() + index * step
            painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        for index in range(-int(middle.y() // step) - 1, int(middle.y() // step) + 2):
            y = middle.y() + index * step
            painter.drawLine(QPointF(0, y), QPointF(self.width(), y))

        bottom = self.height() - SCALE_MARGIN
        painter.setPen(QPen(QColor(colors.muted), 2))
        painter.drawLine(QPointF(SCALE_MARGIN, bottom), QPointF(SCALE_MARGIN + step, bottom))
        for x in (SCALE_MARGIN, SCALE_MARGIN + step):
            painter.drawLine(QPointF(x, bottom - 4), QPointF(x, bottom))
        painter.drawText(QPointF(SCALE_MARGIN + step + 8, bottom + 1), _distance_text(step_km))

    def _draw_point(self, painter: QPainter, colors, point: MapPoint) -> None:
        """Tomchi shaklidagi belgi (uchi — obyekt turgan joy) va yonida obyekt nomi."""
        is_selected = point.id == self._selected_id
        tip = self._positions[point.id]
        scale = SELECTED_SCALE if is_selected else 1.0
        radius, height = PIN_RADIUS * scale, PIN_HEIGHT * scale
        head = QPointF(tip.x(), tip.y() - height + radius)
        circle, tail = QPainterPath(), QPainterPath()
        circle.addEllipse(head, radius, radius)
        tail.moveTo(tip)
        tail.lineTo(head.x() - radius * 0.8, head.y() + radius * 0.6)
        tail.lineTo(head.x() + radius * 0.8, head.y() + radius * 0.6)
        tail.closeSubpath()
        pin = circle.united(tail)
        painter.setPen(QPen(QColor(colors.surface), 1.5))
        painter.setBrush(QColor(colors.tile_out if is_selected else colors.accent))
        painter.drawPath(pin)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors.surface))
        painter.drawEllipse(head, radius * 0.38, radius * 0.38)

        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold if is_selected else QFont.Weight.Normal)
        painter.setFont(font)
        width = painter.fontMetrics().horizontalAdvance(point.name)
        fits_right = head.x() + radius + LABEL_GAP + width <= self.width() - 4
        left = head.x() + radius + LABEL_GAP if fits_right else head.x() - radius - LABEL_GAP - width
        label = QRectF(left - 4, head.y() - 10, width + 8, 20)
        painter.setBrush(QColor(colors.surface))
        painter.setOpacity(0.85)
        painter.drawRoundedRect(label, 5, 5)  # yozuv to'r chiziqlari ustida ham o'qiladi
        painter.setOpacity(1.0)
        painter.setPen(QColor(colors.text))
        painter.drawText(label, Qt.AlignmentFlag.AlignCenter, point.name)

    def _draw_compass(self, painter: QPainter, colors) -> None:
        """Chap yuqorida shimol belgisi (nuqtalarning yozuvlari o'ngga qarab chiqadi — ularga xalaqit bermaydi)."""
        top = QPointF(COMPASS_MARGIN, 12)
        arrow = QPainterPath()
        arrow.moveTo(top)
        arrow.lineTo(top.x() - 6, top.y() + 16)
        arrow.lineTo(top.x(), top.y() + 12)
        arrow.lineTo(top.x() + 6, top.y() + 16)
        arrow.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors.muted))
        painter.drawPath(arrow)
        painter.setPen(QColor(colors.muted))
        painter.drawText(QRectF(top.x() - 12, top.y() + 18, 24, 16), Qt.AlignmentFlag.AlignCenter, tr("Sh"))

    # --- Sichqoncha ------------------------------------------------------------

    def point_at(self, position: QPointF) -> MapPoint | None:
        """Shu joydagi (belgisining boshiga eng yaqin) obyekt; yaqinida yo'q bo'lsa — None."""
        nearest, nearest_distance = None, HIT_RADIUS
        for point in self._points:
            tip = self._positions.get(point.id)
            if tip is None:
                continue
            head = QPointF(tip.x(), tip.y() - PIN_HEIGHT + PIN_RADIUS)
            distance = math.hypot(position.x() - head.x(), position.y() - head.y())
            if distance <= nearest_distance:
                nearest, nearest_distance = point, distance
        return nearest

    def mousePressEvent(self, event) -> None:
        point = self.point_at(event.position())
        if point is not None and event.button() == Qt.MouseButton.LeftButton:
            self.select(point.id)
            self.selected.emit(point.id)

    def mouseDoubleClickEvent(self, event) -> None:
        point = self.point_at(event.position())
        if point is not None:
            self.opened.emit(point.id)

    def mouseMoveEvent(self, event) -> None:
        point = self.point_at(event.position())
        self.setCursor(Qt.CursorShape.PointingHandCursor if point else Qt.CursorShape.ArrowCursor)
        if point is None:
            QToolTip.hideText()
        else:
            text = f"{point.name}\n{point.details}" if point.details else point.name
            QToolTip.showText(event.globalPosition().toPoint(), text, self)
