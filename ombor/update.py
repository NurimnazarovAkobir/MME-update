"""Dasturni yangilash: yangi exe faylini joriysining o'rniga qo'yadi.

Yangi versiya uch yo'l bilan o'rnatiladi:
- qo'lda: «Sozlamalar»da yangi `MME-Ombor.exe` fayli ko'rsatiladi;
- papkadan: rahbar «yangilanishlar papkasi»ni (masalan, tarmoqdagi umumiy papka) belgilaydi; u yerga
  yangi `MME-Ombor.exe` va `versiya.txt` qo'yilsa, har bir kompyuter ochilganda yangilashni taklif qiladi;
- internetdan: xuddi shu ikki fayl internetdagi manzilga (https) qo'yiladi; dastur ochilganda fonda
  tekshiradi. Internet bo'lmasa, tekshiruv jimgina o'tkazib yuboriladi — dastur ishlayveradi.
"""

import http.client
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import APP_VERSION, DEFAULT_UPDATE_URL
from .errors import WarehouseError
from .i18n import tr

UPDATE_FOLDER_KEY = "update_folder"
EXE_NAME = "MME-Ombor.exe"
VERSION_FILE = "versiya.txt"
OLD_SUFFIX = "-eski.exe"
TRIAL_ARGUMENT = "--sinov"  # bu bilan ochilgan dastur darhol yopiladi (main.py)
TRIAL_TIMEOUT_SECONDS = 120
TRIAL_ATTEMPTS, TRIAL_PAUSE_SECONDS = 3, 10
BLOCKED_BY_POLICY = 4551  # Windows xatosi: «An Application Control policy has blocked this file»
UPDATE_URL_KEY = "update_url"
CHECK_TIMEOUT_SECONDS = 6  # internet sekin yoki yo'q bo'lsa, tekshiruv shundan uzoq kutmaydi
DOWNLOAD_TIMEOUT_SECONDS = 30
DOWNLOAD_CHUNK = 256 * 1024
MIN_EXE_BYTES = 1024 * 1024  # bundan kichik fayl dastur emas (masalan, xato sahifasi)


@dataclass(frozen=True)
class Offer:
    """Topilgan yangi versiya: papkadagi tayyor fayl (`exe`) yoki internetdan yuklab olinadigan (`url`)."""

    version: str
    exe: Path | None = None
    url: str = ""


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


def is_windows_program(path: Path | str) -> bool:
    """Fayl haqiqiy Windows dasturimi (sarlavhasi bo'yicha).

    Dastur bo'lmagan faylni (masalan, chala yuklangan yoki buzilgan) ishga tushirishga urinilsa, Windows
    «Unsupported 16-Bit Application» degan oyna chiqaradi — shuning uchun avval sarlavhasi tekshiriladi.
    """
    try:
        with open(path, "rb") as file:
            header = file.read(64)
            if len(header) < 64 or header[:2] != b"MZ":
                return False
            file.seek(int.from_bytes(header[60:64], "little"))
            return file.read(4) == b"PE\0\0"
    except OSError:
        return False


def can_run(exe: Path | str) -> bool:
    """Windows shu faylni ishga tushirishga ruxsat beradimi.

    Imzolanmagan dasturni Smart App Control ba'zan bloklaydi; bunday nusxani o'rnatib (yoki tarqatib)
    bo'lmaydi — aks holda ishlab turgan dastur ochilmaydigan nusxa bilan almashib qoladi.

    Smart App Control ning qarori barqaror emas: bitta faylni goh o'tkazadi, goh bloklaydi. Shuning uchun
    birinchi rad javobida darhol voz kechilmaydi — bir necha marta, oraliq bilan urinib ko'riladi.
    """
    if not is_windows_program(exe):
        return False
    for attempt in range(TRIAL_ATTEMPTS):
        if attempt:
            time.sleep(TRIAL_PAUSE_SECONDS)
        try:
            process = subprocess.Popen([str(exe), TRIAL_ARGUMENT])
        except OSError as error:
            if getattr(error, "winerror", None) != BLOCKED_BY_POLICY:
                return False  # bu umuman dastur emas — qayta urinishdan foyda yo'q
            continue
        try:
            return process.wait(TRIAL_TIMEOUT_SECONDS) == 0
        except subprocess.TimeoutExpired:
            process.kill()  # eski nusxa sinov belgisini tushunmay ochilib qolgan: demak, ishga tushdi
            return True
    return False


def install(
    new_exe: Path | str, current_exe: Path | str | None = None, verify: Callable[[Path], bool] = can_run
) -> None:
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
    if not verify(new_exe):
        raise WarehouseError(
            tr(
                "Windows (Smart App Control) yangi versiyani ishga tushirishga ruxsat bermadi. "
                "Dastur o'zgarmadi — hozirgi versiyada ishlayverasiz."
            )
        )
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


# --- Internet orqali -----------------------------------------------------------


def update_url(stored: str) -> str:
    """Yangilanishlar manzili: sozlamada kiritilgani, bo'lmasa — dasturga yozib qo'yilgani."""
    return (stored or DEFAULT_UPDATE_URL).strip()


def check_url(url: str) -> str:
    """Manzilni tekshirib, tartibga keltiradi; faqat himoyalangan (https) manzil qabul qilinadi."""
    url = url.strip()
    if url and not url.lower().startswith("https://"):
        raise WarehouseError(tr("Manzil https:// bilan boshlanishi kerak."))
    return url


def _file_url(base_url: str, name: str) -> str:
    return base_url.rstrip("/") + "/" + name


def online_version(base_url: str, timeout: float = CHECK_TIMEOUT_SECONDS) -> str | None:
    """Internetdagi versiya raqami; internet yo'q, manzil xato yoki fayl topilmasa — None (xato ko'tarilmaydi)."""
    try:
        with urllib.request.urlopen(_file_url(base_url, VERSION_FILE), timeout=timeout) as response:
            text = response.read(64).decode("utf-8", errors="replace").strip()
    except (OSError, ValueError, http.client.HTTPException):
        return None
    return text if parse_version(text) else None


def available_online(base_url: str, current: str = APP_VERSION) -> str | None:
    """Internetda joriysidan yangiroq versiya bo'lsa — uning raqami; aks holda yoki internet bo'lmasa — None."""
    if not base_url:
        return None
    version = online_version(base_url)
    return version if version and parse_version(version) > parse_version(current) else None


def download(base_url: str, target: Path | str, progress: Callable[[int, int], None] | None = None) -> Path:
    """Yangi exe ni `target` ga yuklab oladi; `progress(yuklangan, jami)` har bo'lakda chaqiriladi.

    Yuklash uzilib qolsa yoki fayl dasturga o'xshamasa, yarim fayl o'chiriladi va WarehouseError ko'tariladi.
    """
    target = Path(target)
    partial = target.with_suffix(".qism")
    try:
        with urllib.request.urlopen(_file_url(base_url, EXE_NAME), timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with open(partial, "wb") as file:
                while chunk := response.read(DOWNLOAD_CHUNK):
                    file.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        if done < MIN_EXE_BYTES or (total and done != total):
            raise OSError("incomplete download")
        os.replace(partial, target)
    except (OSError, ValueError, http.client.HTTPException) as error:
        partial.unlink(missing_ok=True)
        raise WarehouseError(
            tr("Yangi versiyani yuklab bo'lmadi. Internetni tekshirib, keyinroq qayta urinib ko'ring.")
        ) from error
    return target


def find(folder: str, url: str, current: str = APP_VERSION) -> Offer | None:
    """Yangi versiyani avval yangilanishlar papkasidan, keyin internetdan qidiradi; topilmasa — None.

    Hech qachon xato ko'tarmaydi: papka yoki internetga yetib bo'lmasa, o'sha manba o'tkazib yuboriladi.
    """
    local = available(folder, current) if folder else None
    if local:
        return Offer(local[0], exe=local[1])
    version = available_online(url, current)
    return Offer(version, url=url) if version else None
