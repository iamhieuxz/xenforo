"""Nguồn profile trình duyệt cho mode persistent.

Hai việc, tách khỏi engine để test được không cần Playwright:

1. Dò xem máy có những trình duyệt nào và profile của chúng ở đâu.
2. Kiểm tra profile có đang bị tiến trình khác giữ không, trước khi mở.

VÌ SAO CẦN KIỂM TRA "ĐANG CHẠY": Chromium giữ khoá độc quyền trên file
`Cookies` trong profile. Đo được trên máy thật khi Cốc Cốc đang chạy:

    Network/Cookies          BI KHOÁ   <- độc quyền
    Preferences              đọc được
    History                  đọc được
    Web Data                 đọc được

Chỉ đúng file Cookies bị khoá, nên đây không phải vấn đề quyền của tiến trình
gọi — không có quyền nào vượt được. Hệ quả: muốn dùng profile của một trình
duyệt đang chạy thì phải đóng nó trước. Không đóng được thì phải copy profile
sang nơi khác, mà copy cũng thất bại đúng ở file Cookies.
"""

import os
import shutil
import subprocess
import sys

import config


# Đường dẫn profile mặc định của từng trình duyệt, theo thứ tự ưu tiên.
_PROFILE_DIRS = {
    "coccoc": [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"CocCoc\Browser\User Data"),
    ],
    "chrome": [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\User Data"),
    ],
    "edge": [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Edge\User Data"),
    ],
}

# Tên tiến trình để kiểm tra "đang chạy".
_PROCESS_NAMES = {
    "coccoc": "browser.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
}

# File mà Chromium khoá độc quyền khi đang chạy. Dùng để chẩn đoán.
LOCKED_DB = ("Default", "Network", "Cookies")


def default_session_profile(browser=None):
    """Thư mục profile riêng của app cho mode persistent.

    CỐ ĐỊNH theo tên trình duyệt — đây là điều làm session sống qua các lần chạy.
    Nếu hàm này trả về một thư mục mới mỗi lần gọi thì đăng nhập sẽ mất sau mỗi
    phiên. Đã kiểm chứng: profile cố định giữ cookie qua 3 lần mở/đóng.
    """
    browser = (browser or config.SESSION_BROWSER or "chrome").lower()
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "V72Crawler", f"session_{browser}")


def resolve_profile(browser=None):
    """Profile sẽ dùng: ưu tiên config.SESSION_PROFILE nếu có, không thì mặc định."""
    explicit = (config.SESSION_PROFILE or "").strip()
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    return default_session_profile(browser)


def find_installed_profiles():
    """Dò profile mặc định của các trình duyệt có trên máy.

    Trả {tên: {"path": ..., "exists": bool, "has_cookies": bool}}
    """
    found = {}
    for name, dirs in _PROFILE_DIRS.items():
        for d in dirs:
            if not d:
                continue
            if os.path.isdir(d):
                cookies = os.path.join(d, *LOCKED_DB)
                found[name] = {
                    "path": d,
                    "exists": True,
                    "has_cookies": os.path.isfile(cookies),
                    "cookies_bytes": (os.path.getsize(cookies)
                                      if os.path.isfile(cookies) else 0),
                }
                break
    return found


def is_browser_running(browser=None):
    """True nếu tiến trình của trình duyệt đó đang chạy.

    Dùng tasklist trên Windows. Không dùng cách "thử khoá file" vì khoá do
    Chromium giữ là độc quyền, thử mở sẽ chỉ cho biết "không mở được" — không
    phân biệt được với lỗi quyền.
    """
    browser = (browser or config.SESSION_BROWSER or "chrome").lower()
    proc = _PROCESS_NAMES.get(browser)
    if not proc:
        return False
    if sys.platform != "win32":
        try:
            out = subprocess.run(["pgrep", "-f", proc],
                                 capture_output=True, text=True, timeout=5).stdout
            return bool(out.strip())
        except Exception:
            return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {proc}", "/FO", "CSV"],
                             capture_output=True, text=True, timeout=8).stdout
    except Exception:
        return False
    # tasklist in dòng tiêu đề + "INFO: No tasks..." khi không có gì.
    for line in out.splitlines():
        if proc.lower() in line.lower():
            return True
    return False


def profile_is_writable(path):
    """True nếu ghi được vào thư mục profile.

    Cần kiểm trước khi mở: nếu không ghi được, Chromium không tạo được
    ProcessSingleton và thoát với "Failed to create a ProcessSingleton" —
    thông báo đó không nói được nguyên nhân thật là thiếu quyền ghi.
    """
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, f".w_{os.getpid()}.tmp")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("1")
        os.remove(probe)
        return True
    except Exception:
        return False


def cookie_db_path(profile_dir):
    """Đường dẫn file Cookies trong một profile, hoặc None."""
    p = os.path.join(profile_dir, *LOCKED_DB)
    return p if os.path.isfile(p) else None


def read_cookie_summary(profile_dir, hosts_filter=None):
    """Đọc tóm tắt cookie từ profile KHÔNG bị khoá.

    Trả {"ok": bool, "total": int, "hosts": [str], "reason": str}.
    Chỉ đọc được khi trình duyệt đang đóng — xem docstring đầu module.
    Dùng để trả lời "profile này đã đăng nhập chưa" mà không cần mở trình duyệt.
    """
    import sqlite3
    db = cookie_db_path(profile_dir)
    if not db:
        return {"ok": False, "total": 0, "hosts": [], "reason": "không có file Cookies"}
    try:
        uri = "file:" + db.replace("\\", "/") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2)
        try:
            total = conn.execute("SELECT COUNT(*) FROM cookies").fetchone()[0]
            hosts = [r[0] for r in conn.execute(
                "SELECT DISTINCT host_key FROM cookies ORDER BY host_key").fetchall()]
        finally:
            conn.close()
        if hosts_filter:
            hosts = [h for h in hosts if any(f.lower() in h.lower() for f in hosts_filter)]
        return {"ok": True, "total": total, "hosts": hosts, "reason": ""}
    except Exception as e:
        return {"ok": False, "total": 0, "hosts": [],
                "reason": f"{type(e).__name__}: {e}"}


def copy_profile(src, dst, overwrite=False):
    """Copy profile, BỎ QUA cache (không cần cho đăng nhập, vài GB).

    Trả {"ok": bool, "copied": int, "skipped": [str], "reason": str}.

    Cảnh báo: nếu trình duyệt đang chạy, file `Cookies` bị khoá độc quyền nên
    copy sẽ thất bại đúng ở file đó — nghĩa là bản copy KHÔNG có session. Hàm
    này trả về danh sách `skipped` để chỗ gọi biết và báo cho người dùng, thay
    vì im lặng tạo ra một profile trông như thật nhưng trống.
    """
    if not os.path.isdir(src):
        return {"ok": False, "copied": 0, "skipped": [], "reason": f"không thấy {src}"}
    if os.path.exists(dst) and not overwrite:
        return {"ok": False, "copied": 0, "skipped": [],
                "reason": f"{dst} đã tồn tại (dùng overwrite=True để ghi đè)"}

    ignore = shutil.ignore_patterns(
        "Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache",
        "DawnWebGPUCache", "Service Worker", "ShaderCache", "*.log", "Crashpad",
    )

    copied = 0
    skipped = []
    try:
        os.makedirs(dst, exist_ok=True)
        for root, dirs, files in os.walk(src):
            rel = os.path.relpath(root, src)
            target_dir = dst if rel == "." else os.path.join(dst, rel)
            # Bỏ qua thư mục cache ngay ở cấp thư mục
            dirs[:] = [d for d in dirs
                       if d not in ("Cache", "Code Cache", "GPUCache", "DawnCache",
                                    "DawnGraphiteCache", "DawnWebGPUCache",
                                    "Service Worker", "ShaderCache", "Crashpad")]
            os.makedirs(target_dir, exist_ok=True)
            for name in files:
                if name.endswith(".log"):
                    continue
                s = os.path.join(root, name)
                d = os.path.join(target_dir, name)
                try:
                    shutil.copy2(s, d)
                    copied += 1
                except Exception:
                    # Thường là Cookies / LOCK khi trình duyệt đang chạy.
                    skipped.append(os.path.relpath(s, src))
    except Exception as e:
        return {"ok": False, "copied": copied, "skipped": skipped,
                "reason": f"{type(e).__name__}: {e}"}

    return {"ok": True, "copied": copied, "skipped": skipped, "reason": ""}


def describe(browser=None):
    """Một dòng trạng thái để log: trình duyệt nào, profile nào, đang chạy không."""
    browser = (browser or config.SESSION_BROWSER or "chrome").lower()
    prof = resolve_profile(browser)
    running = is_browser_running(browser)
    installed = find_installed_profiles().get(browser)
    if installed:
        where = installed["path"]
        ck = f"{installed['cookies_bytes']}B cookie" if installed["has_cookies"] else "chưa có cookie"
    else:
        where = "không tìm thấy profile mặc định"
        ck = ""
    return (f"{browser}: profile dùng = {prof} | "
            f"đang chạy = {running} | mặc định: {where} {ck}")
