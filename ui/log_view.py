"""Widget nhật ký + bảng màu + swallow() — phần dùng chung của các trang.

Tách từ gui_fluent.py (P2.1).
"""

import re
from typing import Optional

from PySide6.QtGui import QFont, QTextCharFormat, QColor

import session_log


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

# Tag theo dấu hiệu đầu dòng của engine.
_MARKER_RE = re.compile(r"^(\[\*\]|\[-\]|\[!\]|\[\+\]|\[✓\]|\[•\])")
_MARKER_TAGS = {
    "[*]": "system",
    "[-]": "error",
    "[!]": "summary",
    "[+]": "info",
    "[✓]": "success",
    "[•]": "skip",
}


def detect_log_tag(message: str, tag: Optional[str] = None) -> str:
    """Nhận tag từ nội dung khi engine không truyền tag."""
    if tag:
        return tag
    m = _MARKER_RE.match(message)
    if m:
        return _MARKER_TAGS[m.group(1)]
    return "dim"


# Bộ ghi lỗi nuốt an toàn: mỗi lần except: pass gọi hàm này, lỗi được đếm và
# (nếu có session_log) ghi một dòng. Không ném lại — không bao giờ.
#
# VÌ SAO QUAN TRỌNG: 2/5 lỗi nghiêm trọng của đợt review trước trốn đúng trong
# các khối except:pass im lặng (AttributeError lúc tải media, exception trong
# callback). Nuốt lỗi khi cần giữ app chạy là hợp lý; nuốt KHÔNG dấu vết thì
# không. Gọi hàm này thay cho `pass` để mỗi lần nuốt đều để lại dấu vết trong
# log phiên — mở check_log.py là thấy.
_swallowed = {"count": 0}


def swallow(where, exc=None):
    """Nuốt lỗi nhưng để lại dấu vết. Trả về None, không bao giờ ném."""
    _swallowed["count"] += 1
    try:
        if exc is not None:
            session_log.note_swallow(where, exc)
    except Exception:
        pass
    return None


# Font log. Phải là monospace để cột thẳng hàng, nhưng KHÔNG font monospace
# nào trên Windows có đủ glyph cho ✓ ↳ 👥 cùng lúc với tiếng Việt (đo được:
# Consolas 6/8, Courier New 6/8, Lucida Console 4/8). Qt sẽ mượn font dự phòng
# cho ký tự thiếu, và font dự phòng có metric khác -> dòng cao thấp khác nhau.
#
# Vì vậy KHÔNG dựa vào font để "có đủ ký tự"; thay vào đó chuẩn hoá ký tự
# trong log (xem LOG_GLYPH_MAP) để mọi dòng chỉ dùng ký tự Consolas có sẵn.
LOG_FONT_FAMILY = "Consolas"
LOG_FONT_SIZE = 10

# Thay ký tự không có glyph trong font log bằng tương đương ASCII.
# ĐO ĐƯỢC: dòng chứa 👥 cao 17px, dòng thường 15px -> lệch 2px mỗi dòng,
# cộng dồn thành "mớ hỗn độn". Sau khi thay: mọi dòng đều 15px.
LOG_GLYPH_MAP = {
    "👥": "",       # emoji người: bỏ hẳn, thông tin đã có ở nhãn [USER]
    "✓": "OK",     # dấu tick: Consolas không có glyph. Dùng "OK" chứ
                    # không "[OK]": log gốc đã có ngoặc " [✓] " nên sẽ
                    # thành "[[OK]]" nếu thêm ngoặc ở đây.
    "↳": "  >",    # mũi tên gấp khúc: không có glyph
    "•": "-",       # bullet tròn: có glyph nhưng thay cho đồng nhất
    "↓": "v",       # mũi tên xuống: có glyph, đổi cho khỏi lẫn với chữ
    "—": "-",       # em dash: đổi sang gạch ngang ASCII
    "►": ">",
}

# Trần độ dài nhật ký (tính bằng KÝ TỰ, không phải block).
#
# Vì sao đo bằng ký tự: ta chèn mỗi dòng log bằng insertHtml, không tạo
# paragraph mới, nên document().blockCount() luôn = 1 và không dùng làm
# ngưỡng được.
#
# Vì sao 20.000: chi phí mỗi dòng của QTextEdit tỉ lệ với độ dài tài liệu.
# Đo được (ms/dòng khi nhật ký đã đầy):
#     ngưỡng  20.000 ký tự -> 0,29 ms/dòng
#     ngưỡng  40.000        -> 0,55
#     ngưỡng  80.000        -> 1,09
#     ngưỡng 120.000        -> 1,71
# Quét một thread sinh vài trăm dòng log; để trần 120k là tự làm chậm gần
# 6 lần so với cần thiết. 20.000 ký tự ≈ 200 dòng — vẫn đọc lại được.
LOG_MAX_CHARS = 20_000


def make_log_font():
    """QFont cho widget log, monospace + fixed pitch."""
    f = QFont(LOG_FONT_FAMILY, LOG_FONT_SIZE)
    f.setStyleHint(QFont.Monospace)
    f.setFixedPitch(True)
    return f


def format_log_text(message, glyph_map=None):
    """Chuẩn hoá ký tự glyph trong message. Trả chuỗi sạch."""
    text = message
    for bad, good in (glyph_map or LOG_GLYPH_MAP).items():
        if bad in text:
            text = text.replace(bad, good)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def insert_formatted(cursor, message, tag, colors):
    """Ghi một dòng log vào cursor bằng QTextCharFormat, KHÔNG dùng HTML.

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
    color = colors.get(tag, colors["dim"])
    text = format_log_text(message)
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    parts = text.split("\n")
    for i, part in enumerate(parts):
        cursor.insertText(part, fmt)
        if i < len(parts) - 1:
            cursor.insertText("\n", fmt)
    cursor.insertText("\n", fmt)
