"""Umumiy papka (Google Drive, Yandex Disk, OneDrive yoki tarmoq papkasi) orqali yagona baza.

Server shart emas. Har bir kompyuter umumiy papkadagi `MME-Ombor-baza` ichida o'z papkachasiga o'zgarishlarni
raqamlangan fayllar (`000001.json`, `000002.json`…) sifatida yozadi va boshqalarning papkachalaridagi yangi
fayllarni o'qiydi:

- har bir faylni faqat bitta kompyuter yozadi va u keyin o'zgarmaydi — shuning uchun Google Drive faylni
  hech qachon «nusxa (1)» qilib ikkiga ajratmaydi va bazaning o'zi (ombor.db) Drive'ga qo'yilmaydi;
- fayl avval vaqtinchalik nom bilan yoziladi, to'liq yozilgach nomi o'zgartiriladi: chala fayl o'qilmaydi;
- har bir o'zgarishda vaqt belgisi bor; bitta yozuvni ikki kompyuter o'zgartirsa, belgisi kattasi g'olib
  bo'ladi, shuning uchun o'zgarishlar qaysi tartibda kelmasin, hamma kompyuterda natija bir xil.

Internet (yoki Drive) bo'lmasa, o'zgarishlar shu kompyuterning bazasida navbatda kutadi va papka yana
ko'ringanda o'zi yoziladi.
"""

import json
import os
import re
import time
from pathlib import Path

from .driver import sqlite3
from .i18n import tr
from .local import LocalPrefs
from .replication import Replica
from .sync import SyncError, SyncResult, device_name
from .sync_protocol import PROTOCOL_VERSION, PUSH_LIMIT, Change, known_changes

FOLDER_KEY = "sync_folder"  # shu kompyuterdagi umumiy papka yo'li (LocalPrefs)
FOLDER_NAME = "MME-Ombor-baza"
MARKER = "ombor.json"
FOLDER_FORMAT = 1
BATCH_PATTERN = re.compile(r"^(\d{6,})\.json$")
CLOCK_KEY = "clock"
MAX_ROUNDS = 3


class FolderUnavailable(SyncError):
    """Papkaga yetib bo'lmadi (Drive ulanmagan, fleshka chiqarilgan): keyinroq qayta uriniladi."""


def shared_folder(prefs: LocalPrefs) -> SharedFolder | None:
    """Shu kompyuter ulangan umumiy papka; ulanmagan bo'lsa — None."""
    path = prefs.get(FOLDER_KEY)
    return SharedFolder(Path(path), device_name(prefs)) if path else None


def remember_folder(prefs: LocalPrefs, folder: Path | None) -> None:
    prefs.set(FOLDER_KEY, str(folder) if folder else "")


def database_folder(chosen: Path) -> Path:
    """Foydalanuvchi tanlagan papka ichidagi umumiy baza papkasi (tanlanganining o'zi bo'lishi ham mumkin)."""
    return chosen if (chosen / MARKER).is_file() or chosen.name == FOLDER_NAME else chosen / FOLDER_NAME


def has_shared_data(folder: Path) -> bool:
    """Papkada boshqa kompyuter allaqachon ma'lumot yozganmi."""
    root = database_folder(folder)
    if not (root / MARKER).is_file():
        return False
    return any(path.is_file() and BATCH_PATTERN.match(path.name) for path in root.glob("*/*.json"))


def _device_folder_name(device: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", device) or "kompyuter"


class SharedFolder:
    """Umumiy papkadagi fayllar bilan ishlash: o'z fayllarini yozish, boshqalarnikini o'qish."""

    def __init__(self, folder: Path, device: str):
        self.root = database_folder(folder)
        self.device = _device_folder_name(device)

    def check(self) -> None:
        if not self.root.parent.is_dir():
            raise FolderUnavailable(tr("Umumiy papka topilmadi: {0}").format(self.root.parent))

    def create(self) -> None:
        self.check()
        try:
            (self.root / self.device).mkdir(parents=True, exist_ok=True)
            marker = self.root / MARKER
            if not marker.exists():
                _write_atomic(marker, {"format": FOLDER_FORMAT, "protocol": PROTOCOL_VERSION})
        except OSError as error:
            raise FolderUnavailable(tr("Umumiy papkaga yozib bo'lmadi: {0}").format(error)) from error

    def write_batch(self, number: int, changes: list[Change]) -> None:
        own = self.root / self.device
        try:
            own.mkdir(parents=True, exist_ok=True)
            payload = {"device": self.device, "batch": number, "changes": [change.to_json() for change in changes]}
            _write_atomic(own / f"{number:06d}.json", payload)
        except OSError as error:
            raise FolderUnavailable(tr("Umumiy papkaga yozib bo'lmadi: {0}").format(error)) from error

    def last_own_batch(self) -> int:
        """Papkadagi shu kompyuter fayllarining eng katta raqami (baza nusxadan tiklangan bo'lsa ham to'g'ri davom
        etish uchun)."""
        return max(self._batches(self.root / self.device), default=0)

    def read_new(self, seen: dict[str, int]) -> tuple[list[Change], dict[str, int]]:
        """Boshqa kompyuterlarning hali o'qilmagan fayllari: (o'zgarishlar, yangilangan o'qish holati).

        Har bir kompyuterning fayllari ketma-ket o'qiladi; raqamlar orasida bo'shliq bo'lsa (Drive hali ko'chirib
        bo'lmagan) yoki fayl chala bo'lsa, o'sha joyda to'xtaladi va keyingi safar davom etiladi.
        """
        self.check()
        changes: list[Change] = []
        updated = dict(seen)
        try:
            devices = [path for path in self.root.iterdir() if path.is_dir() and not path.name.startswith(".")]
        except OSError as error:
            raise FolderUnavailable(tr("Umumiy papkani o'qib bo'lmadi: {0}").format(error)) from error
        for device in devices:
            if device.name == self.device:
                continue
            last = seen.get(device.name, 0)
            for number in sorted(n for n in self._batches(device) if n > last):
                if number != last + 1:
                    break
                batch = _read_json(device / f"{number:06d}.json")
                if batch is None:
                    break
                changes += known_changes(batch.get("changes") or [])
                last = number
            if last:
                updated[device.name] = last
        return changes, updated

    @staticmethod
    def _batches(folder: Path) -> list[int]:
        try:
            names = [path.name for path in folder.iterdir()]
        except OSError:
            return []
        return [int(match.group(1)) for match in map(BATCH_PATTERN.match, names) if match]


def _write_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.yozilmoqda")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


class Clock:
    """O'zgarishlarga vaqt belgisi beradi: «millisekund-hisoblagich-kompyuter». Belgilar har doim o'sib boradi
    va boshqa kompyuterlarda ko'rilgan eng katta belgidan ham katta bo'ladi (soatlar farq qilsa ham)."""

    def __init__(self, replica: Replica, device: str):
        self._replica = replica
        self._device = device

    def next(self, amount: int) -> list[str]:
        """`amount` ta ketma-ket belgi."""
        last_ms, last_count = _parse(self._replica.meta(CLOCK_KEY))
        now = int(time.time() * 1000)
        ms, count = (now, 0) if now > last_ms else (last_ms, last_count + 1)
        stamps = [f"{ms:013d}-{count + index:06d}-{self._device}" for index in range(amount)]
        self._replica.set_meta(CLOCK_KEY, f"{ms:013d}-{count + amount - 1:06d}")
        return stamps

    def observe(self, stamps: list[str]) -> None:
        """Boshqa kompyuterlardan kelgan eng katta belgi: shu yerdagi keyingi belgilar undan katta bo'ladi."""
        seen = max((_parse(stamp) for stamp in stamps), default=(0, 0))
        if seen > _parse(self._replica.meta(CLOCK_KEY)):
            self._replica.set_meta(CLOCK_KEY, f"{seen[0]:013d}-{seen[1]:06d}")


def _parse(stamp: str) -> tuple[int, int]:
    parts = stamp.split("-")
    try:
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return 0, 0


class FolderSynchronizer:
    """Bitta bazani umumiy papka bilan sinxronlaydi (`sync.Synchronizer` bilan bir xil ko'rinishda)."""

    def __init__(self, conn: sqlite3.Connection, folder: SharedFolder):
        self._replica = Replica(conn)
        self._folder = folder
        self._clock = Clock(self._replica, folder.device)

    def run(self) -> SyncResult:
        sent = received = 0
        try:
            self._folder.check()
            for _ in range(MAX_ROUNDS):
                sent += self._push_all()
                changes, peers = self._folder.read_new(self._replica.peers())
                self._clock.observe([change.stamp for change in changes])
                if self._replica.apply_versioned(changes, peers):
                    received += len(changes)
                    sent += self._push_all()  # o'chirilgan, lekin shu yerda ishlatilayotgan qator qayta yuboriladi
                    break
        except SyncError as failure:
            return SyncResult(
                sent=sent,
                waiting=self._replica.pending_count(),
                error=str(failure),
                offline=isinstance(failure, FolderUnavailable),
            )
        return SyncResult(sent=sent, received=received, waiting=self._replica.pending_count())

    def publish(self) -> SyncResult:
        """Bo'sh papka: shu kompyuterdagi hamma ma'lumot umumiy baza sifatida yoziladi."""
        self._folder.create()
        self._replica.enable(publish_all=True)
        return self.run()

    def join(self) -> int:
        """Ma'lumoti bor papka: shu yerdagi ma'lumotlar umumiy bazadagi bilan almashtiriladi.

        Avval hammasi o'qiladi, keyin bitta tranzaksiyada almashtiriladi. O'qilgan o'zgarishlar sonini qaytaradi.
        """
        self._folder.create()
        changes, peers = self._folder.read_new({})
        latest: dict[tuple[str, str], Change] = {}
        for change in changes:
            key = (change.table, change.uid)
            if key not in latest or change.stamp > latest[key].stamp:
                latest[key] = change
        current = list(latest.values())
        has_admin = any(c.table == "users" and not c.deleted and c.data.get("role") == "admin" for c in current)
        if not has_admin:
            raise SyncError(tr("Umumiy papkadagi bazada rahbar hisobi yo'q: unga ulanib bo'lmaydi."))
        self._replica.replace_all(current, versioned=True, peers=peers)
        self._clock.observe([change.stamp for change in current])
        return len(current)

    def _push_all(self) -> int:
        sent = 0
        while True:
            last_id, changes = self._replica.outgoing(PUSH_LIMIT)
            if not changes:
                return sent
            stamps = self._clock.next(len(changes))
            stamped = [Change(c.table, c.uid, c.data, c.deleted, stamp=s) for c, s in zip(changes, stamps)]
            number = max(self._replica.peers().get(self._folder.device, 0), self._folder.last_own_batch()) + 1
            self._folder.write_batch(number, stamped)
            self._replica.record_versions(stamped)
            self._replica.save_peers({self._folder.device: number})
            self._replica.acknowledge(last_id, changes)
            sent += len(changes)
