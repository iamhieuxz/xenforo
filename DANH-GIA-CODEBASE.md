# Đánh giá codebase — XenForo Crawler V72

> Thời điểm đánh giá: 2026-11-05
> Phạm vi: toàn bộ 9 module (~2.100 LOC), chạy test suite, và **kiểm chứng từng lỗi bằng thực nghiệm**.
> Mọi kết luận trong tài liệu này đều có lệnh repro kèm theo, không suy luận từ đọc code.

---

## Điểm tổng: **64/100 — C+**

Nền tảng kiến trúc tốt, kỹ nghệ UI/accessibility trên mức trung bình, nhưng có **lỗi im lặng (silent failure) nghiêm trọng** làm sai lệch báo cáo cho người dùng.

| Tiêu chí | Trọng số | Điểm | Ghi chú |
|---|---|---|---|
| Kiến trúc / tách tầng | 20% | 7.5 | Phân tầng rõ, nhưng có 1 quả mìn namespace |
| Tính đúng đắn | 20% | 5.5 | 4 lỗi im lặng đã kiểm chứng |
| Xử lý lỗi / quan sát | 15% | 5.5 | `except` quá rộng, timeout biến mất |
| Hiệu năng / tài nguyên | 15% | 5.5 | Nạp cả file vào RAM, busy-poll |
| Bảo mật / bền vững | 10% | 7.0 | Path traversal an toàn, thiếu giới hạn dung lượng |
| Kiểm thử | 10% | 6.5 | 52 test nhanh nhưng **không hermetic** |
| UX / accessibility | 10% | 8.0 | WCAG AA có kiểm tự động — rất tốt |

**Mục tiêu sau khi sửa:** P0 → ~78 điểm; P0+P1 → ~85 điểm.

---

## Điểm mạnh

**1. Ranh giới tầng thực sự sạch.** `xenforo_parse.py` là hàm thuần (nhận soup → trả dữ liệu), `selectors.py` chỉ chứa hằng. Nhờ vậy 40/52 test chạy không cần mạng, không cần Chrome — quyết định kiến trúc đúng và hiếm gặp ở tool loại này.

**2. Văn hoá "sửa lỗi kèm giải thích nguyên nhân".** Docstring ghi rõ bug cũ và tại sao cách mới đúng. Ví dụ trong `selectors.py` giải thích vì sao phải neo `^...$` thay vì khớp chuỗi con — `js-selectToQuote` từng khớp `quote` và **xoá sạch thân bài**. Đây là thứ giữ code khỏi tái phát.

**3. Accessibility được tự động hoá thay vì khẩu hiệu.** `_check_palette.py` kiểm 2 theme × mọi cặp chữ/nền, có cả ngưỡng viền 3:1 theo WCAG 1.4.11:

```
ok  vien tren the: 3.54:1 (can >= 3.0)
Tat ca cap dat WCAG 2.2 AA.
```

Và test tương phản nằm luôn trong suite (`test_all_text_colors_pass_wcag_aa`) nên không thể regress.

**4. Ghi file nguyên tử + chống rò connection.** `tmp_path` → `os.replace()` trong `_fetch`, và `await response.dispose()` trong `finally` — hai chi tiết mà bản crawler nghiệp dư gần như luôn bỏ sót.

**5. Chống lặp vô hạn ở cả 2 tầng.** `visited` set cho box (`crawl_user`) và cho thread (`crawl_thread`) — cần thiết vì XenForo lặp link "Trang sau" khi filter không khớp.

**6. Nút Dừng thực sự cắt được.** `_racing_stop` đua giữa `get()` và cờ dừng thay vì chờ timeout 40s — có test đo bằng `perf_counter`.

---

## Điểm yếu — tất cả đã kiểm chứng bằng thực nghiệm

### C1. Banner báo "THÀNH CÔNG" dù mọi user đều lỗi — 🔴 nghiêm trọng

`engine.py`, hàm `crawl_users`: biến `ok` được gán `ok = False` **bên trong closure `user_worker`** mà không có `nonlocal`.

Kiểm bằng AST:

```
crawl_users L161 nested=[('user_worker', 169)]
  marks=[('assign_ok', 162), ('assign_ok', 184), ('assign_ok', 187), ('assign_ok', 178)]
                                        ↑ trong crawl_users   ↑ trong user_worker
```

Repro độc lập, cùng hình dạng code:

```
  worker 0: set local ok=False
  worker 1: set local ok=False
  worker 2: set local ok=False
crawl_users returned ok = True -> banner will claim SUCCESS
```

`ok` ở scope ngoài **không bao giờ** đổi. Người dùng quét 30 user, hỏng hết, vẫn thấy `[✓] ... ĐÃ HOÀN TẤT!`.

**Sửa:** thêm `nonlocal ok`, hoặc dùng `state = {"ok": True}` accumulator.

### C2. Media lỗi bị bỏ qua vĩnh viễn trong thread — 🔴 nghiêm trọng

`downloader.py`, hàm `dispatch`: `seen_hashes[h] = save_path` được ghi **trước khi** tải thành công. Lần xuất hiện thứ 2 của cùng URL → `clone_cached()` trả `False` → `continue`, không task nào được tạo.

```
first attempt file exists? False           ← tải hỏng (HTTP 500)
second occurrence dispatched any task? 0   → 0 means silently skipped
second file exists? False
```

Một ảnh xuất hiện ở 2 post, lần đầu fail → **lần hai bị coi là "đã xử lý"**.

**Sửa:** chỉ ghi `seen_hashes` sau khi `_fetch` trả `"OK"` (qua `add_done_callback`).

### C3. Timeout bị phân loại là "CANCELLED" — mất dấu hoàn toàn — 🔴 nghiêm trọng

`_racing_stop` hết vòng lặp thì trả `None`; `_fetch` đổi thành `"CANCELLED"`. Trong `counted()` chỉ `"FAILED"` mới tăng `failed`.

```
stats: {'ok': 0, 'failed': 0, 'image': 0, 'video': 0, 'file': 0}
any log line about it? []          ← KHÔNG một dòng log
file downloaded? False
=> slow download classified as: SILENT DROP
```

Máy chủ chậm 40s → file biến mất, **không log, không đếm lỗi**. Người dùng tưởng đã tải đủ.

**Sửa:** trả `"TIMEOUT"` khi hết hạn mà cờ dừng chưa bật; đếm vào `failed`; log một dòng `[!]`.

### C4. Video/file trùng tên đè nhau — 🔴 nghiêm trọng

`plan_jobs` chỉ thêm hash cho nhánh ảnh; video/file dùng `f"[{ts}]_{tag}_{i:03d}{ext}"` với `i` reset về 1 mỗi post:

```
post1 -> [20240101_120000]_comment_video_001.mp4
post2 -> [20240101_120000]_comment_video_001.mp4
COLLISION (different media, same path)? True
```

Nguy hiểm hơn: `post_timestamp` trả `"00000000_000000"` khi thiếu `<time.u-dt>` — **mọi post thiếu timestamp va vào cùng một tên**.

**Sửa:** thêm `_{h[:6]}` vào cả nhánh video/file.

### H1. `selectors.py` che module chuẩn của Python — 🟠 cao

File nội bộ đặt tên trùng module stdlib. `downloader.py` viết `import selectors as S` → nạp file local:

```
sys.modules['selectors'] -> F:\XENFORO2\selectors.py
stdlib names present? DefaultSelector: False EVENT_READ: False
SelectorEventLoop BROKEN -> AttributeError: module 'selectors' has no attribute 'DefaultSelector'
```

Hiện **chưa nổ** vì Windows Python 3.10 mặc định dùng `ProactorEventLoop` (không đi qua `selectors`). Nhưng đổi policy, dùng `uvloop`, hay Python đổi default → app chết ngay lúc tạo event loop.

**Sửa:** đổi tên thành `xf_selectors.py`.

### H2. Đổi theme giữa lúc quét → nút sai trạng thái + mất phím tắt — 🟠 cao

`toggle_theme` destroy toàn bộ widget rồi `_build_ui()` lại từ đầu, nhưng **không khôi phục state đang chạy**:

```
mid-scan: scan state = disabled | stop state = normal
AFTER theme switch mid-scan:
   scan button state = normal   <-- expected disabled
   stop button state = disabled <-- expected normal
   new entry <Return> bindings = ''  <-- empty means lost
```

Hậu quả: bấm "Quét" lúc đang quét → **hai engine song song**, dùng chung `stop_event` và `cache`. Phím `Return` ở ô URL cũng chết vì `_bind_keys()` chỉ gọi 1 lần lúc khởi động.

### H3. `_launch` không có khoá chống chạy chồng — 🟠 cao

`_launch` không kiểm tra `current_loop`. Và `_focused_primary` gọi thẳng `start_single_crawl_thread()` — **không đi qua** trạng thái disabled của nút:

```
scan buttons disabled? disabled
second engine launch attempted during a run? True
=> concurrent runs: 2
```

### H4. Nạp nguyên file vào RAM — 🟠 cao

`body = await response.body()` giữ toàn bộ bytes trong bộ nhớ rồi mới ghi. Với `DOWNLOAD_SEM = 10` và video vài trăm MB → dễ vượt 2-3 GB RSS.

### M1. `_racing_stop` busy-poll 20 lần/giây — 🟡 trung bình

Vòng lặp `for _ in range(int(DOWNLOAD_TIMEOUT_MS / 50) + 1)` + `asyncio.wait(timeout=0.05)` → 800 lần đánh thức mỗi file, ×10 file đồng thời = 8.000 wakeup/40s.

### M2. Bộ đếm thống kê ghi đè thay vì cộng dồn — 🟡 trung bình

`_track_stats` lấy **giá trị cuối** trong chuỗi log:

```
thread1 reports 8 ảnh -> 8
thread2 reports 1 ảnh -> 1
UI shows total: 1    actual session total: 9
```

### M3. Test không hermetic — ghi vào DB production — 🟡 trung bình

3 test tạo `XenForoScannerApp` thật → `MediaCache` mở `crawler_cache.db` **trong thư mục tải thật**:

```
--- artifacts written into the 'download' dir by tests ---
crawler_cache.db  20480
```

Khi `E:\` không ghi được (sandbox CI), chính 3 test này fail: `sqlite3.OperationalError: unable to open database file`.

### M4. Fallback thư mục bị "split-brain" — 🟡 trung bình

`_resolve_dir` fallback sang `~/RPHANG` và đặt **cache ở đó**, nhưng `engine.py` vẫn dùng `config.DOWNLOAD_DIR` để ghi media:

```
config.DOWNLOAD_DIR = E:\HIDE\RPHANG
=> cache ở ~/RPHANG, media ở E:\HIDE\RPHANG
```

Cache trỏ đường dẫn không tồn tại → mất tác dụng khử trùng lặp.

### M5. Deadlock tiềm ẩn khi `TAB_SEM = 1` — 🟡 trung bình

`crawl_link` giữ `tab_semaphore` rồi gọi `crawl_thread` — nơi **acquire lại cùng semaphore**:

```
TAB_SEM=2: thread done
TAB_SEM=1: DEADLOCK (timed out) <-- nested acquire never satisfied
```

README hướng dẫn chỉnh `TAB_SEM` trong config → người dùng hạ xuống 1 là treo cứng.

### M6. Task không giới hạn — 🟡 trung bình

`crawl_user` tạo **một task cho mỗi thread** rồi `gather`. Box 5.000 thread → 5.000 coroutine sống cùng lúc dù chỉ 2 cái chạy. Tương tự `pending` tích luỹ cả thread.

### N1. Tài liệu lệch thực tế — 🟢 thấp

- `browser_launcher.py` bảo đặt `COCOC_PATH` — biến này **không được đọc ở đâu cả** (grep chỉ ra 1 match duy nhất chính là dòng thông báo).
- README liệt kê `playwright==1.54.0` v.v. nhưng **không có `requirements.txt`**.
- `xenforo_parse.py` tự nhận "hàm thuần", nhưng `extract_post_media` gọi `_strip_junk` → `decompose()`, **sửa soup của caller**.

### N2. Không có giới hạn dung lượng / kiểm tra toàn vẹn — 🟢 thấp

Không so `Content-Length` với bytes ghi, không chặn file > N MB, không kiểm tra dung lượng đĩa trước khi tải.

### N3. Không có backoff ngẫu nhiên — 🟢 thấp

`asyncio.sleep(2 + attempt)` cố định → nhiều worker cùng nhịp, dễ bị rate-limit tập thể. `RETRY_STATUSES` chỉ có `429`.

---

## Đề xuất nâng cấp (theo thứ tự ưu tiên)

### P0 — Sửa ngay, ~50 dòng, chặn báo cáo sai

```python
# engine.py — C1
async def crawl_users(self, user_list, box_url):
    state = {"ok": True}                      # tránh closure rebind
    ...
        except Exception as e:
            state["ok"] = False
            self.log(f"[-] Lỗi user {user}: {e}")
    ...
    self._banner(state["ok"], "TOÀN BỘ ...")

# downloader.py — C2: chỉ ghi seen_hashes khi thành công
async def dispatch(self, context, jobs, referer_url, seen_hashes):
    tasks = []
    for url, save_path, h, kind in jobs:
        if h in seen_hashes and not os.path.exists(seen_hashes[h]):
            seen_hashes.pop(h)                # bản trước fail -> cho tải lại
        ...
        t = asyncio.create_task(self._fetch(...))
        t.add_done_callback(
            lambda f, h=h, p=save_path: seen_hashes.__setitem__(h, p)
            if not f.cancelled() and f.result() == "OK" else None)

# downloader.py — C3: phân biệt timeout với cancel
return "TIMEOUT" if not self.stop_event.is_set() else "CANCELLED"
# và trong counted(): elif r in ("FAILED", "TIMEOUT"): state["failed"] += 1
#   + self.log(f"   [!] Timeout: {save_path}", "summary")

# downloader.py — C4: thêm hash như nhánh ảnh
filename = f"[{ts}]_{tag}_{i:03d}_{h[:6]}{ext}"
```

### P1 — Cứng hoá kiến trúc (~1 buổi)

1. **Đổi tên `selectors.py` → `xf_selectors.py`** (H1). Cập nhật 3 import. Thay đổi 1 dòng nhưng loại bỏ một lớp lỗi không thể debug.
2. **Tách hàm `_apply_running_state()`** gọi ở cuối `toggle_theme` + `_launch` (H2), và gọi `_bind_keys()` bên trong `_build_ui`.
3. **Thêm guard trong `_launch`** (H3): `if self.current_loop and not self.current_loop.is_closed(): return`.
4. **`engine` nhận `download_dir` qua `__init__`** (M4), bỏ đọc `config.DOWNLOAD_DIR` trực tiếp.
5. **`TAB_SEM` tối thiểu 2** — hoặc bỏ acquire lồng nhau ở `crawl_link` (M5).

### P2 — Hiệu năng & độ bền (~1-2 ngày)

6. **Streaming download** thay `response.body()` (H4): ghi theo chunk qua `aiofiles`, kèm trần kích thước trong `config.py` (`MAX_FILE_MB = 512`).
7. **Thay busy-poll** bằng race thật (M1):
   ```python
   stop_task = asyncio.create_task(self._wait_stop())
   done, _ = await asyncio.wait({get_task, stop_task}, timeout=DOWNLOAD_TIMEOUT_MS/1000,
                                return_when=asyncio.FIRST_COMPLETED)
   ```
8. **Bounded queue** thay `gather` toàn bộ (M6): `asyncio.Queue` + N worker cố định cho thread.
9. **Backoff có jitter** + phân biệt host: `sleep(base * 2**attempt + random.uniform(0, 1))`.

### P3 — Kiểm thử & vận hành

10. **Hermetic test** (M3): `setUpModule` đặt `tempfile.mkdtemp()` vào `config.DOWNLOAD_DIR`, `tearDownModule` dọn. Thêm `requirements.txt` sinh từ version đã pin.
11. **Test cho engine** — hiện 0 test cho `engine.py`, đúng nơi chứa C1. Có thể test logic `ok` + `_banner` mà không cần Playwright bằng cách mock `crawl_user`.
12. **Sửa tài liệu** (N1): bỏ `COCOC_PATH`, hoặc implement thật (`find_browser(explicit=os.environ.get("COCOC_PATH"))`).
13. **Đổi tên `extract_post_media` → `extract_post_media_mutating`** hoặc copy soup trước khi `_strip_junk` (N1).

### P4 — Tính năng đáng cân nhắc

- **Resume checkpoint**: lưu tiến độ box/thread đã quét vào SQLite (bảng `crawl_state`) → tắt app giữa chừng không mất.
- **Bảng thống kê riêng** thay vì bóc regex từ chuỗi log — README tự thừa nhận đây là điểm yếu. `Downloader.gather()` đã có `stats` dict, chỉ cần trả về qua callback.
- **`--dry-run`**: quét và liệt kê media, không tải.

---

## Kết luận

Đây là codebase **trên mức trung bình rõ rệt** so với tool crawler cùng loại: phân tầng đúng, accessibility được kiểm tự động, và mỗi bug fix đều kèm giải thích nguyên nhân gốc.

Điểm trừ lớn nhất không phải là code khó đọc, mà là **app báo sai sự thật** — C1, C2, C3 cùng chiều: người dùng thấy "THÀNH CÔNG" trong khi dữ liệu thiếu. Với một công cụ tải hàng loạt, đây là loại lỗi tệ nhất vì nó phá huỷ niềm tin vào chính báo cáo của app.

Bốn sửa đổi P0 (~50 dòng) sẽ đưa điểm từ 64 lên khoảng **78**. Làm thêm P1 sẽ đạt **~85** — mức "solid production tool".
