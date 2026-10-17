"""Profil rasmini qirqish (Telegram'dagi kabi): rasm doira ostida sudrab suriladi, g'ildirak yoki surgich bilan
kattalashtiriladi; doira ichida ko'ringan qism saqlanadi."""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QSlider, QVBoxLayout, QWidget

from ..i18n import tr
from .widgets import button, label

VIEW_SIZE = 340  # qirqish maydoni (kvadrat), piksel
MAX_ZOOM = 4.0  # rasm doirani to'liq qoplagan holatga nisbatan eng ko'p kattalashtirish
ZOOM_STEPS = 100  # surgich bo'linmalari
WHEEL_STEP = 1.1  # g'ildirakning bir qadamida kattalashtirish


class CropView(QWidget):
    """Rasm va uning ustidagi doira. Rasm doiradan chiqib ketmaydi: doira ichida doim rasm bo'ladi."""

    zoom_changed = Signal(float)

    def __init__(self, image: QImage, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(VIEW_SIZE, VIEW_SIZE)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._image = image
        self._cover = VIEW_SIZE / min(image.width(), image.height())  # rasm doirani endigina qoplaydigan masshtab
        self._zoom = 1.0
        self._offset = QPointF(  # rasmning chap yuqori burchagi (maydon koordinatalarida); boshida — o'rtada
            (VIEW_SIZE - image.width() * self._cover) / 2, (VIEW_SIZE - image.height() * self._cover) / 2
        )
        self._drag_from: QPointF | None = None

    @property
    def zoom(self) -> float:
        return self._zoom

    def _scale(self) -> float:
        return self._cover * self._zoom

    def set_zoom(self, zoom: float) -> None:
        """Maydon markazidagi nuqta joyida qolgan holda kattalashtiradi."""
        zoom = min(max(zoom, 1.0), MAX_ZOOM)
        if zoom == self._zoom:
            return
        center = QPointF(VIEW_SIZE / 2, VIEW_SIZE / 2)
        ratio = zoom / self._zoom
        self._zoom = zoom
        self._offset = center - (center - self._offset) * ratio
        self._keep_covered()
        self.update()
        self.zoom_changed.emit(zoom)

    def move_by(self, dx: float, dy: float) -> None:
        self._offset += QPointF(dx, dy)
        self._keep_covered()
        self.update()

    def _keep_covered(self) -> None:
        scale = self._scale()
        width, height = self._image.width() * scale, self._image.height() * scale
        self._offset = QPointF(
            min(0.0, max(VIEW_SIZE - width, self._offset.x())), min(0.0, max(VIEW_SIZE - height, self._offset.y()))
        )

    def cropped(self) -> QImage:
        """Doira ichida ko'ringan kvadrat qism (asl rasm piksellarida)."""
        scale = self._scale()
        side = max(1, round(VIEW_SIZE / scale))
        left = min(max(0, round(-self._offset.x() / scale)), self._image.width() - side)
        top = min(max(0, round(-self._offset.y() / scale)), self._image.height() - side)
        return self._image.copy(left, top, side, side)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        scale = self._scale()
        target = QRectF(self._offset.x(), self._offset.y(), self._image.width() * scale, self._image.height() * scale)
        painter.drawImage(target, self._image)
        circle = QRectF(1, 1, VIEW_SIZE - 2, VIEW_SIZE - 2)
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        hole = QPainterPath()
        hole.addEllipse(circle)
        painter.fillPath(shade.subtracted(hole), QColor(0, 0, 0, 150))  # doiradan tashqarisi qoraytiriladi
        painter.setPen(QPen(QColor(255, 255, 255, 200), 2))
        painter.drawEllipse(circle)
        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None:
            delta = event.position() - self._drag_from
            self._drag_from = event.position()
            self.move_by(delta.x(), delta.y())

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y() / 120
        if steps:
            self.set_zoom(self._zoom * WHEEL_STEP**steps)


class PhotoCropDialog(QDialog):
    """«Rasmni tanlang» oynasi: qirqish maydoni, kattalashtirish surgichi, «Bekor qilish / Saqlash»."""

    def __init__(self, image: QImage, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Profil rasmi"))
        self.view = CropView(image)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, ZOOM_STEPS)
        self.slider.valueChanged.connect(lambda value: self.view.set_zoom(1 + (MAX_ZOOM - 1) * value / ZOOM_STEPS))
        self.view.zoom_changed.connect(self._show_zoom)
        cancel = button(tr("Bekor qilish"))
        cancel.clicked.connect(self.reject)
        save = button(tr("Saqlash"), "primary")
        save.setDefault(True)
        save.clicked.connect(self.accept)

        zoom_row = QHBoxLayout()
        zoom_row.addWidget(label("−", "muted"))
        zoom_row.addWidget(self.slider, stretch=1)
        zoom_row.addWidget(label("+", "muted"))
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        self.setFixedWidth(VIEW_SIZE + 40)
        hint = label(tr("Rasmni sudrab suring, g'ildirak yoki surgich bilan kattalashtiring"), "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(self.view, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addLayout(zoom_row)
        layout.addLayout(buttons)

    def _show_zoom(self, zoom: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(round((zoom - 1) / (MAX_ZOOM - 1) * ZOOM_STEPS))
        self.slider.blockSignals(False)

    def cropped(self) -> QImage:
        return self.view.cropped()
