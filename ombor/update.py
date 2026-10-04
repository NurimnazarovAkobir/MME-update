"""Dasturni yangilash: yangi exe faylini joriysining o'rniga qo'yadi.

Dastur internetga chiqmaydi. Yangi versiya ikki yo'l bilan o'rnatiladi:
- qo'lda: «Sozlamalar»da yangi `MME-Ombor.exe` fayli ko'rsatiladi;
- o'zi: rahbar «yangilanishlar papkasi»ni (masalan, tarmoqdagi umumiy papka) belgilaydi; u yerga
  yangi `MME-Ombor.exe` va `versiya.txt` qo'yilsa, har bir kompyuter ochilganda yangilashni taklif qiladi.
"""

import os
import shutil
import sys
from pathlib import Path

from .config import APP_VERSION
from .errors import WarehouseError
from .i18n import tr

UPDATE_FOLDER_KEY = "update_folder"
EXE_NAME = "MME-Ombor.exe"
VERSION_FILE = "versiya.txt"
OLD_SUFFIX = "-eski.exe"


def parse_version(text: str) -> tuple[int, ...]:
    """'1.10' -> (1, 10); tushunarsiz matn — bo'sh (har qanday versiyadan kichik)."""
    try:
        return tuple(int(part) for part in text.strip().split("."))
    except ValueError:
        return ()


def available(folder: Path | str, current: str = APP_VERSION) -> tuple[str, Path] | None:
    """`folder` da joriysidan yangiroq versiya bo'lsa — (versiya, exe yo'li); bo'lmasa yoki papkaga yetib bo'lmasa — None."""
    folder = Path(folder)
    try:
        version = (folder / VERSION_FILE).read_text(encoding="utf-8").strip()
        has_exe = (folder / EXE_NAME).is_file()
    except OSError:
        return None
    if not has_exe or parse_version(version) <= parse_version(current):
        return None
    return version, folder / EXE_NAME


def is_installed_program() -> bool:
    """Dastur yig'ilgan exe sifatida ishlayaptimi (manba koddan ishga tushirilganda yangilab bo'lmaydi)."""
    return bool(getattr(sys, "frozen", False))


def install(new_exe: Path | str, current_exe: Path | str | None = None) -> None:
    """Joriy exe ni `new_exe` bilan almashtiradi; eskisi yonida «-eski» nomi bilan qoladi.

    Ishlab turgan exe ni o'chirib bo'lmaydi, lekin nomini o'zgartirish mumkin — shuning uchun avval
    nomi o'zgartiriladi, keyin yangisi uning joyiga ko'chiriladi. Shundan keyin dastur qayta ochilishi kerak.
    """
    new_exe = Path(new_exe)
    current = Path(current_exe or sys.executable)
    if not new_exe.is_file() or new_exe.suffix.lower() != ".exe":
        raise WarehouseError(tr("Yangi versiya fayli (MME-Ombor.exe) topilmadi."))
    if new_exe.resolve() == current.resolve():
        raise WarehouseError(tr("Bu — hozir ishlab turgan dasturning o'zi. Yangi versiya faylini tanlang."))
    old = current.with_name(current.stem + OLD_SUFFIX)
    try:
        old.unlink(missing_ok=True)
        os.replace(current, old)
    except OSError as error:
        raise WarehouseError(tr("Dastur faylini almashtirib bo'lmadi. Dastur papkasiga yozish huquqi yo'q.")) from error
    try:
        shutil.copy2(new_exe, current)
    except OSError as error:
        os.replace(old, current)  # eski holatga qaytarish
        raise WarehouseError(tr("Yangi versiyani ko'chirib bo'lmadi. Dastur o'zgarmadi.")) from error


def remove_old_version(current_exe: Path | str | None = None) -> None:
    """Oldingi yangilashdan qolgan eski exe ni o'chiradi (hali band bo'lsa — keyingi safar)."""
    current = Path(current_exe or sys.executable)
    try:
        current.with_name(current.stem + OLD_SUFFIX).unlink(missing_ok=True)
    except OSError:
        pass
