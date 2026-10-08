"""Obyektlar xaritasi: haqiqiy xarita (OpenStreetMap) ustida obyektlar belgilari.

Xarita bo'laklari birinchi marta internetdan olinadi va shu kompyuterda saqlanadi — keyin o'sha
joylar internetsiz ham ko'rinadi. Bo'lak yo'q joyda (internet ham, saqlangani ham bo'lmasa) masofa
to'ri chiziladi: obyektlar baribir o'z joyida turadi. Sichqoncha bilan surish va g'ildirak bilan
kattalashtirish mumkin. Belgi bosilsa — tanlanadi, ikki marta bosilsa — Google Maps'da ochish so'raladi.
"""

import math
from dataclasses import dataclass
from typing import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ..geo import Location, metres_per_unit
from ..i18n import tr
from ..tiles import ATTRIBUTION, MAX_ZOOM, MIN_ZOOM, TILE_SIZE
from . import theme
from .tile_loader import TileLoader

MIN_SIZE = (280, 240)
PADDING = 48  # hamma obyekt sig'dirilganda chetdagi belgilar va yozuvlari uchun joy
SINGLE_POINT_ZOOM = 15  # bitta obyekt bo'lsa — mahalla ko'rinadigan kattalikda
GRID_CELLS = 4  # xarita eniga taxminan shuncha to'r katagi
PIN_RADIUS, PIN_HEIGHT = 8, 22  # belgining boshi va uchigacha bo'lgan balandligi
SELECTED_SCALE = 1.3
HIT_RADIUS = 16
LABEL_GAP = 6
CORNER_RADIUS = 12
SCALE_MARGIN = 14
DRAG_THRESHOLD = 4  # shundan kam surilsa — bosish hisoblanadi
# Xarita rasmi har doim och rangda: ustidagi yozuvlar fon (tungi/kunduzgi) qanday bo'lmasin o'qilishi kerak.
MAP_INK, MAP_PAPER = "#1f2937", "#ffffff"


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


def _distance_text(metres: float) -> str:
    return tr("{0} km").format(f"{metres / 1000:g}") if metres >= 1000 else tr("{0} m").format(f"{metres:g}")


class SiteMap(QWidget):
    selected = Signal(int)  # belgi bosildi: obyekt id si
    opened = Signal(int)  # belgi ikki marta bosildi

    def __init__(self, tiles: TileLoader | None = None):
        """`tiles` berilmasa, xarita rasmi yuklanmaydi — faqat masofa to'ri va belgilar chiziladi."""
        super().__init__()
        self._tiles = tiles
        self._points: list[MapPoint] = []
        self._selected_id: int | None = None
        # Ko'rinish: markaz (xaritaning 0…1 koordinatalarida) va kattalashtirish darajasi.
        self._center = (0.5, 0.5)
        self._zoom = MIN_ZOOM
        self._fitted = False  # ko'rinish hozirgi belgilar va o'lchamga moslab qo'yilganmi
        self._drag_from: QPointF | None = None
        self._dragged = False
        self.setMinimumSize(*MIN_SIZE)
        self.setMouseTracking(True)
        if tiles is not None:
            tiles.loaded.connect(self.update)

    def set_points(self, points: Sequence[MapPoint]) -> None:
        """Belgilarni almashtiradi; joylashuvlar o'zgargan bo'lsa, xarita hammasini qayta sig'diradi."""
        points = list(points)
        if [point.location for point in points] != [point.location for point in self._points]:
            self._fitted = False
        self._points = points
        self.update()

    def select(self, point_id: int | None) -> None:
        self._selected_id = point_id
        self.update()

    def position_of(self, point_id: int) -> QPointF | None:
        """Obyekt belgisining uchi ekranda qayerda; bunday obyekt xaritada bo'lmasa — None."""
        self._fit_if_needed()
        for point in self._points:
            if point.id == point_id:
                return self._to_screen(point.location)
        return None

    # --- Ko'rinish (markaz va kattalik) -----------------------------------------

    def _scale(self) -> float:
        """Butun dunyo (0…1) hozirgi kattalikda necha piksel."""
        return TILE_SIZE * 2**self._zoom

    def _to_screen(self, location: Location) -> QPointF:
        x, y = location.to_unit()
        scale = self._scale()
        return QPointF(
            (x - self._center[0]) * scale + self.width() / 2, (y - self._center[1]) * scale + self.height() / 2
        )

    def _fit_if_needed(self) -> None:
        """Hamma belgi sig'adigan eng katta kattalikni tanlaydi va ularni o'rtaga qo'yadi."""
        if self._fitted or not self._points:
            return
        self._fitted = True
        units = [point.location.to_unit() for point in self._points]
        left, right = min(x for x, _ in units), max(x for x, _ in units)
        top, bottom = min(y for _, y in units), max(y for _, y in units)
        self._center = ((left + right) / 2, (top + bottom) / 2)
        room = (max(self.width() - 2 * PADDING, 1), max(self.height() - 2 * PADDING, 1))
        self._zoom = SINGLE_POINT_ZOOM
        while self._zoom > MIN_ZOOM and (
            (right - left) * self._scale() > room[0] or (bottom - top) * self._scale() > room[1]
        ):
            self._zoom -= 1

    def _zoom_at(self, position: QPointF, steps: int) -> None:
        """Kattalikni o'zgartiradi; sichqoncha ostidagi joy o'z o'rnida qoladi."""
        zoom = min(max(self._zoom + steps, MIN_ZOOM), MAX_ZOOM)
        if zoom == self._zoom:
            return
        offset = (position.x() - self.width() / 2, position.y() - self.height() / 2)
        under_cursor = [self._center[axis] + offset[axis] / self._scale() for axis in (0, 1)]
        self._zoom = zoom
        self._center = tuple(under_cursor[axis] - offset[axis] / self._scale() for axis in (0, 1))
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fitted = False  # o'lcham o'zgarsa, belgilar yana hammasi ko'rinadigan qilib joylanadi

    # --- Chizish ---------------------------------------------------------------

    def paintEvent(self, event) -> None:
        self._fit_if_needed()
        colors = theme.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        frame = QPainterPath()
        frame.addRoundedRect(area, CORNER_RADIUS, CORNER_RADIUS)
        painter.fillPath(frame, QColor(colors.alt_row))
        painter.setClipPath(frame)
        if not self._points:
            painter.setPen(QColor(colors.muted))
            painter.drawText(
                area.adjusted(PADDING / 2, 0, -PADDING / 2, 0),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                tr("Joylashuvi yozilgan obyekt yo'q.\nObyektni tahrirlab, «Joylashuv» maydoniga koordinatasini kiriting."),
            )
        else:
            metres_per_pixel = metres_per_unit(Location.from_unit(*self._center).latitude) / self._scale()
            step_metres = _nice_step(self.width() * metres_per_pixel / GRID_CELLS)
            self._draw_grid(painter, colors, step_metres / metres_per_pixel)
            has_map = self._draw_tiles(painter)
            # Tanlangan belgi eng oxirida chiziladi — boshqalarining ustida turadi.
            for point in sorted(self._points, key=lambda point: point.id == self._selected_id):
                self._draw_point(painter, colors, point)
            # Xarita rasmi ustida yozuvlar to'q rangda va oq taglikda; rasm yo'q bo'lsa — fon rangida.
            ink = QColor(MAP_INK if has_map else colors.muted)
            self._draw_scale(painter, ink, has_map, step_metres, step_metres / metres_per_pixel)
            self._draw_compass(painter, ink)
            if has_map:
                self._draw_caption(painter, QRectF(self.width() - 6, self.height() - 22, 0, 16), ATTRIBUTION)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(colors.border), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(frame)

    def _draw_tiles(self, painter: QPainter) -> bool:
        """Ko'rinayotgan joyning xarita bo'laklarini chizadi; kamida bittasi chizilgan bo'lsa — True.

        Tayyor bo'lmagan bo'laklar fonda yuklanadi va kelgach xarita qayta chiziladi.
        """
        if self._tiles is None:
            return False
        count = 2**self._zoom
        left = self._center[0] * self._scale() - self.width() / 2
        top = self._center[1] * self._scale() - self.height() / 2
        drawn = False
        for row in range(int(top // TILE_SIZE), int((top + self.height()) // TILE_SIZE) + 1):
            if not 0 <= row < count:
                continue
            for column in range(int(left // TILE_SIZE), int((left + self.width()) // TILE_SIZE) + 1):
                pixmap = self._tiles.pixmap((self._zoom, column % count, row))
                if pixmap is not None:
                    painter.drawPixmap(QPointF(column * TILE_SIZE - left, row * TILE_SIZE - top), pixmap)
                    drawn = True
        return drawn

    def _draw_grid(self, painter: QPainter, colors, step: float) -> None:
        """Masofa to'ri (markazdan boshlab): xarita rasmi yo'q joyda ham masofani chamalash mumkin."""
        middle = QRectF(self.rect()).center()
        painter.setPen(QPen(QColor(colors.grid), 1))
        for index in range(-int(middle.x() // step) - 1, int(middle.x() // step) + 2):
            x = middle.x() + index * step
            painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        for index in range(-int(middle.y() // step) - 1, int(middle.y() // step) + 2):
            y = middle.y() + index * step
            painter.drawLine(QPointF(0, y), QPointF(self.width(), y))

    def _draw_scale(self, painter: QPainter, ink: QColor, on_map: bool, metres: float, length: float) -> None:
        """Chap pastda masshtab chizig'i va uning uzunligi (masalan, «5 km»)."""
        bottom = self.height() - SCALE_MARGIN
        text = _distance_text(metres)
        if on_map:
            width = length + painter.fontMetrics().horizontalAdvance(text) + 24
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(MAP_PAPER))
            painter.setOpacity(0.75)
            painter.drawRoundedRect(QRectF(SCALE_MARGIN - 6, bottom - 14, width, 22), 5, 5)
            painter.setOpacity(1.0)
        painter.setPen(QPen(ink, 2))
        painter.drawLine(QPointF(SCALE_MARGIN, bottom), QPointF(SCALE_MARGIN + length, bottom))
        for x in (SCALE_MARGIN, SCALE_MARGIN + length):
            painter.drawLine(QPointF(x, bottom - 4), QPointF(x, bottom))
        painter.drawText(QPointF(SCALE_MARGIN + length + 8, bottom + 1), text)

    def _draw_point(self, painter: QPainter, colors, point: MapPoint) -> None:
        """Tomchi shaklidagi belgi (uchi — obyekt turgan joy) va yonida obyekt nomi."""
        is_selected = point.id == self._selected_id
        tip = self._to_screen(point.location)
        scale = SELECTED_SCALE if is_selected else 1.0
        radius, height = PIN_RADIUS * scale, PIN_HEIGHT * scale
        head = QPointF(tip.x(), tip.y() - height + radius)
        circle, tail = QPainterPath(), QPainterPath()
        circle.addEllipse(head, radius, radius)
        tail.moveTo(tip)
        tail.lineTo(head.x() - radius * 0.8, head.y() + radius * 0.6)
        tail.lineTo(head.x() + radius * 0.8, head.y() + radius * 0.6)
        tail.closeSubpath()
        painter.setPen(QPen(QColor(MAP_PAPER), 1.5))
        painter.setBrush(QColor(colors.tile_out if is_selected else colors.accent))
        painter.drawPath(circle.united(tail))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(MAP_PAPER))
        painter.drawEllipse(head, radius * 0.38, radius * 0.38)

        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold if is_selected else QFont.Weight.Medium)
        painter.setFont(font)
        width = painter.fontMetrics().horizontalAdvance(point.name)
        fits_right = head.x() + radius + LABEL_GAP + width <= self.width() - 4
        left = head.x() + radius + LABEL_GAP if fits_right else head.x() - radius - LABEL_GAP - width
        label = QRectF(left - 5, head.y() - 11, width + 10, 22)
        painter.setBrush(QColor(MAP_PAPER))
        painter.setOpacity(0.9)
        painter.drawRoundedRect(label, 6, 6)  # yozuv xarita ustida ham o'qiladi
        painter.setOpacity(1.0)
        painter.setPen(QColor(MAP_INK))
        painter.drawText(label, Qt.AlignmentFlag.AlignCenter, point.name)
        painter.setFont(self.font())

    def _draw_compass(self, painter: QPainter, ink: QColor) -> None:
        """Chap yuqorida shimol belgisi."""
        top = QPointF(SCALE_MARGIN + 6, 12)
        arrow = QPainterPath()
        arrow.moveTo(top)
        arrow.lineTo(top.x() - 6, top.y() + 16)
        arrow.lineTo(top.x(), top.y() + 12)
        arrow.lineTo(top.x() + 6, top.y() + 16)
        arrow.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        painter.drawPath(arrow)
        painter.setPen(ink)
        painter.drawText(QRectF(top.x() - 12, top.y() + 18, 24, 16), Qt.AlignmentFlag.AlignCenter, tr("Sh"))

    def _draw_caption(self, painter: QPainter, right_edge: QRectF, text: str) -> None:
        """Oq taglikdagi kichik yozuv, o'ng cheti `right_edge` da: xarita manbasi (OpenStreetMap talabi)."""
        font = QFont(self.font())
        font.setPointSizeF(font.pointSizeF() * 0.8)
        painter.setFont(font)
        width = painter.fontMetrics().horizontalAdvance(text) + 10
        backing = QRectF(right_edge.right() - width, right_edge.top(), width, right_edge.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(MAP_PAPER))
        painter.setOpacity(0.75)
        painter.drawRoundedRect(backing, 4, 4)
        painter.setOpacity(1.0)
        painter.setPen(QColor(MAP_INK))
        painter.drawText(backing, Qt.AlignmentFlag.AlignCenter, text)
        painter.setFont(self.font())

    # --- Sichqoncha ------------------------------------------------------------

    def point_at(self, position: QPointF) -> MapPoint | None:
        """Shu joydagi (belgisining boshiga eng yaqin) obyekt; yaqinida yo'q bo'lsa — None."""
        self._fit_if_needed()
        nearest, nearest_distance = None, HIT_RADIUS
        for point in self._points:
            tip = self._to_screen(point.location)
            distance = math.hypot(position.x() - tip.x(), position.y() - (tip.y() - PIN_HEIGHT + PIN_RADIUS))
            if distance <= nearest_distance:
                nearest, nearest_distance = point, distance
        return nearest

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = self.point_at(event.position())
        if point is not None:
            self.select(point.id)
            self.selected.emit(point.id)
        else:
            self._drag_from, self._dragged = event.position(), False

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None:
            self._drag_to(event.position())
            return
        point = self.point_at(event.position())
        self.setCursor(Qt.CursorShape.PointingHandCursor if point else Qt.CursorShape.OpenHandCursor)
        if point is None:
            QToolTip.hideText()
        else:
            text = f"{point.name}\n{point.details}" if point.details else point.name
            QToolTip.showText(event.globalPosition().toPoint(), text, self)

    def _drag_to(self, position: QPointF) -> None:
        """Xaritani sichqoncha bilan suradi (juda kichik siljish — bosish, surish emas)."""
        moved = position - self._drag_from
        if not self._dragged and moved.manhattanLength() < DRAG_THRESHOLD:
            return
        self._dragged = True
        self._drag_from = position
        scale = self._scale()
        self._center = (self._center[0] - moved.x() / scale, self._center[1] - moved.y() / scale)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, event) -> None:
        point = self.point_at(event.position())
        if point is not None:
            self.opened.emit(point.id)
        else:
            self._zoom_at(event.position(), 1)  # bo'sh joyda ikki marta bosish — yaqinlashtirish

    def wheelEvent(self, event) -> None:
        if self._points and event.angleDelta().y():
            self._zoom_at(event.position(), 1 if event.angleDelta().y() > 0 else -1)
