"""Unit tests cho giao diện Fluent UI mới (gui_fluent.py).

Kiểm tra:
- Khởi tạo giao diện, nạp sub-interfaces và theme
- Khả năng tự thích ứng thư mục lưu trữ (_resolve_dir)
- Cơ chế Signal/Slot và phân tích thống kê log_bridge của CrawlWorker
- Tính đúng đắn của logic bật/tắt nút theo input (_check_inputs)
- Trạng thái khi đang quét và khi dừng khẩn cấp
- Bộ lọc và quản lý nhật ký
- Đóng cửa sổ và giải phóng tài nguyên an toàn (closeEvent)
"""

import os
import sys
import tempfile
import threading
import unittest

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

import config
import gui_fluent
from cache import MediaCache

# Khởi tạo QApplication singleton cho test
_app = QApplication.instance()
if _app is None:
    _app = QApplication(sys.argv)


class TestWorkerSignalsAndBridge(unittest.TestCase):
    """Kiểm tra CrawlWorker phân tích log và phát tín hiệu Signal chuẩn xác."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="worker_test_")
        self.cache = MediaCache(os.path.join(self.tmp_dir, "test.db"))
        self.stop_event = threading.Event()
        self.worker = gui_fluent.CrawlWorker(
            cache=self.cache,
            download_dir=self.tmp_dir,
            stop_event=self.stop_event,
            coro_factory=lambda eng: None
        )

    def tearDown(self):
        self.cache.close()
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_log_tag_detection(self):
        self.assertEqual(gui_fluent.detect_log_tag("[-] Lỗi kết nối"), "error")
        self.assertEqual(gui_fluent.detect_log_tag("[✓] Hoàn thành bài viết"), "success")
        # [+] là "thông tin tiến trình" — đã đổi từ success sang info ở đợt
        # chuẩn hoá tag log (log_view.py), vì [+] chỉ nói "tìm thấy", không
        # phải "hoàn thành".
        self.assertEqual(gui_fluent.detect_log_tag("[+] Tìm thấy 5 bài"), "info")
        self.assertEqual(gui_fluent.detect_log_tag("[!] Cảnh báo timeout"), "summary")
        self.assertEqual(gui_fluent.detect_log_tag("[•] Đã trùng khớp"), "skip")
        self.assertEqual(gui_fluent.detect_log_tag("[*] Đang bóc tách"), "system")
        self.assertEqual(gui_fluent.detect_log_tag("Dòng không dấu"), "dim")
        self.assertEqual(gui_fluent.detect_log_tag("[-] Custom", tag="bulk"), "bulk")

    def test_log_bridge_parses_stats_and_emits_signals(self):
        received_logs = []
        received_stats = []

        self.worker.signals.sig_log.connect(lambda msg, tag: received_logs.append((msg, tag)))
        self.worker.signals.sig_stats.connect(
            lambda img, vid, err, det: received_stats.append((img, vid, err, det))
        )

        self.worker.log_bridge("[✓] TACGIA: Bài 1 tải mới 8 ảnh và 2 video", "success")
        self.worker.log_bridge("   [!] Cảnh báo: 3 tệp lỗi đường truyền trong bài này.", "summary")

        self.assertEqual(len(received_logs), 2)
        self.assertEqual(received_logs[0][1], "success")
        self.assertEqual(received_logs[1][1], "summary")

        self.assertTrue(self.worker.had_error, "Dòng [!] phải kích hoạt had_error")
        self.assertEqual(self.worker._n_image, 8)
        self.assertEqual(self.worker._n_video, 2)
        self.assertEqual(self.worker._n_error, 3)
        # Dấu phân cách đã đổi từ "," sang "·" ở đợt dọn log — thống kê
        # hiển thị trên status bar của GUI, không phải chuỗi engine.
        self.assertIn("8 ảnh", self.worker._last_detail)
        self.assertIn("2 video", self.worker._last_detail)
        self.assertIn("3 tệp lỗi", self.worker._last_detail)

    def test_emergency_cleanup_sets_stop_event(self):
        self.assertFalse(self.stop_event.is_set())
        self.worker.emergency_cleanup()
        self.assertTrue(self.stop_event.is_set())


class TestMainWindowAndUIFlow(unittest.TestCase):
    """Kiểm tra luồng hoạt động, tương tác và dọn dẹp của MainWindow."""

    def setUp(self):
        self.window = gui_fluent.MainWindow(auto_browser=False)
        self.window.show()
        QApplication.processEvents()

    def tearDown(self):
        self.window.close()
        QApplication.processEvents()
        # Dọn file theme test nếu có tạo trong workspace
        local_theme = os.path.join(os.getcwd(), ".xenforo_theme")
        if os.path.exists(local_theme):
            try:
                os.remove(local_theme)
            except OSError:
                pass

    def test_window_initialization(self):
        self.assertIsNotNone(self.window.crawler_interface)
        self.assertIsNotNone(self.window.settings_interface)
        self.assertEqual(self.window.crawler_interface.objectName(), "crawlerInterface")
        self.assertEqual(self.window.settings_interface.objectName(), "settingsInterface")
        self.assertTrue(os.path.exists(self.window.download_dir))

    def test_input_validation_controls_buttons(self):
        ci = self.window.crawler_interface

        # Mặc định: box có sẵn preset, user có sẵn -> nút quét tác giả bật
        ci._check_inputs()
        self.assertTrue(ci.btn_crawl_user.isEnabled())
        self.assertTrue(ci.btn_crawl_all.isEnabled())
        # Ô link thớt trống -> nút quét thớt tắt
        self.assertFalse(ci.btn_crawl_thread.isEnabled())

        # Gõ link thớt -> nút quét thớt bật
        ci.ent_thread_url.setText("https://domain/threads/test.123/")
        self.assertTrue(ci.btn_crawl_thread.isEnabled())

        # Xoá ô box -> cả nút tác giả và nút quét all đều tắt
        ci.cmb_box_url.setText("")
        ci._check_inputs()
        self.assertFalse(ci.btn_crawl_user.isEnabled())
        self.assertFalse(ci.btn_crawl_all.isEnabled())

    def test_log_append_and_filtering(self):
        ci = self.crawler_interface = self.window.crawler_interface
        self.window.append_log("[*] Khởi động hệ thống", "system")
        self.window.append_log("[✓] Tải thành công ảnh 1", "success")
        self.window.append_log("[-] Lỗi máy chủ 500", "error")

        self.assertEqual(len(self.window.log_history), 3)

        # Lọc từ khoá 'Lỗi'
        ci.filter_edit.setText("lỗi")
        filtered_text = ci.log_edit.toPlainText()
        self.assertIn("Lỗi máy chủ", filtered_text)
        self.assertNotIn("Tải thành công", filtered_text)

        # Bỏ lọc -> hiện lại đủ
        ci.filter_edit.setText("")
        full_text = ci.log_edit.toPlainText()
        self.assertIn("Lỗi máy chủ", full_text)
        self.assertIn("Tải thành công", full_text)

        # Xoá log
        ci._clear_log()
        self.assertEqual(len(self.window.log_history), 0)
        self.assertEqual(ci.log_edit.toPlainText(), "")

    def test_running_state_ui_toggles(self):
        ci = self.window.crawler_interface

        self.window._set_ui_running(True, "Kiểm thử tác vụ")
        self.assertFalse(ci.btn_crawl_user.isEnabled())
        self.assertFalse(ci.btn_crawl_thread.isEnabled())
        self.assertFalse(ci.btn_crawl_all.isEnabled())
        self.assertTrue(ci.btn_stop.isEnabled())
        self.assertTrue(ci.progress_bar.isVisible())
        self.assertEqual(ci.lbl_state_title.text(), "ĐANG QUÉT")

        self.window._set_ui_running(False)
        self.assertFalse(ci.btn_stop.isEnabled())
        self.assertFalse(ci.progress_bar.isVisible())

    def test_theme_switch_and_persistence(self):
        si = self.window.settings_interface
        # Chuyển sang Light
        si.card_theme.hBoxLayout
        si._on_theme_changed(1)
        self.assertEqual(self.window.load_theme_setting(), "light")

        # Chuyển sang Dark
        si._on_theme_changed(0)
        self.assertEqual(self.window.load_theme_setting(), "dark")


class TestCopyLogButton(unittest.TestCase):
    """Hồi quy: nút "Sao chép" phải thật sự chép được, không ném NameError.

    VÌ SAO CÓ TEST NÀY: khi tách gui_fluent.py thành package ui/ (P2.1),
    module crawler_view.py dùng QApplication.clipboard() nhưng KHÔNG import
    QApplication. 261 test vẫn xanh vì không test nào gọi _copy_log, nên lỗi
    chỉ lộ ra khi người dùng bấm nút thật:

        AttributeError: module 'ui.crawler_view' has no attribute 'QApplication'

    Test dưới đây chốt cả hai tầng: (1) tên QApplication có trong namespace
    của module — bắt đúng lớp lỗi thiếu import, không phụ thuộc clipboard;
    (2) gọi _copy_log thật và đọc lại clipboard — bắt lỗi runtime.
    """

    def setUp(self):
        self.window = gui_fluent.MainWindow(auto_browser=False)
        self.ci = self.window.crawler_interface

    def tearDown(self):
        self.window.close()
        QApplication.processEvents()
        local_theme = os.path.join(os.getcwd(), ".xenforo_theme")
        if os.path.exists(local_theme):
            try:
                os.remove(local_theme)
            except OSError:
                pass

    def test_module_exposes_qapplication(self):
        """Thiếu import là gốc của lỗi — kiểm thẳng vào namespace module."""
        from ui import crawler_view
        self.assertTrue(
            hasattr(crawler_view, "QApplication"),
            "ui/crawler_view.py phải import QApplication vì _copy_log dùng nó")

    def test_copy_log_puts_text_on_clipboard(self):
        self.window.append_log("[*] Dòng cần sao chép", "system")
        self.ci._copy_log()

        clip = QApplication.clipboard().text()
        self.assertIn("Dòng cần sao chép", clip)

    def test_copy_log_on_empty_log_does_not_raise(self):
        """Nhật ký trống: phải đi nhánh cảnh báo, không được ném."""
        self.ci._clear_log()
        self.ci._copy_log()          # không assert nội dung, chỉ cần không ném
        self.assertEqual(self.ci.log_edit.toPlainText(), "")


if __name__ == "__main__":
    unittest.main()
