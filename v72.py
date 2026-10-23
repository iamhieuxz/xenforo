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

# Bảng màu xuất phát từ hue hổ phách, chọn độ sáng bằng công thức OKLCH sao cho
# mọi cặp chữ/nền đạt WCAG AA. Accent dùng làm NỀN nút với chữ tối (8:1) chứ
# không phải chữ trắng trên nền tối — đó là chỗ bảng màu cũ bị xỉn.
# Mỗi token đều trả lời trước câu hỏi: nó nằm trên nền nào?
PALETTE = {
    "light": {
        "BG_MAIN":   "#eae5da",   # nền app, kem sáng
        "BG_CARD":   "#fdfbf7",   # thẻ nổi nhẹ trên nền app
        "BG_INPUT":  "#ffffff",
        "BORDER":    "#8c7d5e",   # 3:1 tren ca nen the, o nhap va nen app
        "FG_TEXT":   "#1c1917",
        "FG_SUB":    "#5f574e",
        "ACCENT":    "#f49d08",   # nền nút: chữ tối đặt lên, 8.06:1
        "ACCENT_TXT": "#8f5600",   # accent dùng làm CHỮ, dat tren ca 3 nen
        "ACCENT_HOVER": "#e68f00",
        "FG_ON_ACCENT": "#1c1917",
        "DANGER":    "#f13f39",
        "DISABLED":  "#e4ded1",
        "LOG": {
            "error": "#b42318", "summary": "#9a6700", "success": "#157f3d",
            "info": "#1d4ed8", "system": "#0e7490", "bulk": "#6d28d9",
            "skip": "#57534e", "dim": "#78716c",
        },
    },
    "warm": {
        "BG_MAIN":   "#1f1c19",   # nền app tối ấm, không chìm như bản cũ
        "BG_CARD":   "#2b2724",
        "BG_INPUT":  "#37322d",
        "BORDER":    "#867a6d",
        "FG_TEXT":   "#f7f3ec",
        "FG_SUB":    "#a89e92",
        "ACCENT":    "#9a630b",   # chữ sáng đặt lên, 4.56:1
        "ACCENT_TXT": "#f49d08",  # accent dùng làm CHỮ trên thẻ, 6.82:1
        "ACCENT_HOVER": "#8c5500",
        "FG_ON_ACCENT": "#f7f3ec",
        "DANGER":    "#d82122",
        "DISABLED":  "#2f2a26",
        "LOG": {
            "error": "#fca5a5", "summary": "#fcd34d", "success": "#86efac",
            "info": "#93c5fd", "system": "#67e8f9", "bulk": "#c4b5fd",
            "skip": "#a8a29e", "dim": "#a8a29e",
        },
    },
}

# Đường dẫn file ghi chọn theme, để lần sau mở app vẫn dùng đúng bảng màu đã chọn.
_THEME_FILE = os.path.join(os.path.expanduser("~"), ".xenforo_theme")


def load_theme():
    try:
        with open(_THEME_FILE) as f:
            name = f.read().strip()
        if name in PALETTE:
            return name
    except OSError:
        pass
    return "light"


def save_theme(name):
    try:
        with open(_THEME_FILE, "w") as f:
            f.write(name)
    except OSError:
        pass

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
        self.root.title("XENFORO CRAWLER - V72")
        self.root.geometry("1060x820")
        self.root.minsize(760, 560)

        self.theme_name = load_theme()
        self._apply_palette()

        self.FONT_TITLE = ("Segoe UI", 16, "bold")
        self.FONT_CARD_HEADER = ("Segoe UI", 9, "bold")
        self.FONT_MAIN = ("Segoe UI", 10)
        self.FONT_BTN = ("Segoe UI", 10, "bold")
        self.FONT_MONO = ("Consolas", 10)

        # Giữ N dòng gốc để lọc/copy lại được. Quá nhiều thì nhật ký phình to và
        # vẽ lại chậm; 1000 dòng là quá đủ để đọc lại một phiên quét.
        self.LOG_KEEP = 1000

        self.root.configure(bg=self.BG_MAIN)
        self._enable_dark_titlebar(self.theme_name == "warm")

        self.stop_event = threading.Event()
        self.download_dir = config.DOWNLOAD_DIR
        self.current_loop = None
        self.engine = None
        self._had_error = False    # run_async_engine set khi engine log lỗi
        self._last_detail = ""     # dòng phụ dưới trạng thái, ví dụ "12 ảnh, 3 lỗi"
        self._n_image = 0
        self._n_video = 0
        self._n_error = 0

        self._resolve_dir()
        self.cache = MediaCache(os.path.join(self.download_dir, "crawler_cache.db"))
        self.local_users = LocalUserIndex(self.cache.conn)
        self._scan_local_users()

        self._build_ui()

        if self._boot_error:
            self.log(f"[-] {self._boot_error}", "error")
        self.log(f"[*] V72 ENGINE: Playwright Native Fetch • cache: {self.download_dir}", "system")

    # ---------- bảng màu ----------
    def _apply_palette(self):
        """Đổa token của theme vào thuộc tính cũ để các widget đã dựng lấy màu đúng."""
        p = PALETTE[self.theme_name]
        self.BG_MAIN, self.BG_CARD, self.BG_INPUT = p["BG_MAIN"], p["BG_CARD"], p["BG_INPUT"]
        self.BORDER, self.FG_TEXT, self.FG_SUB = p["BORDER"], p["FG_TEXT"], p["FG_SUB"]
        self.ACCENT, self.ACCENT_HOVER = p["ACCENT"], p["ACCENT_HOVER"]
        self.ACCENT_TXT = p["ACCENT_TXT"]
        self.FG_ON_ACCENT = p["FG_ON_ACCENT"]
        self.LOG_COLORS = p["LOG"]
        self.COLOR_GREEN = p["LOG"]["success"]
        self.COLOR_RED = p["DANGER"]
        self.COLOR_ORANGE = p["LOG"]["summary"]
        self.COLOR_DISABLED = p["DISABLED"]

    def _make_theme_button(self, parent):
        """Nút đổi sáng/tối: ký hiệu + nhãn tiếng Việt, có viền để thấy rõ.

        Ký tự ◐ trần trên nền app rất dễ bị bỏ qua. Nhãn 'Giao diện' nói rõ
        nút làm gì; viền accent tách nó khỏi nền.
        """
        self.btn_theme = tk.Button(
            parent, text="◐  Giao diện", relief="flat", bd=0,
            bg=self.BG_CARD, activebackground=self.ACCENT,
            fg=self.ACCENT_TXT, activeforeground=self.FG_ON_ACCENT,
            highlightbackground=self.BORDER, highlightthickness=1,
            highlightcolor=self.ACCENT,
            font=("Segoe UI", 9, "bold"), cursor="hand2",
            padx=10, pady=6, command=self.toggle_theme)
        self.btn_theme.pack(side="left")

    def toggle_theme(self):
        """Đổi sáng/tối: sửa token rồi dựng lại toàn bộ UI từ nguồn, không vá tay."""
        self.theme_name = "warm" if self.theme_name == "light" else "light"
        save_theme(self.theme_name)
        self._apply_palette()
        self._enable_dark_titlebar(self.theme_name == "warm")
        for child in self.root.winfo_children():
            child.destroy()
        self.root.configure(bg=self.BG_MAIN)
        self._build_ui()
        self._apply_filter()   # _log_lines còn nguyên nên log hiện lại sau khi đổi màu

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
    def _enable_dark_titlebar(self, dark=True):
        try:
            import ctypes
            self.root.update()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            dark = ctypes.c_int(1 if dark else 0)
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
        header = tk.Frame(self.root, bg=self.BG_MAIN, padx=24, pady=18)
        header.pack(fill="x")
        # Cột trái tiêu đề, cột phải trạng thái: dùng weight để trạng thái luôn
        # bám mép phải khi cửa sổ co giãn.
        header.columnconfigure(0, weight=1)

        title_box = tk.Frame(header, bg=self.BG_MAIN)
        title_box.grid(row=0, column=0, sticky="w")
        tk.Label(title_box, text="XENFORO CRAWLER", bg=self.BG_MAIN, fg=self.FG_TEXT,
                 font=self.FONT_TITLE).pack(anchor="w")
        tk.Label(title_box, text="Playwright Native Fetch · Cache SQLite · Dừng khẩn cấp",
                 bg=self.BG_MAIN, fg=self.FG_SUB, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        right_box = tk.Frame(header, bg=self.BG_MAIN)
        right_box.grid(row=0, column=1, sticky="e", padx=(20, 0))
        self._make_theme_button(right_box)

        state_box = tk.Frame(right_box, bg=self.BG_MAIN)
        state_box.pack(side="right", padx=(12, 0))
        self.lbl_state = tk.Label(state_box, text="SẴN SÀNG", bg=self.BG_MAIN, fg=self.FG_SUB,
                                  font=("Segoe UI", 10, "bold"))
        self.lbl_state.pack(anchor="e")
        self.lbl_progress = tk.Label(state_box, text="", bg=self.BG_MAIN, fg=self.FG_SUB,
                                     font=("Segoe UI", 9))
        self.lbl_progress.pack(anchor="e", pady=(2, 0))

        tk.Frame(self.root, bg=self.BORDER, height=1).pack(fill="x", padx=24, pady=(10, 0))

        grid = tk.Frame(self.root, bg=self.BG_MAIN, padx=24, pady=14)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="cards")
        grid.columnconfigure(1, weight=1, uniform="cards")

        card_config = tk.Frame(grid, bg=self.BG_CARD, padx=18, pady=16,
                               highlightbackground=self.BORDER, highlightthickness=1)
        card_config.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self._card_header(card_config, "THÔNG TIN ĐỐI TƯỢNG", self.ACCENT_TXT)

        self.cmb_box_url = self._combo(card_config, "Link Chuyên Mục (Box URL)",
                                       config.BOX_PRESETS[0], config.BOX_PRESETS)
        self.cmb_username = self._combo(card_config, "Username quét đơn",
                                       self._default_user(), self.local_users.names())
        self.ent_thread_url = self._entry(card_config, "Nhập Link Bài Viết (URL)", "")

        card_control = tk.Frame(grid, bg=self.BG_CARD, padx=18, pady=16,
                                highlightbackground=self.BORDER, highlightthickness=1)
        card_control.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self._card_header(card_control, "ĐIỀU KHIỂN", self.FG_SUB)

        btn_grid = tk.Frame(card_control, bg=self.BG_CARD)
        btn_grid.pack(fill="x", pady=(0, 8))
        btn_grid.columnconfigure(0, weight=1, uniform="b")
        btn_grid.columnconfigure(1, weight=1, uniform="b")

        self.btn_download_user = self._button(btn_grid, "Quét 1 User", self.ACCENT,
                                              command=self.start_single_crawl_thread)
        self.btn_download_user.grid(row=0, column=0, sticky="we", padx=(0, 4))

        self.btn_download_link = self._button(btn_grid, "Quét 1 Thớt", self.ACCENT,
                                             command=self.start_link_crawl_thread)
        self.btn_download_link.grid(row=0, column=1, sticky="we", padx=(4, 0))

        self.btn_stop = self._button(card_control, "Dừng khẩn cấp", self.COLOR_DISABLED,
                                    fg=self.FG_SUB, command=self.stop_crawl)
        self.btn_stop.configure(state="disabled")
        self.btn_stop.pack(fill="x", pady=(0, 8))

        self.btn_update_all = self._button(card_control, "Cập nhật toàn bộ User", self.BG_INPUT,
                                           fg=self.FG_TEXT,
                                           command=self.start_update_all_thread)
        self.btn_update_all.pack(fill="x")

        tk.Frame(self.root, bg=self.BORDER, height=1).pack(fill="x", padx=24, pady=(14, 0))

        card_monitor = tk.Frame(self.root, bg=self.BG_CARD, padx=18, pady=14,
                                highlightbackground=self.BORDER, highlightthickness=1)
        card_monitor.pack(fill="both", expand=True, padx=24, pady=(12, 22))
        card_monitor.columnconfigure(0, weight=1)
        card_monitor.rowconfigure(1, weight=1)

        log_bar = tk.Frame(card_monitor, bg=self.BG_CARD)
        log_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tk.Label(log_bar, text="NHẬT KÝ", bg=self.BG_CARD, fg=self.FG_SUB,
                 font=self.FONT_CARD_HEADER).pack(side="left")

        log_tools = tk.Frame(log_bar, bg=self.BG_CARD)
        log_tools.pack(side="right")
        self.ent_filter = tk.Entry(log_tools, bg=self.BG_INPUT, fg=self.FG_TEXT,
                                   insertbackground=self.FG_TEXT, font=self.FONT_MAIN, bd=0,
                                   highlightthickness=1, highlightbackground=self.BORDER,
                                   highlightcolor=self.ACCENT, width=18)
        self.ent_filter.pack(side="left", padx=(0, 6), ipady=4, ipadx=6)
        self.ent_filter.bind("<KeyRelease>", lambda e: self._apply_filter())
        tk.Label(log_tools, text="Lọc", bg=self.BG_CARD, fg=self.FG_SUB,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))

        self.btn_copy_log = self._button(log_tools, "Sao chép", self.BG_INPUT, fg=self.FG_TEXT,
                                        pady=4, padx=10, command=self.copy_log)
        self.btn_copy_log.pack(side="left", padx=(0, 6))
        self.btn_clear_log = self._button(log_tools, "Xóa", self.BG_INPUT, fg=self.FG_TEXT,
                                          pady=4, padx=10, command=self.clear_log)
        self.btn_clear_log.pack(side="left")

        self.log_box = scrolledtext.ScrolledText(card_monitor, state='disabled', wrap='word',
                                                 bg=self.BG_INPUT, fg=self.FG_TEXT,
                                                 font=self.FONT_MONO, bd=0,
                                                 padx=12, pady=10, height=12,
                                                 highlightthickness=1,
                                                 highlightbackground=self.BORDER)
        self.log_box.grid(row=1, column=0, sticky="nsew")
        for tag, color in self.LOG_COLORS.items():
            self.log_box.tag_configure(tag, foreground=color,
                                       font=("Consolas", 10, "bold"))
        self.log_box.tag_configure("dim", foreground=self.LOG_COLORS["dim"], font=self.FONT_MONO)
        # Giữ toàn bộ dòng gốc để lọc/copy lại được, vẽ lại theo bộ lọc hiện tại.
        # Không reset: khi đổi theme, UI dựng lại và danh sách này phải còn để vẽ log.
        if not hasattr(self, "_log_lines"):
            self._log_lines = []

    def _card_header(self, parent, text, color):
        """Tiêu đề thẻ: chữ nhỏ, giãn chữ, không emoji."""
        tk.Label(parent, text=text, bg=self.BG_CARD, fg=color,
                 font=self.FONT_CARD_HEADER).pack(anchor="w", pady=(0, 12))

    def _button(self, parent, text, bg, fg=None, command=None, pady=9, padx=10):
        """Nút phẳng, có phản hồi hover/active để bấm không bị cảm giác chết."""
        btn = tk.Button(parent, text=text, bg=bg, fg=fg or self.FG_ON_ACCENT,
                        font=self.FONT_BTN, bd=0, relief="flat", cursor="hand2",
                        pady=pady, padx=padx, activebackground=bg,
                        activeforeground=fg or self.FG_ON_ACCENT, command=command)
        btn.bind("<Enter>", lambda e, b=btn, c=bg: self._hover(b, c, True))
        btn.bind("<Leave>", lambda e, b=btn, c=bg, f=fg: self._hover(b, c, False, f))
        btn._base_bg = bg
        btn._base_fg = fg or self.FG_ON_ACCENT
        return btn

    def _hover(self, btn, base, entering, fg=None):
        """Hover đổi nền sang bản tối hơn, không làm nhạt.

        Làm nhạt sẽ kéo tỷ lệ chữ trắng xuống dưới 4.5:1, nên hướng ngược lại:
        tối đi một chút. Nút disabled không đổi màu.
        """
        if str(btn.cget("state")) == "disabled":
            return
        btn.config(bg=self._shift(base, -18) if entering else base)

    def _shift(self, hex_color, amount):
        """Dịch mọi kênh theo amount (âm = tối, dương = sáng), giữ tỷ lệ kênh."""
        hex_color = hex_color.lstrip("#")
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
        clamp = lambda v: max(0, min(v + amount, 255))
        return "#%02x%02x%02x" % (clamp(r), clamp(g), clamp(b))

    def _entry(self, parent, label, initial):
        tk.Label(parent, text=label, bg=self.BG_CARD, fg=self.FG_SUB,
                 font=("Segoe UI", 9)).pack(anchor="w")
        ent = tk.Entry(parent, bg=self.BG_INPUT, fg=self.FG_TEXT, insertbackground=self.FG_TEXT,
                       font=self.FONT_MAIN, bd=0, highlightthickness=1,
                       highlightbackground=self.BORDER, highlightcolor=self.ACCENT)
        ent.pack(fill="x", pady=(4, 12), ipady=7, ipadx=6)
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
                    foreground=self.FG_TEXT, selectbackground=self.ACCENT,
                    selectforeground=self.FG_ON_ACCENT, borderwidth=0)
        try:
            # PopdownWindow trả về ĐƯỜNG DẪN widget đầy đủ dạng chuỗi, ví dụ
            # '.!frame.!combobox.popdown'. root.nametowwidget() dùng đúng dạng này.
            lst = "%s.f.l" % combo.tk.call("ttk::combobox::PopdownWindow", combo)
            combo.tk.call(lst, "configure", "-background", self.BG_INPUT,
                          "-foreground", self.FG_TEXT,
                          "-selectbackground", self.ACCENT,
                          "-selectforeground", self.FG_ON_ACCENT,
                          "-borderwidth", 0, "-highlightthickness", 0)
        except tk.TclError:
            pass

    # ---------- log ----------
    def log(self, message, tag=None):
        self.root.after(0, self._safe_log, message, tag)

    def _safe_log(self, message, tag=None):
        try:
            tag = log_tag(message, tag)
            self._log_lines.append((message, tag))
            if len(self._log_lines) > self.LOG_KEEP:
                self._log_lines = self._log_lines[-self.LOG_KEEP:]
            self._track_stats(message, tag)
            needle = self.ent_filter.get().strip().lower() if self.ent_filter.winfo_exists() else ""
            if needle and needle not in message.lower():
                return                      # đang lọc -> dòng không khớp bị ẩn
            self.log_box.configure(state='normal')
            self.log_box.insert(tk.END, message + "\n", tag)
            num_lines = int(self.log_box.index('end-1c').split('.')[0])
            if num_lines > self.LOG_KEEP:
                self.log_box.delete("1.0", f"{num_lines - self.LOG_KEEP}.0")
            self.log_box.configure(state='disabled')
            self.log_box.yview(tk.END)
        except tk.TclError:
            pass

    def _track_stats(self, message, tag):
        """Bóc số liệu từ dòng log để đổ vào dòng phụ dưới trạng thái.

        Engine đã in sẵn số liệu ở dòng tiến độ qua count_files(), ví dụ
        '8 ảnh và 2 video'. Đếm ở đây thay vì sửa engine: không đụng tầng crawl,
        chỉ đọc chuỗi nó đã in.
        """
        if tag in ("error", "summary") and message.lstrip().startswith("["):
            self._had_error = True
        m = re.search(r"(\d+)\s+ảnh", message)
        if m:
            self._n_image = int(m.group(1))
        m = re.search(r"(\d+)\s+video", message)
        if m:
            self._n_video = int(m.group(1))
        # count_files() gọi nhóm thứ ba là "tệp", và số lỗi đường truyền nằm ở
        # dòng "[!] ... 3 tệp lỗi" chứ không phải "3 lỗi".
        m = re.search(r"(\d+)\s+tệp lỗi", message)
        if m:
            self._n_error = int(m.group(1))
        elif re.search(r"tệp lỗi", message):
            self._n_error = 1
        parts = []
        if self._n_image or self._n_video:
            parts.append(f"{self._n_image} ảnh, {self._n_video} video")
        if self._n_error:
            parts.append(f"{self._n_error} lỗi")
        if not parts:
            return
        self._last_detail = " · ".join(parts)
        # Chỉ cập nhật dòng phụ khi đang chạy; khi xong _safe_change ghi trạng thái riêng.
        if self.stop_event is not None and not self.stop_event.is_set():
            self._set_status(self.lbl_state.cget("text"), None, self._last_detail)

    def _apply_filter(self):
        """Vẽ lại log từ danh sách gốc theo từ khoá lọc hiện tại."""
        needle = self.ent_filter.get().strip().lower()
        try:
            self.log_box.configure(state='normal')
            self.log_box.delete("1.0", tk.END)
            for message, tag in self._log_lines:
                if not needle or needle in message.lower():
                    self.log_box.insert(tk.END, message + "\n", tag)
            self.log_box.configure(state='disabled')
            self.log_box.yview(tk.END)
        except tk.TclError:
            pass

    def copy_log(self):
        """Sao chép những gì đang hiện (đã lọc) để dán đi hỏi lỗi."""
        try:
            text = self.log_box.get("1.0", "end-1c")
            if not text.strip():
                self.log("[-] Nhật ký đang trống, không có gì để sao chép.", "error")
                return
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            n = len(self._log_lines)
            self.log(f"[✓] Đã sao chép {n} dòng nhật ký vào clipboard.", "system")
        except tk.TclError:
            pass

    def clear_log(self):
        try:
            self._log_lines = []
            self.log_box.configure(state='normal')
            self.log_box.delete("1.0", tk.END)
            self.log_box.configure(state='disabled')
        except tk.TclError:
            pass

    def set_status(self, text, color=None, detail=""):
        """Cập nhật trạng thái góc phải. Gọi từ thread engine qua after()."""
        self.root.after(0, self._set_status, text, color, detail)

    def _set_status(self, text, color=None, detail=""):
        try:
            self.lbl_state.config(text=text, fg=color or self.FG_SUB)
            self.lbl_progress.config(text=detail)
        except tk.TclError:
            pass

    def change_buttons_state(self, running=True):
        self.root.after(0, self._safe_change_buttons_state, running)

    def _safe_change_buttons_state(self, running):
        if running:
            for btn in (self.btn_download_user, self.btn_download_link, self.btn_update_all):
                btn.config(state="disabled", bg=self.COLOR_DISABLED, fg=self.FG_SUB)
            self.btn_stop.config(state="normal", bg=self.COLOR_RED, fg=self.FG_ON_ACCENT)
        else:
            self.btn_download_user.config(state="normal", bg=self.ACCENT,
                                          fg=self.FG_ON_ACCENT)
            self.btn_download_link.config(state="normal", bg=self.ACCENT,
                                          fg=self.FG_ON_ACCENT)
            self.btn_update_all.config(state="normal", bg=self.BG_INPUT, fg=self.FG_TEXT)
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
            # Ưu tiên thông báo lỗi/dừng; bình thường thì báo xong.
            if self.stop_event.is_set():
                self.set_status("ĐÃ DỪNG", self.COLOR_ORANGE)
            elif self._had_error:
                self.set_status("CÓ LỖI", self.COLOR_RED)
            else:
                self.set_status("SẴN SÀNG", self.FG_SUB, self._last_detail)

    def stop_crawl(self):
        self.stop_event.set()
        # Phản hồi tức thì: bấm xong thấy trạng thái đổi ngay, không phải chờ
        # engine thoát rồi mới thấy nút tắt (với file nặng có thể vài giây).
        self.set_status("ĐANG DỪNG", self.COLOR_ORANGE, "huỷ tải và đóng tab...")
        self.btn_stop.config(state="disabled", bg=self.COLOR_DISABLED, fg=self.FG_SUB)
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
        self._had_error = False
        self._last_detail = ""
        self._n_image = self._n_video = self._n_error = 0
        self.change_buttons_state(running=True)
        self.set_status("ĐANG QUÉT", self.ACCENT)
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

    # ---------- phím tắt ----------
    def _bind_keys(self):
        root = self.root
        root.bind("<Control-Return>", lambda e: self._focused_primary())
        root.bind("<Escape>", lambda e: self.stop_crawl())
        root.bind("<Control-f>", lambda e: self._focus_filter())
        root.bind("<Control-l>", lambda e: self.clear_log())
        for w in (self.ent_thread_url, self.ent_filter):
            w.bind("<Return>", lambda e: self._focused_primary())

    def _focused_primary(self):
        """Ctrl+Enter chạy đúng nút theo ô đang có con trỏ.

        Không bắt được thì mặc định quét 1 user, vì đó là hành động dùng nhiều nhất.
        """
        focused = self.root.focus_get()
        if focused is self.ent_thread_url:
            self.start_link_crawl_thread()
        elif focused is self.cmb_username:
            self.start_single_crawl_thread()
        else:
            self.start_single_crawl_thread()

    def _focus_filter(self):
        self.ent_filter.focus_set()
        self.ent_filter.select_range(0, tk.END)


if __name__ == "__main__":
    app_root = tk.Tk()
    app = XenForoScannerApp(app_root)
    app._bind_keys()
    app.auto_launch_browser()
    app_root.mainloop()