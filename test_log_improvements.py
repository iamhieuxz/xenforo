"""Test hồi quy cho cải thiện log terminal (2026-11-08).

Kiểm tra:
  1. Session stats accumulator cộng dồn đúng qua nhiều thread
  2. _report_thread in ký hiệu [▶] cho file mới, [◦] cho file cũ
  3. _banner in tổng kết cuối phiên với đủ số liệu
  4. Màu log "new" và "cached" tồn tại trong cả 2 theme và pass WCAG
  5. Marker regex nhận diện ▶ và ◦

Chạy: python -m unittest test_log_improvements -v
"""

from test_common import setUpModule, tearDownModule, soup_of  # noqa: F401

import os
import re
import shutil
import tempfile
import threading
import unittest

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config


class TestSessionStatsAccumulator(unittest.TestCase):
    """Bộ đếm tổng phiên phải cộng dồn đúng qua nhiều _accumulate_session."""

    def _engine(self):
        import engine as E
        e = E.CrawlerEngine(cache=None, log=lambda *a, **k: None,
                            stop_event=threading.Event())
        return e

    def test_reset_zeros_all_fields(self):
        e = self._engine()
        e._session_stats["new_image"] = 99
        e._session_stats["cached"] = 50
        e._reset_session_stats()
        for v in e._session_stats.values():
            self.assertEqual(v, 0)

    def test_accumulate_adds_correctly(self):
        e = self._engine()
        e._reset_session_stats()
        # Thread 1: 5 ảnh mới, 2 video mới, thấy 10 media tổng → 3 cached
        e._accumulate_session(
            {"ok": 7, "failed": 0, "image": 5, "video": 2, "file": 0},
            {"images": 8, "videos": 2, "files": 0})
        self.assertEqual(e._session_stats["new_image"], 5)
        self.assertEqual(e._session_stats["new_video"], 2)
        self.assertEqual(e._session_stats["cached"], 3)  # 10 seen - 7 ok
        self.assertEqual(e._session_stats["threads_done"], 1)

        # Thread 2: 3 ảnh mới, 1 file mới, thấy 6 media → 2 cached
        e._accumulate_session(
            {"ok": 4, "failed": 1, "image": 3, "video": 0, "file": 1},
            {"images": 4, "videos": 0, "files": 2})
        self.assertEqual(e._session_stats["new_image"], 8)   # 5+3
        self.assertEqual(e._session_stats["new_video"], 2)   # 2+0
        self.assertEqual(e._session_stats["new_file"], 1)    # 0+1
        self.assertEqual(e._session_stats["cached"], 5)      # 3+2
        self.assertEqual(e._session_stats["failed"], 1)
        self.assertEqual(e._session_stats["threads_done"], 2)

    def test_cached_never_negative(self):
        """Nếu ok > seen (edge case), cached không được âm."""
        e = self._engine()
        e._reset_session_stats()
        e._accumulate_session(
            {"ok": 10, "image": 10, "video": 0, "file": 0},
            {"images": 5, "videos": 0, "files": 0})
        self.assertEqual(e._session_stats["cached"], 0)


class TestReportThreadFormat(unittest.TestCase):
    """_report_thread phải in [▶] cho file mới, [◦] cho file cũ."""

    def _engine_with_log(self):
        import engine as E
        lines = []
        e = E.CrawlerEngine(cache=None, log=lambda m, t=None: lines.append((m, t)),
                            stop_event=threading.Event())
        e._reset_session_stats()
        return e, lines

    def test_new_files_use_marker_and_tag(self):
        e, lines = self._engine_with_log()
        e._report_thread("testuser", 1,
                         {"ok": 5, "failed": 0, "image": 3, "video": 2, "file": 0},
                         {"images": 5, "videos": 2, "files": 0, "author_posts": 3,
                          "other_posts": 1, "pages": 1, "folder": None})
        new_lines = [(m, t) for m, t in lines if "[▶]" in m]
        self.assertTrue(new_lines, "phải có dòng [▶] khi tải mới")
        self.assertIn("TẢI MỚI", new_lines[0][0])
        self.assertEqual(new_lines[0][1], "new", "tag phải là 'new'")

    def test_cached_files_use_marker_and_tag(self):
        e, lines = self._engine_with_log()
        e._report_thread("testuser", 1,
                         {"ok": 0, "failed": 0, "image": 0, "video": 0, "file": 0},
                         {"images": 5, "videos": 3, "files": 0, "author_posts": 2,
                          "other_posts": 0, "pages": 1, "folder": None})
        cached_lines = [(m, t) for m, t in lines if "[◦]" in m]
        self.assertTrue(cached_lines, "phải có dòng [◦] khi đã có sẵn")
        self.assertIn("đã có sẵn", cached_lines[0][0])
        self.assertEqual(cached_lines[0][1], "cached", "tag phải là 'cached'")

    def test_no_media_shows_cached_marker(self):
        e, lines = self._engine_with_log()
        e._report_thread("testuser", 1,
                         {"ok": 0, "failed": 0, "image": 0, "video": 0, "file": 0},
                         {"images": 0, "videos": 0, "files": 0, "author_posts": 1,
                          "other_posts": 0, "pages": 1, "folder": None})
        cached_lines = [m for m, t in lines if "[◦]" in m]
        self.assertTrue(cached_lines, "không có media vẫn hiện [◦]")
        self.assertIn("không có media", cached_lines[0])


class TestBannerSummary(unittest.TestCase):
    """_banner phải in tổng kết cuối phiên."""

    def _engine_with_log(self):
        import engine as E
        lines = []
        e = E.CrawlerEngine(cache=None, log=lambda m, t=None: lines.append((m, t)),
                            stop_event=threading.Event())
        e._reset_session_stats()
        return e, lines

    def test_banner_includes_summary_when_threads_done(self):
        e, lines = self._engine_with_log()
        e._session_stats.update({
            "new_image": 12, "new_video": 3, "new_file": 1,
            "cached": 20, "failed": 2, "threads_done": 5})
        e._banner(True, "TEST")
        text = "\n".join(m for m, t in lines)
        self.assertIn("Tải mới:", text)
        self.assertIn("12 ảnh", text)
        self.assertIn("3 video", text)
        self.assertIn("Đã có sẵn: 20", text)
        self.assertIn("Lỗi:      2", text)
        self.assertIn("5 bài đã xử lý", text)

    def test_banner_no_summary_when_no_threads(self):
        """Không in tổng kết khi chưa xử lý thread nào (ví dụ: lỗi kết nối)."""
        e, lines = self._engine_with_log()
        e._banner(False, "TEST")
        text = "\n".join(m for m, t in lines)
        self.assertNotIn("Tải mới:", text)
        self.assertIn("GIÁN ĐOẠN", text)


class TestNewLogColors(unittest.TestCase):
    """Màu 'new' và 'cached' phải tồn tại trong cả 2 theme và pass WCAG AA."""

    def test_both_themes_have_new_and_cached(self):
        from v72 import PALETTE
        for theme in ("light", "warm"):
            self.assertIn("new", PALETTE[theme]["LOG"], f"{theme}: thiếu màu 'new'")
            self.assertIn("cached", PALETTE[theme]["LOG"], f"{theme}: thiếu màu 'cached'")

    def test_new_and_cached_pass_wcag(self):
        """Chạy _check_palette để xác nhận tất cả màu log đạt WCAG AA."""
        import subprocess
        r = subprocess.run(
            [sys.executable, "_check_palette.py"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30, cwd=os.path.dirname(__file__))
        self.assertEqual(r.returncode, 0,
                         f"WCAG check failed:\n{r.stdout}\n{r.stderr}")

    def test_marker_regex_matches_new_markers(self):
        from v72 import _MARKER_RE, _MARKER_TAGS
        self.assertIsNotNone(_MARKER_RE.match("   [▶] Tải mới 5 ảnh"))
        self.assertIsNotNone(_MARKER_RE.match("   [◦] Đã có sẵn 3 media"))
        self.assertEqual(_MARKER_TAGS["▶"], "new")
        self.assertEqual(_MARKER_TAGS["◦"], "cached")

    def test_log_tag_detects_new_and_cached(self):
        from v72 import log_tag
        self.assertEqual(log_tag("   [▶] TẢI MỚI 5 ảnh"), "new")
        self.assertEqual(log_tag("   [◦] Đã có sẵn 3 media"), "cached")


if __name__ == "__main__":
    unittest.main()
