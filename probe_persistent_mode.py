"""Kiểm chứng mode persistent đầu-cuối trên code thật.

Chạy: python probe_persistent_mode.py
Mọi thao tác trong thư mục tạm — không đụng profile thật của người dùng.
"""
import asyncio
import os
import shutil
import sys
import tempfile
import threading

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
import engine
import session_source as SS

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"   [{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"          {detail}")


async def main():
    print("=" * 78)
    print("MODE PERSISTENT — kiểm chứng đầu-cuối trên code thật")
    print("=" * 78)

    tmp = tempfile.mkdtemp(prefix="pmode_")
    profile = os.path.join(tmp, "profile")
    os.makedirs(profile, exist_ok=True)

    # Trỏ app vào profile tạm, trình duyệt Chrome, headless
    config.BROWSER_MODE = "persistent"
    config.SESSION_BROWSER = "chrome"
    config.SESSION_PROFILE = profile
    config.SESSION_HEADLESS = True

    print(f"  BROWSER_MODE   : {config.BROWSER_MODE}")
    print(f"  SESSION_BROWSER: {config.SESSION_BROWSER}")
    print(f"  SESSION_PROFILE: {profile}")
    print()

    logs = []

    def log(msg, tag=None):
        logs.append(msg)
        print(f"     log> {msg[:110]}")

    eng = engine.CrawlerEngine(
        cache=None, log=log, stop_event=threading.Event(), download_dir=tmp)

    print("=" * 78)
    print("1. connect() ở mode persistent")
    print("=" * 78)

    from playwright.async_api import async_playwright

    ctx = None
    async with async_playwright() as p:
        try:
            ctx = await eng.connect(p)
            check("connect() trả về context", ctx is not None,
                  f"type={type(ctx).__name__ if ctx else None}")
            if ctx:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await page.goto("about:blank", timeout=15000)

                # Ghi cookie qua trang web (cách duy nhất persist được)
                await page.set_content("<h1>x</h1>")
                check("mở và render page được", True, f"pages={len(ctx.pages)}")

                # ctx.request dùng để tải media
                try:
                    r = await ctx.request.get("https://example.com", timeout=20000)
                    check("ctx.request.get hoạt động", r.status == 200, f"status={r.status}")
                    await r.dispose()
                except Exception as e:
                    check("ctx.request.get hoạt động", False, f"{type(e).__name__}: {e}")
        finally:
            pass

    print()
    print("=" * 78)
    print("2. close_browser() đóng đúng context của app")
    print("=" * 78)
    await eng.close_browser()
    check("close_browser() không ném exception", True)
    check("_browser đã reset", eng._browser is None)

    # Context đã đóng -> dùng lại phải lỗi
    if ctx:
        try:
            await ctx.new_page()
            check("context sau close không dùng được", False, "vẫn mở được page")
        except Exception:
            check("context sau close không dùng được", True, "đã đóng đúng")

    print()
    print("=" * 78)
    print("3. Session sống qua 2 lần connect liên tiếp")
    print("=" * 78)

    async def roundtrip(marker):
        async with async_playwright() as p2:
            e2 = engine.CrawlerEngine(cache=None, log=lambda *a, **k: None,
                                      stop_event=threading.Event(), download_dir=tmp)
            c2 = await e2.connect(p2)
            try:
                pg = c2.pages[0] if c2.pages else await c2.new_page()
                await pg.goto("https://example.com", timeout=25000)
                if marker:
                    await pg.evaluate(
                        "document.cookie='pmode_ck=VALUE1; path=/; max-age=2592000';")
                got = await pg.evaluate("document.cookie")
                return got
            finally:
                await e2.close_browser()

    first = await roundtrip(True)
    second = await roundtrip(False)
    check("lần 1 đặt được cookie", "pmode_ck=VALUE1" in first, first[:80])
    check("lần 2 còn cookie (session sống)", "pmode_ck=VALUE1" in second, second[:80])

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 78)
    print(f"KET QUA: {sum(results)}/{len(results)} PASS")
    print("=" * 78)
    return all(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
