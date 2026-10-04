"""Bazani shifrlash kaliti.

Shifrlash yoqilganda baza fayli (SQLCipher, AES-256) tasodifiy kalit bilan shifrlanadi.
Kalitning o'zi hech qayerda ochiq saqlanmaydi: baza yonidagi `ombor.kalit` faylida har bir
foydalanuvchi uchun uning paroli bilan (va tiklash kodi bilan) o'ralgan nusxasi turadi.
Parolni bilmagan odam bazani ham, kalit faylini ham o'qiy olmaydi.

Kalit fayli yo'qolsa, shifrlangan bazani ochib bo'lmaydi — shuning uchun u har bir zaxira
nusxa yoniga ko'chiriladi.
"""

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from .database import open_raw, schema_version
from .driver import sqlite3
from .errors import WarehouseError
from .i18n import tr
from .models import Role, User

KEY_SUFFIX = ".kalit"
KEY_BYTES = 32
SALT_BYTES = 16
ITERATIONS = 200_000
TEMPORARY_SUFFIX = ".yangi"


def _stretch(secret: str, salt: bytes) -> tuple[bytes, bytes]:
    """Paroldan ikkita kalit: biri o'rash uchun, ikkinchisi to'g'riligini tekshirish uchun."""
    material = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, ITERATIONS, dklen=2 * KEY_BYTES)
    return material[:KEY_BYTES], material[KEY_BYTES:]


def _wrap(key: str, secret: str) -> dict:
    salt = secrets.token_bytes(SALT_BYTES)
    pad, check_key = _stretch(secret, salt)
    wrapped = bytes(a ^ b for a, b in zip(bytes.fromhex(key), pad))
    return {"salt": salt.hex(), "wrapped": wrapped.hex(), "check": hmac.new(check_key, wrapped, "sha256").hexdigest()}


def _unwrap(entry: dict, secret: str) -> str | None:
    """O'ralgan kalitni ochadi; parol (yoki kod) noto'g'ri bo'lsa — None."""
    pad, check_key = _stretch(secret, bytes.fromhex(entry["salt"]))
    wrapped = bytes.fromhex(entry["wrapped"])
    if not hmac.compare_digest(hmac.new(check_key, wrapped, "sha256").hexdigest(), entry["check"]):
        return None
    return bytes(a ^ b for a, b in zip(wrapped, pad)).hex()


def _normalize_code(code: str) -> str:
    return "".join(character for character in code.upper() if character.isalnum())


class Vault:
    """Bitta bazaning kalit fayli. `key` — dasturga kirilgach xotirada turadigan baza kaliti."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.path = self.db_path.with_suffix(KEY_SUFFIX)
        self.key: str | None = None

    @property
    def enabled(self) -> bool:
        """Baza shifrlanganmi (kalit fayli bormi)."""
        return self.path.is_file()

    @property
    def unlocked(self) -> bool:
        return self.enabled and self.key is not None

    # --- Kirish --------------------------------------------------------------

    def users(self) -> list[User]:
        """Kira oladigan foydalanuvchilar (baza hali ochilmagan paytda ro'yxat shu fayldan olinadi)."""
        entries = self._read()["users"]
        users = [User(int(user_id), entry["name"], Role(entry["role"])) for user_id, entry in entries.items()]
        return sorted(users, key=lambda user: user.name.casefold())

    def unlock(self, user_id: int, password: str) -> str:
        entry = self._read()["users"].get(str(user_id))
        key = _unwrap(entry, password) if entry else None
        if key is None:
            raise WarehouseError(tr("Parol noto'g'ri."))
        self.key = key
        return key

    def unlock_with_code(self, code: str) -> str:
        entry = self._read().get("recovery")
        key = _unwrap(entry, _normalize_code(code)) if entry else None
        if key is None:
            raise WarehouseError(tr("Tiklash kodi noto'g'ri."))
        self.key = key
        return key

    def has_recovery_code(self) -> bool:
        return bool(self._read().get("recovery"))

    # --- Kalitni foydalanuvchilarga berish (baza ochiq bo'lganda) -------------

    def set_user(self, user: User, password: str) -> None:
        """Foydalanuvchiga uning (yangi) paroli bilan kirish imkonini beradi."""
        data = self._read()
        data["users"][str(user.id)] = {"name": user.name, "role": user.role.value, **_wrap(self._key(), password)}
        self._write(data)

    def remove_user(self, user_id: int) -> None:
        data = self._read()
        data["users"].pop(str(user_id), None)
        self._write(data)

    def set_recovery_code(self, code: str) -> None:
        data = self._read()
        data["recovery"] = _wrap(self._key(), _normalize_code(code))
        self._write(data)

    # --- Shifrlashni yoqish va o'chirish --------------------------------------

    def encrypt(self, conn: sqlite3.Connection, admin: User, password: str, recovery_code: str) -> None:
        """Ochiq bazani shifrlangan nusxasi bilan almashtiradi. `conn` yopiladi; keyin dastur qayta ochilishi kerak.

        Kalit faqat `admin` ga (uning paroli bilan) va tiklash kodiga beriladi; boshqa foydalanuvchilar
        rahbar ularning parolini qayta o'rnatgach kira oladi.
        """
        key = secrets.token_hex(KEY_BYTES)
        self._export(conn, f"\"x'{key}'\"")
        self._verify(key)
        data = {
            "version": 1,
            "users": {str(admin.id): {"name": admin.name, "role": admin.role.value, **_wrap(key, password)}},
            "recovery": _wrap(key, _normalize_code(recovery_code)),
        }
        # Kalit fayli avval yoniga yoziladi: baza almashtirilgach, uni joyiga qo'yish faqat nom o'zgartirish bo'ladi.
        prepared = self.path.with_suffix(KEY_SUFFIX + TEMPORARY_SUFFIX)
        prepared.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        conn.close()
        os.replace(self._temporary(), self.db_path)
        os.replace(prepared, self.path)
        self.key = key

    def decrypt(self, conn: sqlite3.Connection) -> None:
        """Shifrlangan bazani ochiq nusxasi bilan almashtiradi va kalit faylini o'chiradi. `conn` yopiladi."""
        self._export(conn, "''")
        self._verify(None)
        conn.close()
        os.replace(self._temporary(), self.db_path)
        self.path.unlink()
        self.key = None

    def copy_key_file(self, target: Path) -> None:
        """Kalit faylini zaxira nusxa yoniga ko'chiradi (shifrlash yoqilmagan bo'lsa, hech narsa qilmaydi)."""
        if self.enabled:
            Path(target).write_bytes(self.path.read_bytes())

    # --- Ichki ---------------------------------------------------------------

    def _temporary(self) -> Path:
        return self.db_path.with_suffix(TEMPORARY_SUFFIX)

    def _export(self, conn: sqlite3.Connection, key_clause: str) -> None:
        """Bazaning to'liq nusxasini boshqa kalit bilan (yoki kalitsiz) vaqtinchalik faylga yozadi."""
        temporary = self._temporary()
        temporary.unlink(missing_ok=True)
        conn.commit()
        conn.execute(f"ATTACH DATABASE ? AS copy KEY {key_clause}", (str(temporary),))
        try:
            conn.execute("SELECT sqlcipher_export('copy')")
            conn.execute(f"PRAGMA copy.user_version = {schema_version(conn)}")
        finally:
            conn.execute("DETACH DATABASE copy")

    def _verify(self, key: str | None) -> None:
        """Yangi nusxa ochilishini va yozuvlari joyida ekanini tekshiradi — asl fayl shundan keyingina almashtiriladi."""
        copy = open_raw(self._temporary(), key)
        try:
            copy.execute("SELECT COUNT(*) FROM movements").fetchone()
            copy.execute("SELECT COUNT(*) FROM users").fetchone()
        except sqlite3.DatabaseError as error:
            raise WarehouseError(
                tr("Bazaning yangi nusxasini tekshirib bo'lmadi. Hech narsa o'zgartirilmadi.")
            ) from error
        finally:
            copy.close()

    def _key(self) -> str:
        if self.key is None:
            raise RuntimeError("Baza kaliti hali ochilmagan")
        return self.key

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise WarehouseError(
                tr("Kalit faylini o'qib bo'lmadi: {0}. Usiz shifrlangan bazani ochib bo'lmaydi.").format(self.path)
            ) from error

    def _write(self, data: dict) -> None:
        """Avval yoniga yozib, keyin almashtiradi: yozish paytida uzilish kalit faylini buzmaydi."""
        temporary = self.path.with_suffix(KEY_SUFFIX + TEMPORARY_SUFFIX)
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporary, self.path)
