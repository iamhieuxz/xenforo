"""XenForo Crawler V72 — Giao diện Windows 11 Fluent Design (PySide6 + QFluentWidgets).

Kế thừa toàn bộ logic nghiệp vụ (CrawlerEngine, MediaCache, Downloader, xf_selectors).
Thay thế toàn bộ tầng giao diện Tkinter cũ bằng chuẩn thiết kế hiện đại của Windows 11:
- Khung cửa sổ Fluent với hiệu ứng Acrylic / Mica
- Quản lý đa luồng chuẩn Qt (QThread, QObject Signal & Slot)
- Thẻ giao diện bo góc, đổ bóng, phản hồi trạng thái mượt mà
- Thanh tiến trình thực tế, toast notifications (InfoBar)
- Tự động thích ứng Dark / Light Mode theo Windows hoặc tuỳ chọn người dùng
"""

import asyncio
import os
import re
import subprocess
import sys
import threading
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QObject, QSize, QTimer
from PySide6.QtGui import QIcon, QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFileDialog, QSizePolicy
)

from qfluentwidgets import (
    MSFluentWindow, FluentIcon, NavigationItemPosition,
    CardWidget, SimpleCardWidget, HeaderCardWidget,
    SubtitleLabel, TitleLabel, BodyLabel, CaptionLabel, StrongBodyLabel,
    PrimaryPushButton, PushButton, TransparentPushButton, HyperlinkButton,
    LineEdit, SearchLineEdit, ComboBox, EditableComboBox,
    ProgressBar, IndeterminateProgressBar, TextEdit,
    InfoBar, InfoBarPosition, Theme, setTheme, isDarkTheme,
    SettingCardGroup, SettingCard, PushSettingCard, ComboBoxSettingCard, SwitchSettingCard,
    RangeSettingCard, setFont
)

import config
import browser_launcher
import session_source
from cache import MediaCache, LocalUserIndex
from engine import CrawlerEngine
from downloader import count_files
import xf_selectors as S


# Bảng màu log cho Light và Dark theme
LOG_COLORS_LIGHT = {
    "error": "#b42318",
    "summary": "#b45309",
    "success": "#15803d",
    "info": "#1d4ed8",
    "system": "#0e7490",
    "bulk": "#7e22ce",
    "skip": "#57534e",
    "dim": "#78716c",
}

LOG_COLORS_DARK = {
    "error": "#f87171",
    "summary": "#fbbf24",
    "success": "#4ade80",
    "info": "#60a5fa",
    "system": "#38bdf8",
    "bulk": "#c084fc",
    "skip": "#a8a29e",
    "dim": "#9ca3af",
}

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


def detect_log_tag(message: str, tag: Optional[str] = None) -> str:
    if tag:
        return tag
    m = _MARKER_RE.match(message)
    if m:
        return _MARKER_TAGS[m.group(1)]
    return "dim"


class WorkerSignals(QObject):
    """Signals để truyền dữ liệu an toàn từ async crawler loop sang Qt GUI thread."""
    sig_log = Signal(str, str)             # (message, tag)
    sig_status = Signal(str, str, str)     # (status_text, color_type, detail)
    sig_stats = Signal(int, int, int, str) # (images, videos, errors, detail)
    sig_finished = Signal(bool, bool, str) # (is_stopped, had_error, detail)


class CrawlWorker(QThread):
    """Worker QThread quản lý vòng đời của CrawlerEngine trong event loop riêng."""

    def __init__(self, cache: MediaCache, download_dir: str, stop_event: threading.Event,
                 coro_factory, parent=None):
        super().__init__(parent)
        self.cache = cache
        self.download_dir = download_dir
        self.stop_event = stop_event
        self.coro_factory = coro_factory
        self.signals = WorkerSignals()
        self.current_loop: Optional[asyncio.AbstractEventLoop] = None
        self.engine: Optional[CrawlerEngine] = None
        self.had_error = False
        self._n_image = 0
        self._n_video = 0
        self._n_error = 0
        self._last_detail = ""

    def log_bridge(self, message: str, tag: Optional[str] = None):
        """Hàm logger được truyền vào engine. Tự động phân tích thống kê và gửi Signal."""
        tag = detect_log_tag(message, tag)
        if tag in ("error", "summary") and message.lstrip().startswith("["):
            self.had_error = True

        m_img = re.search(r"(\d+)\s+ảnh", message)
        if m_img:
            self._n_image += int(m_img.group(1))

        m_vid = re.search(r"(\d+)\s+video", message)
        if m_vid:
            self._n_video += int(m_vid.group(1))

        m_err = re.search(r"(\d+)\s+tệp lỗi", message)
        if m_err:
            self._n_error += int(m_err.group(1))
        elif re.search(r"tệp lỗi", message):
            self._n_error += 1

        parts = []
        if self._n_image or self._n_video:
            parts.append(f"{self._n_image} ảnh, {self._n_video} video")
        if self._n_error:
            parts.append(f"{self._n_error} lỗi")
        if parts:
            self._last_detail = " · ".join(parts)
            self.signals.sig_stats.emit(self._n_image, self._n_video, self._n_error, self._last_detail)

        self.signals.sig_log.emit(message, tag)

    def emergency_cleanup(self):
        """Gọi khẩn cấp khi người dùng bấm Dừng hoặc tắt cửa sổ."""
        self.stop_event.set()
        loop = self.current_loop
        if loop and not loop.is_closed():
            try:
                if self.engine:
                    loop.call_soon_threadsafe(self.engine.emergency_cleanup)
            except RuntimeError:
                pass

    def run(self):
        loop = asyncio.new_event_loop()
        self.current_loop = loop
        asyncio.set_event_loop(loop)
        try:
            self.engine = CrawlerEngine(
                self.cache, self.log_bridge, self.stop_event, download_dir=self.download_dir
            )
            loop.run_until_complete(self.coro_factory(self.engine))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.had_error = True
            self.log_bridge(f"[-] Tiến trình dừng bất thường: {e}", "error")
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
            is_stopped = self.stop_event.is_set()
            self.signals.sig_finished.emit(is_stopped, self.had_error, self._last_detail)


class CrawlerInterface(QWidget):
    """Giao diện chính điều khiển quét XenForo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Tiêu đề trang
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_lbl = TitleLabel("XenForo Media Crawler", self)
        subtitle_lbl = CaptionLabel("Quét media tự động qua Playwright CDP • Khử trùng lặp SQLite • Windows 11 Fluent UI", self)
        subtitle_lbl.setTextColor(Qt.gray, Qt.gray)
        title_box.addWidget(title_lbl)
        title_box.addWidget(subtitle_lbl)
        layout.addLayout(title_box)

        # ----------------- HÀNG 1: Thẻ Quét theo Tác giả -----------------
        self.card_author = CardWidget(self)
        layout_author = QVBoxLayout(self.card_author)
        layout_author.setContentsMargins(16, 14, 16, 14)
        layout_author.setSpacing(8)

        head_author = QHBoxLayout()
        head_author.addWidget(StrongBodyLabel("Quét theo tác giả trong chuyên mục", self.card_author))
        head_author.addStretch()
        layout_author.addLayout(head_author)

        grid_author = QGridLayout()
        grid_author.setSpacing(10)

        # Box URL
        lbl_box = BodyLabel("Chuyên mục (Box URL):", self.card_author)
        self.cmb_box_url = EditableComboBox(self.card_author)
        self.cmb_box_url.addItems(config.BOX_PRESETS)
        self.cmb_box_url.setCurrentIndex(0)
        grid_author.addWidget(lbl_box, 0, 0)
        grid_author.addWidget(self.cmb_box_url, 1, 0)

        # Username
        lbl_user = BodyLabel("Tên tác giả:", self.card_author)
        self.cmb_username = EditableComboBox(self.card_author)
        self.refresh_user_dropdown()
        grid_author.addWidget(lbl_user, 0, 1)
        grid_author.addWidget(self.cmb_username, 1, 1)

        # Nút quét tác giả
        self.btn_crawl_user = PrimaryPushButton(FluentIcon.DOWNLOAD, "Quét tác giả", self.card_author)
        self.btn_crawl_user.setFixedHeight(34)
        self.btn_crawl_user.clicked.connect(self.main_window.start_author_crawl)
        grid_author.addWidget(self.btn_crawl_user, 1, 2)

        grid_author.setColumnStretch(0, 3)
        grid_author.setColumnStretch(1, 2)
        grid_author.setColumnStretch(2, 1)
        layout_author.addLayout(grid_author)
        layout.addWidget(self.card_author)

        # ----------------- HÀNG 2: Thẻ Quét theo Bài viết & Toàn bộ -----------------
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(14)

        # Thẻ quét link bài viết
        self.card_thread = CardWidget(self)
        layout_thread = QVBoxLayout(self.card_thread)
        layout_thread.setContentsMargins(16, 14, 16, 14)
        layout_thread.setSpacing(8)
        layout_thread.addWidget(StrongBodyLabel("Quét riêng một bài viết (Thread URL)", self.card_thread))

        grid_thread = QHBoxLayout()
        grid_thread.setSpacing(10)
        self.ent_thread_url = LineEdit(self.card_thread)
        self.ent_thread_url.setPlaceholderText("Dán liên kết bài viết (ví dụ: https://domain/threads/bai-viet.123/)")
        self.ent_thread_url.setClearButtonEnabled(True)
        self.btn_crawl_thread = PrimaryPushButton(FluentIcon.DOCUMENT, "Quét bài viết", self.card_thread)
        self.btn_crawl_thread.setFixedHeight(34)
        self.btn_crawl_thread.clicked.connect(self.main_window.start_thread_crawl)
        grid_thread.addWidget(self.ent_thread_url, 1)
        grid_thread.addWidget(self.btn_crawl_thread)
        layout_thread.addLayout(grid_thread)
        row2_layout.addWidget(self.card_thread, 3)

        # Thẻ tác vụ mở rộng: Quét lại toàn bộ user
        self.card_bulk = CardWidget(self)
        layout_bulk = QVBoxLayout(self.card_bulk)
        layout_bulk.setContentsMargins(16, 14, 16, 14)
        layout_bulk.setSpacing(8)
        layout_bulk.addWidget(StrongBodyLabel("Đồng bộ hàng loạt", self.card_bulk))
        self.btn_crawl_all = PushButton(FluentIcon.SYNC, "Quét lại tất cả tác giả", self.card_bulk)
        self.btn_crawl_all.setFixedHeight(34)
        self.btn_crawl_all.clicked.connect(self.main_window.start_all_crawl)
        layout_bulk.addWidget(self.btn_crawl_all)
        row2_layout.addWidget(self.card_bulk, 1)

        layout.addLayout(row2_layout)

        # ----------------- HÀNG 3: Thẻ Điều khiển & Trạng thái -----------------
        self.card_status = CardWidget(self)
        layout_status = QHBoxLayout(self.card_status)
        layout_status.setContentsMargins(16, 12, 16, 12)
        layout_status.setSpacing(14)

        status_info_box = QVBoxLayout()
        status_info_box.setSpacing(2)
        self.lbl_state_title = StrongBodyLabel("SẴN SÀNG", self.card_status)
        self.lbl_state_detail = CaptionLabel("Chưa có tác vụ nào đang chạy.", self.card_status)
        self.lbl_state_detail.setTextColor(Qt.gray, Qt.gray)
        status_info_box.addWidget(self.lbl_state_title)
        status_info_box.addWidget(self.lbl_state_detail)
        layout_status.addLayout(status_info_box, 2)

        # Thanh tiến trình mượt
        self.progress_bar = IndeterminateProgressBar(self.card_status)
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(4)
        layout_status.addWidget(self.progress_bar, 3)

        # Nút Dừng khẩn cấp
        self.btn_stop = PushButton(FluentIcon.CANCEL, "Dừng khẩn cấp", self.card_status)
        self.btn_stop.setFixedHeight(34)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.main_window.stop_crawl)
        layout_status.addWidget(self.btn_stop, 1)

        layout.addWidget(self.card_status)

        # ----------------- HÀNG 4: Nhật ký hoạt động -----------------
        self.card_log = CardWidget(self)
        layout_log = QVBoxLayout(self.card_log)
        layout_log.setContentsMargins(16, 12, 16, 14)
        layout_log.setSpacing(10)

        log_head = QHBoxLayout()
        log_head.addWidget(StrongBodyLabel("Nhật ký chi tiết", self.card_log))
        log_head.addStretch()

        self.filter_edit = SearchLineEdit(self.card_log)
        self.filter_edit.setPlaceholderText("Lọc nhật ký...")
        self.filter_edit.setFixedWidth(220)
        self.filter_edit.textChanged.connect(self._apply_filter)
        log_head.addWidget(self.filter_edit)

        self.btn_copy = TransparentPushButton(FluentIcon.COPY, "Sao chép", self.card_log)
        self.btn_copy.clicked.connect(self._copy_log)
        log_head.addWidget(self.btn_copy)

        self.btn_clear = TransparentPushButton(FluentIcon.DELETE, "Xóa", self.card_log)
        self.btn_clear.clicked.connect(self._clear_log)
        log_head.addWidget(self.btn_clear)
        layout_log.addLayout(log_head)

        self.log_edit = TextEdit(self.card_log)
        self.log_edit.setReadOnly(True)
        font = QFont("Consolas", 10)
        self.log_edit.setFont(font)
        layout_log.addWidget(self.log_edit, 1)

        layout.addWidget(self.card_log, 1)

        # Kết nối sự kiện thay đổi input để tự động bật/tắt nút
        self.cmb_box_url.currentTextChanged.connect(self._check_inputs)
        self.cmb_username.currentTextChanged.connect(self._check_inputs)
        self.ent_thread_url.textChanged.connect(self._check_inputs)
        self._check_inputs()

    def refresh_user_dropdown(self):
        names = self.main_window.local_users.names()
        self.cmb_username.clear()
        self.cmb_username.addItems(names if names else ["traicube"])
        if names:
            self.cmb_username.setCurrentIndex(0)

    def _check_inputs(self):
        if self.main_window.is_crawling():
            return
        has_box = bool(self.cmb_box_url.currentText().strip())
        has_user = bool(self.cmb_username.currentText().strip())
        has_thread = bool(self.ent_thread_url.text().strip())

        self.btn_crawl_user.setEnabled(has_box and has_user)
        self.btn_crawl_thread.setEnabled(has_thread)
        self.btn_crawl_all.setEnabled(has_box)

    def _apply_filter(self):
        keyword = self.filter_edit.text().strip().lower()
        self.log_edit.clear()
        cursor = self.log_edit.textCursor()
        for message, tag in self.main_window.log_history:
            if not keyword or keyword in message.lower():
                self._append_formatted(message, tag, cursor)
        self.log_edit.moveCursor(QTextCursor.End)

    def append_log(self, message: str, tag: str):
        cursor = self.log_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        keyword = self.filter_edit.text().strip().lower()
        if not keyword or keyword in message.lower():
            self._append_formatted(message, tag, cursor)
            self.log_edit.moveCursor(QTextCursor.End)

    def _append_formatted(self, message: str, tag: str, cursor: QTextCursor):
        colors = LOG_COLORS_DARK if isDarkTheme() else LOG_COLORS_LIGHT
        color = colors.get(tag, colors["dim"])
        escaped = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html = f'<div style="color:{color}; line-height:135%;">{escaped}</div>'
        cursor.insertHtml(html)

    def _copy_log(self):
        text = self.log_edit.toPlainText()
        if not text.strip():
            InfoBar.warning(
                title="Thông báo",
                content="Nhật ký đang trống, không có gì để sao chép.",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=2500
            )
            return
        QApplication.clipboard().setText(text)
        InfoBar.success(
            title="Thành công",
            content=f"Đã sao chép {len(self.main_window.log_history)} dòng nhật ký vào clipboard.",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=2500
        )

    def _clear_log(self):
        self.main_window.log_history.clear()
        self.log_edit.clear()


class SettingsInterface(QWidget):
    """Giao diện Cài đặt theo chuẩn Fluent SettingCardGroup."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_box.addWidget(TitleLabel("Cài đặt hệ thống", self))
        caption = CaptionLabel("Tùy biến giao diện, thư mục lưu trữ, trình duyệt và giới hạn luồng cào", self)
        caption.setTextColor(Qt.gray, Qt.gray)
        title_box.addWidget(caption)
        layout.addLayout(title_box)

        # Nhóm Giao diện
        group_ui = SettingCardGroup("Giao diện & Chủ đề", self)
        self.card_theme = SettingCard(
            FluentIcon.PALETTE,
            "Chế độ màu",
            "Chuyển đổi giữa chế độ Tối, Sáng hoặc Tự động theo Windows",
            parent=group_ui
        )
        self.cmb_theme = ComboBox(self.card_theme)
        self.cmb_theme.addItems(["Tối (Dark Mode)", "Sáng (Light Mode)", "Tự động (Windows)"])
        saved = self.main_window.load_theme_setting()
        if saved == "light":
            self.cmb_theme.setCurrentIndex(1)
        elif saved == "auto":
            self.cmb_theme.setCurrentIndex(2)
        else:
            self.cmb_theme.setCurrentIndex(0)
        self.cmb_theme.currentIndexChanged.connect(self._on_theme_changed)
        self.card_theme.hBoxLayout.addWidget(self.cmb_theme)
        self.card_theme.hBoxLayout.addSpacing(16)
        group_ui.addSettingCard(self.card_theme)
        layout.addWidget(group_ui)

        # Nhóm Lưu trữ
        group_storage = SettingCardGroup("Lưu trữ & Dữ liệu", self)
        self.card_folder = PushSettingCard(
            text="Chọn thư mục",
            icon=FluentIcon.FOLDER,
            title="Thư mục tải về",
            content=self.main_window.download_dir,
            parent=group_storage
        )
        self.card_folder.clicked.connect(self._choose_download_dir)
        group_storage.addSettingCard(self.card_folder)
        layout.addWidget(group_storage)

        # Nhóm Phiên đăng nhập
        group_session = SettingCardGroup("Phiên đăng nhập", self)
        self.card_login = PushSettingCard(
            text="Đăng nhập",
            icon=FluentIcon.PEOPLE,
            title="Đăng nhập vào diễn đàn (chỉ cần một lần)",
            content=self._session_summary(),
            parent=group_session
        )
        self.card_login.clicked.connect(self._open_login_window)
        group_session.addSettingCard(self.card_login)
        layout.addWidget(group_session)

        # Nhóm Trình duyệt & Cổng CDP
        group_browser = SettingCardGroup("Trình duyệt", self)
        self.card_browser_launch = PushSettingCard(
            text="Mở trình duyệt Debug",
            icon=FluentIcon.APPLICATION,
            title=f"Cổng kết nối CDP: {config.CDP_PORT} (chế độ dự phòng)",
            content="Chỉ dùng khi BROWSER_MODE = \"cdp\". Chế độ mặc định "
                    "(persistent) không cần cổng này.",
            parent=group_browser
        )
        self.card_browser_launch.clicked.connect(self._launch_browser)
        group_browser.addSettingCard(self.card_browser_launch)
        layout.addWidget(group_browser)

        # Thông tin phiên bản
        group_about = SettingCardGroup("Thông tin phần mềm", self)
        card_about = PushSettingCard(
            text="V72 Fluent Edition",
            icon=FluentIcon.INFO,
            title="XenForo Media Crawler",
            content="Phiên bản V72 nâng cấp kiến trúc PySide6 + PyQt-Fluent-Widgets.",
            parent=group_about
        )
        card_about.button.setEnabled(False)
        group_about.addSettingCard(card_about)
        layout.addWidget(group_about)

        layout.addStretch()

    def _on_theme_changed(self, index: int):
        if index == 0:
            setTheme(Theme.DARK)
            self.main_window.save_theme_setting("dark")
        elif index == 1:
            setTheme(Theme.LIGHT)
            self.main_window.save_theme_setting("light")
        else:
            setTheme(Theme.AUTO)
            self.main_window.save_theme_setting("auto")

    def _choose_download_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục lưu trữ media", self.main_window.download_dir
        )
        if folder:
            self.main_window.download_dir = os.path.abspath(folder)
            self.card_folder.setContent(self.main_window.download_dir)
            if not self.main_window.reload_storage():
                return
            InfoBar.success(
                title="Đã đổi thư mục",
                content=f"Thư mục lưu trữ mới: {self.main_window.download_dir}",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000
            )

    def _session_summary(self):
        """Dòng mô tả ngắn về trạng thái phiên, hiển thị trên thẻ Cài đặt."""
        try:
            browser = (config.SESSION_BROWSER or "chrome").lower()
            prof = session_source.resolve_profile(browser)
            running = session_source.is_browser_running(browser)
            parts = [f"{browser} · {prof}"]
            if running:
                parts.append("đang chạy (cần đóng trước khi quét)")
            return " | ".join(parts)
        except Exception:
            return "Chưa cấu hình phiên đăng nhập."

    def _open_login_window(self):
        """Mở trình duyệt CÓ CỬA SỔ để người dùng đăng nhập.

        Đây là điểm mấu chốt của mode persistent: mở bằng cùng `user_data_dir`
        với lúc quét, nên cookie đăng nhập nằm đúng chỗ và các phiên sau tự
        dùng lại — không cần đăng nhập lại.

        Phải kiểm tra trước: nếu trình duyệt của profile đó đang chạy thì
        Chromium giữ khoá ProcessSingleton và tiến trình mới thoát ngay.
        """
        browser = (config.SESSION_BROWSER or "chrome").lower()
        exe = browser_launcher.find_browser_for(browser)
        if not exe:
            InfoBar.error(
                title="Không tìm thấy trình duyệt",
                content=f"Không thấy {browser}. Cài nó hoặc đổi SESSION_BROWSER "
                        f"trong config.py.",
                parent=self, position=InfoBarPosition.TOP_RIGHT, duration=6000)
            return

        prof = session_source.resolve_profile(browser)

        # Profile mặc định của trình duyệt đang chạy -> không mở được (khoá).
        installed = session_source.find_installed_profiles().get(browser, {}).get("path", "")
        if installed and os.path.abspath(prof) == os.path.abspath(installed) \
                and session_source.is_browser_running(browser):
            InfoBar.warning(
                title="Trình duyệt đang chạy",
                content=f"Hãy đóng {browser} hoàn toàn trước khi dùng profile của nó, "
                        f"hoặc để profile riêng của app (SESSION_PROFILE = \"\").",
                parent=self, position=InfoBarPosition.TOP_RIGHT, duration=8000)
            return

        if not session_source.profile_is_writable(prof):
            InfoBar.error(
                title="Không ghi được profile",
                content=f"{prof} không ghi được. Đổi SESSION_PROFILE trong config.py.",
                parent=self, position=InfoBarPosition.TOP_RIGHT, duration=6000)
            return

        def work():
            try:
                args = [exe, f"--user-data-dir={prof}"]
                args += list(getattr(config, "SESSION_EXTRA_ARGS", []) or [])
                # KHÔNG headless: người dùng cần thấy cửa sổ để đăng nhập.
                proc = subprocess.Popen(args)
                QTimer.singleShot(0, lambda: self._on_login_opened(browser, prof))
            except Exception as e:
                QTimer.singleShot(0, lambda: InfoBar.error(
                    title="Không mở được",
                    content=f"{type(e).__name__}: {e}",
                    parent=self, position=InfoBarPosition.TOP_RIGHT, duration=6000))

        threading.Thread(target=work, daemon=True).start()

    def _on_login_opened(self, browser, prof):
        InfoBar.success(
            title="Đã mở trình duyệt",
            content="Hãy đăng nhập vào diễn đàn trong cửa sổ vừa mở, rồi ĐÓNG nó. "
                    "Phiên sẽ được dùng lại ở các lần quét sau.",
            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=12000)
        self.card_login.setContent(self._session_summary())

    def _launch_browser(self):
        """Mở/chẩn đoán cổng CDP từ trang Cài đặt.

        Dùng probe_port() thay vì is_port_open(): bản cũ chỉ kiểm HTTP 200 nên
        một server bất kỳ chiếm cổng cũng làm nút này báo "đã sẵn sàng".
        """
        state = browser_launcher.probe_port()
        if state["state"] == "ready":
            InfoBar.info(
                title="Cổng đã sẵn sàng",
                content=f"Cổng {config.CDP_PORT}: {state['detail']}",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000
            )
            return
        if state["state"] == "not_chromium":
            InfoBar.error(
                title="Cổng bị chiếm",
                content=state["detail"],
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=6000
            )
            return

        def work():
            ok, msg = browser_launcher.launch()
            QTimer.singleShot(0, lambda: self._on_browser_launched(ok, msg))

        threading.Thread(target=work, daemon=True).start()

    def _on_browser_launched(self, ok: bool, msg: str):
        if ok:
            InfoBar.success(
                title="Khởi động thành công",
                content=msg,
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3500
            )
        else:
            InfoBar.error(
                title="Khởi động thất bại",
                content=msg,
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=5000
            )


class MainWindow(MSFluentWindow):
    """Cửa sổ chính của ứng dụng với thiết kế Fluent Design chuẩn Windows 11."""

    def __init__(self, auto_browser: bool = True):
        super().__init__()
        self.setWindowTitle("XenForo Crawler — V72 Fluent")
        self.resize(1100, 850)
        self.setMinimumSize(850, 720)

        self.download_dir = config.DOWNLOAD_DIR
        self._resolve_dir()

        self.cache = MediaCache(os.path.join(self.download_dir, "crawler_cache.db"))
        self.local_users = LocalUserIndex(self.cache.conn)
        self.local_users.refresh(self.download_dir)

        self.stop_event = threading.Event()
        self.worker: Optional[CrawlWorker] = None
        self.log_history = []  # Lưu (message, tag)

        # Thiết lập theme ban đầu
        saved_theme = self.load_theme_setting()
        if saved_theme == "light":
            setTheme(Theme.LIGHT)
        elif saved_theme == "auto":
            setTheme(Theme.AUTO)
        else:
            setTheme(Theme.DARK)

        # Khởi tạo giao diện trang con
        self.crawler_interface = CrawlerInterface(self)
        self.crawler_interface.setObjectName("crawlerInterface")
        self.settings_interface = SettingsInterface(self)
        self.settings_interface.setObjectName("settingsInterface")

        self.init_navigation()

        # Tự động nạp trình duyệt nếu cấu hình bật
        if auto_browser and config.AUTO_LAUNCH_BROWSER:
            QTimer.singleShot(500, self.auto_launch_browser)

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
        except Exception:
            pass
        self.cache = MediaCache(os.path.join(self.download_dir, "crawler_cache.db"))
        self.local_users = LocalUserIndex(self.cache.conn)
        self.local_users.refresh(self.download_dir)
        self.crawler_interface.refresh_user_dropdown()
        return True

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

        # mode == "cdp": giữ nguyên đường cũ.
        if not config.AUTO_LAUNCH_BROWSER:
            return

        state = browser_launcher.probe_port()
        if state["state"] == "ready":
            self.append_log(f"[*] Cổng {config.CDP_PORT} đã sẵn sàng "
                            f"({state['detail']}).", "system")
            return
        if state["state"] == "not_chromium":
            self.append_log(f"[!] {state['detail']} Đổi CDP_PORT trong config.py "
                            f"hoặc tắt tiến trình đang giữ cổng.", "error")
            return

        def work():
            ok, msg = browser_launcher.launch()
            tag = "system" if ok else "error"
            symbol = "✓" if ok else "!"
            QTimer.singleShot(0, lambda: self.append_log(f"[{symbol}] {msg}", tag))

        threading.Thread(target=work, daemon=True).start()

    def append_log(self, message: str, tag: str = "info"):
        self.log_history.append((message, tag))
        if len(self.log_history) > 1500:
            self.log_history = self.log_history[-1500:]
        self.crawler_interface.append_log(message, tag)

    def _theme_file_path(self) -> str:
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
        candidates = [
            os.path.join(os.path.expanduser("~"), ".xenforo_theme"),
            os.path.join(os.getcwd(), ".xenforo_theme"),
        ]
        for path in candidates:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    t = f.read().strip()
                    if t in ("light", "dark", "auto"):
                        return t
            except OSError:
                pass
        return "dark"

    def save_theme_setting(self, theme_str: str):
        path = self._theme_file_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(theme_str)
        except OSError:
            pass

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
        self.worker.start()

    def stop_crawl(self):
        if not self.is_crawling():
            return
        self.stop_event.set()
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
            ci.lbl_state_title.setText("ĐANG QUÉT")
            ci.lbl_state_detail.setText(f"Tác vụ: {task_desc}...")
        else:
            ci.btn_stop.setEnabled(False)
            ci.progress_bar.stop()
            ci.progress_bar.setVisible(False)
            ci._check_inputs()

    def _on_stats_updated(self, images: int, videos: int, errors: int, detail: str):
        if self.is_crawling():
            self.crawler_interface.lbl_state_detail.setText(f"Tiến độ: {detail}")

    def _on_crawl_finished(self, is_stopped: bool, had_error: bool, detail: str):
        self._set_ui_running(False)
        ci = self.crawler_interface
        if is_stopped:
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
            ci.lbl_state_title.setText("SẴN SÀNG")
            ci.lbl_state_detail.setText(f"Đã đồng bộ xong! {detail}" if detail else "Đã hoàn thành xuất sắc!")
            InfoBar.success(
                title="Hoàn tất",
                content=f"Đồng bộ thành công! {detail}",
                parent=self.crawler_interface,
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000
            )

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
        except Exception:
            pass
        try:
            browser_launcher.shutdown()
        except Exception:
            pass
        event.accept()


def main():
    # Bật High-DPI scaling cho màn hình 2K/4K
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
