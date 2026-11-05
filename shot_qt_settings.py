"""Chụp ảnh trang Cài đặt (Settings View) của Fluent UI."""
import os
import sys
import time
from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme, Theme
import gui_fluent

app = QApplication(sys.argv)
setTheme(Theme.DARK)

window = gui_fluent.MainWindow()
window.resize(1100, 850)
window.show()

# Chuyển sang sub-interface Settings
window.switchTo(window.settings_interface)

app.processEvents()
time.sleep(0.4)
app.processEvents()

pixmap = window.grab()
out_file = os.path.abspath("ux_fluent_settings_dark.png")
pixmap.save(out_file, "PNG")
print(f"Đã lưu ảnh Settings: {out_file} ({pixmap.width()}x{pixmap.height()})")

window.close()
app.quit()
