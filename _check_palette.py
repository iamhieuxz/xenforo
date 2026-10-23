"""Self-check: moi cap chu/nen trong PALETTE phai dat WCAG AA.

Chay: python _check_palette.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def hex_contrast(f1, f2):
    """Tương phản WCAG 2.x giữa hai mã hex."""
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    def lum(h):
        h = h.lstrip("#")
        r, g, b = (lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    a, b = lum(f1), lum(f2)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


from v72 import PALETTE  # noqa: E402

TEXT, UI = 4.5, 3.0
fail = 0

for name, p in PALETTE.items():
    print(f"== {name} ==")
    card, main, inp, fg = p["BG_CARD"], p["BG_MAIN"], p["BG_INPUT"], p["FG_TEXT"]

    # Chu chinh / phu phai doc tren ca nen the, nen app va o nhap.
    for label, fg_c in (("FG_TEXT", fg), ("FG_SUB", p["FG_SUB"]), ("ACCENT_TXT", p["ACCENT_TXT"])):
        for bg_name, bg in (("the", card), ("app", main), ("o nhap", inp)):
            r = hex_contrast(fg_c, bg)
            ok = r >= TEXT
            fail += not ok
            print(f"  {'ok ' if ok else 'NO '} {label} tren {bg_name}: {r:.2f}:1")

    # Nut: chu dat tren nen nut.
    for label, bg in (("ACCENT", p["ACCENT"]), ("DANGER", p["DANGER"])):
        r = hex_contrast(p["FG_ON_ACCENT"], bg)
        ok = r >= TEXT
        fail += not ok
        print(f"  {'ok ' if ok else 'NO '} {label}: chu tren nut = {r:.2f}:1")

    # Hover phai giu duoc nguong chu.
    r = hex_contrast(p["FG_ON_ACCENT"], p["ACCENT_HOVER"])
    fail += r < TEXT
    print(f"  {'ok ' if r >= TEXT else 'NO '} ACCENT_HOVER: chu = {r:.2f}:1")

    # Log tren nen o nhap - noi mat thu cong nhin nhieu nhat.
    for tag, c in p["LOG"].items():
        r = hex_contrast(c, inp)
        ok = r >= TEXT
        fail += not ok
        print(f"  {'ok ' if ok else 'NO '} log/{tag}: {r:.2f}:1")

    # Vien phai thay duoc tren ca nen the, o nhap va nen app (1.4.11).
    for bg_name, bg in (("the", card), ("app", main), ("o nhap", inp)):
        r = hex_contrast(p["BORDER"], bg)
        fail += r < UI
        print(f"  {'ok ' if r >= UI else 'NO '} vien tren {bg_name}: {r:.2f}:1 (can >= {UI})")

    # Nut disabled: phai phan biet duoc, khong bat buoc dat AA.
    r = hex_contrast(p["FG_SUB"], p["DISABLED"])
    print(f"  --  disabled nen {p['DISABLED']} + FG_SUB = {r:.2f}:1")

    print()

print(f"{fail} cap khong dat" if fail else "Tat ca cap dat WCAG 2.2 AA.")
sys.exit(1 if fail else 0)