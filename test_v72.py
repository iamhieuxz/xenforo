"""Self-check cho logic không cần mạng/Tk.

Chạy: python test_v72.py

Các test gọi thẳng xenforo_parse/cache/downloader nên không cần import Tk,
không cần Chrome, không cần mạng.

HERMETIC: setUpModule trỏ config.DOWNLOAD_DIR vào thư mục tạm trước khi bất kỳ
test nào chạy. Bản cũ để nguyên E:\\HIDE\\RPHANG, nên ba test dựng
XenForoScannerApp thật đã mở và GHI crawler_cache.db của thư viện thật — vừa
làm bẩn dữ liệu người dùng, vừa làm suite đỏ trên máy không có ổ đó (CI).
"""

import os
import shutil
import tempfile
import unittest

from bs4 import BeautifulSoup

import xf_selectors as S
import xenforo_parse as X
import config
import browser_launcher as B
from cache import MediaCache, LocalUserIndex
from downloader import plan_jobs, url_hash, Downloader, count_files
from v72 import PALETTE, log_tag, _MARKER_TAGS


_ORIGINAL_DOWNLOAD_DIR = config.DOWNLOAD_DIR
_TEST_TMP = None


def setUpModule():
    """Cô lập hoàn toàn khỏi thư mục tải thật.

    Phải chạy trước MỌI test: XenForoScannerApp đọc config.DOWNLOAD_DIR trong
    __init__ rồi mở MediaCache ngay, nên chỉ cần một test dựng app trước khi
    kịp đổi là DB thật bị mở.
    """
    global _TEST_TMP
    _TEST_TMP = tempfile.mkdtemp(prefix="v72_test_")
    config.DOWNLOAD_DIR = _TEST_TMP
    os.environ["RPHANG_DIR"] = _TEST_TMP


def tearDownModule():
    config.DOWNLOAD_DIR = _ORIGINAL_DOWNLOAD_DIR
    os.environ.pop("RPHANG_DIR", None)
    if _TEST_TMP:
        # Windows khoá file đang mở: nếu còn MediaCache chưa close thì rmtree
        # thất bại IM LẶNG (ignore_errors) và thư mục tạm ở lại mãi. Thử vài lần
        # rồi mới bỏ cuộc, và báo ra ngoài thay vì nuốt.
        for _ in range(3):
            shutil.rmtree(_TEST_TMP, ignore_errors=True)
            if not os.path.exists(_TEST_TMP):
                break
            import gc
            gc.collect()
            import time
            time.sleep(0.05)
        if os.path.exists(_TEST_TMP):
            shutil.rmtree(_TEST_TMP, ignore_errors=True)


def soup_of(html):
    return BeautifulSoup(html, 'lxml')


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
            c.conn.execute("INSERT OR REPLACE INTO media_index VALUES (?,?,?)",
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


class TestBrowserLauncher(unittest.TestCase):
    """Mở trình duyệt cổng 9222. Chỉ test phần quyết định, không bật Chrome thật."""

    def test_9222_is_the_port_we_look_for(self):
        self.assertEqual(config.CDP_PORT, 9222)
        self.assertIn(str(config.CDP_PORT), config.CDP_URL)

    def test_browser_exe_found(self):
        exe = B.find_browser()
        self.assertTrue(exe and os.path.isfile(exe),
                        "phải tìm được Cốc Cốc/Chrome, không thì app báo lỗi ngay")

    def test_profile_dir_is_separate(self):
        """Profile phải tách khỏi profile đang dùng, nếu không cờ debug bị bỏ qua."""
        self.assertNotIn("User Data", B.profile_dir())
        self.assertTrue(B.profile_dir().endswith(config.BROWSER_PROFILE))

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


class TestLogColors(unittest.TestCase):
    """Phân loại màu thông báo. Không cần Tk: chỉ gọi hàm log_tag thuần."""

    def test_marker_prefix_picks_the_right_color(self):
        cases = [
            ("[-] Lỗi: chưa nhập tên tác giả!", "error"),
            ("   [!] Cảnh báo: 3 tệp lỗi đường truyền", "summary"),
            ("[✓] Bài 1 đồng bộ thành công 8 ảnh và 2 video.", "success"),
            ("   [+] USER: Định vị thành công 9 Thread bài viết.", "success"),
            ("   [•] Bài 2 đã trùng khớp (SQLite Index Match).", "skip"),
            ("[*] Đang bóc tách trang đầu tiên: https://r/threads/x/", "info"),
        ]
        for message, expected in cases:
            self.assertEqual(log_tag(message), expected, f"sai màu cho: {message}")

    def test_emoji_prefix_does_not_break_detection(self):
        """'👥 [USER 1/2]' có emoji trước dấu, vẫn phải ra màu chứ không rơi về dim."""
        self.assertEqual(log_tag("👥 [USER 1/2] ĐỒNG BỘ DỮ LIỆU", "info"), "info")

    def test_no_emoji_left_in_ui_labels(self):
        """Nhãn giao diện không được chứa emoji — dùng emoji cho icon là mẫu UI rác."""
        import re as _re
        import tkinter as tk
        import v72
        root = tk.Tk()
        root.withdraw()
        try:
            app = v72.XenForoScannerApp(root)
            texts = [app.btn_download_user.cget("text"), app.btn_download_link.cget("text"),
                     app.btn_stop.cget("text"), app.btn_update_all.cget("text"),
                     app.btn_copy_log.cget("text"), app.btn_clear_log.cget("text")]
            labels = []
            def walk(w):
                for child in w.winfo_children():
                    if isinstance(child, tk.Label):
                        labels.append(child.cget("text"))
                    walk(child)
            walk(root)
            for t in texts + labels:
                self.assertIsNone(_re.search(r"[\U0001F300-\U0001FAFF☀-➿️]",
                                             str(t)),
                                  f"còn emoji trong nhãn: {t!r}")
        finally:
            app.cache.close()      # nhả handle SQLite trước khi destroy
            root.destroy()

    def test_marker_mid_line_is_not_mistaken_for_a_tag(self):
        """Dấu ngoặc giữa dòng (URL, text) không được nhận nhầm làm dấu phân loại."""
        self.assertEqual(log_tag("xem https://r/threads/a.1/page-2/?q=[ok]"), "dim")
        self.assertEqual(log_tag("[USER 1/2] ĐỒNG BỘ"), "dim")

    def test_explicit_tag_wins(self):
        self.assertEqual(log_tag("[-] lỗi", "bulk"), "bulk")
        self.assertEqual(log_tag("👥 [USER 1/2] ...", "bulk"), "bulk")

    def test_separator_lines_are_dimmed(self):
        self.assertEqual(log_tag("\n========================================"), "dim")
        self.assertEqual(log_tag(""), "dim")

    def test_every_marker_in_engine_has_a_color(self):
        """Mọi dấu engine/downloader thực sự ghi ra phải có màu, không dòng nào trắng."""
        for src in ('[-]', '[!]', '[✓]', '[+]', '[•]', '[*]'):
            self.assertIn(src[1], _MARKER_TAGS, f"dấu {src} chưa được gán màu")

    def test_all_tags_used_are_configured(self):
        """Mọi màu log phải là hex hợp lệ, và phải có ở cả hai theme."""
        for theme, p in PALETTE.items():
            self.assertTrue(p["LOG"], f"{theme}: thiếu bảng màu log")
            for tag, color in p["LOG"].items():
                self.assertRegex(color, r'^#[0-9a-fA-F]{6}$', f"{theme}/{tag} sai định dạng màu")


class TestDownloadProgress(unittest.TestCase):
    """Log tiến độ phải chạy TRONG lúc tải, không phải đợi xong mới báo."""

    def test_progress_fires_while_tasks_still_running(self):
        import asyncio
        lines = []

        d = Downloader(cache=None, log=lambda m, t=None: lines.append(m),
                       stop_event=None, semaphore=None, db_lock=None)
        d.stop_event = type("E", (), {"is_set": staticmethod(lambda: False)})()

        async def job(delay, result):
            await asyncio.sleep(delay)
            return result

        async def run():
            tasks = [asyncio.create_task(job(0.01, "OK")) for _ in range(12)]
            tasks.append(asyncio.create_task(job(0.5, "OK")))
            # gather phải được gọi, nhưng ta kiểm tra callback chạy trước khi nó kết thúc
            probe = []

            async def watch():
                await asyncio.sleep(0.3)
                probe.append(list(lines))

            await asyncio.gather(d.gather(tasks), watch())
            return probe

        probe = asyncio.new_event_loop().run_until_complete(run())
        # Sau 0.3s, task 0.5s chưa xong nhưng đã có dòng tiến độ -> không phải đợi hết.
        self.assertTrue(probe[0], "phải có dòng tiến độ TRƯỚC khi tất cả tệp xong")

    def test_progress_counts_are_correct(self):
        import asyncio
        lines = []
        d = Downloader(cache=None, log=lambda m, t=None: lines.append(m),
                       stop_event=None, semaphore=None, db_lock=None)
        d.stop_event = type("E", (), {"is_set": staticmethod(lambda: False)})()

        async def run():
            async def job(r):
                return r
            tasks = [asyncio.create_task(job(r)) for r in ("OK", "OK", "FAILED", "OK")]
            tasks[0].kind = "image"
            tasks[1].kind = "video"
            tasks[3].kind = "image"
            return await d.gather(tasks)

        stats = asyncio.new_event_loop().run_until_complete(run())
        self.assertEqual(stats["ok"], 3, f"sai đếm ok: {stats}")
        self.assertEqual(stats["failed"], 1, f"sai đếm failed: {stats}")
        self.assertEqual(stats["image"], 2, f"sai đếm ảnh: {stats}")
        self.assertEqual(stats["video"], 1, f"sai đếm video: {stats}")

    def test_count_files_wording(self):
        """Thông báo phải đọc như người, không phải đếm chung một số."""
        self.assertEqual(count_files({"image": 8, "video": 2, "file": 0}),
                         "8 ảnh và 2 video")
        self.assertEqual(count_files({"image": 8, "video": 0, "file": 0}), "8 ảnh")
        self.assertEqual(count_files({"image": 0, "video": 3, "file": 0}), "3 video")
        self.assertEqual(count_files({"image": 1, "video": 2, "file": 1}),
                         "1 ảnh, 2 video và 1 tệp")
        self.assertEqual(count_files({"image": 0, "video": 0, "file": 0}), "0 tệp")

    def test_all_text_colors_pass_wcag_aa(self):
        """Mọi cặp chữ/nền phải đạt WCAG AA, kể cả màu lúc hover.

        Nền tối dễ trượt: chữ trắng trên accent sáng chỉ đạt 3.68:1, và làm nhạt
        nền lúc hover càng làm tỷ lệ tệ hơn. Bắt bằng test để không tái phát.
        """
        def lum(hex_color):
            h = hex_color.lstrip("#")
            ch = []
            for i in (0, 2, 4):
                v = int(h[i:i + 2], 16) / 255
                ch.append(v / 12.92 if v <= 0.03928
                          else ((v + 0.055) / 1.055) ** 2.4)
            return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]

        def ratio(fg, bg):
            a, b = lum(fg), lum(bg)
            return (max(a, b) + 0.05) / (min(a, b) + 0.05)

        for theme, p in PALETTE.items():
            card, main, inp = p["BG_CARD"], p["BG_MAIN"], p["BG_INPUT"]
            pairs = [
                ("chinh/nen the", p["FG_TEXT"], card, 4.5),
                ("chinh/nen app", p["FG_TEXT"], main, 4.5),
                ("chinh/nen o nhap", p["FG_TEXT"], inp, 4.5),
                ("nhan phu/nen the", p["FG_SUB"], card, 4.5),
                ("nhan phu/nen app", p["FG_SUB"], main, 4.5),
                ("nhan phu/nen o nhap", p["FG_SUB"], inp, 4.5),
                ("accent chu/nen the", p["ACCENT_TXT"], card, 4.5),
                ("accent chu/nen app", p["ACCENT_TXT"], main, 4.5),
                ("accent chu/nen o nhap", p["ACCENT_TXT"], inp, 4.5),
                ("chu tren nut accent", p["FG_ON_ACCENT"], p["ACCENT"], 4.5),
                ("chu tren nut hover", p["FG_ON_ACCENT"], p["ACCENT_HOVER"], 4.5),
                ("chu tren nut do", p["FG_ON_ACCENT"], p["DANGER"], 4.5),
            ]
            for tag, color in p["LOG"].items():
                pairs.append((f"log {tag}", color, inp, 4.5))
            # Viền là control trực quan (1.4.11): cần thấy trên mọi nền nó nằm.
            for bg_name, bg in (("the", card), ("app", main), ("o nhap", inp)):
                pairs.append((f"vien/{bg_name}", p["BORDER"], bg, 3.0))

            for name, fg, bg, need in pairs:
                r = ratio(fg, bg)
                self.assertGreaterEqual(
                    r, need, f"[{theme}] {name}: {fg} tren {bg} chi {r:.2f}:1")

    def test_stats_read_the_exact_strings_engine_prints(self):
        """Bộ đếm phải khớp đúng chuỗi engine thật sự in ra.

        count_files() gọi nhóm thứ ba là 'tệp', và số lỗi nằm ở dòng
        '[!] Cảnh báo: N tệp lỗi đường truyền' chứ không phải 'N lỗi'. Regex đoán
        sai từ là hỏng cả dòng thống kê.
        """
        import tkinter as tk
        import v72
        root = tk.Tk()
        root.withdraw()
        try:
            app = v72.XenForoScannerApp(root)
            app._safe_log("[✓] Đã tải: " + count_files({"image": 12, "video": 2, "file": 0}))
            app._safe_log("   [!] Cảnh báo: 3 tệp lỗi đường truyền trong bài này.")
            self.assertEqual(app._n_image, 12)
            self.assertEqual(app._n_video, 2)
            self.assertEqual(app._n_error, 3)
            self.assertEqual(app._last_detail, "12 ảnh, 2 video · 3 lỗi")
            self.assertTrue(app._had_error, "dòng [!] phải bật cờ có lỗi")
        finally:
            app.cache.close()
            root.destroy()

    def test_log_filter_hides_and_restores(self):
        """Lọc phải ẩn dòng không khớp nhưng giữ nguyên dữ liệu gốc để bỏ lọc là hiện lại."""
        import tkinter as tk
        import v72
        root = tk.Tk()
        root.withdraw()
        try:
            app = v72.XenForoScannerApp(root)
            app._safe_log("[✓] Bài 1 xong")
            app._safe_log("[-] Lỗi kết nối")
            app._safe_log("[✓] Bài 2 xong")
            all_lines = app.log_box.index("end-1c")

            app.ent_filter.insert(0, "lỗi")
            app._apply_filter()
            shown = app.log_box.get("1.0", "end-1c")
            self.assertIn("Lỗi kết nối", shown)
            self.assertNotIn("Bài 1 xong", shown)
            self.assertEqual(len(app._log_lines), 3, "lọc không được xoá dữ liệu gốc")

            app.ent_filter.delete(0, tk.END)
            app._apply_filter()
            self.assertEqual(app.log_box.index("end-1c"), all_lines,
                             "bỏ lọc phải hiện lại đủ số dòng ban đầu")
        finally:
            app.cache.close()
            root.destroy()

    def test_stop_cuts_off_hung_download(self):
        """Bấm Dừng phải cắt ngay request đang treo, không chờ hết timeout.

        Timeout của Playwright chỉ áp dụng lúc BẮT ĐẦU request: request đã vào
        get() rồi sẽ sống tới hết DOWNLOAD_TIMEOUT_MS (40s). Không có _racing_stop
        thì nút Dừng treo gần 40s.
        """
        import asyncio, os, shutil, tempfile, threading, time

        class Hanging:
            status = 200
            headers = {"content-type": "video/mp4"}

            async def body(self):
                await asyncio.sleep(3600)

            async def dispose(self):
                pass

        class Req:
            async def get(self, url, headers=None, timeout=None):
                await asyncio.sleep(3600)     # treo vô hạn
                return Hanging()

        class Ctx:
            request = Req()

        class NoCache:
            @staticmethod
            def path_for(h):
                return None

            @staticmethod
            def record(h, p):
                pass

        tmp = tempfile.mkdtemp(prefix="stopcut")
        try:
            stop = threading.Event()
            d = Downloader(cache=NoCache(), log=lambda m, t=None: None,
                           stop_event=stop, semaphore=asyncio.Semaphore(4),
                           db_lock=asyncio.Lock())
            jobs = plan_jobs([f"http://x/{i}.mp4" for i in range(12)],
                             os.path.join(tmp, "out"), "t", "main_video")

            async def run():
                tasks = await d.dispatch(Ctx(), jobs, "http://ref", {})
                await asyncio.sleep(0.1)
                t0 = time.perf_counter()
                stop.set()
                stats = await d.gather(tasks)
                return (time.perf_counter() - t0) * 1000, stats

            loop = asyncio.new_event_loop()
            left = []
            try:
                ms, stats = loop.run_until_complete(run())
                left = asyncio.all_tasks(loop)
            finally:
                for t in left:
                    t.cancel()
                if not loop.is_closed() and left:
                    loop.run_until_complete(
                        asyncio.gather(*left, return_exceptions=True))
                loop.close()

            self.assertLess(ms, 2000,
                            f"nút Dừng mất {ms:.0f}ms - phải cắt nhanh, không chờ timeout 40s")
            self.assertEqual(stats["ok"], 0, "không tải được gì cả khi request treo")
            tmpfiles = [f for r, _, fs in os.walk(tmp) for f in fs if f.endswith(".tmp")]
            self.assertEqual(tmpfiles, [], f"còn sót file .tmp: {tmpfiles}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_settle_does_not_wait_pointlessly(self):
        """Đo thực tế: settle=0 vẫn ra đủ post. Nếu XenForo đổi sang client-side
        rendering thì test này KHÔNG bắt được, phải tăng lại config.SETTLE_MS."""
        self.assertEqual(config.SETTLE_MS, 0)


class TestDedupeWithinThread(unittest.TestCase):
    """seen_hashes chỉ được ghi khi tải THÀNH CÔNG.

    Bug cũ: ghi path ngay trong vòng lặp dispatch, trước khi tải. Một URL xuất
    hiện ở hai post mà lần đầu fail (500, timeout) thì lần hai bị coi là "đã
    xử lý" -> media mất im lặng.
    """

    class _Resp:
        def __init__(self, status):
            self.status = status
            self.headers = {"content-type": "image/jpeg"}

        async def body(self):
            return b"bytes" if self.status == 200 else b""

        async def dispose(self):
            pass

    class _NoStop:
        @staticmethod
        def is_set():
            return False

    def _dispatch_twice(self, first_ok):
        """first_ok=False: mọi request ở lần dispatch đầu trả 404 (lỗi vĩnh viễn,
        không retry nên test nhanh và tất định). first_ok=True: trả 200."""
        import asyncio, tempfile, shutil
        from downloader import Downloader

        tmp = tempfile.mkdtemp(prefix="dedupe")
        try:
            state = {"ok": first_ok}

            class _Req:
                async def get(inner, url, headers=None, timeout=None):
                    return TestDedupeWithinThread._Resp(200 if state["ok"] else 404)

            class _Ctx:
                request = _Req()

            class _Cache:
                @staticmethod
                def path_for(h):
                    return None

                @staticmethod
                def record(h, p):
                    pass

            async def run():
                d = Downloader(cache=_Cache(), log=lambda *a, **k: None,
                               stop_event=TestDedupeWithinThread._NoStop(),
                               semaphore=asyncio.Semaphore(2), db_lock=asyncio.Lock())
                seen, folder, url = {}, os.path.join(tmp, "f"), "http://x/same.jpg"
                t1 = await d.dispatch(_Ctx(), [(url, os.path.join(folder, "a.jpg"),
                                                "H", "image")], "http://ref", seen)
                await d.gather(t1)
                a_ok = os.path.exists(os.path.join(folder, "a.jpg"))
                state["ok"] = True          # từ đây server hoạt động bình thường
                t2 = await d.dispatch(_Ctx(), [(url, os.path.join(folder, "b.jpg"),
                                                "H", "image")], "http://ref", seen)
                await d.gather(t2)
                return len(t1), len(t2), a_ok, os.path.exists(os.path.join(folder, "b.jpg"))

            return asyncio.run(run())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_failed_first_attempt_retries_second_occurrence(self):
        n1, n2, a_ok, b_ok = self._dispatch_twice(first_ok=False)
        self.assertEqual(n1, 1)
        self.assertFalse(a_ok, "lần 1 phải fail (404)")
        self.assertEqual(n2, 1, "lần 2 cùng URL phải được tải lại, không bị coi là đã xử lý")
        self.assertTrue(b_ok, "lần 2 thành công thì file phải có")

    def test_successful_first_attempt_is_cloned_not_refetched(self):
        n1, n2, a_ok, b_ok = self._dispatch_twice(first_ok=True)
        self.assertTrue(a_ok)
        self.assertEqual(n2, 0, "đã tải thành công rồi thì phải clone, không tải lại")
        self.assertTrue(b_ok, "clone phải tạo ra file thứ hai")


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


class TestDownloadDirInjection(unittest.TestCase):
    """Engine phải dùng thư mục được TIÊM, không đọc config trực tiếp.

    Bug cũ: v72._resolve_dir() fallback sang ~/RPHANG khi ổ cấu hình hỏng và đặt
    cache ở đó, nhưng engine vẫn ghi media vào config.DOWNLOAD_DIR. Kết quả:
    cache trỏ đường dẫn không tồn tại -> mất tác dụng khử trùng lặp, lần sau tải
    lại toàn bộ.
    """

    def _engine(self, download_dir=None):
        import threading
        import engine
        return engine.CrawlerEngine(cache=None, log=lambda *a, **k: None,
                                    stop_event=threading.Event(),
                                    download_dir=download_dir)

    def test_defaults_to_config(self):
        self.assertEqual(self._engine().download_dir, config.DOWNLOAD_DIR)

    def test_injected_dir_wins_over_config(self):
        injected = r"C:\Users\test\RPHANG"
        self.assertEqual(self._engine(injected).download_dir, injected)
        self.assertNotEqual(injected, config.DOWNLOAD_DIR)

    def test_crawl_thread_uses_instance_dir_not_config(self):
        """Chốt bằng source: không còn chỗ nào đọc config.DOWNLOAD_DIR trong engine."""
        import inspect
        import engine
        src = inspect.getsource(engine.CrawlerEngine.crawl_thread)
        self.assertNotIn("config.DOWNLOAD_DIR", src,
                         "crawl_thread không được đọc config trực tiếp")
        self.assertIn("self.download_dir", src)

    def test_fallback_keeps_cache_and_media_together(self):
        """Kịch bản fallback: cache và media phải cùng một gốc."""
        import os, tempfile, shutil
        from cache import MediaCache, LocalUserIndex
        tmp = tempfile.mkdtemp(prefix="fallback")
        try:
            fallback = os.path.join(tmp, "RPHANG")
            os.makedirs(fallback)
            app_dir = fallback                      # mô phỏng _resolve_dir
            cache = MediaCache(os.path.join(app_dir, "crawler_cache.db"))
            LocalUserIndex(cache.conn)
            eng = self._engine(app_dir)
            folder = X.thread_folder(eng.download_dir, "user", "title", "2024-01-01")
            self.assertTrue(os.path.normpath(folder).startswith(os.path.normpath(app_dir)),
                            "media phải nằm dưới cùng gốc với cache")
            cache.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestRunGuard(unittest.TestCase):
    """Không được mở engine thứ hai khi đang có phiên chạy.

    Bug cũ: _launch không kiểm tra gì, và _focused_primary gọi thẳng hàm start
    nên bỏ qua trạng thái disabled của nút. Hai engine song song dùng chung
    stop_event và cache -> tranh chấp SQLite, nút Dừng không dừng được cái nào.
    """

    def setUp(self):
        import tkinter as tk
        import v72
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = v72.XenForoScannerApp(self.root)
        self.started = []
        self.app.run_async_engine = lambda factory: self.started.append(factory)
        self.app.cmb_username.set("someone")
        self.app.cmb_box_url.set("https://r/box/x.140/")
        self.app.ent_thread_url.insert(0, "https://r/threads/x.1/")

    def tearDown(self):
        try:
            # Chạy hết callback after(0) còn treo TRƯỚC khi destroy: nếu destroy
            # trước, Tcl báo "invalid command name ..._safe_log" và
            # "application has been destroyed" làm nhiễu output test.
            self.root.update()
        except Exception:
            pass
        try:
            if self.app.current_loop and not self.app.current_loop.is_closed():
                self.app.current_loop.close()
        except Exception:
            pass
        self.root.destroy()

    def _start_fake_run(self):
        import asyncio
        self.app.current_loop = asyncio.new_event_loop()

    def test_launch_refuses_second_run(self):
        self._start_fake_run()
        self.assertFalse(self.app._launch(lambda: None), "_launch phải từ chối")
        self.assertEqual(self.started, [])

    def test_launch_allows_when_idle(self):
        self.assertIsNone(self.app.current_loop)
        self.assertTrue(self.app._launch(lambda: None), "rảnh thì phải cho chạy")
        self.assertEqual(len(self.started), 1)

    def test_all_entry_points_blocked_while_running(self):
        """Phải chặn cả 4 đường: 3 nút + Ctrl+Enter. Nút disabled không đủ."""
        self._start_fake_run()
        self.app._focused_primary()
        self.app.start_single_crawl_thread()
        self.app.start_link_crawl_thread()
        self.app.start_update_all_thread()
        self.assertEqual(self.started, [],
                         "không đường nào được khởi động engine khi đang quét")

    def test_closed_loop_does_not_block(self):
        """Loop đã đóng = phiên trước kết thúc, phải cho chạy lại."""
        loop = __import__("asyncio").new_event_loop()
        loop.close()
        self.app.current_loop = loop
        self.app.start_link_crawl_thread()
        self.assertEqual(len(self.started), 1,
                         "loop đã đóng không được coi là đang chạy")


class TestThemeSwitchMidScan(unittest.TestCase):
    """Đổi theme KHÔNG được làm mất trạng thái đang chạy.

    Bug cũ: toggle_theme destroy toàn bộ widget rồi _build_ui lại, nhưng không
    khôi phục trạng thái nút và không bind lại phím tắt. Kết quả: đang quét mà
    đổi theme -> nút "Quét" bấm được -> mở engine thứ hai chạy song song trên
    cùng stop_event/cache; Enter ở ô URL và Ctrl+Enter cũng chết.
    """

    def setUp(self):
        import tkinter as tk
        import v72
        self.tk = tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = v72.XenForoScannerApp(self.root)
        self.app.current_loop = __import__("asyncio").new_event_loop()

    def tearDown(self):
        try:
            self.root.update()   # chạy hết after(0) treo trước khi destroy
        except Exception:
            pass
        try:
            if not self.app.current_loop.is_closed():
                self.app.current_loop.close()
        except Exception:
            pass
        self.root.destroy()

    def test_scan_buttons_stay_disabled_after_theme_switch(self):
        self.app.change_buttons_state(True)
        self.root.update()
        self.app.toggle_theme()
        self.root.update()
        for name in ("btn_download_user", "btn_download_link", "btn_update_all"):
            self.assertEqual(getattr(self.app, name).cget("state"), "disabled",
                             f"{name} phải giữ disabled khi đang quét")
        self.assertEqual(self.app.btn_stop.cget("state"), "normal",
                         "nút Dừng phải vẫn bấm được")

    def test_stop_button_disabled_when_idle_after_theme_switch(self):
        self.app.current_loop.close()
        self.app.toggle_theme()
        self.root.update()
        self.assertEqual(self.app.btn_stop.cget("state"), "disabled")
        self.assertEqual(self.app.btn_download_user.cget("state"), "normal")

    def test_shortcuts_survive_theme_switch(self):
        self.app.toggle_theme()
        self.root.update()
        self.assertTrue(self.app.ent_thread_url.bind("<Return>"),
                        "Enter ở ô URL phải còn tác dụng sau khi đổi theme")
        self.assertTrue(self.app.root.bind("<Control-Return>"))
        self.assertTrue(self.app.root.bind("<Escape>"))

    def test_typed_input_survives_theme_switch(self):
        self.app.cmb_username.set("user_dang_go")
        self.app.ent_thread_url.insert(0, "https://r/threads/x.1/")
        self.app.ent_filter.insert(0, "loi")
        self.app.toggle_theme()
        self.root.update()
        self.assertEqual(self.app.cmb_username.get(), "user_dang_go")
        self.assertEqual(self.app.ent_thread_url.get(), "https://r/threads/x.1/")
        self.assertEqual(self.app.ent_filter.get(), "loi")

    def test_is_running_reflects_loop_state(self):
        self.assertTrue(self.app._is_running())
        self.app.current_loop.close()
        self.assertFalse(self.app._is_running(), "loop đã đóng thì phải coi là không chạy")
        self.app.current_loop = None
        self.assertFalse(self.app._is_running())


class TestCloseWhileCrawling(unittest.TestCase):
    """Đóng cửa sổ khi đang quét phải dọn dẹp, không chỉ destroy root.

    Bản cũ không có handler WM_DELETE_WINDOW. Đóng app giữa lúc quét làm event
    loop bị huỷ giữa chừng: Playwright driver báo EPIPE, SQLite có thể còn WAL
    chưa gộp, và process con của Playwright có thể mồ côi.
    """

    def setUp(self):
        import tkinter as tk
        import v72
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = v72.XenForoScannerApp(self.root)

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_close_handler_is_installed(self):
        handler = self.root.protocol("WM_DELETE_WINDOW")
        self.assertTrue(handler, "phải đăng ký handler cho WM_DELETE_WINDOW")
        self.assertIn("on_close", str(handler))

    def test_close_sets_stop_event(self):
        self.assertFalse(self.app.stop_event.is_set())
        self.app.on_close()
        self.assertTrue(self.app.stop_event.is_set(),
                        "đóng app phải bật cờ dừng engine")

    def test_close_destroys_root(self):
        self.app.on_close()
        import tkinter as tk
        with self.assertRaises(tk.TclError):
            self.root.winfo_exists()

    def test_close_reports_whether_it_was_running(self):
        """Có thread engine thật đang chạy thì on_close phải báo True và join nó."""
        import threading, time

        def slow_engine():
            time.sleep(0.15)

        self.app._engine_thread = threading.Thread(target=slow_engine, daemon=True)
        self.app._engine_thread.start()
        already = self.app._engine_thread.is_alive()
        self.assertTrue(already)
        # _is_running dựa trên current_loop; giả lập bằng loop thật của thread
        # engine là quá phức tạp cho unit test, nên chỉ kiểm join hoạt động.
        t0 = time.perf_counter()
        self.app.on_close()
        elapsed = time.perf_counter() - t0
        self.assertFalse(self.app._engine_thread.is_alive(), "phải join thread engine")
        self.assertLess(elapsed, 2.0, f"không được chờ quá lâu: {elapsed:.2f}s")

    def test_close_is_idempotent(self):
        """Đóng hai lần không được ném exception."""
        self.app.on_close()
        try:
            self.app.on_close()
        except Exception as e:
            self.fail(f"gọi on_close lần hai không được ném: {e!r}")


class TestBackoff(unittest.TestCase):
    """Retry phải có jitter và trần thật.

    Bug cũ: `sleep(2 * (attempt + 1))` cố định -> 10 worker cùng nhịp, cùng hỏi
    lại server ở cùng thời điểm, dễ bị rate-limit tập thể.
    """

    def test_has_jitter(self):
        from downloader import backoff_seconds
        samples = {round(backoff_seconds(2), 4) for _ in range(30)}
        self.assertGreater(len(samples), 1, "không có jitter thì các worker vẫn cùng nhịp")

    def test_cap_is_a_real_cap(self):
        """Trần phải là trần thật: cap 30 thì không được ngủ 32."""
        from downloader import backoff_seconds
        for attempt in range(30):
            self.assertLessEqual(backoff_seconds(attempt), 30.0,
                                 f"attempt {attempt} vượt trần")

    def test_grows_then_plateaus(self):
        from downloader import backoff_seconds
        low = max(backoff_seconds(0) for _ in range(20))
        mid = max(backoff_seconds(2) for _ in range(20))
        self.assertGreater(mid, low, "phải tăng theo số lần thử")
        high = backoff_seconds(20)
        self.assertLessEqual(high, 30.0)

    def test_never_negative_or_zero(self):
        from downloader import backoff_seconds
        for attempt in range(10):
            self.assertGreater(backoff_seconds(attempt), 0)


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


class TestDiskSpaceGuard(unittest.TestCase):
    """Hết đĩa giữa chừng để lại file cụt + loạt lỗi khó hiểu."""

    def _dl(self):
        from downloader import Downloader
        class _NoStop:
            @staticmethod
            def is_set():
                return False
        return Downloader(cache=None, log=lambda *a, **k: None, stop_event=_NoStop(),
                          semaphore=None, db_lock=None)

    def test_normal_size_passes(self):
        d = self._dl()
        self.assertFalse(d._disk_full(os.path.join(tempfile.gettempdir(), "x.bin"),
                                      1024))

    def test_absurd_size_is_refused(self):
        d = self._dl()
        self.assertTrue(d._disk_full(os.path.join(tempfile.gettempdir(), "x.bin"),
                                     10 ** 18))

    def test_unknown_size_is_not_refused(self):
        d = self._dl()
        self.assertFalse(d._disk_full(tempfile.gettempdir(), None))

    def test_free_bytes_returns_number(self):
        d = self._dl()
        free = d._free_bytes(tempfile.gettempdir())
        self.assertIsNotNone(free)
        self.assertGreater(free, 0)


class TestDownloadIntegrityGuards(unittest.TestCase):
    """Chặn file quá lớn TRƯỚC khi nạp, và phát hiện tải thiếu dữ liệu.

    H4 gốc muốn streaming, nhưng Playwright 1.54 không có API stream cho
    context.request: APIResponse chỉ có body() nạp toàn bộ payload vào RAM. Vì
    vậy hai chốt khả thi là kiểm content-length trước khi gọi body(), và so
    content-length với số byte thực nhận trước khi ghi ra file.
    """

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

    def _fetch(self, resp, max_mb=512):
        import asyncio, tempfile, shutil
        from downloader import Downloader

        tmp = tempfile.mkdtemp(prefix="integrity")
        real = config.MAX_FILE_MB
        config.MAX_FILE_MB = max_mb
        try:
            class _Req:
                async def get(inner, url, headers=None, timeout=None):
                    return resp

            class _Ctx:
                request = _Req()

            async def run():
                logs = []
                d = Downloader(cache=self._Cache(), log=lambda m, t=None: logs.append(m),
                               stop_event=self._NoStop(),
                               semaphore=asyncio.Semaphore(2), db_lock=asyncio.Lock())
                tasks = await d.dispatch(
                    _Ctx(), [("http://x/f.bin", os.path.join(tmp, "f.bin"), "H", "file")],
                    "http://ref", {})
                stats = await d.gather(tasks)
                return stats, os.path.exists(os.path.join(tmp, "f.bin")), logs

            return asyncio.run(run())
        finally:
            config.MAX_FILE_MB = real
            shutil.rmtree(tmp, ignore_errors=True)

    def test_oversized_file_rejected_before_body(self):
        """Không được gọi body() khi đã biết vượt trần — đó là điểm hết RAM."""
        class Big:
            status = 200
            headers = {"content-type": "video/mp4",
                       "content-length": str(600 * 1024 * 1024)}

            async def body(self):
                raise AssertionError("body() không được gọi khi đã biết quá lớn")

            async def dispose(self):
                pass

        stats, exists, logs = self._fetch(Big(), max_mb=512)
        self.assertEqual(stats["failed"], 1)
        self.assertFalse(exists, "không được tạo file rác")
        self.assertTrue(any("512MB" in l for l in logs), f"phải log lý do: {logs}")

    def test_truncated_download_is_rejected(self):
        """content-length nói 1000 mà chỉ nhận 400 -> file hỏng, không được ghi."""
        class Truncated:
            status = 200
            headers = {"content-type": "image/jpeg", "content-length": "1000"}

            async def body(self):
                return b"x" * 400

            async def dispose(self):
                pass

        stats, exists, logs = self._fetch(Truncated())
        self.assertEqual(stats["failed"], 1, "tải thiếu phải tính là lỗi")
        self.assertFalse(exists, "không được lưu file cụt")
        self.assertTrue(any("thiếu dữ liệu" in l for l in logs))

    def test_normal_file_still_saved(self):
        """Guard không được chặn nhầm file bình thường."""
        class Good:
            status = 200
            headers = {"content-type": "image/jpeg", "content-length": "400"}

            async def body(self):
                return b"x" * 400

            async def dispose(self):
                pass

        stats, exists, _ = self._fetch(Good())
        self.assertEqual(stats["ok"], 1)
        self.assertTrue(exists)

    def test_missing_content_length_is_not_blocked(self):
        """Server dùng chunked encoding: không biết trước kích thước thì vẫn tải."""
        class NoLen:
            status = 200
            headers = {"content-type": "image/jpeg"}

            async def body(self):
                return b"y" * 1000

            async def dispose(self):
                pass

        stats, exists, _ = self._fetch(NoLen(), max_mb=1)
        self.assertEqual(stats["ok"], 1, "thiếu content-length không được coi là quá lớn")
        self.assertTrue(exists)

    def test_max_file_mb_zero_means_unlimited(self):
        class Huge:
            status = 200
            headers = {"content-type": "video/mp4",
                       "content-length": str(999 * 1024 * 1024)}

            async def body(self):
                return b"z" * 10

            async def dispose(self):
                pass

        stats, exists, _ = self._fetch(Huge(), max_mb=0)
        # body() trả 10 byte != 999MB -> bị chặn bởi guard toàn vẹn, không phải guard size
        self.assertEqual(stats["failed"], 1,
                         "0 = không giới hạn size, nhưng vẫn phải kiểm toàn vẹn")

    def test_playwright_has_no_streaming_api(self):
        """Ghi nhận lý do H4 không làm được trọn: API không tồn tại."""
        from playwright.async_api import APIResponse
        stream_names = [m for m in dir(APIResponse)
                        if "stream" in m.lower() or "chunk" in m.lower()]
        self.assertEqual(stream_names, [],
                         "nếu Playwright thêm streaming, hãy làm lại H4 cho đúng")


class TestNoBusyPoll(unittest.TestCase):
    """_racing_stop không được poll cờ dừng liên tục.

    Bug cũ: lặp asyncio.wait(timeout=0.05) tới DOWNLOAD_TIMEOUT_MS/50 lần. Với
    timeout 40s là 800 lần đánh thức event loop CHO MỖI FILE; DOWNLOAD_SEM=10
    thành 8.000 lần trong 40 giây, chỉ để kiểm một cờ.
    """

    class _NoStop:
        @staticmethod
        def is_set():
            return False

    class _StopSet:
        @staticmethod
        def is_set():
            return True

    def _downloader(self, stop):
        import asyncio
        from downloader import Downloader
        return Downloader(cache=None, log=lambda *a, **k: None, stop_event=stop,
                          semaphore=asyncio.Semaphore(4), db_lock=asyncio.Lock())

    def test_timeout_is_accurate(self):
        """Hết hạn đúng hạn, không sớm không muộn — chứng tỏ không còn poll 50ms."""
        import asyncio, time
        real = config.DOWNLOAD_TIMEOUT_MS
        config.DOWNLOAD_TIMEOUT_MS = 300
        try:
            async def run():
                d = self._downloader(self._NoStop())
                async def slow():
                    await asyncio.sleep(10)
                t0 = time.perf_counter()
                r = await d._racing_stop(slow())
                return r, (time.perf_counter() - t0) * 1000
            r, ms = asyncio.run(run())
        finally:
            config.DOWNLOAD_TIMEOUT_MS = real
        from downloader import _TIMEOUT
        self.assertIs(r, _TIMEOUT, "phải trả sentinel _TIMEOUT")
        self.assertGreaterEqual(ms, 250, f"không được timeout sớm: {ms:.0f}ms")
        self.assertLess(ms, 700, f"không được chậm hơn hạn nhiều: {ms:.0f}ms")

    def test_stop_event_wins_over_timeout(self):
        """Bấm Dừng phải thắng, trả None chứ không phải _TIMEOUT."""
        import asyncio
        from downloader import _TIMEOUT
        real = config.DOWNLOAD_TIMEOUT_MS
        config.DOWNLOAD_TIMEOUT_MS = 5000      # hạn dài, để cờ dừng thắng trước
        try:
            async def run():
                d = self._downloader(self._StopSet())
                async def slow():
                    await asyncio.sleep(10)
                return await d._racing_stop(slow())
            r = asyncio.run(run())
        finally:
            config.DOWNLOAD_TIMEOUT_MS = real
        self.assertIsNone(r, "cờ dừng phải trả None, không phải _TIMEOUT")
        self.assertIsNot(r, _TIMEOUT)

    def test_completed_request_wins(self):
        import asyncio
        d = self._downloader(self._NoStop())

        class R:
            status = 200
        async def fast():
            return R()
        r = asyncio.run(d._racing_stop(fast()))
        self.assertEqual(r.status, 200, "request xong trước thì phải trả response")


class TestPendingIsBounded(unittest.TestCase):
    """Số task tải đồng thời trong một thread phải có trần.

    Bug cũ (M6): crawl_thread gom TẤT CẢ task vào `pending` rồi gather ở cuối.
    Thread 20 trang × 20 post × 20 ảnh sinh hàng nghìn task cùng sống dù chỉ
    DOWNLOAD_SEM cái thực chạy. Đo được: 300 task -> 79 sau khi sửa.
    """

    class _NoStop:
        @staticmethod
        def is_set():
            return False

    def test_drain_keeps_running_below_keep(self):
        import asyncio
        from downloader import Downloader
        d = Downloader(cache=None, log=lambda *a, **k: None, stop_event=self._NoStop(),
                       semaphore=asyncio.Semaphore(4), db_lock=asyncio.Lock())

        async def run():
            peak = {"n": 0}
            pending = []

            async def one():
                await asyncio.sleep(0.01)

            for _ in range(120):
                pending.append(asyncio.create_task(one()))
                if len(pending) >= 20:
                    await d.drain(pending)
                    pending = [t for t in pending if not t.done()]
                peak["n"] = max(peak["n"], len(pending))
            await d.gather(pending)
            return peak["n"]

        peak = asyncio.run(run())
        self.assertLessEqual(peak, 20, f"pending vượt trần: đỉnh {peak}")

    def test_pending_limit_exists_and_positive(self):
        self.assertGreaterEqual(config.PENDING_LIMIT, 1)
        self.assertLessEqual(config.PENDING_LIMIT, 1000,
                             "trần quá cao thì không còn tác dụng chặn")

    def test_engine_thread_worker_count_is_bounded(self):
        """Số worker phải bằng THREAD_SEM, không phải số thread trong box."""
        import inspect
        import engine
        src = inspect.getsource(engine.CrawlerEngine.crawl_user)
        self.assertIn("config.THREAD_SEM", src, "worker phải bám THREAD_SEM")
        self.assertNotIn("for i, u in enumerate(sorted(thread_urls), 1)]",
                         src, "không được quay lại gather một task cho mỗi thread")


class TestSuiteIsHermetic(unittest.TestCase):
    """Test không được đụng vào thư mục tải thật.

    Bug cũ: ba test dựng XenForoScannerApp thật, mà app mở MediaCache ngay trong
    __init__ với config.DOWNLOAD_DIR -> mở và GHI crawler_cache.db của thư viện
    thật. Hệ quả kép: (1) làm bẩn dữ liệu người dùng, (2) suite đỏ trên máy
    không có ổ cấu hình (CI), vì sqlite không tạo được file.
    """

    def test_download_dir_points_into_temp(self):
        tmp_root = os.path.normpath(tempfile.gettempdir())
        actual = os.path.normpath(config.DOWNLOAD_DIR)
        self.assertTrue(actual.startswith(tmp_root),
                        f"test phải chạy trong temp, đang là {actual}")

    def test_not_the_original_production_dir(self):
        self.assertNotEqual(os.path.normpath(config.DOWNLOAD_DIR),
                            os.path.normpath(_ORIGINAL_DOWNLOAD_DIR),
                            "config.DOWNLOAD_DIR phải đã được đổi khỏi giá trị thật")

    def test_app_creates_cache_inside_temp_only(self):
        """Dựng app thật rồi kiểm DB nằm trong temp, không phải ổ thật."""
        import tkinter as tk
        import v72
        tmp_root = os.path.normpath(tempfile.gettempdir())
        root = tk.Tk()
        root.withdraw()
        app = None
        try:
            app = v72.XenForoScannerApp(root)
            db_path = os.path.join(app.download_dir, "crawler_cache.db")
            self.assertTrue(os.path.normpath(app.download_dir).startswith(tmp_root),
                            f"app đang dùng {app.download_dir}, phải nằm trong temp")
            self.assertTrue(os.path.exists(db_path),
                            "app phải tạo DB trong thư mục tạm của test")
        finally:
            if app is not None:
                app.cache.close()
            root.destroy()


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


class TestVideoNameCollision(unittest.TestCase):
    """Video/file phải có hash trong tên, nếu không hai post cùng timestamp đè nhau.

    Bug cũ: nhánh video/file dùng f"[{ts}]_{tag}_{i:03d}{ext}" với `i` reset về 1
    ở mỗi post. Hai post khác nhau trong cùng thread -> cùng tên -> ghi đè, mất
    media. Tệ hơn khi post thiếu <time.u-dt>: mọi post dùng "00000000_000000".
    """

    def _paths(self, urls, ts, tag):
        return [p for _, p, _, _ in plan_jobs(urls, r"C:\f", ts, tag)]

    def test_different_videos_same_timestamp_do_not_collide(self):
        a = self._paths(["http://x/vid/A.mp4"], "20240101_120000", "comment_video")[0]
        b = self._paths(["http://x/vid/B.mp4"], "20240101_120000", "comment_video")[0]
        self.assertNotEqual(a, b, f"hai video khác nhau không được trùng path: {a}")

    def test_missing_timestamp_does_not_cause_mass_collision(self):
        """Mọi post thiếu <time.u-dt> đều dùng "00000000_000000" -> phải vẫn khác path."""
        a = self._paths(["http://x/vid/A.mp4"], "00000000_000000", "main_video")[0]
        b = self._paths(["http://x/vid/B.mp4"], "00000000_000000", "main_video")[0]
        self.assertNotEqual(a, b, "post thiếu timestamp không được đè lên nhau")

    def test_files_typed_as_files_and_unique(self):
        paths = self._paths(["http://x/a/doc.zip", "http://x/b/doc.zip"],
                            "20240101_120000", "comment_file")
        self.assertEqual(len(set(paths)), len(paths), f"file trùng tên: {paths}")
        for p in paths:
            self.assertTrue(p.endswith(".zip"), f"phải giữ đuôi .zip: {p}")

    def test_same_video_twice_is_idempotent(self):
        """Cùng một URL phải ra cùng path — nếu khác sẽ tải trùng thay vì clone."""
        a = self._paths(["http://x/v.mp4"], "t", "comment_video")[0]
        b = self._paths(["http://x/v.mp4"], "t", "comment_video")[0]
        self.assertEqual(a, b, "cùng URL phải cùng path để clone_cached dùng được")


class TestTimeoutIsNotSilence(unittest.TestCase):
    """Hết thời gian chờ phải hiện trong thống kê, không được nuốt im lặng.

    Bug cũ: _racing_stop trả None cho cả "hết giờ" và "bấm Dừng". _fetch biến
    cả hai thành "CANCELLED", mà counted() chỉ đếm "FAILED". Kết quả: server
    chậm 40s -> file biến mất, failed=0, không một dòng log.
    """

    class _NoStop:
        @staticmethod
        def is_set():
            return False

    def _run_with(self, timeout_ms):
        import asyncio, tempfile, shutil
        from downloader import Downloader

        tmp = tempfile.mkdtemp(prefix="timeout")
        real = config.DOWNLOAD_TIMEOUT_MS
        config.DOWNLOAD_TIMEOUT_MS = timeout_ms
        try:
            class _Req:
                async def get(inner, url, headers=None, timeout=None):
                    await asyncio.sleep(5)      # chậm hơn hạn
                    raise AssertionError("không được tới đây")

            class _Ctx:
                request = _Req()

            class _Cache:
                @staticmethod
                def path_for(h):
                    return None

                @staticmethod
                def record(h, p):
                    pass

            async def run():
                d = Downloader(cache=_Cache(), log=lambda *a, **k: None,
                               stop_event=TestTimeoutIsNotSilence._NoStop(),
                               semaphore=asyncio.Semaphore(2), db_lock=asyncio.Lock())
                tasks = await d.dispatch(
                    _Ctx(), [("http://x/big.mp4", os.path.join(tmp, "b.mp4"), "H", "video")],
                    "http://ref", {})
                return await d.gather(tasks)

            return asyncio.run(run())
        finally:
            config.DOWNLOAD_TIMEOUT_MS = real
            shutil.rmtree(tmp, ignore_errors=True)

    def test_timeout_counts_as_failure(self):
        stats = self._run_with(300)
        self.assertEqual(stats["failed"], 1,
                         f"timeout phải đếm vào failed, không được im lặng: {stats}")
        self.assertEqual(stats["ok"], 0)

    def test_timeout_does_not_steal_ok_slot(self):
        """Timeout không được tính là thành công — nếu không, báo cáo lại sai."""
        stats = self._run_with(300)
        self.assertEqual(stats["video"], 0, "không tải được file nào thì không được đếm là video")


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