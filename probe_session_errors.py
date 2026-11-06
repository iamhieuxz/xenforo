"""Kiểm tra các lỗi có thể xảy ra trong một phiên quét thật.

Chạy: python probe_session_errors.py

Chạy một phiên quét THẬT (không giả lập) trên box nhỏ, ghi lại mọi lỗi và
cảnh báo, rồi phân loại xem lỗi nào là thật, lỗi nào là nhiễu.
"""
import asyncio
import os
import re
import shutil
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
import fast_fetch
import xenforo_parse as X

BOX = "https://rphang.show/box/nhat-ky-may-mua.140/"


def classify(msg):
    """Phân loại một dòng log lỗi/cảnh báo."""
    low = msg.lower()
    if "timeout" in low or "timed out" in low:
        return "TIMEOUT"
    if "403" in low or "401" in low:
        return "AUTH"
    if "404" in low:
        return "NOT_FOUND"
    if "429" in low or "rate" in low:
        return "RATE_LIMIT"
    if "connection" in low or "reset" in low:
        return "CONNECTION"
    if "no such" in low or "khong tim" in low:
        return "MISSING"
    if "lỗi" in low or "loi" in low or "error" in low:
        return "OTHER_ERROR"
    if "!" in msg and "[" in msg:
        return "WARNING"
    return "INFO"


async def main():
    print("=" * 78)
    print("KIỂM TRA LỖI TRONG MỘT PHIÊN QUÉT THẬT")
    print("=" * 78)

    errors = []
    warnings = []
    all_logs = []

    def log(msg, tag=None):
        all_logs.append((tag or "", msg))
        c = classify(msg)
        if c in ("TIMEOUT", "AUTH", "NOT_FOUND", "RATE_LIMIT",
                 "CONNECTION", "OTHER_ERROR"):
            errors.append((c, msg))
        elif c == "WARNING":
            warnings.append(msg)

    # ---- 1. Tải nhiều trang box, ghi lại mọi lỗi ----
    print("\n1. Tải 8 trang box")
    t0 = time.perf_counter()
    urls = [f"{BOX}page-{i}" for i in range(1, 9)]
    results = fast_fetch.fetch_many(urls, workers=8)
    dt = time.perf_counter() - t0

    ok = sum(1 for r in results if r.ok)
    print(f"   {ok}/8 ok trong {dt:.2f}s ({ok/dt:.1f} trang/s)")
    for r in results:
        if not r.ok:
            log(f"[-] Không tải được {r.url}: {r.error}")
            print(f"   LỖI: {r.url} -> {r.error}")

    # ---- 2. Bóc thread từ các trang ----
    print("\n2. Bóc thread + kiểm tra URL media")
    thread_urls = []
    for r in results:
        if not r.ok or not r.text:
            continue
        soup = X.make_soup(r.text)
        links, _ = X.parse_thread_links(soup, r.url)
        thread_urls.extend(links)
    thread_urls = list(dict.fromkeys(thread_urls))
    print(f"   {len(thread_urls)} thread")

    # ---- 3. Tải 5 thread thật, bóc media ----
    print("\n3. Tải 5 thread, kiểm tra media URL")
    sample = [u for u in thread_urls if "noi-quy" not in u][:5]
    tres = fast_fetch.fetch_many(sample, workers=5)

    total_media = 0
    media_urls = []
    for r in tres:
        if not r.ok:
            log(f"[-] Không tải được thread {r.url[:60]}: {r.error}")
            continue
        ts = X.make_soup(r.text)
        posts = ts.select("article.message--post[data-author]")
        for p in posts:
            imgs, vids, files = X.extract_post_media(p, r.url)
            total_media += len(imgs) + len(vids) + len(files)
            media_urls.extend(imgs + vids + files)

    print(f"   {total_media} media URL thu được")

    # ---- 4. Kiểm tra 3 media URL có tải được không ----
    print("\n4. Thử tải 3 media thật")
    for u in media_urls[:3]:
        r = fast_fetch.fetch_one(u, as_text=False, retries=0)
        if r.ok:
            print(f"   OK   {r.status} {len(r.content or b'')}B  {u[-50:]}")
        else:
            print(f"   LỖI  {r.status} {r.error}  {u[-50:]}")
            log(f"[-] Media lỗi {u[-60:]}: {r.error}")

    # ---- 5. Tổng hợp ----
    print()
    print("=" * 78)
    print("TỔNG HỢP LỖI")
    print("=" * 78)
    if not errors:
        print("  Không có lỗi nào.")
    else:
        from collections import Counter
        c = Counter(k for k, _ in errors)
        for kind, n in c.most_common():
            print(f"  {kind:14} x{n}")
            for k, m in errors:
                if k == kind:
                    print(f"     {m[:100]}")

    print()
    if warnings:
        print(f"  Cảnh báo ({len(warnings)}):")
        for w in warnings[:5]:
            print(f"    {w[:100]}")

    print()
    print("=" * 78)
    print(f"  tổng log: {len(all_logs)}  |  lỗi: {len(errors)}  |  cảnh báo: {len(warnings)}")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())