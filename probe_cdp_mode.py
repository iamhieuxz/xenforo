"""Kiểm chứng mode CDP đầu-cuối với Chrome thật.

Chạy: python probe_cdp_mode.py

Chứng minh: app mở Chrome -> Chrome lên cổng 9222 -> engine.connect() bám được
vào cửa sổ đó và bóc được DOM. Đây là toàn bộ đường đi của mode cdp.

Dùng profile trong thư mục dự án (ghi được) vì môi trường test chặn ghi
%LOCALAPPDATA%; cơ chế thì giống hệt.
"""
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
import browser_launcher as B

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"   [{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"          {detail}")


async def main():
    exe = B.find_browser_for("chrome")
    if not exe:
        print("Không có Chrome, bỏ qua.")
        return

    tmp = tempfile.mkdtemp(prefix="cdpmode_", dir=os.getcwd())
    profile = os.path.join(tmp, "profile")
    os.makedirs(profile, exist_ok=True)

    print("=" * 78)
    print("MODE CDP — kiểm chứng đầu-cuối")
    print("=" * 78)
    print(f"  chrome : {exe}")
    print(f"  profile: {profile}")
    print(f"  cổng   : {config.CDP_PORT}")
    print()

    # ---- 1. Mở Chrome bằng đúng lệnh của app ----
    args = B.build_args(exe, profile)
    print("1. Mở Chrome")
    print(f"   lenh: {' '.join(args)[:120]}...")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _cleanup():
        """Dọn SẠCH: Chrome đẻ ra nhiều tiến trình con, terminate() một cái
        không đủ — chúng giữ cổng 9222 và làm các lần chạy sau fail."""
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=15)
        except Exception:
            pass
        import shutil as _sh
        _sh.rmtree(tmp, ignore_errors=True)

    opened = False
    for _ in range(30):
        await asyncio.sleep(0.5)
        if B.probe_port()["state"] == "ready":
            opened = True
            break
        if proc.poll() is not None:
            break
    check("Chrome mở cổng thành công", opened,
          f"probe_port = {B.probe_port()['state']}")

    if not opened:
        _cleanup()
        print(f"\nKET QUA: {sum(results)}/{len(results)} PASS")
        return

    # ---- 2. engine.connect() bám vào đúng cửa sổ đó ----
    print()
    print("2. engine.connect() ở mode cdp")
    old_mode = config.BROWSER_MODE
    config.BROWSER_MODE = "cdp"
    logs = []
    import engine
    eng = engine.CrawlerEngine(
        cache=None, log=lambda m, t=None: logs.append(m),
        stop_event=threading.Event(), download_dir=tmp)

    from playwright.async_api import async_playwright
    ctx = None
    async with async_playwright() as p:
        try:
            ctx = await eng.connect(p)
            check("connect() trả về context", ctx is not None,
                  f"type={type(ctx).__name__ if ctx else None}")

            if ctx:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                # KHÔNG dùng set_content trên trang thật: Chrome 156 của người
                # dùng bật Trusted Types, document.write bị chặn và set_content
                # ném "requires 'TrustedHTML' assignment". Đây là giới hạn của
                # trang, không phải lỗi app. Điều hướng tới data: URL rồi đọc DOM.
                try:
                    await page.goto(
                        "data:text/html,<div class='message-body'>"
                        "<img data-src='https://example.com/a.jpg'></div>",
                        timeout=15000)
                    html = await page.content()
                except Exception as e:
                    html = ""
                    print(f"          (goto lỗi: {type(e).__name__}: {e})")

                import xenforo_parse as X
                soup = X.make_soup(html) if html else None
                node = soup.select_one("div.message-body") if soup else None
                imgs = X.extract_post_media(node, "https://example.com/")[0] if node else []
                check("bóc được DOM qua kết nối CDP", len(imgs) == 1,
                      f"{len(imgs)} ảnh")

                # Đếm số cửa sổ: mode cdp KHÔNG được mở thêm cửa sổ mới
                pages = len(ctx.pages)
                check("không mở thêm cửa sổ thừa", pages <= 4,
                      f"context có {pages} page")
        finally:
            # Mode cdp: close_browser() KHÔNG được đóng trình duyệt của người dùng
            await eng.close_browser()
            check("close_browser() không đóng trình duyệt của người dùng",
                  B.probe_port()["state"] == "ready",
                  "cổng vẫn mở sau close_browser()")

    # ---- 3. Dọn ----
    config.BROWSER_MODE = old_mode
    _cleanup()

    # Xác nhận đã dọn sạch: cổng phải đóng sau khi dọn, nếu không lần chạy sau
    # sẽ thấy cổng bị chiếm bởi chính tiến trình mồ côi của lần này.
    for _ in range(10):
        await asyncio.sleep(0.5)
        if B.probe_port()["state"] != "ready":
            break
    check("đã dọn sạch, cổng đóng lại sau khi xong",
          B.probe_port()["state"] != "ready",
          f"probe_port = {B.probe_port()['state']}")

    print()
    print("=" * 78)
    print(f"KET QUA: {sum(results)}/{len(results)} PASS")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0 if all(results) else 1)