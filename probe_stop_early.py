"""Kiểm chứng: dừng sớm khi gặp bài đã có — cơ chế có hoạt động không?

Chạy: python probe_stop_early.py

Hai box bạn theo dõi có 989 + 347 = 1.336 trang. Quét lại toàn bộ mỗi lần là
không cần thiết vì bài mới luôn nằm ở trang đầu.

Kiểm ở mức ĐƠN VỊ (không chạy cả crawl_user) để probe nhanh và không cần
trình duyệt: đây là thứ quyết định dừng sớm, và nó thuần logic.
"""
import os
import re
import shutil
import sys
import tempfile
import threading

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
import engine
import fast_fetch
import xenforo_parse as X
from cache import MediaCache

BOX = "https://rphang.show/box/clip-sex-phim-sex.86/"
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"   [{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"          {detail}")


def main():
    tmp = tempfile.mkdtemp(prefix="stops_", dir=os.getcwd())
    cache = MediaCache(os.path.join(tmp, "c.db"))
    eng = engine.CrawlerEngine(
        cache=cache, log=lambda *a, **k: None,
        stop_event=threading.Event(), download_dir=tmp)

    res = fast_fetch.fetch_one(BOX)
    if not res.ok:
        print("Không tải được box, dừng.")
        cache.close()
        shutil.rmtree(tmp, ignore_errors=True)
        return

    soup = X.make_soup(res.text)
    links, _ = X.parse_thread_links(soup, BOX)
    links = [u for u in links if "noi-quy" not in u]
    print(f"  trang 1: {len(links)} thread thật")

    print()
    print("=" * 78)
    print("1. Cache TRỐNG — không được coi là đã xong")
    print("=" * 78)
    found = [u for u in links if eng._thread_already_done(u)]
    check("cache trống -> không thread nào bị coi là xong", not found,
          f"{len(found)} bị coi là xong (phải là 0)")

    print()
    print("=" * 78)
    print("2. Đánh dấu 3 thread — chỉ 3 cái đó bị coi là xong")
    print("=" * 78)
    marked = links[:3]
    for u in marked:
        cache.remember_thread_date(X.thread_key(u), "2024-01-01",
                                   os.path.join(tmp, "f"))
    done = [u for u in links if eng._thread_already_done(u)]
    check("đúng số thread đã đánh dấu", len(done) == len(marked),
          f"{len(done)} xong / {len(marked)} đánh dấu")

    print()
    print("=" * 78)
    print("3. Đánh dấu CẢ trang -> điều kiện dừng thoả")
    print("=" * 78)
    for u in links:
        cache.remember_thread_date(X.thread_key(u), "2024-01-01",
                                   os.path.join(tmp, "f"))
    page_total = len(links)
    page_known = sum(1 for u in links if eng._thread_already_done(u))
    check("cả trang đã biết", page_known == page_total,
          f"{page_known}/{page_total}")

    would_stop = (getattr(config, "STOP_ON_KNOWN_THREAD", True)
                  and page_total > 0 and page_known == page_total)
    check("crawl_user sẽ dừng sau trang này", would_stop)

    print()
    print("=" * 78)
    print("4. Slug đổi nhưng id giữ -> vẫn nhận ra bài cũ")
    print("=" * 78)
    old_url = links[0]
    new_url = re.sub(r"/t/[^/]*\.", "/t/tieu-de-hoan-toan-moi.", old_url)
    new_url = re.sub(r"/threads/[^/]*\.", "/threads/tieu-de-moi.", new_url)
    check("slug đổi vẫn coi là đã xong",
          eng._thread_already_done(new_url),
          f"{old_url[-38:]} -> {new_url[-38:]}")

    print()
    print("=" * 78)
    print("5. Tắt STOP_ON_KNOWN_THREAD -> không dừng nữa")
    print("=" * 78)
    old = config.STOP_ON_KNOWN_THREAD
    try:
        config.STOP_ON_KNOWN_THREAD = False
        check("tắt cờ thì luôn quét hết",
              not eng._thread_already_done(links[0]))
    finally:
        config.STOP_ON_KNOWN_THREAD = old

    print()
    print("=" * 78)
    print(f"KET QUA: {sum(results)}/{len(results)} PASS")
    print("=" * 78)

    cache.close()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
    sys.exit(0 if all(results) else 1)