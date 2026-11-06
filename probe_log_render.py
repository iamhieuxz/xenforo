"""Render nhật ký ra ảnh để NHÌN thấy vấn đề, không đoán.

Chạy: python probe_log_render.py
Xuất: log_before.png, log_after.png
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtGui import QFont, QTextCursor, QPixmap, QColor, QPainter
from PySide6.QtWidgets import QApplication, QTextEdit

app = QApplication.instance() or QApplication([])

# Log mẫu giống thật trong phiên vừa rồi
LINES = [
    ("system",  "[*] Trình duyệt: browser.exe | profile: C:\\Users\\iamhieuxz\\AppData\\Local\\CocCoc\\Browser\\User Data | ẩn"),
    ("system",  "[*] Đã lấy 783 cookie từ phiên đang mở (dùng cho tải nhanh, không lộ giá trị)."),
    ("info",    "👥 [USER 1/1] ĐỒNG BỘ DỮ LIỆU: NGAOTRAN98"),
    ("system",  "[✓] Đã định danh chính xác tác giả gốc: NGAOTRAN98"),
    ("dim",     "   [↓] Bài 1: Full kho video của thằng chicma666 aka baddirty"),
    ("dim",     "   ↳ tải xong /data/attachment-files/2024/08/1109053.mp4"),
    ("success", "[✓] Hoàn tất thread 1/31: 39 ảnh, 56 video, 0 tệp lỗi"),
    ("info",    "   [+] ngaotran98: 31 bài mới trong 5 trang (0 bài khác, 0 đã có)"),
    ("skip",    "   [•] không có bài nào trong box này (1 trang đã đọc)"),
    ("error",   "[-] Lỗi thread https://rphang.show/t/abc.123/: timeout sau 30s"),
    ("summary", "========================================"),
    ("info",    "Tiếng Việt có dấu: ế ữ ỹ ợ ẩ ậ đ Đ — kiểm tra hiển thị"),
    ("dim",     "ASCII thuần: abcdef 12345 --- ... ==="),
]

COLORS_DARK = {
    "error": "#f87171", "summary": "#fbbf24", "success": "#4ade80",
    "info": "#60a5fa", "system": "#38bdf8", "bulk": "#c084fc",
    "skip": "#a8a29e", "dim": "#9ca3af",
}


def render(path, font_name, size, title, use_div=True, replace_map=None):
    """Render log ra PNG, trả (cao, chiều_cao_từng_dòng)."""
    te = QTextEdit()
    f = QFont(font_name, size)
    f.setStyleHint(QFont.Monospace)
    f.setFixedPitch(True)
    te.setFont(f)
    te.setStyleSheet("QTextEdit { background:#1e1e1e; border:1px solid #333; }")
    te.resize(1100, 700)

    cur = QTextCursor(te.document())
    for tag, text in LINES:
        if replace_map:
            for a, b in replace_map.items():
                text = text.replace(a, b)
        color = COLORS_DARK.get(tag, "#9ca3af")
        esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if use_div:
            cur.insertHtml(
                f'<div style="color:{color}; line-height:135%;">{esc}</div>')
        else:
            cur.insertHtml(
                f'<pre style="color:{color}; margin:0; line-height:135%;">{esc}</pre>')
    te.show()
    app.processEvents()

    doc = te.document()
    doc.setTextWidth(te.viewport().width())
    app.processEvents()

    # Đo chiều cao từng dòng thực tế
    heights = []
    b = doc.begin()
    while b.isValid():
        lay = b.layout()
        if lay:
            lay.beginLayout()
            while True:
                line = lay.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(te.viewport().width())
                heights.append(round(line.height(), 1))
            lay.endLayout()
        b = b.next()

    # Lưu ảnh
    pm = QPixmap(te.size())
    pm.fill(QColor("#1e1e1e"))
    te.render(pm)
    pm.save(path)

    print(f"\n  {title}")
    print(f"    font: {font_name} {size}pt  ({'div' if use_div else 'pre'})")
    print(f"    số dòng đo được: {len(heights)}")
    print(f"    chiều cao: {heights}")
    uniq = sorted(set(heights))
    if len(uniq) > 1:
        print(f"    >>> KHÔNG ĐỀU: {len(uniq)} mức, chênh {max(heights)-min(heights):.1f} px")
    else:
        print(f"    >>> ĐỀU: tất cả {uniq[0]} px")
    print(f"    đã lưu: {path}")

    te.close()
    return heights


print("=" * 78)
print("RENDER NHẬT KÝ RA ẢNH")
print("=" * 78)

h1 = render("log_before.png", "Consolas", 10, "1. HIỆN TẠI (Consolas, div, có emoji)")

# Thử bỏ emoji
h2 = render("log_noemoji.png", "Consolas", 10, "2. BỎ EMOJI",
            replace_map={"👥 ": "", "↳ ": "  ", "✓ ": "[OK] ", "• ": "- ",
                         "↓": "v", "—": "-"})

print()
print("=" * 78)
print("SO SÁNH")
print("=" * 78)
u1, u2 = sorted(set(h1)), sorted(set(h2))
print(f"  Hiện tại : {len(u1)} mức cao {u1}  -> chênh {max(h1)-min(h1):.1f} px")
print(f"  Bỏ emoji : {len(u2)} mức cao {u2}  -> chênh {max(h2)-min(h2):.1f} px")
print()
if len(u1) > len(u2):
    print("  => EMOJI là nguyên nhân gây lệch chiều cao dòng.")
else:
    print("  => Cần xem ảnh để đánh giá thêm.")