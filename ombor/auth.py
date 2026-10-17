"""Foydalanuvchilar, parollar va parolni tiklash kodi.

Parollarning o'zi saqlanmaydi — faqat tuz (salt) qo'shib hisoblangan xeshi.
Parol dasturga kirishni cheklaydi; ma'lumotlar fayli shifrlanmaydi.
"""

import hashlib
import hmac
import secrets
from typing import Callable

from .driver import sqlite3
from .errors import WarehouseError
from .i18n import tr
from .models import Role, User
from .settings import Settings
from .vault import Vault

MIN_PASSWORD_LENGTH = 4
MAX_PHOTO_CHARS = 400_000  # base64 dagi rasm (≈300 KB); oyna uni oldindan 256×256 gacha kichraytiradi
HASH_ITERATIONS = 200_000
SALT_BYTES = 16

RECOVERY_KEY = "recovery_code"
# Bir-biriga o'xshash belgilarsiz (0/O, 1/I/L), qog'ozdan ko'chirish oson bo'lishi uchun.
RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
RECOVERY_GROUPS, RECOVERY_GROUP_SIZE = 3, 4


def _make_hash(secret: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    return f"{salt.hex()}:{_digest(secret, salt).hex()}"


def _matches(secret: str, stored: str) -> bool:
    salt_hex, hash_hex = stored.split(":")
    return hmac.compare_digest(_digest(secret, bytes.fromhex(salt_hex)), bytes.fromhex(hash_hex))


def _digest(secret: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, HASH_ITERATIONS)


def _check_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WarehouseError(tr("Parol kamida {0} ta belgidan iborat bo'lishi kerak.").format(MIN_PASSWORD_LENGTH))


def _normalize_code(code: str) -> str:
    return "".join(character for character in code.upper() if character.isalnum())


class Auth:
    def __init__(self, conn: sqlite3.Connection, vault: Vault | None = None):
        """`vault` — baza shifrlangan bo'lsa, har bir parol o'zgarishi kalit fayliga ham yoziladi."""
        self._conn = conn
        self._settings = Settings(conn)
        self._vault = vault if vault is not None and vault.unlocked else None

    # --- Foydalanuvchilar --------------------------------------------------

    def users(self) -> list[User]:
        rows = self._conn.execute("SELECT id, name, role FROM users ORDER BY name")
        return [User(row["id"], row["name"], Role(row["role"])) for row in rows]

    def user(self, user_id: int) -> User | None:
        """Hisobning bazadagi hozirgi holati; o'chirilgan bo'lsa — None."""
        row = self._conn.execute("SELECT id, name, role FROM users WHERE id = ?", (user_id,)).fetchone()
        return User(row["id"], row["name"], Role(row["role"])) if row else None

    # --- Profil rasmi --------------------------------------------------------

    def photo(self, user_id: int) -> str:
        """Profil rasmi (kvadrat JPEG, base64); rasm qo'yilmagan bo'lsa — bo'sh qator."""
        row = self._conn.execute("SELECT photo FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["photo"] if row else ""

    def set_photo(self, user_id: int, photo: str) -> None:
        """Rasmni almashtiradi (bo'sh qator — rasmni olib tashlash). Umumiy bazada boshqa kompyuterlarga ham o'tadi."""
        if len(photo) > MAX_PHOTO_CHARS:
            raise WarehouseError(tr("Rasm juda katta."))
        with self._conn:
            self._conn.execute("UPDATE users SET photo = ? WHERE id = ?", (photo, user_id))

    def add_user(self, name: str, password: str, role: Role) -> User:
        name = name.strip()
        if not name:
            raise WarehouseError(tr("Foydalanuvchi ismini kiriting."))
        _check_new_password(password)
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "INSERT INTO users (name, password, role) VALUES (?, ?, ?)",
                    (name, _make_hash(password), role.value),
                )
        except sqlite3.IntegrityError as error:
            raise WarehouseError(tr("«{0}» ismli foydalanuvchi allaqachon bor.").format(name)) from error
        user = User(cursor.lastrowid, name, role)
        if self._vault:
            self._vault.set_user(user, password)
        return user

    def delete_user(self, user_id: int) -> None:
        remaining_admins = [user for user in self.users() if user.is_admin and user.id != user_id]
        if not remaining_admins:
            raise WarehouseError(tr("Oxirgi rahbarni o'chirib bo'lmaydi: dasturni boshqaradigan odam qolmaydi."))
        with self._conn:
            self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        if self._vault:
            self._vault.remove_user(user_id)

    # --- Parollar ----------------------------------------------------------

    def login(self, user_id: int, password: str) -> User:
        row = self._conn.execute("SELECT id, name, role, password FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None or not _matches(password, row["password"]):
            raise WarehouseError(tr("Parol noto'g'ri."))
        return User(row["id"], row["name"], Role(row["role"]))

    def change_password(self, user_id: int, current: str, new: str) -> None:
        """Foydalanuvchi o'z parolini almashtiradi."""
        try:
            self.login(user_id, current)
        except WarehouseError:
            raise WarehouseError(tr("Joriy parol noto'g'ri.")) from None
        self.set_password(user_id, new)

    def set_password(self, user_id: int, new: str) -> None:
        """Parolni eskisini so'ramasdan o'rnatadi (rahbar boshqa foydalanuvchi uchun)."""
        _check_new_password(new)
        with self._conn:
            self._conn.execute("UPDATE users SET password = ? WHERE id = ?", (_make_hash(new), user_id))
        if self._vault:
            self._vault.set_user(next(user for user in self.users() if user.id == user_id), new)

    # --- Tiklash kodi ------------------------------------------------------

    def has_recovery_code(self) -> bool:
        return bool(self._settings.get(RECOVERY_KEY))

    def new_recovery_code(self) -> str:
        """Yangi kod yaratadi (eskisi bekor bo'ladi). Kod faqat shu yerda bir marta ko'rinadi."""
        groups = [
            "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_GROUP_SIZE))
            for _ in range(RECOVERY_GROUPS)
        ]
        code = "-".join(groups)
        self._settings.set(RECOVERY_KEY, _make_hash(_normalize_code(code)))
        if self._vault:
            self._vault.set_recovery_code(code)
        return code

    def reset_with_recovery_code(self, user_id: int, code: str, new: str) -> None:
        """Parol unutilganda: tiklash kodi to'g'ri bo'lsa, yangi parol o'rnatadi."""
        stored = self._settings.get(RECOVERY_KEY)
        if not stored or not _matches(_normalize_code(code), stored):
            raise WarehouseError(tr("Tiklash kodi noto'g'ri."))
        self.set_password(user_id, new)


class LockedAuth:
    """Shifrlangan bazaga kirish: foydalanuvchilar ro'yxati kalit faylidan olinadi, baza parol to'g'ri bo'lgachgina ochiladi.

    Kirish oynasi uchun `Auth` bilan bir xil ko'rinishda. Kirilgach, ochilgan ulanish — `conn`.
    """

    def __init__(self, vault: Vault, open_database: Callable[[str], sqlite3.Connection]):
        """`open_database` — kalit bo'yicha bazaga ulanadigan funksiya."""
        self._vault = vault
        self._open = open_database
        self.conn: sqlite3.Connection | None = None

    def users(self) -> list[User]:
        return self._vault.users()

    def login(self, user_id: int, password: str) -> User:
        key = self._vault.unlock(user_id, password)
        self.conn = self.conn or self._open(key)
        return Auth(self.conn, self._vault).login(user_id, password)

    def has_recovery_code(self) -> bool:
        return self._vault.has_recovery_code()

    def new_recovery_code(self) -> str:
        return Auth(self.conn, self._vault).new_recovery_code()

    def reset_with_recovery_code(self, user_id: int, code: str, new: str) -> None:
        """Tiklash kodi baza kalitini ochadi; yangi parol bazaga ham, kalit fayliga ham yoziladi."""
        _check_new_password(new)
        self.conn = self.conn or self._open(self._vault.unlock_with_code(code))
        Auth(self.conn, self._vault).set_password(user_id, new)
