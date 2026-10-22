"""Tải file + lập kế hoạch tải.

Tách khỏi GUI: chỉ cần logger (hàm) và stop_event (threading.Event).
"""

import asyncio
import hashlib
import os
import shutil

import aiofiles

import config
import selectors as S
from xenforo_parse import clean_name, ext_for, get_url_filename


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
            filename = f"[{ts}]_{tag}_{i:03d}{ext}"
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
        """Tạo task cho các job chưa có. seen_hashes: hash -> path đã chiếm trong thread.

        Trùng hash trong cùng thread thì clone từ bản đầu, không tải lại.
        """
        tasks = []
        for url, save_path, h, kind in jobs:
            if h in seen_hashes:
                self.clone_cached(seen_hashes[h], save_path)
                continue
            seen_hashes[h] = save_path
            if os.path.exists(save_path):
                continue
            cached = self.cache.path_for(h)
            if cached and self.clone_cached(cached, save_path):
                continue
            if self.stop_event.is_set():
                break
            t = asyncio.create_task(self._fetch(context, url, save_path, referer_url, h))
            t.kind = kind          # gather() đọc để đếm ảnh/video
            self.active_tasks.add(t)
            t.add_done_callback(self.active_tasks.discard)
            tasks.append(t)
        return tasks

    async def _racing_stop(self, coro):
        """Chờ get() hoặc cờ dừng, cái nào tới trước thì thắng. Trả None nếu bị dừng."""
        get_task = asyncio.ensure_future(coro)
        try:
            for _ in range(int(config.DOWNLOAD_TIMEOUT_MS / 50) + 1):
                done, _ = await asyncio.wait([get_task], timeout=0.05)
                if done:
                    return get_task.result()
                if self.stop_event.is_set():
                    return None
            return None
        finally:
            # Bắt buộc: nếu chính _fetch bị cancel_all() huỷ, CancelledError
            # ném ra khỏi await asyncio.wait và get_task thành task mồ côi ->
            # "Task was destroyed but it is pending" và giữ connection mở.
            if not get_task.done():
                get_task.cancel()

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
                    if response.status == 200:
                        ctype = (response.headers.get('content-type') or '').lower()
                        if any(ct in ctype for ct in S.NON_MEDIA_CONTENT_TYPES):
                            # 200 nhưng trả HTML -> Cloudflare/404. Lưu ra .jpg là file rác.
                            self.log(f"   [!] Bị chặn/nội dung HTML, bỏ qua: {url[:70]}")
                            return "FAILED"
                        body = await response.body()
                        if not body:
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