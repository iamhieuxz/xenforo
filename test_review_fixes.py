"""Test hồi quy cho các lỗi tìm thấy trong đợt review 2026-11-06.

Mỗi test ứng với một lỗi ĐÃ ĐO ĐƯỢC bằng thực nghiệm, không phải suy đoán.
Chạy: python -m unittest test_review_fixes -v
"""

import asyncio
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import browser_launcher as B
import config
import xenforo_parse as X
from cache import MediaCache, LocalUserIndex


class TestCdpPortControl(unittest.TestCase):
    """Cổng CDP: không được nhầm "có gì đó trả lời" với "Chromium thật"."""

    def test_cdp_url_derives_from_port(self):
        """CDP_URL phải suy ra từ CDP_PORT, không phải literal thứ hai."""
        self.assertIn(f":{config.CDP_PORT}", config.CDP_URL,
                      "đổi CDP_PORT mà URL không đổi -> kết nối sai cổng")

    def test_cdp_url_uses_ipv4_literal(self):
        """Không dùng 'localhost': Windows resolve ra ::1 trước, Chromium bind IPv4."""
        self.assertNotIn("localhost", config.CDP_URL,
                         "localhost có thể resolve ra ::1 -> request bị refuse")
        self.assertNotIn("localhost", B._cdp_base())

    def test_probe_closed_port(self):
        st = B.probe_port(timeout=0.3)
        self.assertIn(st["state"], ("closed", "not_chromium"))
        if st["state"] == "closed":
            self.assertFalse(B.is_port_open(timeout=0.3))

    def test_probe_detects_non_chromium_server(self):
        """Server HTTP thường chiếm cổng: phải là not_chromium, không phải ready."""
        import http.server

        class Plain(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"<html>not cdp</html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        try:
            srv = http.server.HTTPServer(("127.0.0.1", config.CDP_PORT), Plain)
        except OSError as e:
            self.skipTest(f"cổng {config.CDP_PORT} đang bận: {e}")
            return
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        time.sleep(0.3)
        try:
            st = B.probe_port()
            self.assertEqual(st["state"], "not_chromium",
                             f"bị đánh lừa bởi server không phải CDP: {st}")
            self.assertFalse(B.is_port_open(),
                             "is_port_open không được trả True cho server lạ")
            ok, msg = B.launch()
            self.assertFalse(ok, "launch() không được coi cổng bị chiếm là 'đã sẵn sàng'")
            self.assertIn("chiếm", msg.lower())
        finally:
            srv.shutdown()
            srv.server_close()

    def test_probe_accepts_real_chromium_json(self):
        """Server trả /json/version đúng chuẩn Chromium -> ready."""
        import http.server
        import json as _json

        class Like(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = _json.dumps({
                    "Browser": "Chrome/152.0.0",
                    "webSocketDebuggerUrl": "ws://127.0.0.1/x",
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        try:
            srv = http.server.HTTPServer(("127.0.0.1", config.CDP_PORT), Like)
        except OSError as e:
            self.skipTest(f"cổng {config.CDP_PORT} đang bận: {e}")
            return
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        time.sleep(0.3)
        try:
            st = B.probe_port()
            self.assertEqual(st["state"], "ready", st)
            self.assertIn("Chrome", st["detail"])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_shutdown_without_launch_is_noop(self):
        self.assertFalse(B.shutdown())
        self.assertIsNone(B._launched_process)

    def test_build_args_puts_port_and_profile(self):
        args = B.build_args("C:/b.exe", "C:/prof")
        self.assertTrue(any(f"--remote-debugging-port={config.CDP_PORT}" == a for a in args))
        self.assertTrue(any(a == "--user-data-dir=C:/prof" for a in args))


class TestMediaCacheThreadSafety(unittest.TestCase):
    """Đo được ở bản cũ: 4 thread × 300 ghi -> chỉ 322/1200 dòng, 3 exception."""

    def test_concurrent_writes_do_not_lose_rows(self):
        d = tempfile.mkdtemp(prefix="cachets")
        try:
            c = MediaCache(os.path.join(d, "t.db"))
            errors = []

            def writer(tid):
                try:
                    for i in range(150):
                        c.record(f"h{tid}_{i}", os.path.join(d, f"f{tid}_{i}.jpg"))
                except Exception as e:
                    errors.append(f"thread{tid}: {type(e).__name__}: {e}")

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            n = c.conn.execute("SELECT COUNT(*) FROM media_index").fetchone()[0]
            c.close()
            self.assertEqual(errors, [], f"có exception khi ghi song song: {errors[:3]}")
            self.assertEqual(n, 600, f"mất dữ liệu: ghi được {n}/600 dòng")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_concurrent_read_write(self):
        d = tempfile.mkdtemp(prefix="cachets2")
        try:
            c = MediaCache(os.path.join(d, "t.db"))
            stop = threading.Event()
            errors = []

            def reader():
                try:
                    while not stop.is_set():
                        c.path_for("h0_1")
                except Exception as e:
                    errors.append(f"reader: {type(e).__name__}: {e}")

            r = threading.Thread(target=reader, daemon=True)
            r.start()
            try:
                for i in range(200):
                    c.record(f"h0_{i}", os.path.join(d, f"f{i}.jpg"))
            finally:
                stop.set()
                r.join(timeout=2)
            c.close()
            self.assertEqual(errors, [], errors[:3])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_local_user_index_uses_same_lock(self):
        d = tempfile.mkdtemp(prefix="lu")
        try:
            c = MediaCache(os.path.join(d, "t.db"))
            idx = LocalUserIndex(c.conn)
            for name in ("userA", "userB"):
                os.makedirs(os.path.join(d, name), exist_ok=True)
            n = idx.refresh(d)
            self.assertEqual(n, 2)
            self.assertEqual(idx.names(), ["userA", "userB"])
            c.close()
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestWindowsFilenameSafety(unittest.TestCase):
    """Ba lỗi ghi file đã đo được ở clean_name bản cũ."""

    def test_null_byte_removed(self):
        """Bản cũ giữ \\x00 -> open() ném ValueError: embedded null character."""
        name = X.clean_name("abc\x00def")
        self.assertNotIn("\x00", name)
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, name + ".jpg")
            with open(p, "wb") as f:
                f.write(b"x")
            self.assertTrue(os.path.exists(p))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_windows_device_name_with_extension(self):
        """'con.txt' vẫn bị Windows chặn; bản cũ chỉ so khớp nguyên chuỗi."""
        for raw in ("con.txt", "PRN.log", "COM1.mp4", "nul.txt"):
            name = X.clean_name(raw)
            self.assertTrue(name.startswith("_"),
                            f"{raw!r} -> {name!r} chưa được chặn")
        d = tempfile.mkdtemp()
        try:
            for raw in ("con.txt", "PRN.log"):
                p = os.path.join(d, X.clean_name(raw))
                with open(p, "wb") as f:
                    f.write(b"x")
                os.remove(p)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_control_characters_removed(self):
        self.assertEqual(X.clean_name("a\x01b\x1fc"), "abc")

    def test_vietnamese_diacritics_preserved(self):
        """Không được lọc mất dấu tiếng Việt khi loại ký tự điều khiển."""
        s = "Bài viết có dấu tiếng Việt"
        self.assertEqual(X.clean_name(s), s)


class TestMaxPathBudget(unittest.TestCase):
    """Bản cũ: base_dir sâu + tiêu đề 200 ký tự -> đường dẫn 281 ký tự (>260)."""

    def test_long_title_fits_within_max_path(self):
        for base in (r"E:\HIDE\RPHANG",
                     r"F:\a-very-long-base-folder-name-here\RPHANG"):
            folder = X.thread_folder(base, "someuser", "a" * 400, "2024-01-01")
            media = os.path.join(
                folder, "[20240101_120000]_media_001_slug_abcdef.jpg")
            self.assertLessEqual(len(media), 260,
                                 f"vượt MAX_PATH: {len(media)} ký tự")

    def test_short_title_not_truncated(self):
        folder = X.thread_folder(r"E:\X\RPHANG", "u",
                                 "Bai viet binh thuong", "2024-01-01")
        self.assertIn("Bai viet binh thuong", folder)

    def test_folder_is_stable_across_calls(self):
        a = X.thread_folder(r"E:\X\RPHANG", "u", "T" * 300, "2024-01-01")
        b = X.thread_folder(r"E:\X\RPHANG", "u", "T" * 300, "2024-01-01")
        self.assertEqual(a, b, "folder đổi tên giữa 2 lần gọi -> tải lại toàn bộ")

    def test_missing_date_uses_stable_label(self):
        folder = X.thread_folder(r"E:\X\RPHANG", "u", "A", "")
        self.assertIn("khong-ngay", folder)
        self.assertNotIn("0000", folder)


class TestBoundedUserWorkers(unittest.TestCase):
    """Bản cũ gather() toàn bộ user: 500 user -> 500 coroutine cùng sống."""

    def test_worker_count_is_bounded(self):
        import inspect
        import engine
        src = inspect.getsource(engine.CrawlerEngine.crawl_users)
        self.assertIn("queue", src, "phải dùng queue thay vì gather hết")
        self.assertIn("min(max(1, config.USER_SEM), total)", src,
                      "số worker phải bị chặn trên bởi USER_SEM")

    def test_empty_user_list_returns_early(self):
        import inspect
        import engine
        src = inspect.getsource(engine.CrawlerEngine.crawl_users)
        self.assertIn("if not total", src)


class TestEngineCacheOptional(unittest.TestCase):
    """Engine phải chịu được cache=None (đường test dùng)."""

    def test_engine_accepts_none_cache(self):
        import engine
        e = engine.CrawlerEngine(cache=None, log=lambda *a, **k: None,
                                 stop_event=threading.Event())
        self.assertIsNone(e.cache)


if __name__ == "__main__":
    unittest.main()
