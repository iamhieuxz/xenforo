"""GUI Tk + vòng đời tiến trình.

run_async_engine luôn trả UI về trạng thái normal trong finally: bản cũ không có
try/finally nên một exception là thread chết, loop không đóng và 3 nút kẹt
vĩnh viễn ở trạng thái disabled.
"""

import asyncio
import os
import re
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

import config
import browser_launcher
from cache import MediaCache, LocalUserIndex
from engine import CrawlerEngine

# Mỗi loại thông báo một màu riêng, tất cả đủ tương phản trên nền BG_INPUT.
LOG_COLORS = {
    "error":   "#f87171",   # [-] lỗi
    "summary": "#fb923c",   # [!] cảnh báo, tệp lỗi đường truyền
    "success": "#4ade80",   # [✓] [+] xong
    "info":    "#38bdf8",   # [*] đang chạy
    "system":  "#22d3ee",   # [*] dòng khởi động app
    "bulk":    "#c084fc",   # cập nhật đa luồng
    "skip":    "#94a3b8",   # [•] trùng khớp, bỏ qua
    "dim":     "#64748b",   # dấu phân cách, dòng chưa phân loại
}

# Dấu mở đầu dòng -> tag. Engine/downloader đã viết sẵn dấu này ở mọi tin,
# nên suy ra màu ở đây thay vì sửa từng chỗ gọi log (23 chỗ đang thiếu tag).
_MARKER_TAGS = {
    "-": "error",
    "!": "summary",
    "✓": "success",
    "+": "success",
    "↓": "info",
    "•": "skip",
    "*": "info",
}

_MARKER_RE = re.compile(r"^\W{0,4}\[([-!✓+↓•*])\]")


def log_tag(message, tag=None):
    """Tag màu cho một dòng log. Ưu tiên tag truyền vào, không có thì đoán từ dấu ở đầu.

    Dòng '👥 [USER 1/2] ...' có emoji trước dấu nên phải cho phép ký tự không phải
    chữ ở trước. Neo ^\W{0,4} để không bắt nhầm dấu ngoặc nằm giữa dòng (URL)."""
    if tag:
        return tag
    m = _MARKER_RE.match(message)
    if m:
        return _MARKER_TAGS[m.group(1)]
    return "dim"


class XenForoScannerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("XENFORO ULTIMATE - V72 ENGINE")
        self.root.geometry("960x920")

        self.BG_MAIN = "#090d16"
        self.BG_CARD = "#141a29"
        self.BG_INPUT = "#1c2438"
        self.FG_TEXT = "#ffffff"
        self.FG_SUB = "#707e94"

        self.COLOR_GREEN = "#4ade80"
        self.COLOR_BLUE = "#38bdf8"
        self.COLOR_RED = "#f87171"
        self.COLOR_ORANGE = "#fbbf24"
        self.COLOR_DISABLED = "#2e394e"

        self.FONT_TITLE = ("Segoe UI", 15, "bold")
        self.FONT_CARD_HEADER = ("Segoe UI", 10, "bold")
        self.FONT_MAIN = ("Segoe UI", 10)
        self.FONT_BTN = ("Segoe UI", 10, "bold")

        self.root.configure(bg=self.BG_MAIN)
        self._enable_dark_titlebar()

        self.stop_event = threading.Event()
        self.download_dir = config.DOWNLOAD_DIR
        self.current_loop = None
        self.engine = None

        self._resolve_dir()
        self.cache = MediaCache(os.path.join(self.download_dir, "crawler_cache.db"))
        self.local_users = LocalUserIndex(self.cache.conn)
        self._scan_local_users()

        self._build_ui()

        if self._boot_error:
            self.log(f"[-] {self._boot_error}", "error")
        self.log(f"[*] V72 ENGINE: Playwright Native Fetch • cache: {self.download_dir}", "system")

    def auto_launch_browser(self):
        """Bật trình duyệt cổng 9222 ngay khi mở app (chạy ngoài GUI để không treo)."""
        if not config.AUTO_LAUNCH_BROWSER:
            return
        if browser_launcher.is_port_open():
            self.log(f"[*] Cổng {config.CDP_PORT} đã sẵn sàng.", "system")
            return

        def work():
            ok, msg = browser_launcher.launch()
            self.log(f"[{'✓' if ok else '!'}] {msg}", "system" if ok else "error")

        threading.Thread(target=work, daemon=True).start()

    # ---------- khởi tạo ----------
    def _enable_dark_titlebar(self):
        try:
            import ctypes
            self.root.update()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            dark = ctypes.c_int(1)
            for attr in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(dark), ctypes.sizeof(dark))
        except Exception:
            pass

    def _resolve_dir(self):
        """Ổ cứng khác máy thì vẫn chạy được thay vì crash lúc khởi động."""
        try:
            os.makedirs(self.download_dir, exist_ok=True)
            self._boot_error = None
        except OSError as e:
            fallback = os.path.join(os.path.expanduser("~"), "RPHANG")
            os.makedirs(fallback, exist_ok=True)
            self.download_dir = fallback
            self._boot_error = f"Không tạo được thư mục gốc, chuyển sang: {fallback} ({e})"

    def _default_user(self):
        """User đầu tiên trong danh sách, hoặc giá trị cũ nếu ổ còn trống."""
        names = self.local_users.names()
        return names[0] if names else "traicube"

    def _scan_local_users(self):
        """Quét ổ một lần lúc mở app, đọc từ DB cho các lần sau."""
        try:
            n = self.local_users.refresh(self.download_dir)
            if n:
                self.log(f"[*] Đã nạp {n} user local từ ổ.", "system")
            else:
                self.log("[-] Chưa có user nào trên ổ.", "summary")
            return n
        except Exception as e:
            self.log(f"[!] Không đọc được danh sách user local: {e}", "error")
            return 0

    def _build_ui(self):
        header = tk.Frame(self.root, bg=self.BG_MAIN, padx=25, pady=15)
        header.pack(fill="x")
        tk.Label(header, text="What's up, Crawler Engine", bg=self.BG_MAIN, fg=self.FG_TEXT,
                 font=self.FONT_TITLE).pack(anchor="w")
        tk.Label(header, text="Dynamic Expansion Core • Playwright Native Fetch • Local Validator",
                 bg=self.BG_MAIN, fg=self.FG_SUB, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        grid = tk.Frame(self.root, bg=self.BG_MAIN, padx=20)
        grid.pack(fill="x", pady=5)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        card_config = tk.Frame(grid, bg=self.BG_CARD, padx=20, pady=15)
        card_config.grid(row=0, column=0, sticky="nwes", padx=(0, 10))
        tk.Label(card_config, text="🎯 TARGET INFORMATION", bg=self.BG_CARD, fg=self.COLOR_GREEN,
                 font=self.FONT_CARD_HEADER).pack(anchor="w", pady=(0, 10))

        self.cmb_box_url = self._combo(card_config, "Link Chuyên Mục (Box URL)",
                                       config.BOX_PRESETS[0], config.BOX_PRESETS)
        self.cmb_username = self._combo(card_config, "Username quét đơn",
                                       self._default_user(), self.local_users.names())
        self.ent_thread_url = self._entry(card_config, "Nhập Link Bài Viết (URL)", "")

        card_control = tk.Frame(grid, bg=self.BG_CARD, padx=20, pady=15)
        card_control.grid(row=0, column=1, sticky="nwes", padx=(10, 0))
        tk.Label(card_control, text="🛠️ SYSTEM CONTROLS", bg=self.BG_CARD, fg=self.COLOR_BLUE,
                 font=self.FONT_CARD_HEADER).pack(anchor="w", pady=(0, 10))

        btn_grid = tk.Frame(card_control, bg=self.BG_CARD)
        btn_grid.pack(fill="x", pady=(0, 8))
        btn_grid.columnconfigure(0, weight=1)
        btn_grid.columnconfigure(1, weight=1)

        self.btn_download_user = tk.Button(btn_grid, text="Quét 1 User", bg=self.COLOR_GREEN, fg=self.BG_MAIN,
                                           font=self.FONT_BTN, bd=0, relief="flat", cursor="hand2", pady=10,
                                           command=self.start_single_crawl_thread)
        self.btn_download_user.grid(row=0, column=0, sticky="we", padx=(0, 4))

        self.btn_download_link = tk.Button(btn_grid, text="Quét 1 Thớt", bg=self.COLOR_BLUE, fg=self.BG_MAIN,
                                           font=self.FONT_BTN, bd=0, relief="flat", cursor="hand2", pady=10,
                                           command=self.start_link_crawl_thread)
        self.btn_download_link.grid(row=0, column=1, sticky="we", padx=(4, 0))

        self.btn_stop = tk.Button(card_control, text="Dừng Khẩn Cấp Tức Thời", bg=self.COLOR_DISABLED,
                                  fg=self.FG_TEXT, font=self.FONT_BTN, bd=0, relief="flat", cursor="hand2",
                                  pady=10, state="disabled", command=self.stop_crawl)
        self.btn_stop.pack(fill="x", pady=(0, 8))

        self.btn_update_all = tk.Button(card_control, text="Kích Hoạt Cập Nhật Tổng Lớn (Bulk Update)",
                                        bg=self.COLOR_ORANGE, fg=self.BG_MAIN, font=self.FONT_BTN, bd=0,
                                        relief="flat", cursor="hand2", pady=11,
                                        command=self.start_update_all_thread)
        self.btn_update_all.pack(fill="x")

        card_monitor = tk.Frame(self.root, bg=self.BG_CARD, padx=20, pady=15)
        card_monitor.pack(fill="both", expand=True, padx=20, pady=(15, 20))
        tk.Label(card_monitor, text="🖥️ TERMINAL OUTPUT MONITOR", bg=self.BG_CARD, fg=self.FG_SUB,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 8))

        self.log_box = scrolledtext.ScrolledText(card_monitor, state='disabled', wrap='word',
                                                 bg=self.BG_INPUT, fg=self.FG_TEXT, font=("Consolas", 10),
                                                 bd=0, padx=12, pady=12)
        self.log_box.pack(fill="both", expand=True)
        for tag, color in LOG_COLORS.items():
            self.log_box.tag_configure(tag, foreground=color, font=("Consolas", 10, "bold"))
        self.log_box.tag_configure("dim", foreground=LOG_COLORS["dim"], font=("Consolas", 10))

    def _entry(self, parent, label, initial):
        tk.Label(parent, text=label, bg=self.BG_CARD, fg=self.FG_SUB,
                 font=("Segoe UI", 9)).pack(anchor="w")
        ent = tk.Entry(parent, bg=self.BG_INPUT, fg=self.FG_TEXT, insertbackground=self.FG_TEXT,
                       font=self.FONT_MAIN, bd=0, highlightthickness=1,
                       highlightbackground=self.BG_INPUT, highlightcolor=self.COLOR_GREEN)
        ent.pack(fill="x", pady=(4, 10), ipady=6, ipadx=5)
        if initial:
            ent.insert(0, initial)
        return ent

    def _combo(self, parent, label, initial, presets):
        """Dropdown gợi ý, vẫn gõ tay tự do.

        Ttk mặc định lấy màu hệ điều hành (sáng) nên phải ép style clam để khớp
        nền tối. Combobox kế thừa Tk vẫn lấy được .get() như các ô khác, nên
        code đọc box_url không phải sửa.
        """
        tk.Label(parent, text=label, bg=self.BG_CARD, fg=self.FG_SUB,
                 font=("Segoe UI", 9)).pack(anchor="w")
        combo = ttk.Combobox(parent, values=presets, font=self.FONT_MAIN)
        combo.set(initial)
        combo.pack(fill="x", pady=(4, 10), ipady=5)
        self._style_combo(combo)
        return combo

    def _style_combo(self, combo):
        s = ttk.Style()
        if "clam" in s.theme_names():
            s.theme_use("clam")
        s.configure("Dark.TCombobox", fieldbackground=self.BG_INPUT,
                    background=self.BG_INPUT, foreground=self.FG_TEXT,
                    arrowcolor=self.FG_TEXT, bordercolor=self.BG_CARD,
                    lightcolor=self.BG_INPUT, darkcolor=self.BG_INPUT,
                    insertcolor=self.FG_TEXT, padding=6, relief="flat")
        s.map("Dark.TCombobox",
              fieldbackground=[("readonly", self.BG_INPUT)],
              foreground=[("readonly", self.FG_TEXT)],
              selectbackground=[("readonly", self.BG_INPUT)],
              selectforeground=[("readonly", self.FG_TEXT)])
        combo.configure(style="Dark.TCombobox")
        # Dropdown listbox nằm ngoài style combobox, phải tô riêng theo theme.
        s.configure("Dark.TCombobox.Listbox", background=self.BG_INPUT,
                    foreground=self.FG_TEXT, selectbackground=self.COLOR_GREEN,
                    selectforeground=self.BG_MAIN, borderwidth=0)
        try:
            # PopdownWindow trả về ĐƯỜNG DẪN widget đầy đủ dạng chuỗi, ví dụ
            # '.!frame.!combobox.popdown'. root.nametowwidget() dùng đúng dạng này.
            lst = "%s.f.l" % combo.tk.call("ttk::combobox::PopdownWindow", combo)
            combo.tk.call(lst, "configure", "-background", self.BG_INPUT,
                          "-foreground", self.FG_TEXT,
                          "-selectbackground", self.COLOR_GREEN,
                          "-selectforeground", self.BG_MAIN,
                          "-borderwidth", 0, "-highlightthickness", 0)
        except tk.TclError:
            pass

    # ---------- log ----------
    def log(self, message, tag=None):
        self.root.after(0, self._safe_log, message, tag)

    def _safe_log(self, message, tag=None):
        try:
            self.log_box.configure(state='normal')
            self.log_box.insert(tk.END, message + "\n", log_tag(message, tag))
            num_lines = int(self.log_box.index('end-1c').split('.')[0])
            if num_lines > 1000:
                self.log_box.delete("1.0", f"{num_lines - 1000}.0")
            self.log_box.configure(state='disabled')
            self.log_box.yview(tk.END)
        except tk.TclError:
            pass

    def change_buttons_state(self, running=True):
        self.root.after(0, self._safe_change_buttons_state, running)

    def _safe_change_buttons_state(self, running):
        if running:
            for btn in (self.btn_download_user, self.btn_download_link, self.btn_update_all):
                btn.config(state="disabled", bg=self.COLOR_DISABLED, fg=self.FG_SUB)
            self.btn_stop.config(state="normal", bg=self.COLOR_RED, fg=self.FG_TEXT)
        else:
            self.btn_download_user.config(state="normal", bg=self.COLOR_GREEN, fg=self.BG_MAIN)
            self.btn_download_link.config(state="normal", bg=self.COLOR_BLUE, fg=self.BG_MAIN)
            self.btn_update_all.config(state="normal", bg=self.COLOR_ORANGE, fg=self.BG_MAIN)
            self.btn_stop.config(state="disabled", bg=self.COLOR_DISABLED, fg=self.FG_SUB)

    # ---------- vòng đời ----------
    def run_async_engine(self, coro_factory):
        """coro_factory: hàm trả về coroutine, gọi BÊN TRONG loop để không khởi tạo
        asyncio primitives ở thread khác (Lock/Semaphore gắn với loop tạo ra chỗ này)."""
        loop = asyncio.new_event_loop()
        self.current_loop = loop
        asyncio.set_event_loop(loop)
        try:
            self.engine = CrawlerEngine(self.cache, self.log, self.stop_event)
            loop.run_until_complete(coro_factory())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log(f"[-] Engine dừng bất thường: {e}", "error")
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            loop.close()
            self.current_loop = None
            self.change_buttons_state(running=False)

    def stop_crawl(self):
        self.stop_event.set()
        loop = self.current_loop
        if loop and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._async_emergency_cleanup)
            except RuntimeError:
                pass

    def _async_emergency_cleanup(self):
        if self.engine:
            self.engine.emergency_cleanup()

    def _launch(self, coro_factory):
        self.stop_event.clear()
        self.change_buttons_state(running=True)
        threading.Thread(target=self.run_async_engine, args=(coro_factory,), daemon=True).start()

    # ---------- điểm vào từ UI ----------
    def start_single_crawl_thread(self):
        target_user = self.cmb_username.get().strip()
        box_url = self.cmb_box_url.get().strip()
        if not target_user:
            self.log("[-] Lỗi: Bạn chưa nhập tên tác giả!", "error")
            return
        if not box_url:
            self.log("[-] Lỗi: Bạn chưa nhập Link Chuyên Mục (Box URL)!", "error")
            return
        self._launch(lambda: self.engine.crawl_users([target_user], box_url))

    def start_link_crawl_thread(self):
        input_url = self.ent_thread_url.get().strip()
        if not input_url:
            self.log("[-] Lỗi: Bạn chưa nhập đường dẫn bài viết!", "error")
            return
        self._launch(lambda: self.engine.crawl_link(input_url))

    def start_update_all_thread(self):
        box_url = self.cmb_box_url.get().strip()
        if not box_url:
            self.log("[-] Lỗi: Bạn chưa nhập Link Chuyên Mục (Box URL)!", "error")
            return
        # Quét lại ổ lúc bấm nút: có thể bạn vừa tải user mới, danh sách trong
        # dropdown còn cũ. Lấy từ DB chứ không os.listdir trực tiếp.
        self.local_users.refresh(self.download_dir)
        local_users = self.local_users.names()
        if not local_users:
            self.log("[-] Chưa có profile nào trên máy local để cập nhật!", "error")
            return
        self._sync_user_dropdown()
        self.log(f"\n[*] Tìm thấy {len(local_users)} User local. Tiến hành cập nhật đa luồng...", "bulk")
        self._launch(lambda: self.engine.crawl_users(local_users, box_url))

    def _sync_user_dropdown(self):
        """Đẩy danh sách mới vào dropdown mà không làm mất user đang gõ."""
        typed = self.cmb_username.get().strip()
        self.cmb_username.configure(values=self.local_users.names())
        self.cmb_username.set(typed)


if __name__ == "__main__":
    app_root = tk.Tk()
    app = XenForoScannerApp(app_root)
    app.auto_launch_browser()
    app_root.mainloop()