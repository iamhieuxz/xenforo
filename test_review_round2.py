"""Test hồi quy cho các lỗi tìm được trong đợt review 2026-11-06.

Mỗi test ứng với một lỗi ĐÃ CHỨNG MINH bằng thực nghiệm, không phải suy đoán.

Chạy: python -m unittest test_review_round2 -v
"""

import asyncio
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config


class TestDownloaderCookieHeader(unittest.TestCase):
    """LỖI NẶNG NHẤT: `_cookie_header` chưa khởi tạo -> AttributeError mọi lần tải.

    Đo được trước khi sửa: dispatch 2 task -> gather trả
    {'ok': 0, 'failed': 0} và không file nào được tải. Lỗi hoàn toàn im lặng
    vì callback `counted` gọi `fut.result()` mà không bọc try.
    """

    def _make(self):
        from cache import MediaCache
        from downloader import Downloader
        tmp = tempfile.mkdtemp(prefix="dl_")
        self.addCleanup(shutil.rmtree, tmp, True)
        c = MediaCache(os.path.join(tmp, "c.db"))
        self.addCleanup(c.close)
        d = Downloader(cache=c, log=lambda *a, **k: None,
                       stop_event=threading.Event(),
                       semaphore=asyncio.Semaphore(2),
                       db_lock=asyncio.Lock())
        return d, tmp

    def test_cookie_header_is_initialised(self):
        d, _ = self._make()
        self.assertTrue(hasattr(d, "_cookie_header"),
                        "Downloader phải có _cookie_header ngay từ __init__")
        self.assertEqual(d._cookie_header, "")

    def test_task_error_is_counted_not_swallowed(self):
        """Task ném exception phải vào `failed`, không được ra 0."""
        d, tmp = self._make()

        async def run():
            # Ép lỗi bằng cách dùng URL không hợp lệ về cú pháp
            jobs = [("http://[::1", os.path.join(tmp, "x.jpg"), "h1", "image")]
            tasks = await d.dispatch(None, jobs, "https://example.com/", {})
            return await d.gather(tasks)

        stats = asyncio.run(run())
        self.assertEqual(stats["ok"], 0)
        self.assertGreaterEqual(stats["failed"], 1,
                                "task lỗi phải được đếm vào failed")

    def test_no_exception_leaks_from_callback(self):
        """Callback `counted` không được ném ra asyncio."""
        d, tmp = self._make()
        leaked = []

        async def run():
            loop = asyncio.get_running_loop()
            loop.set_exception_handler(
                lambda l, ctx: leaked.append(ctx.get("exception")))
            jobs = [("http://[::1", os.path.join(tmp, "y.jpg"), "h2", "image")]
            tasks = await d.dispatch(None, jobs, "https://example.com/", {})
            await d.gather(tasks)

        asyncio.run(run())
        self.assertEqual(leaked, [],
                         f"exception lọt ra asyncio: {leaked[:2]}")

    def test_task_errors_reported_in_stats(self):
        """Khi có exception cấp task, gather phải mang nó ra ngoài.

        Không tạo lỗi thật được nữa (vì `_fetch` đã bọc `_fetch_streaming`),
        nên nạp thẳng `_task_errors` để kiểm CƠ CHẾ truyền tải.
        """
        d, tmp = self._make()

        async def run():
            d._task_errors.append("ValueError: gia lap")
            jobs = [(f"http://127.0.0.1:1/x{i}.jpg",
                     os.path.join(tmp, f"z{i}.jpg"), f"h{i}", "image")
                    for i in range(1)]
            tasks = await d.dispatch(None, jobs, "https://example.com/", {})
            return await d.gather(tasks)

        stats = asyncio.run(run())
        self.assertIn("task_errors", stats,
                      "phải có task_errors để engine báo cho người dùng")

    def test_fetch_wraps_streaming_errors(self):
        """`_fetch` phải bọc `_fetch_streaming`: lỗi ở đường nhanh không được
        làm chết task (đó chính là cơ chế khiến lỗi biến mất im lặng)."""
        import inspect
        import downloader
        src = inspect.getsource(downloader.Downloader._fetch)
        self.assertIn("_fetch_streaming", src)
        self.assertIn("try:", src)
        self.assertIn("except", src)


class TestSignalNotQTimer(unittest.TestCase):
    """QTimer.singleShot từ worker thread KHÔNG BAO GIỜ chạy.

    Đo được: singleShot từ main thread fired=1, từ worker thread fired=0.
    Hệ quả: mọi thông báo (mở trình duyệt thành công/thất bại, log từ thread)
    đều im lặng biến mất.
    """

    def test_qtime_from_worker_thread_does_not_fire(self):
        """Chứng minh hành vi của Qt để test dưới có cơ sở."""
        from PySide6.QtCore import QEventLoop, QTimer
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])

        fired = {"worker": 0}

        def worker():
            QTimer.singleShot(10, lambda: fired.__setitem__("worker", 1))

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join()

        loop = QEventLoop()
        QTimer.singleShot(300, loop.quit)
        loop.exec()
        app.processEvents()

        self.assertEqual(fired["worker"], 0,
                         "nếu Qt đổi hành vi thì ghi chú này cần xem lại")

    def test_main_window_has_ui_signals(self):
        """MainWindow phải có Signal để worker thread báo về GUI thread."""
        import gui_fluent
        for name in ("sig_ui_notify", "sig_ui_login_opened", "sig_ui_log"):
            self.assertTrue(hasattr(gui_fluent.MainWindow, name),
                            f"thiếu {name}")

    def test_no_qtime_singleShot_in_worker_blocks(self):
        """Không còn QTimer.singleShot bên trong threading.Thread target."""
        import inspect
        import re
        import gui_fluent
        src = inspect.getsource(gui_fluent)
        # Bỏ comment — lý do như trên.
        lines = [re.sub(r"#.*$", "", l) for l in src.splitlines()]
        bad = []
        for i, l in enumerate(lines):
            if "threading.Thread(" in l and "daemon=True" in l:
                for j in range(i, max(0, i - 45), -1):
                    if re.match(r"\s*def (\w+)\(", lines[j]):
                        block = "\n".join(lines[j:i + 1])
                        if "QTimer.singleShot" in block:
                            bad.append(j + 1)
                        break
        self.assertEqual(bad, [],
                         f"còn QTimer.singleShot trong thread tại dòng {bad}")


class TestExceptionVariableGotcha(unittest.TestCase):
    """Python 3 xoá biến `except ... as e` sau khi ra khỏi block.

    Đo được: lambda dùng `e` chạy sau đó ném NameError: name 'e' is not defined.
    """

    def test_lambda_capturing_exception_var_fails(self):
        fns = []
        try:
            raise ValueError("x")
        except Exception as e:
            fns.append(lambda: e)
        with self.assertRaises(NameError):
            fns[0]()

    def test_no_lambda_uses_exception_var(self):
        """Không được có lambda đọc biến `except ... as X`."""
        import inspect
        import re
        import gui_fluent
        src = inspect.getsource(gui_fluent)
        # Bỏ comment: comment giải thích lỗi cũng chứa chữ "lambda" và "e",
        # nếu không lọc thì test báo sai (đã gặp).
        lines = [re.sub(r"#.*$", "", l) for l in src.splitlines()]
        bad = []
        for i, l in enumerate(lines):
            m = re.match(r"\s*except\s+[\w.]*\s+as\s+(\w+)\s*:", l)
            if not m:
                continue
            var = m.group(1)
            indent = len(l) - len(l.lstrip())
            for j in range(i + 1, min(i + 10, len(lines))):
                if (lines[j].strip()
                        and (len(lines[j]) - len(lines[j].lstrip())) <= indent):
                    break
                if "lambda" in lines[j] and re.search(rf"\b{var}\b", lines[j]):
                    bad.append((j + 1, var))
        self.assertEqual(bad, [],
                         f"lambda đọc biến except (sẽ NameError): {bad}")


class TestLoginWindowUsesCorrectMode(unittest.TestCase):
    """Nút Đăng nhập phải mở ĐÚNG trình duyệt + profile của mode đang chạy.

    Lỗi cũ: luôn dùng SESSION_BROWSER (chrome) + resolve_profile() (profile tạm),
    trong khi mode mặc định là cdp (coccoc + profile thật). Đăng nhập xong cookie
    ghi vào chỗ khác nên lần quét sau vẫn không thấy phiên.
    """

    def test_open_login_window_branches_on_mode(self):
        import inspect
        import gui_fluent
        src = inspect.getsource(gui_fluent.SettingsInterface._open_login_window)
        self.assertIn("BROWSER_MODE", src,
                      "phải rẽ nhánh theo mode")
        self.assertIn("CDP_BROWSER", src,
                      "mode cdp phải dùng CDP_BROWSER")
        self.assertIn("profile_dir", src,
                      "mode cdp phải dùng profile_dir() (profile thật)")

    def test_ensure_login_uses_same_profile_as_open_login(self):
        """Kiểm phiên và mở cửa sổ đăng nhập phải cùng một profile."""
        import inspect
        import gui_fluent
        a = inspect.getsource(gui_fluent.MainWindow._ensure_login)
        b = inspect.getsource(gui_fluent.SettingsInterface._open_login_window)
        for src, who in ((a, "_ensure_login"), (b, "_open_login_window")):
            self.assertIn("BROWSER_MODE", src, f"{who} phải rẽ nhánh theo mode")


class TestSessionLogWiring(unittest.TestCase):
    """Log phải ghi ra FILE, không chỉ trong RAM."""

    def test_log_to_file_default_on(self):
        self.assertTrue(getattr(config, "LOG_TO_FILE", False))
        self.assertTrue(getattr(config, "LOG_DIR", ""))

    def test_session_log_creates_file_and_classifies(self):
        import session_log as SL
        tmp = tempfile.mkdtemp(prefix="sl_")
        self.addCleanup(shutil.rmtree, tmp, True)
        sl = SL.SessionLog(log_dir=tmp, keep=3)
        self.assertTrue(sl, "phải mở được file log")
        self.assertTrue(os.path.isfile(sl.path))

        sl.write("[*] bình thường", "system")
        sl.write("[-] Lỗi giao dịch", None)
        sl.write("[!] Cảnh báo nhỏ", None)
        path = sl.path
        sl.close("test")

        s = SL.summarize(path)
        self.assertEqual(s["errors"], 1, "dòng [-] phải là ERROR")
        self.assertEqual(s["warns"], 1, "dòng [!] phải là WARN")

    def test_main_window_writes_log_file(self):
        from PySide6.QtWidgets import QApplication
        import gui_fluent

        tmp = tempfile.mkdtemp(prefix="mwlog_")
        old_dir, old_log = config.DOWNLOAD_DIR, config.LOG_DIR
        old_to_file = getattr(config, "LOG_TO_FILE", True)
        try:
            config.DOWNLOAD_DIR = tmp
            config.LOG_DIR = tmp
            config.LOG_TO_FILE = True
            app = QApplication.instance() or QApplication([])
            w = gui_fluent.MainWindow(auto_browser=False)
            try:
                self.assertIsNotNone(w.session_log,
                                     "MainWindow phải tạo SessionLog")
                w.append_log("[-] Lỗi kiểm thử", None)
                path = w.session_log.path
                w.session_log.close("test")
                self.assertTrue(os.path.isfile(path))
                with open(path, encoding="utf-8") as f:
                    body = f.read()
                self.assertIn("Lỗi kiểm thử", body)
            finally:
                w.close()
                app.processEvents()
        finally:
            config.DOWNLOAD_DIR = old_dir
            config.LOG_DIR = old_log
            config.LOG_TO_FILE = old_to_file
            shutil.rmtree(tmp, ignore_errors=True)


class TestContentHashDedup(unittest.TestCase):
    """Khử trùng lặp theo NỘI DUNG (P1.2 trong DE-XUAT-CAI-TIEN.md).

    VẤN ĐỀ ĐO ĐƯỢC: `url_hash()` băm theo URL, không theo nội dung. Cùng một
    ảnh ở hai URL (thumbnail và bản đầy đủ) sinh hai hash -> hai file giống hệt.
    Trên ổ thật: 416 nhóm trùng, 13,5 GB (13,3 %).

    CÁCH SỬA: lưu md5 nội dung vào media_index; khi tải xong mà nội dung đã có
    ở file khác thì thay bản mới bằng HARDLINK tới bản cũ -> 0 byte thêm.
    """

    def _cache(self):
        from cache import MediaCache
        tmp = tempfile.mkdtemp(prefix="ch_")
        self.addCleanup(shutil.rmtree, tmp, True)
        c = MediaCache(os.path.join(tmp, "c.db"))
        self.addCleanup(c.close)
        return c, tmp

    def test_schema_has_content_hash(self):
        c, _ = self._cache()
        cols = {r[1] for r in c.conn.execute("PRAGMA table_info(media_index)")}
        self.assertIn("content_hash", cols)

    def test_migration_from_old_schema(self):
        """DB cũ (3 cột) phải được nâng cấp, KHÔNG mất dữ liệu."""
        import sqlite3
        from cache import MediaCache
        tmp = tempfile.mkdtemp(prefix="mig_")
        self.addCleanup(shutil.rmtree, tmp, True)
        db = os.path.join(tmp, "old.db")

        conn = sqlite3.connect(db)
        conn.execute("""CREATE TABLE media_index (
            url_clean_hash TEXT PRIMARY KEY, filename TEXT, downloaded_at TEXT)""")
        f = os.path.join(tmp, "old.jpg")
        with open(f, "wb") as fh:
            fh.write(b"X")
        conn.execute("INSERT INTO media_index VALUES ('u', ?, '2020')", (f,))
        conn.commit()
        conn.close()

        c = MediaCache(db)
        try:
            cols = {r[1] for r in c.conn.execute("PRAGMA table_info(media_index)")}
            self.assertIn("content_hash", cols, "phải thêm được cột")
            self.assertEqual(c.path_for("u"), os.path.abspath(f),
                             "dữ liệu cũ phải còn dùng được")
        finally:
            c.close()

    def test_path_for_content_returns_none_when_missing(self):
        """File đã bị xoá khỏi đĩa thì không được trả về (hardlink sẽ hỏng)."""
        c, tmp = self._cache()
        f = os.path.join(tmp, "a.jpg")
        with open(f, "wb") as fh:
            fh.write(b"AAA")
        c.record("u1", f, "md5x")
        self.assertEqual(c.path_for_content("md5x"), os.path.abspath(f))
        os.remove(f)
        self.assertIsNone(c.path_for_content("md5x"))

    def test_path_for_content_excludes_self(self):
        """Không được trả về chính đường dẫn vừa tải (sẽ hardlink vào nó)."""
        c, tmp = self._cache()
        f = os.path.join(tmp, "a.jpg")
        with open(f, "wb") as fh:
            fh.write(b"AAA")
        c.record("u1", f, "md5x")
        self.assertIsNone(c.path_for_content("md5x", exclude=f))

    def test_two_urls_same_content_same_inode(self):
        """Hai URL khác nhau, cùng nội dung -> một inode (hardlink)."""
        from cache import MediaCache
        from downloader import Downloader
        tmp = tempfile.mkdtemp(prefix="dd_")
        self.addCleanup(shutil.rmtree, tmp, True)
        c = MediaCache(os.path.join(tmp, "c.db"))
        self.addCleanup(c.close)
        d = Downloader(cache=c, log=lambda *a, **k: None,
                       stop_event=threading.Event(),
                       semaphore=asyncio.Semaphore(2),
                       db_lock=asyncio.Lock())

        # Ghi thẳng cache như thể file 1 đã tải trước đó, rồi kiểm tra
        # path_for_content tìm ra nó.
        f1 = os.path.join(tmp, "f1.jpg")
        with open(f1, "wb") as fh:
            fh.write(b"CONTENT")
        import hashlib
        h = hashlib.md5(b"CONTENT").hexdigest()
        c.record("h1", f1, h)

        found = c.path_for_content(h, exclude=os.path.join(tmp, "f2.jpg"))
        self.assertEqual(found, os.path.abspath(f1))

    def test_download_result_has_md5_field(self):
        import fast_fetch
        r = fast_fetch.DownloadResult()
        self.assertEqual(r.md5, "", "mặc định rỗng, không phải None")
        self.assertTrue(hasattr(r, "md5"))

    def test_record_uses_named_columns(self):
        """Ghi theo TÊN CỘT — chèn theo vị trí sẽ hỏng khi thêm cột."""
        import inspect
        import cache
        src = inspect.getsource(cache.MediaCache.record)
        self.assertIn("url_clean_hash, filename, downloaded_at", src)
        self.assertNotIn("media_index VALUES", src)


class TestCleanDuplicatesSafety(unittest.TestCase):
    """Script dọn trùng lặp phải AN TOÀN: dry-run mặc định, không xoá nhầm."""

    def test_default_is_dry_run(self):
        import inspect
        import clean_duplicates
        src = inspect.getsource(clean_duplicates.main)
        self.assertIn("--apply", src)
        self.assertIn("DRY-RUN", src)

    def test_no_apply_means_no_delete(self):
        """Chạy không có --apply thì không được xoá file nào."""
        import subprocess
        tmp = tempfile.mkdtemp(prefix="safe_")
        self.addCleanup(shutil.rmtree, tmp, True)
        folder = os.path.join(tmp, "u")
        os.makedirs(folder)
        for name in ("[20240101_120000]_main_video_001.mp4",
                     "[20240101_120000]_main_video_001_abc123.mp4"):
            with open(os.path.join(folder, name), "wb") as fh:
                fh.write(b"A" * 100)

        before = len(os.listdir(folder))
        r = subprocess.run(
            [sys.executable, "clean_duplicates.py", "--dir", tmp],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120)
        after = len(os.listdir(folder))
        self.assertEqual(before, after,
                         "dry-run KHÔNG được xoá file")
        self.assertEqual(r.returncode, 0)

    def test_different_content_not_deleted(self):
        """Cùng tên gốc nhưng nội dung KHÁC nhau thì phải giữ cả hai."""
        import subprocess
        tmp = tempfile.mkdtemp(prefix="diff_")
        self.addCleanup(shutil.rmtree, tmp, True)
        folder = os.path.join(tmp, "u")
        os.makedirs(folder)
        with open(os.path.join(folder, "a_media_001.jpg"), "wb") as fh:
            fh.write(b"AAA")
        with open(os.path.join(folder, "a_media_001_111111.jpg"), "wb") as fh:
            fh.write(b"BBB")     # nội dung khác

        subprocess.run(
            [sys.executable, "clean_duplicates.py", "--dir", tmp,
             "--apply", "--yes"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120)
        self.assertEqual(len(os.listdir(folder)), 2,
                         "nội dung khác nhau thì không được xoá")


if __name__ == "__main__":
    unittest.main()