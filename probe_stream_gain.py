"""Đo hiệu quả streaming: tải thật một thread, đo thời gian và RAM.

Chạy: python probe_stream_gain.py

So sánh hai cách trên CÙNG bộ file:
  1. `body()` — nạp cả file vào RAM (đường cũ)
  2. streaming 64 KB (đường mới)
"""
import os
import shutil
import statistics
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fast_fetch
import xenforo_parse as X

BOX = "https://rphang.show/box/nhat-ky-may-mua.140/"

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def rss_mb():
    if not HAS_PSUTIL:
        return 0.0
    import psutil as p
    return p.Process().memory_info().rss / 1024 / 1024


def main():
    print("=" * 78)
    print("ĐO HIỆU QUẢ STREAMING")
    print("=" * 78)

    # Lấy media thật
    r = fast_fetch.fetch_one(BOX)
    soup = X.make_soup(r.text)
    links, _ = X.parse_thread_links(soup, BOX)
    sample = [u for u in links if "noi-quy" not in u][:3]

    media = []
    for u in sample:
        rr = fast_fetch.fetch_one(u)
        if not rr.ok:
            continue
        ts = X.make_soup(rr.text)
        for p in ts.select("article.message--post[data-author]"):
            i, v, f = X.extract_post_media(p, u)
            media.extend(i + v)
        if len(media) >= 12:
            break

    media = media[:12]
    print(f"  {len(media)} media để thử")
    if not media:
        print("  Không lấy được media, dừng.")
        return

    tmp = tempfile.mkdtemp(prefix="stream_", dir=os.getcwd())

    # ---- Cách 1: nạp cả file ----
    print("\n1. CÁCH CŨ: body() nạp cả file")
    base_rss = rss_mb()
    peak_old = base_rss
    times_old = []
    sizes = []
    d1 = os.path.join(tmp, "old")
    for idx, u in enumerate(media):
        t0 = time.perf_counter()
        try:
            res = fast_fetch.fetch_one(u, as_text=False, retries=0)
            if res.ok and res.content:
                os.makedirs(d1, exist_ok=True)
                with open(os.path.join(d1, f"f{idx}.bin"), "wb") as f:
                    f.write(res.content)
                sizes.append(len(res.content))
        except Exception:
            pass
        times_old.append(time.perf_counter() - t0)
        if HAS_PSUTIL:
            peak_old = max(peak_old, rss_mb())

    print(f"   {len(times_old)} file, tổng {sum(sizes)/1024/1024:.1f} MB")
    print(f"   thời gian: {sum(times_old):.2f}s  (TB {statistics.mean(times_old)*1000:.0f} ms/file)")
    if HAS_PSUTIL:
        print(f"   RAM đỉnh: {peak_old:.0f} MB (tăng {peak_old-base_rss:.0f} MB)")

    # ---- Cách 2: streaming ----
    print("\n2. CÁCH MỚI: stream 64 KB")
    base_rss2 = rss_mb()
    peak_new = base_rss2
    times_new = []
    d2 = os.path.join(tmp, "new")
    for idx, u in enumerate(media):
        t0 = time.perf_counter()
        res = fast_fetch.download_to_file(u, os.path.join(d2, f"f{idx}.bin"),
                                          referer=BOX)
        times_new.append(time.perf_counter() - t0)
        if HAS_PSUTIL:
            peak_new = max(peak_new, rss_mb())

    print(f"   {len(times_new)} file")
    print(f"   thời gian: {sum(times_new):.2f}s  (TB {statistics.mean(times_new)*1000:.0f} ms/file)")
    if HAS_PSUTIL:
        print(f"   RAM đỉnh: {peak_new:.0f} MB (tăng {peak_new-base_rss2:.0f} MB)")

    # ---- Kết luận ----
    print()
    print("=" * 78)
    print("KẾT LUẬN")
    print("=" * 78)
    if times_old and times_new:
        gate = sum(times_old) / max(sum(times_new), 0.001)
        print(f"  tốc độ: {gate:.2f}× (stream so với body())")
    if HAS_PSUTIL:
        print(f"  RAM tăng: body() {peak_old-base_rss:.0f} MB  |  stream {peak_new-base_rss2:.0f} MB")
        if peak_old > peak_new:
            print(f"  => streaming tiết kiệm {peak_old-peak_new:.0f} MB RAM")

    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()