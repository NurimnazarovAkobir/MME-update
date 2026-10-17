"""Markaziy server bilan sinxronlash: o'zgarishlarni yuborish va olish (mijoz tomoni).

Server manzili, kirish kaliti va kompyuterning nomi shu kompyuterning shaxsiy sozlamalarida
(`LocalPrefs`) saqlanadi. Internet bo'lmasa, sinxronlash jimgina keyingi safarga qoldiriladi:
o'zgarishlar navbatda kutib turadi va ulanish tiklanganda o'zi yuboriladi.
"""

import json
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from urllib import error, parse, request

from .driver import sqlite3
from .i18n import tr
from .local import LocalPrefs
from .replication import Replica
from .sync_protocol import (
    DEVICE_HEADER,
    PROTOCOL_HEADER,
    PROTOCOL_VERSION,
    PULL_LIMIT,
    PUSH_LIMIT,
    TOKEN_HEADER,
    Change,
    known_changes,
)

URL_KEY, TOKEN_KEY, DEVICE_KEY = "sync_url", "sync_token", "sync_device"
TIMEOUT_SECONDS = 20
MAX_ROUNDS = 3  # olish paytida yangi o'zgarish paydo bo'lsa, yuborish-olish shuncha marta takrorlanadi


class SyncError(Exception):
    """Sinxronlab bo'lmadi; xabar foydalanuvchiga ko'rsatiladi."""


class OfflineError(SyncError):
    """Serverga yetib bo'lmadi (internet yo'q yoki server o'chiq): keyinroq qayta uriniladi."""


@dataclass(frozen=True)
class SyncConfig:
    url: str
    token: str
    device: str

    @classmethod
    def load(cls, prefs: LocalPrefs) -> "SyncConfig | None":
        """Shu kompyuterda server sozlangan bo'lsa — uning sozlamalari, aks holda None."""
        url, token = prefs.get(URL_KEY), prefs.get(TOKEN_KEY)
        if not url or not token:
            return None
        return cls(url, token, device_name(prefs))

    def save(self, prefs: LocalPrefs) -> None:
        prefs.set(URL_KEY, self.url)
        prefs.set(TOKEN_KEY, self.token)

    @staticmethod
    def forget(prefs: LocalPrefs) -> None:
        prefs.set(URL_KEY, "")
        prefs.set(TOKEN_KEY, "")


def device_name(prefs: LocalPrefs) -> str:
    """Kompyuterning serverdagi nomi: kompyuter nomi va bir martalik tasodifiy belgi."""
    name = prefs.get(DEVICE_KEY)
    if not name:
        name = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
        prefs.set(DEVICE_KEY, name)
    return name


def normalize_url(url: str) -> str:
    """Foydalanuvchi kiritgan manzil: «http(s)://» bo'lmasa — qo'shiladi, oxiridagi «/» olib tashlanadi."""
    url = url.strip().rstrip("/")
    if url and "://" not in url:
        url = f"http://{url}"
    parsed = parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SyncError(tr("Server manzili noto'g'ri. Masalan: https://ombor.example.uz yoki 192.168.1.10:8765"))
    return url


class SyncClient:
    """Server bilan HTTP (JSON) orqali gaplashadi."""

    def __init__(self, config: SyncConfig, timeout: float = TIMEOUT_SECONDS):
        self._config = config
        self._timeout = timeout

    def status(self) -> dict:
        """Server holati: {'head': oxirgi o'zgarish raqami, 'rows': qatorlar soni}."""
        return self._call("GET", "/api/status")

    def push(self, changes: list[Change]) -> int:
        return self._call("POST", "/api/push", {"changes": [change.to_json() for change in changes]})["head"]

    def pull(self, since: int) -> tuple[list[Change], int, bool, int]:
        """`since` dan keyingi o'zgarishlar: (o'zgarishlar, serverdagi oxirgi raqam, yana bormi, shu to'plamning
        oxirgi raqami). Bu versiya bilmaydigan jadvallar tashlab ketiladi, lekin raqami hisobga olinadi."""
        answer = self._call("GET", f"/api/pull?since={since}&limit={PULL_LIMIT}")
        items = answer["changes"]
        last = max([since, *(int(item.get("seq") or 0) for item in items)])
        return known_changes(items), answer["head"], bool(answer["more"]), last

    def prune(self, keys: dict[str, list[str]]) -> int:
        """Serverda `keys` da yo'q qatorlarni o'chiradi (zaxiradan tiklangan bazani asosiy qilish uchun)."""
        return self._call("POST", "/api/prune", {"keys": keys})["head"]

    def _call(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        call = request.Request(f"{self._config.url}{path}", data=body, method=method)
        call.add_header(TOKEN_HEADER, f"Bearer {self._config.token}")
        call.add_header(DEVICE_HEADER, self._config.device)
        call.add_header(PROTOCOL_HEADER, str(PROTOCOL_VERSION))
        call.add_header("Content-Type", "application/json")
        try:
            with request.urlopen(call, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as failure:
            raise SyncError(_server_message(failure)) from failure
        except (error.URLError, OSError) as failure:  # internet yo'q, server o'chiq, vaqt tugadi
            raise OfflineError(tr("Serverga ulanib bo'lmadi: {0}").format(failure)) from failure
        except ValueError as failure:
            raise SyncError(tr("Server noto'g'ri javob qaytardi.")) from failure


def _server_message(failure: error.HTTPError) -> str:
    try:
        with failure:
            message = json.loads(failure.read().decode("utf-8")).get("error", "")
    except (ValueError, OSError, AttributeError):
        message = ""
    if failure.code in (401, 403):
        return tr("Server kirish kalitini qabul qilmadi. Kalitni tekshiring.")
    return tr("Server xatosi ({0}): {1}").format(failure.code, message or failure.reason)


@dataclass(frozen=True)
class SyncResult:
    at: datetime = field(default_factory=datetime.now)
    sent: int = 0
    received: int = 0
    waiting: int = 0  # serverga hali yuborilmagan o'zgarishlar
    error: str = ""
    offline: bool = False

    @property
    def ok(self) -> bool:
        return not self.error


class Synchronizer:
    """Bitta bazani bitta server bilan sinxronlaydi."""

    def __init__(self, conn: sqlite3.Connection, client: SyncClient):
        self._replica = Replica(conn)
        self._client = client

    def run(self) -> SyncResult:
        """Yuborish va olish; xato bo'lsa, natijada yoziladi (ma'lumot yo'qolmaydi — navbatda qoladi)."""
        sent = received = 0
        try:
            for _ in range(MAX_ROUNDS):
                sent += self._push_all()
                if self._replica.needs_republish:
                    self._client.prune(self._replica.all_keys())
                    self._replica.republished()
                changes, head = self._pull_all(self._replica.last_seq)
                if self._replica.apply_remote(changes, head):
                    received += len(changes)
                    # Boshqa kompyuterda o'chirilgan, lekin shu yerda ishlatilayotgan qator qaytadan yuboriladi.
                    sent += self._push_all()
                    break
        except SyncError as failure:
            return SyncResult(
                sent=sent,
                waiting=self._replica.pending_count(),
                error=str(failure),
                offline=isinstance(failure, OfflineError),
            )
        return SyncResult(sent=sent, received=received, waiting=self._replica.pending_count())

    def publish(self) -> SyncResult:
        """Bo'sh serverga ulanish: shu kompyuterdagi hamma ma'lumot asosiy baza sifatida yuboriladi."""
        self._replica.enable(publish_all=True)
        return self.run()

    def join(self) -> int:
        """Ma'lumoti bor serverga ulanish: shu yerdagi ma'lumotlar serverdagilari bilan almashtiriladi.

        Avval hammasi yuklab olinadi, keyin bitta tranzaksiyada almashtiriladi: internet uzilsa,
        eski ma'lumotlar o'z holicha qoladi. Olingan qatorlar sonini qaytaradi.
        """
        changes, head = self._pull_all(0)
        has_admin = any(
            change.table == "users" and not change.deleted and change.data.get("role") == "admin" for change in changes
        )
        if not has_admin:
            raise SyncError(tr("Serverdagi bazada rahbar hisobi yo'q: unga ulanib bo'lmaydi."))
        self._replica.replace_all(changes, head)
        return len(changes)

    def _push_all(self) -> int:
        sent = 0
        while True:
            last_id, changes = self._replica.outgoing(PUSH_LIMIT)
            if not changes:
                return sent
            self._client.push(changes)
            self._replica.acknowledge(last_id, changes)
            sent += len(changes)

    def _pull_all(self, since: int) -> tuple[list[Change], int]:
        changes: list[Change] = []
        while True:
            batch, head, more, since = self._client.pull(since)
            changes += batch
            if not more:
                return changes, max(head, since)
