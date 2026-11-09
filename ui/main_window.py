"""Cửa sổ chính + main(). Tách từ gui_fluent.py (P2.1)."""

import os
import sys
import threading
from typing import Optional

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QStackedWidget

from qfluentwidgets import (
    FluentIcon, NavigationItemPosition,
    InfoBar, InfoBarPosition, Theme, setTheme,
)
from qfluentwidgets.common.config import qconfig
from qframelesswindow import FramelessWindow

import config
import browser_launcher
import session_log
import session_source
from cache import MediaCache, LocalUserIndex

from ui.log_view import swallow
from ui.worker import CrawlWorker
from ui.crawler_view import CrawlerInterface
from ui.settings_view import SettingsInterface
from ui.startup_overlay import StartupOverlay
from ui.theme import (
    MacSidebar, MacTitleBar, apply_macos_typography, apply_accent_color,
    apply_widget_styles, palette,
)


class MainWindow(FramelessWindow):
    """Cửa sổ chính phong cách macOS: sidebar, traffic-light, card nổi."""

    # Signal để worker thread báo về GUI thread. PHẢI dùng Signal, không dùng
    # QTimer.singleShot: QTimer tạo trong thread không có Qt event loop thì
    # KHÔNG BAO GIỜ chạy. Đo được: singleShot từ main thread fired=1, từ worker
    # thread fired=0. Hệ quả trước đây: mọi thông báo (mở trình duyệt thành
    # công, thất bại, log từ thread) đều im lặng biến mất.
    #
    # Signal phát từ thread khác được Qt xếp hàng và giao cho GUI thread —
    # đây là cơ chế đúng, thread-safe.
    sig_ui_notify = Signal(str, str, str, int)   # (kind, title, content, ms)
    sig_ui_login_opened = Signal(str, str, bool)  # (browser, profile, wait)
    sig_ui_log = Signal(str, str)                 # (message, tag)
    sig_startup_status = Signal(str, str, int)    # (state, detail, percent)

    def __init__(self, auto_browser: bool = True):
        # Font + accent phải đặt trước khi tạo widget: QSS của qfluentwidgets
        # đọc fontFamilies lúc apply.
        apply_macos_typography()
        apply_accent_color()
        super().__init__()
        self.setWindowTitle("XenForo Download")
        self.resize(1180, 880)
        self.setMinimumSize(960, 740)

        # Theme PHẢI đặt trước khi tạo widget. Đo được: nếu đặt sau, QSS phủ
        # lên cây widget đang ẩn không repolish hết — khởi động thẳng vào dark
        # thì tiêu đề sidebar kẹt màu light (#1D1D1F), gần như vô hình.
        saved_theme = self.load_theme_setting()
        if saved_theme == "light":
            setTheme(Theme.LIGHT)
        elif saved_theme == "auto":
            setTheme(Theme.AUTO)
        else:
            setTheme(Theme.DARK)

        self.setTitleBar(MacTitleBar(self))
        self._build_shell()

        # Thiết lập Icon thương hiệu ứng dụng
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "app_icon.ico")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "logo_256.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.download_dir = config.DOWNLOAD_DIR
        self._resolve_dir()

        self.cache = MediaCache(os.path.join(self.download_dir, "crawler_cache.db"))
        self.local_users = LocalUserIndex(self.cache.conn)
        self.local_users.refresh(self.download_dir)

        self.stop_event = threading.Event()
        self.worker: Optional[CrawlWorker] = None
        self.log_history = []  # Lưu (message, tag)

        # Ghi nhật ký ra file để xem lại được sau khi đóng app.
        # Bản trước chỉ giữ trong RAM nên khi người dùng báo "có 7 lỗi" thì
        # không còn gì để đọc — mọi chẩn đoán phải đoán lại.
        self.session_log = None
        if getattr(config, "LOG_TO_FILE", True):
            try:
                self.session_log = session_log.SessionLog(
                    log_dir=getattr(config, "LOG_DIR", None),
                    keep=getattr(config, "LOG_KEEP_SESSIONS", 30),
                    min_level=getattr(config, "LOG_MIN_LEVEL", "DEBUG"))
                # Đăng ký logger active: lỗi bị nuốt từ giờ ghi thẳng vào
                # file, còn lỗi đã đệm từ trước thì đổ vào.
                try:
                    session_log.set_active_logger(self.session_log)
                except Exception:
                    pass
            except Exception:
                self.session_log = None

        # Khởi tạo giao diện trang con
        self.crawler_interface = CrawlerInterface(self)
        self.crawler_interface.setObjectName("crawlerInterface")
        self.settings_interface = SettingsInterface(self)
        self.settings_interface.setObjectName("settingsInterface")

        self.init_navigation()
        # QSS macOS cho toàn bộ control đã tạo xong (nút, ô nhập, combo...).
        apply_widget_styles(self)

        # Nối signal -> handler. Qt tự chọn QueuedConnection vì phát từ thread
        # khác, nên handler luôn chạy trên GUI thread.
        self.sig_ui_notify.connect(self._on_ui_notify)
        self.sig_ui_login_opened.connect(self._on_login_opened_ui)
        self.sig_ui_log.connect(self.append_log)
        self.sig_startup_status.connect(self._on_startup_status)
        qconfig.themeChangedFinished.connect(self._on_theme_changed)

        # Màn hình chờ: chỉ dùng cho chế độ CDP (chế độ persistent không mở
        # trình duyệt lúc khởi động nên không có gì để chờ).
        self.startup_overlay: Optional[StartupOverlay] = None
        self._startup_pending = False
        self._startup_grace = QTimer(self)
        self._startup_grace.setSingleShot(True)
        self._startup_grace.timeout.connect(self._show_startup_overlay)

        # Tự động nạp trình duyệt nếu cấu hình bật
        if auto_browser and config.AUTO_LAUNCH_BROWSER:
            QTimer.singleShot(350, self._begin_startup)

    def _build_shell(self):
        """Dựng khung macOS: sidebar trái + vùng nội dung xếp lớp."""
        self.sidebar = MacSidebar(self)
        self.stackedWidget = QStackedWidget(self)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, MacTitleBar.HEIGHT, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.sidebar)
        root.addWidget(self.stackedWidget, 1)
        self.sidebar.currentChanged.connect(self._on_nav_changed)

    def addSubInterface(self, interface, icon, text, selectedIcon=None,
                        position=NavigationItemPosition.TOP, **kwargs):
        """Tương thích MSFluentWindow: thêm trang + mục sidebar."""
        self.stackedWidget.addWidget(interface)
        return self.sidebar.addItem(
            interface.objectName(), icon, text,
            bottom=(position == NavigationItemPosition.BOTTOM))

    def switchTo(self, interface):
        if self.stackedWidget.indexOf(interface) < 0:
            return
        self.stackedWidget.setCurrentWidget(interface)
        self.sidebar.setCurrent(interface.objectName())

    def _on_nav_changed(self, key: str):
        for i in range(self.stackedWidget.count()):
            widget = self.stackedWidget.widget(i)
            if widget.objectName() == key:
                self.stackedWidget.setCurrentWidget(widget)
                return

    def resizeEvent(self, event):
        if getattr(self, "titleBar", None) is not None:
            self.titleBar.setGeometry(0, 0, self.width(), MacTitleBar.HEIGHT)
        self._position_overlay()
        super().resizeEvent(event)

    def paintEvent(self, event):
        pal = palette()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(pal["canvas"]))
        # Sidebar chạy sát đỉnh sau title bar, giống macOS Finder: dải trên
        # bên trái cùng màu sidebar, có đường phân cách dọc.
        if getattr(self, "sidebar", None) is not None:
            top = QRect(0, 0, MacSidebar.WIDTH, MacTitleBar.HEIGHT)
            painter.fillRect(top, QColor(pal["sidebar"]))
            painter.setPen(QPen(QColor(pal["sidebar_border"]), 1))
            painter.drawLine(
                MacSidebar.WIDTH - 1, 0,
                MacSidebar.WIDTH - 1, MacTitleBar.HEIGHT)

    def _on_theme_changed(self):
        self.update()
        if getattr(self, "sidebar", None) is not None:
            self.sidebar.update()
        if getattr(self, "titleBar", None) is not None:
            self.titleBar.update()
        if getattr(self, "startup_overlay", None) is not None:
            self.startup_overlay.update()

    def init_navigation(self):
        self.addSubInterface(
            self.crawler_interface,
            FluentIcon.DOWNLOAD,
            "Quét Media",
            position=NavigationItemPosition.TOP
        )
        self.addSubInterface(
            self.settings_interface,
            FluentIcon.SETTING,
            "Cài đặt",
            position=NavigationItemPosition.BOTTOM
        )
        self.switchTo(self.crawler_interface)

    def is_crawling(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _resolve_dir(self):
        """Ổ cứng khác máy hoặc bị hạn chế quyền thì tự động tìm thư mục khả dụng."""
        import tempfile
        candidates = [
            self.download_dir,
            os.path.join(os.path.expanduser("~"), "RPHANG"),
            os.path.join(os.getcwd(), "RPHANG"),
            os.path.join(tempfile.gettempdir(), "RPHANG"),
        ]
        for candidate in candidates:
            try:
                os.makedirs(candidate, exist_ok=True)
                test_file = os.path.join(candidate, f".test_write_{os.getpid()}.tmp")
                with open(test_file, "w", encoding="utf-8") as f:
                    f.write("1")
                os.remove(test_file)
                self.download_dir = os.path.abspath(candidate)
                self._boot_error = None
                return
            except Exception:
                continue

        # Tuyệt vọng cuối cùng
        fallback = os.path.join(tempfile.gettempdir(), "RPHANG")
        os.makedirs(fallback, exist_ok=True)
        self.download_dir = os.path.abspath(fallback)
        self._boot_error = f"Chỉ ghi được vào thư mục tạm: {self.download_dir}"

    def reload_storage(self):
        """Đổi thư mục lưu trữ: đóng DB cũ, mở DB mới.

        Phải từ chối khi engine đang chạy: worker đang giữ chính đối tượng cache
        này và ghi vào nó giữa lúc quét. Đóng connection lúc đó làm worker ném
        "Cannot operate on a closed database", và tệ hơn là mất dòng cache của
        các file vừa tải xong -> lần sau tải lại toàn bộ.
        """
        if self.is_crawling():
            InfoBar.warning(
                title="Đang quét",
                content="Không đổi thư mục lưu trữ khi đang quét. Hãy dừng trước.",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000
            )
            return False
        try:
            self.cache.close()
        except Exception as e:
            # Đổi thư mục lưu trữ: DB cũ có thể đang bị worker giữ. Nuốt để
            # vẫn mở được DB mới, nhưng ghi lại — mất cache cũ nghĩa là lần
            # sau tải lại media đã có.
            swallow("reload_storage.close", e)
        self.cache = MediaCache(os.path.join(self.download_dir, "crawler_cache.db"))
        self.local_users = LocalUserIndex(self.cache.conn)
        self.local_users.refresh(self.download_dir)
        self.crawler_interface.refresh_user_dropdown()
        return True

    def _begin_startup(self):
        """Khởi động trình duyệt kèm màn hình chờ nếu cần chờ thật."""
        mode = (getattr(config, "BROWSER_MODE", "cdp") or "cdp").lower()
        if mode != "cdp" or not config.AUTO_LAUNCH_BROWSER:
            self.auto_launch_browser()
            return

        self._startup_pending = True
        # Cổng đã sẵn sàng thì launch() trả về gần như tức thì; chờ 250ms rồi
        # mới phủ màn hình để trường hợp bình thường không bị nháy overlay.
        self._startup_grace.start(250)
        self.auto_launch_browser()

    def _show_startup_overlay(self):
        if not self._startup_pending:
            return
        if self.startup_overlay is None:
            self.startup_overlay = StartupOverlay(self)
            self.startup_overlay.dismissed.connect(self._on_startup_dismissed)
            self.startup_overlay.closed.connect(self._on_startup_closed)
        self._position_overlay()
        self._set_content_enabled(False)
        self.startup_overlay.start()
        self.startup_overlay.show()
        self.startup_overlay.raise_()

    def _position_overlay(self):
        overlay = getattr(self, "startup_overlay", None)
        if overlay is None:
            return
        overlay.setGeometry(
            0, MacTitleBar.HEIGHT, self.width(),
            max(0, self.height() - MacTitleBar.HEIGHT))

    def _set_content_enabled(self, enabled: bool):
        for widget in (getattr(self, "sidebar", None),
                       getattr(self, "stackedWidget", None)):
            if widget is not None:
                widget.setEnabled(enabled)

    def _on_startup_status(self, state: str, detail: str, percent: int):
        if state == "progress":
            if self._startup_pending and self.startup_overlay is not None:
                self.startup_overlay.set_progress(percent, detail)
            return

        if state == "error":
            self._startup_grace.stop()
            if self.startup_overlay is not None and self.startup_overlay.isVisible():
                self._startup_pending = False
                self.startup_overlay.finish_error(detail)
                return
            # Lỗi có thể tới trước khi overlay kịp hiện (250ms) — vẫn phải
            # báo, vì ở chế độ CDP app chưa dùng được khi thiếu trình duyệt.
            # Nhưng người dùng đã bấm "Bỏ qua" thì tôn trọng, chỉ ghi log.
            if self._startup_pending:
                self._show_startup_overlay()
                self._startup_pending = False
                if self.startup_overlay is not None:
                    self.startup_overlay.finish_error(detail)
            return

        self._startup_pending = False
        self._startup_grace.stop()
        if self.startup_overlay is not None and self.startup_overlay.isVisible():
            self.startup_overlay.finish_success(detail)

    def _on_startup_dismissed(self):
        was_skipped = self._startup_pending
        self._startup_pending = False
        self._startup_grace.stop()
        if was_skipped:
            self.append_log("[*] Bạn đã bỏ qua màn hình khởi động. Trình duyệt "
                            "vẫn tiếp tục mở ngầm.", "system")

    def _on_startup_closed(self):
        self._set_content_enabled(True)

    def auto_launch_browser(self):
        """Chuẩn bị trình duyệt lúc khởi động — theo đúng BROWSER_MODE.

        BẢN TRƯỚC (lỗi): hàm này không kiểm BROWSER_MODE nên dù mode là
        "persistent" nó vẫn gọi browser_launcher.launch() và MỞ CỔNG 9222.
        Người dùng đã báo đúng: "phiên này vẫn mở cổng 9222".

        Ở mode persistent KHÔNG mở cổng nào: Playwright tự mở trình duyệt khi
        bắt đầu quét, qua pipe. Chỉ cần kiểm profile ghi được không và báo
        trạng thái phiên.
        """
        mode = (getattr(config, "BROWSER_MODE", "persistent") or "persistent").lower()

        if mode != "cdp":
            # persistent: không mở cổng, không mở trình duyệt sớm.
            browser = (config.SESSION_BROWSER or "chrome").lower()
            exe = browser_launcher.find_browser_for(browser)
            profile = session_source.resolve_profile(browser)
            if not exe:
                self.append_log(f"[!] Không tìm thấy {browser}. Cài nó hoặc đổi "
                                f"SESSION_BROWSER trong config.py.", "error")
                return
            if not session_source.profile_is_writable(profile):
                self.append_log(f"[!] Không ghi được profile {profile}. "
                                f"Đổi SESSION_PROFILE trong config.py.", "error")
                return
            self.append_log(f"[*] Chế độ persistent: {os.path.basename(exe)} · "
                            f"profile {profile}", "system")
            self.append_log("[*] Không mở cổng TCP nào. Trình duyệt sẽ được mở "
                            "khi bắt đầu quét.", "system")
            return

        # mode == "cdp": mở/cập nhật cổng debug. launch() tự kiểm cổng, nên
        # không probe thêm trên GUI thread (probe có thể chặn tới 1.5s — đúng
        # lúc người dùng đang nhìn màn hình chờ).
        if not config.AUTO_LAUNCH_BROWSER:
            return

        def work():
            # Chỉ cần trình duyệt mở được là cho vào app. Cổng CDP được chờ
            # ngắn để phiên quét chắc chắn dùng được, nhưng không chặn người
            # dùng ở màn hình chờ khi cổng chưa/không mở.
            wait_seconds = 6.0

            def on_progress(remaining):
                percent = int(round((1 - remaining / wait_seconds) * 100))
                self.sig_startup_status.emit(
                    "progress",
                    f"Đang chờ trình duyệt khởi động · còn ~{max(1, int(remaining) + 1)}s",
                    percent)

            ok, msg = browser_launcher.launch(
                wait_seconds=wait_seconds, on_progress=on_progress,
                require_port=False)
            tag = "system" if ok else "error"
            symbol = "OK" if ok else "!"
            self.sig_ui_log.emit(f"[{symbol}] {msg}", tag)
            self.sig_startup_status.emit("success" if ok else "error", msg, 100)

        threading.Thread(target=work, daemon=True).start()

    def _on_ui_notify(self, kind: str, title: str, content: str, ms: int):
        """Handler cho thông báo phát từ worker thread. Chạy trên GUI thread."""
        fn = {"error": InfoBar.error, "warn": InfoBar.warning,
              "success": InfoBar.success, "info": InfoBar.info}.get(kind,
                                                                   InfoBar.info)
        try:
            fn(title=title, content=content, parent=self,
               position=InfoBarPosition.TOP_RIGHT, duration=ms or 4000)
        except Exception as e:
            # Thông báo lỗi không được làm chết luồng GUI. Nhưng nếu InfoBar
            # hỏng thì người dùng mất mọi phản hồi — phải thấy trong log.
            swallow("infobar", e)

    def _on_login_opened_ui(self, browser: str, prof: str, wait: bool):
        """Handler cho việc mở cửa sổ đăng nhập. Chạy trên GUI thread."""
        try:
            self.settings_interface._on_login_opened(browser, prof, wait)
        except Exception as e:
            # Lỗi ở đây nghĩa là người dùng không thấy hướng dẫn đăng nhập.
            swallow("login_opened_ui", e)

    def append_log(self, message: str, tag: str = "info"):
        self.log_history.append((message, tag))
        if len(self.log_history) > 1500:
            self.log_history = self.log_history[-1500:]
        # Ghi ra file TRƯỚC khi vẽ: nếu giao diện treo hoặc app bị kill, file
        # vẫn còn dòng cuối. Không để việc vẽ chặn việc ghi log.
        if self.session_log is not None:
            try:
                self.session_log.write(message, tag)
            except Exception as e:
                # Ghi file hỏng không được chặn vẽ log ra màn hình.
                swallow("session_log.write", e)
        self.crawler_interface.append_log(message, tag)
    def _theme_file_path(self) -> str:
        """Đường dẫn file lưu lựa chọn giao diện.

        MỘT nơi duy nhất: HOME nếu ghi được, không thì cwd. `load_theme_setting`
        đọc đúng đường dẫn này, nhờ vậy đọc và ghi không bao giờ lệch nhau.
        """
        return self._pick_theme_path()

    def _pick_theme_path(self) -> str:
        """Chọn file theme ghi được: HOME trước, cwd sau.

        VÌ SAO PHẢI CHỌN MỘT CHỖ: bản trước `load_theme_setting` tự dò cả hai
        đường dẫn và trả cái ĐẦU TIÊN đọc được, trong khi `_theme_file_path`
        (dùng để ghi) trả cái ĐẦU TIÊN ghi được. Khi HOME có file cũ "dark"
        nhưng không ghi được (sandbox, quyền), app ghi "light" vào cwd rồi lần
        sau đọc HOME ra "dark" — người dùng đổi theme xong mở lại vẫn thấy cũ.
        Đo được: HOME='dark', cwd='light', load_theme_setting() -> 'dark'.
        """
        candidates = [
            os.path.join(os.path.expanduser("~"), ".xenforo_theme"),
            os.path.join(os.getcwd(), ".xenforo_theme"),
        ]
        for path in candidates:
            try:
                with open(path, "a", encoding="utf-8"):
                    pass
                return path
            except OSError:
                continue
        return os.path.join(os.getcwd(), ".xenforo_theme")

    def load_theme_setting(self) -> str:
        """Đọc theme đã lưu. Đọc ĐÚNG file mà save_theme_setting sẽ ghi."""
        path = self._pick_theme_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                t = f.read().strip()
                if t in ("light", "dark", "auto"):
                    return t
        except OSError:
            pass
        # Chưa có file (lần chạy đầu) -> macOS Light là giao diện mặc định.
        return "light"

    def save_theme_setting(self, theme_str: str):
        path = self._theme_file_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(theme_str)
        except OSError as e:
            # Mất theme đã chọn thì lần sau mở lại sai theme — phiền nhưng
            # không chết app. Ghi lại để biết vì sao theme không giữ được.
            swallow("save_theme", e)

    # ---------------- Các hành động quét ----------------
    def start_author_crawl(self):
        if self.is_crawling():
            return
        user = self.crawler_interface.cmb_username.currentText().strip()
        box_url = self.crawler_interface.cmb_box_url.currentText().strip()
        if not user or not box_url:
            InfoBar.error(
                title="Thiếu thông tin",
                content="Vui lòng nhập đầy đủ Chuyên mục và Tên tác giả!",
                parent=self.crawler_interface,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3500
            )
            return
        if not self._ensure_login():
            return
        self._launch(lambda eng: eng.crawl_users([user], box_url), f"Tác giả: {user.upper()}")

    def start_thread_crawl(self):
        if self.is_crawling():
            return
        thread_url = self.crawler_interface.ent_thread_url.text().strip()
        if not thread_url:
            InfoBar.error(
                title="Thiếu thông tin",
                content="Vui lòng dán liên kết bài viết cần quét!",
                parent=self.crawler_interface,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3500
            )
            return
        if not self._ensure_login():
            return
        self._launch(lambda eng: eng.crawl_link(thread_url), "Bài viết đơn")

    def start_all_crawl(self):
        if self.is_crawling():
            return
        box_url = self.crawler_interface.cmb_box_url.currentText().strip()
        if not box_url:
            InfoBar.error(
                title="Thiếu thông tin",
                content="Vui lòng chọn hoặc nhập Link Chuyên Mục!",
                parent=self.crawler_interface,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3500
            )
            return
        if not self._ensure_login():
            return
        self.local_users.refresh(self.download_dir)
        users = self.local_users.names()
        if not users:
            InfoBar.warning(
                title="Không có tác giả",
                content="Chưa có profile tác giả nào trên máy local để cập nhật!",
                parent=self.crawler_interface,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3500
            )
            return
        self.crawler_interface.refresh_user_dropdown()
        self.append_log(f"\n[*] Tìm thấy {len(users)} tác giả local. Đồng bộ đa luồng...", "bulk")
        self._launch(lambda eng: eng.crawl_users(users, box_url), f"Toàn bộ ({len(users)} tác giả)")

    def _ensure_login(self) -> bool:
        """Bảo đảm đã có phiên đăng nhập TRƯỚC khi chạy ẩn.

        Vì sao cần: chế độ quét chạy ẩn (headless). Nếu chưa đăng nhập, mọi
        request vào box riêng bị XenForo chuyển về trang login, và app tải về
        HTML của trang đăng nhập thay vì media — rất nặng và không có kết quả.
        Người dùng không thấy gì vì chạy ẩn, nên phải chặn từ đầu.

        Profile phải lấy ĐÚNG THEO MODE: ở mode cdp, session nằm trong profile
        của browser_launcher (BROWSER_PROFILE), không phải profile riêng của
        mode persistent. Kiểm nhầm profile sẽ đòi đăng nhập oan dù đã có sẵn.
        """
        mode = (getattr(config, "BROWSER_MODE", "cdp") or "cdp").lower()
        if mode == "cdp":
            profile = browser_launcher.profile_dir()
        else:
            browser = (config.SESSION_BROWSER or "chrome").lower()
            profile = session_source.resolve_profile(browser)

        need, why = session_source.needs_first_login(profile)
        if not need:
            return True

        self.append_log(f"[!] {why}", "summary")
        self.append_log("[*] Mở trình duyệt để bạn đăng nhập. Cửa sổ này hiện rõ "
                        "để bạn thao tác.", "system")
        # _open_login_window nằm ở SettingsInterface (nơi có thẻ Đăng nhập và
        # InfoBar). Gọi qua settings_interface, KHÔNG gọi self._open_login_window:
        # MainWindow không có hàm đó và sẽ ném AttributeError đúng vào lúc người
        # dùng cần nó nhất — lần chạy đầu tiên, khi chưa có cookie.
        self.settings_interface._open_login_window(wait_for_login=True)
        return False

    def _launch(self, coro_factory, task_desc: str):
        self.stop_event.clear()
        self._set_ui_running(True, task_desc)

        self.worker = CrawlWorker(
            cache=self.cache,
            download_dir=self.download_dir,
            stop_event=self.stop_event,
            coro_factory=coro_factory,
            parent=self
        )
        self.worker.signals.sig_log.connect(self.append_log)
        self.worker.signals.sig_stats.connect(self._on_stats_updated)
        self.worker.signals.sig_finished.connect(self._on_crawl_finished)
        self.worker.signals.sig_author_found.connect(self._on_author_found)
        self.worker.signals.sig_box_found.connect(self._on_box_found)
        self.worker.start()

    def stop_crawl(self):
        if not self.is_crawling():
            return
        self.stop_event.set()
        self.crawler_interface.status_dot.set_state("warning")
        self.crawler_interface.lbl_state_title.setText("ĐANG DỪNG...")
        self.crawler_interface.lbl_state_detail.setText("Đang hủy các luồng tải và đóng tab...")
        self.crawler_interface.btn_stop.setEnabled(False)
        if self.worker:
            self.worker.emergency_cleanup()

    def _set_ui_running(self, running: bool, task_desc: str = ""):
        ci = self.crawler_interface
        if running:
            ci.btn_crawl_user.setEnabled(False)
            ci.btn_crawl_thread.setEnabled(False)
            ci.btn_crawl_all.setEnabled(False)
            ci.btn_stop.setEnabled(True)
            ci.progress_bar.setVisible(True)
            ci.progress_bar.start()
            ci.status_dot.set_state("running")
            ci.lbl_state_title.setText("ĐANG QUÉT")
            ci.lbl_state_detail.setText(f"Tác vụ: {task_desc}...")
        else:
            ci.btn_stop.setEnabled(False)
            ci.progress_bar.stop()
            ci.progress_bar.setVisible(False)
            ci.status_dot.set_state("ready")
            ci._check_inputs()

    def _on_stats_updated(self, images: int, videos: int, errors: int, detail: str):
        if self.is_crawling():
            self.crawler_interface.lbl_state_detail.setText(f"Tiến độ: {detail}")

    def _on_author_found(self, author: str):
        """Tự động điền tên chủ thớt vào ô Tên tác giả khi quét bài viết.

        Khi user bấm "Quét 1 Thớt", engine tìm được chủ thớt và log dòng
        "Đã định danh chính xác tác giả gốc: AUTHOR". Worker bắt dòng này,
        phát signal → hàm này điền vào ô cmb_username để lần sau user có thể
        bấm "Quét tác giả" ngay mà không cần gõ lại tên.
        """
        ci = self.crawler_interface
        current = ci.cmb_username.currentText().strip()
        # Chỉ điền nếu ô đang trống hoặc khác tên vừa tìm được
        if author and author.lower() != current.lower():
            # EditableComboBox của QFluentWidgets cần setText(), không phải setCurrentText()
            ci.cmb_username.setText(author)

    def _on_box_found(self, box_url: str):
        """Tự động điền box URL vào ô Chuyên mục khi quét bài viết.

        Khi user bấm "Quét 1 Thớt", engine đọc breadcrumb trên trang thread
        để tìm box URL và log "Bài viết thuộc chuyên mục: URL". Worker bắt
        dòng này → phát signal → hàm này điền vào ô cmb_box_url.
        Nếu box chưa có trong preset, nút ➕ sẽ tự hiện.
        """
        ci = self.crawler_interface
        current = ci.cmb_box_url.currentText().strip()
        if box_url and box_url != current:
            ci.cmb_box_url.setText(box_url)
        # Cập nhật trạng thái nút thêm box
        ci._update_add_box_button()

    def add_current_box_to_presets(self):
        """Thêm box URL hiện tại vào danh sách preset và lưu vào file."""
        ci = self.crawler_interface
        box_url = ci.cmb_box_url.currentText().strip()
        if not box_url or "/box/" not in box_url:
            return

        # Kiểm tra đã có chưa
        if ci.is_box_in_presets(box_url):
            InfoBar.info(
                title="Đã có sẵn",
                content="Chuyên mục này đã nằm trong danh sách.",
                parent=ci, position=InfoBarPosition.TOP_RIGHT, duration=2000)
            return

        # Thêm vào dropdown
        ci.cmb_box_url.addItem(box_url)
        ci.cmb_box_url.setCurrentText(box_url)

        # Lưu vào file ~/.xenforo_boxes
        try:
            with open(ci._box_presets_file(), "a", encoding="utf-8") as f:
                f.write(box_url + "\n")
        except OSError as e:
            swallow("save_box_preset", e)

        ci.btn_add_box.setVisible(False)
        InfoBar.success(
            title="Đã thêm",
            content="Đã lưu chuyên mục vào danh sách preset.",
            parent=ci, position=InfoBarPosition.TOP_RIGHT, duration=3000)

    def _on_crawl_finished(self, is_stopped: bool, had_error: bool, detail: str):
        self._set_ui_running(False)
        ci = self.crawler_interface
        if is_stopped:
            ci.status_dot.set_state("warning")
            ci.lbl_state_title.setText("ĐÃ DỪNG")
            ci.lbl_state_detail.setText(f"Đã dừng cưỡng bức. {detail}")
            InfoBar.warning(
                title="Đã dừng",
                content="Phiên quét đã dừng lại theo yêu cầu của bạn.",
                parent=self.crawler_interface,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3500
            )
        elif had_error:
            ci.status_dot.set_state("error")
            ci.lbl_state_title.setText("CÓ LỖI")
            ci.lbl_state_detail.setText(f"Hoàn tất với một số lỗi. {detail}")
            InfoBar.error(
                title="Lưu ý",
                content=f"Quét hoàn tất nhưng có cảnh báo/lỗi: {detail}",
                parent=self.crawler_interface,
                position=InfoBarPosition.TOP_RIGHT,
                duration=4500
            )
        else:
            ci.status_dot.set_state("ready")
            ci.lbl_state_title.setText("SẴN SÀNG")
            ci.lbl_state_detail.setText(f"Đã đồng bộ xong! {detail}" if detail else "Đã hoàn thành xuất sắc!")
            InfoBar.success(
                title="Hoàn tất",
                content=f"Đồng bộ thành công! {detail}",
                parent=self.crawler_interface,
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000
            )

        # GIẢI PHÓNG worker. Thiếu bước này là nguồn gốc của "chạy xong vẫn lag":
        # QThread đã chạy xong vẫn giữ toàn bộ Python frame, closure `coro_factory`
        # (bắt cả engine + cache), và 3 Signal đã kết nối. Mỗi phiên quét để lại
        # một object như vậy, cộng dồn qua nhiều lần chạy.
        self._release_worker()

    def _release_worker(self):
        """Hủy QThread và ngắt Signal sau khi phiên quét kết thúc."""
        w = self.worker
        self.worker = None
        if w is None:
            return
        try:
            # Ngắt Signal trước để callback không bắn vào object sắp bị xoá.
            for sig in (w.signals.sig_log, w.signals.sig_stats,
                        w.signals.sig_finished):
                try:
                    sig.disconnect()
                except (RuntimeError, TypeError):
                    pass    # chưa connect thì disconnect ném RuntimeError — hợp lệ
        except Exception as e:
            swallow("release_worker.disconnect", e)
        try:
            if w.isRunning():
                w.wait(3000)
        except Exception as e:
            # QThread không chịu dừng sau 3s: đáng biết, vì worker đó còn giữ
            # engine + cache.
            swallow("release_worker.wait", e)
        # Không deleteLater nếu closeEvent đang chạy trên chính thread này.
        try:
            w.deleteLater()
        except Exception as e:
            swallow("release_worker.deleteLater", e)
        self.append_log("[*] Đã giải phóng tiến trình quét.", "system")

    def closeEvent(self, event):
        """Dọn dẹp sạch sẽ khi đóng cửa sổ ứng dụng.

        Gồm cả việc đóng trình duyệt do CHÍNH app mở: trước đây app mở trình
        duyệt rồi bỏ mặc, mỗi lần chạy để lại một cửa sổ mồ côi với profile riêng.
        Không đụng trình duyệt người dùng tự mở.
        """
        if self.is_crawling():
            self.stop_event.set()
            if self.worker:
                self.worker.emergency_cleanup()
                self.worker.wait(2000)
        try:
            self.cache.close()
        except Exception as e:
            swallow("close.cache", e)
        try:
            browser_launcher.shutdown()
        except Exception as e:
            swallow("close.browser_shutdown", e)
        # Đóng log SAU CÙNG để còn ghi được lỗi ở các bước dọn dẹp trên.
        # Summary giúp biết ngay phiên đó có bao nhiêu lỗi mà không phải grep.
        if getattr(self, "session_log", None) is not None:
            try:
                ci = self.crawler_interface
                summary = (f"nhật ký UI: {ci.log_edit.document().blockCount()} dòng | "
                           f"lỗi: {self.session_log.error_count} | "
                           f"cảnh báo: {self.session_log.warn_count}")
                self.session_log.close(summary)
            except Exception:
                pass
        event.accept()




def main():
    # Bật High-DPI scaling cho màn hình 2K/4K
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    apply_macos_typography(app)
    apply_accent_color()
    window = MainWindow()
    window.show()

    # Bắt exception không xử lý được. Mặc định Python chỉ in ra stderr; chạy
    # bằng .bat thì cửa sổ đóng là mất sạch, không biết app chết vì gì.
    def _excepthook(exc_type, exc, tb):
        try:
            if window.session_log is not None:
                window.session_log.exception("main", exc)
        except Exception:
            pass
        # Vẫn in ra console để chạy từ terminal thấy ngay.
        import traceback as _tb
        _tb.print_exception(exc_type, exc, tb)

    sys.excepthook = _excepthook

    exit_code = app.exec()
    # Đóng log cả khi thoát bình thường lẫn khi lỗi.
    if window.session_log is not None:
        try:
            window.session_log.close(f"mã thoát: {exit_code}")
        except Exception:
            pass
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
