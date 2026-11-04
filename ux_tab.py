"""Đo THỨ TỰ TAB THẬT bằng tk_focusNext, không đoán theo toạ độ.

Chạy: python ux_tab.py
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk

os.environ.setdefault("RPHANG_DIR", os.path.join(os.environ.get("TEMP", "."), "v72_tab"))
os.makedirs(os.environ["RPHANG_DIR"], exist_ok=True)

import v72

root = tk.Tk()
app = v72.XenForoScannerApp(root)
root.update_idletasks()
root.update()


def describe(w):
    """Tên dễ đọc cho widget."""
    names = {
        str(app.cmb_box_url): "Link Chuyên Mục",
        str(app.cmb_username): "Username",
        str(app.ent_thread_url): "Link Bài Viết",
        str(app.btn_download_user): "Nút: Quét 1 User",
        str(app.btn_download_link): "Nút: Quét 1 Thớt",
        str(app.btn_stop): "Nút: Dừng khẩn cấp",
        str(app.btn_update_all): "Nút: Cập nhật toàn bộ",
        str(app.btn_copy_log): "Nút: Sao chép",
        str(app.btn_clear_log): "Nút: Xóa",
        str(app.ent_filter): "Ô lọc nhật ký",
        str(app.btn_theme): "Nút: Giao diện",
        str(app.log_box): "Vùng nhật ký",
    }
    return names.get(str(w), f"{w.winfo_class()}?")


out = []
out.append("=" * 78)
out.append("THỨ TỰ TAB THẬT (tk_focusNext, giống khi bấm phím Tab)")
out.append("=" * 78)

# Bắt đầu từ widget đầu tiên trong toplevel
w = root.tk.call("tk_focusNext", root._w)
chain = []
seen = set()
for _ in range(30):
    if not w:
        break
    try:
        widget = root.nametowidget(w)
    except Exception:
        break
    key = str(widget)
    if key in seen:
        break
    seen.add(key)
    chain.append(describe(widget))
    w = root.tk.call("tk_focusNext", w)

for i, name in enumerate(chain, 1):
    out.append(f"   {i:>2}. {name}")

out.append("")
out.append("=" * 78)
out.append("SO VỚI THỨ TỰ THỊ GIÁC MONG ĐỢI")
out.append("=" * 78)
expected = [
    "Link Chuyên Mục", "Username", "Link Bài Viết",
    "Nút: Quét 1 User", "Nút: Quét 1 Thớt", "Nút: Cập nhật toàn bộ",
    "Nút: Dừng khẩn cấp", "Ô lọc nhật ký", "Nút: Sao chép", "Nút: Xóa",
]
out.append("   Mong đợi (trên -> dưới, trái -> phải):")
for i, name in enumerate(expected, 1):
    out.append(f"      {i:>2}. {name}")
out.append("")
out.append(f"   Thực tế có {len(chain)} điểm dừng tab")
missing = [e for e in expected if e not in chain]
extra = [c for c in chain if c not in expected]
if missing:
    out.append(f"   THIẾU khỏi chuỗi tab: {missing}")
if extra:
    out.append(f"   THỪA trong chuỗi tab: {extra}")

# So sánh vị trí tương đối
if chain:
    common = [c for c in chain if c in expected]
    exp_order = [e for e in expected if e in chain]
    if common != exp_order:
        out.append("")
        out.append("   => THỨ TỰ KHÁC mong đợi:")
        for i, (a, b) in enumerate(zip(common, exp_order), 1):
            mark = "  " if a == b else " <--"
            out.append(f"      {i:>2}. thực tế={a:<28} mong đợi={b}{mark}")
    else:
        out.append("   => Thứ tự KHỚP mong đợi")

txt = "\n".join(out)
open("ux_tab.txt", "w", encoding="utf-8").write(txt)
print(txt)
root.destroy()
