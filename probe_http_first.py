"""Kiểm chứng: HTTP-first có bóc đúng và nhanh hơn trình duyệt không.

Chạy: python probe_http_first.py

Không cần mở trình duyệt cho phần chính — đó chính là điểm của tối ưu này.
"""
import asyncio
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
import fast_fetch
import xenforo_parse as X

BOX_A = "https://rphang.show/box/clip-sex-phim-sex.86/"
BOX_B = "https://rphang.show/box/nhat-ky-may-mua.140/"

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"   [{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"          {detail}")


print("=" * 78)
print("1. fast_fetch tải một trang")
print("=" * 78)
t0 = time.perf_counter()
res = fast_fetch.fetch_one(BOX_A)
dt = time.perf_counter() - t0
check("tải được box", res.ok, f"{res}")

if res.ok:
    soup = X.make_soup(res.text)
    links, nxt = X.parse_thread_links(soup, BOX_A)
    check("bóc được link thread", len(links) > 10, f"{len(links)} link")
    check("tìm được trang kế", bool(nxt), nxt or "(không có)")
    check("giữ đúng domain", all("rphang.show" in u for u in links[:3]))

print()
print("=" * 78)
print("2. Tải song song 12 trang — đo tốc độ thật")
print("=" * 78)
urls = [f"{BOX_A}page-{i}" for i in range(1, 13)]

t0 = time.perf_counter()
res_list = fast_fetch.fetch_many(urls, workers=config.HTTP_WORKERS)
dt_par = time.perf_counter() - t0

ok = [r for r in res_list if r.ok]
check(f"12 trang song song: {len(ok)}/12 ok", len(ok) >= 10,
      f"{dt_par:.2f}s -> {len(ok)/dt_par:.1f} trang/giây")

# Giữ đúng thứ tự
check("kết quả đúng thứ tự (trang 1 trước trang 2)",
      res_list[0].url.endswith("page-1") and res_list[1].url.endswith("page-2"))

# Bóc được thread từ mọi trang
total_links = 0
for r in ok:
    if r.text:
        s = X.make_soup(r.text)
        l, _ = X.parse_thread_links(s, r.url)
        total_links += len(l)
check("bóc được thread từ mọi trang", total_links > 100,
      f"{total_links} link tổng cộng")

print()
print("=" * 78)
print("3. So với tải tuần tự")
print("=" * 78)
t0 = time.perf_counter()
for u in urls[:6]:
    fast_fetch.fetch_one(u)
dt_seq = time.perf_counter() - t0
t0 = time.perf_counter()
fast_fetch.fetch_many(urls[:6], workers=6)
dt_par6 = time.perf_counter() - t0
check("song song nhanh hơn tuần tự", dt_par6 < dt_seq,
      f"{dt_seq:.2f}s tuần tự vs {dt_par6:.2f}s song song "
      f"({dt_seq/max(dt_par6,0.01):.1f}×)")

print()
print("=" * 78)
print("4. Bóc media từ thread thật (qua HTTP, không cần trình duyệt)")
print("=" * 78)
soup = X.make_soup(res_list[0].text)
links, _ = X.parse_thread_links(soup, BOX_A)
thread_url = next((u for u in links if "noi-quy" not in u), None)
if thread_url:
    tr = fast_fetch.fetch_one(thread_url)
    check("tải được thread", tr.ok, f"{len(tr.text) if tr.text else 0} ký tự")
    if tr.ok:
        ts = X.make_soup(tr.text)
        posts = ts.select("article.message--post")
        check("tìm được post", len(posts) > 0, f"{len(posts)} post")

        imgs, vids, files = X.extract_post_media(posts[0], thread_url)
        check("bóc được media", len(imgs) + len(vids) > 0,
              f"ảnh={len(imgs)} video={len(vids)} file={len(files)}")

        # Quảng cáo đã bị lọc chưa
        ads = [u for u in imgs + vids if any(k in u.lower() for k in
                                             ("xnhau", "/image/", "ads-", "banner"))]
        check("không còn URL quảng cáo", not ads, f"{len(ads)} nghi vấn")

print()
print("=" * 78)
print(f"KET QUA: {sum(results)}/{len(results)} PASS")
print("=" * 78)
sys.exit(0 if all(results) else 1)