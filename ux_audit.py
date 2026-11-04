"""Audit hình học: đo widget tree ĐÃ RENDER, không mô tả ý định thiết kế.

Chạy: python ux_audit.py [rong] [cao]
Xuất: ux_geometry.txt + in tóm tắt ra màn hình.

Đo những thứ đo được bằng số: kích thước, khoảng cách, thứ tự tab, độ tương phản,
vị trí tương đối. Không chấm điểm thẩm mỹ — chỉ ra bằng chứng để người đọc tự thấy.
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk

width = int(sys.argv[1]) if len(sys.argv) > 1 else 1060
height = int(sys.argv[2]) if len(sys.argv) > 2 else 820

os.environ.setdefault("RPHANG_DIR", os.path.join(os.environ.get("TEMP", "."), "v72_audit"))
os.makedirs(os.environ["RPHANG_DIR"], exist_ok=True)

import v72

root = tk.Tk()
app = v72.XenForoScannerApp(root)
# XenForoScannerApp.__init__ tự gọi geometry("1060x820") nên phải đặt lại SAU.
root.geometry(f"{width}x{height}+60+40")
root.update_idletasks()
root.update()

rows = []


def walk(w, depth=0):
    for child in w.winfo_children():
        cls = child.winfo_class()
        try:
            text = str(child.cget("text"))
        except Exception:
            text = ""
        x, y = child.winfo_rootx() - root.winfo_rootx(), child.winfo_rooty() - root.winfo_rooty()
        cw, ch = child.winfo_width(), child.winfo_height()
        try:
            bg = str(child.cget("background"))
        except Exception:
            bg = ""
        try:
            fg = str(child.cget("foreground"))
        except Exception:
            fg = ""
        try:
            state = str(child.cget("state"))
        except Exception:
            state = ""
        rows.append({
            "depth": depth, "cls": cls, "text": str(text)[:52],
            "x": x, "y": y, "w": cw, "h": ch,
            "bg": bg, "fg": fg, "state": state,
        })
        walk(child, depth + 1)


walk(root)

lines = []
lines.append("=" * 100)
lines.append(f"AUDIT HÌNH HỌC — cửa sổ {width}x{height}")
lines.append("=" * 100)
lines.append(f"{'depth':>5} {'class':<14} {'x':>5} {'y':>5} {'w':>5} {'h':>5}  {'state':<9} text")
lines.append("-" * 100)
for r in rows:
    lines.append(
        f"{r['depth']:>5} {r['cls']:<14} {r['x']:>5} {r['y']:>5} {r['w']:>5} {r['h']:>5}  "
        f"{r['state']:<9} {r['text']}")

# ---- Phân tích ----
lines.append("")
lines.append("=" * 100)
lines.append("PHÂN TÍCH")
lines.append("=" * 100)

buttons = [r for r in rows if r["cls"] in ("Button", "TButton")]
lines.append(f"\n1. NÚT BẤM ({len(buttons)} cái)")
for b in buttons:
    verdict = "OK" if b["h"] >= 30 else "NHỎ"
    lines.append(f"   {b['text'][:34]:<36} {b['w']:>4}x{b['h']:<3} tại ({b['x']},{b['y']})  {verdict}")

entries = [r for r in rows if r["cls"] in ("Entry", "TEntry", "TCombobox")]
lines.append(f"\n2. Ô NHẬP ({len(entries)} cái)")
for e in entries:
    verdict = "OK" if e["h"] >= 26 else "THẤP"
    lines.append(f"   {e['cls']:<12} {e['w']:>4}x{e['h']:<3} tại ({e['x']},{e['y']})  {verdict}")

# Khoảng cách dọc giữa các khối lớn (card)
cards = [r for r in rows if r["cls"] == "Frame" and r["w"] > 300 and r["h"] > 60]
lines.append(f"\n3. KHỐI LỚN ({len(cards)} khối)")
seen = set()
for c in cards:
    key = (c["x"], c["y"], c["w"], c["h"])
    if key in seen:
        continue
    seen.add(key)
    lines.append(f"   {c['w']:>4}x{c['h']:<4} tại ({c['x']:>4},{c['y']:>4})")

# Vùng log: chiều cao so với tổng
log_boxes = [r for r in rows if r["cls"] == "Text"]
lines.append(f"\n4. VÙNG NHẬT KÝ")
for t in log_boxes:
    pct = 100.0 * t["h"] / height
    lines.append(f"   {t['w']}x{t['h']} tại ({t['x']},{t['y']}) — chiếm {pct:.0f}% chiều cao cửa sổ")

# ---- Tương phản thật của widget ----
lines.append("\n5. TƯƠNG PHẢN THỰC TẾ (đo trên widget render, không phải bảng màu)")


def lum(h):
    h = h.lstrip("#")
    if len(h) != 6:
        return None
    ch = []
    for i in (0, 2, 4):
        v = int(h[i:i + 2], 16) / 255
        ch.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def ratio(fg, bg):
    a, b = lum(fg), lum(bg)
    if a is None or b is None:
        return None
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


bad = 0
for r in rows:
    fg, bg = r["fg"], r["bg"]
    if not fg or not bg or fg == bg:
        continue
    cr = ratio(fg, bg)
    if cr is None:
        continue
    if cr < 4.5 and r["text"]:
        bad += 1
        lines.append(f"   THẤP {cr:.2f}:1  {r['cls']:<12} fg={fg} bg={bg}  '{r['text'][:30]}'")
lines.append(f"   -> {bad} widget có chữ dưới 4.5:1")

# ---- Thứ tự tab ----
lines.append("\n6. ĐỘ SÂU LỒNG NHAU (depth) — càng sâu càng khó đoán vị trí")
from collections import Counter
c = Counter(r["depth"] for r in rows)
for d in sorted(c):
    lines.append(f"   depth {d}: {c[d]} widget")

out = "\n".join(lines)
open("ux_geometry.txt", "w", encoding="utf-8").write(out)
print(f"da ghi ux_geometry.txt ({len(rows)} widget)")

# In tóm tắt
print("\n".join(lines[lines.index("PHÂN TÍCH") - 1:]))
root.destroy()
