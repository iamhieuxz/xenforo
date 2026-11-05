"""Kiểm chứng: nhật ký không phình vô hạn (nguyên nhân lag).

Chạy: python probe_log_leak.py

Đo thời gian thêm log TRƯỚC và SAU khi vượt ngưỡng. Nếu trim không hoạt
động, chi phí mỗi dòng tăng tuyến tính và app treo dần.
"""
import os
import shutil
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config

_TMP = tempfile.mkdtemp(prefix="logleak_")
config.DOWNLOAD_DIR = _TMP
config.SESSION_PROFILE = _TMP

from PySide6.QtWidgets import QApplication
import gui_fluent

app = QApplication.instance() or QApplication([])
w = gui_fluent.MainWindow(auto_browser=False)
ci = w.crawler_interface
MAX = ci.LOG_MAX_CHARS

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"   [{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"          {detail}")


def add_batch(n):
    """Thêm n dòng, KHÔNG gọi processEvents từng dòng (chậm vô ích)."""
    t0 = time.perf_counter()
    for i in range(n):
        ci.append_log(f"[*] dòng thử #{i} — nội dung giả để đo hiệu năng", "info")
    app.processEvents()
    dt = (time.perf_counter() - t0) * 1000
    chars = ci.log_edit.document().characterCount()
    return dt, chars


print("=" * 78)
print("NHẬT KÝ CÓ BỊ PHÌNH VÔ HẠN KHÔNG?")
print("=" * 78)
print(f"  LOG_MAX_CHARS = {MAX}")
print()

rows = []
for label, n in [("200 dòng đầu", 200), ("thêm 800", 800),
                 ("thêm 2000 (vượt ngưỡng)", 2000), ("thêm 2000 nữa", 2000)]:
    dt, chars = add_batch(n)
    rate = dt / n
    rows.append((label, n, dt, chars, rate))
    print(f"  {label:26} {n:5} dòng  {dt:8.1f} ms  "
          f"({rate:6.3f} ms/dòng)  ký tự={chars}")

print()
check(f"số ký tự không vượt {MAX}",
      rows[-1][3] <= MAX + 200,
      f"cuối cùng = {rows[-1][3]} (ngưỡng {MAX})")

# Chi phí mỗi dòng ở cuối không được cao hơn nhiều lần so với đầu
first_rate = rows[0][4]
last_rate = rows[-1][4]
check("chi phí/dòng không tăng vô hạn",
      last_rate < first_rate * 3,
      f"{first_rate:.3f} ms/dòng (đầu) vs {last_rate:.3f} ms/dòng (cuối)")

# Tài liệu phải còn nội dung (không bị xoá sạch)
check("nhật ký còn nội dung sau khi cắt",
      rows[-1][3] > MAX * 0.5,
      f"còn {rows[-1][3]} ký tự")

print()
print("=" * 78)
print(f"KET QUA: {sum(results)}/{len(results)} PASS")
print("=" * 78)

w.close()
app.processEvents()
shutil.rmtree(_TMP, ignore_errors=True)
sys.exit(0 if all(results) else 1)