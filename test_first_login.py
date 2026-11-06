"""Test cho first-run login và tối ưu bộ nhớ.

Chạy: python -m unittest test_first_login -v

Bối cảnh: người dùng báo "nếu chưa có cookie hay session thì hãy mở 1 phiên
đăng nhập đầu tiên, sau đó chạy ẩn" và "chạy xong treo, lag, chiếm quá nhiều
bộ nhớ". Hai nhóm test dưới đây khoá lại cả hai yêu cầu đó.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
import session_source as SS


class TestLoginCookieDetection(unittest.TestCase):
    """Căn cứ để quyết định có mở phiên đăng nhập đầu tiên hay không."""

    def _profile_with_cookies(self, base, rows):
        """Tạo profile giả có bảng cookies đúng schema Chrome."""
        import sqlite3
        prof = os.path.join(base, "profile")
        net = os.path.join(prof, "Default", "Network")
        os.makedirs(net, exist_ok=True)
        db = os.path.join(net, "Cookies")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT)")
        conn.executemany("INSERT INTO cookies VALUES (?,?,?)", rows)
        conn.commit()
        conn.close()
        return prof

    def test_detects_login_cookie(self):
        base = tempfile.mkdtemp()
        try:
            prof = self._profile_with_cookies(
                base, [("rphang.beer", "xf_user", "123")])
            self.assertTrue(SS.has_login_session(prof, SS.FORUM_HOST_HINTS))
            need, why = SS.needs_first_login(prof)
            self.assertFalse(need, f"đã có xf_user nhưng vẫn đòi đăng nhập: {why}")
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_no_cookie_means_login_needed(self):
        base = tempfile.mkdtemp()
        try:
            prof = self._profile_with_cookies(
                base, [("rphang.beer", "xf_csrf", "abc")])
            self.assertFalse(SS.has_login_session(prof, SS.FORUM_HOST_HINTS))
            need, why = SS.needs_first_login(prof)
            self.assertTrue(need, "thiếu xf_user thì phải yêu cầu đăng nhập")
            self.assertIn("xf_user", why)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_missing_profile_needs_login(self):
        need, _ = SS.needs_first_login(r"F:\khong\ton\tai\xyz")
        self.assertTrue(need)

    def test_empty_cookie_table_needs_login(self):
        base = tempfile.mkdtemp()
        try:
            prof = self._profile_with_cookies(base, [])
            need, _ = SS.needs_first_login(prof)
            self.assertTrue(need)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_cookie_on_other_host_still_counts_without_filter(self):
        """xf_user ở host khác vẫn là phiên đăng nhập nếu không lọc host."""
        base = tempfile.mkdtemp()
        try:
            prof = self._profile_with_cookies(
                base, [("example.com", "xf_user", "1")])
            self.assertTrue(SS.has_login_session(prof))
            # Có lọc host thì không tính
            self.assertFalse(SS.has_login_session(prof, SS.FORUM_HOST_HINTS))
        finally:
            shutil.rmtree(base, ignore_errors=True)


class TestGuiLoginGate(unittest.TestCase):
    """GUI phải chặn quét khi chưa đăng nhập, thay vì chạy ẩn rồi thất bại."""

    def test_gui_has_ensure_login(self):
        import inspect
        import gui_fluent
        self.assertTrue(hasattr(gui_fluent.MainWindow, "_ensure_login"))
        src = inspect.getsource(gui_fluent.MainWindow._ensure_login)
        self.assertIn("needs_first_login", src)
        self.assertIn("_open_login_window", src)

    def test_all_crawl_entrypoints_check_login(self):
        """Ba nút quét đều phải gọi _ensure_login trước khi chạy."""
        import inspect
        import gui_fluent
        for fn in ("start_author_crawl", "start_thread_crawl", "start_all_crawl"):
            src = inspect.getsource(getattr(gui_fluent.MainWindow, fn))
            self.assertIn("_ensure_login", src,
                          f"{fn} không kiểm phiên đăng nhập")

    def test_login_watch_polls_profile(self):
        """Sau khi mở cửa sổ đăng nhập, app phải tự phát hiện khi xong."""
        import inspect
        import gui_fluent
        # Hàm nằm ở SettingsInterface (nơi có thẻ Đăng nhập + InfoBar).
        self.assertTrue(hasattr(gui_fluent.SettingsInterface, "_start_login_watch"))
        src = inspect.getsource(gui_fluent.SettingsInterface._start_login_watch)
        self.assertIn("needs_first_login", src)
        self.assertIn("QTimer", src)

    def test_ensure_login_does_not_crash_when_no_session(self):
        """LỖI ĐÃ SỬA: _ensure_login gọi self._open_login_window, nhưng hàm đó
        nằm ở SettingsInterface chứ không phải MainWindow -> AttributeError
        đúng vào lần chạy đầu tiên, khi người dùng chưa có cookie.

        Test này GỌI THẬT _ensure_login với profile trống, không chỉ grep.
        """
        from PySide6.QtWidgets import QApplication
        import gui_fluent

        old_dir = config.DOWNLOAD_DIR
        old_prof = config.SESSION_PROFILE
        old_mode = config.BROWSER_MODE
        tmp = tempfile.mkdtemp(prefix="nologin_")
        opened = {"n": 0}
        try:
            config.DOWNLOAD_DIR = tmp
            config.SESSION_PROFILE = tmp      # profile trống -> chưa đăng nhập
            # Ép mode persistent để _ensure_login đọc config.SESSION_PROFILE.
            # Ở mode cdp nó đọc profile của browser_launcher, không phải tmp.
            config.BROWSER_MODE = "persistent"
            app = QApplication.instance() or QApplication([])
            w = gui_fluent.MainWindow(auto_browser=False)
            try:
                # Chặn việc mở trình duyệt thật nhưng đếm số lần được gọi.
                def spy(wait_for_login=False):
                    opened["n"] += 1

                w.settings_interface._open_login_window = spy
                allowed = w._ensure_login()     # <-- gọi thật
                self.assertFalse(allowed, "chưa đăng nhập thì không được cho quét")
                self.assertEqual(opened["n"], 1,
                                 "phải mở cửa sổ đăng nhập đầu tiên")
            finally:
                w.close()
                app.processEvents()
        finally:
            config.DOWNLOAD_DIR = old_dir
            config.SESSION_PROFILE = old_prof
            config.BROWSER_MODE = old_mode
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ensure_login_allows_when_session_exists(self):
        """Đã có xf_user thì cho quét, không mở cửa sổ."""
        import sqlite3
        from PySide6.QtWidgets import QApplication
        import gui_fluent

        old_dir = config.DOWNLOAD_DIR
        old_prof = config.SESSION_PROFILE
        old_mode = config.BROWSER_MODE
        config.BROWSER_MODE = "persistent"
        tmp = tempfile.mkdtemp(prefix="haslogin_")
        opened = {"n": 0}
        try:
            net = os.path.join(tmp, "Default", "Network")
            os.makedirs(net, exist_ok=True)
            conn = sqlite3.connect(os.path.join(net, "Cookies"))
            conn.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT)")
            conn.execute("INSERT INTO cookies VALUES ('rphang.beer','xf_user','1')")
            conn.commit()
            conn.close()

            config.DOWNLOAD_DIR = tmp
            config.SESSION_PROFILE = tmp
            app = QApplication.instance() or QApplication([])
            w = gui_fluent.MainWindow(auto_browser=False)
            try:
                w.settings_interface._open_login_window = (
                    lambda wait_for_login=False:
                    opened.__setitem__("n", opened["n"] + 1))
                self.assertTrue(w._ensure_login(), "đã có session thì phải cho quét")
                self.assertEqual(opened["n"], 0,
                                 "không được mở cửa sổ khi đã có session")
            finally:
                w.close()
                app.processEvents()
        finally:
            config.DOWNLOAD_DIR = old_dir
            config.SESSION_PROFILE = old_prof
            config.BROWSER_MODE = old_mode
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class TestCdpBrowserSelection(unittest.TestCase):
    """LỖI ĐÃ SỬA: launch() mở NHẦM trình duyệt.

    find_browser() trả ứng viên ĐẦU TIÊN trong danh sách, mà danh sách xếp Cốc
    Cốc trước Chrome. Nên bấm Quét thì app mở một cửa sổ Cốc Cốc trắng bên cạnh
    trình duyệt người dùng đang dùng — đúng cái "một đống bùi nhùi".
    """

    def test_cdp_browser_config_exists(self):
        """CDP_BROWSER phải là một trong các trình duyệt hỗ trợ.

        Mặc định hiện là "coccoc" vì người dùng muốn dùng phiên Cốc Cốc có sẵn
        (783 cookie, có xf_user cho rphang.show). Đổi qua env V72_CDP_BROWSER.
        """
        self.assertTrue(hasattr(config, "CDP_BROWSER"))
        self.assertIn(config.CDP_BROWSER, ("chrome", "coccoc", "edge"))

    def _capture_launch(self, **kwargs):
        """Chạy launch() với Popen giả, trả đường dẫn exe sẽ được gọi."""
        import browser_launcher as B

        captured = {}

        class FakePopen:
            def __init__(self, args, **kw):
                captured["exe"] = args[0]
                self.pid = 999
                self.returncode = None

            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self, timeout=None):
                pass

            def kill(self):
                pass

        real_popen = B.subprocess.Popen
        real_probe = B.probe_port
        B.subprocess.Popen = FakePopen
        B.probe_port = lambda *a, **k: {"state": "closed", "detail": "", "version": None}
        try:
            B.launch(wait_seconds=0.2, **kwargs)
        finally:
            B.subprocess.Popen = real_popen
            B.probe_port = real_probe
        return captured.get("exe", "")

    def test_launch_picks_configured_browser_not_first_candidate(self):
        """launch() phải mở ĐÚNG trình duyệt trong config.CDP_BROWSER.

        Lỗi gốc: launch() gọi find_browser() trần, hàm này trả ứng viên ĐẦU TIÊN
        trong danh sách (Cốc Cốc đứng trước Chrome) nên mở nhầm trình duyệt.
        Test này kiểm launch() theo config, không hard-code tên trình duyệt.
        """
        import browser_launcher as B
        want = (config.CDP_BROWSER or "chrome").lower()
        if not B.find_browser_for(want):
            self.skipTest(f"máy không có {want}")

        exe = self._capture_launch()
        self.assertTrue(exe, "launch() không gọi Popen")

        # Phải là đúng loại trong config, KHÔNG phải "ứng viên đầu danh sách".
        expect = B.find_browser_for(want)
        self.assertEqual(os.path.normcase(exe), os.path.normcase(expect),
                         f"launch() mở {exe}, phải mở {expect}")

        # Và phải KHÁC ứng viên đầu danh sách nếu chúng khác nhau
        first = B.find_browser()
        if first and os.path.normcase(first) != os.path.normcase(expect):
            self.assertNotEqual(os.path.normcase(exe), os.path.normcase(first),
                                "launch() quay lại lỗi 'lấy ứng viên đầu danh sách'")

    def test_launch_respects_browser_argument(self):
        """Truyền browser= cụ thể phải thắng config."""
        import browser_launcher as B
        if not B.find_browser_for("coccoc"):
            self.skipTest("máy không có Cốc Cốc")
        exe = self._capture_launch(browser="coccoc")
        self.assertIn("coccoc", exe.lower())


class TestMemoryOptimizations(unittest.TestCase):
    """Các nút chỉnh để giảm RAM và độ trễ."""

    def test_log_limit_is_bounded(self):
        """Chi phí QTextEdit tỉ lệ với độ dài; trần phải đủ nhỏ."""
        import gui_fluent
        limit = gui_fluent.CrawlerInterface.LOG_MAX_CHARS
        self.assertLessEqual(limit, 40_000,
                             f"trần {limit} ký tự quá lớn -> log chậm dần")
        self.assertGreaterEqual(limit, 8_000,
                                "trần quá nhỏ thì không đọc lại được")

    def test_trim_uses_char_count_not_block_count(self):
        """insertHtml không tạo paragraph -> blockCount luôn 1, không dùng được."""
        import inspect
        import gui_fluent
        src = inspect.getsource(gui_fluent.CrawlerInterface._trim_log)
        # Kiểm CODE, không kiểm docstring (docstring có nhắc blockCount để giải thích).
        body = src.split('"""')[-1]   # chỉ kiểm phần code sau docstring
        self.assertIn("characterCount", body)
        self.assertNotIn("blockCount", body,
                         "đếm block không hoạt động với insertHtml")

    def test_resource_blocking_configurable(self):
        self.assertTrue(hasattr(config, "BLOCK_IMAGES"))
        self.assertTrue(hasattr(config, "BLOCK_FONTS"))

    def test_image_blocking_does_not_break_parser(self):
        """Chặn ảnh KHÔNG được làm mất media: parser đọc DOM, không đọc ảnh."""
        import inspect
        import engine
        src = inspect.getsource(engine.CrawlerEngine._install_resource_blocker)
        # Chỉ chặn image/font, KHÔNG chặn document/script/xhr
        self.assertIn('"image"', src)
        self.assertNotIn('"document"', src,
                         "chặn document sẽ làm mất HTML cần bóc")
        self.assertNotIn('"script"', src,
                         "chặn script sẽ làm hỏng lazy-load của XenForo")

    def test_worker_released_after_finish(self):
        """QThread giữ closure + engine; không giải phóng là rò rỉ."""
        import inspect
        import gui_fluent
        self.assertTrue(hasattr(gui_fluent.MainWindow, "_release_worker"))
        src = inspect.getsource(gui_fluent.MainWindow._release_worker)
        self.assertIn("deleteLater", src)
        self.assertIn("self.worker = None", src)


if __name__ == "__main__":
    unittest.main()