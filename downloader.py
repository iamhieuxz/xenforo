"""Tải file + lập kế hoạch tải.

Tách khỏi GUI: chỉ cần logger (hàm) và stop_event (threading.Event).
"""

import asyncio
import hashlib
import os
import shutil

import aiofiles

import config
import xf_selectors as S
from xenforo_parse import clean_name, ext_for, get_url_filename


# Sentinel "hết thời gian chờ". Dùng object riêng thay vì None để phân biệt với
# "người dùng bấm Dừng" — hai tình huống có ý nghĩa thống kê hoàn toàn khác nhau.
class _Timeout:
    __slots__ = ()

    def __repr__(self):
        return "<download timeout>"


_TIMEOUT = _Timeout()


def url_hash(url):
    return hashlib.md5(url.split('?')[0].split('#')[0].encode('utf-8')).hexdigest()


def count_files(stats):
    """Ghép số đếm thành câu tiếng Việt: '8 ảnh và 2 video'.

    Bỏ qua loại có số 0 để không in '0 ảnh', và luôn có 'tệp' làm chốt chặn.
    """
    parts = []
    for key, noun in (("image", "ảnh"), ("video", "video"), ("file", "tệp")):
        n = stats.get(key, 0)
        if n:
            parts.append(f"{n} {noun}")
    if not parts:
        return "0 tệp"
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " và " + parts[-1]


def plan_jobs(urls, folder, ts, tag, seq_start=1):
    """Dựng danh sách (url, save_path, hash, kind) cho từng media, đặt tên theo tag.

    kind: 'image' | 'video' | 'file' — engine cần nó để báo "8 ảnh + 2 video"
    thay vì đếm chung một con số.
    """
    jobs = []
    kind = 'image' if tag == 'image' else ('video' if tag.endswith('video') else 'file')
    for i, url in enumerate(urls, seq_start):
        h = url_hash(url)
        if kind == 'image':
            base = get_url_filename(url) or 'image'
            ext = ext_for(url, S.IMAGE_EXT, '.jpg')
            stem = base.rsplit('.', 1)[0] if '.' in base else base
            name = f"{clean_name(stem)}_{h[:6]}{ext}"
            filename = f"[{ts}]_media_{i:03d}_{name}"
        else:
            ext = ext_for(url,
                          S.VIDEO_EXT if kind == 'video' else S.FILE_EXT,
                          '.mp4' if kind == 'video' else '.bin')
            # h[:6] là BẮT BUỘC: `i` reset về 1 ở mỗi post, nên hai post cùng
            # timestamp (hoặc cùng fallback "00000000_000000" khi thiếu thẻ
            # <time.u-dt>) sinh ra cùng tên và đè nhau -> mất media.
            filename = f"[{ts}]_{tag}_{i:03d}_{h[:6]}{ext}"
        jobs.append((url, os.path.join(folder, filename), h, kind))
    return jobs


class Downloader:
    # Báo tiến độ mỗi N tệp. Thread chỉ vài chục tệp nên N=5 là đủ thấy nhịp
    # mà không làm log dày.
    PROGRESS_EVERY = 5

    def __init__(self, cache, log, stop_event, semaphore, db_lock):
        self.cache = cache
        self.log = log
        self.stop_event = stop_event
        self.semaphore = semaphore
        self.db_lock = db_lock
        self.active_tasks = set()

    def clone_cached(self, src, dst):
        """Tái sử dụng file đã tải: hardlink = 0 byte I/O. Copy nếu FS không hỗ trợ."""
        if os.path.exists(dst):
            return True
        try:
            try:
                os.link(src, dst)
            except (OSError, AttributeError, NotImplementedError):
                shutil.copy2(src, dst)
            return True
        except Exception:
            return False

    async def dispatch(self, context, jobs, referer_url, seen_hashes):
        """Tạo task cho các job chưa có. seen_hashes: hash -> path ĐÃ TẢI XONG trong thread.

        Trùng hash trong cùng thread thì clone từ bản đầu, không tải lại.
        Chỉ ghi seen_hashes khi tải THÀNH CÔNG: bản cũ ghi path trước khi tải,
        nên một URL xuất hiện ở hai post mà lần đầu fail thì lần hai bị coi là
        "đã xử lý" -> media mất im lặng, không log, không đếm lỗi.
        """
        tasks = []
        for url, save_path, h, kind in jobs:
            if h in seen_hashes:
                src = seen_hashes[h]
                # Bản trước có thể đã fail (file không tồn tại) -> bỏ ghi nhận,
                # rơi xuống nhánh dưới để tải lại thay vì clone từ hư không.
                if os.path.exists(src):
                    if self.clone_cached(src, save_path):
                        continue
                seen_hashes.pop(h, None)

            if os.path.exists(save_path):
                seen_hashes[h] = save_path
                continue
            cached = self.cache.path_for(h)
            if cached and self.clone_cached(cached, save_path):
                seen_hashes[h] = save_path
                continue
            if self.stop_event.is_set():
                break
            t = asyncio.create_task(self._fetch(context, url, save_path, referer_url, h))
            t.kind = kind          # gather() đọc để đếm ảnh/video
            self.active_tasks.add(t)
            t.add_done_callback(self.active_tasks.discard)
            t.add_done_callback(self._remember_when_ok(h, save_path, seen_hashes))
            tasks.append(t)
        return tasks

    def _remember_when_ok(self, h, save_path, seen_hashes):
        """Chỉ ghi nhận hash khi task kết thúc với "OK".

        Trả về callback để gắn bằng add_done_callback. Không dùng biến closure
        gán trực tiếp vì lý do đã ghi ở engine.crawl_users: closure rebind sẽ
        tạo biến cục bộ và không ảnh hưởng dict bên ngoài (ở đây dict là object
        nên mutate được, nhưng vẫn tách hàm cho rõ ràng).
        """
        def _cb(fut):
            if fut.cancelled():
                return
            try:
                if fut.result() == "OK" and os.path.exists(save_path):
                    seen_hashes[h] = save_path
            except Exception:
                pass
        return _cb

    async def _racing_stop(self, coro):
        """Chờ get() hoặc cờ dừng, cái nào tới trước thì thắng.

        Trả về:
          - response   : request xong
          - None       : bị người dùng bấm Dừng
          - _TIMEOUT   : hết DOWNLOAD_TIMEOUT_MS mà request chưa xong

        Phân biệt hai trường hợp sau là bắt buộc: bản cũ trả None cho cả hai, nên
        một file tải quá chậm bị xếp vào "CANCELLED" -> counted() không đếm vào
        failed, không log dòng nào. Người dùng thấy "xong" trong khi file mất tích.

        Không poll: dùng asyncio.wait(FIRST_COMPLETED) trên hai task thật. Bản cũ
        lặp `asyncio.wait(timeout=0.05)` 800 lần cho mỗi file; với DOWNLOAD_SEM=10
        là 8.000 lần đánh thức event loop trong 40 giây, chỉ để kiểm một cờ.
        """
        get_task = asyncio.ensure_future(coro)
        stop_task = asyncio.ensure_future(self._stop_waiter())
        try:
            done, _ = await asyncio.wait(
                {get_task, stop_task},
                timeout=config.DOWNLOAD_TIMEOUT_MS / 1000,
                return_when=asyncio.FIRST_COMPLETED)

            if not done:
                return _TIMEOUT              # hết hạn, không ai thắng
            if get_task in done:
                return get_task.result()
            return None                      # stop_task thắng = người dùng dừng
        finally:
            # Bắt buộc: nếu chính _fetch bị cancel_all() huỷ, CancelledError
            # ném ra khỏi await asyncio.wait và các task con thành mồ côi ->
            # "Task was destroyed but it is pending" và giữ connection mở.
            for t in (get_task, stop_task):
                if not t.done():
                    t.cancel()

    async def _stop_waiter(self):
        """Task chỉ để "thua cuộc" khi người dùng bấm Dừng.

        Không dùng asyncio.sleep vô hạn: sleep dài giữ timer trong loop và làm
        thời gian chờ shutdown dài theo. Poll thưa 0.25s là đủ nhạy với nút bấm
        tay mà không tạo tải đáng kể (4 lần/giây so với 20 lần/giây cũ).
        """
        while not self.stop_event.is_set():
            await asyncio.sleep(0.25)

    async def _fetch(self, context, url, save_path, referer_url, url_hash_):
        if self.stop_event.is_set():
            return "CANCELLED"
        if os.path.exists(save_path):
            return "OK"

        async with self.semaphore:
            if os.path.exists(save_path):
                return "OK"
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            tmp_path = save_path + ".tmp"
            headers = {"Referer": referer_url}

            for attempt in range(config.MAX_RETRIES):
                if self.stop_event.is_set():
                    return "CANCELLED"
                response = None
                try:
                    await asyncio.sleep(0.05)
                    # Bấm Dừng -> coi cờ dừng là thời hạn cứng. Timeout của
                    # Playwright chỉ quyết định lúc BẮT ĐẦU request, nên request
                    # đã vào get() rồi vẫn treo tới hết DOWNLOAD_TIMEOUT_MS; bấm
                    # Dừng giữa chừng sẽ không cắt được. wait_for bên ngoài thì cắt
                    # được ngay lập tức dù request đang đọc dở.
                    timeout_ms = config.STOP_TIMEOUT_MS if self.stop_event.is_set() else config.DOWNLOAD_TIMEOUT_MS
                    get_coro = context.request.get(url, headers=headers, timeout=timeout_ms)
                    if self.stop_event.is_set():
                        response = await get_coro
                    else:
                        response = await self._racing_stop(get_coro)

                    if response is None:
                        return "CANCELLED"
                    if response is _TIMEOUT:
                        self.log(f"   [!] Hết thời gian chờ khi tải: {url[:70]}")
                        return "TIMEOUT"
                    if response.status == 200:
                        ctype = (response.headers.get('content-type') or '').lower()
                        if any(ct in ctype for ct in S.NON_MEDIA_CONTENT_TYPES):
                            # 200 nhưng trả HTML -> Cloudflare/404. Lưu ra .jpg là file rác.
                            self.log(f"   [!] Bị chặn/nội dung HTML, bỏ qua: {url[:70]}")
                            return "FAILED"

                        # Chặn TRƯỚC khi nạp: body() nằm trong RAM, nên file quá
                        # lớn phải biết trước. Playwright 1.54 không có API stream
                        # cho context.request, nên đây là chốt duy nhất.
                        too_big = self._too_big(response, url)
                        if too_big:
                            return "FAILED"

                        body = await response.body()
                        if not body:
                            return "FAILED"

                        # content-length khai báo mà nhận thiếu -> tải dở, lưu vào
                        # là file hỏng. Bản cũ không kiểm nên ghi thẳng.
                        declared = self._content_length(response)
                        if declared is not None and declared != len(body):
                            self.log(f"   [!] Nhận thiếu dữ liệu ({len(body)}/{declared} byte), "
                                     f"bỏ qua: {url[:60]}")
                            return "FAILED"

                        async with aiofiles.open(tmp_path, "wb") as f:
                            await f.write(body)
                        os.replace(tmp_path, save_path)
                        async with self.db_lock:
                            self.cache.record(url_hash_, save_path)
                        return "OK"

                    self.log(f"   [!] HTTP {response.status} khi tải: {url[:60]}...")
                    if self.stop_event.is_set():
                        return "CANCELLED"
                    if response.status in S.RETRY_STATUSES or response.status >= 500:
                        await asyncio.sleep(2 * (attempt + 1))
                    else:
                        # 4xx khác 429 là lỗi vĩnh viễn -> retry chỉ tốn thời gian.
                        return "FAILED"
                except asyncio.CancelledError:
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass
                    raise
                except Exception:
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass
                    if self.stop_event.is_set():
                        return "CANCELLED"
                    if attempt < config.MAX_RETRIES - 1:
                        await asyncio.sleep(1 + attempt)
                finally:
                    # Không dispose -> rò connection pool, vài trăm file là pool cạn.
                    if response is not None:
                        try:
                            await response.dispose()
                        except Exception:
                            pass
            return "FAILED"

    @staticmethod
    def _content_length(response):
        """content-length khai báo, hoặc None nếu server không gửi / gửi sai."""
        try:
            raw = response.headers.get('content-length')
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    def _too_big(self, response, url):
        """True nếu file vượt MAX_FILE_MB. Trả False khi không biết trước kích thước.

        Không biết thì vẫn tải: chặn mù sẽ bỏ sót media thật khi server không
        gửi content-length (chunked encoding là chuyện thường với XenForo).
        """
        limit = getattr(config, "MAX_FILE_MB", 0) * 1024 * 1024
        if not limit:
            return False
        declared = self._content_length(response)
        if declared is not None and declared > limit:
            self.log(f"   [!] Bỏ qua tệp > {config.MAX_FILE_MB}MB "
                     f"({declared // (1024*1024)}MB): {url[:60]}")
            return True
        return False

    async def drain(self, tasks, keep=0):
        """Chờ cho tới khi số task chưa xong giảm xuống <= keep.

        Dùng để chặn `pending` phình to trong thread dài. KHÔNG đếm thống kê và
        KHÔNG log tiến độ — việc đó vẫn do gather() làm ở cuối thread; ở đây chỉ
        chờ bớt để giới hạn số task đồng thời đang sống.
        """
        while True:
            running = [t for t in tasks if not t.done()]
            if len(running) <= keep:
                return
            await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)

    async def gather(self, tasks):
        """Chờ tải xong, trả về dict đếm theo loại: {'ok','failed','image','video','file'}.

        Mỗi task xong sẽ tự ghi nhận, và cứ mỗi PROGRESS_EVERY tệp lại báo một dòng
        tiến độ. Không có nó thì engine im lặng suốt lúc tải file nặng vài chục MB,
        người dùng tưởng treo. Dùng add_done_callback để đếm NGAY khi từng tệp xong.
        """
        if not tasks:
            return {"ok": 0, "failed": 0, "image": 0, "video": 0, "file": 0}
        total = len(tasks)
        state = {"ok": 0, "failed": 0, "image": 0, "video": 0, "file": 0}

        def counted(fut):
            r = fut.result() if not fut.cancelled() else None
            if r == "OK":
                state["ok"] += 1
                state[getattr(fut, "kind", "file")] += 1
            elif r == "TIMEOUT":
                # Hết giờ là lỗi thật, phải hiện trong thống kê. Bản cũ trả
                # "CANCELLED" cho cả trường hợp này nên file biến mất không dấu vết.
                state["failed"] += 1
            elif r == "FAILED" or (isinstance(r, BaseException)
                                  and not self.stop_event.is_set()):
                state["failed"] += 1
            state["done"] = state.get("done", 0) + 1
            if state["done"] % self.PROGRESS_EVERY == 0:
                self.log(f"      ↳ {state['done']}/{total} tệp xong"
                          f" ({state['ok']} mới, {state['failed']} lỗi)", "info")

        for t in tasks:
            t.add_done_callback(counted)

        await asyncio.gather(*tasks, return_exceptions=True)
        state.pop("done", None)
        return state

    def cancel_all(self):
        for t in list(self.active_tasks):
            try:
                t.cancel()
            except Exception:
                pass
        self.active_tasks.clear()