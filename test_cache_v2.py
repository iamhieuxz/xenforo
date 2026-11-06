"""Test cho cache + chỉ mục local user. Tách từ test_v72.py (P2.2).

setUpModule/tearDownModule và soup_of lấy từ test_common
(chung cơ chế cô lập cho mọi file tách từ test_v72).
"""

from test_common import setUpModule, tearDownModule, soup_of  # noqa: F401

import os
import re
import shutil
import tempfile
import threading
import unittest

import asyncio

from bs4 import BeautifulSoup

import config
import xf_selectors as S
import xenforo_parse as X
import downloader
from downloader import (Downloader, backoff_seconds, plan_jobs, url_hash,
                        count_files, index_folder)
import engine
from cache import MediaCache, LocalUserIndex
import fast_fetch
import browser_launcher as B


import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')


class TestMediaCache(unittest.TestCase):
    def test_absolute_path_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, 'a.jpg')
            with open(f, 'wb') as fh:
                fh.write(b'x')
            c = MediaCache(os.path.join(d, 'c.db'))
            h = url_hash('http://x/a.jpg')
            c.record(h, f)
            self.assertEqual(c.path_for(h), os.path.abspath(f))
            c.close()

    def test_legacy_basename_row_is_ignored(self):
        """Cache cũ lưu basename -> phải bị bỏ qua thay vì dựng sai đường dẫn."""
        with tempfile.TemporaryDirectory() as d:
            c = MediaCache(os.path.join(d, 'c.db'))
            # Nêu TÊN CỘT, không dùng VALUES (?,?,?): bảng có thêm cột
            # content_hash nên chèn theo vị trí sẽ hỏng ("table has 4 columns
            # but 3 values supplied"). Dòng cũ để content_hash NULL — đúng như
            # dữ liệu thật trước khi có cột này.
            c.conn.execute(
                "INSERT OR REPLACE INTO media_index "
                "(url_clean_hash, filename, downloaded_at) VALUES (?,?,?)",
                ('legacy', 'a.jpg', '2020'))
            c.conn.commit()
            self.assertIsNone(c.path_for('legacy'), "dữ liệu cũ kiểu basename phải bị bỏ qua")
            c.close()

    def test_missing_file_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            c = MediaCache(os.path.join(d, 'c.db'))
            c.record('h1', os.path.join(d, 'khong-ton-tai.jpg'))
            self.assertIsNone(c.path_for('h1'), "file không còn thì phải tải lại")
            c.close()


class TestLocalUserIndex(unittest.TestCase):
    """Danh sách user local phải nạp 1 lần, sau đó đọc từ DB."""

    def _index(self, folder):
        c = MediaCache(os.path.join(folder, "c.db"))
        return c, LocalUserIndex(c.conn)

    def test_refresh_then_read(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("Zeta", "alpha", "Beta"):
                os.makedirs(os.path.join(d, n))
            c, idx = self._index(d)
            self.assertEqual(idx.refresh(d), 3)
            self.assertEqual(idx.names(), ["alpha", "Beta", "Zeta"],
                             "phải sắp xếp A-Z không phân biệt hoa thường")
            c.close()

    def test_pycache_is_not_a_user(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "__pycache__"))
            os.makedirs(os.path.join(d, "real_user"))
            c, idx = self._index(d)
            idx.refresh(d)
            self.assertEqual(idx.names(), ["real_user"])
            c.close()

    def test_deleted_folder_marked_stale_not_dropped(self):
        """Xoá folder trên ổ phải còn row (đánh dấu stale), không mất lịch sử."""
        with tempfile.TemporaryDirectory() as d:
            for n in ("keep", "gone"):
                os.makedirs(os.path.join(d, n))
            c, idx = self._index(d)
            idx.refresh(d)
            os.rmdir(os.path.join(d, "gone"))
            idx.refresh(d)
            self.assertEqual(idx.names(), ["keep"], "folder đã xoá không được ở danh sách active")
            self.assertEqual(idx.stale_names(), ["gone"], "phải giữ lại để bạn biết mất gì")
            c.close()

    def test_second_open_reads_db_without_rescanning(self):
        """Lần mở app sau phải đọc DB, không quét ổ - đó là lý do có bảng này."""
        with tempfile.TemporaryDirectory() as d:
            for n in ("a", "b"):
                os.makedirs(os.path.join(d, n))
            c, idx = self._index(d)
            idx.refresh(d)
            c.close()

            c2, idx2 = self._index(d)
            # Xoá ổ sau khi nạp: đọc DB vẫn phải ra dữ liệu đã nạp.
            os.rmdir(os.path.join(d, "a"))
            self.assertEqual(idx2.names(), ["a", "b"],
                             "phải đọc được từ DB dù ổ đã thay đổi")
            c2.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)


class TestThreadDateFallbacks(unittest.TestCase):
    """Ngày mở thread phải tìm được ở nhiều nguồn, không chỉ một selector.

    Bug thật: `thread_meta` chỉ thử `.p-description time.u-dt`. Server không trả
    thẻ đó là ra "0000-00-00", folder thành "[0000-00-00] ...", và vì tên folder
    khác nhau giữa các lần quét nên app coi là bài mới -> tải lại toàn bộ dù file
    đã nằm trên đĩa. Trên đĩa thật đã đo được: 11/11 folder đều là [0000-00-00].
    """

    def _meta(self, html):
        return X.thread_meta(soup_of(html))

    def test_primary_source_still_wins(self):
        html = ('<div class="p-description"><time class="u-dt" data-time="1700000000">'
                '</time></div><h1 class="p-title-value">A</h1>')
        self.assertEqual(self._meta(html)[1], '2023-11-15')

    def test_falls_back_to_time_in_post(self):
        """Thiếu .p-description nhưng post có <time> -> phải lấy được ngày."""
        html = ('<h1 class="p-title-value">A</h1>'
                '<article class="message--post" data-author="a">'
                '<header class="message-attribution">'
                '<time class="u-dt" data-time="1700000000"></time></header></article>')
        self.assertEqual(self._meta(html)[1], '2023-11-15',
                         "không được ra 0000-00-00 khi vẫn còn nguồn khác")

    def test_falls_back_to_meta_tag(self):
        html = ('<html><head><meta property="article:published_time" '
                'content="2023-11-14T22:13:20+00:00"></head><body>'
                '<h1 class="p-title-value">A</h1></body></html>')
        self.assertEqual(self._meta(html)[1], '2023-11-14')

    def test_falls_back_to_datetime_attribute(self):
        """XenForo có build dùng `datetime` ISO thay vì `data-time` epoch."""
        html = ('<h1 class="p-title-value">A</h1>'
                '<div class="p-description">'
                '<time datetime="2023-11-14T22:13:20+0000"></time></div>')
        self.assertEqual(self._meta(html)[1], '2023-11-14')

    def test_no_source_at_all_gives_stable_label(self):
        """Không có nguồn nào: phải là nhãn ỔN ĐỊNH, không phải 0000 cũng không rỗng."""
        html = '<h1 class="p-title-value">A</h1>'
        date_prefix = self._meta(html)[1]
        self.assertEqual(date_prefix, "", "không có ngày thì trả rỗng")
        folder = X.thread_folder(r'F:\base', 'u', 'A', date_prefix)
        self.assertIn('khong-ngay', folder)
        self.assertNotIn('0000', folder)
        # Gọi lại phải ra y hệt -> folder không đổi tên giữa các lần quét.
        self.assertEqual(folder, X.thread_folder(r'F:\base', 'u', 'A', self._meta(html)[1]))

    def test_zero_date_never_appears(self):
        for html in ('<h1 class="p-title-value">A</h1>',
                     '<div class="p-description"><time>?</time></div>'
                     '<h1 class="p-title-value">A</h1>'):
            self.assertNotIn('0000', self._meta(html)[1],
                             f"không được sinh ra 0000: {html[:40]}")


class TestThreadDateIsRemembered(unittest.TestCase):
    """Ngày đã biết phải được lưu lại, để folder không đổi khi server quên ngày."""

    def test_remember_then_read(self):
        with tempfile.TemporaryDirectory() as d:
            c = MediaCache(os.path.join(d, 'c.db'))
            self.assertIsNone(c.thread_date('thread-1'))
            c.remember_thread_date('thread-1', '2023-11-15', r'F:\base\u\[2023-11-15] A')
            self.assertEqual(c.thread_date('thread-1'), '2023-11-15')
            c.close()

    def test_empty_date_does_not_overwrite_known_date(self):
        """Lần quét sau server không trả ngày -> KHÔNG được xoá ngày đã biết."""
        with tempfile.TemporaryDirectory() as d:
            c = MediaCache(os.path.join(d, 'c.db'))
            c.remember_thread_date('t', '2023-11-15', 'folder1')
            c.remember_thread_date('t', '', 'folder1')
            self.assertEqual(c.thread_date('t'), '2023-11-15',
                             "ngày đã biết không được bị ghi đè bằng rỗng")
            c.close()

    def test_new_date_does_update(self):
        with tempfile.TemporaryDirectory() as d:
            c = MediaCache(os.path.join(d, 'c.db'))
            c.remember_thread_date('t', '2023-11-15', 'f')
            c.remember_thread_date('t', '2024-01-02', 'f')
            self.assertEqual(c.thread_date('t'), '2024-01-02')
            c.close()

    def test_remember_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            c = MediaCache(os.path.join(d, 'c.db'))
            for _ in range(3):
                c.remember_thread_date('t', '2023-11-15', 'f')
            rows = c.conn.execute("SELECT COUNT(*) FROM thread_index").fetchone()[0]
            self.assertEqual(rows, 1, "phải upsert, không tạo nhiều dòng")
            c.close()


class TestFolderIndexPreventsDuplicates(unittest.TestCase):
    """Quét lại khi tên file đổi KHÔNG được tạo bản sao thứ hai.

    Bug thật đo được: lần 1 server có timestamp -> tên
    `[20231115_051320]_media_001_a_0d27d9.jpg`. Lần 2 server mất timestamp ->
    tên `[khong-gio]_media_001_a_0d27d9.jpg`. Hash giống nhưng tên khác, nên
    `os.path.exists(save_path)` sai và cache clone ra file thứ hai: 3 -> 6 file.
    """

    def _make(self, urls, folder, ts):
        return plan_jobs(urls, folder, ts, 'image')

    def test_index_folder_finds_existing_files(self):
        from downloader import index_folder
        with tempfile.TemporaryDirectory() as d:
            for name, data in (('[20231115_051320]_media_001_a_0d27d9.jpg', b'x'),
                               ('[khong-gio]_media_002_b_3c0170.jpg', b'y')):
                with open(os.path.join(d, name), 'wb') as f:
                    f.write(data)
            with open(os.path.join(d, 'readme.txt'), 'wb') as f:
                f.write(b'z')
            idx = index_folder(d)
            self.assertIn('0d27d9', idx)
            self.assertIn('3c0170', idx)
            self.assertEqual(len(idx), 2, "file không đúng mẫu tên phải bị bỏ qua")

    def test_index_on_missing_folder_is_empty(self):
        from downloader import index_folder
        self.assertEqual(index_folder(r'F:\khong\ton\tai\abc'), {})

    def test_same_url_different_timestamp_yields_same_hash(self):
        """Cùng URL phải cùng hash dù timestamp khác — đó là cơ sở để chống trùng."""
        a = self._make(['http://x/m/a.jpg'], r'F:\f', '20231115_051320')[0]
        b = self._make(['http://x/m/a.jpg'], r'F:\f', 'khong-gio')[0]
        self.assertNotEqual(a[1], b[1], "tên file khác nhau (đúng như bug)")
        self.assertEqual(a[2], b[2], "nhưng hash phải giống nhau")

    def test_dispatch_skips_when_folder_index_has_hash(self):
        """Đã có trong folder dưới tên khác -> không tạo task, không tạo file mới."""
        import asyncio
        from downloader import Downloader, index_folder

        with tempfile.TemporaryDirectory() as d:
            # File có sẵn với tên cũ
            jobs_old = plan_jobs(['http://x/m/a.jpg'], d, '20231115_051320', 'image')
            old_path = jobs_old[0][1]
            with open(old_path, 'wb') as f:
                f.write(b'x')
            idx = index_folder(d)

            # Lần này tên sẽ khác (timestamp khác)
            jobs_new = plan_jobs(['http://x/m/a.jpg'], d, 'khong-gio', 'image')
            new_path = jobs_new[0][1]
            self.assertNotEqual(old_path, new_path)

            class _NoStop:
                @staticmethod
                def is_set():
                    return False

            class _Cache:
                @staticmethod
                def path_for(h):
                    return None

                @staticmethod
                def record(h, p):
                    pass

            class _Ctx:
                class request:
                    async def get(self, *a, **k):
                        raise AssertionError("không được tải: file đã có rồi")

            async def run():
                dl = Downloader(cache=_Cache(), log=lambda *a, **k: None,
                                stop_event=_NoStop(),
                                semaphore=asyncio.Semaphore(2), db_lock=asyncio.Lock())
                return await dl.dispatch(_Ctx(), jobs_new, 'http://ref', {}, idx)

            tasks = asyncio.run(run())
            self.assertEqual(tasks, [], "không được tạo task khi folder đã có hash")
            self.assertFalse(os.path.exists(new_path), "không được tạo bản sao")
            self.assertEqual(len(os.listdir(d)), 1, f"folder phải giữ 1 file: {os.listdir(d)}")


