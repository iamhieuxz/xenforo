"""Chụp ảnh giao diện PySide6 + PyQt-Fluent-Widgets để kiểm tra visual.

Chạy: python shot_qt.py [dark|light] [ten]
"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme, Theme

import gui_fluent

theme_arg = sys.argv[1] if len(sys.argv) > 1 else "dark"
name_arg = sys.argv[2] if len(sys.argv) > 2 else "fluent"

app = QApplication(sys.argv)

if theme_arg == "light":
    setTheme(Theme.LIGHT)
else:
    setTheme(Theme.DARK)

window = gui_fluent.MainWindow()
window.resize(1100, 850)
window.show()

sample_logs = [
    ("[*] V72 FLUENT ENGINE: Playwright Native Fetch • SQLite Index Active", "system"),
    ("[*] Cổng debug 9222 đã sẵn sàng kết nối.", "system"),
    ("\n👥 [USER 1/2] ĐỒNG BỘ DỮ LIỆU: TRAICUBE", "info"),
    ("   [+] TRAICUBE: Định vị thành công 9 Thread bài viết.", "success"),
    ("   [↓] Bài 1: Lâu quá không đăng bài khoe Vợ nay khoe vợ vs ae", "info"),
    ("      ↳ 5/5 tệp xong (5 mới, 0 lỗi)", "info"),
    ("   [✓] TRAICUBE: Bài 1 tải mới 5 ảnh [4 bài của chủ thớt, 1 bài người khác bỏ qua, 1 trang]", "success"),
    ("   [•] TRAICUBE: Bài 2 đã có đủ 7 media, trên đĩa có 7 tệp — không cần tải lại.", "skip"),
    ("   [!] Cảnh báo: 2 tệp lỗi đường truyền trong bài này.", "summary"),
    ("[-] Lỗi: Bạn chưa nhập đường dẫn bài viết hợp lệ!", "error"),
]

for msg, tag in sample_logs:
    window.append_log(msg, tag)

# Giả lập trạng thái đang chạy
window.crawler_interface.lbl_state_title.setText("ĐANG QUÉT")
window.crawler_interface.lbl_state_detail.setText("Đang cào dữ liệu: Tác giả TRAICUBE (Trang 2/5)...")
window.crawler_interface.progress_bar.setVisible(True)
window.crawler_interface.progress_bar.start()
window.crawler_interface.btn_stop.setEnabled(True)

app.processEvents()
time.sleep(0.4)
app.processEvents()

# Chụp toàn bộ cửa sổ Qt sắc nét
pixmap = window.grab()
out_file = os.path.abspath(f"ux_{name_arg}_{theme_arg}.png")
pixmap.save(out_file, "PNG")
print(f"Đã lưu ảnh chụp: {out_file} ({pixmap.width()}x{pixmap.height()})")

window.close()
app.quit()
