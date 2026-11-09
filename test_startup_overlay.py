"""Khóa hành vi màn hình chờ khởi động (StartupOverlay + MainWindow).

Điều đáng khóa: khi trình duyệt chưa sẵn sàng, nội dung app PHẢI bị vô hiệu
hóa; khi xong/bỏ qua/lỗi thì phải mở lại — nếu không người dùng bị kẹt ở màn
hình chờ hoặc thao tác được vào app lúc chưa có phiên trình duyệt.
"""

import unittest

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.startup_overlay import StartupOverlay


class TestStartupOverlay(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        w = MainWindow(auto_browser=False)
        self.addCleanup(w.close)
        return w

    def test_progress_then_error_state(self):
        ov = StartupOverlay(self._window())
        ov.start()
        self.assertTrue(ov.btn_skip.isHidden())

        ov.set_progress(55, "còn ~10s")
        self.assertEqual(ov.progress.value(), 55)
        self.assertIn("khởi động", ov.lbl_status.text())

        ov.finish_error("Cốc Cốc không mở cổng")
        self.assertFalse(ov.btn_skip.isHidden())
        self.assertEqual(ov.btn_skip.text(), "Tiếp tục")
        self.assertIn("Chưa mở được", ov.lbl_status.text())

    def test_content_blocked_until_overlay_closes(self):
        w = self._window()
        w._startup_pending = True
        w._show_startup_overlay()

        self.assertFalse(w.stackedWidget.isEnabled())
        self.assertFalse(w.sidebar.isEnabled())

        w._on_startup_status("success", "sẵn sàng", 100)
        w.startup_overlay.hide()
        self.assertTrue(w.stackedWidget.isEnabled())
        self.assertTrue(w.sidebar.isEnabled())

    def test_fast_error_still_shows_panel_once(self):
        w = self._window()
        w._startup_pending = True
        w._on_startup_status("error", "không tìm thấy trình duyệt", 100)

        self.assertIsNotNone(w.startup_overlay)
        self.assertEqual(w.startup_overlay.btn_skip.text(), "Tiếp tục")
        self.assertFalse(w.stackedWidget.isEnabled())

        w.startup_overlay._dismiss()
        self.assertTrue(w.stackedWidget.isEnabled())

        # Người dùng đã bỏ qua: lỗi tới sau không được bật lại panel.
        w._on_startup_status("error", "lỗi tới sau", 100)
        self.assertTrue(w.startup_overlay.isHidden())


if __name__ == "__main__":
    unittest.main()
