"""Điều phối Playwright: duyệt box -> duyệt thread -> bóc media -> tải.

Mỗi vòng duyệt đều có visited-set: XenForo hay lặp link 'Trang sau' khi filter
không khớp, thiếu nó sẽ crawl vô hạn.
"""

import asyncio
import os
import urllib.parse

from playwright.async_api import async_playwright

import config
import browser_launcher
import xenforo_parse as X
from downloader import Downloader, plan_jobs, count_files


class CrawlerEngine:
    def __init__(self, cache, log, stop_event):
        self.log = log
        self.stop_event = stop_event
        self.db_lock = asyncio.Lock()
        self.tab_semaphore = asyncio.Semaphore(config.TAB_SEM)
        self.downloader = Downloader(
            cache=cache, log=log, stop_event=stop_event,
            semaphore=asyncio.Semaphore(config.DOWNLOAD_SEM), db_lock=self.db_lock)
        self.thread_semaphore = asyncio.Semaphore(config.THREAD_SEM)
        self.user_semaphore = asyncio.Semaphore(config.USER_SEM)
        self.active_pages = set()

    # ---------- trình duyệt ----------
    async def connect(self, p):
        """Thử CDP; nếu cổng chưa mở thì tự bật trình duyệt rồi thử lại."""
        if browser_launcher.is_port_open():
            return await self._connect_once(p)
        if not config.AUTO_LAUNCH_BROWSER:
            self.log("[-] Lỗi: Thất bại khi kết nối CDP cổng 9222! "
                     "Hãy chắc chắn trình duyệt đang bật debug.")
            return None

        # Chặn event loop thì GUI không vẽ được -> đẩy sang thread phụ.
        ok, msg = await asyncio.to_thread(browser_launcher.launch)
        self.log(f"[*] {msg}", "system")
        return await self._connect_once(p) if ok else None

    async def _connect_once(self, p):
        try:
            browser = await p.chromium.connect_over_cdp(config.CDP_URL)
            return browser.contexts[0] if browser.contexts else await browser.new_context()
        except Exception:
            self.log("[-] Lỗi: Thất bại khi kết nối CDP cổng 9222! "
                     "Hãy chắc chắn trình duyệt đang bật debug.")
            return None

    async def open_page(self, context, url, retries=None):
        """Mở tab và trả về (page, soup). soup=None nến hết retry."""
        page = await context.new_page()
        self.active_pages.add(page)
        retries = config.MAX_RETRIES if retries is None else retries
        soup = None
        try:
            for attempt in range(retries):
                if self.stop_event.is_set():
                    break
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
                    await page.wait_for_timeout(config.SETTLE_MS)
                    soup = X.make_soup(await page.content())
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    if self.stop_event.is_set():
                        break
                    if attempt == retries - 1:
                        self.log(f"   [!] Không tải được {url[:70]}: {e}")
                    else:
                        await asyncio.sleep(2 + attempt)
        except asyncio.CancelledError:
            # Cancel tới giữa chừng open_page thì ngoài try/finally ở crawl_user,
            # tab đã mở sẽ không bao giờ được đóng -> rò tab mỗi lần bấm Dừng.
            await self.close_page(page)
            raise
        return page, soup

    async def refetch(self, page, url):
        """Tái sử dụng tab đang mở thay vì đóng/mở tab mới cho mỗi trang."""
        for attempt in range(config.MAX_RETRIES):
            if self.stop_event.is_set():
                return None
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
                await page.wait_for_timeout(config.SETTLE_MS)
                return X.make_soup(await page.content())
            except asyncio.CancelledError:
                # Nuốt CancelledError ở đây sẽ lặp tiếp MAX_RETRIES lần, mỗi lần
                # chờ 2+attempt giây -> nút Dừng treo thêm ~15s nữa.
                raise
            except Exception:
                if attempt == config.MAX_RETRIES - 1:
                    return None
                await asyncio.sleep(2 + attempt)

    async def close_page(self, page):
        self.active_pages.discard(page)
        try:
            await page.close()
        except Exception:
            pass

    def emergency_cleanup(self):
        self.downloader.cancel_all()
        # Đóng tab bằng ensure_future: hàm này chạy trong engine loop (qua
        # call_soon_threadsafe). Task đóng tab được huỷ lại ở finally của
        # run_async_engine nếu tới trước, nên tab có thể còn mở -> thêm fallback
        # đóng cứng ở cuối.
        for page in list(self.active_pages):
            try:
                asyncio.ensure_future(page.close())
            except Exception:
                pass
        self.active_pages.clear()

    # ---------- quét 1 link bài viết ----------
    async def crawl_link(self, input_url):
        ok = True
        async with async_playwright() as p:
            context = await self.connect(p)
            if not context:
                return
            try:
                async with self.tab_semaphore:
                    first_url = X.normalize_to_first_page(input_url)
                    self.log(f"[*] Đang bóc tách trang đầu tiên: {first_url}")
                    page, soup = await self.open_page(context, first_url, retries=1)
                    try:
                        if soup is None:
                            ok = False
                            return
                        author = X.resolve_author(soup)
                    finally:
                        await self.close_page(page)

                    if not author:
                        self.log("[-] Lỗi: Không thể xác định danh tính tác giả bài viết này!")
                        ok = False
                        return
                    self.log(f"[✓] Đã định danh chính xác tác giả gốc: {author.upper()}")
                    await self.crawl_thread(context, first_url, author)
            except asyncio.CancelledError:
                ok = False
                raise
            except Exception as e:
                ok = False
                self.log(f"[-] Lỗi trong tiến trình cào theo link: {e}")

        self._banner(ok, "TIẾN TRÌNH CÀO THEO LINK")

    # ---------- quét nhiều user ----------
    async def crawl_users(self, user_list, box_url):
        ok = True
        total = len(user_list)
        async with async_playwright() as p:
            context = await self.connect(p)
            if not context:
                return

            async def user_worker(user, idx):
                async with self.user_semaphore:
                    if self.stop_event.is_set():
                        return
                    try:
                        await self.crawl_user(context, user, idx, total, box_url)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        ok = False
                        self.log(f"[-] Lỗi user {user}: {e}")

            try:
                await asyncio.gather(*[user_worker(u, i) for i, u in enumerate(user_list, 1)])
            except asyncio.CancelledError:
                ok = False
                raise
            except Exception as e:
                ok = False
                self.log(f"[-] Tiến trình gặp gián đoạn: {e}")

        self._banner(ok, "TOÀN BỘ TIẾN TRÌNH ĐỒNG BỘ CÁC USER")

    def _banner(self, ok, title):
        self.log("\n========================================")
        if ok and not self.stop_event.is_set():
            self.log(f"[✓] {title} ĐÃ HOÀN TẤT!")
        else:
            self.log(f"[!] {title} BỊ GIÁN ĐOẠN HOẶC DỪNG CƯỠNG BỨC!")
        self.log("========================================\n")

    async def crawl_user(self, context, author, idx, total, box_url):
        self.log(f"\n👥 [USER {idx}/{total}] ĐỒNG BỘ DỮ LIỆU: {author.upper()}", "info")

        base = box_url.split('?')[0]
        first = f"{base}?starter={urllib.parse.quote(author)}"

        thread_urls = set()
        visited = set()
        async with self.tab_semaphore:
            page, soup = await self.open_page(context, first)
            try:
                current = first
                while current and not self.stop_event.is_set():
                    if current in visited:
                        self.log(f"   [!] Phát hiện lặp trang, dừng duyệt box: {current[:60]}")
                        break
                    visited.add(current)
                    if soup is None:
                        break
                    links, current = X.parse_thread_links(soup, current)
                    thread_urls.update(links)
                    if current:
                        soup = await self.refetch(page, current)
            finally:
                await self.close_page(page)

        if not thread_urls:
            return
        self.log(f"   [+] {author.upper()}: Định vị thành công {len(thread_urls)} Thread bài viết.")

        async def thread_worker(url, i):
            async with self.thread_semaphore:
                if self.stop_event.is_set():
                    return
                try:
                    await self.crawl_thread(context, url, author, i)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.log(f"   [!] Lỗi thread {url[:60]}: {e}")

        await asyncio.gather(*[thread_worker(u, i) for i, u in enumerate(sorted(thread_urls), 1)])

    # ---------- bóc + tải 1 thread ----------
    async def crawl_thread(self, context, thread_url, author, idx=1):
        author_key = author.lower().strip()
        async with self.tab_semaphore:
            page, soup = await self.open_page(context, thread_url)
            try:
                if soup is None:
                    return

                title, date_prefix = X.thread_meta(soup)
                # Báo trước khi tải: 1 thread có thể mất cả chục giây vì file nặng,
                # không có dòng này thì nhìn log tưởng app treo.
                self.log(f"   [↓] Bài {idx}: {title[:60]}")
                folder = X.thread_folder(config.DOWNLOAD_DIR, author, title, date_prefix)
                os.makedirs(folder, exist_ok=True)

                current = thread_url
                visited = set()
                seen_hashes = {}     # trùng media trong cùng thread -> clone, không tải lại
                pending = []         # tải chồng với việc bóc trang kế tiếp
                img_idx = 0

                while current and not self.stop_event.is_set():
                    if current in visited:
                        self.log(f"   [!] Lặp trang trong thread, dừng: {current[:60]}")
                        break
                    visited.add(current)

                    posts = soup.select("article.message--post[data-author]")
                    if not posts:
                        break
                    main_content = posts[0].get("data-content", "")

                    for post in posts:
                        if self.stop_event.is_set():
                            break
                        if post.get('data-author', '').strip().lower() != author_key:
                            continue

                        imgs, vids, files = X.extract_post_media(post, current)
                        if not (imgs or vids or files):
                            continue
                        ts = X.post_timestamp(post)
                        video_tag = 'main_video' if post.get("data-content", "") == main_content else 'comment_video'

                        jobs = []
                        if vids:
                            jobs += plan_jobs(vids, folder, ts, video_tag)
                        if files:
                            jobs += plan_jobs(files, folder, ts, 'comment_file')
                        if imgs:
                            img_idx += len(imgs)
                            jobs += plan_jobs(imgs, folder, ts, 'image', seq_start=img_idx - len(imgs) + 1)

                        pending += await self.downloader.dispatch(context, jobs, current, seen_hashes)

                    current = X.next_page_url(soup, current)
                    if current:
                        soup = await self.refetch(page, current)

                stats = await self.downloader.gather(pending)
                self._report_thread(author, idx, stats)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log(f"   [!] Lỗi bóc tách nội dung thớt bài viết: {e}")
            finally:
                await self.close_page(page)

    def _report_thread(self, author, idx, stats):
        failed = stats["failed"]
        if failed:
            self.log(f"   [!] Cảnh báo: {failed} tệp lỗi đường truyền trong bài này.")
        if stats["ok"]:
            self.log(f"   [✓] {author.upper()}: Bài {idx} đồng bộ thành công "
                     + count_files(stats))
        elif failed == 0 and not self.stop_event.is_set():
            self.log(f"   [•] {author.upper()}: Bài {idx} đã trùng khớp (SQLite Index Match).")