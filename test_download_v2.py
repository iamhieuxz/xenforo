"""Test cho downloader + fast_fetch. Tách từ test_v72.py (P2.2).

setUpModule/tearDownModule và soup_of lấy từ test_common
(chung cơ chế cô lập cho mọi file tách từ test_v72).
"""

from test_common import setUpModule, tearDownModule, soup_of  # noqa: F401

import os
import re
import shutil
import tempfile
import threading
import unittest

import asyncio

from bs4 import BeautifulSoup

import config
import xf_selectors as S
import xenforo_parse as X
import downloader
from downloader import (Downloader, backoff_seconds, plan_jobs, url_hash,
                        count_files, index_folder)
import engine
from cache import MediaCache, LocalUserIndex
import fast_fetch
import browser_launcher as B


import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')


class TestBackoff(unittest.TestCase):
    """Retry phải có jitter và trần thật.

    Bug cũ: `sleep(2 * (attempt + 1))` cố định -> 10 worker cùng nhịp, cùng hỏi
    lại server ở cùng thời điểm, dễ bị rate-limit tập thể.
    """

    def test_has_jitter(self):
        from downloader import backoff_seconds
        samples = {round(backoff_seconds(2), 4) for _ in range(30)}
        self.assertGreater(len(samples), 1, "không có jitter thì các worker vẫn cùng nhịp")

    def test_cap_is_a_real_cap(self):
        """Trần phải là trần thật: cap 30 thì không được ngủ 32."""
        from downloader import backoff_seconds
        for attempt in range(30):
            self.assertLessEqual(backoff_seconds(attempt), 30.0,
                                 f"attempt {attempt} vượt trần")

    def test_grows_then_plateaus(self):
        from downloader import backoff_seconds
        low = max(backoff_seconds(0) for _ in range(20))
        mid = max(backoff_seconds(2) for _ in range(20))
        self.assertGreater(mid, low, "phải tăng theo số lần thử")
        high = backoff_seconds(20)
        self.assertLessEqual(high, 30.0)

    def test_never_negative_or_zero(self):
        from downloader import backoff_seconds
        for attempt in range(10):
            self.assertGreater(backoff_seconds(attempt), 0)


class TestDedupeWithinThread(unittest.TestCase):
    """seen_hashes chỉ được ghi khi tải THÀNH CÔNG.

    Bug cũ: ghi path ngay trong vòng lặp dispatch, trước khi tải. Một URL xuất
    hiện ở hai post mà lần đầu fail (500, timeout) thì lần hai bị coi là "đã
    xử lý" -> media mất im lặng.
    """

    class _Resp:
        def __init__(self, status):
            self.status = status
            self.headers = {"content-type": "image/jpeg"}

        async def body(self):
            return b"bytes" if self.status == 200 else b""

        async def dispose(self):
            pass

    class _NoStop:
        @staticmethod
        def is_set():
            return False

    def _dispatch_twice(self, first_ok):
        """first_ok=False: mọi request ở lần dispatch đầu trả 404 (lỗi vĩnh viễn,
        không retry nên test nhanh và tất định). first_ok=True: trả 200."""
        import asyncio, tempfile, shutil
        from downloader import Downloader

        tmp = tempfile.mkdtemp(prefix="dedupe")
        try:
            state = {"ok": first_ok}

            class _Req:
                async def get(inner, url, headers=None, timeout=None):
                    return TestDedupeWithinThread._Resp(200 if state["ok"] else 404)

            class _Ctx:
                request = _Req()

            class _Cache:
                @staticmethod
                def path_for(h):
                    return None

                @staticmethod
                def record(h, p):
                    pass

            async def run():
                d = Downloader(cache=_Cache(), log=lambda *a, **k: None,
                               stop_event=TestDedupeWithinThread._NoStop(),
                               semaphore=asyncio.Semaphore(2), db_lock=asyncio.Lock())
                seen, folder, url = {}, os.path.join(tmp, "f"), "http://x/same.jpg"
                t1 = await d.dispatch(_Ctx(), [(url, os.path.join(folder, "a.jpg"),
                                                "H", "image")], "http://ref", seen)
                await d.gather(t1)
                a_ok = os.path.exists(os.path.join(folder, "a.jpg"))
                state["ok"] = True          # từ đây server hoạt động bình thường
                t2 = await d.dispatch(_Ctx(), [(url, os.path.join(folder, "b.jpg"),
                                                "H", "image")], "http://ref", seen)
                await d.gather(t2)
                return len(t1), len(t2), a_ok, os.path.exists(os.path.join(folder, "b.jpg"))

            return asyncio.run(run())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_failed_first_attempt_retries_second_occurrence(self):
        n1, n2, a_ok, b_ok = self._dispatch_twice(first_ok=False)
        self.assertEqual(n1, 1)
        self.assertFalse(a_ok, "lần 1 phải fail (404)")
        self.assertEqual(n2, 1, "lần 2 cùng URL phải được tải lại, không bị coi là đã xử lý")
        self.assertTrue(b_ok, "lần 2 thành công thì file phải có")

    def test_successful_first_attempt_is_cloned_not_refetched(self):
        n1, n2, a_ok, b_ok = self._dispatch_twice(first_ok=True)
        self.assertTrue(a_ok)
        self.assertEqual(n2, 0, "đã tải thành công rồi thì phải clone, không tải lại")
        self.assertTrue(b_ok, "clone phải tạo ra file thứ hai")


class TestDiskSpaceGuard(unittest.TestCase):
    """Hết đĩa giữa chừng để lại file cụt + loạt lỗi khó hiểu."""

    def _dl(self):
        from downloader import Downloader
        class _NoStop:
            @staticmethod
            def is_set():
                return False
        return Downloader(cache=None, log=lambda *a, **k: None, stop_event=_NoStop(),
                          semaphore=None, db_lock=None)

    def test_normal_size_passes(self):
        d = self._dl()
        self.assertFalse(d._disk_full(os.path.join(tempfile.gettempdir(), "x.bin"),
                                      1024))

    def test_absurd_size_is_refused(self):
        d = self._dl()
        self.assertTrue(d._disk_full(os.path.join(tempfile.gettempdir(), "x.bin"),
                                     10 ** 18))

    def test_unknown_size_is_not_refused(self):
        d = self._dl()
        self.assertFalse(d._disk_full(tempfile.gettempdir(), None))

    def test_free_bytes_returns_number(self):
        d = self._dl()
        free = d._free_bytes(tempfile.gettempdir())
        self.assertIsNotNone(free)
        self.assertGreater(free, 0)


class TestDownloadIntegrityGuards(unittest.TestCase):
    """Chặn file quá lớn TRƯỚC khi nạp, và phát hiện tải thiếu dữ liệu.

    H4 gốc muốn streaming, nhưng Playwright 1.54 không có API stream cho
    context.request: APIResponse chỉ có body() nạp toàn bộ payload vào RAM. Vì
    vậy hai chốt khả thi là kiểm content-length trước khi gọi body(), và so
    content-length với số byte thực nhận trước khi ghi ra file.
    """

    class _NoStop:
        @staticmethod
        def is_set():
            return False

    class _Cache:
        @staticmethod
        def path_for(h):
            return None

        @staticmethod
        def record(h, p):
            pass

    def _fetch(self, resp, max_mb=512):
        import asyncio, tempfile, shutil
        from downloader import Downloader

        tmp = tempfile.mkdtemp(prefix="integrity")
        real = config.MAX_FILE_MB
        config.MAX_FILE_MB = max_mb
        try:
            class _Req:
                async def get(inner, url, headers=None, timeout=None):
                    return resp

            class _Ctx:
                request = _Req()

            async def run():
                logs = []
                d = Downloader(cache=self._Cache(), log=lambda m, t=None: logs.append(m),
                               stop_event=self._NoStop(),
                               semaphore=asyncio.Semaphore(2), db_lock=asyncio.Lock())
                tasks = await d.dispatch(
                    _Ctx(), [("http://x/f.bin", os.path.join(tmp, "f.bin"), "H", "file")],
                    "http://ref", {})
                stats = await d.gather(tasks)
                return stats, os.path.exists(os.path.join(tmp, "f.bin")), logs

            return asyncio.run(run())
        finally:
            config.MAX_FILE_MB = real
            shutil.rmtree(tmp, ignore_errors=True)

    def test_oversized_file_rejected_before_body(self):
        """Không được gọi body() khi đã biết vượt trần — đó là điểm hết RAM."""
        class Big:
            status = 200
            headers = {"content-type": "video/mp4",
                       "content-length": str(600 * 1024 * 1024)}

            async def body(self):
                raise AssertionError("body() không được gọi khi đã biết quá lớn")

            async def dispose(self):
                pass

        stats, exists, logs = self._fetch(Big(), max_mb=512)
        self.assertEqual(stats["failed"], 1)
        self.assertFalse(exists, "không được tạo file rác")
        self.assertTrue(any("512MB" in l for l in logs), f"phải log lý do: {logs}")

    def test_truncated_download_is_rejected(self):
        """content-length nói 1000 mà chỉ nhận 400 -> file hỏng, không được ghi."""
        class Truncated:
            status = 200
            headers = {"content-type": "image/jpeg", "content-length": "1000"}

            async def body(self):
                return b"x" * 400

            async def dispose(self):
                pass

        stats, exists, logs = self._fetch(Truncated())
        self.assertEqual(stats["failed"], 1, "tải thiếu phải tính là lỗi")
        self.assertFalse(exists, "không được lưu file cụt")
        self.assertTrue(any("thiếu dữ liệu" in l for l in logs))

    def test_normal_file_still_saved(self):
        """Guard không được chặn nhầm file bình thường."""
        class Good:
            status = 200
            headers = {"content-type": "image/jpeg", "content-length": "400"}

            async def body(self):
                return b"x" * 400

            async def dispose(self):
                pass

        stats, exists, _ = self._fetch(Good())
        self.assertEqual(stats["ok"], 1)
        self.assertTrue(exists)

    def test_missing_content_length_is_not_blocked(self):
        """Server dùng chunked encoding: không biết trước kích thước thì vẫn tải."""
        class NoLen:
            status = 200
            headers = {"content-type": "image/jpeg"}

            async def body(self):
                return b"y" * 1000

            async def dispose(self):
                pass

        stats, exists, _ = self._fetch(NoLen(), max_mb=1)
        self.assertEqual(stats["ok"], 1, "thiếu content-length không được coi là quá lớn")
        self.assertTrue(exists)

    def test_max_file_mb_zero_means_unlimited(self):
        class Huge:
            status = 200
            headers = {"content-type": "video/mp4",
                       "content-length": str(999 * 1024 * 1024)}

            async def body(self):
                return b"z" * 10

            async def dispose(self):
                pass

        stats, exists, _ = self._fetch(Huge(), max_mb=0)
        # body() trả 10 byte != 999MB -> bị chặn bởi guard toàn vẹn, không phải guard size
        self.assertEqual(stats["failed"], 1,
                         "0 = không giới hạn size, nhưng vẫn phải kiểm toàn vẹn")

    def test_playwright_has_no_streaming_api(self):
        """Ghi nhận lý do H4 không làm được trọn: API không tồn tại."""
        from playwright.async_api import APIResponse
        stream_names = [m for m in dir(APIResponse)
                        if "stream" in m.lower() or "chunk" in m.lower()]
        self.assertEqual(stream_names, [],
                         "nếu Playwright thêm streaming, hãy làm lại H4 cho đúng")


class TestNoBusyPoll(unittest.TestCase):
    """_racing_stop không được poll cờ dừng liên tục.

    Bug cũ: lặp asyncio.wait(timeout=0.05) tới DOWNLOAD_TIMEOUT_MS/50 lần. Với
    timeout 40s là 800 lần đánh thức event loop CHO MỖI FILE; DOWNLOAD_SEM=10
    thành 8.000 lần trong 40 giây, chỉ để kiểm một cờ.
    """

    class _NoStop:
        @staticmethod
        def is_set():
            return False

    class _StopSet:
        @staticmethod
        def is_set():
            return True

    def _downloader(self, stop):
        import asyncio
        from downloader import Downloader
        return Downloader(cache=None, log=lambda *a, **k: None, stop_event=stop,
                          semaphore=asyncio.Semaphore(4), db_lock=asyncio.Lock())

    def test_timeout_is_accurate(self):
        """Hết hạn đúng hạn, không sớm không muộn — chứng tỏ không còn poll 50ms."""
        import asyncio, time
        real = config.DOWNLOAD_TIMEOUT_MS
        config.DOWNLOAD_TIMEOUT_MS = 300
        try:
            async def run():
                d = self._downloader(self._NoStop())
                async def slow():
                    await asyncio.sleep(10)
                t0 = time.perf_counter()
                r = await d._racing_stop(slow())
                return r, (time.perf_counter() - t0) * 1000
            r, ms = asyncio.run(run())
        finally:
            config.DOWNLOAD_TIMEOUT_MS = real
        from downloader import _TIMEOUT
        self.assertIs(r, _TIMEOUT, "phải trả sentinel _TIMEOUT")
        self.assertGreaterEqual(ms, 250, f"không được timeout sớm: {ms:.0f}ms")
        self.assertLess(ms, 700, f"không được chậm hơn hạn nhiều: {ms:.0f}ms")

    def test_stop_event_wins_over_timeout(self):
        """Bấm Dừng phải thắng, trả None chứ không phải _TIMEOUT."""
        import asyncio
        from downloader import _TIMEOUT
        real = config.DOWNLOAD_TIMEOUT_MS
        config.DOWNLOAD_TIMEOUT_MS = 5000      # hạn dài, để cờ dừng thắng trước
        try:
            async def run():
                d = self._downloader(self._StopSet())
                async def slow():
                    await asyncio.sleep(10)
                return await d._racing_stop(slow())
            r = asyncio.run(run())
        finally:
            config.DOWNLOAD_TIMEOUT_MS = real
        self.assertIsNone(r, "cờ dừng phải trả None, không phải _TIMEOUT")
        self.assertIsNot(r, _TIMEOUT)

    def test_completed_request_wins(self):
        import asyncio
        d = self._downloader(self._NoStop())

        class R:
            status = 200
        async def fast():
            return R()
        r = asyncio.run(d._racing_stop(fast()))
        self.assertEqual(r.status, 200, "request xong trước thì phải trả response")


class TestPendingIsBounded(unittest.TestCase):
    """Số task tải đồng thời trong một thread phải có trần.

    Bug cũ (M6): crawl_thread gom TẤT CẢ task vào `pending` rồi gather ở cuối.
    Thread 20 trang × 20 post × 20 ảnh sinh hàng nghìn task cùng sống dù chỉ
    DOWNLOAD_SEM cái thực chạy. Đo được: 300 task -> 79 sau khi sửa.
    """

    class _NoStop:
        @staticmethod
        def is_set():
            return False

    def test_drain_keeps_running_below_keep(self):
        import asyncio
        from downloader import Downloader
        d = Downloader(cache=None, log=lambda *a, **k: None, stop_event=self._NoStop(),
                       semaphore=asyncio.Semaphore(4), db_lock=asyncio.Lock())

        async def run():
            peak = {"n": 0}
            pending = []

            async def one():
                await asyncio.sleep(0.01)

            for _ in range(120):
                pending.append(asyncio.create_task(one()))
                if len(pending) >= 20:
                    await d.drain(pending)
                    pending = [t for t in pending if not t.done()]
                peak["n"] = max(peak["n"], len(pending))
            await d.gather(pending)
            return peak["n"]

        peak = asyncio.run(run())
        self.assertLessEqual(peak, 20, f"pending vượt trần: đỉnh {peak}")

    def test_pending_limit_exists_and_positive(self):
        self.assertGreaterEqual(config.PENDING_LIMIT, 1)
        self.assertLessEqual(config.PENDING_LIMIT, 1000,
                             "trần quá cao thì không còn tác dụng chặn")

    def test_engine_thread_worker_count_is_bounded(self):
        """Số worker phải bằng THREAD_SEM, không phải số thread trong box.

        Logic worker đã được tách sang `_crawl_threads_of_author` để crawl_user
        gọn hơn. Test kiểm ĐÚNG hàm chứa logic đó.
        """
        import inspect
        import engine
        src = inspect.getsource(engine.CrawlerEngine._crawl_threads_of_author)
        self.assertIn("config.THREAD_SEM", src, "worker phải bám THREAD_SEM")
        self.assertIn("Queue", src, "phải dùng queue, không gather một task mỗi thread")


class TestTimeoutIsNotSilence(unittest.TestCase):
    """Hết thời gian chờ phải hiện trong thống kê, không được nuốt im lặng.

    Bug cũ: _racing_stop trả None cho cả "hết giờ" và "bấm Dừng". _fetch biến
    cả hai thành "CANCELLED", mà counted() chỉ đếm "FAILED". Kết quả: server
    chậm 40s -> file biến mất, failed=0, không một dòng log.
    """

    class _NoStop:
        @staticmethod
        def is_set():
            return False

    def _run_with(self, timeout_ms):
        import asyncio, tempfile, shutil
        from downloader import Downloader

        tmp = tempfile.mkdtemp(prefix="timeout")
        real = config.DOWNLOAD_TIMEOUT_MS
        config.DOWNLOAD_TIMEOUT_MS = timeout_ms
        try:
            class _Req:
                async def get(inner, url, headers=None, timeout=None):
                    await asyncio.sleep(5)      # chậm hơn hạn
                    raise AssertionError("không được tới đây")

            class _Ctx:
                request = _Req()

            class _Cache:
                @staticmethod
                def path_for(h):
                    return None

                @staticmethod
                def record(h, p):
                    pass

            async def run():
                d = Downloader(cache=_Cache(), log=lambda *a, **k: None,
                               stop_event=TestTimeoutIsNotSilence._NoStop(),
                               semaphore=asyncio.Semaphore(2), db_lock=asyncio.Lock())
                tasks = await d.dispatch(
                    _Ctx(), [("http://x/big.mp4", os.path.join(tmp, "b.mp4"), "H", "video")],
                    "http://ref", {})
                return await d.gather(tasks)

            return asyncio.run(run())
        finally:
            config.DOWNLOAD_TIMEOUT_MS = real
            shutil.rmtree(tmp, ignore_errors=True)

    def test_timeout_counts_as_failure(self):
        stats = self._run_with(300)
        self.assertEqual(stats["failed"], 1,
                         f"timeout phải đếm vào failed, không được im lặng: {stats}")
        self.assertEqual(stats["ok"], 0)

    def test_timeout_does_not_steal_ok_slot(self):
        """Timeout không được tính là thành công — nếu không, báo cáo lại sai."""
        stats = self._run_with(300)
        self.assertEqual(stats["video"], 0, "không tải được file nào thì không được đếm là video")


class TestVideoNameCollision(unittest.TestCase):
    """Video/file phải có hash trong tên, nếu không hai post cùng timestamp đè nhau.

    Bug cũ: nhánh video/file dùng f"[{ts}]_{tag}_{i:03d}{ext}" với `i` reset về 1
    ở mỗi post. Hai post khác nhau trong cùng thread -> cùng tên -> ghi đè, mất
    media. Tệ hơn khi post thiếu <time.u-dt>: mọi post dùng "00000000_000000".
    """

    def _paths(self, urls, ts, tag):
        return [p for _, p, _, _ in plan_jobs(urls, r"C:\f", ts, tag)]

    def test_different_videos_same_timestamp_do_not_collide(self):
        a = self._paths(["http://x/vid/A.mp4"], "20240101_120000", "comment_video")[0]
        b = self._paths(["http://x/vid/B.mp4"], "20240101_120000", "comment_video")[0]
        self.assertNotEqual(a, b, f"hai video khác nhau không được trùng path: {a}")

    def test_missing_timestamp_does_not_cause_mass_collision(self):
        """Mọi post thiếu <time.u-dt> đều dùng "00000000_000000" -> phải vẫn khác path."""
        a = self._paths(["http://x/vid/A.mp4"], "00000000_000000", "main_video")[0]
        b = self._paths(["http://x/vid/B.mp4"], "00000000_000000", "main_video")[0]
        self.assertNotEqual(a, b, "post thiếu timestamp không được đè lên nhau")

    def test_files_typed_as_files_and_unique(self):
        paths = self._paths(["http://x/a/doc.zip", "http://x/b/doc.zip"],
                            "20240101_120000", "comment_file")
        self.assertEqual(len(set(paths)), len(paths), f"file trùng tên: {paths}")
        for p in paths:
            self.assertTrue(p.endswith(".zip"), f"phải giữ đuôi .zip: {p}")

    def test_same_video_twice_is_idempotent(self):
        """Cùng một URL phải ra cùng path — nếu khác sẽ tải trùng thay vì clone."""
        a = self._paths(["http://x/v.mp4"], "t", "comment_video")[0]
        b = self._paths(["http://x/v.mp4"], "t", "comment_video")[0]
        self.assertEqual(a, b, "cùng URL phải cùng path để clone_cached dùng được")


