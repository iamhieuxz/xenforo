"""Đọc nhật ký phiên chạy để debug.

Chạy:
    python check_log.py                 # phiên gần nhất: tóm tắt + lỗi
    python check_log.py --all           # liệt kê mọi phiên
    python check_log.py --tail 80       # 80 dòng cuối
    python check_log.py --level ERROR   # chỉ lỗi
    python check_log.py --file <path>   # một file cụ thể

Đây là công cụ trả lời "phiên vừa rồi có lỗi gì" mà không phải mở file bằng mắt.
"""

import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
import session_log as SL


def list_sessions():
    """Các file log, mới nhất trước."""
    d = getattr(config, "LOG_DIR", "")
    if not d or not os.path.isdir(d):
        return []
    files = [os.path.join(d, f) for f in os.listdir(d)
             if f.startswith("session-") and f.endswith(".log")]
    return sorted(files, key=os.path.getmtime, reverse=True)


def print_list():
    sessions = list_sessions()
    if not sessions:
        print(f"Chưa có log nào trong {getattr(config, 'LOG_DIR', '?')}")
        print("Chạy app một lần rồi thử lại.")
        return
    print("=" * 76)
    print(f"LOG TRONG {config.LOG_DIR}")
    print("=" * 76)
    for p in sessions:
        s = SL.summarize(p)
        size = os.path.getsize(p) / 1024
        print(f"  {os.path.basename(p):34} {size:8.1f} KB  "
              f"lỗi={s.get('errors', 0):3}  cảnh báo={s.get('warns', 0):3}")


def print_summary(path):
    s = SL.summarize(path)
    print("=" * 76)
    print(os.path.basename(path))
    print("=" * 76)
    if not s.get("ok"):
        print("  không đọc được file")
        return
    print(f"  đường dẫn : {s['path']}")
    print(f"  số dòng   : {s['lines']}")
    print(f"  lỗi       : {s['errors']}")
    print(f"  cảnh báo  : {s['warns']}")

    if s["top_errors"]:
        print()
        print("  LỖI HAY GẶP (gộp theo nội dung):")
        for msg, n in s["top_errors"]:
            print(f"    x{n:<3} {msg}")

    rows = SL.read_errors(path, "WARN")
    if rows:
        print()
        print(f"  CHI TIẾT (WARN trở lên, {len(rows)} dòng):")
        for t, lv, tag, msg in rows[:60]:
            print(f"    {t} {lv:5} [{tag:8}] {msg[:96]}")


def print_tail(path, n):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"không đọc được: {e}")
        return
    print("=" * 76)
    print(f"{n} dòng cuối của {os.path.basename(path)}")
    print("=" * 76)
    for line in lines[-n:]:
        print(f"  {line.rstrip()}")


def main():
    ap = argparse.ArgumentParser(description="Đọc nhật ký phiên chạy")
    ap.add_argument("--all", action="store_true", help="liệt kê mọi phiên")
    ap.add_argument("--file", help="đọc một file cụ thể")
    ap.add_argument("--level", default="",
                    choices=["", "DEBUG", "INFO", "WARN", "ERROR"])
    ap.add_argument("--tail", type=int, default=0)
    args = ap.parse_args()

    if args.all:
        print_list()
        return 0

    if args.file:
        path = args.file
    else:
        sessions = list_sessions()
        if not sessions:
            print(f"Chưa có log nào trong {getattr(config, 'LOG_DIR', '?')}")
            print("Chạy app một lần rồi thử lại.")
            return 0
        path = sessions[0]

    if args.tail:
        print_tail(path, args.tail)
        return 0

    print_summary(path)

    if args.level:
        rows = SL.read_errors(path, args.level)
        print()
        print(f"  LỌC MỨC {args.level} ({len(rows)} dòng):")
        for t, lv, tag, msg in rows[:80]:
            print(f"    {t} {lv:5} [{tag:8}] {msg[:96]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())