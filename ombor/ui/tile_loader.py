"""Xarita bo'laklarini fonda yuklash: oyna bu paytda qotib qolmaydi."""

import queue
import threading
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap

from ..tiles import Tile, TileStore

WORKERS = 2  # OpenStreetMap qoidasi: bir vaqtda ikkitadan ortiq ulanish ochilmaydi
MEMORY_LIMIT = 300  # xotirada turadigan bo'laklar soni; ortig'i — eng eskisidan boshlab — chiqariladi
RETRY_SECONDS = 20  # yuklab bo'lmagan bo'lak (internet yo'q) shuncha vaqt qayta so'ralmaydi


class TileLoader(QObject):
    """Bo'laklarni `TileStore` dan fonda oladi va tayyor rasmlarni xotirada ushlab turadi.

    `pixmap` darhol javob beradi: rasm tayyor bo'lsa — o'zi, bo'lmasa — None (va fonda yuklash
    boshlanadi; tayyor bo'lgach `loaded` signali chiqadi — xarita qayta chiziladi).
    """

    loaded = Signal()
    _fetched = Signal(object, object)  # (bo'lak, rasm baytlari yoki None) — fon oqimidan asosiy oqimga

    def __init__(self, store: TileStore, parent: QObject | None = None):
        super().__init__(parent)
        self._store = store
        self._pixmaps: dict[Tile, QPixmap] = {}
        self._waiting: set[Tile] = set()
        self._failed_at: dict[Tile, float] = {}
        self._requests: queue.LifoQueue[Tile] = queue.LifoQueue()  # oxirgi so'ralgani (ekrandagisi) birinchi
        self._fetched.connect(self._on_fetched)
        for _ in range(WORKERS):
            threading.Thread(target=self._work, daemon=True).start()

    def pixmap(self, tile: Tile) -> QPixmap | None:
        ready = self._pixmaps.get(tile)
        if ready is None and tile not in self._waiting and not self._failed_recently(tile):
            self._waiting.add(tile)
            self._requests.put(tile)
        return ready

    def _failed_recently(self, tile: Tile) -> bool:
        failed_at = self._failed_at.get(tile)
        return failed_at is not None and time.monotonic() - failed_at < RETRY_SECONDS

    def _work(self) -> None:
        while True:
            tile = self._requests.get()
            try:
                self._fetched.emit(tile, self._store.load(tile))
            except RuntimeError:
                return  # dastur yopilmoqda: natijani yetkazadigan joy qolmagan

    def _on_fetched(self, tile: Tile, data: bytes | None) -> None:
        self._waiting.discard(tile)
        pixmap = QPixmap()
        if not data or not pixmap.loadFromData(data):
            self._failed_at[tile] = time.monotonic()
            return
        self._failed_at.pop(tile, None)
        self._pixmaps[tile] = pixmap
        while len(self._pixmaps) > MEMORY_LIMIT:
            self._pixmaps.pop(next(iter(self._pixmaps)))
        self.loaded.emit()
