"""Test cho engine (luồng quét, semaphore, banner) + browser_launcher. Tách từ test_v72.py (P2.2).

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


class TestEngineWiring(unittest.TestCase):
    """Engine phải có cache và dùng index_folder — nếu không thì dedupe không chạy."""

    def test_engine_keeps_cache_reference(self):
        import threading
        import engine
        c = object()
        e = engine.CrawlerEngine(cache=c, log=lambda *a, **k: None,
                                 stop_event=threading.Event())
        self.assertIs(e.cache, c, "engine phải giữ cache để tra thread_date")

    def test_crawl_thread_indexes_folder(self):
        import inspect
        import engine
        src = inspect.getsource(engine.CrawlerEngine.crawl_thread)
        self.assertIn("index_folder", src, "phải quét folder trước khi tải")
        self.assertIn("folder_index", src)

    def test_dispatch_signature_accepts_folder_index(self):
        import inspect
        from downloader import Downloader
        params = list(inspect.signature(Downloader.dispatch).parameters)
        self.assertIn("folder_index", params)


class TestBoxScopeIsNotLeaked(unittest.TestCase):
    """Quét 1 tác giả trong box KHÔNG được kéo cả box.

    Lỗi thật người dùng báo: "giới hạn trong box rồi mà sao quét cả nghìn bài".
    Nguyên nhân: XenForo trả link phân trang TRẦN (`/box/x.6/page-2`), không mang
    `?starter=tacgia`. Engine dùng thẳng link đó nên từ trang 2 trở đi box hiện
    toàn bộ thread của mọi tác giả. Box 100 trang = mở ~2000 thread rồi mới lọc.
    """

    BOX = "https://rphang.beer/box/test-box.6/"

    def test_next_page_keeps_starter_filter(self):
        """Đây chính là lỗi gốc: trang 2 phải còn ?starter."""
        html = ('<a class="pageNav-jump--next" href="/box/test-box.6/page-2">Next</a>')
        _, nxt = X.parse_thread_links(soup_of(html), f"{self.BOX}?starter=tacgia")
        self.assertIsNotNone(nxt)
        self.assertIn("starter=tacgia", nxt,
                      f"trang kế phải giữ bộ lọc, đang là {nxt}")

    def test_next_page_keeps_trailing_slash(self):
        """Thiếu `/` cuối làm visited-set coi hai trang khác nhau là một."""
        html = ('<a class="pageNav-jump--next" href="/box/test-box.6/page-2">Next</a>')
        _, nxt = X.parse_thread_links(soup_of(html), f"{self.BOX}?starter=tacgia")
        self.assertTrue(nxt.rstrip("?starter=tacgia").endswith("/"),
                        f"phải giữ dấu / cuối path: {nxt}")

    def test_filter_survives_three_pages(self):
        """Bộ lọc phải sống qua nhiều trang, không chỉ trang 2."""
        url = f"{self.BOX}?starter=tacgia"
        for page in (2, 3, 4):
            html = (f'<a class="pageNav-jump--next" '
                    f'href="/box/test-box.6/page-{page}">Next</a>')
            _, url = X.parse_thread_links(soup_of(html), url)
            self.assertIn("starter=tacgia", url, f"mất lọc ở trang {page}: {url}")

    def test_existing_query_is_not_overwritten(self):
        """Link phân trang có sẵn tham số riêng thì giữ nguyên, không ghi đè."""
        out = X.with_query_of("/box/x.6/page-2?sort=date", "/box/x.6/?starter=a")
        self.assertIn("sort=date", out)
        self.assertNotIn("starter", out)

    def test_no_query_on_source_leaves_url_alone(self):
        out = X.with_query_of("/box/x.6/page-2", "/box/x.6/")
        self.assertEqual(out, "/box/x.6/page-2")

    def test_thread_starter_reads_data_author(self):
        """Engine truyền vào một Tag (item trong box), không phải soup cả trang."""
        item = soup_of('<div class="structItem structItem--thread" data-author="TraiCube">'
                       '<div class="structItem-title"><a href="/threads/a.1/">A</a>'
                       '</div></div>').find('div', class_='structItem--thread')
        self.assertEqual(X.thread_starter(item), "TraiCube")

    def test_thread_starter_accepts_tag_not_whole_soup(self):
        """Gọi với soup cả trang thì trả '' — chỗ gọi phải truyền item.

        Ghi lại bằng test để nếu ai đổi engine sang truyền soup, test này nhắc.
        """
        whole = soup_of('<div class="structItem structItem--thread" data-author="A">'
                        '</div>')
        self.assertEqual(X.thread_starter(whole), "",
                         "soup cả trang không mang data-author của item")
        item = whole.find('div', class_='structItem--thread')
        self.assertEqual(X.thread_starter(item), "A")

    def test_thread_starter_falls_back_to_username_link(self):
        item = soup_of('<div class="structItem structItem--thread">'
                       '<div class="structItem-title"><a href="/threads/a.1/">A</a></div>'
                       '<a class="username">AiDo</a></div>'
                       ).find('div', class_='structItem--thread')
        self.assertEqual(X.thread_starter(item), "AiDo")

    def test_thread_starter_empty_when_unknown(self):
        self.assertEqual(X.thread_starter(soup_of('<div class="x"></div>')), "")

    def test_engine_filters_before_opening_threads(self):
        """Engine phải lọc ở bước danh sách, không mở hết rồi mới bỏ qua."""
        import inspect
        import engine
        src = inspect.getsource(engine.CrawlerEngine.crawl_user)
        self.assertIn("thread_starter", src,
                      "phải đọc data-author trên item box để lọc sớm")
        self.assertNotIn("thread_urls.update(links)", src,
                         "không được gom hết link rồi mới lọc sau")

    def test_end_to_end_only_author_threads_opened(self):
        """Box 5 trang x 20 bài, chỉ 3 bài của tác giả -> mở đúng 3 thread."""
        import asyncio
        import engine
        from cache import MediaCache

        opened = []
        author = "tacgia"

        def box_page(n):
            items = []
            for i in range(20):
                if n == 1 and i < 2:
                    slug, who = f"bai-cua-toi-{i+1}.{101+i}", author
                elif n == 3 and i == 0:
                    slug, who = "bai-cua-toi-3.103", author
                else:
                    slug, who = f"thread-{n}-{i}.{n}{i:02d}", f"nguoi{n}{i}"
                items.append(
                    f'<div class="structItem structItem--thread" data-author="{who}">'
                    f'<div class="structItem-title">'
                    f'<a data-tp-primary="on" href="/threads/{slug}/">B</a>'
                    f'</div></div>')
            nxt = ""
            if n < 5:
                nxt = (f'<a class="pageNav-jump--next" '
                       f'href="/box/test-box.6/page-{n+1}">N</a>')
            return f'<html><body>{"".join(items)}{nxt}</body></html>'

        thread_html = ('<html><body><h1 class="p-title-value">Bai</h1>'
                       '<article class="message--post" data-author="tacgia" data-content="p">'
                       '<div class="message-body"><img src="/m/x.jpg"></div></article>'
                       '</body></html>')

        def html_for(url):
            if "/threads/" in url:
                return thread_html
            n = 1
            for k in range(2, 10):
                if f"page-{k}" in url:
                    n = k
            return box_page(n)

        class _Page:
            async def goto(self, url, **k):
                self.url = url
                opened.append(url)

            async def wait_for_timeout(self, *a):
                pass

            async def content(self):
                return html_for(self.url)

            async def close(self):
                pass

        class _Ctx:
            def __init__(self):
                self.request = self

            async def new_page(self):
                return _Page()

            async def get(self, url, headers=None, timeout=None):
                class R:
                    status = 200
                    headers = {"content-type": "image/jpeg", "content-length": "2"}

                    async def body(self):
                        return b"xx"

                    async def dispose(self):
                        pass
                return R()

        class _NoStop:
            @staticmethod
            def is_set():
                return False

        tmp = tempfile.mkdtemp(prefix="boxscope")
        real = config.DOWNLOAD_DIR
        real_http = getattr(config, "USE_HTTP_FIRST", True)
        config.DOWNLOAD_DIR = tmp
        # Test nay dung trinh duyet GIA (_Page), nen phai di duong trinh duyet.
        # De USE_HTTP_FIRST=True thi open_page() goi mang that va tra page=None
        # -> khong co thread nao duoc "mo" -> test do sai ly do.
        config.USE_HTTP_FIRST = False
        try:
            async def run():
                cache = MediaCache(os.path.join(tmp, "c.db"))
                eng = engine.CrawlerEngine(cache=cache, log=lambda *a, **k: None,
                                           stop_event=_NoStop(), download_dir=tmp)
                async def connect(p):
                    return _Ctx()
                eng.connect = connect
                await eng.crawl_user(_Ctx(), author, 1, 1,
                                     "https://rphang.beer/box/test-box.6/")
                cache.close()

            asyncio.run(run())
        finally:
            config.DOWNLOAD_DIR = real
            config.USE_HTTP_FIRST = real_http
            shutil.rmtree(tmp, ignore_errors=True)

        threads = [u for u in opened if "/threads/" in u]
        box_pages = [u for u in opened if "/threads/" not in u]
        self.assertEqual(len(box_pages), 5, f"phải đọc đúng 5 trang box: {box_pages}")
        self.assertEqual(len(threads), 3,
                         f"chỉ mở 3 thread của tác giả, đang mở {len(threads)}: {threads}")
        for u in box_pages:
            self.assertIn("starter=tacgia", u, f"mất bộ lọc ở {u}")


class TestRescanFullSweep(unittest.TestCase):
    """Bài đã có trong SQL vẫn phải quét ĐẦY ĐỦ, không lướt qua.

    Yêu cầu người dùng: paste lại link của bài đã tải, app phải kiểm tra số tệp
    và quét cả comment của chủ thớt — không được "kiểm nhanh rồi bỏ qua". Nếu chỉ
    thấy cache có là dừng, media thêm sau sẽ bị bỏ sót vĩnh viễn.
    """

    def _thread_html(self, n_comments, date=True):
        head = ('<div class="p-description"><time class="u-dt" data-time="1700000000">'
                '</time></div>') if date else ''
        posts = ['<article class="message--post" data-author="tacgia" data-content="main">'
                 '<div class="message-body"><img src="/m/main1.jpg">'
                 '<img src="/m/main2.jpg"></div>'
                 '<header class="message-attribution">'
                 '<time class="u-dt" data-time="1700000000"></time></header></article>']
        for i in range(n_comments):
            posts.append(
                f'<article class="message--post" data-author="tacgia" data-content="c{i}">'
                f'<div class="message-body"><img src="/m/c{i}.jpg"></div>'
                f'<header class="message-attribution">'
                f'<time class="u-dt" data-time="{1700000100 + i}"></time></header></article>')
        posts.append('<article class="message--post" data-author="nguoikhac">'
                     '<div class="message-body"><img src="/m/khonglay.jpg"></div></article>')
        return (f'<html><body>{head}<h1 class="p-title-value">Bai Test</h1>'
                f'{"".join(posts)}</body></html>')

    def _run(self, htmls):
        """Chạy crawl_thread cho từng html, trả (số file mỗi lần, log mỗi lần)."""
        import asyncio
        import engine
        from cache import MediaCache

        tmp = tempfile.mkdtemp(prefix="sweep")
        real = config.DOWNLOAD_DIR
        config.DOWNLOAD_DIR = tmp
        try:
            class _Page:
                def __init__(self, h):
                    self.h = h

                async def goto(self, *a, **k):
                    pass

                async def wait_for_timeout(self, *a):
                    pass

                async def content(self):
                    return self.h

                async def close(self):
                    pass

            class _Ctx:
                def __init__(self, h):
                    self.h = h
                    self.request = self

                async def new_page(self):
                    return _Page(self.h)

                async def get(self, url, headers=None, timeout=None):
                    class R:
                        status = 200
                        headers = {"content-type": "image/jpeg", "content-length": "10"}

                        async def body(self):
                            return b"0123456789"

                        async def dispose(self):
                            pass
                    return R()

            class _NoStop:
                @staticmethod
                def is_set():
                    return False

            async def run():
                cache = MediaCache(os.path.join(tmp, "c.db"))
                logs = []
                eng = engine.CrawlerEngine(cache=cache, log=lambda m, t=None: logs.append(m),
                                           stop_event=_NoStop(), download_dir=tmp)
                async def connect(p):
                    return ctx
                eng.connect = connect
                counts = []
                for h in htmls:
                    ctx = _Ctx(h)
                    logs.clear()
                    await eng.crawl_thread(ctx, "https://r/threads/x.1/", "tacgia")
                    folder = None
                    for u in os.listdir(tmp):
                        p = os.path.join(tmp, u)
                        if os.path.isdir(p):
                            for f in os.listdir(p):
                                folder = os.path.join(p, f)
                    counts.append((len(os.listdir(folder)) if folder else 0,
                                   "\n".join(logs)))
                cache.close()
                return counts

            return asyncio.run(run())
        finally:
            config.DOWNLOAD_DIR = real
            shutil.rmtree(tmp, ignore_errors=True)

    def test_new_comments_are_downloaded_on_rescan(self):
        """Chủ thớt trả lời thêm sau lần quét đầu -> phải tải phần mới."""
        counts = self._run([self._thread_html(3), self._thread_html(5)]) 
        self.assertEqual(counts[0][0], 5, f"lần 1 phải có 5 tệp: {counts[0][1]}")
        self.assertEqual(counts[1][0], 7,
                         f"lần 2 phải thêm 2 tệp -> 7, không được bỏ qua: {counts[1][1]}")

    def test_rescan_without_changes_downloads_nothing(self):
        counts = self._run([self._thread_html(3), self._thread_html(3)])
        self.assertEqual(counts[0][0], 5)
        self.assertEqual(counts[1][0], 5, "không có gì mới thì không tải thêm")

    def test_rescan_reports_counts_even_when_skipping(self):
        """Khi không tải gì, vẫn phải báo đã đọc bao nhiêu post/media."""
        counts = self._run([self._thread_html(3), self._thread_html(3)])
        second = counts[1][1]
        self.assertIn("5 media", second, f"phải báo số media: {second}")
        self.assertIn("bài của chủ thớt", second)
        self.assertNotIn("trùng khớp", second)

    def test_other_authors_media_never_downloaded(self):
        counts = self._run([self._thread_html(0)])
        self.assertEqual(counts[0][0], 2, "chỉ media của chủ thớt: 2 ảnh")
        self.assertIn("1 bài người khác bỏ qua", counts[0][1])


class TestDetailedThreadReport(unittest.TestCase):
    """Báo cáo phải nói rõ đã đọc bao nhiêu, thấy bao nhiêu, có bao nhiêu trên đĩa.

    Bug cũ: khi mọi thứ đã có trong cache, app chỉ in "đã trùng khớp (SQLite
    Index Match)" — người dùng không biết nó có thật sự quét hết comment của
    chủ thớt hay chỉ lướt qua rồi bỏ.
    """

    def _report(self, stats, found):
        import engine
        logs = []
        eng = engine.CrawlerEngine.__new__(engine.CrawlerEngine)
        eng.log = lambda m, tag=None: logs.append(m)
        eng.stop_event = type("E", (), {"is_set": staticmethod(lambda: False)})()
        eng._report_thread("TACGIA", 1, stats, found)
        return "\n".join(logs)

    def test_reports_counts_not_just_match(self):
        out = self._report({"ok": 0, "failed": 0, "image": 0, "video": 0, "file": 0},
                           {"images": 5, "author_posts": 3, "other_posts": 4, "pages": 2})
        self.assertIn("5 media", out)
        self.assertIn("3 bài của chủ thớt", out)
        self.assertIn("4 bài người khác bỏ qua", out)
        self.assertIn("2 trang", out)
        self.assertNotIn("trùng khớp", out,
                         "không được dùng câu mơ hồ 'trùng khớp' nữa")

    def test_reports_downloaded_count(self):
        out = self._report({"ok": 3, "failed": 0, "image": 3, "video": 0, "file": 0},
                           {"images": 3, "author_posts": 1})
        self.assertIn("tải mới", out)
        self.assertIn("3 ảnh", out)

    def test_warns_when_disk_has_fewer_files(self):
        """Cache nói có nhưng đĩa thiếu -> phải cảnh báo, không im lặng."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "a.jpg"), "wb") as f:
                f.write(b"x")
            out = self._report(
                {"ok": 0, "failed": 0, "image": 0, "video": 0, "file": 0},
                {"images": 5, "author_posts": 1, "folder": d})
        self.assertIn("chỉ có 1/5", out)
        self.assertIn("tải bù", out)

    def test_reports_empty_thread(self):
        out = self._report({"ok": 0, "failed": 0, "image": 0, "video": 0, "file": 0},
                           {"images": 0, "author_posts": 2})
        self.assertIn("không có media nào", out)

    def test_reports_failures(self):
        out = self._report({"ok": 0, "failed": 4, "image": 0, "video": 0, "file": 0},
                           {"images": 4, "author_posts": 1})
        self.assertIn("4 tệp lỗi", out)


class TestTabSemaphoreNesting(unittest.TestCase):
    """crawl_link không được giữ tab_semaphore khi gọi crawl_thread.

    Bug cũ: crawl_link `async with tab_semaphore` rồi gọi crawl_thread, mà hàm
    đó acquire CHÍNH semaphore đó. Với TAB_SEM=1 là tự khoá mình vĩnh viễn —
    README hướng dẫn chỉnh TAB_SEM trong config nên người dùng hạ xuống 1 là
    app treo cứng, không log, không lỗi.
    """

    def _run_crawl_link(self, tab_sem):
        import asyncio, threading
        import engine

        class _CM:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *e):
                return False

        class _Page:
            async def goto(self, *a, **k):
                pass

            async def wait_for_timeout(self, *a):
                pass

            async def content(self):
                return ("<html><div class='p-description'>"
                        "<a class='username'>tacgia</a></div></html>")

            async def close(self):
                pass

        class _Ctx:
            async def new_page(self):
                return _Page()

        real_playwright, real_tab = engine.async_playwright, config.TAB_SEM
        engine.async_playwright = lambda: _CM()
        config.TAB_SEM = tab_sem
        try:
            async def run():
                eng = engine.CrawlerEngine(cache=None, log=lambda *a, **k: None,
                                           stop_event=threading.Event())
                acquired = []

                async def fake_connect(p):
                    return _Ctx()

                async def fake_crawl_thread(ctx, url, author, idx=1):
                    # đúng như crawl_thread thật: acquire cùng semaphore
                    async with eng.tab_semaphore:
                        acquired.append(author)
                    return author

                eng.connect = fake_connect
                eng.crawl_thread = fake_crawl_thread
                eng._banner = lambda ok, t: None
                await asyncio.wait_for(eng.crawl_link("https://r/threads/x.1/"),
                                       timeout=3)
                return acquired

            return asyncio.run(run())
        finally:
            engine.async_playwright = real_playwright
            config.TAB_SEM = real_tab

    def test_single_tab_budget_does_not_deadlock(self):
        """Đây chính là ca treo cứng trước khi sửa."""
        acquired = self._run_crawl_link(1)
        self.assertEqual(acquired, ["tacgia"], "phải chạy xong và bóc được tác giả")

    def test_default_budget_still_works(self):
        self.assertEqual(self._run_crawl_link(5), ["tacgia"])

    def test_config_clamps_invalid_semaphores(self):
        """Semaphore(0) là khoá chết, giá trị âm ném ValueError."""
        self.assertEqual(config._clamp(0), 1)
        self.assertEqual(config._clamp(-5), 1)
        self.assertEqual(config._clamp("x"), 1)
        self.assertEqual(config._clamp(None), 1)
        self.assertEqual(config._clamp(7), 7)
        for name in ("TAB_SEM", "DOWNLOAD_SEM", "THREAD_SEM", "USER_SEM"):
            self.assertGreaterEqual(getattr(config, name), 1, f"{name} phải >= 1")


class TestEnvVarIsHonoured(unittest.TestCase):
    """COCOC_PATH từng chỉ được NHẮC trong thông báo lỗi, không được đọc."""

    def test_env_var_is_actually_read(self):
        import browser_launcher as B
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            fake = f.name
        old = os.environ.get("COCOC_PATH")
        os.environ["COCOC_PATH"] = fake
        try:
            self.assertEqual(B.find_browser(), fake,
                             "biến môi trường COCOC_PATH phải được find_browser đọc")
        finally:
            if old is None:
                os.environ.pop("COCOC_PATH", None)
            else:
                os.environ["COCOC_PATH"] = old
            os.unlink(fake)

    def test_explicit_arg_beats_env(self):
        import browser_launcher as B
        files = []
        try:
            for _ in range(2):
                with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
                    files.append(f.name)
            old = os.environ.get("COCOC_PATH")
            os.environ["COCOC_PATH"] = files[1]
            try:
                self.assertEqual(B.find_browser(files[0]), files[0],
                                 "tham số truyền vào phải thắng biến môi trường")
            finally:
                if old is None:
                    os.environ.pop("COCOC_PATH", None)
                else:
                    os.environ["COCOC_PATH"] = old
        finally:
            for p in files:
                os.unlink(p)

    def test_nonexistent_env_path_falls_through(self):
        import browser_launcher as B
        old = os.environ.get("COCOC_PATH")
        os.environ["COCOC_PATH"] = r"C:\khong\ton\tai\browser.exe"
        try:
            found = B.find_browser()
            self.assertTrue(found is None or os.path.isfile(found),
                            "đường dẫn hỏng không được trả về")
        finally:
            if old is None:
                os.environ.pop("COCOC_PATH", None)
            else:
                os.environ["COCOC_PATH"] = old


class TestEngineBanner(unittest.TestCase):
    """Banner cuối phiên phải phản ánh đúng kết quả.

    Bug cũ: `ok = False` nằm trong closure user_worker -> gán vào biến cục bộ
    của closure, biến ngoài không đổi, nên quét 30 user hỏng hết vẫn báo
    "ĐÃ HOÀN TẤT". Loại lỗi tệ nhất vì nó phá niềm tin vào chính báo cáo.
    """

    def _run(self, behaviours):
        """behaviours: list hành vi cho từng user. Trả danh sách ok của _banner."""
        import asyncio
        import threading
        import engine

        banners = []

        class _CM:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *exc):
                return False

        real = engine.async_playwright
        engine.async_playwright = lambda: _CM()
        try:
            eng = engine.CrawlerEngine(
                cache=None, log=lambda *a, **k: None, stop_event=threading.Event())

            async def fake_connect(p):
                return object()

            async def fake_crawl_user(context, author, idx, total, box_url):
                if behaviours[author] == "raise":
                    raise RuntimeError("mô phỏng user hỏng")

            eng.connect = fake_connect
            eng.crawl_user = fake_crawl_user
            eng._banner = lambda ok, title: banners.append(ok)
            asyncio.run(eng.crawl_users(list(behaviours), "https://r/box/x.140/"))
        finally:
            engine.async_playwright = real
        return banners

    def test_all_users_failing_reports_failure(self):
        banners = self._run({"a": "raise", "b": "raise"})
        self.assertEqual(banners, [False],
                         "mọi user lỗi -> banner phải báo thất bại, không được báo xong")

    def test_one_failing_user_is_enough(self):
        banners = self._run({"a": "fine", "b": "raise"})
        self.assertEqual(banners, [False], "một user lỗi là đủ để banner báo thất bại")

    def test_all_users_ok_reports_success(self):
        self.assertEqual(self._run({"a": "fine"}), [True], "không lỗi thì báo thành công")


class TestBrowserLauncher(unittest.TestCase):
    """Mở trình duyệt cổng 9222. Chỉ test phần quyết định, không bật Chrome thật."""

    def test_9222_is_the_port_we_look_for(self):
        self.assertEqual(config.CDP_PORT, 9222)
        self.assertIn(str(config.CDP_PORT), config.CDP_URL)

    def test_browser_exe_found(self):
        exe = B.find_browser()
        self.assertTrue(exe and os.path.isfile(exe),
                        "phải tìm được Cốc Cốc/Chrome, không thì app báo lỗi ngay")

    def test_profile_dir_follows_use_real_profile(self):
        """profile_dir() phải theo config.USE_REAL_PROFILE.

        Hai chế độ hợp lệ:
          USE_REAL_PROFILE=True  -> profile gốc của trình duyệt (có session sẵn)
          USE_REAL_PROFILE=False -> profile riêng của app (tách biệt, nhưng trắng)

        Bản cũ hard-code "phải tách khỏi User Data". Điều đó đúng khi app luôn
        dùng profile riêng, nhưng sai khi người dùng muốn tận dụng phiên đăng
        nhập có sẵn của Cốc Cốc — mục đích chính của chế độ CDP.
        """
        old = config.USE_REAL_PROFILE
        try:
            config.USE_REAL_PROFILE = True
            real = B.profile_dir()
            # Có thể không có trình duyệt nào -> rơi về profile riêng, vẫn hợp lệ
            self.assertTrue(real and os.path.isabs(real))

            config.USE_REAL_PROFILE = False
            own = B.profile_dir()
            self.assertTrue(own.endswith(config.BROWSER_PROFILE),
                            f"profile riêng phải kết thúc bằng BROWSER_PROFILE: {own}")
            self.assertIn("V72Crawler", own)
        finally:
            config.USE_REAL_PROFILE = old

    def test_launch_flags_include_user_data_dir(self):
        args = B.build_args(B.find_browser())
        self.assertIn(f"--remote-debugging-port={config.CDP_PORT}", args)
        self.assertTrue(any(a.startswith("--user-data-dir=") for a in args),
                        "thiếu --user-data-dir thì Chrome >= 136 từ chối cổng debug")

    def test_shortcut_in_project_is_coc_coc(self):
        """browser.lnk là shortcut Cốc Cốc của bạn, phải còn nguyên trong project."""
        self.assertTrue(os.path.isfile(B.SHORTCUT_PATH),
                        "browser.lnk không có trong project?")

    def test_port_probe_is_false_when_closed(self):
        # Chỉ kiểm tra hàm probe không ném exception; trạng thái 9222 tùy máy.
        self.assertIn(B.is_port_open(), (True, False))


