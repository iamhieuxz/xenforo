"""Phân tích cấu trúc rphang.show (XenForo 2.3 + UI.X + add-on SAM).

Chạy: python analyze_rphang.py

Mục đích: xác định chính xác selector cho hai box người dùng quan tâm, và
kiểm tra code hiện tại có bóc được không. Mọi kết luận dưới đây đều từ HTML
thật, không suy đoán.
"""
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")

BOXES = {
    "clip-sex-phim-sex": "https://rphang.show/box/clip-sex-phim-sex.86/",
    "nhat-ky-may-mua": "https://rphang.show/box/nhat-ky-may-mua.140/",
}


def get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def section(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


section("0. CLOUDFLARE — có thử thách không?")
for name, url in BOXES.items():
    try:
        html = get(url)
        body_low = html.lower()
        has_challenge = ("cf-challenge" in body_low or "just a moment" in body_low
                         or "challenge-platform" in body_low)
        xf = re.search(r'data-xf="([^"]+)"', html)
        print(f"  {name:22} len={len(html):7}  challenge={has_challenge}  "
              f"XF={xf.group(1) if xf else '?'}")
    except Exception as e:
        print(f"  {name:22} LỖI {type(e).__name__}: {e}")

section("1. CẤU TRÚC BOX")
for name, url in BOXES.items():
    html = get(url)
    titles = re.findall(r'<div class="structItem-title"[^>]*>(.*?)</div>', html, re.S)
    links = []
    for b in titles:
        m = re.findall(r'href="(/t/[^"]+)"', b)
        if m:
            links.append(m[-1])
    authors = re.findall(
        r'class="structItem structItem--thread[^"]*"[^>]*data-author="([^"]+)"', html)
    pages = re.findall(r'href="[^"]*?/page-(\d+)"', html)
    maxpage = max((int(p) for p in pages), default=1)

    print(f"\n  {name}")
    print(f"    link box        : {url}")
    print(f"    thread/trang    : {len(links)}")
    print(f"    tổng số trang   : {maxpage}")
    print(f"    data-author     : {len(authors)} -> {authors[:4]}")
    print(f"    URL thread dạng : /t/<slug>.<id>/  (KHÔNG phải /threads/)")
    for l in links[:3]:
        print(f"      {l}")

section("2. CẤU TRÚC THREAD — media nằm ở đâu")
thread_url = None
for name, url in BOXES.items():
    html = get(url)
    titles = re.findall(r'<div class="structItem-title"[^>]*>(.*?)</div>', html, re.S)
    for b in titles:
        m = re.findall(r'href="(/t/[^"]+)"', b)
        if m and "noi-quy" not in m[-1]:
            thread_url = "https://rphang.show" + m[-1]
            break
    if thread_url:
        break

print(f"  thread mẫu: {thread_url}")
th = get(thread_url)
print(f"  độ dài HTML : {len(th)}")
print(f"  message--post: {th.count('message--post')}")

print("\n  Media thật:")
pat_video = re.findall(r'<source src="(/data/attachment-files/[^"]+)"', th)
print(f"    <source src=/data/attachment-files/>: {len(pat_video)}")
for v in pat_video[:3]:
    print(f"      {v[:100]}")

pat_img = re.findall(r'<img[^>]*src="(/data/attachment-files/[^"]+)"', th)
print(f"    <img src=/data/attachment-files/>  : {len(pat_img)}")
for v in pat_img[:3]:
    print(f"      {v[:100]}")

pat_attach = re.findall(r'href="(/attachments/[^"]+)"', th)
print(f"    href=/attachments/                 : {len(pat_attach)}")

pat_attachfiles = re.findall(r'(/data/attachment-files/[^"\'\s]+)', th)
print(f"    BẤT KỲ /data/attachment-files/     : {len(pat_attachfiles)}")

print("\n  Rác cần loại:")
print(f"    add-on SAM (quảng cáo)   : {th.count('samCodeUnit')} khối")
print(f"    samItem                  : {th.count('samItem')}")
print(f"    reaction-image (emoji)   : {th.count('reaction-image')}")
print(f"    avatar                   : {th.count('/data/avatars/')}")

section("3. CODE HIỆN TẠI CÓ BÓC ĐƯỢC KHÔNG")
import xenforo_parse as X

html_box = get(BOXES["clip-sex-phim-sex"])
soup = X.make_soup(html_box)
found, nxt = X.parse_thread_links(soup, BOXES["clip-sex-phim-sex"])
print(f"  parse_thread_links tìm được: {len(found)} link")
print(f"    ví dụ: {found[:2]}")
print(f"    trang kế: {nxt}")
print(f"    => {'PASS' if len(found) > 10 else 'FAIL — cần sửa selector'}")

th_soup = X.make_soup(th)
posts = th_soup.select("article.message--post")
print(f"\n  select('article.message--post'): {len(posts)}")
if posts:
    imgs, vids, files = X.extract_post_media(posts[0], thread_url)
    print(f"    post đầu: ảnh={len(imgs)} video={len(vids)} file={len(files)}")
    print(f"    video: {vids[:2]}")

# Đếm xem có gì bị bỏ sót
print(f"\n  Media thật trong trang: video={len(pat_video)} img={len(pat_img)}")
total_boc = 0
for p in posts:
    i, v, f = X.extract_post_media(p, thread_url)
    total_boc += len(i) + len(v) + len(f)
print(f"  Tổng bóc được qua extract_post_media: {total_boc}")
print(f"  => {'OK' if total_boc > 0 else 'FAIL — cần sửa parser'}")

section("4. ĐĂNG NHẬP")
print("  Box công khai: trang trả 200 không cần đăng nhập.")
print("  Kiểm tra có phải nội dung đầy đủ hay bị cắt:")
print(f"    có link /login/ : {'/login/' in html_box}")
print(f"    tiêu đề <title>: ", end="")
m = re.search(r"<title>(.*?)</title>", html_box, re.S)
print(m.group(1).strip()[:70] if m else "?")