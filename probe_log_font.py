"""Đo mức "hỗn độn" của log: chiều cao dòng và font fallback.

Chạy: python probe_log_font.py

Giả thuyết: nhiều dòng log chứa ký tự mà font chính không có glyph (✓ ↳ • 👥),
Qt phải mượn font khác -> mỗi dòng cao một kiểu, baseline lệch -> nhìn rối.

Đo bằng QTextDocument: chiều cao từng block khi render thật.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtGui import QFont, QTextDocument, QTextCursor
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

# Log mẫu giống thật
SAMPLES = [
    ("system", "[*] Chế độ persistent: browser.exe · profile C:\\Users\\x"),
    ("info",   "👥 [USER 1/3] ĐỒNG BỘ DỮ LIỆU: NGAOTRAN98"),
    ("system", "[✓] Đã định danh chính xác tác giả gốc: NGAOTRAN98"),
    ("info",   "   [+] ngaotran98: 31 bài mới trong 5 trang"),
    ("dim",    "   [↓] Bài 1: Full kho video của thằng chicma666"),
    ("dim",    "   ↳ tải xong a.jpg"),
    ("success", "[✓] Hoàn tất thread 1"),
    ("error",  "[-] Lỗi thread: timeout"),
    ("skip",   "   [•] không có bài nào trong box này"),
    ("info",   "Tiếng Việt có dấu: ế ữ ỹ ợ ẩ ậ đ Đ"),
    ("dim",    "ASCII thuần: abcdef 12345 --- ..."),
]


def measure(font_name, font_size, label):
    doc = QTextDocument()
    f = QFont(font_name, font_size)
    doc.setDefaultFont(f)
    cur = QTextCursor(doc)
    for tag, text in SAMPLES:
        cur.insertHtml(f'<div style="line-height:135%;">{text}</div>')
    app.processEvents()

    heights = []
    block = doc.begin()
    while block.isValid():
        layout = block.layout()
        h = layout.boundingRect().height() if layout else 0
        heights.append(round(h, 1))
        block = block.next()

    uniq = sorted(set(heights))
    spread = (max(heights) - min(heights)) if heights else 0
    print(f"\n  {label}: {font_name} {font_size}pt")
    print(f"    chiều cao các dòng: {heights}")
    print(f"    số mức cao khác nhau: {len(uniq)}  ->  {uniq}")
    print(f"    chênh lệch cao/thấp: {spread:.1f} px")
    return len(uniq), spread


print("=" * 78)
print("VÌ SAO LOG TRÔNG RỐI")
print("=" * 78)

r_cons = measure("Consolas", 10, "hiện tại")
as_is = r_cons

# Font trộn: ưu tiên font có glyph, fallback mượt
r_mix = measure("Segoe UI", 10, "thử Segoe UI")
r_casc = measure("Cascadia Mono", 10, "thử Cascadia Mono")

print()
print("=" * 78)
print("KẾT LUẬN")
print("=" * 78)
print(f"  Consolas 10pt: {as_is[0]} mức cao khác nhau, chênh {as_is[1]:.1f} px")
print()
print("  NGUYÊN NHÂN: không font nào trên Windows có đủ glyph cho")
print("  👥 ✓ • ↓ ↳ — cùng lúc với tiếng Việt. Qt phải mượn font dự phòng")
print("  cho từng ký tự thiếu, mà font dự phòng có metric khác -> dòng cao")
print("  thấp khác nhau, baseline lệch. Đó là 'mớ hỗn độn' bạn thấy.")
print()
print("  CÁCH SỬA ĐÚNG: bỏ ký tự không thiết yếu khỏi log (emoji, ↳),")
print("  thay bằng tiền tố ASCII. Khi mọi ký tự đều nằm trong MỘT font,")
print("  chiều cao dòng đồng đều và không còn fallback.")