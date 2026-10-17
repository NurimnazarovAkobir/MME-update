"""Profil rasmi: fayldan tayyorlash, saqlash, olib tashlash va boshqa noutbukka o'tishi."""

import base64
import tempfile
from pathlib import Path
from unittest import mock

from PySide6.QtGui import QColor, QImage

from ombor.auth import Auth
from ombor.database import connect
from ombor.errors import WarehouseError
from ombor.folder_sync import FolderSynchronizer, SharedFolder
from ombor.models import Role
from ombor.session import Session
from ombor.ui.avatar import PHOTO_SIZE, avatar_pixmap, encode_photo
from ombor.ui.photo_crop import MAX_ZOOM, VIEW_SIZE, PhotoCropDialog
from ombor.ui.settings_page import SettingsPage
from tests.test_ui import UiTestCase


def picture(folder: Path, width: int = 800, height: int = 500) -> Path:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#3a7bd5"))
    path = folder / "rasm.png"
    image.save(str(path))
    return path


class ProfilePhotoTests(UiTestCase):
    def test_photo_is_cropped_square_and_small(self):
        encoded = encode_photo(str(picture(self.folder)))
        image = QImage.fromData(base64.b64decode(encoded))
        self.assertEqual((image.width(), image.height()), (PHOTO_SIZE, PHOTO_SIZE))
        self.assertLess(len(encoded), 60_000)

    def test_crop_starts_centered_and_follows_drag_and_zoom(self):
        image = QImage(800, 400, QImage.Format.Format_RGB32)
        image.fill(QColor("#ffffff"))
        for x in range(0, 100):
            for y in range(400):
                image.setPixelColor(x, y, QColor("#ff0000"))  # chap chetida qizil chiziq
        dialog = PhotoCropDialog(image)
        crop = dialog.cropped()
        self.assertEqual((crop.width(), crop.height()), (400, 400))  # boshida — o'rtadagi kvadrat
        self.assertEqual(crop.pixelColor(0, 0), QColor("#ffffff"))
        dialog.view.move_by(10_000, 0)  # rasm o'ngga surildi — chap qismi doira ichida, chetdan chiqmaydi
        crop = dialog.cropped()
        self.assertEqual(crop.width(), 400)
        self.assertEqual(crop.pixelColor(0, 0), QColor("#ff0000"))
        dialog.slider.setValue(dialog.slider.maximum())
        self.assertAlmostEqual(dialog.view.zoom, MAX_ZOOM)
        self.assertEqual(dialog.cropped().width(), round(VIEW_SIZE / (VIEW_SIZE / 400 * MAX_ZOOM)))
        dialog.view.set_zoom(1.0)
        self.assertEqual(dialog.slider.value(), 0)  # surgich kattalashtirishga ergashadi

    def test_cancel_in_crop_window_keeps_no_photo(self):
        page = SettingsPage(self.services, Session(self.keeper), self.folder / "ombor.db")
        with (
            mock.patch(
                "ombor.ui.settings_page.QFileDialog.getOpenFileName", return_value=(str(picture(self.folder)), "")
            ),
            mock.patch.object(PhotoCropDialog, "exec", return_value=PhotoCropDialog.DialogCode.Rejected),
        ):
            page._choose_photo()
        self.assertEqual(self.services.auth.photo(self.keeper.id), "")  # «Bekor qilish» — rasm qo'yilmadi

    def test_not_an_image_is_rejected(self):
        path = self.folder / "matn.png"
        path.write_text("rasm emas")
        with self.assertRaises(WarehouseError):
            encode_photo(str(path))

    def test_each_user_sets_own_photo_in_profile(self):
        page = SettingsPage(self.services, Session(self.keeper), self.folder / "ombor.db")
        changed = []
        page.photo_changed.connect(lambda: changed.append(True))
        with (
            mock.patch(
                "ombor.ui.settings_page.QFileDialog.getOpenFileName", return_value=(str(picture(self.folder)), "")
            ),
            mock.patch.object(PhotoCropDialog, "exec", return_value=PhotoCropDialog.DialogCode.Accepted),
        ):
            page._choose_photo()
        self.assertTrue(self.services.auth.photo(self.keeper.id))
        self.assertEqual(self.services.auth.photo(self.admin.id), "")  # boshqasiniki o'zgarmadi
        self.assertFalse(page._remove_photo.isHidden())
        page._save_photo("")
        self.assertEqual(self.services.auth.photo(self.keeper.id), "")
        self.assertEqual(changed, [True, True])

    def test_avatar_without_photo_shows_initial(self):
        pixmap = avatar_pixmap("Safo", "", 40)
        self.assertFalse(pixmap.isNull())
        self.assertEqual(pixmap.deviceIndependentSize().width(), 40)

    def test_chip_in_sidebar_shows_the_photo(self):
        window = self.window(self.admin)
        before = window._chip_avatar.pixmap().toImage()
        self.services.auth.set_photo(self.admin.id, encode_photo(str(picture(self.folder))))
        window._show_chip_photo()
        self.assertNotEqual(window._chip_avatar.pixmap().toImage(), before)

    def test_too_large_photo_is_refused(self):
        with self.assertRaises(WarehouseError):
            self.services.auth.set_photo(self.admin.id, "x" * 500_000)


class PhotoSyncTests(UiTestCase):
    def test_photo_reaches_the_other_laptop(self):
        drive = Path(tempfile.mkdtemp())
        boss = FolderSynchronizer(self.conn, SharedFolder(drive, "rahbar"))
        boss.publish()
        other = connect(":memory:")
        self.addCleanup(other.close)
        safo = FolderSynchronizer(other, SharedFolder(drive, "safo"))
        safo.join()
        photo = encode_photo(str(picture(self.folder)))
        self.services.auth.set_photo(self.admin.id, photo)
        boss.run()
        safo.run()
        admin = next(user for user in Auth(other).users() if user.role is Role.ADMIN)
        self.assertEqual(Auth(other).photo(admin.id), photo)
