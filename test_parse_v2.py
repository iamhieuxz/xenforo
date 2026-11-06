"""Test cho xenforo_parse + xf_selectors. Tách từ test_v72.py (P2.2).

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


class TestClassMatching(unittest.TestCase):
    """Regex cũ khớp chuỗi con -> xoá mất thân bài / bỏ sót media."""

    def test_mixedcase_class_is_matched(self):
        """bs4 so class_=set/list CÓ phân biệt HOA/thường -> set sẽ không khớp
        'bbCodeBlock'. Regex neo ^...$ là cơ chế đúng."""
        s = soup_of('<div class="message-body"><blockquote class="bbCodeBlock">x</blockquote></div>')
        imgs, _, _ = X.extract_post_media(s.select_one('.message-body'), 'http://x/')
        self.assertEqual(imgs, [], "bbCodeBlock HOA/thường phải khớp và bị gỡ")

    def test_jsSelectToQuote_is_not_quote(self):
        s = soup_of('<div class="message-body js-selectToQuote"><img src="a.jpg"></div>')
        imgs, _, _ = X.extract_post_media(s.select_one('.message-body'), 'http://x/')
        self.assertEqual(len(imgs), 1,
                         "js-selectToQuote KHÔNG được coi là blockquote, ảnh phải còn")

    def test_real_quote_removed_but_media_kept(self):
        s = soup_of('<div class="message-body">'
                    '<blockquote class="bbCodeBlock">'
                    '<img src="quoted.jpg"></blockquote>'
                    '<img src="keep.jpg"></div>')
        imgs, _, _ = X.extract_post_media(s.select_one('.message-body'), 'http://x/')
        self.assertEqual(imgs, ['http://x/keep.jpg'], "blockquote thật phải bị loại, ảnh ngoài phải giữ")

    def test_class_containing_ad_word_not_flagged(self):
        s = soup_of('<div class="message-body">'
                    '<a class="download" href="/attachments/1/file.zip">zip</a></div>')
        _, _, files = X.extract_post_media(s.select_one('.message-body'), 'http://x/')
        self.assertEqual(len(files), 1, "'download' chứa 'ad' -> KHÔNG được coi là quảng cáo")

    def test_real_ad_wrapper_still_removed(self):
        s = soup_of('<div class="message-body">'
                    '<div class="ad-container"><img src="ad.jpg"></div>'
                    '<img src="real.jpg"></div>')
        imgs, _, _ = X.extract_post_media(s.select_one('.message-body'), 'http://x/')
        self.assertEqual(imgs, ['http://x/real.jpg'], "ad wrapper phải bị gỡ")


class TestFilename(unittest.TestCase):
    def test_ext_kept_per_type(self):
        # Bug cũ: .zip/.pdf bị đặt tên *_video_*.mp4
        self.assertEqual(X.ext_for('/a/f.zip', S.FILE_EXT, '.bin'), '.zip')
        self.assertEqual(X.ext_for('/a/f.pdf', S.FILE_EXT, '.bin'), '.pdf')
        self.assertEqual(X.ext_for('/a/f.mp4', S.VIDEO_EXT, '.mp4'), '.mp4')
        self.assertEqual(X.ext_for('/a/photo.webp', S.IMAGE_EXT, '.jpg'), '.webp')

    def test_ext_falls_back_when_unknown(self):
        self.assertEqual(X.ext_for('/attachments/12/file', S.IMAGE_EXT, '.jpg'), '.jpg')
        self.assertEqual(X.ext_for('/video/play/9/video.mp4?x=1', S.VIDEO_EXT, '.mp4'), '.mp4')

    def test_zip_goes_to_files_not_videos(self):
        s = soup_of('<div class="message-body"><a href="/attachments/1/doc.zip">download</a></div>')
        _, vids, files = X.extract_post_media(s.select_one('.message-body'), 'http://x/')
        self.assertEqual(vids, [], "zip KHÔNG được coi là video")
        self.assertEqual(files, ['http://x/attachments/1/doc.zip'])

    def test_xenforo_attachment_suffix_still_typed_right(self):
        """XenForo tên attachment là ten.zip.12345/ -> phải ra FILE, không phải ảnh."""
        s = soup_of('<div class="message-body"><a href="/attachments/01/doc.zip.12345/">dl</a></div>')
        imgs, vids, files = X.extract_post_media(s.select_one('.message-body'), 'http://x/')
        self.assertEqual(imgs, [], "doc.zip.12345 không được nhét vào imgs")
        self.assertEqual(files, ['http://x/attachments/01/doc.zip.12345/'])

    def test_pdf_does_not_become_jpg(self):
        s = soup_of('<div class="message-body"><a href="/attachments/1/tailieu.pdf">tai ve</a></div>')
        imgs, _, files = X.extract_post_media(s.select_one('.message-body'), 'http://x/')
        self.assertEqual(imgs, [], "pdf KHÔNG được lưu như ảnh")
        self.assertEqual(len(files), 1)

    def test_plan_names_unique(self):
        jobs = plan_jobs(['http://x/m/1.jpg', 'http://x/m/1.jpg', 'http://x/m/2.jpg'],
                         'C:/f', '20240101_000000', 'image')
        names = [os.path.basename(p) for _, p, _, _ in jobs]
        self.assertEqual(len(set(names)), len(names), f"trùng tên: {names}")

    def test_plan_paths_differ_between_threads(self):
        """Hai thread khác folder cùng 1 URL -> path khác để cache clone, không đè file."""
        a = plan_jobs(['http://x/m/1.jpg'], 'C:/user/[d] thread A', 't', 'image')[0][1]
        b = plan_jobs(['http://x/m/1.jpg'], 'C:/user/[d] thread B', 't', 'image')[0][1]
        self.assertNotEqual(a, b, "path phải khác để tránh đè file")

    def test_hash_ignores_query(self):
        self.assertEqual(url_hash('http://x/a.jpg?w=1'), url_hash('http://x/a.jpg#frag'))


class TestPageLoop(unittest.TestCase):
    def test_page_num_stripped(self):
        self.assertEqual(X.normalize_to_first_page('https://r/threads/x.1/page-5/?a=1#p9'),
                         'https://r/threads/x.1/')

    def test_thread_links_and_next_page(self):
        html = ('<div class="structItem structItem--thread">'
                '<div class="structItem-title">'
                '<a data-tp-primary="on" href="/threads/bai-viet-1.10/">Bai 1</a>'
                '</div></div>'
                '<a class="pageNav-jump--next" href="/box/x.140/page-2/">Next</a>')
        links, nxt = X.parse_thread_links(soup_of(html), 'https://r/box/x.140/')
        self.assertEqual(links, ['https://r/threads/bai-viet-1.10/'])
        self.assertEqual(nxt, 'https://r/box/x.140/page-2/')

    def test_visiting_same_page_twice_is_detectable(self):
        """visited-set phải bắt được vòng lặp A -> B -> A (engine dựa vào nó)."""
        visited, current, hops = set(), 'http://x/page-2/', 0
        while current and current not in visited:
            visited.add(current)
            hops += 1
            current = 'http://x/page-2/' if current == 'http://x/page-3/' else 'http://x/page-3/'
        self.assertLessEqual(hops, 2, "vòng lặp phải bị chặn")


class TestAuthorAndMeta(unittest.TestCase):
    def test_author_from_description(self):
        s = soup_of('<div class="p-description"><a class="username">TraiCube</a></div>')
        self.assertEqual(X.resolve_author(s), 'TraiCube')

    def test_author_fallback_to_first_post(self):
        s = soup_of('<article class="message--post" data-author="abc"></article>')
        self.assertEqual(X.resolve_author(s), 'abc')

    def test_label_stripped_from_title(self):
        s = soup_of('<h1 class="p-title-value">[VIP] <span class="label">Label</span>Bai Hay</h1>')
        title, _ = X.thread_meta(s)
        self.assertNotIn('[VIP]', title)
        self.assertNotIn('Label', title)
        self.assertIn('Bai Hay', title)

    def test_bad_timestamp_returns_empty_not_zero(self):
        """Không xác định được giờ thì trả "" để caller tự quyết định.

        Bản cũ trả "00000000_000000" — nhìn như một giá trị hợp lệ nên không ai
        biết là thiếu, và mọi post thiếu giờ dùng chung một tiền tố.
        """
        s = soup_of('<article class="message--post" data-author="a">'
                    '<time class="u-dt" data-time="abc"></time></article>')
        self.assertEqual(X.post_timestamp(s), "",
                         "phải là chuỗi rỗng, không phải 00000000_000000")


class TestWindowsNames(unittest.TestCase):
    def test_reserved_and_illegal_chars(self):
        self.assertEqual(X.clean_name('CON'), '_CON')
        self.assertEqual(X.clean_name('a/b:c*d?'), 'abcd')
        self.assertEqual(X.clean_name('   '), 'Untitled')
        self.assertEqual(X.clean_name(''), 'Untitled')

    def test_long_name_truncated(self):
        self.assertLessEqual(len(X.clean_name('x' * 500)), 180)

    def test_no_trailing_dot_or_space(self):
        self.assertFalse(X.clean_name('ten file...').endswith(('.', ' ')))


class TestNoStdlibShadowing(unittest.TestCase):
    """Không file nào trong project được trùng tên module chuẩn của Python.

    Bug cũ: module nội bộ tên `selectors.py` che `selectors` của stdlib. Mọi
    `import selectors` - kể cả trong asyncio - nhận file của project. Trên
    Windows Python 3.10 chưa nổ vì mặc định dùng ProactorEventLoop, nhưng chỉ
    cần đổi loop policy hoặc lên bản Python khác là app chết lúc tạo event loop.
    """

    # Module chuẩn dễ bị trùng nhất khi đặt tên file trong project.
    SHADOW_PRONE = {
        "selectors", "types", "queue", "code", "copy", "io", "abc", "json",
        "token", "time", "signal", "socket", "threading", "logging", "hashlib",
    }

    def _project_modules(self):
        import pathlib
        root = pathlib.Path(__file__).parent
        return {p.stem for p in root.glob("*.py")}

    def test_stdlib_selectors_is_not_shadowed(self):
        import selectors
        self.assertNotEqual(
            os.path.basename(getattr(selectors, "__file__", "")),
            "xf_selectors.py", "phải là module của stdlib, không phải file project")
        self.assertTrue(hasattr(selectors, "DefaultSelector"),
                        "stdlib selectors bị che -> asyncio không tạo được event loop")

    def test_selector_event_loop_can_be_created(self):
        """Đây chính là thứ đã chết khi bị che: AttributeError DefaultSelector."""
        import asyncio
        loop = asyncio.SelectorEventLoop()
        loop.close()

    def test_no_project_file_collides_with_stdlib(self):
        collided = sorted(self._project_modules() & self.SHADOW_PRONE)
        for name in collided:
            self.fail(f"file {name}.py trùng tên module chuẩn -> che stdlib khi import")

    def test_internal_constants_module_still_works(self):
        """Đổi tên không được làm mất hằng số nào phần parse đang dùng."""
        for const in ("IMAGE_EXT", "VIDEO_EXT", "FILE_EXT", "FILE_URL_RE",
                      "IMAGE_URL_RE", "VIDEO_URL_RE", "NOISE_URL_PARTS",
                      "NON_MEDIA_CONTENT_TYPES", "RETRY_STATUSES"):
            self.assertTrue(hasattr(S, const), f"thiếu hằng {const} trong xf_selectors")


class TestSoupsIsNotPureByAccident(unittest.TestCase):
    """extract_post_media sửa input — phải nói rõ, và phải có bản không sửa.

    Module từng tự nhận "hàm thuần" trong khi _strip_junk gọi decompose() xoá
    node khỏi cây gốc. Gọi hai lần trên cùng soup cho kết quả khác nhau.
    """

    HTML = ('<article class="message--post" data-author="a"><div class="message-body">'
            '<blockquote class="bbCodeBlock"><img src="/quoted.jpg"></blockquote>'
            '<img src="/real.jpg"></div></article>')

    def test_documented_as_mutating(self):
        self.assertIn("SỬA", X.extract_post_media.__doc__ or "",
                      "docstring phải cảnh báo rõ là hàm sửa input")

    def test_module_docstring_no_longer_claims_pure(self):
        self.assertNotIn("Hàm thuần", X.__doc__ or "",
                         "module không được tự nhận tất cả đều thuần")

    def test_copy_variant_does_not_mutate(self):
        soup = soup_of(self.HTML)
        post = soup.select_one("article")
        first = X.extract_post_media_copy(post, "https://r/")[0]
        second = X.extract_post_media_copy(post, "https://r/")[0]
        self.assertEqual(first, ['https://r/real.jpg'])
        self.assertEqual(first, second, "bản copy phải cho cùng kết quả mọi lần")


