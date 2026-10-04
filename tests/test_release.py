"""Chiqarish vositasi (`tools/chiqarish.py`) testlari: versiya, sozlama, papkaga va GitHub ga joylash."""

import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path

from ombor import update
from tools import chiqarish
from tools.chiqarish import ReleaseError

CONFIG = '''"""Sozlamalar."""

APP_NAME = "MME Ombor"
APP_VERSION = "1.4"
DEFAULT_UPDATE_URL = ""
'''


class FolderCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.dist = self.folder / "dist"
        self.dist.mkdir()
        (self.dist / chiqarish.EXE_NAME).write_bytes(b"MZ yangi dastur")
        (self.dist / chiqarish.VERSION_FILE).write_text("1.5\n", encoding="utf-8")


class VersionTests(FolderCase):
    def setUp(self):
        super().setUp()
        self.config = self.folder / "config.py"
        self.config.write_text(CONFIG, encoding="utf-8")

    def test_next_version_increments_the_last_number(self):
        self.assertEqual(chiqarish.next_version("1.4"), "1.5")
        self.assertEqual(chiqarish.next_version("1.9"), "1.10")
        self.assertEqual(chiqarish.next_version("2.0.9"), "2.0.10")
        with self.assertRaises(ReleaseError):
            chiqarish.next_version("1.x")

    def test_versions_compare_as_numbers(self):
        self.assertGreater(chiqarish.as_number("1.10"), chiqarish.as_number("1.9"))
        with self.assertRaises(ReleaseError):
            chiqarish.as_number("v2")

    def test_config_is_rewritten_in_place(self):
        self.assertEqual(chiqarish.current_version(self.config), "1.4")
        chiqarish.write_config("1.5", config=self.config)
        self.assertEqual(chiqarish.current_version(self.config), "1.5")
        self.assertIn('DEFAULT_UPDATE_URL = ""', self.config.read_text(encoding="utf-8"))
        chiqarish.write_config("1.6", "https://github.com/a/b/releases/latest/download/", self.config)
        text = self.config.read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "1.6"', text)
        self.assertIn('DEFAULT_UPDATE_URL = "https://github.com/a/b/releases/latest/download/"', text)
        self.assertIn('APP_NAME = "MME Ombor"', text)

    def test_real_config_has_both_values(self):
        self.assertEqual(chiqarish.current_version(), update.APP_VERSION)
        self.assertIn("DEFAULT_UPDATE_URL = ", chiqarish.CONFIG_PY.read_text(encoding="utf-8"))


class SettingsTests(FolderCase):
    def test_template_is_created_on_first_run(self):
        path = self.folder / "chiqarish.json"
        settings = chiqarish.load_settings(path)
        self.assertEqual(settings["papkalar"], ["sinov/yangilanish"])
        self.assertIsNone(settings["github"])  # namuna bo'sh: GitHub hali sozlanmagan
        self.assertTrue(path.is_file())

    def test_github_needs_both_repo_and_token(self):
        path = self.folder / "chiqarish.json"
        path.write_text(json.dumps({"papkalar": [], "github": {"repo": "a/b", "token": "t"}}), encoding="utf-8")
        self.assertEqual(chiqarish.load_settings(path)["github"]["repo"], "a/b")
        path.write_text(json.dumps({"papkalar": [""], "github": {"repo": "a/b", "token": ""}}), encoding="utf-8")
        with self.assertRaises(ReleaseError):
            chiqarish.load_settings(path)
        path.write_text("{buzilgan", encoding="utf-8")
        with self.assertRaises(ReleaseError):
            chiqarish.load_settings(path)

    def test_github_address_matches_what_the_program_checks(self):
        self.assertEqual(
            chiqarish.github_update_url("akkaunt/ombor"), "https://github.com/akkaunt/ombor/releases/latest/download/"
        )
        self.assertEqual(update.check_url(chiqarish.github_update_url("a/b")), chiqarish.github_update_url("a/b"))


class PublishTests(FolderCase):
    def test_folder_gets_both_files_and_the_program_sees_the_update(self):
        target = self.folder / "tarmoq" / "yangilanish"
        chiqarish.publish_to_folder(target, self.dist)
        self.assertEqual(sorted(path.name for path in target.iterdir()), ["MME-Ombor.exe", "versiya.txt"])
        self.assertEqual(update.available(target, "1.4"), ("1.5", target / "MME-Ombor.exe"))
        chiqarish.publish_to_folder(target, self.dist)  # qayta chiqarish ustidan yozadi

    def test_locked_program_file_is_moved_aside(self):
        exe = self.dist / chiqarish.EXE_NAME
        chiqarish.free_dist_exe(self.dist)
        self.assertTrue(exe.exists())  # hech kim ochmagan — joyida qoladi
        chiqarish.free_dist_exe(self.folder / "yoq")

    def test_github_release_is_created_and_files_uploaded(self):
        requests = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                requests.append((self.path, self.headers["Authorization"], body))
                self.send_response(201)
                self.end_headers()
                self.wfile.write(json.dumps({"id": 77}).encode())

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"

        chiqarish.publish_to_github("akkaunt/ombor", "maxfiy-token", "1.5", self.dist, api=base, uploads=base)
        paths = [path for path, _, _ in requests]
        self.assertEqual(
            paths,
            [
                "/repos/akkaunt/ombor/releases",
                "/repos/akkaunt/ombor/releases/77/assets?name=MME-Ombor.exe",
                "/repos/akkaunt/ombor/releases/77/assets?name=versiya.txt",
            ],
        )
        self.assertEqual({token for _, token, _ in requests}, {"Bearer maxfiy-token"})
        self.assertEqual(json.loads(requests[0][2])["tag_name"], "v1.5")
        self.assertEqual(requests[1][2], b"MZ yangi dastur")

    def test_github_refusal_is_reported(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"message": "Bad credentials"}')

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with self.assertRaises(ReleaseError) as caught:
            chiqarish.publish_to_github("a/b", "xato", "1.5", self.dist, api=base, uploads=base)
        self.assertIn("401", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
