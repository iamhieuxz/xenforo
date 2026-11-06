"""Tái hiện 7 lỗi: chạy đúng luồng quét và ghi lại MỌI dòng có dấu hiệu lỗi.

Chạy: python probe_repro_seven.py

Không sửa code. Chỉ quan sát và báo cáo, để biết 7 lỗi đó là gì.
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
from cache import MediaCache

# Box có hoạt động gần nhất theo dữ liệu cache
BOX = "https://rphang.show/box/nhat-ky-may-mua.140/"

errors = []
warnings = []
all_log = []


def log(msg, tag=None):
    """Ghi lại mọi dòng log, phân loại."""
    all_log.append(msg)
    low = msg.lower()
    is_err = ("[-]" in msg or "lỗi" in low or "loi" in low or "error" in low
              or "that bai" in low or "thất bại" in low or "timeout" in low
              or "fail" in low)
    is_warn = ("[!]" in msg or "bị chặn" in low or "bo qua" in low
               or "bỏ qua" in low or "thiếu" in low or "thieu" in low)
    if is_err:
        errors.append(msg)
    elif is_warn:
        warnings.append(msg)


async def main():
    print("=" * 78)
    print("TÁI HIỆN LỖI — chạy đúng luồng quét, ghi mọi lỗi")
    print("=" * 78)

    tmp = tempfile.mkdtemp(prefix="repro7_", dir=os.getcwd())
    cache_path = os.path.join(tmp, "c.db")
    cache = MediaCache(cache_path)

    # Dùng cache thật để kiểm tra "dừng sớm" như phiên thật
    real_cache = None
    try:
        real_cache = MediaCache(r"E:\HIDE\RPHANG\crawler_cache.db")
        print("  dùng cache thật E:\\HIDE\\RPHANG để kiểm 'dừng sớm'")
    except Exception as e:
        print(f"  không mở được cache thật: {type(e).__name__}")

    import engine

    class NoStop:
        @staticmethod
        def is_set():
            return False

    c = real_cache or cache
    eng = engine.CrawlerEngine(
        cache=c, log=log, stop_event=NoStop(), download_dir=tmp)

    vec = X
    print("\n1. Tải trang box thật")
    r = fast_fetch.fetch_one(BOX)
    if not r.ok:
        log(f"[-] Không tải được box: {r.error}")
        print(f"   LỖI: {r.error}")
        return
    soup = X.make_soup(r.text)
    links, nxt = X.parse_thread_links(soup, BOX)
    print(f"   {len(links)} thread, trang kế: {bool(nxt)}")

    print("\n2. Kiểm tra 'dừng sớm' — thread nào đã có trong cache")
    known = sum(1 for u in links if eng._thread_already_done(u))
    print(f"   {known}/{len(links)} thread đã có trong cache")

    print("\n3. Tải 6 thread CHƯA có, bóc media, thử tải 1 media mỗi thread")
    fresh = [u for u in links if not eng._thread_already_done(u)
             and "noi-quy" not in u][:6]
    print(f"   {len(fresh)} thread mới để thử")

    tres = fast_fetch.fetch_many(fresh, workers=6) if fresh else []
    media_all = []
    for rr in tres:
        if not rr.ok:
            log(f"[-] Không tải được thread {rr.url[:60]}: {rr.error}")
            print(f"   LỖI thread: {rr.error}")
            continue
        ts = X.make_soup(rr.text)
        posts = ts.select("article.message--post[data-author]")
        err_before = len(errors)
        for p in posts:
            i, v, f = X.extract_post_media(p, rr.url)
            media_all.extend(i + v + f)
        print(f"   {rr.url[-40:]}: {len(posts)} post")

    print(f"\n   tổng {len(media_all)} media URL")

    print("\n4. Thử tải 8 media (kiểm tra lỗi tải thật)")
    ok_n = fail_n = 0
    fails = []
    for u in media_all[:8]:
        res = fast_fetch.download_to_file(
            u, os.path.join(tmp, "m", os.path.basename(u.split("?")[0])[:60] or "x.bin"),
            referer=BOX)
        if res.ok:
            ok_n += 1
        else:
            fail_n += 1
            fails.append((u, res.status, res.error))
            log(f"[-] Tải media lỗi {res.status} {res.error}: {u[-50:]}")
    print(f"   ok={ok_n} fail={fail_n}")
    for u, st, er in fails:
        print(f"     {st} {er}: {u[-60:]}")

    print("\n5. Kiểm tra media URL có phải rác không")
    JUNK = ("joypixels", "reaction", "/data/avatars/", "/styles/", "/image/",
            "logo", "smilies", "emoji")
    junk = [u for u in media_all if any(j in u.lower() for j in JUNK)]
    print(f"   {len(junk)} URL rác / {len(media_all)}")
    for u in junk[:5]:
        print(f"     {u[:90]}")

    print()
    print("=" * 78)
    print("TỔNG HỢP")
    print("=" * 78)
    print(f"  tổng dòng log : {len(all_log)}")
    print(f"  lỗi           : {len(errors)}")
    print(f"  cảnh báo      : {len(warnings)}")
    print()
    if errors:
        print("  CÁC LỖI:")
        for i, e in enumerate(errors[:15], 1):
            print(f"    {i}. {e}")
    if warnings:
        print("\n  CẢNH BÁO:")
        for i, w in enumerate(warnings[:10], 1):
            print(f"    {i}. {w}")

    if real_cache:
        real_cache.close()
    cache.close()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())