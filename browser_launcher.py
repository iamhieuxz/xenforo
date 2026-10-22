"""Tự mở trình duyệt ở cổng CDP 9222.

Đã test với Cốc Cốc 152 (Chrome/152.0.7977.124):
- Tên exe là browser.exe, KHÔNG phải coccoc.exe.
- Shortcut browser.lnk trong project (Cốc Cốc + --remote-debugging-port=9222,
  KHÔNG có --user-data-dir) chạy được, nhưng khi Cốc Cốc đang chạy thì browser
  bỏ qua cờ debug và chỉ mở tab: vẫn là instance cũ, cổng 9222 không đổi.
  Vì vậy app TỰ MỞ bằng lệnh (kèm --user-data-dir tách profile) và không dùng
  shortcut làm nguồn chính; shortcut vẫn chạy được để bạn mở tay khi cần.
- Chrome >= 136 từ chối cổng debug không phải cổng mặc định của chính profile
  đó, nên --user-data-dir riêng là điều kiện sống còn, không phải tuỳ chọn.
"""

import json
import os
import subprocess
import time
import urllib.request

import config

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SHORTCUT_PATH = os.path.join(PROJECT_DIR, "browser.lnk")

# browser.lnk trỏ tới Cốc Cốc, đúng ứng viên đầu tiên. Không cần parse .lnk:
# đọc shortcut chỉ để lấy đường dẫn exe mà ta đã có sẵn trong danh sách dưới.
# Thứ tự ưu tiên: Cốc Cốc -> Chrome -> Edge.
_BROWSER_CANDIDATES = (
    r"C:\Program Files\CocCoc\Browser\Application\browser.exe",
    r"C:\Program Files (x86)\CocCoc\Browser\Application\browser.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), r"CocCoc\Browser\Application\browser.exe"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

# Cốc Cốc có cảnh báo khởi động lần đầu, có thể chặn cổng debug cho tới khi bấm.
_FIRST_RUN_TAGS = ("--no-first-run", "--no-default-browser-check")

EXE_CANDIDATES = tuple(p for p in _BROWSER_CANDIDATES if p)


def find_browser(explicit=None):
    """Đường dẫn exe trình duyệt, hoặc None."""
    for path in ([explicit] if explicit else []) + list(EXE_CANDIDATES):
        if path and os.path.isfile(path):
            return path
    return None


def profile_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "V72Crawler", config.BROWSER_PROFILE)


def is_port_open(timeout=1.0):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{config.CDP_PORT}/json/version", timeout=timeout):
            return True
    except Exception:
        return False


def browser_version(exe):
    """Tên + phiên bản để log, không bắt buộc phải đúng."""
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
        return (out.stdout or out.stderr).strip()
    except Exception:
        return os.path.basename(exe)


def build_args(exe, pdir=None):
    """Danh sách tham số mở cổng debug. Tách riêng để test không cần bật Chrome thật."""
    return [exe,
            f"--remote-debugging-port={config.CDP_PORT}",
            f"--user-data-dir={pdir or profile_dir()}",
            *_FIRST_RUN_TAGS]


def launch(exe=None, wait_seconds=25.0):
    """Mở trình duyệt ở cổng debug. Trả (thành công, thông báo lỗi)."""
    if is_port_open():
        return True, f"Cổng {config.CDP_PORT} đã có sẵn, không cần mở trình duyệt."

    exe = find_browser(exe)
    if not exe:
        return False, ("Không tìm thấy trình duyệt. Đặt COCOC_PATH trỏ tới browser.exe "
                       "hoặc sửa _BROWSER_CANDIDATES trong browser_launcher.py.")

    pdir = profile_dir()
    os.makedirs(pdir, exist_ok=True)

    try:
        # Không chặn: subprocess bị giữ khi ta đẹi cổng, app Tk sẽ treo.
        subprocess.Popen(build_args(exe, pdir),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return False, f"Không mở được trình duyệt: {e}"

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if is_port_open(timeout=0.5):
            return True, f"Đã mở {browser_version(exe)} trên cổng {config.CDP_PORT}."
        time.sleep(0.3)

    return False, (f"{os.path.basename(exe)} không mở cổng {config.CDP_PORT} sau "
                   f"{wait_seconds:.0f}s. Thử: tắt hết cửa sổ {os.path.basename(exe)} cũ rồi mở lại app.")


def tab_count():
    """Số tab đang mở, để log khi chẩn đoán."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{config.CDP_PORT}/json", timeout=1.5) as r:
            return len(json.load(r))
    except Exception:
        return -1