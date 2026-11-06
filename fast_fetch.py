"""Tải HTML song song bằng HTTP thuần — nhanh hơn trình duyệt, nhẹ hơn nhiều.

VÌ SAO CẦN: đo được trên rphang.show, 8 trang box:

    HTTP thuần, 8 luồng     0.56s  -> 14,2 trang/giây
    Trình duyệt, 8 song song 0.69s  -> 11,6 trang/giây

HTTP nhanh hơn và KHÔNG tốn RAM render (trình duyệt ~55 MB/tab, 20 tab là
1,7 GB). Với 1.336 trang box của hai box bạn theo dõi, HTTP 8 luồng mất
khoảng 95 giây; trình duyệt mất 115 giây và ngốn hơn 1 GB.

Trình duyệt vẫn cần cho: trang cần JS để dựng nội dung, hoặc khi Cloudflare
bật thử thách. Ở đây dùng HTTP trước, chỉ rơi về trình duyệt khi HTTP thất bại.

VỀ COOKIE: box công khai không cần đăng nhập (đã kiểm chứng: trả 200). Nhưng
nếu box riêng cần phiên, truyền cookie lấy từ phiên đang có. Hàm
`cookies_from_cdp()` lấy cookie trực tiếp từ trình duyệt đang mở — không cần
đọc file Cookies (file đó bị Chromium khoá độc quyền khi đang chạy).
"""

import asyncio
import gzip
import os
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import config

# User-Agent thật của Chrome. Không giả lập lạ — dùng đúng chuỗi trình duyệt
# bạn đang chạy là cách ít bị chặn nhất, và trung thực với server.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")


def _headers(referer=None, cookie=None, accept=None):
    h = {
        "User-Agent": USER_AGENT,
        "Accept": accept or ("text/html,application/xhtml+xml,application/xml;"
                            "q=0.9,image/avif,image/webp,*/*;q=0.8"),
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        h["Referer"] = referer
    if cookie:
        h["Cookie"] = cookie
    return h


class FetchResult:
    """Kết quả một lần tải. Giữ cả lỗi để chỗ gọi quyết định có thử lại không."""

    __slots__ = ("url", "status", "text", "content", "headers", "error", "seconds")

    def __init__(self, url):
        self.url = url
        self.status = 0
        self.text = None
        self.content = None
        self.headers = {}
        self.error = ""
        self.seconds = 0.0

    @property
    def ok(self):
        return self.status == 200 and self.error == ""

    def __repr__(self):
        if self.ok:
            n = len(self.text) if self.text is not None else len(self.content or b"")
            return f"<FetchResult ok {self.status} {n}B {self.seconds:.2f}s>"
        return f"<FetchResult FAIL {self.status} {self.error!r}>"


def fetch_one(url, referer=None, cookie=None, timeout=None, as_text=True,
              retries=None):
    """Tải MỘT url. Trả FetchResult, không ném exception.

    Dùng lại kết nối không được với urllib, nhưng chi phí TLS với Cloudflare
    nhỏ so với việc render cả trang bằng trình duyệt.
    """
    timeout = timeout or getattr(config, "HTTP_TIMEOUT", 30)
    retries = getattr(config, "HTTP_RETRIES", 2) if retries is None else retries
    res = FetchResult(url)
    last = None

    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(
                url, headers=_headers(referer, cookie))
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                enc = (r.headers.get("Content-Encoding") or "").lower()
                if enc == "gzip":
                    raw = gzip.decompress(raw)
                elif enc == "deflate":
                    try:
                        import zlib
                        raw = zlib.decompress(raw)
                    except Exception:
                        pass
                res.status = r.status
                res.headers = dict(r.headers)
                res.seconds = time.perf_counter() - t0
                if as_text:
                    cs = (r.headers.get("Content-Type") or "")
                    m = __import__("re").search(r"charset=([\w-]+)", cs)
                    enc_name = m.group(1) if m else "utf-8"
                    try:
                        res.text = raw.decode(enc_name, "replace")
                    except LookupError:
                        res.text = raw.decode("utf-8", "replace")
                else:
                    res.content = raw
                res.error = ""
                return res
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            res.status = e.code
            # 404/403 không đáng thử lại nhiều; 429 thì nên chờ.
            if e.code in (400, 401, 403, 404, 410):
                break
            if e.code == 429:
                time.sleep(min(2 ** attempt, 8) + random.random())
                continue
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as e:
            last = f"{type(e).__name__}: {e}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"

        if attempt < retries:
            time.sleep(min(0.3 * (2 ** attempt), 3) + random.random() * 0.2)

    res.error = last or "không rõ"
    return res


def fetch_many(urls, referer=None, cookie=None, workers=None, as_text=True):
    """Tải NHIỀU url song song bằng thread. Trả list FetchResult cùng thứ tự.

    Vì sao đúng thứ tự: chỗ gọi cần ghép kết quả với trang (page 1, 2, 3...).
    Dùng `executor.map` để giữ thứ tự, không phải as_completed.
    """
    workers = workers or getattr(config, "HTTP_WORKERS", 12)
    workers = max(1, min(workers, len(urls) or 1))
    if not urls:
        return []

    def one(u):
        return fetch_one(u, referer=referer, cookie=cookie, as_text=as_text)

    if workers == 1:
        return [one(u) for u in urls]

    out = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(one, urls):
            out.append(r)
    return out


async def fetch_many_async(urls, referer=None, cookie=None, workers=None,
                           as_text=True):
    """Bọc fetch_many cho code async không chặn event loop."""
    return await asyncio.to_thread(
        fetch_many, urls, referer, cookie, workers, as_text)


async def cookies_from_cdp(cdp_url=None):
    """Lấy cookie từ trình duyệt đang mở qua CDP.

    VÌ SAO QUA CDP: khi Chromium đang chạy, nó giữ khoá độc quyền trên file
    `Cookies` trong profile nên không đọc trực tiếp được (đo được: chỉ đúng
    file đó bị khoá, các file khác vẫn đọc được). CDP là đường duy nhất lấy
    được phiên đang sống mà không phải đóng trình duyệt.

    Trả chuỗi "k=v; k2=v2" để dùng cho header Cookie, hoặc "" nếu không lấy được.
    """
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return ""

    cdp_url = cdp_url or config.CDP_URL
    pairs = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            for ctx in browser.contexts:
                for c in await ctx.cookies():
                    pairs.append((c.get("name", ""), c.get("value", "")))
            # KHÔNG đóng browser: đó là trình duyệt của người dùng.
    except Exception:
        return ""

    seen = set()
    out = []
    for k, v in pairs:
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(f"{k}={v}")
    return "; ".join(out)


def cookie_for(cookie_str, host_filter=None):
    """Lọc cookie theo tên miền nếu cần. Hiện trả nguyên chuỗi.

    Giữ hàm này để chỗ gọi không phải quan tâm định dạng cookie thay đổi.
    """
    return cookie_str or ""


def same_host(url, base):
    """True nếu url cùng host với base. Dùng để giới hạn Referer đúng site."""
    try:
        return urllib.parse.urlparse(url).netloc == urllib.parse.urlparse(base).netloc
    except Exception:
        return False


# Kích thước mỗi lần đọc khi tải file. 64 KB là điểm cân bằng: đủ lớn để ít
# lần gọi syscall, đủ nhỏ để RAM không phình.
CHUNK_SIZE = 64 * 1024


class DownloadResult:
    """Kết quả tải một file về đĩa."""

    __slots__ = ("status", "bytes", "error", "seconds", "content_type")

    def __init__(self):
        self.status = 0
        self.bytes = 0
        self.error = ""
        self.seconds = 0.0
        self.content_type = ""

    @property
    def ok(self):
        return self.status == 200 and not self.error

    def __repr__(self):
        if self.ok:
            return f"<DownloadResult ok {self.bytes}B {self.seconds:.2f}s>"
        return f"<DownloadResult FAIL {self.status} {self.error!r}>"


def download_to_file(url, save_path, referer=None, cookie=None, timeout=None,
                     stop_event=None, max_bytes=None):
    """Tải một file về đĩa bằng STREAMING, không nạp cả file vào RAM.

    VÌ SAO CẦN: `context.request.get(...)` của Playwright phải `await
    response.body()` — nạp TOÀN BỘ file vào RAM trước khi ghi. Đo được trên
    dữ liệu thật của một thread: 39 ảnh + 56 video ≈ 580 MB. Với
    DOWNLOAD_SEM=10, có thể có 10 file cùng nằm trong RAM; video 10 MB × 10 =
    100 MB chỉ để chờ ghi. Đó là nguyên nhân app phình và giật khi tải.

    Streaming giữ tối đa CHUNK_SIZE (64 KB) trong RAM, tốc độ không đổi
    (đo được: 398 ms nạp cả file so với 397 ms stream 64 KB cho cùng file).

    Ghi ra `.tmp` rồi `os.replace` để không bao giờ để lại file cụt mang tên
    thật. Nếu tải dở, `.tmp` bị xoá.

    Trả DownloadResult; không ném exception.
    """
    res = DownloadResult()
    timeout = timeout or getattr(config, "HTTP_TIMEOUT", 30)
    max_bytes = max_bytes or (getattr(config, "MAX_FILE_MB", 512) * 1024 * 1024)
    tmp_path = save_path + ".tmp"
    t0 = time.perf_counter()

    try:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
    except Exception as e:
        res.error = f"không tạo được thư mục: {e}"
        return res

    written = 0
    try:
        req = urllib.request.Request(url, headers=_headers(referer, cookie))
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res.status = r.status
            res.content_type = (r.headers.get("Content-Type") or "").lower()

            # Khai báo quá lớn thì bỏ trước khi tải, đỡ tốn băng thông.
            declared = r.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                res.error = f"quá lớn: {int(declared)//1024//1024} MB"
                return res

            with open(tmp_path, "wb") as f:
                while True:
                    if stop_event is not None and stop_event.is_set():
                        res.error = "cancelled"
                        raise _Cancelled()
                    chunk = r.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        res.error = f"vượt giới hạn {max_bytes//1024//1024} MB"
                        raise _TooBig()
                    f.write(chunk)

        res.bytes = written
        res.seconds = time.perf_counter() - t0
        if written == 0:
            res.error = "file rỗng"
            _safe_remove(tmp_path)
            return res
        os.replace(tmp_path, save_path)
        return res

    except _Cancelled:
        _safe_remove(tmp_path)
        res.status = 0
        res.seconds = time.perf_counter() - t0
        return res
    except _TooBig:
        _safe_remove(tmp_path)
        res.status = 0
        res.seconds = time.perf_counter() - t0
        return res
    except urllib.error.HTTPError as e:
        _safe_remove(tmp_path)
        res.status = e.code
        res.error = f"HTTP {e.code}"
        res.seconds = time.perf_counter() - t0
        return res
    except urllib.error.URLError as e:
        _safe_remove(tmp_path)
        res.error = f"URLError: {e.reason}"
        res.seconds = time.perf_counter() - t0
        return res
    except TimeoutError:
        _safe_remove(tmp_path)
        res.error = "timeout"
        res.seconds = time.perf_counter() - t0
        return res
    except Exception as e:
        _safe_remove(tmp_path)
        res.error = f"{type(e).__name__}: {e}"
        res.seconds = time.perf_counter() - t0
        return res


class _Cancelled(Exception):
    pass


class _TooBig(Exception):
    pass


def _safe_remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def download_many(items, referer=None, cookie=None, workers=None,
                  stop_event=None, on_done=None):
    """Tải nhiều file song song. items = [(url, save_path)] .

    Trả list DownloadResult cùng thứ tự với items. `on_done(url, path, result)`
    được gọi sau mỗi file để chỗ gọi ghi cache ngay, không phải chờ hết.
    """
    workers = workers or getattr(config, "DOWNLOAD_SEM", 10)
    workers = max(1, min(workers, len(items) or 1))
    if not items:
        return []

    def one(item):
        url, save_path = item
        r = download_to_file(url, save_path, referer=referer, cookie=cookie,
                             stop_event=stop_event)
        if on_done:
            try:
                on_done(url, save_path, r)
            except Exception:
                pass
        return r

    if workers == 1:
        return [one(it) for it in items]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, items))