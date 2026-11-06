"""Ghi nhật ký phiên chạy ra FILE để debug về sau.

VÌ SAO CẦN: bản trước chỉ giữ log trong RAM (`log_history`), mất khi đóng app.
Khi người dùng báo "có 7 lỗi" thì không còn gì để đọc lại — mọi chẩn đoán đều
phải đoán. Module này khắc phục đúng điểm đó.

Thiết kế có chủ đích:

1. MỘT FILE MỖI PHIÊN, tên có timestamp: `session-20261106-143812.log`.
   Không ghi chung một file: lịch sử dài vài MB thì tìm lỗi một phiên là cực.

2. GHI NGAY, không đệm. `flush()` sau mỗi dòng: app bị kill giữa chừng vẫn còn
   log tới dòng cuối. Đây là điểm quan trọng nhất khi debug crash.

3. ĐỊNH DẠNG ĐỌC ĐƯỢC BẰNG MÁY: mỗi dòng có mức (INFO/WARN/ERROR), thời gian,
   tag. Nhờ vậy script khác lọc được lỗi mà không cần đọc bằng mắt.

4. TỰ XOAY VÒNG: giữ N phiên gần nhất, xoá cũ. Không để log ăn hết ổ.

5. GHI CẢ LỖI CHƯA BẮT ĐƯỢC (exception) kèm traceback. Bản trước chỉ in ra
   stderr, mà chạy bằng .bat thì cửa sổ đóng là mất.

6. KHÔNG BAO GIỜ NÉM EXCEPTION. Ghi log hỏng (ổ đầy, quyền) không được làm chết
   app — log là công cụ, không phải tính năng chính.
"""

import os
import re
import sys
import threading
import time
import traceback
from datetime import datetime

import config


# Mức log, dùng để lọc. Đặt số để so sánh được.
LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "ERROR": 40,
}

# Tag của giao diện -> mức log trong file.
TAG_TO_LEVEL = {
    "error": "ERROR",
    "summary": "WARN",
    "success": "INFO",
    "info": "INFO",
    "system": "INFO",
    "bulk": "INFO",
    "skip": "DEBUG",
    "dim": "DEBUG",
}


def _looks_like_warn(msg):
    if not msg:
        return False
    if msg.lstrip().startswith("[!]"):
        return True
    low = msg.lower()
    for needle in ("cảnh báo", "canh bao", "bỏ qua", "bo qua",
                   "thiếu", "thieu", "trùng", "trung"):
        if needle in low:
            return True
    return False


def _looks_like_error(msg):
    """Nhận diện dòng log là lỗi, dựa trên dấu hiệu trong chính câu log.

    Vì sao cần: engine gọi `log("[-] Lỗi ...")` mà không truyền tag. Nếu chỉ
    dựa vào tag thì những lỗi đó bị ghi ở mức INFO và bị bộ lọc bỏ qua — đúng
    loại lỗi người dùng cần thấy nhất.

    THỨ TỰ QUAN TRỌNG: phải kiểm dấu hiệu cảnh báo TRƯỚC. Đo được: dòng
    "[!] Không tải được trang 3" khớp cả "không tải" (lỗi) và "[!]" (cảnh báo);
    nếu kiểm lỗi trước thì nó bị xếp ERROR, làm số lỗi trong báo cáo sai.
    """
    if not msg:
        return False
    if _looks_like_warn(msg):
        return False
    low = msg.lower()
    if msg.lstrip().startswith("[-]"):
        return True
    for needle in ("lỗi", "loi ", "that bai", "thất bại", "timeout",
                   "traceback", "exception", "cannot ", "failed",
                   "không tải", "khong tai", "bị chặn", "bi chan"):
        if needle in low:
            return True
    return False


class SessionLog:
    """Ghi log một phiên ra file. Thread-safe, không ném exception."""

    def __init__(self, log_dir=None, prefix="session", keep=30,
                 min_level="DEBUG"):
        self.log_dir = log_dir or config.LOG_DIR
        self.prefix = prefix
        self.keep = keep
        self.min_level = LEVELS.get(min_level.upper(), 10)
        self.path = ""
        self._fh = None
        self._lock = threading.Lock()
        self._error_count = 0
        self._warn_count = 0
        self._line_count = 0
        self._started = datetime.now()

        try:
            os.makedirs(self.log_dir, exist_ok=True)
            stamp = self._started.strftime("%Y%m%d-%H%M%S")
            self.path = os.path.join(self.log_dir, f"{prefix}-{stamp}.log")
            self._fh = open(self.path, "a", encoding="utf-8", buffering=1)
            self._write_header()
            self._rotate()
        except Exception:
            # Không ghi được log thì vẫn chạy app. Đây là quyết định có chủ ý:
            # log là công cụ phụ, mất nó không được làm mất chức năng chính.
            self._fh = None
            self.path = ""

    # ---------- ghi ----------

    def _write_header(self):
        try:
            self._fh.write("#" * 72 + "\n")
            self._fh.write(f"# XenForo Crawler — phiên {self._started:%Y-%m-%d %H:%M:%S}\n")
            self._fh.write(f"# Python {sys.version.split()[0]} | "
                           f"{sys.platform}\n")
            try:
                self._fh.write(f"# Thư mục tải: {config.DOWNLOAD_DIR}\n")
                self._fh.write(f"# Trình duyệt : {config.CDP_BROWSER} | "
                               f"mode={config.BROWSER_MODE} | "
                               f"cổng={config.CDP_PORT}\n")
                self._fh.write(f"# HTTP-first  : {config.USE_HTTP_FIRST} | "
                               f"workers={config.HTTP_WORKERS} | "
                               f"stop_on_known={config.STOP_ON_KNOWN_THREAD}\n")
            except Exception:
                pass
            self._fh.write("#" * 72 + "\n")
            self._fh.flush()
        except Exception:
            pass

    def _rotate(self):
        """Giữ `keep` file gần nhất, xoá cũ hơn."""
        if self.keep <= 0:
            return
        try:
            files = sorted(
                (os.path.join(self.log_dir, f)
                 for f in os.listdir(self.log_dir)
                 if f.startswith(self.prefix + "-") and f.endswith(".log")),
                key=os.path.getmtime, reverse=True)
            for old in files[self.keep:]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception:
            pass

    def write(self, message, tag=None, level=None):
        """Ghi một dòng. Không ném exception, không chặn lâu."""
        if self._fh is None:
            return
        if level is None:
            level = TAG_TO_LEVEL.get(tag or "", None)
        if level is None:
            if _looks_like_error(message):
                level = "ERROR"
            elif _looks_like_warn(message):
                level = "WARN"
            else:
                level = "INFO"

        if LEVELS.get(level, 20) < self.min_level:
            return

        # Bỏ ký tự điều khiển để file log không bị hỏng khi mở bằng editor.
        clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(message))
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        with self._lock:
            try:
                self._fh.write(f"{stamp} {level:5} [{tag or '-':8}] {clean}\n")
                self._fh.flush()
                self._line_count += 1
                if level == "ERROR":
                    self._error_count += 1
                elif level == "WARN":
                    self._warn_count += 1
            except Exception:
                pass

    def exception(self, where, exc):
        """Ghi exception kèm traceback. Dùng trong `except`."""
        try:
            tb = "".join(traceback.format_exception(
                type(exc), exc, exc.__traceback__))
        except Exception:
            tb = f"{type(exc).__name__}: {exc}"
        with self._lock:
            try:
                stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                self._fh.write(f"{stamp} ERROR [{where[:8]:8}] "
                               f"ngoại lệ: {type(exc).__name__}: {exc}\n")
                for line in tb.rstrip().splitlines():
                    self._fh.write(f"            | {line}\n")
                self._fh.flush()
                self._error_count += 1
            except Exception:
                pass

    def close(self, summary=None):
        if self._fh is None:
            return
        with self._lock:
            try:
                elapsed = (datetime.now() - self._started).total_seconds()
                self._fh.write("=" * 72 + "\n")
                self._fh.write(f"# Kết thúc sau {elapsed:.1f}s | "
                               f"{self._line_count} dòng | "
                               f"{self._error_count} lỗi | "
                               f"{self._warn_count} cảnh báo\n")
                if summary:
                    self._fh.write(f"# {summary}\n")
                self._fh.write("=" * 72 + "\n")
                self._fh.flush()
                self._fh.close()
            except Exception:
                pass
            self._fh = None

    # ---------- thông tin ----------

    @property
    def error_count(self):
        return self._error_count

    @property
    def warn_count(self):
        return self._warn_count

    def __bool__(self):
        return self._fh is not None


# ---------- tiện ích đọc log ----------

_ERROR_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3} (ERROR|WARN)\s+\[([^\]]*)\]\s*(.*)$")


def read_errors(path, level="WARN"):
    """Đọc file log, trả các dòng mức >= `level`.

    Trả [(time, level, tag, message)]. Dùng để rà lỗi một phiên mà không phải
    mở file bằng mắt.
    """
    want = LEVELS.get(level.upper(), 30)
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _ERROR_RE.match(line.rstrip("\n"))
                if not m:
                    continue
                lv, tag, msg = m.groups()
                if LEVELS.get(lv, 0) >= want:
                    out.append((line[:12], lv, tag.strip(), msg))
    except Exception:
        pass
    return out


def summarize(path):
    """Tóm tắt một file log: số dòng, số lỗi, lỗi hay gặp nhất."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return {"ok": False}

    from collections import Counter
    errs = Counter()
    warns = 0
    n_err = 0
    for line in lines:
        m = _ERROR_RE.match(line.rstrip("\n"))
        if not m:
            continue
        lv, tag, msg = m.groups()
        if lv == "ERROR":
            n_err += 1
            # Nhóm theo dấu hiệu đầu tiên để gộp lỗi giống nhau.
            key = msg[:60]
            errs[key] += 1
        else:
            warns += 1

    return {
        "ok": True,
        "path": path,
        "lines": len(lines),
        "errors": n_err,
        "warns": warns,
        "top_errors": errs.most_common(10),
    }