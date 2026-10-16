"""Avtomatik qulflash: qulf ekrani, foydalanuvchi bo'yicha vaqt va sozlamalar."""

from unittest import mock

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from ombor.session import Session
from ombor.ui.lock_screen import DEFAULT_LOCK_MINUTES, LockScreen, lock_minutes, set_lock_minutes
from ombor.ui.settings_page import SettingsPage
from tests.test_ui import UiTestCase


class LockScreenTests(UiTestCase):
    def test_each_user_unlocks_with_own_password(self):
        for user, password in ((self.admin, "parol-1"), (self.keeper, "parol-2")):
            screen = LockScreen(self.services.auth, user, 5)
            self.assertFalse(screen.unlock("parol-3"))
            self.assertTrue(screen._error.text())
            self.assertTrue(screen.unlock(password))

    def test_escape_does_not_unlock(self):
        screen = LockScreen(self.services.auth, self.admin, 5)
        screen.show()
        screen.reject()
        self.assertTrue(screen.isVisible())

    def test_lock_time_is_kept_per_user(self):
        prefs = self.services.prefs
        self.assertEqual(lock_minutes(prefs, self.admin), DEFAULT_LOCK_MINUTES)
        set_lock_minutes(prefs, self.admin, 1)
        set_lock_minutes(prefs, self.keeper, 60)
        self.assertEqual((lock_minutes(prefs, self.admin), lock_minutes(prefs, self.keeper)), (1, 60))
        set_lock_minutes(prefs, self.keeper, 0)
        self.assertEqual(lock_minutes(prefs, self.keeper), 0)

    def test_window_locks_hides_everything_and_unlocks(self):
        window = self.window(self.keeper)
        window.show()
        seen = {}

        def type_password():
            screen = window._auto_lock._screen
            seen["locked"] = window._auto_lock.is_locked
            seen["opacity"] = window.windowOpacity()
            screen.unlock("parol-2")

        QTimer.singleShot(0, type_password)
        window._auto_lock.lock()
        self.assertEqual(seen, {"locked": True, "opacity": 0.0})
        self.assertFalse(window._auto_lock.is_locked)
        self.assertEqual(window.windowOpacity(), 1.0)

    def test_inactivity_timer_follows_the_setting(self):
        window = self.window(self.admin)
        page = SettingsPage(self.services, Session(self.admin), self.folder / "ombor.db")
        page.lock_minutes_changed.connect(window._auto_lock.set_minutes)
        page._change_lock_minutes(1)
        self.assertEqual(window._auto_lock._timer.interval(), 60_000)
        self.assertTrue(window._auto_lock._timer.isActive())
        page._change_lock_minutes(0)
        self.assertFalse(window._auto_lock._timer.isActive())

    def test_activity_restarts_the_timer(self):
        window = self.window(self.admin)
        auto_lock = window._auto_lock
        with mock.patch.object(auto_lock, "_restart") as restart:
            key = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(window, key)
        restart.assert_called()
