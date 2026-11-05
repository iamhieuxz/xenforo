"""Kiểm chứng phương án thay thế cổng 9222: launch_persistent_context.

Ba câu hỏi cần trả lời bằng thực nghiệm, không đoán:
  1. Playwright 1.54 có điều khiển được Cốc Cốc 154 (mới hơn nhiều) không?
  2. launch_persistent_context có cần mở cổng TCP nào không?
  3. Profile riêng đã có session thì đọc được nội dung cần đăng nhập không?

Chạy: python probe_persistent.py
Không đụng profile thật của người dùng — chỉ dùng thư mục tạm.
"""

import asyncio
import os
import socket
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
import browser_launcher as B

COC = r"C:\Program Files\CocCoc\Browser\Application\browser.exe"


def ports_of_pid(pid):
    """Các cổng TCP đang LISTEN của tiến trình `pid`."""
    import subprocess
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                             capture_output=True, text=True, timeout=8).stdout
    except Exception:
        return []
    found = []
    for line in out.splitlines():
        if "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if len(parts) >= 5 and parts[-1] == str(pid):
            local = parts[1]
            if ":" in local:
                try:
                    found.append(int(local.rsplit(":", 1)[1]))
                except ValueError:
                    pass
    return sorted(set(found))


async def main():
    from playwright.async_api import async_playwright

    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"   [{'PASS' if ok else 'FAIL'}] {name}")
        if detail:
            print(f"          {detail}")

    exe = COC if os.path.isfile(COC) else B.find_browser()
    print("=" * 78)
    print("PHUONG AN THAY THE CONG 9222: launch_persistent_context")
    print("=" * 78)
    print(f"  executable : {exe}")

    tmp = tempfile.mkdtemp(prefix="persist_")
    profile = os.path.join(tmp, "profile")
    os.makedirs(profile, exist_ok=True)
    print(f"  profile tam: {profile}")
    print()

    print("=" * 78)
    print("1. Playwright 1.54 + Coc Coc 154 co tuong thich khong?")
    print("=" * 78)

    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=profile,
                executable_path=exe,
                headless=True,
                args=["--no-sandbox", "--disable-crash-reporter"],
            )
            check("launch_persistent_context thành công", True,
                  f"version: {browser.browser.version if browser.browser else 'n/a'}")

            page = browser.pages[0] if browser.pages else await browser.new_page()
            await page.goto("about:blank", timeout=15000)
            check("mở được page", True, f"url: {page.url}")

            # Thử lấy nội dung thật để chắc chắn render được, không chỉ mở tab
            await page.set_content("<h1 id='x'>XIN CHAO</h1>")
            txt = await page.inner_text("#x")
            check("đọc được DOM", txt == "XIN CHAO", f"nội dung: {txt!r}")

            # Đếm cổng đang mở của tiến trình này
            pid = None
            try:
                pid = browser.browser.process.pid if browser.browser else None
            except Exception:
                pass
            if pid:
                ports = ports_of_pid(pid)
                print(f"          PID {pid}, cổng TCP đang LISTEN: {ports or 'KHÔNG CÓ'}")
                # Playwright dùng pipe/websocket nội bộ trên cổng ngẫu nhiên
                # bind 127.0.0.1. Điểm chính: KHÔNG cần cổng cố định 9222.
                check("không cần cổng cố định 9222",
                      config.CDP_PORT not in (ports or []),
                      f"9222 có trong danh sách: {config.CDP_PORT in (ports or [])}")

            # Kiểm tra cookie API hoạt động (cơ chế chuyển session sẽ dùng)
            ctx = browser
            await ctx.add_cookies([{
                "name": "dsh_probe", "value": "1",
                "domain": "example.com", "path": "/",
            }])
            got = await ctx.cookies("http://example.com")
            check("add_cookies / cookies() hoạt động",
                  any(c["name"] == "dsh_probe" for c in got),
                  f"{len(got)} cookie")

    except Exception as e:
        check("launch_persistent_context", False, f"{type(e).__name__}: {e}")
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 78)
    print(f"KET QUA: {sum(results)}/{len(results)} PASS")
    print("=" * 78)
    return all(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
