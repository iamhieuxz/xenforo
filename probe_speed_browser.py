"""So sánh trực tiếp: HTTP thuần vs trình duyệt, khi tải song song.

Chạy: python probe_speed_browser.py

Tự mở Chrome ở cổng riêng (không đụng cổng 9222 của bạn), dọn sạch sau khi xong.
"""
import asyncio
import concurrent.futures
import gzip
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import browser_launcher as B
import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")

BASE = "https://rphang.show/box/clip-sex-phim-sex.86/"
N = 8   # số trang mỗi lần đo


def http_get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    })
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        enc = r.headers.get("Content-Encoding")
    if enc == "gzip":
        raw = gzip.decompress(raw)
    return time.perf_counter() - t0, len(raw)


def bench_http(urls, workers):
    t0 = time.perf_counter()
    ok = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(http_get, u): u for u in urls}
        for f in concurrent.futures.as_completed(futs):
            try:
                f.result()
                ok += 1
            except Exception:
                pass
    return time.perf_counter() - t0, ok


async def bench_browser(ctx, urls, concurrency):
    sem = asyncio.Semaphore(concurrency)
    ok = [0]

    async def one(u):
        async with sem:
            page = await ctx.new_page()
            try:
                await page.goto(u, wait_until="domcontentloaded", timeout=40000)
                await page.content()
                ok[0] += 1
            except Exception:
                pass
            finally:
                await page.close()

    t0 = time.perf_counter()
    await asyncio.gather(*[one(u) for u in urls])
    return time.perf_counter() - t0, ok[0]


async def main():
    urls = [f"{BASE}page-{i}" for i in range(1, N + 1)]

    print("=" * 78)
    print(f"SO SÁNH: {N} trang box, HTTP thuần vs trình duyệt")
    print("=" * 78)

    # ---- HTTP ----
    print("\nHTTP thuần:")
    for w in (1, 4, 8, 16):
        dt, ok = bench_http(urls, w)
        print(f"  {w:2} luồng: {dt:5.2f}s  ({ok}/{N} ok)  {ok/dt:5.1f} trang/s")

    # ---- Trình duyệt ----
    exe = B.find_browser_for("chrome")
    if not exe:
        print("\nKhông có Chrome, dừng.")
        return

    tmp = tempfile.mkdtemp(prefix="speed_", dir=os.getcwd())
    prof = os.path.join(tmp, "p")
    os.makedirs(prof, exist_ok=True)
    port = 9550
    old_port = config.CDP_PORT
    config.CDP_PORT = port
    config.CDP_URL = f"http://127.0.0.1:{port}"

    args = [exe, f"--remote-debugging-port={port}",
            f"--user-data-dir={prof}", "--no-first-run",
            "--no-default-browser-check", "--no-sandbox",
            "--disable-crash-reporter", "--headless=new"]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def cleanup():
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=15)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
        config.CDP_PORT = old_port
        config.CDP_URL = f"http://127.0.0.1:{old_port}"

    opened = False
    for _ in range(30):
        await asyncio.sleep(0.5)
        if B.probe_port()["state"] == "ready":
            opened = True
            break
        if proc.poll() is not None:
            break

    if not opened:
        print("\nKhông mở được Chrome để đo.")
        cleanup()
        return

    print("\nTrình duyệt (Playwright, DOM đã render):")
    from playwright.async_api import async_playwright
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(config.CDP_URL)
            ctx = browser.contexts[0]
            for c in (1, 4, 8):
                dt, ok = await bench_browser(ctx, urls, c)
                print(f"  {c:2} song song: {dt:5.2f}s  ({ok}/{N} ok)  {ok/dt:5.1f} trang/s")
    finally:
        cleanup()

    print()
    print("=" * 78)
    print("KẾT LUẬN")
    print("=" * 78)
    print("  HTTP thuần: nhanh, nhẹ, không cần trình duyệt.")
    print("  Lưu ý: chạy quá nhiều luồng cùng lúc có thể bị chặn — 8-16 là hợp lý.")


if __name__ == "__main__":
    asyncio.run(main())