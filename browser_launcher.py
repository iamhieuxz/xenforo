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
import socket
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

# Giữ tham chiếu tới tiến trình đã mở. Bản cũ gọi Popen(...) rồi bỏ ngay đối
# tượng: không thể terminate() khi app thoát, và không phân biệt được cổng
# đang do CHÍNH tiến trình này giữ hay của người khác.
_launched_process = None


def find_browser_for(browser=None):
    """Đường dẫn exe của MỘT trình duyệt cụ thể ("chrome"|"coccoc"|"edge").

    Khác find_browser(): hàm kia trả ứng viên đầu tiên có trên máy, bất kể loại.
    Mode persistent cần đúng loại vì profile gắn với từng trình duyệt — đưa
    profile Chrome cho Cốc Cốc sẽ hỏng dữ liệu.
    """
    browser = (browser or "chrome").lower()
    patterns = {
        "coccoc": ("coccoc", "browser.exe"),
        "chrome": ("chrome", "chrome.exe"),
        "edge": ("edge", "msedge.exe"),
    }
    keys = patterns.get(browser, (browser,))
    for path in EXE_CANDIDATES:
        low = path.lower()
        if all(k.lower() in low for k in keys):
            if os.path.isfile(path):
                return path
    # Dự phòng: COCOC_PATH / V72_BROWSER_PATH nếu khớp loại
    env_path = os.environ.get("COCOC_PATH") or os.environ.get("V72_BROWSER_PATH")
    if env_path and os.path.isfile(env_path) and keys[-1].lower() in env_path.lower():
        return env_path
    return None


def find_browser(explicit=None):
    """Đường dẫn exe trình duyệt, hoặc None.

    Thứ tự: tham số truyền vào -> biến môi trường -> danh sách mặc định.
    COCOC_PATH trước đây chỉ được NHẮC trong thông báo lỗi mà không hề được đọc,
    nên ai làm theo hướng dẫn đều không có tác dụng.
    """
    env_path = os.environ.get("COCOC_PATH") or os.environ.get("V72_BROWSER_PATH")
    for path in ([explicit] if explicit else []) + ([env_path] if env_path else []) \
            + list(EXE_CANDIDATES):
        if path and os.path.isfile(path):
            return path
    return None


def profile_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "V72Crawler", config.BROWSER_PROFILE)


def _cdp_base():
    """Gốc URL của cổng CDP, luôn dùng IPv4 literal.

    Không dùng "localhost": trên Windows nó resolve ra ::1 trước, mà Chromium
    chỉ bind IPv4 -> request bị refuse dù trình duyệt đang chạy.
    """
    return f"http://{getattr(config, 'CDP_HOST', '127.0.0.1')}:{config.CDP_PORT}"


def _port_connectable(host=None, port=None, timeout=1.0):
    """True nếu TCP tới cổng mở được. Phân biệt "không có gì lắng nghe" với
    "có thứ gì đó lắng nghe nhưng không nói tiếng CDP"."""
    host = host or getattr(config, "CDP_HOST", "127.0.0.1")
    port = port or config.CDP_PORT
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def read_cdp_version(timeout=1.5):
    """Đọc /json/version và trả dict, hoặc None nếu không đọc được."""
    try:
        with urllib.request.urlopen(f"{_cdp_base()}/json/version", timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def probe_port(timeout=1.5):
    """Chẩn đoán cổng CDP. Trả dict trạng thái thay vì chỉ True/False.

    Bản cũ chỉ thử HTTP 200. Hệ quả đo được: một server bất kỳ chiếm cổng 9222
    (hoặc phần mềm khác, hoặc tiến trình Chrome cũ của profile khác) đều làm
    is_port_open() trả True; launch() liền bỏ qua việc mở trình duyệt và trả
    "đã có sẵn", rồi connect_over_cdp thất bại — người dùng chỉ thấy một dòng
    lỗi chung chung, không biết cổng đang bị ai chiếm.

    PHẢI kiểm TCP trước: nếu chỉ thử đọc /json/version thì một server trả HTML
    (không phải JSON) sẽ khiến hàm này báo "closed", và launch() sẽ cố mở thêm
    một trình duyệt lên đúng cổng đã bị chiếm.

    Trả về:
      {"state": "closed"|"not_chromium"|"ready", "detail": str, "version": dict|None}
    """
    info = read_cdp_version(timeout=timeout)

    if info is None:
        if _port_connectable(timeout=min(timeout, 1.0)):
            return {"state": "not_chromium",
                    "detail": "Cổng đang mở nhưng không trả dữ liệu CDP hợp lệ.",
                    "version": None}
        return {"state": "closed", "detail": "Cổng chưa mở.", "version": None}

    # Chromium luôn có ít nhất một trong hai field này. Server lạ thì không.
    browser = str(info.get("Browser") or "")
    ws = str(info.get("webSocketDebuggerUrl") or "")
    if not browser and not ws:
        return {"state": "not_chromium",
                "detail": "Cổng đang bị tiến trình khác chiếm (không phải Chromium).",
                "version": info}

    return {"state": "ready", "detail": f"{browser}", "version": info}


def is_port_open(timeout=1.0):
    """True chỉ khi cổng có CHROMIUM THẬT, không phải server bất kỳ.

    Giữ tên hàm cũ để không phá vỡ chỗ gọi, nhưng ngữ nghĩa đã chặt hơn.
    """
    return probe_port(timeout).get("state") == "ready"


def _is_our_profile(info):
    """True/False/None: cổng có thuộc profile của app không.

    Không xác định được thì trả None (không coi là sai). Chrome không công bố
    đường dẫn profile qua /json/version, nên cách duy nhất là so số PID của
    tiến trình đang giữ cổng với tiến trình ta đã mở.
    """
    pid = _listening_pid(config.CDP_PORT)
    if pid is None:
        return None
    ref = _launched_process
    if ref is None or ref.poll() is not None:
        return None
    return pid == ref.pid


def _listening_pid(port):
    """PID đang LISTEN trên `port`, hoặc None. Chỉ Windows, dùng netstat."""
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    needle = f":{port} "
    for line in out.splitlines():
        if needle not in line:
            continue
        if "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if len(parts) >= 5 and parts[-1].isdigit():
            return int(parts[-1])
    return None


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


def launch(exe=None, wait_seconds=25.0, on_progress=None):
    """Mở trình duyệt ở cổng debug. Trả (thành công, thông báo).

    Khác bản cũ ở ba điểm quan trọng:
    1. Không tin `is_port_open()` đơn thuần. Nếu cổng bị tiến trình KHÁC chiếm,
       báo rõ "bị chiếm" thay vì im lặng trả "đã có sẵn" rồi để
       connect_over_cdp thất bại với thông báo chung chung.
    2. Nếu cổng đã có Chromium thật nhưng KHÔNG phải profile của app, vẫn dùng
       được (người dùng có thể tự mở) nhưng phải nói rõ để họ hiểu vì sao
       cookie/phiên đăng nhập có thể khác.
    3. Lưu Popen object để shutdown() dọn được, và để _is_our_profile() so PID.
    """
    global _launched_process

    state = probe_port()
    if state["state"] == "ready":
        ours = _is_our_profile(state["version"])
        if ours is False:
            return True, (f"Cổng {config.CDP_PORT} đang do một tiến trình KHÁC giữ "
                          f"({state['detail']}). Vẫn dùng được, nhưng profile có thể "
                          f"không phải của app — cookie/phiên đăng nhập có thể khác.")
        return True, f"Cổng {config.CDP_PORT} đã sẵn sàng ({state['detail']})."

    if state["state"] == "not_chromium":
        pid = _listening_pid(config.CDP_PORT)
        who = f" (PID {pid})" if pid else ""
        return False, (f"Cổng {config.CDP_PORT} đang bị tiến trình khác chiếm{who}, "
                       f"không phải Chromium. Tắt tiến trình đó hoặc đổi CDP_PORT "
                       f"trong config.py.")

    exe = find_browser(exe)
    if not exe:
        return False, ("Không tìm thấy trình duyệt. Đặt COCOC_PATH trỏ tới browser.exe "
                       "hoặc sửa _BROWSER_CANDIDATES trong browser_launcher.py.")

    pdir = profile_dir()
    os.makedirs(pdir, exist_ok=True)

    try:
        # Không chặn: subprocess bị giữ khi ta đợi cổng thì GUI sẽ treo.
        _launched_process = subprocess.Popen(
            build_args(exe, pdir),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        _launched_process = None
        return False, f"Không mở được trình duyệt: {e}"

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        # Tiến trình thoát ngay = sai đường dẫn hoặc bị chặn; không cần chờ hết.
        if _launched_process.poll() is not None:
            return False, (f"{os.path.basename(exe)} thoát ngay sau khi mở "
                           f"(mã {_launched_process.returncode}). Kiểm tra lại đường dẫn "
                           f"hoặc chạy tay để xem thông báo.")
        st = probe_port(timeout=0.5)
        if st["state"] == "ready":
            return True, f"Đã mở {browser_version(exe)} trên cổng {config.CDP_PORT}."
        if st["state"] == "not_chromium":
            return False, (f"Cổng {config.CDP_PORT} bị tiến trình khác chiếm ngay sau khi "
                           f"mở {os.path.basename(exe)}.")
        if on_progress:
            try:
                on_progress(deadline - time.time())
            except Exception:
                pass
        time.sleep(0.3)

    return False, (f"{os.path.basename(exe)} không mở cổng {config.CDP_PORT} sau "
                   f"{wait_seconds:.0f}s. Thử: tắt hết cửa sổ {os.path.basename(exe)} "
                   f"cũ rồi mở lại app.")


def shutdown(terminate=True):
    """Đóng tiến trình trình duyệt do app mở. Gọi khi app thoát.

    Bản cũ không giữ Popen nên không dọn được gì: mỗi lần chạy app lại để lại
    một cửa sổ trình duyệt mồ côi với profile riêng.

    Chỉ terminate tiến trình do CHÍNH app mở — không đụng trình duyệt người dùng
    tự mở, vì có thể họ đang dùng cho việc khác.
    """
    global _launched_process
    proc = _launched_process
    _launched_process = None
    if proc is None or proc.poll() is not None:
        return False
    if not terminate:
        return False
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        return True
    except Exception:
        return False


def tab_count():
    """Số tab đang mở, để log khi chẩn đoán."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{config.CDP_PORT}/json", timeout=1.5) as r:
            return len(json.load(r))
    except Exception:
        return -1