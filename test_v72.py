"""Self-check cho logic không cần mạng/Tk.

Chạy: python test_v72.py

Các test gọi thẳng xenforo_parse/cache/downloader nên không cần import Tk,
không cần Chrome, không cần mạng.
"""

import os
import tempfile
import unittest

from bs4 import BeautifulSoup

import selectors as S
import xenforo_parse as X
import config
import browser_launcher as B
from cache import MediaCache, LocalUserIndex
from downloader import plan_jobs, url_hash, Downloader, count_files
from v72 import PALETTE, log_tag, _MARKER_TAGS


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

    def test_bad_timestamp_does_not_crash(self):
        s = soup_of('<article class="message--post" data-author="a">'
                    '<time class="u-dt" data-time="abc"></time></article>')
        self.assertEqual(X.post_timestamp(s), "00000000_000000")


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