"""Design system macOS cho giao diện XenForo Download.

Gồm 3 phần:
    - Token màu (Light/Dark) + QSS cho các control của qfluentwidgets
    - Widget tự vẽ: MacCard, IconBadge, StatusDot, HairLine
    - Khung macOS: MacTitleBar (traffic-light), MacSidebar

VÌ SAO TỰ VẼ THAY VÌ CHỈ QSS: CardWidget của qfluentwidgets vẽ nền bằng
paintEvent (không nhận background qua QSS), còn nút traffic-light cần hình
tròn và glyph khi hover — QSS không làm được hai việc này. Các control còn lại
(ô nhập, nút, combo) vẫn dùng QSS để giữ hành vi gốc của thư viện.
"""

import os

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from qfluentwidgets import isDarkTheme, setCustomStyleSheet
from qfluentwidgets.common.config import qconfig
from qfluentwidgets.common.style_sheet import setThemeColor
from qframelesswindow import TitleBarBase

from ui.log_view import swallow

# ---------------------------------------------------------------- tokens
ACCENT = "#007AFF"

LIGHT = {
    "canvas": "#F3F3F5",
    "sidebar": "#E9E9EC",
    "sidebar_border": "#DCDCE0",
    "card": "#FFFFFF",
    "card_border": "#ECECF0",
    "console": "#F7F7F9",
    "console_border": "#ECECEF",
    "text": "#1D1D1F",
    "text2": "#6E6E73",
    "text3": "#8E8E93",
    "accent": "#007AFF",
    "accent_hover": "#0071E3",
    "accent_pressed": "#0063CC",
    "accent_soft": "rgba(0, 122, 255, 0.10)",
    "accent_soft2": "rgba(0, 122, 255, 0.16)",
    "nav_selected": "rgba(0, 122, 255, 0.12)",
    "hover": "rgba(0, 0, 0, 0.045)",
    "pressed": "rgba(0, 0, 0, 0.08)",
    "separator": "#ECECEF",
    "disabled_bg": "#F2F2F4",
    "disabled_text": "#AEAEB2",
    "primary_disabled": "#B7D7FF",
    "danger": "#FF3B30",
    "danger_bg": "rgba(255, 59, 48, 0.10)",
    "danger_border": "rgba(255, 59, 48, 0.28)",
    "success": "#34C759",
    "warning": "#FF9500",
    "scroll_handle": "rgba(0, 0, 0, 0.18)",
    "scroll_handle_hover": "rgba(0, 0, 0, 0.32)",
}

DARK = {
    "canvas": "#1B1B1D",
    "sidebar": "#232325",
    "sidebar_border": "#303033",
    "card": "#2A2A2C",
    "card_border": "#38383A",
    "console": "#202022",
    "console_border": "#38383A",
    "text": "#F5F5F7",
    "text2": "#A1A1A6",
    "text3": "#7C7C80",
    "accent": "#0A84FF",
    "accent_hover": "#409CFF",
    "accent_pressed": "#0974D8",
    "accent_soft": "rgba(10, 132, 255, 0.16)",
    "accent_soft2": "rgba(10, 132, 255, 0.24)",
    "nav_selected": "rgba(10, 132, 255, 0.20)",
    "hover": "rgba(255, 255, 255, 0.06)",
    "pressed": "rgba(255, 255, 255, 0.10)",
    "separator": "#38383A",
    "disabled_bg": "#333335",
    "disabled_text": "#6E6E73",
    "primary_disabled": "#3E5C7A",
    "danger": "#FF453A",
    "danger_bg": "rgba(255, 69, 58, 0.16)",
    "danger_border": "rgba(255, 69, 58, 0.35)",
    "success": "#30D158",
    "warning": "#FF9F0A",
    "scroll_handle": "rgba(255, 255, 255, 0.20)",
    "scroll_handle_hover": "rgba(255, 255, 255, 0.34)",
}

FONT_FAMILIES = [
    "SF Pro Text", "SF Pro Display",
    "Segoe UI Variable Text", "Segoe UI",
]


def palette():
    return DARK if isDarkTheme() else LIGHT


def status_color(state):
    p = palette()
    return {
        "running": p["accent"],
        "ready": p["success"],
        "warning": p["warning"],
        "error": p["danger"],
    }.get(state, p["text3"])


# ------------------------------------------------------------ typography
def apply_macos_typography(app=None):
    """SF Pro nếu có, fallback Segoe UI Variable / Segoe UI."""
    try:
        qconfig.set(qconfig.fontFamilies, FONT_FAMILIES, save=False)
    except Exception as e:
        swallow("typography.font_families", e)
    if app is not None:
        font = app.font()
        font.setFamilies(FONT_FAMILIES)
        font.setPointSizeF(10.0)
        app.setFont(font)


def apply_accent_color():
    """Một accent xanh macOS cho mọi control dùng ThemeColor của thư viện."""
    try:
        setThemeColor(ACCENT, save=False)
    except TypeError:
        try:
            setThemeColor(ACCENT)
        except Exception as e:
            swallow("accent_color", e)
    except Exception as e:
        swallow("accent_color", e)


# ------------------------------------------------------------------ QSS
def _page_qss(p):
    return f"""
#pageTitle {{
    color: {p['text']};
    font-size: 22px;
    font-weight: 600;
    background: transparent;
}}
#pageCaption {{
    color: {p['text2']};
    font-size: 12px;
    background: transparent;
}}
#cardTitle {{
    color: {p['text']};
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}}
#cardCaption {{
    color: {p['text2']};
    font-size: 11px;
    background: transparent;
}}
#fieldLabel {{
    color: {p['text2']};
    font-size: 11px;
    font-weight: 500;
    background: transparent;
}}
#groupTitle {{
    color: {p['text']};
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}}
#sectionLabel {{
    color: {p['text2']};
    font-size: 10px;
    font-weight: 600;
    background: transparent;
}}
#sidebarTitle {{
    color: {p['text']};
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}}
#sidebarCaption {{
    color: {p['text2']};
    font-size: 11px;
    background: transparent;
}}
#versionLabel {{
    color: {p['text3']};
    font-size: 10px;
    background: transparent;
}}
#statusTitle {{
    color: {p['text']};
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}}
#statusDetail {{
    color: {p['text2']};
    font-size: 11px;
    background: transparent;
}}
"""


def _input_qss(p):
    return f"""
LineEdit, SearchLineEdit {{
    color: {p['text']};
    background-color: {p['card']};
    border: 1px solid {p['card_border']};
    border-radius: 8px;
    padding: 3px 10px;
    selection-background-color: {p['accent']};
    selection-color: #FFFFFF;
}}
LineEdit:hover, SearchLineEdit:hover {{
    border-color: {p['text3']};
}}
LineEdit:focus, SearchLineEdit:focus {{
    border: 1px solid {p['accent']};
    background-color: {p['card']};
}}
LineEdit:disabled, SearchLineEdit:disabled {{
    color: {p['disabled_text']};
    background-color: {p['disabled_bg']};
}}
"""


def _combo_qss(p):
    return f"""
ComboBox, ModelComboBox, EditableComboBox {{
    color: {p['text']};
    background-color: {p['card']};
    border: 1px solid {p['card_border']};
    border-radius: 8px;
    padding: 3px 30px 3px 10px;
    outline: none;
}}
ComboBox:hover, ModelComboBox:hover, EditableComboBox:hover {{
    border-color: {p['text3']};
}}
ComboBox:focus, ModelComboBox:focus, EditableComboBox:focus {{
    border: 1px solid {p['accent']};
}}
ComboBox:disabled, ModelComboBox:disabled, EditableComboBox:disabled {{
    color: {p['disabled_text']};
    background-color: {p['disabled_bg']};
}}
"""


def _secondary_button_qss(p):
    return f"""
PushButton {{
    color: {p['text']};
    background-color: {p['card']};
    border: 1px solid {p['card_border']};
    border-radius: 8px;
    padding: 6px 14px;
    font-weight: 500;
}}
PushButton:hover {{
    background-color: {p['hover']};
    border-color: {p['text3']};
}}
PushButton:pressed {{
    background-color: {p['pressed']};
}}
PushButton:disabled {{
    color: {p['disabled_text']};
    background-color: {p['disabled_bg']};
    border-color: {p['separator']};
}}
PushButton:focus {{
    border: 1px solid {p['accent']};
}}
"""


def _primary_button_qss(p):
    return f"""
PrimaryPushButton {{
    color: #FFFFFF;
    background-color: {p['accent']};
    border: 1px solid {p['accent']};
    border-radius: 8px;
    padding: 6px 16px;
    font-weight: 600;
}}
PrimaryPushButton:hover {{
    background-color: {p['accent_hover']};
    border-color: {p['accent_hover']};
}}
PrimaryPushButton:pressed {{
    background-color: {p['accent_pressed']};
    border-color: {p['accent_pressed']};
}}
PrimaryPushButton:disabled {{
    color: #FFFFFF;
    background-color: {p['primary_disabled']};
    border-color: {p['primary_disabled']};
}}
PrimaryPushButton:focus {{
    background-color: {p['accent_hover']};
}}
"""


def _ghost_button_qss(p):
    return f"""
TransparentPushButton {{
    color: {p['text2']};
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 4px 8px;
    font-weight: 500;
}}
TransparentPushButton:hover {{
    color: {p['accent']};
    background: {p['accent_soft']};
}}
TransparentPushButton:pressed {{
    color: {p['accent']};
    background: {p['accent_soft2']};
}}
TransparentPushButton:disabled {{
    color: {p['disabled_text']};
    background: transparent;
}}
TransparentPushButton:focus {{
    color: {p['accent']};
    background: {p['accent_soft']};
}}
"""


def _danger_button_qss(p):
    return f"""
PushButton {{
    color: {p['danger']};
    background-color: {p['danger_bg']};
    border: 1px solid {p['danger_border']};
    border-radius: 8px;
    padding: 6px 14px;
    font-weight: 600;
}}
PushButton:hover {{
    background-color: {p['danger_bg']};
    border-color: {p['danger']};
}}
PushButton:pressed {{
    background-color: {p['danger_bg']};
}}
PushButton:disabled {{
    color: {p['disabled_text']};
    background-color: {p['disabled_bg']};
    border-color: {p['separator']};
}}
"""


def _setting_card_qss(p):
    return f"""
SettingCard {{
    background: transparent;
    border: none;
}}
SettingCard QLabel {{
    color: {p['text']};
    font-size: 13px;
    background: transparent;
}}
SettingCard QLabel#contentLabel {{
    color: {p['text2']};
    font-size: 11px;
}}
SettingCard QPushButton {{
    color: {p['text']};
    background-color: {p['card']};
    border: 1px solid {p['card_border']};
    border-radius: 7px;
    padding: 4px 14px;
    font-size: 12px;
    font-weight: 500;
}}
SettingCard QPushButton:hover {{
    background-color: {p['hover']};
    border-color: {p['text3']};
}}
SettingCard QPushButton:pressed {{
    background-color: {p['pressed']};
}}
SettingCard QPushButton:disabled {{
    color: {p['disabled_text']};
    background-color: {p['disabled_bg']};
    border-color: {p['separator']};
}}
SettingCard QPushButton#primaryButton {{
    color: #FFFFFF;
    background-color: {p['accent']};
    border: 1px solid {p['accent']};
}}
"""


def _log_qss(p):
    return f"""
TextEdit {{
    color: {p['text']};
    background: transparent;
    border: none;
    padding: 2px;
    selection-background-color: {p['accent']};
    selection-color: #FFFFFF;
}}
"""


def _console_qss(p):
    return f"""
#logConsole {{
    background-color: {p['console']};
    border: 1px solid {p['console_border']};
    border-radius: 10px;
}}
"""


def _startup_qss(p):
    return f"""
#startupTitle {{
    color: {p['text']};
    font-size: 16px;
    font-weight: 600;
    background: transparent;
}}
#startupSubtitle {{
    color: {p['text2']};
    font-size: 11px;
    background: transparent;
}}
#startupStatus {{
    color: {p['text']};
    font-size: 12px;
    font-weight: 500;
    background: transparent;
}}
#startupDetail {{
    color: {p['text2']};
    font-size: 11px;
    background: transparent;
}}
"""


def _scroll_qss(p):
    return f"""
QScrollArea,
QScrollArea > QWidget > QWidget,
QScrollArea #qt_scrollarea_viewport {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: {p['scroll_handle']};
    border-radius: 3px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p['scroll_handle_hover']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
    background: transparent;
    border: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    height: 0px;
}}
"""


def _nav_item_qss(p):
    return f"""
#sidebarItem {{
    text-align: left;
    padding: 0px 8px;
    border: none;
    border-radius: 7px;
    background: transparent;
    color: {p['text']};
    font-size: 13px;
    font-weight: 500;
    outline: none;
}}
#sidebarItem:hover {{
    background: {p['hover']};
}}
#sidebarItem:pressed {{
    background: {p['pressed']};
}}
#sidebarItem:checked {{
    background: {p['nav_selected']};
    color: {p['accent']};
}}
#sidebarItem:focus {{
    background: {p['hover']};
}}
"""


_PAGE_QSS = (_page_qss(LIGHT), _page_qss(DARK))
_INPUT_QSS = (_input_qss(LIGHT), _input_qss(DARK))
_COMBO_QSS = (_combo_qss(LIGHT), _combo_qss(DARK))
_SECONDARY_QSS = (_secondary_button_qss(LIGHT), _secondary_button_qss(DARK))
_PRIMARY_QSS = (_primary_button_qss(LIGHT), _primary_button_qss(DARK))
_GHOST_QSS = (_ghost_button_qss(LIGHT), _ghost_button_qss(DARK))
_DANGER_QSS = (_danger_button_qss(LIGHT), _danger_button_qss(DARK))
_SETTING_CARD_QSS = (_setting_card_qss(LIGHT), _setting_card_qss(DARK))
_LOG_QSS = (_log_qss(LIGHT), _log_qss(DARK))
_CONSOLE_QSS = (_console_qss(LIGHT), _console_qss(DARK))
_NAV_QSS = (_nav_item_qss(LIGHT), _nav_item_qss(DARK))
_SCROLL_QSS = (_scroll_qss(LIGHT), _scroll_qss(DARK))
_STARTUP_QSS = (_startup_qss(LIGHT), _startup_qss(DARK))


class _ThemeQssWatcher(QObject):
    """Giữ QSS đúng theme cho widget KHÔNG thuộc qfluentwidgets.

    setCustomStyleSheet chỉ hoạt động với widget đã đăng ký trong
    StyleSheetManager của thư viện. QWidget/QFrame/QPushButton thuần không
    đăng ký, nên phải tự setStyleSheet và đổi lại khi theme đổi. Watcher được
    parent vào widget nên tự hủy theo widget.
    """

    def __init__(self, widget, light_qss, dark_qss):
        super().__init__(widget)
        self._widget = widget
        self._light_qss = light_qss
        self._dark_qss = dark_qss
        qconfig.themeChangedFinished.connect(self.apply)

    def apply(self):
        self._widget.setStyleSheet(
            self._dark_qss if isDarkTheme() else self._light_qss)


def apply_theme_qss(widget, light_qss, dark_qss):
    watcher = _ThemeQssWatcher(widget, light_qss, dark_qss)
    watcher.apply()
    return watcher


def style_page(widget):
    apply_theme_qss(widget, _PAGE_QSS[0], _PAGE_QSS[1])


def style_log_edit(widget):
    # TextEdit là widget qfluentwidgets (đã đăng ký) -> setCustomStyleSheet
    # được cộng dồn sau QSS gốc nên giữ được hành vi của thư viện.
    setCustomStyleSheet(widget, _LOG_QSS[0], _LOG_QSS[1])


def style_console(widget):
    apply_theme_qss(widget, _CONSOLE_QSS[0], _CONSOLE_QSS[1])


def style_scroll_area(widget):
    apply_theme_qss(widget, _SCROLL_QSS[0], _SCROLL_QSS[1])


def style_startup_overlay(widget):
    apply_theme_qss(widget, _STARTUP_QSS[0], _STARTUP_QSS[1])


def apply_widget_styles(root):
    """Áp QSS macOS cho mọi control qfluentwidgets trong cây widget."""
    from qfluentwidgets import (
        ComboBox, EditableComboBox, LineEdit, ModelComboBox,
        PrimaryPushButton, PushButton, SearchLineEdit, SettingCard,
        TransparentPushButton,
    )

    widgets = [root]
    try:
        widgets.extend(root.findChildren(QWidget))
    except Exception as e:
        swallow("apply_widget_styles.find", e)

    for w in widgets:
        try:
            role = w.property("macRole")
            if role == "danger":
                setCustomStyleSheet(w, _DANGER_QSS[0], _DANGER_QSS[1])
            elif isinstance(w, SettingCard):
                setCustomStyleSheet(w, _SETTING_CARD_QSS[0], _SETTING_CARD_QSS[1])
            elif isinstance(w, PrimaryPushButton):
                setCustomStyleSheet(w, _PRIMARY_QSS[0], _PRIMARY_QSS[1])
            elif isinstance(w, TransparentPushButton):
                setCustomStyleSheet(w, _GHOST_QSS[0], _GHOST_QSS[1])
            elif isinstance(w, PushButton):
                setCustomStyleSheet(w, _SECONDARY_QSS[0], _SECONDARY_QSS[1])
            elif isinstance(w, (LineEdit, SearchLineEdit)):
                setCustomStyleSheet(w, _INPUT_QSS[0], _INPUT_QSS[1])
            elif isinstance(w, (ComboBox, ModelComboBox, EditableComboBox)):
                setCustomStyleSheet(w, _COMBO_QSS[0], _COMBO_QSS[1])
        except Exception as e:
            swallow("apply_widget_styles.item", e)


# --------------------------------------------------------------- widgets
class MacCard(QFrame):
    """Card macOS: nền trắng/xám, viền hairline, bo 12, bóng mềm.

    shadow=False cho card chứa log: QGraphicsDropShadowEffect render lại cả
    cây con mỗi lần log cập nhật, trong khi log đã được tối ưu cho tốc độ.
    """

    def __init__(self, parent=None, radius=12, padding=16, spacing=12,
                 shadow=True):
        super().__init__(parent)
        self._radius = radius
        self._effect = None
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        if shadow:
            from PySide6.QtWidgets import QGraphicsDropShadowEffect
            self._effect = QGraphicsDropShadowEffect(self)
            self._effect.setBlurRadius(22)
            self._effect.setOffset(0, 4)
            self._sync_effect_color()
            self.setGraphicsEffect(self._effect)
            qconfig.themeChangedFinished.connect(self._sync_effect_color)

        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(spacing)

    def _sync_effect_color(self):
        if self._effect is None:
            return
        color = QColor(0, 0, 0)
        color.setAlpha(18 if not isDarkTheme() else 80)
        self._effect.setColor(color)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = palette()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(pal["card_border"]), 1))
        p.setBrush(QColor(pal["card"]))
        p.drawRoundedRect(rect, self._radius, self._radius)


class IconBadge(QWidget):
    """Ô vuông bo góc nền accent nhạt + icon đơn sắc, kiểu sidebar macOS."""

    def __init__(self, icon, parent=None, color=None, size=28, radius=9,
                 icon_size=16):
        super().__init__(parent)
        self._icon = icon
        self._color = color
        self._radius = radius
        self._icon_size = icon_size
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        qconfig.themeChangedFinished.connect(self.update)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor(self._color or palette()["accent"])
        bg = QColor(color)
        bg.setAlpha(26 if not isDarkTheme() else 40)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(self.rect(), self._radius, self._radius)

        pix = self._icon.icon(color=color).pixmap(
            self._icon_size, self._icon_size)
        x = (self.width() - pix.width()) // 2
        y = (self.height() - pix.height()) // 2
        p.drawPixmap(x, y, pix)


class StatusDot(QWidget):
    """Chấm trạng thái có quầng nhẹ. State: running/ready/warning/error."""

    def __init__(self, state="ready", parent=None):
        super().__init__(parent)
        self._state = state
        self.setFixedSize(10, 10)
        qconfig.themeChangedFinished.connect(self.update)

    def set_state(self, state):
        if state == self._state:
            return
        self._state = state
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor(status_color(self._state))
        glow = QColor(color)
        glow.setAlpha(55)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(self.rect())
        p.setBrush(color)
        p.drawEllipse(self.rect().adjusted(2, 2, -2, -2))


class HairLine(QWidget):
    """Đường phân cách 1px, màu theo theme."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        qconfig.themeChangedFinished.connect(self.update)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(palette()["separator"]))


# ------------------------------------------------------------ window controls
class WindowControlButton(QAbstractButton):
    """Nút điều khiển cửa sổ tối giản: vuông, to, dễ bấm, icon rõ."""

    SIZE = 36

    def __init__(self, symbol, tooltip, parent=None):
        super().__init__(parent)
        self._symbol = symbol  # "close" | "min" | "max"
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setAttribute(Qt.WA_Hover)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Nền hover / pressed
        if self.isDown():
            bg = QColor(0, 0, 0, 40)
        elif self.underMouse():
            bg = QColor(0, 0, 0, 25)
        else:
            bg = QColor(0, 0, 0, 0)

        if bg.alpha() > 0:
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(self.rect(), 6, 6)

        # Icon
        pen_color = QColor("#d9534f") if self._symbol == "close" else QColor("#555555")
        if self.underMouse() and self._symbol == "close":
            pen_color = QColor("#c9302c")
        pen = QPen(pen_color, 1.8)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)

        m = 11  # margin từ cạnh
        w = self.width()
        h = self.height()

        if self._symbol == "close":
            p.drawLine(QPointF(m, m), QPointF(w - m, h - m))
            p.drawLine(QPointF(w - m, m), QPointF(m, h - m))
        elif self._symbol == "min":
            p.drawLine(QPointF(m, h // 2), QPointF(w - m, h // 2))
        elif self._symbol == "max":
            p.drawRect(QRectF(m, m, w - 2 * m, h - 2 * m))


class MacTitleBar(TitleBarBase):
    """Title bar tối giản: nút điều khiển bên trái + tiêu đề, kéo cửa sổ được.

    Kế thừa TitleBarBase để giữ kéo/thả, double-click phóng to và resize
    của qframelesswindow. Nút đóng/mở rộng/thu nhỏ to hơn, dễ bấm.
    """

    HEIGHT = 44

    def __init__(self, parent):
        super().__init__(parent)

        for button in (self.minBtn, self.maxBtn, self.closeBtn):
            button.hide()

        self.setFixedHeight(self.HEIGHT)
        self.setAttribute(Qt.WA_TranslucentBackground)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(4)

        self.close_button = WindowControlButton("close", "Đóng", self)
        self.min_button = WindowControlButton("min", "Thu nhỏ", self)
        self.max_button = WindowControlButton("max", "Phóng to", self)
        self.close_button.clicked.connect(self.window().close)
        self.min_button.clicked.connect(self.window().showMinimized)
        self.max_button.clicked.connect(self._toggle_max)
        layout.addWidget(self.close_button)
        layout.addWidget(self.min_button)
        layout.addWidget(self.max_button)
        layout.addSpacing(12)
        layout.addStretch(1)

    def _toggle_max(self):
        window = self.window()
        if window.isMaximized():
            window.showNormal()
        else:
            window.showMaximized()


class SidebarItem(QPushButton):
    """Một dòng sidebar: icon + nhãn, chọn được, icon đổi màu theo trạng thái."""

    def __init__(self, icon, text, parent=None):
        super().__init__(text, parent)
        self._fluent_icon = icon
        self.setObjectName("sidebarItem")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(32)
        self.setIconSize(QSize(16, 16))
        self._apply_style()
        self.toggled.connect(self._refresh_icon)
        self._refresh_icon()

    def _apply_style(self):
        # QPushButton thuần không thuộc StyleSheetManager -> đặt QSS trực tiếp.
        self.setStyleSheet(_NAV_QSS[1] if isDarkTheme() else _NAV_QSS[0])

    def _refresh_icon(self):
        color = palette()["accent"] if self.isChecked() else palette()["text2"]
        self.setIcon(self._fluent_icon.icon(color=QColor(color)))

    def refresh_theme(self):
        self._apply_style()
        self._refresh_icon()
        self.update()


class LogoBadge(QWidget):
    """Logo app đặt trên nền nhẹ ở dark để không chìm vào sidebar tối.

    Ảnh logo có khung squircle màu navy rất tối (#0F172A); đặt trực tiếp lên
    sidebar dark (#232325) thì gần như dính thành một khối. Nền nhẹ + viền
    mảnh giúp logo tách khỏi sidebar mà vẫn giữ nguyên màu thương hiệu.
    """

    def __init__(self, parent=None, size=28, logo_size=24, radius=8):
        super().__init__(parent)
        self._radius = radius
        self._logo = None
        base = os.path.dirname(os.path.dirname(__file__))
        for name in ("logo_64.png", "logo_32.png"):
            path = os.path.join(base, "assets", name)
            if os.path.exists(path):
                self._logo = QPixmap(path).scaled(
                    logo_size, logo_size, Qt.KeepAspectRatio,
                    Qt.SmoothTransformation)
                break
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        qconfig.themeChangedFinished.connect(self.update)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if isDarkTheme():
            p.setPen(QPen(QColor(255, 255, 255, 26), 1))
            p.setBrush(QColor(255, 255, 255, 16))
            p.drawRoundedRect(
                QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                self._radius, self._radius)
        if self._logo is not None:
            x = (self.width() - self._logo.width()) // 2
            y = (self.height() - self._logo.height()) // 2
            p.drawPixmap(x, y, self._logo)


class MacSidebar(QWidget):
    """Sidebar macOS: logo + tên app, mục điều hướng, mục Cài đặt dưới đáy."""

    currentChanged = Signal(str)
    WIDTH = 176

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = {}
        self.setFixedWidth(self.WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.NoFocus)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(LogoBadge(self))

        name = QLabel("XenForo Download", self)
        name.setObjectName("sidebarTitle")
        header.addWidget(name)
        header.addStretch(1)
        root.addLayout(header)
        root.addSpacing(10)

        self._top = QVBoxLayout()
        self._top.setSpacing(2)
        root.addLayout(self._top)
        root.addStretch(1)

        self._bottom = QVBoxLayout()
        self._bottom.setSpacing(2)
        self._bottom.addWidget(HairLine(self))
        root.addLayout(self._bottom)

        qconfig.themeChangedFinished.connect(self.refresh_theme)
        self.refresh_theme()

    def addItem(self, key, icon, text, bottom=False):
        item = SidebarItem(icon, text, self)
        item.clicked.connect(lambda _=False, k=key: self._select(k))
        (self._bottom if bottom else self._top).addWidget(item)
        self._items[key] = item
        return item

    def _select(self, key):
        self.setCurrent(key)
        self.currentChanged.emit(key)

    def setCurrent(self, key):
        for k, item in self._items.items():
            item.setChecked(k == key)

    def refresh_theme(self):
        self.setStyleSheet(_PAGE_QSS[1] if isDarkTheme() else _PAGE_QSS[0])
        self.update()
        for item in self._items.values():
            item.refresh_theme()

    def paintEvent(self, event):
        p = QPainter(self)
        pal = palette()
        p.fillRect(self.rect(), QColor(pal["sidebar"]))
        p.setPen(QPen(QColor(pal["sidebar_border"]), 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
