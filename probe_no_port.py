"""Kiểm chứng: app KHÔNG được mở cổng 9222 ở mode persistent.

Lỗi đã sửa: auto_launch_browser() không kiểm BROWSER_MODE nên vẫn gọi
browser_launcher.launch() và mở cổng 9222 dù mode là persistent.

Chạy: python probe_no_port.py
"""
import socket
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config

# Môi trường sandbox chặn ghi %LOCALAPPDATA% và E:\ -> trỏ hết vào thư mục tạm
# để test đo đúng thứ cần đo (cổng có mở không), không bị chặn bởi quyền ghi.
_TMP = tempfile.mkdtemp(prefix="noport_")
config.DOWNLOAD_DIR = _TMP
config.SESSION_PROFILE = _TMP
config.SESSION_HEADLESS = True

PORT = config.CDP_PORT
results = []


def port_open(port=PORT, host="127.0.0.1"):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def check(name, ok, detail=""):
    results.append(ok)
    print(f"   [{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"          {detail}")


print("=" * 78)
print("APP CÓ MỞ CỔNG 9222 KHÔNG (mode persistent)?")
print("=" * 78)
print(f"  BROWSER_MODE       : {config.BROWSER_MODE}")
print(f"  AUTO_LAUNCH_BROWSER: {config.AUTO_LAUNCH_BROWSER}")
print(f"  cổng {PORT} trước khi chạy app: {port_open()}")
print()

# Ghi lại mọi lần launch() được gọi
import browser_launcher

launch_calls = []
_real_launch = browser_launcher.launch


def spy_launch(*a, **k):
    launch_calls.append((a, k))
    return False, "(đã chặn trong test)"


browser_launcher.launch = spy_launch

try:
    print("=" * 78)
    print("1. gui_fluent — khởi động ở mode persistent")
    print("=" * 78)
    from PySide6.QtWidgets import QApplication
    import gui_fluent

    app = QApplication.instance() or QApplication(sys.argv)
    w = gui_fluent.MainWindow(auto_browser=False)
    before = len(launch_calls)
    w.auto_launch_browser()
    app.processEvents()
    after = len(launch_calls)
    check("không gọi browser_launcher.launch()", after == before,
          f"launch() gọi {after - before} lần")
    check(f"cổng {PORT} vẫn đóng", not port_open())

    # Log phải nói rõ là không mở cổng
    joined = "\n".join(m for m, _ in w.log_history)
    check("log nói 'Không mở cổng TCP nào'",
          "Không mở cổng TCP nào" in joined,
          [m for m in joined.splitlines() if "persistent" in m.lower()][:2])

    w.close()
    app.processEvents()

    print()
    print("=" * 78)
    print("2. v72 (Tkinter) — khởi động ở mode persistent")
    print("=" * 78)
    import tkinter as tk
    import v72

    root = tk.Tk()
    root.withdraw()
    a = v72.XenForoScannerApp(root)
    before = len(launch_calls)
    a.auto_launch_browser()
    # v72 ghi log qua root.after(0, ...) nên phải xả hàng đợi mới thấy.
    root.update()
    after = len(launch_calls)
    check("không gọi browser_launcher.launch()", after == before,
          f"launch() gọi {after - before} lần")
    check(f"cổng {PORT} vẫn đóng", not port_open())

    joined2 = "\n".join(m for m, _ in a._log_lines)
    check("log nói 'Không mở cổng TCP nào'",
          "Không mở cổng TCP nào" in joined2)

    a.cache.close()
    root.destroy()

    print()
    print("=" * 78)
    print("3. Đối chứng: mode 'cdp' VẪN gọi launch()")
    print("=" * 78)
    config.BROWSER_MODE = "cdp"
    app2 = QApplication.instance() or QApplication(sys.argv)
    w2 = gui_fluent.MainWindow(auto_browser=False)
    before = len(launch_calls)
    w2.auto_launch_browser()
    time.sleep(0.3)
    app2.processEvents()
    after = len(launch_calls)
    check("mode cdp có gọi launch() (đúng như thiết kế)", after > before,
          f"launch() gọi {after - before} lần")
    w2.close()
    app2.processEvents()
    config.BROWSER_MODE = "persistent"

finally:
    browser_launcher.launch = _real_launch

print()
print("=" * 78)
print(f"KET QUA: {sum(results)}/{len(results)} PASS")
print("=" * 78)
sys.exit(0 if all(results) else 1)