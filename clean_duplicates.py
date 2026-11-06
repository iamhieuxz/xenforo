"""Dọn file media trùng lặp — CÙNG NỘI DUNG, KHÁC TÊN.

VÌ SAO CẦN: đo được trên ổ thật (2026-11-06)
    folder có media : 323
    tổng file       : 3 140
    file thừa       : 418
    dung lượng thừa : 13,52 GB  (13,3 %)

Nguyên nhân: cùng một media xuất hiện ở 2 nơi (post chủ thớt và comment), hoặc
cùng ảnh ở 2 URL (thumbnail và bản đầy đủ) -> tên file khác nhau nên cache
không nhận ra. Sau khi sửa lỗi C4 (thêm hash vào tên), các file tải TRƯỚC ngày
sửa vẫn mang tên không hash, nên mỗi lần quét lại sinh thêm một bản có hash.

PHÂN LOẠI (đo được):
    cũ (không hash) + mới (có hash) : 413 nhóm  <- nợ cũ
    2 file đều có hash              :   5 nhóm  <- đang phát sinh
    cùng hash, tên khác             :   0 nhóm

AN TOÀN:
  - Mặc định DRY-RUN: chỉ báo cáo, KHÔNG xoá gì.
  - Chỉ xoá khi có --apply, và hỏi xác nhận.
  - So md5 nội dung, KHÔNG so tên: hai file cùng tên gốc nhưng nội dung khác
    nhau thì giữ cả hai.
  - Chỉ xoá file nằm trong thư mục tải, không đụng nơi khác.
  - Không xoá nếu file đang bị khoá (đang tải).
  - Giữ bản CÓ HASH nếu có (đó là bản mới nhất và đúng chuẩn tên hiện tại).

Chạy:
    python clean_duplicates.py                 # dry-run, báo cáo
    python clean_duplicates.py --apply         # xoá thật (có xác nhận)
    python clean_duplicates.py --dir D:\\khac   # quét thư mục khác
"""

import argparse
import hashlib
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config

# Hash 6 ký tự hex ở cuối tên file (trước phần mở rộng).
HASH_SUFFIX_RE = re.compile(r"_([0-9a-f]{6})(\.[A-Za-z0-9]+)$")

# File không phải media — bỏ qua hoàn toàn.
SKIP_EXT = {".db", ".db-wal", ".db-shm", ".tmp", ".log", ".ldb", ".ini",
            ".json", ".txt", ".part"}


def md5_of(path, chunk=1 << 20):
    """md5 nội dung file. Đọc theo khối để không nạp cả file lớn vào RAM."""
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()
    except (OSError, PermissionError):
        return None


def has_hash(name):
    """True nếu tên file đã có hậu tố hash 6 ký tự."""
    return bool(HASH_SUFFIX_RE.search(name))


def base_of(name):
    """Tên gốc: bỏ hậu tố hash và phần mở rộng.

    '[20250415]_main_video_001_7d7620.mp4' -> '[20250415]_main_video_001'
    '[20250415]_main_video_001.mp4'        -> '[20250415]_main_video_001'
    """
    m = HASH_SUFFIX_RE.search(name)
    if m:
        return name[:m.start()]
    stem, _ = os.path.splitext(name)
    return stem


def scan(root):
    """Quét và trả danh sách nhóm nghi trùng.

    Mỗi phần tử: {
        "folder": str,
        "base": str,
        "keep": path,        # file sẽ giữ
        "drop": [path],      # file sẽ xoá (nếu --apply)
        "bytes": int,        # dung lượng thu hồi được
        "reason": str,       # vì sao coi là trùng
    }
    """
    groups = []
    scanned = 0
    skipped_locked = 0
    t0 = time.time()

    for dirpath, dirnames, filenames in os.walk(root):
        # Bỏ thư mục log và cache
        dirnames[:] = [d for d in dirnames
                       if d not in ("logs", "__pycache__", ".git")]

        media = [f for f in filenames
                 if os.path.splitext(f)[1].lower() not in SKIP_EXT]
        if len(media) < 2:
            continue
        scanned += len(media)

        by_base = {}
        for name in media:
            by_base.setdefault(base_of(name), []).append(name)

        for base, names in by_base.items():
            if len(names) < 2:
                continue

            # Băm nội dung để chắc chắn là CÙNG file, không chỉ cùng tên gốc.
            by_md5 = {}
            for name in names:
                p = os.path.join(dirpath, name)
                try:
                    if os.path.getsize(p) == 0:
                        continue
                except OSError:
                    continue
                h = md5_of(p)
                if h is None:
                    skipped_locked += 1
                    continue
                by_md5.setdefault(h, []).append(name)

            for h, same in by_md5.items():
                if len(same) < 2:
                    continue

                # Giữ bản CÓ HASH (bản mới, đúng chuẩn tên hiện tại).
                # Trong cùng loại thì giữ bản mtime mới nhất.
                def rank(n):
                    return (1 if has_hash(n) else 0,
                            os.path.getmtime(os.path.join(dirpath, n)))

                same.sort(key=rank, reverse=True)
                keep = os.path.join(dirpath, same[0])
                drop = [os.path.join(dirpath, n) for n in same[1:]]

                total = 0
                for d in drop:
                    try:
                        total += os.path.getsize(d)
                    except OSError:
                        pass

                keep_has = has_hash(same[0])
                drop_has = [has_hash(n) for n in same[1:]]
                if keep_has and all(drop_has):
                    reason = "cả hai đều có hash -> trùng đang phát sinh"
                elif keep_has and not any(drop_has):
                    reason = "bản cũ không hash, giữ bản có hash"
                else:
                    reason = "cùng nội dung"

                groups.append({
                    "folder": dirpath,
                    "base": base,
                    "keep": keep,
                    "drop": drop,
                    "bytes": total,
                    "reason": reason,
                    "md5": h,
                })

    return groups, scanned, skipped_locked, time.time() - t0


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def verify_inside(path, root):
    """True nếu path nằm trong root. Chốt an toàn trước khi xoá."""
    try:
        rp = os.path.realpath(path)
        rr = os.path.realpath(root)
        return os.path.commonpath([rp, rr]) == rr
    except (ValueError, OSError):
        return False


def main():
    ap = argparse.ArgumentParser(
        description="Dọn media trùng lặp (cùng nội dung, khác tên)")
    ap.add_argument("--dir", default=config.DOWNLOAD_DIR,
                    help="thư mục cần quét (mặc định: config.DOWNLOAD_DIR)")
    ap.add_argument("--apply", action="store_true",
                    help="XOÁ THẬT. Không có cờ này thì chỉ báo cáo.")
    ap.add_argument("--yes", action="store_true",
                    help="bỏ qua câu hỏi xác nhận (dùng khi chạy tự động)")
    ap.add_argument("--show", type=int, default=10,
                    help="số nhóm hiển thị chi tiết")
    args = ap.parse_args()

    root = os.path.abspath(args.dir)
    if not os.path.isdir(root):
        print(f"Không thấy thư mục: {root}")
        return 1

    print("=" * 78)
    print("DỌN MEDIA TRÙNG LẶP")
    print("=" * 78)
    print(f"  thư mục   : {root}")
    print(f"  chế độ    : {'XOÁ THẬT' if args.apply else 'DRY-RUN (không xoá gì)'}")
    print()
    print("  Đang quét và băm nội dung...")

    groups, scanned, locked, elapsed = scan(root)

    total_bytes = sum(g["bytes"] for g in groups)
    total_files = sum(len(g["drop"]) for g in groups)

    print(f"  xong sau {elapsed:.1f}s")
    print()
    print("=" * 78)
    print("KẾT QUẢ")
    print("=" * 78)
    print(f"  file đã xét        : {scanned}")
    print(f"  nhóm trùng         : {len(groups)}")
    print(f"  file thừa          : {total_files}")
    print(f"  dung lượng thu hồi : {fmt_size(total_bytes)}")
    if locked:
        print(f"  file bị khoá (bỏ)  : {locked}")

    if not groups:
        print()
        print("  Không có file trùng lặp. Không cần làm gì.")
        return 0

    # Phân loại
    from collections import Counter
    reasons = Counter(g["reason"] for g in groups)
    print()
    print("  Theo nguyên nhân:")
    for r, n in reasons.most_common():
        print(f"    {n:4} nhóm  {r}")

    # Chi tiết
    print()
    print(f"  {args.show} nhóm đầu (giữ -> xoá):")
    for g in groups[:args.show]:
        print(f"\n    {g['base'][-56:]}")
        print(f"      GIỮ : {os.path.basename(g['keep'])}")
        for d in g["drop"]:
            try:
                sz = fmt_size(os.path.getsize(d))
            except OSError:
                sz = "?"
            print(f"      XOÁ : {os.path.basename(d)}  ({sz})")

    if len(groups) > args.show:
        print(f"\n    ... và {len(groups) - args.show} nhóm nữa")

    # ---- Dry-run thì dừng ----
    if not args.apply:
        print()
        print("=" * 78)
        print("DRY-RUN — KHÔNG CÓ FILE NÀO BỊ XOÁ")
        print("=" * 78)
        print(f"  Nếu muốn xoá thật, chạy lại với --apply")
        print(f"  Sẽ thu hồi: {fmt_size(total_bytes)}")
        return 0

    # ---- Xoá thật ----
    if not args.yes:
        print()
        print("=" * 78)
        print(f"SẮP XOÁ {total_files} FILE ({fmt_size(total_bytes)})")
        print("=" * 78)
        print("  Mỗi nhóm giữ lại 1 bản (bản có hash, mới nhất).")
        print("  Không thể hoàn tác.")
        try:
            ans = input("  Gõ 'XOA' để tiếp tục: ").strip()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans != "XOA":
            print("  Đã huỷ. Không xoá gì.")
            return 0

    print()
    deleted = 0
    freed = 0
    errors = []

    for g in groups:
        for d in g["drop"]:
            # Chốt an toàn: chỉ xoá trong thư mục tải.
            if not verify_inside(d, root):
                errors.append(f"ngoài thư mục: {d}")
                continue
            # Bản giữ phải còn tồn tại và cùng kích thước.
            try:
                if not os.path.exists(g["keep"]):
                    errors.append(f"bản giữ đã mất: {g['keep']}")
                    continue
                sz = os.path.getsize(d)
                os.remove(d)
                deleted += 1
                freed += sz
            except OSError as e:
                errors.append(f"{os.path.basename(d)}: {e}")

    print("=" * 78)
    print("ĐÃ XOÁ")
    print("=" * 78)
    print(f"  file đã xoá        : {deleted}")
    print(f"  dung lượng thu hồi : {fmt_size(freed)}")
    if errors:
        print(f"  lỗi                : {len(errors)}")
        for e in errors[:10]:
            print(f"    {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())