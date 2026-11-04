"""Chụp ảnh UI thật để audit.

Chạy: python shot.py <theme> <ten> [rong] [cao]
Ví dụ: python shot.py light before 1060 820

Dùng PIL ImageGrab chụp đúng vùng cửa sổ Tk, không chụp cả màn hình.
"""
import ctypes
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk

theme = sys.argv[1] if len(sys.argv) > 1 else "light"
name = sys.argv[2] if len(sys.argv) > 2 else "shot"
width = int(sys.argv[3]) if len(sys.argv) > 3 else 1060
height = int(sys.argv[4]) if len(sys.argv) > 4 else 820

os.environ.setdefault("RPHANG_DIR", os.path.join(os.environ.get("TEMP", "."), "v72_shot"))
os.makedirs(os.environ["RPHANG_DIR"], exist_ok=True)

import v72

root = tk.Tk()
root.geometry(f"{width}x{height}+60+40")
v72.save_theme(theme)
app = v72.XenForoScannerApp(root)
if app.theme_name != theme:
    app.toggle_theme()

# Đổ log mẫu để thấy đủ loại màu, giống một phiên thật đang chạy
for msg, tag in (
    ("[*] V72 ENGINE: Playwright Native Fetch • cache: E:\\HIDE\\RPHANG", "system"),
    ("[*] Cổng 9222 đã sẵn sàng.", "system"),
    ("\n👥 [USER 1/2] ĐỒNG BỘ DỮ LIỆU: TRAICUBE", "info"),
    ("   [+] TRAICUBE: Định vị thành công 9 Thread bài viết.", "success"),
    ("   [↓] Bài 1: Lâu quá không đăng bài khoe Vợ nay khoe vợ vs ae", "info"),
    ("      ↳ 5/5 tệp xong (5 mới, 0 lỗi)", "info"),
    ("   [✓] TRAICUBE: Bài 1 tải mới 5 ảnh [4 bài của chủ thớt, 1 bài người khác bỏ qua, 1 trang]", "success"),
    ("   [•] TRAICUBE: Bài 2 đã có đủ 7 media, trên đĩa có 7 tệp — không cần tải lại.", "skip"),
    ("   [!] Cảnh báo: 3 tệp lỗi đường truyền trong bài này.", "summary"),
    ("   [!] Đĩa chỉ có 3/7 tệp. Có thể file đã bị xoá; chạy lại để tải bù.", "summary"),
    ("[-] Lỗi: Bạn chưa nhập đường dẫn bài viết!", "error"),
):
    app._safe_log(msg, tag)

root.update_idletasks()
root.update()
time.sleep(0.5)
root.update()

# Lấy toạ độ thật của cửa sổ
root.update_idletasks()
x = root.winfo_rootx()
y = root.winfo_rooty()
w = root.winfo_width()
h = root.winfo_height()

from PIL import ImageGrab
img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
out = os.path.abspath(f"ux_{name}_{theme}.png")
img.save(out)
print(f"da luu: {out}  ({img.size[0]}x{img.size[1]})")
root.destroy()
