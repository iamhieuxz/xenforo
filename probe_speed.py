"""Đo tốc độ thật: tải trang box và thread.

Chạy: python probe_speed.py

Mục tiêu: biết nút thắt nằm ở đâu trước khi tối ưu. Ba thứ cần đo:
  1. Tải HTML box (1 trang) bằng HTTP thuần
  2. Tải cùng trang đó bằng trình duyệt (CDP)
  3. Chạy lại nhiều lần để biết độ ổn định
"""
import asyncio
import statistics
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")

BOX = "https://rphang.show/box/clip-sex-phim-sex.86/"
THREAD = ("https://rphang.show/t/full-kho-video-cua-thang-chicma666-aka-"
          "baddirty-chich-may-em-non-cap-3-16-tuoi.248242/")


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    })
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    dt = time.perf_counter() - t0
    # gzip
    if r.headers.get("Content-Encoding") == "gzip":
        import gzip
        raw = gzip.decompress(raw)
    return dt, len(raw)


async def browser_get(ctx, url):
    page = await ctx.new_page()
    try:
        t0 = time.perf_counter()
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        html = await page.content()
        dt = time.perf_counter() - t0
        return dt, len(html)
    finally:
        await page.close()


def stats(label, times):
    if not times:
        print(f"  {label:34} (không có dữ liệu)")
        return
    avg = statistics.mean(times)
    print(f"  {label:34} trung bình {avg:6.2f}s  "
          f"min {min(times):5.2f}  max {max(times):5.2f}  (n={len(times)})")


def main():
    print("=" * 78)
    print("ĐO TỐC ĐỘ — HTTP thuần")
    print("=" * 78)

    box_times, thread_times = [], []
    print("  Tải box 3 lần:")
    for i in range(3):
        try:
            dt, n = http_get(BOX)
            box_times.append(dt)
            print(f"    lần {i+1}: {dt:6.2f}s  {n:7} bytes")
        except Exception as e:
            print(f"    lần {i+1}: LỖI {type(e).__name__}")

    print("  Tải thread 3 lần:")
    for i in range(3):
        try:
            dt, n = http_get(THREAD)
            thread_times.append(dt)
            print(f"    lần {i+1}: {dt:6.2f}s  {n:7} bytes")
        except Exception as e:
            print(f"    lần {i+1}: LỖI {type(e).__name__}")

    print()
    stats("HTTP box", box_times)
    stats("HTTP thread", thread_times)

    # Đo song song: 10 trang box cùng lúc
    print()
    print("=" * 78)
    print("ĐO SONG SONG — 10 trang box cùng lúc (HTTP thuần, 10 thread)")
    print("=" * 78)
    import concurrent.futures
    urls = [f"https://rphang.show/box/clip-sex-phim-sex.86/page-{i}"
            for i in range(1, 11)]
    t0 = time.perf_counter()
    ok, fail = 0, 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(http_get, u): u for u in urls}
        for f in concurrent.futures.as_completed(futs):
            try:
                f.result()
                ok += 1
            except Exception:
                fail += 1
    dt = time.perf_counter() - t0
    print(f"  10 trang song song: {dt:5.2f}s  (ok={ok} fail={fail})")
    print(f"  => {ok/dt:.2f} trang/giây")
    if box_times:
        seq = statistics.mean(box_times) * 10
        print(f"  Tuần tự 10 trang sẽ mất khoảng {seq:.1f}s")
        print(f"  Nhanh hơn: {seq/dt:.1f}×")

    print()
    print("=" * 78)
    print("ĐO QUA TRÌNH DUYỆT (CDP) — chậm hơn HTTP vì phải render")
    print("=" * 78)
    try:
        asyncio.run(_browser_bench())
    except Exception as e:
        print(f"  Bỏ qua: {type(e).__name__}: {e}")


async def _browser_bench():
    import os
    import tempfile
    import browser_launcher as B
    import config

    if B.probe_port()["state"] != "ready":
        print("  Cổng CDP chưa mở — bỏ qua phần này.")
        print("  (Chạy open_debug_chrome.py trước nếu muốn đo.)")
        return

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(config.CDP_URL)
        ctx = browser.contexts[0]
        times = []
        for i in range(3):
            try:
                dt, n = await browser_get(ctx, BOX)
                times.append(dt)
                print(f"    lần {i+1}: {dt:6.2f}s  {n:7} bytes")
            except Exception as e:
                print(f"    lần {i+1}: LỖI {type(e).__name__}")
        stats("CDP box", times)


if __name__ == "__main__":
    main()