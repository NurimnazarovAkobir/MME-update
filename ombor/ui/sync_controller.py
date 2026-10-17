"""Fonda sinxronlash: har 30 soniyada (va so'ralganda) alohida oqimda umumiy baza bilan almashadi.

Umumiy baza — markaziy server (sync.py) yoki umumiy papka, masalan Google Drive (folder_sync.py). Oqim bazaga
o'zining alohida ulanishi bilan ishlaydi, shuning uchun internet sekin bo'lsa ham oyna qotmaydi.
"""

from typing import Callable

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from ..driver import sqlite3
from ..folder_sync import FolderSynchronizer, shared_folder
from ..i18n import tr
from ..local import LocalPrefs
from ..sync import SyncClient, SyncConfig, SyncResult, Synchronizer

SYNC_INTERVAL_MS = 30_000
SHUTDOWN_WAIT_MS = 25_000  # dastur yopilganda boshlangan sinxronlash tugashi kutiladi

SynchronizerFactory = Callable[[sqlite3.Connection], "Synchronizer | FolderSynchronizer"]


def synchronizer_factory(prefs: LocalPrefs) -> SynchronizerFactory | None:
    """Shu kompyuterda sozlangan almashish usuli: umumiy papka yoki server; hech biri bo'lmasa — None."""
    folder = shared_folder(prefs)
    if folder is not None:
        return lambda conn: FolderSynchronizer(conn, folder)
    config = SyncConfig.load(prefs)
    if config is not None:
        return lambda conn: Synchronizer(conn, SyncClient(config))
    return None


class _SyncThread(QThread):
    done = Signal(object)  # SyncResult

    def __init__(self, reconnect: Callable[[], sqlite3.Connection], factory: SynchronizerFactory, parent: QObject):
        super().__init__(parent)
        self._reconnect = reconnect
        self._factory = factory

    def run(self) -> None:
        try:
            conn = self._reconnect()
        except sqlite3.Error as error:
            self.done.emit(SyncResult(error=tr("Bazani ochib bo'lmadi: {0}").format(error)))
            return
        try:
            result = self._factory(conn).run()
        except sqlite3.Error as error:  # masalan, baza uzoq vaqt band bo'lsa — keyingi safar qayta uriniladi
            result = SyncResult(error=tr("Baza xatosi: {0}").format(error))
        finally:
            conn.close()
        self.done.emit(result)


class SyncController(QObject):
    """Sinxronlashni rejalashtiradi; natija `finished` signali bilan keladi."""

    finished = Signal(object)  # SyncResult

    def __init__(self, prefs: LocalPrefs, reconnect: Callable[[], sqlite3.Connection] | None, parent: QObject):
        super().__init__(parent)
        self._prefs = prefs
        self._reconnect = reconnect
        self._thread: _SyncThread | None = None
        self.last_result: SyncResult | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.sync_now)

    @property
    def available(self) -> bool:
        """Bu bazani sinxronlash mumkinmi (xotiradagi sinov bazasida — yo'q)."""
        return self._reconnect is not None

    @property
    def configured(self) -> bool:
        return self.available and synchronizer_factory(self._prefs) is not None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self) -> None:
        """Sozlangan bo'lsa — darhol va keyin muntazam sinxronlaydi."""
        if self.configured:
            self._timer.start(SYNC_INTERVAL_MS)
            self.sync_now()

    def stop(self) -> None:
        self._timer.stop()
        self.wait()

    def sync_now(self) -> None:
        factory = synchronizer_factory(self._prefs)
        if self.running or factory is None or self._reconnect is None:
            return
        self._thread = _SyncThread(self._reconnect, factory, self)
        self._thread.done.connect(self._finish)
        self._thread.start()

    def wait(self) -> None:
        """Boshlangan sinxronlash tugashini kutadi (bazani yopish yoki almashtirishdan oldin)."""
        if self.running:
            self._thread.wait(SHUTDOWN_WAIT_MS)

    def _finish(self, result: SyncResult) -> None:
        self.last_result = result
        self.finished.emit(result)


def describe(result: SyncResult | None) -> tuple[str, str]:
    """Holat yozuvi va izohi (sichqoncha ustida): yon menyu va sozlamalar uchun."""
    if result is None:
        return tr("☁ Sinxronlanmoqda…"), ""
    if result.offline:
        waiting = tr("{0} ta o'zgarish yuborilishini kutmoqda").format(result.waiting) if result.waiting else ""
        return tr("☁ Internet yo'q"), "\n".join(filter(None, (waiting, result.error)))
    if not result.ok:
        return tr("⚠ Sinxronlash xatosi"), result.error
    text = tr("☁ Sinxronlandi {0:%H:%M}").format(result.at)
    return text, tr("Yuborildi: {0}, olindi: {1}").format(result.sent, result.received)
