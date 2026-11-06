"""Test cho GUI Tkinter (v72.py) + các test GUI cũ. Tách từ test_v72.py (P2.2).

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

from v72 import PALETTE, log_tag, _MARKER_TAGS


import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')


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
        # Lấy từ test_common: giá trị gốc được lưu khi setUpModule chạy.
        import test_common
        self.assertNotEqual(os.path.normpath(config.DOWNLOAD_DIR),
                            os.path.normpath(test_common._ORIGINAL_DOWNLOAD_DIR),
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


