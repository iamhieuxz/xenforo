"""Màn hình chờ lúc khởi động — chặn thao tác cho tới khi trình duyệt sẵn sàng.

VÌ SAO CẦN: lúc mở app ở chế độ CDP, app phải chờ Cốc Cốc/Chrome mở cổng debug
(đo được tới ~25s). Trước đây người dùng thấy giao diện bình thường nhưng mọi
nút bấm đều thất bại vì chưa có phiên trình duyệt. Overlay này phủ vùng nội
dung, hiện tiến độ thật (lấy từ on_progress của browser_launcher.launch) và chỉ
cho tương tác trở lại khi xong — hoặc khi người dùng bấm "Bỏ qua".
"""

import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from qfluentwidgets import ProgressBar, TransparentPushButton

from ui.theme import (
    MacCard, StatusDot, apply_widget_styles, palette, style_startup_overlay,
)


def _short(text: str, limit: int = 150) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


class StartupOverlay(QWidget):
    """Lớp phủ mờ + thẻ giữa màn hình, chặn tương tác với phần còn lại."""

    dismissed = Signal()
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("startupOverlay")
        self.setFocusPolicy(Qt.StrongFocus)

        card = MacCard(self, radius=16, padding=22, spacing=14)
        card.setFixedWidth(390)
        card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self._card = card
        body = card.body

        header = QHBoxLayout()
        header.setSpacing(12)

        logo = QLabel(card)
        logo_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "assets", "logo_64.png")
        if os.path.exists(logo_path):
            logo.setPixmap(QPixmap(logo_path).scaled(
                42, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setFixedSize(42, 42)
        header.addWidget(logo, 0, Qt.AlignTop)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.lbl_title = QLabel("XenForo Download", card)
        self.lbl_title.setObjectName("startupTitle")
        self.lbl_subtitle = QLabel("Đang chuẩn bị không gian làm việc", card)
        self.lbl_subtitle.setObjectName("startupSubtitle")
        titles.addWidget(self.lbl_title)
        titles.addWidget(self.lbl_subtitle)
        header.addLayout(titles, 1)
        body.addLayout(header)

        self.progress = ProgressBar(card)
        self.progress.setFixedHeight(5)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        body.addWidget(self.progress)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.dot = StatusDot("running", card)
        self.lbl_status = QLabel("Đang kiểm tra trình duyệt…", card)
        self.lbl_status.setObjectName("startupStatus")
        status_row.addWidget(self.dot, 0, Qt.AlignVCenter)
        status_row.addWidget(self.lbl_status, 1)
        body.addLayout(status_row)

        self.lbl_detail = QLabel("Phiên làm việc sẽ sẵn sàng trong giây lát.", card)
        self.lbl_detail.setObjectName("startupDetail")
        self.lbl_detail.setWordWrap(True)
        body.addWidget(self.lbl_detail)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.btn_skip = TransparentPushButton("Bỏ qua", card)
        self.btn_skip.setFixedHeight(30)
        self.btn_skip.setCursor(Qt.PointingHandCursor)
        self.btn_skip.clicked.connect(self._dismiss)
        actions.addWidget(self.btn_skip)
        body.addLayout(actions)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.addStretch(1)
        center = QHBoxLayout()
        center.addStretch(1)
        center.addWidget(card)
        center.addStretch(1)
        root.addLayout(center)
        root.addStretch(1)

        self.btn_skip.hide()
        self._skip_timer = QTimer(self)
        self._skip_timer.setSingleShot(True)
        self._skip_timer.timeout.connect(self.btn_skip.show)

        style_startup_overlay(self)
        apply_widget_styles(self)

    # ---------------------------------------------------------- paint
    def paintEvent(self, event):
        p = QPainter(self)
        color = QColor(palette()["canvas"])
        color.setAlpha(250)
        p.fillRect(self.rect(), color)

    # -------------------------------------------------------- controls
    def start(self):
        """Vào trạng thái chờ: tiến độ 0, nút Bỏ qua hiện sau 4 giây."""
        self.dot.set_state("running")
        self.lbl_status.setText("Đang kiểm tra trình duyệt…")
        self.lbl_detail.setText("Phiên làm việc sẽ sẵn sàng trong giây lát.")
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_skip.setText("Bỏ qua")
        self.btn_skip.hide()
        self._skip_timer.start(4000)
        self.setFocus()

    def set_progress(self, percent: int, detail: str = ""):
        if percent > 0:
            self.lbl_status.setText("Đang khởi động trình duyệt…")
        self.progress.setValue(max(0, min(100, int(percent))))
        if detail:
            self.lbl_detail.setText(detail)

    def finish_success(self, detail: str):
        self._skip_timer.stop()
        self.btn_skip.hide()
        self.dot.set_state("ready")
        self.lbl_status.setText("Đã sẵn sàng")
        self.lbl_detail.setText(_short(detail or "Trình duyệt đã sẵn sàng."))
        self.progress.setValue(100)
        QTimer.singleShot(900, self.hide)

    def finish_error(self, detail: str):
        self._skip_timer.stop()
        self.dot.set_state("error")
        self.lbl_status.setText("Chưa mở được trình duyệt")
        self.lbl_detail.setText(
            _short(detail) + "\nBạn vẫn có thể tiếp tục; app sẽ thử lại khi bắt đầu quét.")
        self.progress.setVisible(False)
        self.btn_skip.setText("Tiếp tục")
        self.btn_skip.show()

    def _dismiss(self):
        self._skip_timer.stop()
        self.hide()
        self.dismissed.emit()

    def showEvent(self, event):
        self.setFocus()
        super().showEvent(event)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.closed.emit()
