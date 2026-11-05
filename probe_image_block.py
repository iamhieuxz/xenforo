"""Kiểm chứng: chặn ảnh có làm hỏng việc bóc DOM không?

RỦI RO LỚN NHẤT của tối ưu này: nếu chặn ảnh làm XenForo không gán data-src
(ảnh không render -> JS lazy-load không chạy), parser sẽ không thấy media.

Chạy: python probe_image_block.py
"""
import asyncio
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
import browser_launcher as B
import xenforo_parse as X

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"   [{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"          {detail}")


# Trang HTML mô phỏng XenForo: có cả ảnh thường và ảnh lazy-load
THREAD_HTML = """<html><body>
<div class="p-description"><time class="u-dt" data-time="1700000000"></time></div>
<h1 class="p-title-value">Bai Test</h1>
<article class="message--post" data-author="tacgia" data-content="p1">
  <div class="message-body">
    <img src="https://example.com/a.jpg">
    <img src="https://example.com/placeholder.gif" data-src="https://example.com/b.jpg">
    <img data-src="https://example.com/c.jpg">
    <a href="https://example.com/doc.zip">file</a>
  </div>
  <header class="message-attribution"><time class="u-dt" data-time="1700000000"></time></header>
</article>
</body></html>"""


async def run(block_images):
    from playwright.async_api import async_playwright

    config.BLOCK_IMAGES = block_images
    config.BLOCK_FONTS = block_images
    config.SESSION_HEADLESS = True
    config.SESSION_BROWSER = "chrome"

    tmp = tempfile.mkdtemp(prefix="imgblk_")
    config.SESSION_PROFILE = os.path.join(tmp, "p")

    import engine
    logs = []
    e = engine.CrawlerEngine(cache=None, log=lambda m, t=None: logs.append(m),
                             stop_event=__import__("threading").Event(),
                             download_dir=tmp)
    async with async_playwright() as p:
        ctx = await e.connect(p)
        if ctx is None:
            return None, logs
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto("about:blank")
            await page.set_content(THREAD_HTML)
            html = await page.content()
            soup = X.make_soup(html)
            post = soup.select_one("article.message--post")
            imgs, vids, files = X.extract_post_media(post, "https://example.com/")
            return (imgs, vids, files), logs
        finally:
            await e.close_browser()
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


async def main():
    print("=" * 78)
    print("CHẶN ẢNH CÓ LÀM HỎNG BÓC DOM KHÔNG?")
    print("=" * 78)

    print("\n1. KHÔNG chặn ảnh (đối chứng)")
    r1, logs1 = await run(False)
    if r1:
        imgs, vids, files = r1
        print(f"     ảnh bóc được: {len(imgs)}  -> {[u.split('/')[-1] for u in imgs]}")
        print(f"     file: {len(files)}")
        check("không chặn: bóc được ảnh", len(imgs) >= 3,
              f"thấy {len(imgs)} ảnh")
    else:
        check("không chặn: mở được trình duyệt", False, "\n".join(logs1[:2]))

    print("\n2. CÓ chặn ảnh + font")
    r2, logs2 = await run(True)
    if r2:
        imgs2, vids2, files2 = r2
        print(f"     ảnh bóc được: {len(imgs2)}  -> {[u.split('/')[-1] for u in imgs2]}")
        print(f"     file: {len(files2)}")
        check("chặn ảnh: vẫn bóc được ảnh", len(imgs2) >= 3,
              f"thấy {len(imgs2)} ảnh — nếu ít hơn thì tối ưu này phá parser")
        check("chặn ảnh: vẫn bóc được file", len(files2) >= 1)
        if r1:
            check("số ảnh KHÔNG giảm so với không chặn",
                  len(imgs2) >= len(r1[0]),
                  f"{len(imgs2)} vs {len(r1[0])}")
    else:
        check("chặn ảnh: mở được trình duyệt", False, "\n".join(logs2[:2]))

    print("\n3. Có log thông báo không")
    joined = "\n".join(logs2)
    check("có log 'Đã chặn tài nguyên'", "Đã chặn tài nguyên" in joined,
          [l for l in logs2 if "chặn" in l.lower()][:1])

    print()
    print("=" * 78)
    print(f"KET QUA: {sum(results)}/{len(results)} PASS")
    print("=" * 78)
    return all(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)