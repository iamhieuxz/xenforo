"""Khung kiểm chứng lỗi P0 (C1-C4) chạy trên CODE THẬT, không phải bản sao logic.

Chạy: python audit_repro.py
Mã thoát: 0 nếu TẤT CẢ đã được sửa, 1 nếu còn lỗi.

Mỗi case in một trong hai nhãn:
  BUG PRESENT  -> lỗi còn tái hiện được (trạng thái trước khi sửa)
  OK           -> đã sửa, hành vi đúng

Script này độc lập với test_v72.py để suite chính vẫn xanh trong lúc sửa.
Sau khi xong P0, các case ở đây được chuyển thành test thật (bước 10).
"""

import asyncio
import os
import shutil
import sys
import tempfile
import threading

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config

# Không đụng ổ thật: mọi thao tác file nằm trong temp.
_SANDBOX = tempfile.mkdtemp(prefix="v72_audit_")
config.DOWNLOAD_DIR = os.path.join(_SANDBOX, "download")

import engine
import downloader
import xenforo_parse as X
from downloader import Downloader, plan_jobs

BUG, OK = "BUG PRESENT", "OK"
results = []


def record(name, buggy, detail, repro):
    """buggy=True nghĩa là lỗi còn tồn tại."""
    label = BUG if buggy else OK
    results.append((name, label, detail))
    print(f"\n[{name}] {label}")
    print(f"   {detail}")
    print(f"   repro: {repro}")


class _DummyCache:
    def path_for(self, h):
        return None

    def record(self, h, p):
        pass


class _FakePlaywrightCM:
    """Thay async_playwright() để không khởi động trình duyệt thật."""

    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


# ---------------------------------------------------------------- C1
async def _probe_c1():
    eng = engine.CrawlerEngine(
        cache=_DummyCache(), log=lambda *a, **k: None, stop_event=threading.Event())

    async def fake_connect(p):
        return object()          # context giả, user_worker không dùng tới

    async def failing_crawl_user(*a, **k):
        raise RuntimeError("mô phỏng user hỏng")

    banners = []
    eng.connect = fake_connect
    eng.crawl_user = failing_crawl_user
    eng._banner = lambda ok, title: banners.append(ok)

    await eng.crawl_users(["user_a", "user_b"], "https://r/box/x.140/")
    return banners


def check_c1():
    real = engine.async_playwright
    engine.async_playwright = lambda: _FakePlaywrightCM()
    try:
        banners = asyncio.run(_probe_c1())
    finally:
        engine.async_playwright = real

    # 2 user đều lỗi -> banner phải nhận ok=False
    buggy = banners != [False]
    record(
        "C1", buggy,
        f"2/2 user raise lỗi, _banner nhận ok={banners} "
        f"(đúng phải là [False])",
        "engine.crawl_users -> _banner(ok)")


# ---------------------------------------------------------------- C2
class _FiveHundred:
    status = 500
    headers = {}

    async def dispose(self):
        pass


class _FailRequest:
    async def get(self, url, headers=None, timeout=None):
        return _FiveHundred()


class _Ctx:
    request = _FailRequest()


class _NoStop:
    @staticmethod
    def is_set():
        return False


async def _probe_c2():
    d = Downloader(cache=_DummyCache(), log=lambda *a, **k: None, stop_event=_NoStop(),
                   semaphore=asyncio.Semaphore(2), db_lock=asyncio.Lock())
    folder = os.path.join(config.DOWNLOAD_DIR, "c2")
    seen = {}
    url = "http://x/repeated.jpg"

    # lần 1: tải hỏng
    t1 = await d.dispatch(_Ctx(), [(url, os.path.join(folder, "a.jpg"), "H", "image")],
                          "http://ref", seen)
    await d.gather(t1)

    # lần 2: cùng URL xuất hiện ở post khác -> phải được tải lại
    t2 = await d.dispatch(_Ctx(), [(url, os.path.join(folder, "b.jpg"), "H", "image")],
                          "http://ref", seen)
    return len(t1), len(t2)


def check_c2():
    n1, n2 = asyncio.run(_probe_c2())
    buggy = (n2 == 0)
    record(
        "C2", buggy,
        f"lần 1 fail tạo {n1} task, lần 2 (cùng URL) tạo {n2} task "
        f"(đúng phải là 1: phải thử tải lại)",
        "Downloader.dispatch -> seen_hashes")


# ---------------------------------------------------------------- C3
class _SlowRequest:
    async def get(self, url, headers=None, timeout=None):
        await asyncio.sleep(5)      # chậm hơn DOWNLOAD_TIMEOUT_MS
        raise AssertionError("không được tới đây")


class _SlowCtx:
    request = _SlowRequest()


async def _probe_c3():
    d = Downloader(cache=_DummyCache(), log=lambda *a, **k: None, stop_event=_NoStop(),
                   semaphore=asyncio.Semaphore(2), db_lock=asyncio.Lock())
    folder = os.path.join(config.DOWNLOAD_DIR, "c3")
    tasks = await d.dispatch(_SlowCtx(), [("http://x/slow.mp4", os.path.join(folder, "s.mp4"),
                                           "H3", "video")], "http://ref", {})
    return await d.gather(tasks)


def check_c3():
    real_timeout = config.DOWNLOAD_TIMEOUT_MS
    config.DOWNLOAD_TIMEOUT_MS = 300          # 40s -> 0.3s cho nhanh
    try:
        stats = asyncio.run(_probe_c3())
    finally:
        config.DOWNLOAD_TIMEOUT_MS = real_timeout

    buggy = (stats["failed"] == 0)
    record(
        "C3", buggy,
        f"server chậm hơn timeout -> stats={stats} "
        f"(failed phải >= 1, hiện không đếm và không log)",
        "Downloader._fetch -> 'CANCELLED' thay vì 'TIMEOUT'")


# ---------------------------------------------------------------- C4
def check_c4():
    folder = os.path.join(config.DOWNLOAD_DIR, "c4")
    ts = "20240101_120000"
    a = plan_jobs(["http://x/vid/A.mp4"], folder, ts, "comment_video")[0][1]
    b = plan_jobs(["http://x/vid/B.mp4"], folder, ts, "comment_video")[0][1]

    # thêm case timestamp rỗng (post thiếu <time.u-dt>)
    c = plan_jobs(["http://x/vid/C.mp4"], folder, "00000000_000000", "comment_video")[0][1]
    d = plan_jobs(["http://x/vid/D.mp4"], folder, "00000000_000000", "comment_video")[0][1]

    buggy = (a == b) or (c == d)
    record(
        "C4", buggy,
        f"video khác nhau cùng timestamp -> trùng path? {a == b}; "
        f"timestamp rỗng -> trùng path? {c == d}",
        "downloader.plan_jobs -> tên file không có hash")


# ---------------------------------------------------------------- main
def main():
    print("=" * 68)
    print("KIỂM CHỨNG LỖI P0 — chạy trên code thật")
    print("=" * 68)

    check_c1()
    check_c2()
    check_c3()
    check_c4()

    print("\n" + "=" * 68)
    bad = [n for n, label, _ in results if label == BUG]
    for name, label, _ in results:
        print(f"  {name}: {label}")
    print("=" * 68)
    if bad:
        print(f"{len(bad)}/{len(results)} lỗi còn tồn tại: {', '.join(bad)}")
    else:
        print(f"Tất cả {len(results)} lỗi P0 đã được sửa.")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
    sys.exit(code)
