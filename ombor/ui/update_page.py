"""«Yangilash» bo'limi: dastur holati, tekshirish tugmasi va yangi versiya chiqqanda — o'rnatish taklifi.

Yangi versiya haqidagi xabar oyna bo'lib chiqmaydi: menyuda belgi paydo bo'ladi va shu sahifada
«Yuklab olish va o'rnatish» havolasi ko'rinadi. Tekshiruv dastur ochilganda va keyin har bir necha
soatda fonda bajariladi; internet bo'lmasa, hech narsa bo'lmaydi.
"""

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QMessageBox, QProgressBar, QVBoxLayout, QWidget

from .. import update
from ..config import APP_NAME, APP_VERSION
from ..errors import WarehouseError
from ..formatting import fmt_date
from ..i18n import tr
from ..services import Services
from ..session import Session
from ..update import UPDATE_FOLDER_KEY, UPDATE_URL_KEY, Offer
from .extra_dialogs import NameDialog
from .icons import Glyph, icon_label
from .language import restart_application
from .updater import UpdateChecker
from .widgets import button, card, label

LAST_CHECK_KEY = "update_checked"  # shu kompyuterda oxirgi tekshiruv vaqti
FIRST_CHECK_DELAY_MS = 2_000  # dastur ochilgach, oyna chizilib bo'lgandan keyin
RECHECK_INTERVAL_MS = 30 * 60 * 1000  # dastur ochiq turganda har yarim soatda o'zi tekshiradi
STATUS_ICON_SIZE = 64


class UpdatePage(QWidget):
    """`availability_changed` — yangi versiya bor-yo'qligi o'zgarganda (menyudagi belgi uchun)."""

    availability_changed = Signal(bool)

    def __init__(self, services: Services, session: Session):
        super().__init__()
        self.setObjectName("page")
        self._settings = services.settings
        self._prefs = services.prefs
        self._offer: Offer | None = None
        self._announce_result = False  # qo'lda tekshirilganda «yangilanish yo'q» ham aytiladi

        self._checker = UpdateChecker(self)
        self._checker.checked.connect(self._on_checked)
        self._checker.progress.connect(self._on_progress)
        self._checker.installed.connect(self._on_installed)
        self._checker.failed.connect(self._on_failed)

        self._status_icon = icon_label(Glyph.CHECK, "statusGood")
        self._status_icon.setFixedSize(STATUS_ICON_SIZE, STATUS_ICON_SIZE)
        self._status_title = label("", "statusTitle")
        self._status_detail = label("", "muted")
        self._check_button = button(tr("Yangilanishlarni tekshirish"), "primary")
        self._check_button.clicked.connect(lambda: self.check(announce=True))

        status = QHBoxLayout()
        status.setSpacing(18)
        status.addWidget(self._status_icon)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(self._status_title)
        texts.addWidget(self._status_detail)
        status.addLayout(texts, stretch=1)
        status.addWidget(self._check_button)
        status.setAlignment(texts, Qt.AlignmentFlag.AlignVCenter)

        self._sources = label("", "muted")
        self._sources.setWordWrap(True)
        self._sources.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)
        layout.addWidget(label(tr("Yangilash"), "pageTitle"))
        layout.addLayout(status)
        layout.addWidget(self._build_offer_card())
        if session.is_admin:
            layout.addWidget(self._build_sources_card())
        layout.addStretch()

        self._show_state()
        QTimer.singleShot(FIRST_CHECK_DELAY_MS, self.check)
        self._recheck = QTimer(self)
        self._recheck.timeout.connect(self.check)
        self._recheck.start(RECHECK_INTERVAL_MS)

    @property
    def offered_version(self) -> str:
        """Topilgan yangi versiya raqami; yo'q bo'lsa — bo'sh."""
        return self._offer.version if self._offer else ""

    def refresh(self) -> None:
        self._show_state()

    def check(self, announce: bool = False) -> None:
        """Fonda tekshiradi. `announce` — natija topilmasa ham xabar beriladi (tugma bosilganda)."""
        self._announce_result = announce
        self._check_button.setEnabled(False)
        self._status_detail.setText(tr("Tekshirilmoqda…"))
        self._checker.check(self._settings.get(UPDATE_FOLDER_KEY), self._update_url())

    # --- Yangi versiya kartochkasi -------------------------------------------

    def _build_offer_card(self) -> QFrame:
        self._offer_text = label("", "sectionTitle")
        self._install_link = button(tr("Yuklab olish va o'rnatish"), "link")
        self._install_link.clicked.connect(self._install)
        self._dismiss = button("✕", "link")
        self._dismiss.setToolTip(tr("Hozircha yashirish"))
        self._dismiss.clicked.connect(lambda: self._offer_card.hide())
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.hide()

        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(12)
        line.addWidget(icon_label(Glyph.INFO, "iconAccent"))
        line.addWidget(self._offer_text, stretch=1)
        line.addWidget(self._install_link)
        line.addWidget(self._dismiss)
        self._offer_hint = label(tr("Ma'lumotlar saqlanib qoladi. O'rnatilgach, dastur o'zi qayta ochiladi."), "muted")
        self._offer_card = card(row, self._offer_hint, self._progress)
        self._offer_card.hide()
        return self._offer_card

    def _install(self) -> None:
        if self._offer is None:
            return
        if not update.is_installed_program():
            QMessageBox.information(self, tr("Yangilash"), tr("Yangilash faqat o'rnatilgan dasturda (exe) ishlaydi."))
            return
        self._set_installing(True)
        self._checker.install(self._offer)

    def _set_installing(self, installing: bool) -> None:
        for control in (self._install_link, self._dismiss, self._check_button):
            control.setEnabled(not installing)
        self._progress.setRange(0, 0)  # hajmi noma'lum bo'lsa — «kutish» ko'rinishi
        self._progress.setVisible(installing)
        self._offer_hint.setText(
            tr("Yangi versiya yuklab olinmoqda…")
            if installing
            else tr("Ma'lumotlar saqlanib qoladi. O'rnatilgach, dastur o'zi qayta ochiladi.")
        )

    # --- Tekshiruv natijalari --------------------------------------------------

    def _on_checked(self, offer: Offer | None) -> None:
        was_available = self._offer is not None
        self._offer = offer
        self._prefs.set(LAST_CHECK_KEY, datetime.now().isoformat(timespec="minutes"))
        self._check_button.setEnabled(True)
        self._show_state()
        if offer is not None:
            self._offer_card.show()
        if (offer is not None) != was_available:
            self.availability_changed.emit(offer is not None)
        if self._announce_result and offer is None:
            QMessageBox.information(
                self,
                tr("Yangilash"),
                tr("Yangi versiya topilmadi: sizda eng oxirgisi o'rnatilgan yoki hozir internetga chiqib bo'lmadi."),
            )
        self._announce_result = False

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(done)

    def _on_failed(self, message: str) -> None:
        self._set_installing(False)
        QMessageBox.warning(self, tr("Yangilash"), message)

    def _on_installed(self) -> None:
        QMessageBox.information(self, tr("Yangilash"), tr("Yangi versiya o'rnatildi. Dastur qayta ochiladi."))
        restart_application()

    def _show_state(self) -> None:
        available = self._offer is not None
        self._status_icon.setText(Glyph.SYNC if available else Glyph.CHECK)
        self._status_icon.setObjectName("statusAccent" if available else "statusGood")
        self._status_icon.style().unpolish(self._status_icon)
        self._status_icon.style().polish(self._status_icon)
        self._status_title.setText(tr("Yangilanish mavjud") if available else tr("Dastur yangilangan"))
        self._status_detail.setText(
            tr("Joriy versiya: {0}  ·  oxirgi tekshiruv: {1}").format(APP_VERSION, self._last_checked())
        )
        if available:
            self._offer_text.setText(tr("{0}, {1} versiyasi mavjud.").format(APP_NAME, self._offer.version))
        else:
            self._offer_card.hide()
        self._show_sources()

    def _last_checked(self) -> str:
        try:
            moment = datetime.fromisoformat(self._prefs.get(LAST_CHECK_KEY))
        except ValueError:
            return tr("hali tekshirilmagan")
        day = tr("bugun") if moment.date() == datetime.now().date() else fmt_date(moment.date())
        return f"{day}, {moment:%H:%M}"

    # --- Yangilanish manbalari (rahbar) ----------------------------------------

    def _build_sources_card(self) -> QFrame:
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 8, 0, 0)
        for text, handler in (
            (tr("Internet manzilini kiritish"), self._set_update_url),
            (tr("Yangilanishlar papkasini tanlash"), self._choose_update_folder),
            (tr("Fayldan yangilash"), self._update_from_file),
        ):
            action = button(text)
            action.clicked.connect(handler)
            row.addWidget(action)
        row.addStretch()
        explanation = label(
            tr(
                "Dastur yangi versiyani ikki joydan qidiradi: internetdagi manzildan (https) va yangilanishlar "
                "papkasidan. Har ikkalasida yangi MME-Ombor.exe va versiya.txt turishi kerak. Internet bo'lmasa, "
                "tekshiruv o'tkazib yuboriladi va dastur odatdagidek ishlaydi."
            )
        )
        explanation.setWordWrap(True)
        return card(label(tr("Yangilanish manbalari"), "sectionTitle"), explanation, self._sources, buttons)

    def _update_url(self) -> str:
        return update.update_url(self._settings.get(UPDATE_URL_KEY))

    def _show_sources(self) -> None:
        self._sources.setText(
            tr("Internetdagi manzil: {0}").format(self._update_url() or tr("kiritilmagan"))
            + "\n"
            + tr("Yangilanishlar papkasi: {0}").format(self._settings.get(UPDATE_FOLDER_KEY) or tr("tanlanmagan"))
        )

    def _set_update_url(self) -> None:
        title = tr("Internetdagi yangilanishlar manzili")
        dialog = NameDialog(title, {tr("Manzil (https://…)"): self._update_url()}, self)
        dialog.allow_empty = True
        if not dialog.exec():
            return
        try:
            self._settings.set(UPDATE_URL_KEY, update.check_url(dialog.names()[0]))
        except WarehouseError as error:
            QMessageBox.warning(self, tr("Yangilash"), str(error))
        self._show_sources()

    def _choose_update_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, tr("Yangilanishlar papkasi"), self._settings.get(UPDATE_FOLDER_KEY)
        )
        if folder:
            self._settings.set(UPDATE_FOLDER_KEY, folder)
            self._show_sources()

    def _update_from_file(self) -> None:
        if not update.is_installed_program():
            QMessageBox.information(self, tr("Yangilash"), tr("Yangilash faqat o'rnatilgan dasturda (exe) ishlaydi."))
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("Yangi versiya fayli"), "", tr("Dastur (*.exe)"))
        if not path:
            return
        try:
            update.install(path)
        except WarehouseError as error:
            QMessageBox.warning(self, tr("Yangilash"), str(error))
            return
        self._on_installed()
