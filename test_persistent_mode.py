"""Test cho mode persistent và session_source.

Chạy: python -m unittest test_persistent_mode -v

Nguyên tắc: test những gì ĐO ĐƯỢC mà không cần mở trình duyệt thật, để suite
chạy nhanh và không phụ thuộc mạng. Phần mở trình duyệt thật nằm ở
probe_persistent_mode.py (chạy tay, có kết nối mạng).
"""

import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
import session_source as SS


class TestSessionProfileResolution(unittest.TestCase):
    """Profile phải CỐ ĐỊNH — đây là điều làm session sống qua các lần chạy."""

    def test_default_profile_is_stable_across_calls(self):
        a = SS.default_session_profile("chrome")
        b = SS.default_session_profile("chrome")
        self.assertEqual(a, b, "profile đổi tên giữa 2 lần gọi -> mất session")

    def test_default_profile_differs_per_browser(self):
        """Profile Chrome đưa cho Cốc Cốc sẽ hỏng dữ liệu -> phải tách."""
        chrome = SS.default_session_profile("chrome")
        coccoc = SS.default_session_profile("coccoc")
        self.assertNotEqual(chrome, coccoc)
        self.assertIn("chrome", chrome.lower())
        self.assertIn("coccoc", coccoc.lower())

    def test_explicit_profile_wins(self):
        old = config.SESSION_PROFILE
        tmp = tempfile.mkdtemp()
        try:
            config.SESSION_PROFILE = tmp
            self.assertEqual(
                os.path.normcase(SS.resolve_profile()),
                os.path.normcase(os.path.abspath(tmp)),
                "SESSION_PROFILE phải được ưu tiên")
        finally:
            config.SESSION_PROFILE = old
            shutil.rmtree(tmp, ignore_errors=True)

    def test_empty_profile_falls_back_to_default(self):
        old = config.SESSION_PROFILE
        try:
            config.SESSION_PROFILE = ""
            self.assertEqual(
                os.path.normcase(SS.resolve_profile("chrome")),
                os.path.normcase(SS.default_session_profile("chrome")))
        finally:
            config.SESSION_PROFILE = old


class TestProfileSafetyChecks(unittest.TestCase):
    """Kiểm trước khi mở: thiếu quyền ghi thì Chromium báo lỗi khó hiểu."""

    def test_writable_dir_detected(self):
        tmp = tempfile.mkdtemp()
        try:
            self.assertTrue(SS.profile_is_writable(tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_creates_missing_dir(self):
        base = tempfile.mkdtemp()
        target = os.path.join(base, "a", "b", "c")
        try:
            self.assertTrue(SS.profile_is_writable(target))
            self.assertTrue(os.path.isdir(target))
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_unwritable_path_reported(self):
        # Đường dẫn không hợp lệ trên Windows (\0) -> luôn thất bại
        self.assertFalse(SS.profile_is_writable("Z:\\khong\\ton\\tai\\\x00x"))

    def test_browser_running_returns_bool(self):
        for b in ("chrome", "coccoc", "edge"):
            self.assertIn(SS.is_browser_running(b), (True, False))

    def test_unknown_browser_not_running(self):
        self.assertFalse(SS.is_browser_running("khongtontai"))


class TestProfileDiscovery(unittest.TestCase):
    def test_find_installed_profiles_shape(self):
        found = SS.find_installed_profiles()
        self.assertIsInstance(found, dict)
        for name, info in found.items():
            self.assertIn("path", info)
            self.assertIn("exists", info)
            self.assertIn("has_cookies", info)
            self.assertTrue(os.path.isdir(info["path"]))

    def test_cookie_db_path_none_for_empty_dir(self):
        tmp = tempfile.mkdtemp()
        try:
            self.assertIsNone(SS.cookie_db_path(tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_read_cookie_summary_missing_profile(self):
        out = SS.read_cookie_summary(r"F:\khong\ton\tai\abc")
        self.assertFalse(out["ok"])
        self.assertIn("reason", out)


class TestCopyProfile(unittest.TestCase):
    """Copy phải báo rõ file nào bị bỏ, không im lặng tạo profile rỗng."""

    def _fake_profile(self, base):
        prof = os.path.join(base, "src")
        os.makedirs(os.path.join(prof, "Default", "Network"), exist_ok=True)
        os.makedirs(os.path.join(prof, "Default", "Cache"), exist_ok=True)
        with open(os.path.join(prof, "Default", "Network", "Cookies"), "wb") as f:
            f.write(b"cookie-data")
        with open(os.path.join(prof, "Default", "Preferences"), "w") as f:
            f.write("{}")
        with open(os.path.join(prof, "Default", "Cache", "big.bin"), "wb") as f:
            f.write(b"x" * 1000)
        return prof

    def test_copy_skips_cache(self):
        base = tempfile.mkdtemp()
        try:
            src = self._fake_profile(base)
            dst = os.path.join(base, "dst")
            r = SS.copy_profile(src, dst)
            self.assertTrue(r["ok"], r)
            self.assertTrue(os.path.isfile(
                os.path.join(dst, "Default", "Network", "Cookies")))
            self.assertTrue(os.path.isfile(
                os.path.join(dst, "Default", "Preferences")))
            # Cache phải bị bỏ qua
            self.assertFalse(os.path.isdir(os.path.join(dst, "Default", "Cache")),
                             "không được copy cache")
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_copy_refuses_when_dest_exists(self):
        base = tempfile.mkdtemp()
        try:
            src = self._fake_profile(base)
            dst = os.path.join(base, "dst")
            os.makedirs(dst)
            r = SS.copy_profile(src, dst)
            self.assertFalse(r["ok"])
            self.assertIn("đã tồn tại", r["reason"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_copy_missing_source(self):
        r = SS.copy_profile(r"F:\khong\ton\tai", tempfile.mkdtemp())
        self.assertFalse(r["ok"])


class TestEngineModeSelection(unittest.TestCase):
    """engine phải chọn đúng nhánh theo config.BROWSER_MODE."""

    def test_persistent_is_default(self):
        self.assertEqual(getattr(config, "BROWSER_MODE", None), "persistent")

    def test_engine_has_both_paths(self):
        import inspect
        import engine
        src = inspect.getsource(engine.CrawlerEngine)
        self.assertIn("_connect_persistent", src)
        self.assertIn("_connect_cdp", src)
        self.assertIn("close_browser", src)

    def test_connect_dispatches_on_mode(self):
        import inspect
        import engine
        src = inspect.getsource(engine.CrawlerEngine.connect)
        self.assertIn("BROWSER_MODE", src)
        self.assertIn("_connect_persistent", src)
        self.assertIn("_connect_cdp", src)

    def test_close_browser_is_noop_in_cdp_mode(self):
        import asyncio
        import engine
        e = engine.CrawlerEngine(cache=None, log=lambda *a, **k: None,
                                 stop_event=threading.Event())
        self.assertIsNone(e._browser)
        asyncio.run(e.close_browser())   # không được ném
        self.assertIsNone(e._browser)

    def test_engine_keeps_browser_reference(self):
        import inspect
        import engine
        src = inspect.getsource(engine.CrawlerEngine._connect_persistent)
        self.assertIn("_browser", src,
                      "phải giữ context để close_browser() đóng được")
        # Không đóng context thì tiến trình trình duyệt ở lại sau khi quét.
        self.assertIn("self._browser = ctx", src)


class TestBrowserLauncherForBrowser(unittest.TestCase):
    def test_finds_chrome_by_name(self):
        exe = __import__("browser_launcher").find_browser_for("chrome")
        if exe:
            self.assertIn("chrome", os.path.basename(exe).lower())

    def test_finds_coccoc_by_name(self):
        import browser_launcher as B
        exe = B.find_browser_for("coccoc")
        if exe:
            self.assertEqual(os.path.basename(exe).lower(), "browser.exe")

    def test_unknown_returns_none(self):
        import browser_launcher as B
        self.assertIsNone(B.find_browser_for("khongtontai"))

    def test_does_not_mix_browsers(self):
        """find_browser_for('chrome') không được trả Cốc Cốc."""
        import browser_launcher as B
        exe = B.find_browser_for("chrome")
        if exe:
            self.assertNotIn("coccoc", exe.lower(),
                             "profile Chrome đưa cho Cốc Cốc sẽ hỏng dữ liệu")


if __name__ == "__main__":
    unittest.main()
