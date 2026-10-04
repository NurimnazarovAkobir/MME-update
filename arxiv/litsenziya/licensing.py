"""Litsenziya: kompyuterga bog'langan, sotuvchi imzolagan kalit.

Kalit internetsiz tekshiriladi: dasturga faqat ochiq kalit (license_key.py)
qo'yilgan, imzo esa sotuvchida qoladigan maxfiy kalit bilan qo'yiladi.
Kalitsiz dastur sinov muddatida to'liq ishlaydi, keyin «faqat ko'rish»
rejimiga o'tadi — ma'lumotlar ko'rinadi, lekin o'zgartirib bo'lmaydi.
"""

import base64
import binascii
import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .errors import WarehouseError
from .formatting import fmt_date
from .i18n import tr
from .license_key import PUBLIC_KEY_HEX
from .settings import Settings

KEY_PREFIX = "MME1"
TRIAL_DAYS = 14
EXPIRY_WARNING_DAYS = 14
LICENSE_KEY = "license"
TRIAL_START_KEY = "trial_start"
LAST_SEEN_KEY = "last_seen"

MACHINE_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
MACHINE_CODE_GROUPS, MACHINE_CODE_GROUP_SIZE = 3, 4


# --- Kompyuter kodi --------------------------------------------------------


def machine_code() -> str:
    """Shu kompyuterning o'zgarmas qisqa kodi (masalan 'K7MP-2XQR-9BTN')."""
    digest = hashlib.sha256(f"mme-ombor:{_machine_id()}".encode()).digest()
    length = MACHINE_CODE_GROUPS * MACHINE_CODE_GROUP_SIZE
    characters = [MACHINE_CODE_ALPHABET[byte % len(MACHINE_CODE_ALPHABET)] for byte in digest[:length]]
    groups = [
        "".join(characters[start : start + MACHINE_CODE_GROUP_SIZE])
        for start in range(0, length, MACHINE_CODE_GROUP_SIZE)
    ]
    return "-".join(groups)


def _machine_id() -> str:
    """Windows o'rnatilganda beriladigan identifikator; o'qib bo'lmasa — tarmoq kartasi raqami."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            return winreg.QueryValueEx(key, "MachineGuid")[0]
    except (ImportError, OSError):
        return str(uuid.getnode())


def normalize_machine_code(code: str) -> str:
    return "".join(character for character in code.upper() if character.isalnum())


# --- Kalit -----------------------------------------------------------------


@dataclass(frozen=True)
class License:
    firm: str
    machine: str  # kompyuter kodi
    expires: date | None  # None — muddatsiz
    issued: date


def create_license(private_key: Ed25519PrivateKey, license: License) -> str:
    """Sotuvchi tomoni: litsenziyani imzolab, mijozga beriladigan kalit matnini qaytaradi."""
    payload = json.dumps(
        {
            "firm": license.firm,
            "machine": license.machine,
            "expires": license.expires.isoformat() if license.expires else None,
            "issued": license.issued.isoformat(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return ".".join((KEY_PREFIX, _encode(payload), _encode(private_key.sign(payload))))


def parse_license(key: str, public_key_hex: str = PUBLIC_KEY_HEX) -> License:
    """Kalit imzosini tekshirib, ichidagi litsenziyani qaytaradi; soxta yoki buzilgan kalitni rad etadi."""
    invalid = WarehouseError(tr("Litsenziya kaliti noto'g'ri. Kalitni to'liq va o'zgartirmasdan kiriting."))
    parts = "".join(key.split()).split(".")
    if len(parts) != 3 or parts[0] != KEY_PREFIX:
        raise invalid
    try:
        payload, signature = _decode(parts[1]), _decode(parts[2])
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex)).verify(signature, payload)
        data = json.loads(payload)
        return License(
            firm=data["firm"],
            machine=data["machine"],
            expires=date.fromisoformat(data["expires"]) if data["expires"] else None,
            issued=date.fromisoformat(data["issued"]),
        )
    except (InvalidSignature, binascii.Error, ValueError, KeyError, TypeError) as error:
        raise invalid from error


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# --- Holat -----------------------------------------------------------------


class LicenseStatus(Enum):
    ACTIVE = "active"
    TRIAL = "trial"
    EXPIRED = "expired"  # litsenziya yoki sinov muddati tugagan


@dataclass(frozen=True)
class LicenseState:
    status: LicenseStatus
    firm: str  # litsenziya egasi; sinov rejimida bo'sh
    expires: date | None
    days_left: int | None  # None — muddatsiz

    @property
    def read_only(self) -> bool:
        return self.status is LicenseStatus.EXPIRED

    @property
    def summary(self) -> str:
        """Foydalanuvchiga ko'rsatiladigan bir qatorli holat."""
        if self.status is LicenseStatus.TRIAL:
            return tr("Sinov muddati: {0} kun qoldi").format(self.days_left)
        if self.status is LicenseStatus.EXPIRED:
            return (
                tr("Litsenziya muddati tugagan — faqat ko'rish rejimi")
                if self.firm
                else tr("Sinov muddati tugagan — faqat ko'rish rejimi")
            )
        if self.expires is None:
            return tr("Litsenziya: muddatsiz")
        return tr("Litsenziya {0} gacha ({1} kun qoldi)").format(fmt_date(self.expires), self.days_left)

    @property
    def needs_attention(self) -> bool:
        """Muddat tugagan yoki tugashiga oz qolgan."""
        return self.read_only or (self.days_left is not None and self.days_left <= EXPIRY_WARNING_DAYS)


class Licensing:
    def __init__(self, conn: sqlite3.Connection, machine: str | None = None, public_key_hex: str = PUBLIC_KEY_HEX):
        self._settings = Settings(conn)
        self.machine = machine or machine_code()
        self._public_key_hex = public_key_hex

    def state(self, today: date | None = None) -> LicenseState:
        today = self._effective_today(today or date.today())
        license = self._stored_license()
        if license is not None:
            return self._license_state(license, today)

        trial_start = self._settings.get(TRIAL_START_KEY)
        if not trial_start:
            trial_start = today.isoformat()
            self._settings.set(TRIAL_START_KEY, trial_start)
        trial_end = date.fromisoformat(trial_start) + timedelta(days=TRIAL_DAYS)
        days_left = (trial_end - today).days
        status = LicenseStatus.TRIAL if days_left > 0 else LicenseStatus.EXPIRED
        return LicenseState(status, "", trial_end, max(days_left, 0))

    def activate(self, key: str, today: date | None = None) -> LicenseState:
        """Kalitni tekshirib saqlaydi; boshqa kompyuterga berilgan yoki muddati o'tgan kalitni rad etadi."""
        license = parse_license(key, self._public_key_hex)
        if normalize_machine_code(license.machine) != normalize_machine_code(self.machine):
            raise WarehouseError(
                tr("Bu kalit boshqa kompyuter uchun berilgan ({0}). Shu kompyuterning kodi: {1}.").format(
                    license.machine, self.machine
                )
            )
        state = self._license_state(license, self._effective_today(today or date.today()))
        if state.read_only:
            raise WarehouseError(tr("Bu kalitning muddati {0} da tugagan.").format(fmt_date(license.expires)))
        self._settings.set(LICENSE_KEY, "".join(key.split()))
        return state

    def _stored_license(self) -> License | None:
        """Saqlangan kalit; boshqa kompyuterdan ko'chirilgan yoki buzilgan bo'lsa — None."""
        key = self._settings.get(LICENSE_KEY)
        if not key:
            return None
        try:
            license = parse_license(key, self._public_key_hex)
        except WarehouseError:
            return None
        same_machine = normalize_machine_code(license.machine) == normalize_machine_code(self.machine)
        return license if same_machine else None

    @staticmethod
    def _license_state(license: License, today: date) -> LicenseState:
        if license.expires is None:
            return LicenseState(LicenseStatus.ACTIVE, license.firm, None, None)
        days_left = (license.expires - today).days + 1  # tugash kuni ham ishlaydi
        status = LicenseStatus.ACTIVE if days_left > 0 else LicenseStatus.EXPIRED
        return LicenseState(status, license.firm, license.expires, max(days_left, 0))

    def _effective_today(self, today: date) -> date:
        """Kompyuter soati orqaga surilgan bo'lsa, dastur ko'rgan eng oxirgi sanani ishlatadi."""
        last_seen = self._settings.get(LAST_SEEN_KEY)
        if last_seen and date.fromisoformat(last_seen) > today:
            return date.fromisoformat(last_seen)
        if last_seen != today.isoformat():
            self._settings.set(LAST_SEEN_KEY, today.isoformat())
        return today
