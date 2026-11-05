"""Kiểm chứng: app có mở cổng ĐÚNG THEO MODE không.

Lỗi đã sửa trước đây: auto_launch_browser() không kiểm BROWSER_MODE nên vẫn mở
cổng 9222 dù mode là persistent.

Giờ mặc định là "cdp", nên probe phải ÉP mode thay vì giả định.
Nó kiểm hai chiều:
  - mode persistent -> KHÔNG được gọi launch() (không mở cổng nào)
  - mode cdp        -> PHẢI gọi launch() (đó là cách nó kết nối)

Chạy: python probe_no_port.py
"""
import os
import shutil
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
    results.append(bool(ok))
    print(f"   [{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"          {detail}")


def spy_launch():
    """Thay launch() bằng hàm đếm; trả danh sách để đếm số lần gọi."""
    import browser_launcher
    calls = []
    real = browser_launcher.launch

    def spy(*a, **k):
        calls.append((a, k))
        return False, "(đã chặn trong test)"

    browser_launcher.launch = spy
    return calls, lambda: setattr(browser_launcher, "launch", real)


def run_fluent(mode):
    from PySide6.QtWidgets import QApplication
    import gui_fluent

    old = config.BROWSER_MODE
    config.BROWSER_MODE = mode
    calls, restore = spy_launch()
    try:
        app = QApplication.instance() or QApplication([])
        w = gui_fluent.MainWindow(auto_browser=False)
        try:
            w.auto_launch_browser()
            app.processEvents()
            return len(calls), "\n".join(m for m, _ in w.log_history)
        finally:
            w.close()
            app.processEvents()
    finally:
        restore()
        config.BROWSER_MODE = old


def run_tk(mode):
    import tkinter as tk
    import v72

    old = config.BROWSER_MODE
    config.BROWSER_MODE = mode
    calls, restore = spy_launch()
    try:
        root = tk.Tk()
        root.withdraw()
        a = v72.XenForoScannerApp(root)
        try:
            a.auto_launch_browser()
            root.update()
            return len(calls), "\n".join(m for m, _ in a._log_lines)
        finally:
            a.cache.close()
            root.destroy()
    finally:
        restore()
        config.BROWSER_MODE = old


print("=" * 78)
print("APP MỞ CỔNG ĐÚNG THEO MODE?")
print("=" * 78)
print(f"  mode mặc định: {config.BROWSER_MODE}")
print(f"  cổng {PORT} lúc bắt đầu: {port_open()}")
print()

# ---- mode persistent: KHÔNG được mở cổng ----
print("=" * 78)
print("1. mode persistent — không được mở cổng TCP nào")
print("=" * 78)
n, logs = run_fluent("persistent")
check("gui_fluent không gọi launch()", n == 0, f"launch() gọi {n} lần")
check("gui_fluent báo không mở cổng", "Không mở cổng TCP nào" in logs)
check(f"cổng {PORT} vẫn đóng", not port_open())

n, logs = run_tk("persistent")
check("v72 không gọi launch()", n == 0, f"launch() gọi {n} lần")
check("v72 báo không mở cổng", "Không mở cổng TCP nào" in logs)

# ---- mode cdp: PHẢI gọi launch() ----
print()
print("=" * 78)
print("2. mode cdp — PHẢI gọi launch() (đó là cách nó kết nối)")
print("=" * 78)
n, logs = run_fluent("cdp")
time.sleep(0.3)
check("gui_fluent gọi launch()", n > 0, f"launch() gọi {n} lần")

n, logs = run_tk("cdp")
check("v72 gọi launch()", n > 0, f"launch() gọi {n} lần")

print()
print("=" * 78)
print(f"KET QUA: {sum(results)}/{len(results)} PASS")
print("=" * 78)
shutil.rmtree(_TMP, ignore_errors=True)
sys.exit(0 if all(results) else 1)