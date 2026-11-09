"""Trang quét chính — bố cục macOS, giữ nguyên logic cũ."""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (QFont, QTextCursor, QTextCharFormat,
                           QTextBlockFormat, QColor)
# QApplication PHẢI có trong danh sách này: _copy_log() gọi
# QApplication.clipboard(). Thiếu nó thì bấm "Sao chép" ném NameError —
# lỗi lọt lưới từ đợt tách gui_fluent.py thành package ui/ (P2.1) vì
# không test nào gọi tới _copy_log.
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                               QGridLayout, QApplication, QLabel, QFrame)

from qfluentwidgets import (
    FluentIcon,
    PrimaryPushButton, PushButton, TransparentPushButton,
    LineEdit, SearchLineEdit, EditableComboBox,
    IndeterminateProgressBar, TextEdit,
    InfoBar, InfoBarPosition, isDarkTheme,
)

import config
import urllib.parse

from ui.log_view import (
    LOG_COLORS_LIGHT, LOG_COLORS_DARK,
    LOG_FONT_FAMILY, LOG_FONT_SIZE, LOG_GLYPH_MAP, LOG_MAX_CHARS,
    swallow,
)
from ui.theme import (
    MacCard, IconBadge, StatusDot, HairLine,
    style_page, style_console, style_log_edit,
)


def _label(text, object_name, parent):
    lbl = QLabel(text, parent)
    lbl.setObjectName(object_name)
    return lbl


class CrawlerInterface(QWidget):
    """Giao diện chính điều khiển quét XenForo."""

    LOG_FONT_FAMILY = LOG_FONT_FAMILY
    LOG_FONT_SIZE = LOG_FONT_SIZE
    LOG_GLYPH_MAP = LOG_GLYPH_MAP
    LOG_MAX_CHARS = LOG_MAX_CHARS

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        # Cho biết đang gom log và chưa vẽ lại (xem append_log).
        self._flush_pending = False
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # ------------------------- Header -------------------------
        title_row = QHBoxLayout()
        title_row.setSpacing(12)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title_box.addWidget(_label("Quét Media", "pageTitle", self))
        title_box.addWidget(_label(
            "Đồng bộ media XenForo theo tác giả, bài viết hoặc thư viện đã có",
            "pageCaption", self))
        title_row.addLayout(title_box)
        title_row.addStretch(1)
        layout.addLayout(title_row)

        # ----------------- HÀNG 1: Thẻ Quét theo Tác giả -----------------
        self.card_author = MacCard(self)
        body = self.card_author.body

        head_author = QHBoxLayout()
        head_author.setSpacing(10)
        head_author.addWidget(IconBadge(FluentIcon.DOWNLOAD, self.card_author))
        head_box = QVBoxLayout()
        head_box.setSpacing(1)
        head_box.addWidget(_label(
            "Quét theo tác giả", "cardTitle", self.card_author))
        head_box.addWidget(_label(
            "Chọn chuyên mục và tên tác giả cần đồng bộ",
            "cardCaption", self.card_author))
        head_author.addLayout(head_box)
        head_author.addStretch(1)
        body.addLayout(head_author)

        grid_author = QGridLayout()
        grid_author.setHorizontalSpacing(12)
        grid_author.setVerticalSpacing(6)

        lbl_box = _label("Chuyên mục (Box URL)", "fieldLabel", self.card_author)
        self.cmb_box_url = EditableComboBox(self.card_author)
        self._load_box_presets()
        self.cmb_box_url.setCurrentIndex(0)
        self.cmb_box_url.setFixedHeight(34)
        grid_author.addWidget(lbl_box, 0, 0)
        grid_author.addWidget(self.cmb_box_url, 1, 0)

        lbl_user = _label("Tên tác giả", "fieldLabel", self.card_author)
        self.cmb_username = EditableComboBox(self.card_author)
        self.refresh_user_dropdown()
        self.cmb_username.setFixedHeight(34)
        grid_author.addWidget(lbl_user, 0, 1)
        grid_author.addWidget(self.cmb_username, 1, 1)

        # Ô tìm kiếm tác giả — lọc dropdown theo tên
        user_search_row = QHBoxLayout()
        user_search_row.setSpacing(6)
        self.ent_search_user = SearchLineEdit(self.card_author)
        self.ent_search_user.setPlaceholderText("Tìm tác giả...")
        self.ent_search_user.setFixedHeight(30)
        self.ent_search_user.textChanged.connect(self._filter_users)
        user_search_row.addWidget(self.ent_search_user)
        grid_author.addLayout(user_search_row, 2, 1)

        grid_author.setColumnStretch(0, 3)
        grid_author.setColumnStretch(1, 2)
        body.addLayout(grid_author)

        body.addWidget(HairLine(self.card_author))

        # Domain là thiết lập phụ -> nằm chung hàng chân với CTA chính.
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(_label("Domain", "fieldLabel", self.card_author))
        self.ent_domain = LineEdit(self.card_author)
        self.ent_domain.setPlaceholderText("vd: rphang.show")
        self.ent_domain.setFixedWidth(180)
        self.ent_domain.setFixedHeight(34)
        self.ent_domain.setText(config.DOMAIN_OVERRIDE or "")
        self.btn_apply_domain = TransparentPushButton(
            FluentIcon.SYNC, "Áp dụng", self.card_author)
        self.btn_apply_domain.setFixedHeight(32)
        self.btn_apply_domain.clicked.connect(self._apply_domain)
        footer.addWidget(self.ent_domain)
        footer.addWidget(self.btn_apply_domain)
        footer.addStretch(1)

        self.btn_crawl_user = PrimaryPushButton(
            FluentIcon.DOWNLOAD, "Quét tác giả", self.card_author)
        self.btn_crawl_user.setFixedHeight(34)
        self.btn_crawl_user.setMinimumWidth(150)
        self.btn_crawl_user.clicked.connect(self.main_window.start_author_crawl)
        footer.addWidget(self.btn_crawl_user)

        # Nút reload danh sách tác giả — cập nhật tác giả mới lưu trong phiên
        self.btn_reload_users = PushButton(
            FluentIcon.SYNC, "Reload tác giả", self.card_author)
        self.btn_reload_users.setFixedHeight(34)
        self.btn_reload_users.setMinimumWidth(130)
        self.btn_reload_users.setToolTip("Cập nhật danh sách tác giả từ thư mục tải")
        self.btn_reload_users.clicked.connect(self._reload_users)
        footer.addWidget(self.btn_reload_users)

        # Nút thêm box mới vào preset — cùng style nút Quét, chỉ hiện khi box chưa có
        self.btn_add_box = PushButton(
            FluentIcon.ADD, "Lưu chuyên mục", self.card_author)
        self.btn_add_box.setFixedHeight(34)
        self.btn_add_box.setMinimumWidth(130)
        self.btn_add_box.setToolTip("Thêm chuyên mục này vào danh sách để chọn nhanh lần sau")
        self.btn_add_box.clicked.connect(lambda: self.main_window.add_current_box_to_presets())
        self.btn_add_box.setVisible(False)
        footer.addWidget(self.btn_add_box)
        body.addLayout(footer)
        layout.addWidget(self.card_author)

        # ----------------- HÀNG 2: Bài viết & Hàng loạt -----------------
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(16)

        self.card_thread = MacCard(self)
        body_thread = self.card_thread.body
        head_thread = QHBoxLayout()
        head_thread.setSpacing(10)
        head_thread.addWidget(IconBadge(FluentIcon.DOCUMENT, self.card_thread))
        head_thread_box = QVBoxLayout()
        head_thread_box.setSpacing(1)
        head_thread_box.addWidget(_label(
            "Quét một bài viết", "cardTitle", self.card_thread))
        head_thread_box.addWidget(_label(
            "Dán URL bài viết để quét riêng", "cardCaption", self.card_thread))
        head_thread.addLayout(head_thread_box)
        head_thread.addStretch(1)
        body_thread.addLayout(head_thread)
        body_thread.addStretch(1)

        grid_thread = QHBoxLayout()
        grid_thread.setSpacing(8)
        self.ent_thread_url = LineEdit(self.card_thread)
        self.ent_thread_url.setPlaceholderText("Dán URL bài viết...")
        self.ent_thread_url.setClearButtonEnabled(True)
        self.ent_thread_url.setFixedHeight(34)
        self.btn_crawl_thread = PrimaryPushButton(
            FluentIcon.DOCUMENT, "Quét bài viết", self.card_thread)
        self.btn_crawl_thread.setFixedHeight(34)
        self.btn_crawl_thread.clicked.connect(self.main_window.start_thread_crawl)
        grid_thread.addWidget(self.ent_thread_url, 1)
        grid_thread.addWidget(self.btn_crawl_thread)
        body_thread.addLayout(grid_thread)
        row2_layout.addWidget(self.card_thread, 1)

        self.card_bulk = MacCard(self)
        body_bulk = self.card_bulk.body
        head_bulk = QHBoxLayout()
        head_bulk.setSpacing(10)
        head_bulk.addWidget(IconBadge(FluentIcon.SYNC, self.card_bulk))
        head_bulk_box = QVBoxLayout()
        head_bulk_box.setSpacing(1)
        head_bulk_box.addWidget(_label(
            "Đồng bộ hàng loạt", "cardTitle", self.card_bulk))
        head_bulk_box.addWidget(_label(
            "Chạy lại toàn bộ tác giả đã có trong cache",
            "cardCaption", self.card_bulk))
        head_bulk.addLayout(head_bulk_box)
        head_bulk.addStretch(1)
        body_bulk.addLayout(head_bulk)
        self.lbl_bulk_count = _label(
            "", "cardCaption", self.card_bulk)
        body_bulk.addWidget(self.lbl_bulk_count)
        self._update_bulk_hint()
        body_bulk.addStretch(1)
        self.btn_crawl_all = PushButton(
            FluentIcon.SYNC, "Quét lại tất cả tác giả", self.card_bulk)
        self.btn_crawl_all.setFixedHeight(34)
        self.btn_crawl_all.clicked.connect(self.main_window.start_all_crawl)
        body_bulk.addWidget(self.btn_crawl_all)
        row2_layout.addWidget(self.card_bulk, 1)

        layout.addLayout(row2_layout)

        # ----------------- HÀNG 3: Nhật ký & Trạng thái -----------------
        # Không bóng: card này vẽ lại mỗi lần log cập nhật.
        self.card_log = MacCard(self, padding=16, spacing=12, shadow=False)
        body_log = self.card_log.body

        log_head = QHBoxLayout()
        log_head.setSpacing(10)
        log_head.addWidget(IconBadge(FluentIcon.HISTORY, self.card_log))
        log_head_box = QVBoxLayout()
        log_head_box.setSpacing(1)
        log_head_box.addWidget(_label(
            "Nhật ký chi tiết", "cardTitle", self.card_log))
        log_head_box.addWidget(_label(
            "Tiến trình, cảnh báo và lỗi của phiên quét",
            "cardCaption", self.card_log))
        log_head.addLayout(log_head_box)
        log_head.addStretch(1)

        self.filter_edit = SearchLineEdit(self.card_log)
        self.filter_edit.setPlaceholderText("Lọc nhật ký...")
        self.filter_edit.setFixedWidth(220)
        self.filter_edit.setFixedHeight(30)
        self.filter_edit.textChanged.connect(self._apply_filter)
        log_head.addWidget(self.filter_edit)

        self.btn_copy = TransparentPushButton(
            FluentIcon.COPY, "Sao chép", self.card_log)
        self.btn_copy.setFixedHeight(30)
        self.btn_copy.clicked.connect(self._copy_log)
        log_head.addWidget(self.btn_copy)

        self.btn_clear = TransparentPushButton(
            FluentIcon.DELETE, "Xóa", self.card_log)
        self.btn_clear.setFixedHeight(30)
        self.btn_clear.clicked.connect(self._clear_log)
        log_head.addWidget(self.btn_clear)
        body_log.addLayout(log_head)

        # Thanh trạng thái nằm ngay trên console, cùng một surface với nhật ký.
        self.card_status = QWidget(self.card_log)
        status_row = QHBoxLayout(self.card_status)
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(12)

        self.status_dot = StatusDot("ready", self.card_status)
        status_row.addWidget(self.status_dot)

        status_info_box = QVBoxLayout()
        status_info_box.setSpacing(1)
        self.lbl_state_title = _label(
            "SẴN SÀNG", "statusTitle", self.card_status)
        self.lbl_state_detail = _label(
            "Chưa có tác vụ nào đang chạy.", "statusDetail", self.card_status)
        status_info_box.addWidget(self.lbl_state_title)
        status_info_box.addWidget(self.lbl_state_detail)
        status_row.addLayout(status_info_box, 2)

        self.progress_bar = IndeterminateProgressBar(self.card_status)
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(4)
        status_row.addWidget(self.progress_bar, 3)

        self.btn_stop = PushButton(
            FluentIcon.CANCEL, "Dừng khẩn cấp", self.card_status)
        self.btn_stop.setFixedHeight(32)
        self.btn_stop.setMinimumWidth(130)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setProperty("macRole", "danger")
        self.btn_stop.clicked.connect(self.main_window.stop_crawl)
        status_row.addWidget(self.btn_stop)
        body_log.addWidget(self.card_status)
        body_log.addWidget(HairLine(self.card_log))

        self.log_console = QFrame(self.card_log)
        self.log_console.setObjectName("logConsole")
        console_layout = QVBoxLayout(self.log_console)
        console_layout.setContentsMargins(8, 6, 8, 6)
        console_layout.setSpacing(0)

        self.log_edit = TextEdit(self.log_console)
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText(
            "Chưa có phiên quét nào. Nhật ký sẽ hiện ở đây khi bắt đầu.")
        # Font monospace + setFixedPitch: cột thẳng hàng, mọi ký tự rộng bằng nhau.
        log_font = QFont()
        log_font.setFamilies([
            "SF Mono", "SFMono-Regular", "Cascadia Mono",
            self.LOG_FONT_FAMILY,
        ])
        log_font.setPointSize(self.LOG_FONT_SIZE)
        log_font.setStyleHint(QFont.Monospace)
        log_font.setFixedPitch(True)
        self.log_edit.setFont(log_font)
        # Tab = 4 space cố định, nếu không Qt tự chọn bề rộng và các dòng lệch nhau.
        self.log_edit.setTabStopDistance(
            self.log_edit.fontMetrics().horizontalAdvance(" ") * 4)
        self.log_edit.setLineWrapMode(TextEdit.WidgetWidth)
        self.log_edit.document().setDocumentMargin(6)
        console_layout.addWidget(self.log_edit)
        style_console(self.log_console)
        style_log_edit(self.log_edit)
        body_log.addWidget(self.log_console, 1)

        layout.addWidget(self.card_log, 1)

        # Kết nối sự kiện thay đổi input để tự động bật/tắt nút
        self.cmb_box_url.currentTextChanged.connect(self._check_inputs)
        self.cmb_box_url.currentTextChanged.connect(lambda _: self._update_add_box_button())
        self.cmb_username.currentTextChanged.connect(self._check_inputs)
        self.ent_thread_url.textChanged.connect(self._check_inputs)
        self._check_inputs()

        style_page(self)

    def _box_presets_file(self):
        """File lưu box presets tùy chỉnh của user.

        Lưu trong thư mục chạy app (cùng chỗ với .xenforo_theme) để tránh
        vấn đề quyền ghi ra HOME trên một số môi trường.
        """
        return os.path.join(os.getcwd(), ".xenforo_boxes")

    def _load_box_presets(self):
        """Nạp box presets: preset mặc định + box user đã lưu."""
        self.cmb_box_url.clear()
        presets = list(config.BOX_PRESETS)
        # Đọc box user đã lưu
        try:
            with open(self._box_presets_file(), "r", encoding="utf-8") as f:
                for line in f:
                    url = line.strip()
                    if url and url not in presets:
                        presets.append(url)
        except OSError:
            pass
        self.cmb_box_url.addItems(presets)

    def is_box_in_presets(self, box_url: str) -> bool:
        """True nếu box URL đã có trong danh sách preset (mặc định + user).

        Chỉ kiểm tra các item chính thức trong dropdown, KHÔNG tính text
        đang gõ/nhập — vì EditableComboBox.setText() có thể làm currentText
        khớp dù chưa addItem.
        """
        for i in range(self.cmb_box_url.count()):
            if self.cmb_box_url.itemText(i).strip() == box_url:
                return True
        return False

    def _update_add_box_button(self):
        """Hiện/ẩn nút thêm box dựa trên việc box hiện tại có trong preset chưa."""
        current = self.cmb_box_url.currentText().strip()
        if current and "/box/" in current:
            self.btn_add_box.setVisible(not self.is_box_in_presets(current))
        else:
            self.btn_add_box.setVisible(False)

    def refresh_user_dropdown(self):
        names = self.main_window.local_users.names()
        self._all_user_names = names if names else ["traicube"]
        self.cmb_username.clear()
        self.cmb_username.addItems(self._all_user_names)
        if self._all_user_names:
            self.cmb_username.setCurrentIndex(0)
        # Xóa ô tìm kiếm khi reload
        if hasattr(self, "ent_search_user"):
            self.ent_search_user.clear()
        self._update_bulk_hint()

    def _filter_users(self, keyword: str):
        """Lọc dropdown tác giả theo từ khóa tìm kiếm.

        Gõ text vào ô tìm kiếm → dropdown chỉ hiện các tên chứa keyword
        (không phân biệt hoa/thường). Ô trống → hiện lại toàn bộ.
        """
        keyword = keyword.strip().lower()
        self.cmb_username.clear()
        if not keyword:
            self.cmb_username.addItems(self._all_user_names)
        else:
            matched = [n for n in self._all_user_names if keyword in n.lower()]
            self.cmb_username.addItems(matched if matched else self._all_user_names)
        if self.cmb_username.count() > 0:
            self.cmb_username.setCurrentIndex(0)

    def _reload_users(self):
        """Reload danh sách tác giả từ thư mục tải và cập nhật dropdown.

        Quét lại thư mục download_dir → đồng bộ vào SQLite local_users →
        cập nhật dropdown. Dùng khi vừa quét xong và muốn thấy tác giả mới
        ngay mà không cần khởi động lại app.
        """
        try:
            count = self.main_window.local_users.refresh(self.main_window.download_dir)
            self.refresh_user_dropdown()
            InfoBar.success(
                title="Đã cập nhật",
                content=f"Tìm thấy {count} tác giả trong thư mục tải.",
                parent=self, position=InfoBarPosition.TOP_RIGHT, duration=3000)
        except Exception as e:
            InfoBar.error(
                title="Lỗi",
                content=f"Không thể reload: {e}",
                parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)

    def _update_bulk_hint(self):
        if not hasattr(self, "lbl_bulk_count"):
            return
        try:
            names = self.main_window.local_users.names()
        except Exception as e:
            swallow("crawler.bulk_hint", e)
            names = []
        self.lbl_bulk_count.setText(
            f"{len(names)} tác giả trong cache" if names
            else "Chưa có tác giả nào trong cache")

    def _check_inputs(self):
        if self.main_window.is_crawling():
            return
        has_box = bool(self.cmb_box_url.currentText().strip())
        has_user = bool(self.cmb_username.currentText().strip())
        has_thread = bool(self.ent_thread_url.text().strip())

        self.btn_crawl_user.setEnabled(has_box and has_user)
        self.btn_crawl_thread.setEnabled(has_thread)
        self.btn_crawl_all.setEnabled(has_box)

    def _apply_domain(self):
        """Thay domain trong preset và ô nhập URL.

        Khi forum đổi domain (vd: rphang.beer → rphang.show), user gõ tên mới
        vào ô Domain rồi bấm Áp dụng. Hàm này:
        1. Lưu domain mới vào config.DOMAIN_OVERRIDE
        2. Thay host trong mọi preset của BOX_PRESETS
        3. Thay host trong ô Box URL và ô Thread URL đang nhập
        4. Cập nhật lại dropdown preset
        """
        new_domain = self.ent_domain.text().strip()
        if not new_domain:
            InfoBar.warning(
                title="Thiếu domain",
                content="Nhập tên domain mới trước khi bấm Áp dụng.",
                parent=self, position=InfoBarPosition.TOP_RIGHT, duration=3000)
            return

        # Bỏ protocol nếu user gõ nhầm "https://rphang.show"
        new_domain = new_domain.replace("https://", "").replace("http://", "").rstrip("/")
        old_domain = config.DOMAIN_OVERRIDE or ""

        # Lấy domain từ preset đầu tiên nếu chưa có old_domain
        if not old_domain and config.BOX_PRESETS:
            try:
                parsed = urllib.parse.urlparse(config.BOX_PRESETS[0])
                old_domain = parsed.netloc
            except Exception:
                pass

        if not old_domain:
            InfoBar.warning(
                title="Không xác định được domain cũ",
                content="Không tìm thấy domain trong preset để thay thế.",
                parent=self, position=InfoBarPosition.TOP_RIGHT, duration=3000)
            return

        if old_domain == new_domain:
            InfoBar.info(
                title="Không đổi",
                content=f"Domain đã là {new_domain}.",
                parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)
            return

        # Thay trong preset
        replaced = 0
        for i, url in enumerate(config.BOX_PRESETS):
            new_url = url.replace(f"://{old_domain}/", f"://{new_domain}/")
            if new_url != url:
                config.BOX_PRESETS[i] = new_url
                replaced += 1

        # Lưu domain mới
        config.DOMAIN_OVERRIDE = new_domain

        # Thay trong ô đang nhập
        box_text = self.cmb_box_url.currentText()
        if old_domain in box_text:
            self.cmb_box_url.setCurrentText(box_text.replace(old_domain, new_domain))

        thread_text = self.ent_thread_url.text()
        if old_domain in thread_text:
            self.ent_thread_url.setText(thread_text.replace(old_domain, new_domain))

        # Cập nhật dropdown
        current = self.cmb_box_url.currentText()
        self.cmb_box_url.clear()
        self.cmb_box_url.addItems(config.BOX_PRESETS)
        # Giữ nguyên text đang nhập nếu còn trong list, hoặc giữ nguyên
        idx = self.cmb_box_url.findText(current)
        if idx >= 0:
            self.cmb_box_url.setCurrentIndex(idx)
        else:
            self.cmb_box_url.setCurrentText(current)

        InfoBar.success(
            title="Đã đổi domain",
            content=f"{old_domain} → {new_domain} ({replaced} preset được cập nhật)",
            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)

    def _apply_filter(self):
        keyword = self.filter_edit.text().strip().lower()
        self.log_edit.clear()
        cursor = self.log_edit.textCursor()
        for message, tag in self.main_window.log_history:
            if not keyword or keyword in message.lower():
                self._append_formatted(message, tag, cursor)
        self.log_edit.moveCursor(QTextCursor.End)

    def append_log(self, message: str, tag: str):
        """Thêm một dòng vào nhật ký.

        Hai chi phí ẩn ở đây, cả hai đều là nguyên nhân "chạy xong vẫn lag":

        1. QTextEdit layout lại tài liệu khi nội dung đổi. Đo được chi phí mỗi
           dòng tăng từ 0,12 ms (nhật ký ngắn) lên 2,0 ms (nhật ký dài) — tức
           chỉ 2.000 dòng log mất gần 4 giây.
        2. Gọi setHtml/insertHtml cho từng dòng khi widget đang hiển thị khiến
           Qt xếp lịch vẽ lại sau mỗi lần.

        Cách chặn: tắt updates của widget trong lúc ghi, chỉ bật lại theo nhịp
        (dùng QTimer) để không vẽ lại N lần cho N dòng.
        """
        keyword = self.filter_edit.text().strip().lower()
        if keyword and keyword not in message.lower():
            return

        # Chỉ cập nhật khi widget đang hiển thị; khi tab khác đang mở thì để
        # Qt tự vẽ lúc được hiện ra.
        self.log_edit.setUpdatesEnabled(False)
        try:
            cursor = QTextCursor(self.log_edit.document())
            cursor.movePosition(QTextCursor.End)
            self._append_formatted(message, tag, cursor)
            self._trim_log()
        finally:
            if not self._flush_pending:
                self._flush_pending = True
                # Gom nhiều dòng vào một lần vẽ thay vì vẽ từng dòng.
                QTimer.singleShot(80, self._flush_log)

    def _flush_log(self):
        self._flush_pending = False
        self.log_edit.setUpdatesEnabled(True)
        self.log_edit.moveCursor(QTextCursor.End)

    def _trim_log(self):
        """Giữ độ dài nhật ký ở mức giới hạn, cắt THEO DÒNG.

        Vì sao theo dòng chứ không theo ký tự: mỗi dòng log giờ là một paragraph
        thật (xem _append_formatted), nên cắt giữa ký tự sẽ chặt đôi một dòng và
        để lại nửa dòng rác ở đầu nhật ký. Cắt theo block thì mỗi dòng còn
        nguyên vẹn.

        Vì sao cần giới hạn: QTextEdit phải layout lại toàn bộ tài liệu khi vẽ,
        chi phí tăng theo độ dài. Đo được chi phí mỗi dòng:
            20.000 ký tự -> 0,29 ms/dòng
           120.000 ký tự -> 1,71 ms/dòng
        Không chặn thì phiên quét dài càng lúc càng chậm.
        """
        doc = self.log_edit.document()
        total = doc.characterCount()
        if total <= self.LOG_MAX_CHARS:
            return

        cut_to = int(self.LOG_MAX_CHARS * 0.8)
        excess = total - cut_to

        # Đếm xem cần bỏ bao nhiêu BLOCK để bớt được `excess` ký tự.
        removed = 0
        block = doc.begin()
        blocks_to_drop = 0
        while block.isValid() and removed < excess:
            removed += block.length()
            blocks_to_drop += 1
            block = block.next()

        if blocks_to_drop <= 0:
            return

        cur = QTextCursor(doc)
        cur.movePosition(QTextCursor.Start)
        # NextBlock giữ nguyên ranh giới dòng, không chặt đôi dòng nào.
        cur.movePosition(QTextCursor.NextBlock, QTextCursor.KeepAnchor,
                         blocks_to_drop)
        cur.removeSelectedText()

    def _append_formatted(self, message: str, tag: str, cursor: QTextCursor):
        """Ghi một dòng log bằng QTextCharFormat, KHÔNG dùng HTML.

        VÌ SAO BỎ HTML — đây là nguyên nhân chính của "mớ hỗn độn":

        `QTextCursor.insertHtml("<div>...</div>")` KHÔNG tạo xuống dòng trong
        QTextDocument của Qt. Đo được: chèn 5 dòng bằng insertHtml("<div>") thì
        `blockCount` vẫn = 1 và `toPlainText()` ra "dong 0dong 1dong 2dong 3" —
        tất cả dính thành một dòng dài, rồi widget tự ngắt theo bề rộng. Nhìn
        vào là một khối chữ, không phân biệt được dòng nào với dòng nào.

        Dùng insertText + QTextCharFormat: mỗi dòng là paragraph thật, xuống
        dòng đúng, giữ nguyên khoảng trắng thụt lề, màu áp theo format.

        Chuẩn hoá glyph cũng bắt buộc: font monospace trên Windows không có
        glyph cho ✓ ↳ 👥 (đo được: Consolas thiếu cả ba), Qt mượn font dự phòng
        có metric khác -> dòng chứa emoji cao 17px, dòng thường 15px.
        """
        colors = LOG_COLORS_DARK if isDarkTheme() else LOG_COLORS_LIGHT
        color = colors.get(tag, colors["dim"])

        text = message
        for bad, good in self.LOG_GLYPH_MAP.items():
            if bad in text:
                text = text.replace(bad, good)
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        block_fmt = QTextBlockFormat()
        block_fmt.setLineHeight(135.0, QTextBlockFormat.ProportionalHeight.value)
        block_fmt.setTopMargin(0)
        block_fmt.setBottomMargin(0)

        # PHẢI tách dòng bằng "\n" qua insertText, KHÔNG dùng insertBlock.
        #
        # Lý do đo được: insertBlock tạo block mới nhưng cursor do append_log
        # lấy bằng movePosition(End) lại nằm ở CUỐI BLOCK CUỐI, không phải ở
        # block mới. Kết quả: 9 dòng log vẫn ra blockCount = 1 và toPlainText()
        # dính thành một chuỗi. insertText("\n") tách block thật và vị trí
        # cursor vẫn đúng cho lần ghi sau.
        parts = text.split("\n")
        for i, part in enumerate(parts):
            cursor.insertText(part, fmt)
            if i < len(parts) - 1:
                cursor.insertText("\n", fmt)
        # Ngăn cách các lần gọi append_log. Không có bước này, lần ghi sau lại
        # nối tiếp vào cuối dòng trước.
        cursor.insertText("\n", fmt)

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


