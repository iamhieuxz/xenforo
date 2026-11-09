"""Trang cài đặt. Tách từ gui_fluent.py (P2.1)."""

import os
import subprocess
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QLabel, QFrame,
    QScrollArea,
)

from qfluentwidgets import (
    FluentIcon, ComboBox,
    Theme, setTheme, InfoBar, InfoBarPosition,
    SettingCard, PushSettingCard,
)

import config
import browser_launcher
import session_source
from ui.theme import MacCard, IconBadge, style_page, style_scroll_area


class SettingsInterface(QWidget):
    """Giao diện Cài đặt theo chuẩn Fluent SettingCardGroup."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._init_ui()

    def _init_ui(self):
        # Trang cài đặt có thể dài hơn cửa sổ: cuộn dọc, nền trong suốt để
        # canvas xám của cửa sổ lộ ra.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        style_scroll_area(self.scroll)
        outer.addWidget(self.scroll)

        container = QWidget()
        container.setAutoFillBackground(False)
        self.scroll.setWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 24, 24, 16)
        layout.setSpacing(16)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Cài đặt", container)
        title.setObjectName("pageTitle")
        caption = QLabel(
            "Tùy biến giao diện, thư mục lưu trữ, trình duyệt và giới hạn luồng cào",
            container)
        caption.setObjectName("pageCaption")
        title_box.addWidget(title)
        title_box.addWidget(caption)
        layout.addLayout(title_box)

        def make_group(group_title, icon):
            card = MacCard(container, padding=16, spacing=10)
            head = QHBoxLayout()
            head.setSpacing(10)
            head.addWidget(IconBadge(icon, card, size=26, radius=8))
            group_label = QLabel(group_title, card)
            group_label.setObjectName("groupTitle")
            head.addWidget(group_label)
            head.addStretch(1)
            card.body.addLayout(head)
            rows = QVBoxLayout()
            rows.setSpacing(0)
            card.body.addLayout(rows)
            layout.addWidget(card)
            return card, rows

        # Nhóm Giao diện
        group_ui, rows_ui = make_group(
            "Giao diện & Chủ đề", FluentIcon.PALETTE)
        self.card_theme = SettingCard(
            FluentIcon.BRIGHTNESS,
            "Chế độ màu",
            "Chuyển đổi giữa chế độ Tối, Sáng hoặc Tự động theo Windows",
            parent=group_ui
        )
        self.card_theme.setFixedHeight(64)
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
        rows_ui.addWidget(self.card_theme)

        # Nhóm Lưu trữ
        group_storage, rows_storage = make_group(
            "Lưu trữ & Dữ liệu", FluentIcon.FOLDER)
        self.card_folder = PushSettingCard(
            text="Chọn thư mục",
            icon=FluentIcon.FOLDER,
            title="Thư mục tải về",
            content=self.main_window.download_dir,
            parent=group_storage
        )
        self.card_folder.setFixedHeight(64)
        self.card_folder.clicked.connect(self._choose_download_dir)
        rows_storage.addWidget(self.card_folder)

        # Nhóm Phiên đăng nhập
        group_session, rows_session = make_group(
            "Phiên đăng nhập", FluentIcon.PEOPLE)
        self.card_login = PushSettingCard(
            text="Đăng nhập",
            icon=FluentIcon.PEOPLE,
            title="Đăng nhập vào diễn đàn (chỉ cần một lần)",
            content=self._session_summary(),
            parent=group_session
        )
        self.card_login.setFixedHeight(64)
        self.card_login.clicked.connect(lambda: self._open_login_window())
        rows_session.addWidget(self.card_login)

        # Nhóm Trình duyệt & Cổng CDP
        group_browser, rows_browser = make_group(
            "Trình duyệt", FluentIcon.APPLICATION)
        self.card_browser_launch = PushSettingCard(
            text="Mở trình duyệt Debug",
            icon=FluentIcon.APPLICATION,
            title=f"Cổng kết nối CDP: {config.CDP_PORT} (chế độ dự phòng)",
            content="Chỉ dùng khi BROWSER_MODE = \"cdp\". Chế độ mặc định "
                    "(persistent) không cần cổng này.",
            parent=group_browser
        )
        self.card_browser_launch.setFixedHeight(64)
        self.card_browser_launch.clicked.connect(self._launch_browser)
        rows_browser.addWidget(self.card_browser_launch)

        # Thông tin phiên bản
        group_about, rows_about = make_group(
            "Thông tin phần mềm", FluentIcon.INFO)
        card_about = PushSettingCard(
            text="V72 Fluent Edition",
            icon=FluentIcon.INFO,
            title="XenForo Media Crawler",
            content="Phiên bản V72 nâng cấp kiến trúc PySide6 + PyQt-Fluent-Widgets.",
            parent=group_about
        )
        card_about.setFixedHeight(64)
        card_about.button.setEnabled(False)
        rows_about.addWidget(card_about)

        layout.addStretch(1)
        style_page(container)

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
        """Dòng mô tả ngắn về trạng thái phiên, hiển thị trên thẻ Cài đặt.

        Phải theo ĐÚNG mode: mode cdp dùng profile của browser_launcher,
        mode persistent dùng profile riêng của app. Hiện nhầm profile thì người
        dùng thấy trạng thái không liên quan tới cái app thực sự dùng.
        """
        try:
            mode = (getattr(config, "BROWSER_MODE", "cdp") or "cdp").lower()
            if mode == "cdp":
                prof = browser_launcher.profile_dir()
                need, why = session_source.needs_first_login(prof)
                state = "chưa đăng nhập" if need else "đã đăng nhập"
                return f"chế độ CDP · {prof} · {state}"
            browser = (config.SESSION_BROWSER or "chrome").lower()
            prof = session_source.resolve_profile(browser)
            running = session_source.is_browser_running(browser)
            parts = [f"{browser} · {prof}"]
            if running:
                parts.append("đang chạy (cần đóng trước khi quét)")
            return " | ".join(parts)
        except Exception:
            return "Chưa cấu hình phiên đăng nhập."

    def _open_login_window(self, wait_for_login=False):
        """Mở trình duyệt CÓ CỬA SỔ để người dùng đăng nhập.

        Đây là điểm mấu chốt của mode persistent: mở bằng cùng `user_data_dir`
        với lúc quét, nên cookie đăng nhập nằm đúng chỗ và các phiên sau tự
        dùng lại — không cần đăng nhập lại.

        wait_for_login=True: sau khi mở, theo dõi file Cookies. Khi thấy
        `xf_user` xuất hiện (người dùng đăng nhập xong và đóng trình duyệt),
        báo để họ bấm Quét lại.
        """
        # PHẢI theo ĐÚNG mode đang chạy. Bản trước luôn dùng SESSION_BROWSER
        # (chrome) + resolve_profile() (profile riêng của app), nên ở mode cdp
        # (mặc định, dùng Cốc Cốc + profile thật) nút Đăng nhập lại mở Chrome
        # với một profile TẠM — đăng nhập xong cookie ghi vào chỗ khác, và lần
        # quét sau vẫn không thấy phiên. Đo được: mode=cdp/coccoc nhưng nút mở
        # chrome + F:\XENFORO2\tmp....
        mode = (getattr(config, "BROWSER_MODE", "cdp") or "cdp").lower()
        if mode == "cdp":
            browser = (getattr(config, "CDP_BROWSER", "coccoc") or "coccoc").lower()
            prof = browser_launcher.profile_dir()
        else:
            browser = (config.SESSION_BROWSER or "chrome").lower()
            prof = session_source.resolve_profile(browser)
        exe = browser_launcher.find_browser_for(browser)
        if not exe:
            InfoBar.error(
                title="Không tìm thấy trình duyệt",
                content=f"Không thấy {browser}. Cài nó hoặc đổi SESSION_BROWSER "
                        f"trong config.py.",
                parent=self, position=InfoBarPosition.TOP_RIGHT, duration=6000)
            return

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
                subprocess.Popen(args)
                # Phat signal thay vi QTimer.singleShot: QTimer tao trong thread
                # khong co event loop thi khong bao gio chay (da do).
                self.main_window.sig_ui_login_opened.emit(
                    browser, prof, bool(wait_for_login))
            except Exception as e:
                # PHẢI tính chuỗi LỜI NGAY tại đây (trong except), không để lambda
                # tự đọc `e`. Ở Python 3, biến `e` bị XOÁ khi ra khỏi khối except,
                # nên lambda chạy sau (qua QTimer) ném NameError: name 'e' is not
                # defined. Đo được: lỗi này xảy ra đúng khi mở trình duyệt thất
                # bại — tức lúc cần thông báo lỗi nhất thì app lại crash thêm.
                msg = f"{type(e).__name__}: {e}"
                self.main_window.sig_ui_notify.emit(
                    "error", "Không mở được", msg, 6000)

        threading.Thread(target=work, daemon=True).start()

    def _on_login_opened(self, browser, prof, wait_for_login=False):
        InfoBar.success(
            title="Đã mở trình duyệt để đăng nhập",
            content="Hãy đăng nhập vào diễn đàn trong cửa sổ vừa mở, rồi ĐÓNG nó. "
                    "App sẽ tự phát hiện và cho phép quét ẩn.",
            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=12000)
        self.card_login.setContent(self._session_summary())

        if wait_for_login:
            self._start_login_watch(browser, prof)

    def _start_login_watch(self, browser, prof, interval_ms=2000):
        """Theo dõi profile cho tới khi thấy cookie đăng nhập.

        Vì sao cần: người dùng đăng nhập xong rồi đóng trình duyệt, nhưng app
        không tự biết. Không theo dõi thì họ phải tự bấm Quét lại và đoán xem
        đã được chưa. Ở đây app kiểm file Cookies định kỳ (chỉ đọc được khi
        trình duyệt đã đóng) và báo ngay khi xong.
        """
        state = {"timer": None}

        def tick():
            need, why = session_source.needs_first_login(prof)
            if not need:
                if state["timer"] is not None:
                    state["timer"].stop()
                self.main_window.append_log("[✓] Đã phát hiện phiên đăng nhập. "
                                            "Giờ có thể quét ẩn.", "success")
                InfoBar.success(
                    title="Đã đăng nhập",
                    content="Phiên đã lưu. Bấm Quét để bắt đầu.",
                    parent=self, position=InfoBarPosition.TOP_RIGHT, duration=8000)
                self.card_login.setContent(self._session_summary())
                return
            # Trình duyệt còn mở thì chưa đọc được cookie — tiếp tục chờ.

        timer = QTimer(self)
        timer.setInterval(interval_ms)
        timer.timeout.connect(tick)
        timer.start()
        state["timer"] = timer

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
            self.main_window.sig_ui_notify.emit(
                "success" if ok else "error",
                "Khởi động thành công" if ok else "Khởi động thất bại",
                msg, 3500 if ok else 5000)

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


