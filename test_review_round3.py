"""Test hồi quy cho các lỗi tìm thấy trong đợt review 2026-11-08 (round 3).

Mỗi test ứng với một mục trong CODE-REVIEW-REPORT.md, không suy đoán:
  BUG-1  _track_stats ghi đè thay vì cộng dồn (M2 cũ) — v72.py
  BUG-2  đường browser fallback ghi file vượt MAX_FILE_MB khi server không
         khai báo content-length (H4 phần dư) — downloader.py
  SEC-1  URL ngoài http/https (file://...) lọt qua urlopen — fast_fetch.py

Chạy: python -m unittest test_review_round3 -v
"""

from test_common import setUpModule, tearDownModule, soup_of  # noqa: F401

import asyncio
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config


# ---------- fake cho đường tải Playwright (không cần trình duyệt thật) ----------

class _FakeResponse:
    """Response giả: 200, KHÔNG header (không content-length), body cho sẵn.

    Không content-length chính là khe hở BUG-2: _too_big() chỉ chặn được khi
    server khai báo kích thước — chunked response thì lưới trước là mù.
    """

    def __init__(self, body):
        self.status = 200
        self.headers = {}
        self._body = body

    async def body(self):
        return self._body

    async def dispose(self):
        pass


class _FakeRequest:
    def __init__(self, response):
        self._response = response

    async def get(self, url, headers=None, timeout=None):
        return self._response


class _FakeContext:
    def __init__(self, response):
        self.request = _FakeRequest(response)


class TestStatsAccumulateAcrossThreads(unittest.TestCase):
    """BUG-1 (M2): bộ đếm phải CỘNG DỒN giữa các thread, không lấy số cuối.

    Đo được ở bản lỗi: thread 1 báo 8 ảnh, thread 2 báo 1 ảnh -> dòng trạng
    thái chỉ còn '1 ảnh' dù phiên đã tải 9. Bản PySide6 (ui/worker.py) đã cộng
    dồn từ trước; chỗ Tk là nơi sai lệch.
    """

    def _app(self):
        import tkinter as tk
        import v72
        root = tk.Tk()
        root.withdraw()
        app = v72.XenForoScannerApp(root)
        return app, root

    def test_second_thread_does_not_erase_first(self):
        app, root = self._app()
        try:
            app._safe_log("[✓] A: Bài 1 tải mới 8 ảnh và 2 video")
            app._safe_log("[✓] A: Bài 2 tải mới 1 ảnh")
            self.assertEqual(app._n_image, 9,
                             "8 + 1 phải là 9, không phải số của thread cuối")
            self.assertEqual(app._n_video, 2)
            self.assertEqual(app._last_detail, "9 ảnh, 2 video")
        finally:
            app.cache.close()
            root.destroy()

    def test_errors_accumulate_too(self):
        """Số 'N tệp lỗi' cũng cộng dồn — mỗi thread cảnh báo riêng."""
        app, root = self._app()
        try:
            app._safe_log("   [!] Cảnh báo: 3 tệp lỗi đường truyền trong bài này.")
            app._safe_log("   [!] Cảnh báo: 2 tệp lỗi đường truyền trong bài này.")
            self.assertEqual(app._n_error, 5)
        finally:
            app.cache.close()
            root.destroy()

    def test_launch_resets_counters(self):
        """Cộng dồn chỉ đúng khi mỗi phiên reset về 0 — hai thứ đi cùng nhau.

        Thiếu reset thì phiên sau kế thừa số của phiên trước (lỗi mới do chính
        việc sửa BUG-1 tạo điều kiện), nên khoá chặt hành vi reset lại.
        """
        app, root = self._app()
        try:
            app._n_image, app._n_video, app._n_error = 99, 7, 5
            app._had_error = True
            # Thay run_async_engine bằng stub: _launch vẫn reset + vẫn guard,
            # nhưng không dựng engine/Playwright thật trong test GUI.
            app.run_async_engine = lambda coro_factory: None
            self.assertTrue(app._launch(lambda: None))
            self.assertEqual((app._n_image, app._n_video, app._n_error),
                             (0, 0, 0), "_launch phải reset bộ đếm mỗi phiên")
            self.assertFalse(app._had_error)
        finally:
            app.cache.close()
            root.destroy()


class TestBrowserFallbackSizeCap(unittest.TestCase):
    """BUG-2: body() đã nạp trọn thì phải có lưới SAU, không chỉ lưới trước.

    _too_big() chặn dựa trên content-length; server chunked không gửi header
    đó. Không có check sau body(), một response 2 GB vẫn được ghi đủ xuống đĩa
    dù MAX_FILE_MB=512.
    """

    def _make(self):
        from cache import MediaCache
        from downloader import Downloader
        tmp = tempfile.mkdtemp(prefix="bf_")
        self.addCleanup(shutil.rmtree, tmp, True)
        c = MediaCache(os.path.join(tmp, "c.db"))
        self.addCleanup(c.close)
        d = Downloader(cache=c, log=lambda *a, **k: None,
                       stop_event=threading.Event(),
                       semaphore=asyncio.Semaphore(2),
                       db_lock=asyncio.Lock())
        return d, tmp

    def test_chunked_oversize_body_is_rejected(self):
        d, tmp = self._make()
        old = getattr(config, "MAX_FILE_MB", 512)
        config.MAX_FILE_MB = 1          # trần 1 MB
        try:
            save = os.path.join(tmp, "big.mp4")
            ctx = _FakeContext(_FakeResponse(b"X" * (2 * 1024 * 1024)))

            async def run():
                return await d._fetch_browser(
                    ctx, "https://ex.com/v.mp4", save, "https://ex.com/", "h")

            r = asyncio.run(run())
            self.assertEqual(r, "FAILED")
            self.assertFalse(os.path.exists(save),
                             "file vượt trần không được ghi xuống đĩa")
        finally:
            config.MAX_FILE_MB = old

    def test_small_body_still_saved(self):
        """Chống chặn nhầm: body trong trần vẫn tải OK — cùng đường fake."""
        d, tmp = self._make()
        old = getattr(config, "MAX_FILE_MB", 512)
        config.MAX_FILE_MB = 1
        try:
            save = os.path.join(tmp, "ok.jpg")
            ctx = _FakeContext(_FakeResponse(b"X" * 100))

            async def run():
                return await d._fetch_browser(
                    ctx, "https://ex.com/i.jpg", save, "https://ex.com/", "h")

            r = asyncio.run(run())
            self.assertEqual(r, "OK")
            self.assertTrue(os.path.exists(save))
        finally:
            config.MAX_FILE_MB = old


class TestSchemeGuard(unittest.TestCase):
    """SEC-1: URL ngoài http/https bị chặn ở tầng HTTP.

    VÌ SAO: urljoin giữ nguyên scheme tuyệt đối của URL trong HTML diễn đàn
    (dữ liệu ngoài), mà urllib.urlopen hỗ trợ sẵn file:// — một post chứa
    <img src="file:///C:/..."> khiến app đọc file local rồi ghi vào thư mục tải.
    """

    def test_scheme_ok_helper(self):
        import fast_fetch
        self.assertTrue(fast_fetch.scheme_ok("http://a.b/c"))
        self.assertTrue(fast_fetch.scheme_ok("HTTPS://a.b/c"))
        self.assertFalse(fast_fetch.scheme_ok("file:///C:/x.txt"))
        self.assertFalse(fast_fetch.scheme_ok("ftp://a.b/c"))
        self.assertFalse(fast_fetch.scheme_ok("C:/x.txt"))

    def _secret(self, prefix):
        tmp = tempfile.mkdtemp(prefix=prefix)
        self.addCleanup(shutil.rmtree, tmp, True)
        secret = os.path.join(tmp, "secret.txt")
        with open(secret, "w", encoding="utf-8") as f:
            f.write("NOI_DUNG_BI_MAT")
        return f"file:///{secret.replace(os.sep, '/')}", tmp

    def test_fetch_one_rejects_file_url(self):
        import fast_fetch
        url, _ = self._secret("sc_")
        res = fast_fetch.fetch_one(url)
        self.assertFalse(res.ok, "file:// phải bị từ chối")
        self.assertIn("scheme", res.error)
        self.assertIsNone(res.text, "không được đọc nội dung file local")

    def test_download_to_file_rejects_file_url(self):
        import fast_fetch
        url, tmp = self._secret("sd_")
        dst = os.path.join(tmp, "dst.bin")
        res = fast_fetch.download_to_file(url, dst)
        self.assertFalse(res.ok)
        self.assertIn("scheme", res.error)
        self.assertFalse(os.path.exists(dst),
                         "file local không được sao chép vào thư mục tải")

    def test_streaming_fails_fast_on_scheme(self):
        """_fetch_streaming không được ngủ backoff 3 lần cho URL rác."""
        from cache import MediaCache
        from downloader import Downloader
        tmp = tempfile.mkdtemp(prefix="sf_")
        self.addCleanup(shutil.rmtree, tmp, True)
        c = MediaCache(os.path.join(tmp, "c.db"))
        self.addCleanup(c.close)
        d = Downloader(cache=c, log=lambda *a, **k: None,
                       stop_event=threading.Event(),
                       semaphore=asyncio.Semaphore(2),
                       db_lock=asyncio.Lock())

        async def run():
            return await d._fetch_streaming(
                "file:///C:/Windows/win.ini", os.path.join(tmp, "x.jpg"),
                "https://ex.com/", "h")

        t0 = time.perf_counter()
        r = asyncio.run(run())
        self.assertEqual(r, "FAILED")
        self.assertLess(time.perf_counter() - t0, 1.0,
                        "phải fail nhanh, không ngủ backoff MAX_RETRIES lần")

    def test_relative_url_rejected_not_crash(self):
        """URL tương đối lệch tới tầng HTTP cũng bị chặn sạch, không exception."""
        import fast_fetch
        res = fast_fetch.download_to_file("/images/a.jpg", "unused.bin")
        self.assertFalse(res.ok)
        self.assertIn("scheme", res.error)


if __name__ == "__main__":
    unittest.main()
