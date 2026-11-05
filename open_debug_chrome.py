"""Mở Chrome ở cổng debug 9222 với ĐÚNG profile có session của bạn.

Vì sao cần script này: Chrome phải được mở với `--remote-debugging-port` NGAY
TỪ ĐẦU. Không có cách nào bật cổng debug cho một cửa sổ Chrome đã mở sẵn —
Chrome chỉ đọc cờ đó lúc khởi động. Và vì cờ này gắn với tiến trình, bạn phải
đóng hết Chrome trước rồi mở lại qua script.

Script dùng đúng profile mà app sẽ bám vào (BROWSER_PROFILE trong config.py),
nên cookie, extension và phiên đăng nhập của bạn vẫn còn.

Chạy:
    python open_debug_chrome.py          # mở Chrome ở cổng 9222
    python open_debug_chrome.py --check  # chỉ kiểm tra trạng thái

Hoặc bấm đúp file open_debug_chrome.bat nếu có.
"""

import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
import browser_launcher as B


def running_chrome_count():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/FO", "CSV"],
                             capture_output=True, text=True, timeout=10).stdout
        return len([l for l in out.splitlines() if "chrome" in l.lower()])
    except Exception:
        return -1


def report():
    """In trạng thái hiện tại: cổng, tiến trình, profile."""
    print("=" * 74)
    print("TRẠNG THÁI")
    print("=" * 74)
    state = B.probe_port()
    print(f"  cổng {config.CDP_PORT}      : {state['state']} — {state['detail']}")

    exe = B.find_browser_for("chrome")
    print(f"  chrome.exe          : {exe or 'KHÔNG TÌM THẤY'}")

    prof = B.profile_dir()
    print(f"  profile sẽ dùng     : {prof}")
    print(f"  profile tồn tại     : {os.path.isdir(prof)}")

    ck = os.path.join(prof, "Default", "Network", "Cookies")
    if os.path.isfile(ck):
        import session_source as SS
        got = SS.has_login_session(prof, SS.FORUM_HOST_HINTS)
        print(f"  cookie đăng nhập    : {'CÓ (xf_user)' if got else 'CHƯA CÓ'}")
    else:
        print(f"  cookie đăng nhập    : chưa có file cookie")

    print(f"  chrome.exe đang chạy: {running_chrome_count()} process")
    print()


def main():
    check_only = "--check" in sys.argv

    report()

    if check_only:
        return 0

    # Đã sẵn sàng thì không mở thêm — mở thêm là tạo cửa sổ thừa.
    if B.probe_port()["state"] == "ready":
        print("Cổng đã sẵn sàng, không cần mở thêm. Bấm Quét trong app.")
        return 0

    n = running_chrome_count()
    if n > 0:
        print(f"[!] Đang có {n} tiến trình chrome.exe chạy.")
        print("    Chrome chỉ đọc cờ --remote-debugging-port lúc khởi động, nên")
        print("    cửa sổ đã mở sẽ KHÔNG có cổng debug.")
        print()
        print("    Hãy ĐÓNG HẾT cửa sổ Chrome rồi chạy lại script này.")
        print("    (Dữ liệu và phiên đăng nhập vẫn còn: chúng nằm trong profile,")
        print("     không phải trong tiến trình.)")
        return 1

    ok, msg = B.launch()
    print(f"[{'✓' if ok else '!'}] {msg}")
    if ok:
        print()
        print("Chrome đang chạy ở cổng", config.CDP_PORT)
        print("Giữ cửa sổ này mở, rồi bấm Quét trong app.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())