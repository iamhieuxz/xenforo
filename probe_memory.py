"""Đo mức tiêu thụ bộ nhớ của app và trình duyệt.

Chạy: python probe_memory.py

Mục tiêu: định lượng "lag, treo, nhiều bộ nhớ" thay vì đoán.
Đo ba thứ:
  1. RAM của tiến trình Python (app)
  2. RAM của cả cây tiến trình trình duyệt (Chromium đẻ ra nhiều process)
  3. Số process và số tab theo thời gian
"""

import asyncio
import os
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config

try:
    import psutil
except ImportError:
    psutil = None


def rss_mb(pid):
    """RAM thực (RSS) của một pid, đơn vị MB."""
    if psutil is None:
        return None
    try:
        return psutil.Process(pid).memory_info().rss / 1024 / 1024
    except Exception:
        return None


def tree_rss_mb(pid):
    """Tổng RAM của pid và mọi tiến trình con."""
    if psutil is None:
        return None
    try:
        p = psutil.Process(pid)
        total = p.memory_info().rss
        for child in p.children(recursive=True):
            try:
                total += child.memory_info().rss
            except Exception:
                pass
        return total / 1024 / 1024
    except Exception:
        return None


def browser_tree_by_profile(profile_dir):
    """Tổng RAM của mọi chrome.exe có --user-data-dir trỏ tới profile này.

    Không dùng ctx.browser.process: Browser của Playwright không có thuộc tính
    đó. Nhận diện qua command line là cách duy nhất đáng tin khi trình duyệt do
    driver node khởi động.
    """
    if psutil is None:
        return None, 0
    total, n = 0, 0
    needle = os.path.normcase(profile_dir)
    for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
        try:
            name = (proc.info["name"] or "").lower()
            if name not in ("chrome.exe", "browser.exe", "msedge.exe"):
                continue
            cmd = " ".join(proc.info["cmdline"] or [])
            if needle in os.path.normcase(cmd):
                total += proc.info["memory_info"].rss
                n += 1
        except Exception:
            continue
    return total / 1024 / 1024, n


def count_process(name):
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV"],
                             capture_output=True, text=True, timeout=8).stdout
        return len([l for l in out.splitlines() if name.lower() in l.lower()])
    except Exception:
        return -1


def show(label, python_rss, browser_tree, nproc):
    r1 = f"{python_rss:7.0f} MB" if python_rss else "     n/a"
    r2 = f"{browser_tree:7.0f} MB" if browser_tree else "     n/a"
    print(f"  {label:32} app={r1}  browser(cây)={r2}  chrome.exe={nproc}")


async def main():
    print("=" * 78)
    print("ĐO BỘ NHỚ — vì sao app ngốn nhiều RAM")
    print("=" * 78)

    if psutil is None:
        print("  (thiếu psutil, chỉ đo được số process. pip install psutil)")
    import psutil as _p
    this = _p.Process()

    show("baseline (chưa mở gì)", rss_mb(os.getpid()), 0, count_process("chrome.exe"))

    # ---- 1. Mở persistent context, đo sau khi mở ----
    from playwright.async_api import async_playwright
    import browser_launcher as B

    tmp = tempfile.mkdtemp(prefix="mem_")
    profile = os.path.join(tmp, "p")
    os.makedirs(profile, exist_ok=True)
    exe = B.find_browser_for("chrome")
    print(f"\n  executable: {exe}")

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=profile, executable_path=exe, headless=True,
            args=["--no-sandbox", "--disable-crash-reporter"])

        show("sau khi mở browser", rss_mb(os.getpid()), browser_tree_by_profile(profile)[0],
             count_process("chrome.exe"))

        # ---- 2. Mở N tab như engine làm ----
        print("\n  Mở tab, đo sau mỗi 5 tab:")
        pages = []
        for i in range(1, 21):
            pg = await ctx.new_page()
            await pg.goto("about:blank", timeout=10000)
            pages.append(pg)
            if i % 5 == 0:
                show(f"  {i} tab", rss_mb(os.getpid()), browser_tree_by_profile(profile)[0],
                     count_process("chrome.exe"))

        # ---- 3. Trang có ảnh thật (đo nặng hơn about:blank) ----
        print("\n  Tải trang có nhiều ảnh (giống thread thật):")
        html = "<html><body>" + "".join(
            f'<img src="data:image/png;base64,{"A" * 20000}">' for _ in range(50)
        ) + "</body></html>"
        for i in range(5):
            pg = await ctx.new_page()
            await pg.set_content(html)
            pages.append(pg)
        show("  +5 tab có ảnh", rss_mb(os.getpid()), browser_tree_by_profile(profile)[0],
             count_process("chrome.exe"))

        # ---- 4. Đóng tab ----
        print("\n  Đóng 25 tab:")
        closed = 0
        for pg in pages:
            try:
                await pg.close()
                closed += 1
            except Exception:
                pass
        await asyncio.sleep(2)
        show(f"  đã đóng {closed} tab", rss_mb(os.getpid()), browser_tree_by_profile(profile)[0],
             count_process("chrome.exe"))

        await ctx.close()
        await asyncio.sleep(2)
        show("sau khi đóng browser", rss_mb(os.getpid()), 0, count_process("chrome.exe"))

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 78)
    print("Ghi chú: 'browser(cây)' = tổng RAM của tiến trình driver Playwright và")
    print("  toàn bộ tiến trình con (Chromium đẻ ra nhiều process: renderer, GPU,")
    print("  network, utility). Đây thường là phần ngốn RAM nhất, không phải app.")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())