"""Markaziy sinxronlash serveri: barcha kompyuterlar uchun yagona baza.

Ishga tushirish (internetdan ko'rinadigan kompyuter yoki VPS'da):

    python -m ombor.sync_server --token MAXFIY-KALIT --port 8765 --data ombor-server.db

HTTPS uchun `--cert` va `--key` (sertifikat fayllari) beriladi yoki server nginx/caddy ortiga qo'yiladi.
Faqat Python standart kutubxonasidan foydalanadi: PySide6 va SQLCipher o'rnatish shart emas.

Server har bir qatorning faqat oxirgi holatini saqlaydi; har bir o'zgarish yangi tartib raqami (`seq`)
oladi, kompyuterlar o'zlari olgan oxirgi raqamdan keyingilarini so'raydi.
"""

import argparse
import hmac
import json
import os
import sqlite3
import ssl
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .sync_protocol import (
    DEVICE_HEADER,
    PROTOCOL_HEADER,
    PROTOCOL_VERSION,
    PULL_LIMIT,
    TABLES_BY_NAME,
    TOKEN_HEADER,
    Change,
    known_changes,
    unique_key,
)

DEFAULT_PORT = 8765
MAX_BODY_BYTES = 64 * 1024 * 1024
TOKEN_ENV = "OMBOR_SYNC_TOKEN"
MIN_TOKEN_LENGTH = 8

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rows (
    tbl        TEXT NOT NULL,
    uid        TEXT NOT NULL,
    data       TEXT,                       -- JSON; o'chirilgan qatorda bo'sh
    deleted    INTEGER NOT NULL DEFAULT 0,
    seq        INTEGER NOT NULL,
    unique_key TEXT NOT NULL DEFAULT '',   -- takrorlanmasligi kerak bo'lgan nom (kichik harflarda)
    device     TEXT NOT NULL DEFAULT '',   -- oxirgi o'zgartirgan kompyuter
    at         TEXT NOT NULL,
    PRIMARY KEY (tbl, uid)
);
CREATE INDEX IF NOT EXISTS rows_seq ON rows(seq);
CREATE INDEX IF NOT EXISTS rows_unique ON rows(tbl, unique_key) WHERE unique_key <> '' AND deleted = 0;
CREATE TABLE IF NOT EXISTS devices (
    name      TEXT PRIMARY KEY,
    last_seen TEXT NOT NULL,
    address   TEXT NOT NULL DEFAULT ''
);
"""


class ServerStore:
    """Serverdagi baza. Barcha amallar bitta qulf ostida: kompyuterlar bir-biriga xalaqit bermaydi."""

    def __init__(self, path: Path | str):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def head(self) -> int:
        return self._conn.execute("SELECT COALESCE(MAX(seq), 0) FROM rows").fetchone()[0]

    def status(self) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT COUNT(*) FROM rows WHERE NOT deleted").fetchone()[0]
            devices = [dict(row) for row in self._conn.execute("SELECT * FROM devices ORDER BY last_seen DESC")]
            return {"protocol": PROTOCOL_VERSION, "head": self.head(), "rows": rows, "devices": devices}

    def seen(self, device: str, address: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO devices (name, last_seen, address) VALUES (?, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET last_seen = excluded.last_seen, address = excluded.address",
                (device, _now(), address),
            )

    def push(self, changes: list[Change], device: str) -> int:
        """O'zgarishlarni yozadi. Boshqa qatorda band bo'lgan nomga « (2)», « (3)»… qo'shiladi."""
        with self._lock, self._conn:
            seq = self.head()
            for change in changes:
                spec = TABLES_BY_NAME[change.table]
                data = None if change.deleted else self._free_name(spec, change)
                stored = self._conn.execute(
                    "SELECT data, deleted FROM rows WHERE tbl = ? AND uid = ?", (change.table, change.uid)
                ).fetchone()
                encoded = json.dumps(data, ensure_ascii=False, sort_keys=True) if data is not None else None
                if stored is not None and stored["data"] == encoded and bool(stored["deleted"]) == change.deleted:
                    continue  # hech narsa o'zgarmagan: boshqa kompyuterlarni bezovta qilmaymiz
                seq += 1
                self._conn.execute(
                    "INSERT INTO rows (tbl, uid, data, deleted, seq, unique_key, device, at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(tbl, uid) DO UPDATE SET data = excluded.data, deleted = excluded.deleted,"
                    " seq = excluded.seq, unique_key = excluded.unique_key, device = excluded.device, at = excluded.at",
                    (
                        change.table,
                        change.uid,
                        encoded,
                        int(change.deleted),
                        seq,
                        unique_key(spec, data),
                        device,
                        _now(),
                    ),
                )
            return seq

    def pull(self, since: int, limit: int = PULL_LIMIT) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT tbl, uid, data, deleted, seq FROM rows WHERE seq > ? ORDER BY seq LIMIT ?", (since, limit + 1)
            ).fetchall()
            head = self.head()
        changes = [
            Change(
                row["tbl"],
                row["uid"],
                json.loads(row["data"]) if row["data"] else None,
                bool(row["deleted"]),
                row["seq"],
            )
            for row in rows[:limit]
        ]
        return {"changes": [change.to_json() for change in changes], "head": head, "more": len(rows) > limit}

    def prune(self, keys: dict[str, list[str]], device: str) -> int:
        """`keys` da ko'rsatilmagan qatorlarni o'chirilgan deb belgilaydi (faqat ko'rsatilgan jadvallarda)."""
        with self._lock, self._conn:
            seq = self.head()
            for table, kept in keys.items():
                if table not in TABLES_BY_NAME:
                    continue
                kept_set = set(kept)
                rows = self._conn.execute("SELECT uid FROM rows WHERE tbl = ? AND NOT deleted", (table,)).fetchall()
                for row in rows:
                    if row["uid"] in kept_set:
                        continue
                    seq += 1
                    self._conn.execute(
                        "UPDATE rows SET data = NULL, deleted = 1, seq = ?, unique_key = '', device = ?, at = ?"
                        " WHERE tbl = ? AND uid = ?",
                        (seq, device, _now(), table, row["uid"]),
                    )
            return seq

    def _free_name(self, spec, change: Change) -> dict:
        """Nom boshqa qatorda band bo'lmasa — ma'lumot o'z holicha, aks holda nomiga raqam qo'shilgan nusxasi."""
        data = dict(change.data)
        base = str(data.get(spec.unique) or "") if spec.unique else ""
        number = 1
        while unique_key(spec, data):
            taken = self._conn.execute(
                "SELECT 1 FROM rows WHERE tbl = ? AND unique_key = ? AND NOT deleted AND uid <> ?",
                (spec.name, unique_key(spec, data), change.uid),
            ).fetchone()
            if taken is None:
                break
            number += 1
            data[spec.unique] = f"{base} ({number})"
        return data


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def make_handler(store: ServerStore, token: str, log: bool = True) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "OmborSync/1"

        def do_GET(self) -> None:  # noqa: N802 — http.server shu nomni kutadi
            self._handle("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._handle("POST")

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            if log:
                print(f"{_now()} {self.address_string()} {format % args}", flush=True)

        def _handle(self, method: str) -> None:
            # So'rov tanasi har doim oxirigacha o'qiladi: rad javobini o'qilmagan tana ustidan yuborib, ulanishni
            # yopsak, Windows mijozga «ulanish uzildi» deydi va u buni «internet yo'q» deb tushunadi.
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                self.close_connection = True
                self._reply(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "So'rov juda katta"})
                return
            self._raw = self.rfile.read(length) if length else b""
            if not self._authorized():
                self._reply(HTTPStatus.UNAUTHORIZED, {"error": "Kirish kaliti noto'g'ri"})
                return
            if self.headers.get(PROTOCOL_HEADER) != str(PROTOCOL_VERSION):
                self._reply(
                    HTTPStatus.CONFLICT, {"error": "Dastur va server versiyalari mos emas. Dasturni yangilang."}
                )
                return
            device = (self.headers.get(DEVICE_HEADER) or "")[:100]
            url = urlparse(self.path)
            try:
                if device:
                    store.seen(device, self.client_address[0])
                answer = self._route(method, url.path, parse_qs(url.query), device)
            except (ValueError, KeyError, TypeError) as failure:
                self._reply(HTTPStatus.BAD_REQUEST, {"error": str(failure)})
                return
            if answer is None:
                self._reply(HTTPStatus.NOT_FOUND, {"error": "Bunday manzil yo'q"})
            else:
                self._reply(HTTPStatus.OK, answer)

        def _route(self, method: str, path: str, query: dict, device: str) -> dict | None:
            if method == "GET" and path == "/api/status":
                return store.status()
            if method == "GET" and path == "/api/pull":
                since = int(query.get("since", ["0"])[0])
                limit = max(1, min(int(query.get("limit", [str(PULL_LIMIT)])[0]), PULL_LIMIT))
                return store.pull(since, limit)
            if method == "POST" and path == "/api/push":
                changes = known_changes(self._body()["changes"])
                return {"head": store.push(changes, device)}
            if method == "POST" and path == "/api/prune":
                return {"head": store.prune(self._body()["keys"], device)}
            return None

        def _authorized(self) -> bool:
            given = self.headers.get(TOKEN_HEADER, "").removeprefix("Bearer ").strip()
            return hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8"))

        def _body(self) -> dict:
            value = json.loads(self._raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSON obyekt kutilgan edi")
            return value

        def _reply(self, status: HTTPStatus, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def make_server(
    store: ServerStore, token: str, host: str = "0.0.0.0", port: int = DEFAULT_PORT, log: bool = True
) -> ThreadingHTTPServer:
    """`log` — har bir so'rovni ekranga yozish."""
    if len(token) < MIN_TOKEN_LENGTH:
        raise ValueError(f"Kirish kaliti kamida {MIN_TOKEN_LENGTH} ta belgidan iborat bo'lishi kerak")
    return ThreadingHTTPServer((host, port), make_handler(store, token, log))


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="MME Ombor — markaziy sinxronlash serveri")
    parser.add_argument("--host", default="0.0.0.0", help="tinglanadigan manzil (odatda 0.0.0.0)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--data", default="ombor-server.db", help="server bazasi fayli")
    parser.add_argument("--token", default=os.environ.get(TOKEN_ENV, ""), help=f"kirish kaliti (yoki {TOKEN_ENV})")
    parser.add_argument("--cert", help="HTTPS sertifikati (PEM)")
    parser.add_argument("--key", help="HTTPS sertifikatining yopiq kaliti (PEM)")
    options = parser.parse_args(arguments)
    if not options.token:
        parser.error(f"kirish kaliti berilmagan: --token yoki {TOKEN_ENV}")

    store = ServerStore(options.data)
    server = make_server(store, options.token, options.host, options.port)
    scheme = "http"
    if options.cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(options.cert, options.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    print(f"Server ishlamoqda: {scheme}://{options.host}:{options.port}  (baza: {Path(options.data).resolve()})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()


if __name__ == "__main__":
    main()
