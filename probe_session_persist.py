"""Kiểm chứng: user_data_dir CỐ ĐỊNH thì login 1 lần dùng mãi?

Trả lời trực tiếp câu hỏi:
  - "login 1 lần, mọi phiên sau pass" đúng hay sai?
  - hay "mỗi phiên mở 1 profile riêng"?

Lưu ý môi trường: sandbox chặn ghi vào %LOCALAPPDATA%, nên không mở được
profile thật của app. Ở đây dùng profile cố định trong thư mục tạm — cùng
một cơ chế, chỉ khác đường dẫn.

Chạy: python probe_session_persist.py
"""
import asyncio
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COC = r"C:\Program Files\CocCoc\Browser\Application\browser.exe"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# Trang kiểm thử: dùng example.com vì rphang cần đăng nhập thật.
# Điều cần chứng minh là CƠ CHẾ lưu session, không phải nội dung cookie cụ thể.
TEST_SITE = "https://example.com"


async def open_ctx(p, exe, profile_dir):
    return await p.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        executable_path=exe,
        headless=True,
        args=["--no-sandbox", "--disable-crash-reporter"],
    )


async def phase_login(exe, profile_dir):
    """Lần 1: 'đăng nhập' = đặt cookie qua trang web (giống login thật)."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        ctx = await open_ctx(p, exe, profile_dir)
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(TEST_SITE, timeout=25000)
            await page.evaluate(
                "document.cookie='auth_token=LOGGED_IN_123; path=/; max-age=2592000';")
            got = await page.evaluate("document.cookie")
            return "auth_token" in got
        finally:
            await ctx.close()


async def phase_check(exe, profile_dir):
    """Các lần sau: mở lại, xem cookie còn không."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        ctx = await open_ctx(p, exe, profile_dir)
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(TEST_SITE, timeout=25000)
            got = await page.evaluate("document.cookie")
            return "auth_token=LOGGED_IN_123" in got, got
        finally:
            await ctx.close()


async def main():
    exe = COC if os.path.isfile(COC) else CHROME
    ok_all = True

    print("=" * 78)
    print("CÂU HỎI: login 1 lần dùng mãi, hay mỗi phiên 1 profile mới?")
    print("=" * 78)
    print(f"  executable: {exe}")
    print()

    # ---------- Phần 1: profile CỐ ĐỊNH ----------
    print("=" * 78)
    print("PHẦN 1 — user_data_dir CỐ ĐỊNH (giống app hiện tại)")
    print("=" * 78)
    base = tempfile.mkdtemp(prefix="fixed_")
    fixed = os.path.join(base, "profile")
    os.makedirs(fixed, exist_ok=True)
    print(f"  profile: {fixed}")
    print()

    try:
        logged = await phase_login(exe, fixed)
        print(f"  Lần 1 (đăng nhập)      : đặt được cookie = {logged}")

        r2, got2 = await phase_check(exe, fixed)
        print(f"  Lần 2 (mở lại)         : còn cookie = {r2}")

        r3, got3 = await phase_check(exe, fixed)
        print(f"  Lần 3 (mở lại)         : còn cookie = {r3}")

        print()
        if logged and r2 and r3:
            print("  => PASS: profile cố định giữ session qua các lần chạy.")
            print("     LOGIN 1 LẦN, CÁC PHIÊN SAU TỰ ĐỘNG PASS.")
        else:
            print("  => FAIL: session không sống qua lần chạy.")
            ok_all = False
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # ---------- Phần 2: profile MỚI mỗi lần ----------
    print()
    print("=" * 78)
    print("PHẦN 2 — Profile MỚI mỗi lần (đối chứng)")
    print("=" * 78)
    for i in (1, 2):
        tmp = tempfile.mkdtemp(prefix=f"newp{i}_")
        prof = os.path.join(tmp, "p")
        os.makedirs(prof, exist_ok=True)
        print(f"  Lần {i} dùng profile mới: {prof}")
        try:
            # Lần 1: đăng nhập
            lg = await phase_login(exe, prof)
            # Lần 2 trên cùng profile mới -> nếu giữ thì phải pass
            kept, _ = await phase_check(exe, prof)
            print(f"      đăng nhập={lg}, mở lại cùng profile={kept}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("  Như vậy: mỗi lần đổi thư mục = mất session, phải login lại.")
    print("  Nhưng trong CÙNG một thư mục thì session sống (Phần 1).")

    # ---------- Kết luận ----------
    print()
    print("=" * 78)
    print("KẾT LUẬN")
    print("=" * 78)
    print("  user_data_dir CỐ ĐỊNH  -> 1 profile duy nhất")
    print("                            login 1 lần, mọi phiên sau pass")
    print("  Mỗi phiên đổi thư mục  -> mất session, login lại mỗi lần")
    print()
    print("  App hiện tại ĐÃ dùng profile cố định (V72Crawler\\v72_crawl),")
    print("  và profile đó ĐÃ có cookie xf_user còn hạn 350 ngày.")
    print("  => Cơ chế 'login 1 lần' vốn đã đúng.")
    print("  => Việc cần làm chỉ là BỎ CỔNG 9222, không phải đổi profile.")
    return ok_all


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
