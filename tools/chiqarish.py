"""Yangi versiyani bitta buyruq bilan chiqarish: `chiqarish.bat` (yoki `python -m tools.chiqarish`).

Ketma-ketlik: versiya raqamini oshiradi → testlarni o'tkazadi → exe ni yig'adi → `MME-Ombor.exe` va
`versiya.txt` ni belgilangan joylarga (yangilanishlar papkalari va/yoki GitHub Releases) joylaydi →
o'zgarishlarni git ga yozadi. Shundan keyin har bir kompyuterdagi dastur yangilanish haqida xabar beradi.

Qayerga chiqarilishi `chiqarish.json` da (birinchi ishga tushirishda namunasi yaratiladi):

    {
      "papkalar": ["sinov/yangilanish"],
      "github": {"repo": "akkaunt/repo", "token": "ghp_..."}
    }

`github` bo'limi to'ldirilsa, dasturga internetdagi manzil ham o'zi yozib qo'yiladi. Token maxfiy:
`chiqarish.json` git ga qo'shilmaydi.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PY = ROOT / "ombor" / "config.py"
SETTINGS = ROOT / "chiqarish.json"
DIST = ROOT / "dist"
EXE_NAME, VERSION_FILE = "MME-Ombor.exe", "versiya.txt"
TEMPLATE = {"papkalar": ["sinov/yangilanish"], "github": {"repo": "", "token": ""}}
GITHUB_API = "https://api.github.com"
GITHUB_UPLOADS = "https://uploads.github.com"


class ReleaseError(Exception):
    """Chiqarishni davom ettirib bo'lmaydi; xabar foydalanuvchiga ko'rsatiladi."""


# --- Versiya -------------------------------------------------------------------


def current_version(config: Path = CONFIG_PY) -> str:
    match = re.search(r'^APP_VERSION = "([^"]+)"', config.read_text(encoding="utf-8"), flags=re.M)
    if not match:
        raise ReleaseError(f"{config} da APP_VERSION topilmadi.")
    return match.group(1)


def next_version(version: str) -> str:
    """Oxirgi raqamni bittaga oshiradi: '1.4' -> '1.5', '2.0.9' -> '2.0.10'."""
    parts = version.split(".")
    if not all(part.isdigit() for part in parts):
        raise ReleaseError(f"Versiya raqamini tushunib bo'lmadi: {version}")
    return ".".join([*parts[:-1], str(int(parts[-1]) + 1)])


def as_number(version: str) -> tuple[int, ...]:
    if not re.fullmatch(r"\d+(\.\d+)*", version):
        raise ReleaseError(f"Versiya faqat raqam va nuqtadan iborat bo'lishi kerak (masalan, 1.5): {version}")
    return tuple(int(part) for part in version.split("."))


def write_config(version: str, update_url: str | None = None, config: Path = CONFIG_PY) -> None:
    """Versiyani (va berilgan bo'lsa, internetdagi yangilanishlar manzilini) `config.py` ga yozadi."""
    text = config.read_text(encoding="utf-8")
    text, count = re.subn(r'^APP_VERSION = "[^"]+"', f'APP_VERSION = "{version}"', text, flags=re.M)
    if count != 1:
        raise ReleaseError(f"{config} da APP_VERSION topilmadi.")
    if update_url is not None:
        text, count = re.subn(
            r'^DEFAULT_UPDATE_URL = "[^"]*"', f'DEFAULT_UPDATE_URL = "{update_url}"', text, flags=re.M
        )
        if count != 1:
            raise ReleaseError(f"{config} da DEFAULT_UPDATE_URL topilmadi.")
    config.write_text(text, encoding="utf-8", newline="\n")


# --- Sozlama ---------------------------------------------------------------------


def load_settings(path: Path = SETTINGS) -> dict:
    if not path.exists():
        path.write_text(json.dumps(TEMPLATE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Namuna sozlama yaratildi: {path}")
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ReleaseError(f"{path} ni o'qib bo'lmadi: {error}") from error
    github = settings.get("github") or {}
    settings["papkalar"] = [folder for folder in settings.get("papkalar") or [] if folder]
    settings["github"] = github if github.get("repo") and github.get("token") else None
    if not settings["papkalar"] and not settings["github"]:
        raise ReleaseError(f"Qayerga chiqarish ko'rsatilmagan: {path} da papka yoki GitHub ma'lumotini kiriting.")
    return settings


def github_update_url(repo: str) -> str:
    """Dastur yangilanishni tekshiradigan manzil: har doim eng oxirgi Release fayllariga olib boradi."""
    return f"https://github.com/{repo}/releases/latest/download/"


# --- Joylash ---------------------------------------------------------------------


def publish_to_folder(folder: Path, dist: Path = DIST) -> None:
    """Avval exe, oxirida versiya fayli: dasturlar yangi versiyani faqat exe to'liq ko'chirilgach ko'radi."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / (EXE_NAME + ".yuklanmoqda")
        shutil.copy2(dist / EXE_NAME, temporary)
        free_dist_exe(folder)  # kimdir dasturni shu papkaning o'zidan ochib qo'ygan bo'lsa
        temporary.replace(folder / EXE_NAME)
        shutil.copy2(dist / VERSION_FILE, folder / VERSION_FILE)
    except OSError as error:
        raise ReleaseError(f"{folder} papkasiga joylab bo'lmadi: {error}") from error


def _github(method: str, url: str, token: str, body: bytes | None, content_type: str) -> dict:
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")[:300]
        raise ReleaseError(f"GitHub rad etdi ({error.code}): {details}") from error
    except OSError as error:
        raise ReleaseError(f"GitHub ga ulanib bo'lmadi: {error}") from error


def publish_to_github(
    repo: str, token: str, version: str, dist: Path = DIST, api: str = GITHUB_API, uploads: str = GITHUB_UPLOADS
) -> None:
    """Yangi Release yaratadi va ikkala faylni unga yuklaydi (exe avval, versiya fayli oxirida)."""
    body = json.dumps({"tag_name": f"v{version}", "name": f"MME Ombor {version}"}).encode("utf-8")
    release = _github("POST", f"{api}/repos/{repo}/releases", token, body, "application/json")
    for name in (EXE_NAME, VERSION_FILE):
        url = f"{uploads}/repos/{repo}/releases/{release['id']}/assets?name={name}"
        _github("POST", url, token, (dist / name).read_bytes(), "application/octet-stream")


# --- Qadamlar --------------------------------------------------------------------


def run(command: list[str], failure: str) -> None:
    if subprocess.run(command, cwd=ROOT).returncode != 0:
        raise ReleaseError(failure)


def free_dist_exe(dist: Path = DIST) -> None:
    """Dastur `dist` dan ochiq turgan bo'lsa, faylini chetga nomlaydi: ishlab turgan exe ustidan yozib bo'lmaydi."""
    exe = dist / EXE_NAME
    if not exe.exists():
        return
    try:
        with open(exe, "ab"):
            return
    except OSError:
        exe.replace(dist / f"MME-Ombor-ochiq-{datetime.now():%H%M%S}.exe")


def release(version: str | None, skip_tests: bool) -> str:
    settings = load_settings()
    old = current_version()
    new = version or next_version(old)
    if as_number(new) <= as_number(old):
        raise ReleaseError(f"Yangi versiya ({new}) joriysidan ({old}) katta bo'lishi kerak.")
    github = settings["github"]

    print(f"== {old} -> {new}")
    write_config(new, github_update_url(github["repo"]) if github else None)
    try:
        if not skip_tests:
            print("== Testlar")
            run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], "Testlar o'tmadi.")
        print("== Yig'ish")
        free_dist_exe()
        run(["cmd", "/c", str(ROOT / "build.bat")], "Yig'ib bo'lmadi (dastur dist papkasidan ochiq bo'lsa, yoping).")
        if (DIST / VERSION_FILE).read_text(encoding="utf-8").strip() != new:
            raise ReleaseError("Yig'ilgan versiya kutilganidan boshqa chiqdi.")
    except BaseException:
        write_config(old)  # chiqarilmagan versiya raqami kodda qolib ketmasin
        raise

    publish(settings, new)
    subprocess.run(["git", "add", "-A"], cwd=ROOT)
    subprocess.run(["git", "commit", "-q", "-m", f"{new} versiyasi chiqarildi"], cwd=ROOT)
    subprocess.run(["git", "tag", "-f", f"v{new}"], cwd=ROOT)
    return new


def publish(settings: dict, version: str) -> None:
    """Yig'ilgan `dist` ni barcha belgilangan joylarga joylaydi."""
    github = settings["github"]
    for folder in settings["papkalar"]:
        target = (ROOT / folder).resolve()
        print(f"== Papkaga: {target}")
        publish_to_folder(target)
    if github:
        print(f"== GitHub: {github['repo']}")
        publish_to_github(github["repo"], github["token"], version)


def main() -> int:
    parser = argparse.ArgumentParser(description="MME Ombor ning yangi versiyasini chiqaradi.")
    parser.add_argument("versiya", nargs="?", help="yangi versiya raqami (berilmasa, oxirgi raqam bittaga oshadi)")
    parser.add_argument("--testsiz", action="store_true", help="testlarni o'tkazib yuborish")
    parser.add_argument(
        "--faqat-joylash", action="store_true", help="qayta yig'masdan, dist dagi tayyor versiyani joylash"
    )
    arguments = parser.parse_args()
    try:
        if arguments.faqat_joylash:
            version = (DIST / VERSION_FILE).read_text(encoding="utf-8").strip()
            publish(load_settings(), version)
        else:
            version = release(arguments.versiya, arguments.testsiz)
    except ReleaseError as error:
        print(f"\nXATO: {error}")
        return 1
    print(f"\nTayyor: {version} versiyasi chiqarildi. Dasturlar keyingi tekshiruvda yangilanishni ko'radi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
