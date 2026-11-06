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
import session_source
import xenforo_parse as X
from downloader import Downloader, plan_jobs, count_files, index_folder

try:
    import fast_fetch as _fast_fetch
except Exception:      # thiếu module thì rơi về trình duyệt, không chết app
    _fast_fetch = None


class CrawlerEngine:
    def __init__(self, cache, log, stop_event, download_dir=None):
        """download_dir: thư mục gốc để ghi media.

        Phải TIÊM vào chứ không đọc config.DOWNLOAD_DIR trực tiếp: khi ổ cấu
        hình không dùng được, v72._resolve_dir() fallback sang ~/RPHANG và đặt
        cache ở đó, nhưng engine vẫn ghi media vào config.DOWNLOAD_DIR ->
        cache trỏ đường dẫn không tồn tại, mất tác dụng khử trùng lặp.
        """
        self.log = log
        self.stop_event = stop_event
        self.cache = cache          # cần cho thread_index (ngày mở thread)
        self.download_dir = download_dir or config.DOWNLOAD_DIR
        self.db_lock = asyncio.Lock()
        self.tab_semaphore = asyncio.Semaphore(config.TAB_SEM)
        self.downloader = Downloader(
            cache=cache, log=log, stop_event=stop_event,
            semaphore=asyncio.Semaphore(config.DOWNLOAD_SEM), db_lock=self.db_lock)
        self.thread_semaphore = asyncio.Semaphore(config.THREAD_SEM)
        self.user_semaphore = asyncio.Semaphore(config.USER_SEM)
        self.active_pages = set()
        self._browser = None        # giữ để đóng ở close_browser()
        self._cookie_header = ""    # cookie lấy từ trình duyệt, cho HTTP-first

    # ---------- trình duyệt ----------
    async def connect(self, p):
        """Lấy browser context theo config.BROWSER_MODE.

        "persistent" (mặc định): Playwright tự mở trình duyệt với profile cố
        định. Không cần cổng TCP nào. Session đăng nhập nằm trong profile nên
        đăng nhập một lần là dùng mãi.

        "cdp": nối vào cổng debug của trình duyệt đang chạy (đường cũ, giữ làm
        dự phòng). Phân biệt ba trạng thái: cổng đóng, cổng bị tiến trình khác
        chiếm, và Chromium thật — bản cũ chỉ kiểm HTTP 200 nên bị đánh lừa.
        """
        mode = (getattr(config, "BROWSER_MODE", "persistent") or "persistent").lower()
        if mode == "cdp":
            return await self._connect_cdp(p)
        return await self._connect_persistent(p)

    async def _connect_persistent(self, p):
        """Mở trình duyệt với profile cố định — không dùng cổng TCP."""
        profile = session_source.resolve_profile()
        browser = (getattr(config, "SESSION_BROWSER", "chrome") or "chrome").lower()
        exe = browser_launcher.find_browser_for(browser)

        if not exe:
            self.log(f"[-] Không tìm thấy {browser}. Cài nó, hoặc đặt "
                     f"SESSION_BROWSER trong config.py sang trình duyệt khác.")
            return None

        # Kiểm trước khi mở: thiếu quyền ghi thì Chromium báo "Failed to create
        # a ProcessSingleton", thông báo đó không nói được nguyên nhân thật.
        if not session_source.profile_is_writable(profile):
            self.log(f"[-] Không ghi được vào profile {profile}. "
                     f"Đổi SESSION_PROFILE trong config.py.")
            return None

        # Trình duyệt đang chạy trên CÙNG profile này sẽ giữ khoá ProcessSingleton.
        if session_source.is_browser_running(browser) and \
                os.path.abspath(profile) == os.path.abspath(
                    session_source.find_installed_profiles().get(browser, {}).get("path", "")):
            self.log(f"[!] {browser} đang chạy và profile dùng chính là profile của nó. "
                     f"Hãy đóng {browser} trước, hoặc dùng profile riêng của app "
                     f"(đặt SESSION_PROFILE = \"\").")
            return None

        try:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=profile,
                executable_path=exe,
                headless=bool(getattr(config, "SESSION_HEADLESS", True)),
                args=list(getattr(config, "SESSION_EXTRA_ARGS", []) or []),
            )
        except Exception as e:
            self.log(f"[-] Không mở được trình duyệt ở mode persistent: {e}")
            return None

        self._browser = ctx

        # Chặn tài nguyên không cần. App chỉ đọc DOM để tìm URL media; tải ảnh
        # và font chỉ tốn băng thông và làm render chậm -> tab giữ lâu hơn ->
        # tốn RAM. Đo được: mỗi tab Chromium ~55 MB.
        if getattr(config, "BLOCK_IMAGES", True) or getattr(config, "BLOCK_FONTS", True):
            await self._install_resource_blocker(ctx)

        self.log(f"[*] Trình duyệt: {os.path.basename(exe)} | profile: {profile} | "
                 f"{'ẩn' if getattr(config, 'SESSION_HEADLESS', True) else 'hiện'}", "system")
        return ctx

    async def _install_resource_blocker(self, ctx):
        """Chặn ảnh/font/media ở tầng mạng.

        Không đụng tới HTML/CSS/JS: engine cần HTML để bóc DOM, và XenForo cần
        JS của nó chạy để dựng lazy-load. Chỉ bỏ những loại tài nguyên mà app
        không bao giờ đọc tới (app tải media bằng request riêng, không qua
        renderer của tab).
        """
        block_images = bool(getattr(config, "BLOCK_IMAGES", True))
        block_fonts = bool(getattr(config, "BLOCK_FONTS", True))

        # XenForo dùng lazy-load: nhiều ảnh chỉ có data-src, không có src. Nếu
        # chặn ảnh mà JS lazy-load gán src muộn thì DOM vẫn giữ data-src nên
        # engine vẫn bóc được — parser đã ưu tiên data-src.
        types = set()
        if block_images:
            types.update({"image"})
        if block_fonts:
            types.add("font")

        if not types:
            return

        async def _route(route):
            try:
                if route.request.resource_type in types:
                    await route.abort()
                else:
                    await route.continue_()
            except Exception:
                try:
                    await route.continue_()
                except Exception:
                    pass

        try:
            await ctx.route("**/*", _route)
            self.log(f"[*] Đã chặn tài nguyên không cần: {', '.join(sorted(types))} "
                     f"(giảm băng thông và RAM)", "system")
        except Exception as e:
            self.log(f"[!] Không đặt được bộ chặn tài nguyên: {e}")

    async def _connect_cdp(self, p):
        state = await asyncio.to_thread(browser_launcher.probe_port)
        if state["state"] == "ready":
            return await self._connect_once(p)

        if state["state"] == "not_chromium":
            self.log(f"[-] Cổng {config.CDP_PORT} đang bị tiến trình khác chiếm. "
                     f"Đổi CDP_PORT trong config.py hoặc tắt tiến trình đó.")
            return None

        if not config.AUTO_LAUNCH_BROWSER:
            self.log(f"[-] Lỗi: Thất bại khi kết nối CDP cổng {config.CDP_PORT}! "
                     f"Hãy chắc chắn trình duyệt đang bật debug.")
            return None

        ok, msg = await asyncio.to_thread(browser_launcher.launch)
        self.log(f"[*] {msg}", "system")
        return await self._connect_once(p) if ok else None

    async def close_browser(self):
        """Đóng browser/context đã mở ở mode persistent.

        Ở mode CDP thì KHÔNG đóng: trình duyệt là của người dùng, đóng nó sẽ
        làm mất cửa sổ họ đang dùng.
        """
        ctx = self._browser
        self._browser = None
        if ctx is None:
            return
        try:
            await ctx.close()
        except Exception:
            pass

    async def _connect_once(self, p):
        try:
            browser = await p.chromium.connect_over_cdp(config.CDP_URL)
            return browser.contexts[0] if browser.contexts else await browser.new_context()
        except Exception as e:
            self.log(f"[-] Không kết nối được CDP tại {config.CDP_URL}: {e}")
            return None

    async def open_page(self, context, url, retries=None):
        """Mở tab và trả về (page, soup). soup=None nến hết retry.

        Ở chế độ HTTP-first, hàm này KHÔNG mở tab: tải HTML bằng HTTP rồi trả
        (None, soup). Chỗ gọi phải chịu được page=None — close_page(None) là
        no-op. Nhờ vậy dò box nhanh gấp ~1,2× và không tốn RAM render.
        """
        if getattr(config, "USE_HTTP_FIRST", True):
            soup = await self.fetch_soup(url)
            if soup is not None:
                return None, soup
            # HTTP thất bại -> rơi về trình duyệt (trang cần JS, bị thử thách...).

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

    async def fetch_soup(self, url):
        """Tải HTML bằng HTTP thuần và trả soup, hoặc None nếu thất bại.

        Đo được: HTTP 8 luồng 14,2 trang/giây so với trình duyệt 11,6 — và
        không tốn ~55 MB RAM mỗi tab. Box công khai không cần JS để dựng danh
        sách thread, nên HTTP đủ.
        """
        if not _fast_fetch:
            return None
        try:
            res = await asyncio.to_thread(
                _fast_fetch.fetch_one, url,
                cookie=self._cookie_header)
        except Exception:
            return None
        if not res.ok or not res.text:
            return None
        return X.make_soup(res.text)

    async def refetch(self, page, url):
        """Tái sử dụng tab đang mở thay vì đóng/mở tab mới cho mỗi trang.

        page=None (chế độ HTTP-first) thì tải bằng HTTP.
        """
        if page is None:
            return await self.fetch_soup(url)
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
        if page is None:      # chế độ HTTP-first: không có tab nào để đóng
            return
        try:
            await page.close()
        except Exception:
            pass

    async def load_cookies(self, context):
        """Lấy cookie từ phiên trình duyệt đang mở, để HTTP-first dùng lại.

        ĐÂY LÀ CÁCH TẬN DỤNG PHIÊN CÓ SẴN. Không đọc file Cookies của trình
        duyệt: khi Chromium đang chạy, nó giữ khoá ĐỘC QUYỀN trên đúng file đó
        (đo được: chỉ Cookies bị khoá, Preferences/History/Web Data vẫn đọc
        được), nên đọc file luôn thất bại. Nhưng Playwright hỏi được cookie qua
        CDP/context — đó là phiên đang sống của chính bạn.

        Cookie được gắn vào request HTTP sau đó, nên dò box nhanh mà vẫn đúng
        danh tính. Không có nó thì box riêng sẽ trả trang đăng nhập thay vì nội
        dung.
        """
        if context is None:
            return
        try:
            cookies = await context.cookies()
        except Exception as e:
            self.log(f"[!] Không lấy được cookie từ trình duyệt: {e}")
            return

        seen = set()
        pairs = []
        for c in cookies:
            name = c.get("name") or ""
            if not name or name in seen:
                continue
            seen.add(name)
            pairs.append(f"{name}={c.get('value','')}")

        self._cookie_header = "; ".join(pairs)
        if pairs:
            self.log(f"[*] Đã lấy {len(pairs)} cookie từ phiên đang mở "
                     f"(dùng cho tải nhanh, không lộ giá trị).", "system")
        else:
            self.log("[*] Trình duyệt chưa có cookie — tải công khai.", "system")

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
            await self.load_cookies(context)
            try:
                # Semaphore chỉ giữ trong lúc dò tác giả, KHÔNG giữ khi gọi
                # crawl_thread: hàm đó tự acquire cùng semaphore. Giữ ở đây thì
                # với TAB_SEM=1 là tự khoá mình (acquire lồng, không bao giờ trả).
                async with self.tab_semaphore:
                    first_url = X.normalize_to_first_page(input_url)
                    self.log(f"[*] Đang bóc tách trang đầu tiên: {first_url}")
                    page, soup = await self.open_page(context, first_url, retries=1)
                    try:
                        author = X.resolve_author(soup) if soup is not None else ""
                    finally:
                        await self.close_page(page)

                if soup is None:
                    ok = False
                    return
                if not author:
                    self.log("[-] Lỗi: Không thể xác định danh tính tác giả bài viết này!")
                    ok = False
                    return
                self.log(f"[✓] Đã định danh chính xác tác giả gốc: {author.upper()}")

                # Dù bài đã có trong SQLite, vẫn chạy ĐẦY ĐỦ: duyệt hết trang,
                # đọc hết comment của chủ thớt, đếm media rồi mới quyết định có
                # phải tải hay không. Trước đây chỉ cần thấy cache có là lướt qua,
                # nên media thêm vào sau (hoặc post chủ thớt trả lời sau) bị bỏ sót
                # mà không ai biết.
                await self.crawl_thread(context, first_url, author)
            except asyncio.CancelledError:
                ok = False
                raise
            except Exception as e:
                ok = False
                self.log(f"[-] Lỗi trong tiến trình cào theo link: {e}")
            finally:
                # Ở mode persistent, context là CỦA APP — không đóng thì tiến
                # trình trình duyệt ở lại sau khi quét xong. Ở mode CDP, hàm này
                # không làm gì (không đóng trình duyệt của người dùng).
                await self.close_browser()

        self._banner(ok, "TIẾN TRÌNH CÀO THEO LINK")

    # ---------- quét nhiều user ----------
    async def crawl_users(self, user_list, box_url):
        # Dùng dict thay vì biến cục bộ: user_worker là closure, gán `ok = False`
        # trong đó tạo biến CỤC BỘ của closure và biến ngoài không bao giờ đổi ->
        # banner vẫn báo "ĐÃ HOÀN TẤT" dù mọi user đều lỗi.
        state = {"ok": True}
        total = len(user_list)
        if not total:
            return

        async with async_playwright() as p:
            context = await self.connect(p)
            if not context:
                return
            await self.load_cookies(context)

            async def user_worker():
                """Nhận user từ queue tới khi hết.

                Bản cũ gather() TOÀN BỘ user cùng lúc: với 500 user local, nó
                tạo 500 coroutine + 500 closure cùng sống dù chỉ USER_SEM cái
                chạy. Tốn RAM và làm nút Dừng chậm vì phải huỷ từng cái.
                Queue cố định N worker giống cách crawl_user đã làm cho thread.
                """
                while True:
                    if self.stop_event.is_set():
                        return
                    try:
                        user, idx = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    async with self.user_semaphore:
                        if self.stop_event.is_set():
                            return
                        try:
                            await self.crawl_user(context, user, idx, total, box_url)
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            state["ok"] = False
                            self.log(f"[-] Lỗi user {user}: {e}")

            queue = asyncio.Queue()
            for i, u in enumerate(user_list, 1):
                queue.put_nowait((u, i))

            workers = min(max(1, config.USER_SEM), total)
            try:
                await asyncio.gather(*[user_worker() for _ in range(workers)])
            except asyncio.CancelledError:
                state["ok"] = False
                raise
            except Exception as e:
                state["ok"] = False
                self.log(f"[-] Tiến trình gặp gián đoạn: {e}")
            finally:
                # Như crawl_link: đóng context của app ở mode persistent.
                await self.close_browser()

        self._banner(state["ok"], "TOÀN BỘ TIẾN TRÌNH ĐỒNG BỘ CÁC USER")

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

        thread_urls = []
        visited = set()
        pages = 0
        skipped = 0
        known = 0
        author_key = author.lower().strip()

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
                    pages += 1

                    # Đếm thread đã biết trong trang này. Dùng để dừng sớm:
                    # hai box bạn theo dõi có 989 + 347 = 1.336 trang, quét lại
                    # toàn bộ mỗi lần là không cần thiết vì bài mới luôn nằm ở
                    # trang đầu. Chỉ dừng khi CẢ TRANG đều đã biết — nếu chỉ một
                    # bài cũ mà dừng ngay thì sẽ bỏ sót bài mới nằm sau nó.
                    page_total = 0
                    page_known = 0

                    # Lọc NGAY ở danh sách: chỉ giữ thread có tác giả khớp.
                    # Trước đây gom hết link rồi mới mở từng thread để kiểm
                    # data-author -> box 100 trang là mở cả nghìn thread, rất
                    # chậm và dễ bị chặn. XenForo ghi data-author trên item của
                    # box nên lọc được từ đây.
                    for item in soup.find_all('div', class_=X.S.STRUCT_THREAD_RE):
                        starter = X.thread_starter(item)
                        if starter and starter.lower() != author_key:
                            skipped += 1
                            continue
                        found, _ = X.parse_thread_links(
                            X.soup_of_single(item), current)
                        for u in found:
                            page_total += 1
                            if u in thread_urls:
                                continue
                            if self._thread_already_done(u):
                                page_known += 1
                                known += 1
                                continue
                            thread_urls.append(u)

                    if getattr(config, "STOP_ON_KNOWN_THREAD", True) and \
                            page_total > 0 and page_known == page_total:
                        self.log(f"   [✓] Trang {pages}: toàn bài đã có trong máy "
                                 f"-> dừng đọc box (tiết kiệm "
                                 f"{'các trang còn lại' if pages == 1 else 'thời gian'}).")
                        break

                    cap = getattr(config, "BOX_MAX_PAGES", 0) or 0
                    if cap and pages >= cap:
                        self.log(f"   [•] Đã đọc {pages} trang (giới hạn BOX_MAX_PAGES).")
                        break

                    # Sang trang: phải GIỮ ?starter=..., nếu không XenForo trả về
                    # toàn bộ box. parse_thread_links đã lo việc này.
                    _, current = X.parse_thread_links(soup, current)
                    if current:
                        soup = await self.refetch(page, current)
            finally:
                await self.close_page(page)

        if not thread_urls:
            self.log(f"   [•] {author.upper()}: không có bài MỚI nào trong box này"
                     f" ({pages} trang đã đọc, {skipped} bài người khác, "
                     f"{known} bài đã có trong máy).")
            return
        self.log(f"   [+] {author.upper()}: {len(thread_urls)} bài mới trong "
                 f"{pages} trang ({skipped} bài người khác, {known} bài đã có).")

        # Chạy các thread đã gom được. Thiếu lời gọi này thì crawl_user chỉ đọc
        # box rồi kết thúc — không tải được gì.
        await self._crawl_threads_of_author(context, thread_urls, author)

    def _thread_already_done(self, thread_url):
        """True nếu thread này đã được tải đủ trước đó.

        Dựa vào `thread_index`: crawl_thread ghi ngày + folder SAU khi đọc hết
        các trang của thread. Có bản ghi nghĩa là lần trước đã xử lý xong.

        Khoá là ID số của thread (/t/<slug>.<id>/), không phải URL đầy đủ: slug
        đổi khi chủ bài sửa tiêu đề, còn id thì không.
        """
        if not getattr(config, "STOP_ON_KNOWN_THREAD", True):
            return False
        cache = getattr(self, "cache", None)
        if cache is None:
            return False
        key = X.thread_key(thread_url)
        if not key:
            return False
        try:
            return bool(cache.thread_date(key))
        except Exception:
            return False

    async def _crawl_threads_of_author(self, context, thread_urls, author):
        """Chạy N worker cố định nhận thread từ queue.

        Không tạo một task cho MỖI thread rồi gather tất cả: box 5.000 thread
        sinh 5.000 coroutine cùng sống (dù chỉ THREAD_SEM cái chạy), tốn bộ nhớ
        và làm chậm nút Dừng.
        """
        if not thread_urls:
            return
        ordered = sorted(thread_urls)
        workers = max(1, config.THREAD_SEM)
        queue = asyncio.Queue()
        for i, url in enumerate(ordered, 1):
            queue.put_nowait((url, i))

        async def thread_worker():
            while True:
                if self.stop_event.is_set():
                    return
                try:
                    url, i = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    async with self.thread_semaphore:
                        if self.stop_event.is_set():
                            return
                        await self.crawl_thread(context, url, author, i)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.log(f"   [!] Lỗi thread {url[:60]}: {e}")

        await asyncio.gather(*[thread_worker() for _ in range(workers)])


    # ---------- bóc + tải 1 thread ----------
    async def crawl_thread(self, context, thread_url, author, idx=1):
        author_key = author.lower().strip()
        async with self.tab_semaphore:
            page, soup = await self.open_page(context, thread_url)
            try:
                if soup is None:
                    return

                title, date_prefix = X.thread_meta(soup)
                # Ngày đã biết từ lần quét trước thì DÙNG LẠI. Nếu không, một lần
                # server thiếu ngày (trang lỗi, theme khác) là folder đổi tên ->
                # app coi là bài mới và tải lại toàn bộ dù file đã có.
                #
                # Khoá phải là ID SỐ của thread, không phải URL đầy đủ: slug đổi
                # khi chủ bài sửa tiêu đề, nên dùng URL làm khoá thì bài cũ bị
                # coi là bài mới sau mỗi lần sửa tiêu đề -> tải lại toàn bộ.
                thread_key = X.thread_key(thread_url) or \
                    thread_url.split('?')[0].split('#')[0]
                remembered = (self.cache.thread_date(thread_key)
                              if self.cache is not None else None)
                if remembered:
                    if not date_prefix:
                        date_prefix = remembered
                        self.log(f"   [*] Dùng ngày đã lưu trong cache: {remembered}")
                # Báo trước khi tải: 1 thread có thể mất cả chục giây vì file nặng,
                # không có dòng này thì nhìn log tưởng app treo.
                self.log(f"   [↓] Bài {idx}: {title[:60]}")
                folder = X.thread_folder(self.download_dir, author, title, date_prefix)
                if not date_prefix:
                    self.log("   [!] Không xác định được ngày mở bài; dùng folder "
                             "'khong-ngay' (sẽ ổn định cho các lần sau).")
                os.makedirs(folder, exist_ok=True)
                # KHÔNG ghi thread_index ở đây. Ghi trước khi tải nghĩa là thread
                # tải hỏng vẫn bị đánh dấu "đã xong", và tính năng dừng sớm sẽ
                # bỏ qua nó ở lần quét sau -> media mất im lặng. Chỉ ghi sau khi
                # đã đọc hết các trang của thread (xem cuối khối này).

                current = thread_url
                visited = set()
                seen_hashes = {}     # trùng media trong cùng thread -> clone, không tải lại
                # Chỉ mục hash -> file đã có trong folder. Cần vì tên file có
                # timestamp: nếu server lần này không trả giờ, tên đổi, và nếu
                # không biết media đã có thì sẽ tạo thêm bản sao thứ hai.
                folder_index = index_folder(folder)
                pending = []         # tải chồng với việc bóc trang kế tiếp
                img_idx = 0
                # Đếm để báo cáo "đã thấy bao nhiêu / tải được bao nhiêu" thay vì
                # im lặng bỏ qua khi mọi thứ đã có trong cache.
                found_images = found_videos = found_files = 0
                author_posts = 0
                other_posts = 0
                pages_done = 0

                while current and not self.stop_event.is_set():
                    if current in visited:
                        self.log(f"   [!] Lặp trang trong thread, dừng: {current[:60]}")
                        break
                    visited.add(current)

                    # soup None = trang này tải hỏng. Bản cũ gọi soup.select() luôn
                    # -> AttributeError -> nhảy ra except ngoài, bỏ dở cả thread VÀ
                    # không chạy gather() nên mất luôn thống kê của các trang đã
                    # xong. Giờ dừng vòng lặp nhưng vẫn báo cáo phần đã tải.
                    if soup is None:
                        self.log(f"   [!] Bỏ qua trang không tải được: {current[:60]}")
                        break

                    posts = soup.select("article.message--post[data-author]")
                    if not posts:
                        break
                    pages_done += 1
                    main_content = posts[0].get("data-content", "")

                    for post in posts:
                        if self.stop_event.is_set():
                            break
                        if post.get('data-author', '').strip().lower() != author_key:
                            other_posts += 1
                            continue
                        author_posts += 1

                        imgs, vids, files = X.extract_post_media(post, current)
                        if not (imgs or vids or files):
                            continue
                        ts = X.post_timestamp(post)
                        if not ts:
                            # Không xác định được giờ post: dùng nhãn ổn định thay
                            # vì chuỗi rỗng. Tên file vẫn có hash nên không đè
                            # nhau, và lần quét sau ra CÙNG tên -> khớp cache.
                            ts = "khong-gio"
                        video_tag = 'main_video' if post.get("data-content", "") == main_content else 'comment_video'

                        found_images += len(imgs)
                        found_videos += len(vids)
                        found_files += len(files)

                        jobs = []
                        if vids:
                            jobs += plan_jobs(vids, folder, ts, video_tag)
                        if files:
                            jobs += plan_jobs(files, folder, ts, 'comment_file')
                        if imgs:
                            img_idx += len(imgs)
                            jobs += plan_jobs(imgs, folder, ts, 'image', seq_start=img_idx - len(imgs) + 1)

                        pending += await self.downloader.dispatch(
                            context, jobs, current, seen_hashes, folder_index)
                        # Chặn `pending` phình to: thread 20 trang × 20 post × 20 ảnh
                        # sinh hàng nghìn task cùng sống. Chờ bớt khi vượt ngưỡng,
                        # rồi chỉ giữ lại các task còn chạy.
                        if len(pending) >= config.PENDING_LIMIT:
                            await self.downloader.drain(pending)
                            pending = [t for t in pending if not t.done()]

                    current = X.next_page_url(soup, current)
                    if current:
                        soup = await self.refetch(page, current)

                stats = await self.downloader.gather(pending)
                self._report_thread(author, idx, stats, {
                    "images": found_images, "videos": found_videos,
                    "files": found_files, "author_posts": author_posts,
                    "other_posts": other_posts, "pages": pages_done,
                    "folder": folder,
                })

                # Ghi mốc "đã xử lý xong" SAU khi đọc hết các trang và tải xong.
                # Điều kiện: đã đọc được ít nhất 1 trang. Nếu tải hỏng ngay trang
                # đầu (pages_done == 0) thì KHÔNG ghi, để lần sau còn thử lại —
                # nếu ghi, tính năng dừng sớm sẽ bỏ qua thread này mãi mãi.
                if self.cache is not None and pages_done > 0:
                    self.cache.remember_thread_date(thread_key, date_prefix, folder)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log(f"   [!] Lỗi bóc tách nội dung thớt bài viết: {e}")
            finally:
                await self.close_page(page)

    def _report_thread(self, author, idx, stats, found=None):
        """Báo cáo kết quả một thread: đã thấy bao nhiêu, tải mới bao nhiêu.

        Bản cũ chỉ nói "đã trùng khớp (SQLite Index Match)" khi không tải được
        gì, nên người dùng không biết app đã thật sự quét hết comment của chủ
        thớt hay chỉ lướt qua rồi bỏ. Giờ luôn in số post của chủ thớt đã đọc,
        số media phát hiện, và số tệp có thật trên đĩa.
        """
        found = found or {}
        failed = stats.get("failed", 0)
        downloaded = stats.get("ok", 0)

        seen_total = (found.get("images", 0) + found.get("videos", 0)
                      + found.get("files", 0))
        posts = found.get("author_posts", 0)
        others = found.get("other_posts", 0)
        pages = found.get("pages", 0)
        folder = found.get("folder")

        # Số tệp CÓ THẬT trên đĩa, không phải số dự kiến: đây là thứ người dùng
        # quan tâm khi nghi ngờ app bỏ sót.
        on_disk = -1
        if folder:
            try:
                on_disk = len([f for f in os.listdir(folder)
                               if os.path.isfile(os.path.join(folder, f))])
            except OSError:
                on_disk = -1

        tail = []
        if posts:
            tail.append(f"{posts} bài của chủ thớt")
        if others:
            tail.append(f"{others} bài người khác bỏ qua")
        if pages:
            tail.append(f"{pages} trang")
        ctx = f" [{', '.join(tail)}]" if tail else ""

        if failed:
            self.log(f"   [!] Cảnh báo: {failed} tệp lỗi đường truyền trong bài này.")
        if downloaded:
            self.log(f"   [✓] {author.upper()}: Bài {idx} tải mới "
                     + count_files(stats) + ctx)
        elif seen_total and not self.stop_event.is_set():
            # ĐÃ QUÉT ĐẦY ĐỦ, chỉ là không có gì mới. Nói rõ ra thay vì "trùng khớp".
            disk = f", trên đĩa có {on_disk} tệp" if on_disk >= 0 else ""
            self.log(f"   [•] {author.upper()}: Bài {idx} đã có đủ "
                     f"{seen_total} media{disk}{ctx} — không cần tải lại.")
        elif not seen_total and not self.stop_event.is_set():
            self.log(f"   [•] {author.upper()}: Bài {idx} không có media nào{ctx}.")
        if on_disk >= 0 and seen_total and on_disk < seen_total and not downloaded:
            # Cache nói "đã có" nhưng đĩa thiếu -> đây là dấu hiệu dữ liệu hỏng,
            # phải cảnh báo chứ không im lặng coi là xong.
            self.log(f"   [!] Đĩa chỉ có {on_disk}/{seen_total} tệp. Có thể file đã bị "
                     f"xoá hoặc di chuyển; chạy lại để tải bù.")
        elif on_disk > seen_total:
            # Đĩa NHIỀU hơn số media phát hiện được: dấu hiệu của bản sao trùng từ
            # các lần quét trước (tên file đổi vì timestamp khác). Không tự xoá,
            # nhưng phải nói ra để người dùng biết mà dọn.
            self.log(f"   [!] Trong folder có {on_disk} tệp nhưng bài chỉ có "
                     f"{seen_total} media — có thể còn bản sao từ lần quét trước.")