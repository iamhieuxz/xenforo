"""Repro thực nghiệm cho test_theme_switch_and_persistence FAIL.

Trả lời đúng 1 câu hỏi: sau khi gọi _on_theme_changed(1), file theme và
load_theme_setting() thực sự ra gì?
"""
import os

from PySide6.QtWidgets import QApplication

import gui_fluent

HOME = os.path.join(os.path.expanduser("~"), ".xenforo_theme")
CWD = os.path.join(os.getcwd(), ".xenforo_theme")


def peek(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError as e:
        return f"<{type(e).__name__}>"


app = QApplication.instance() or QApplication([])

print("before init   home=%r cwd=%r" % (peek(HOME), peek(CWD)))
w = gui_fluent.MainWindow(auto_browser=False)
print("after  init   home=%r cwd=%r" % (peek(HOME), peek(CWD)))
print("theme_file_path ->", w._theme_file_path())
print("load_theme_setting ->", w.load_theme_setting())

si = w.settings_interface
si._on_theme_changed(1)
print("after set[1]  home=%r cwd=%r" % (peek(HOME), peek(CWD)))
print("load_theme_setting ->", w.load_theme_setting())

si._on_theme_changed(0)
print("after set[0]  home=%r cwd=%r" % (peek(HOME), peek(CWD)))
w.close()
app.processEvents()
