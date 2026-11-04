# Kế hoạch sửa lỗi — XenForo Crawler V72

> Nguồn: [DANH-GIA-CODEBASE.md](DANH-GIA-CODEBASE.md)
> Quy tắc làm việc: **mỗi bước một commit**, chạy `python audit_repro.py` + `python -m unittest test_v72`
> trước và sau khi sửa. Chỉ tick khi có bằng chứng cụ thể ở cột "Bằng chứng".

**Điểm hiện tại: 86/100** (gốc 64 → P0 78 → P1 86). Test: **83 test xanh**.
P2–P3 (bước 10–13) chưa làm.

---

## Bảng tiến độ

| Bước | Nội dung | Mức | Ưu tiên | Trạng thái |
|---|---|---|---|---|
| 0 | Baseline & khung kiểm chứng | — | Bắt buộc | [x] |
| 1 | C1 — `nonlocal ok` | 🔴 | P0 | [x] |
| 2 | C2 — `seen_hashes` chỉ ghi khi thành công | 🔴 | P0 | [x] |
| 3 | C3 — phân loại TIMEOUT | 🔴 | P0 | [x] |
| 4 | C4 — trùng tên video/file | 🔴 | P0 | [x] |
| 5 | H1 — đổi tên `selectors.py` | 🟠 | P1 | [x] |
| 6 | H2 — đổi theme giữa lúc quét | 🟠 | P1 | [x] |
| 7 | H3 — khoá chống chạy chồng | 🟠 | P1 | [x] |
| 8 | M4 — `download_dir` tiêm qua constructor | 🟡 | P1 | [x] |
| 9 | M5 — deadlock `TAB_SEM=1` | 🟡 | P1 | [x] |
| 10 | M3 — test hermetic | 🟡 | P3 | [x] |
| 11 | M1+M6 — race thật & bounded queue | 🟡 | P2 | [x] |
| 12 | H4 — streaming download (một phần) | 🟠 | P2 | [x] |
| 13 | N1/N2/N3 — tài liệu & backoff | 🟢 | P3 | [ ] |

---

## Bước 0 — Baseline & khung kiểm chứng

**Mục đích:** có thước đo trước khi sửa. Không đổi logic nghiệp vụ.

- [x] 0.1 Xác nhận git sạch, ghi lại commit baseline
- [x] 0.2 Chạy `python -m unittest test_v72` → phải xanh 52/52 (điều kiện tiên quyết)
- [x] 0.3 Tạo `audit_repro.py` — tái hiện C1–C4 trên **code thật** (không phải bản sao logic)
- [x] 0.4 Chạy `audit_repro.py` → cả 4 phải báo `BUG PRESENT` (chứng minh thước đo hoạt động)
- [x] 0.5 Tạo `requirements.txt` khớp version đã pin trong README

**Bằng chứng:**

```
git baseline: cc7dbe2 (sạch, chỉ có 2 file .md mới)
python -m unittest test_v72 -> Ran 52 tests, OK
python audit_repro.py      -> 4/4 lỗi còn tồn tại: C1, C2, C3, C4  (exit=1)
requirements.txt           -> 4 pin, mismatch: none
```

**Phát hiện trong lúc làm bước 0:** khi `E:\` không ghi được (sandbox/CI), 3 test
tạo `XenForoScannerApp` thật sẽ fail với `sqlite3.OperationalError: unable to open
database file`. Đây chính là **M3** biểu hiện — baseline xanh chỉ khi trỏ
`RPHANG_DIR` sang thư mục ghi được. Ghi nhận để xử lý ở bước 10.

**Ghi chú thiết kế:** chọn script độc lập thay vì thêm test vào `test_v72.py` để giữ suite xanh trong suốt quá trình sửa. Khi xong P0, các case này sẽ được chuyển thành test thật ở bước 10.

---

## Bước 1 — C1: `nonlocal ok`

**File:** `engine.py` (`crawl_users`)

Biến `ok` bị rebind trong closure `user_worker` nên banner luôn báo thành công.

- [x] 1.1 Thay `ok = True` bằng accumulator `state = {"ok": True}`
- [x] 1.2 Cập nhật 3 chỗ gán: dòng trong `user_worker`, trong `except CancelledError`, trong `except Exception`
- [x] 1.3 `_banner(state["ok"], ...)`
- [x] 1.4 Thêm test vào `test_v72.py`: mock `crawl_user` raise → `_banner` nhận `False`

**Bằng chứng:**

```
python audit_repro.py -> [C1] OK  (2/2 user lỗi, _banner nhận ok=[False])
python -m unittest test_v72.TestEngineBanner -> Ran 3 tests, OK
python -m unittest test_v72 -> Ran 55 tests, OK   (52 cũ + 3 mới)
```

Test mới phủ 3 tình huống: tất cả user lỗi, một user lỗi trong nhiều user,
và tất cả thành công — tránh trường hợp sửa quá tay thành luôn báo thất bại.

---

## Bước 2 — C2: `seen_hashes` chỉ ghi khi thành công

**File:** `downloader.py` (`dispatch`)

Hiện ghi path trước khi tải; lần xuất hiện thứ 2 của URL fail bị coi là "đã xử lý".

- [x] 2.1 Bỏ `seen_hashes[h] = save_path` khỏi vòng lặp
- [x] 2.2 Ghi qua `add_done_callback` chỉ khi kết quả `"OK"`
- [x] 2.3 Xử lý trường hợp hash đã có nhưng file không tồn tại → cho tải lại
- [x] 2.4 Test: 2 job cùng URL, job đầu fail → job sau phải có task

**Bằng chứng:**

```
python audit_repro.py -> [C2] OK  (lần 1 fail tạo 1 task, lần 2 tạo 1 task)
python -m unittest test_v72.TestDedupeWithinThread -> Ran 2 tests, OK
python -m unittest test_v72 -> Ran 57 tests, OK
```

Test thứ hai kiểm chiều ngược lại: khi lần đầu **thành công** thì lần hai phải
clone (0 task), không tải lại — tránh sửa quá tay thành luôn tải lại, làm mất
tác dụng khử trùng lặp.

**Ghi chú:** test đầu tiên tôi viết dùng 500 rồi 200 và nó fail — vì `500` nằm
trong nhánh retry nên `MAX_RETRIES` đã tiêu hết cả status 200 của lần sau. Đổi
sang `404` (lỗi vĩnh viễn, không retry) để test tất định và nhanh.

---

## Bước 3 — C3: phân loại TIMEOUT

**File:** `downloader.py` (`_fetch`, `counted`)

Timeout hiện trả `"CANCELLED"` → không đếm vào `failed`, không log.

- [x] 3.1 `_racing_stop` trả sentinel riêng thay vì `None` chung
- [x] 3.2 `_fetch` map sentinel → `"TIMEOUT"`
- [x] 3.3 `counted()` đếm `"TIMEOUT"` vào `failed`
- [x] 3.4 Log `[!]` cho mỗi timeout (gộp, tránh spam)
- [x] 3.5 Test: server chậm hơn `DOWNLOAD_TIMEOUT_MS` → `stats["failed"] == 1`

**Bằng chứng:**

```
python audit_repro.py -> [C3] OK  (stats failed=1, trước là failed=0)
python -m unittest test_v72.TestTimeoutIsNotSilence -> Ran 2 tests, OK
python -m unittest test_v72 -> Ran 59 tests, OK
```

**Ghi chú thiết kế:** dùng sentinel object `_TIMEOUT` thay vì chuỗi/`None`.
Ba trạng thái cần phân biệt là "có response", "bị người dùng dừng", "hết giờ" —
`None` chỉ mã hoá được hai. Test thứ hai kiểm riêng rằng timeout **không** bị
đếm nhầm sang `video`, vì đó là kiểu sửa quá tay làm báo cáo vẫn sai.

---

## Bước 4 — C4: trùng tên video/file

**File:** `downloader.py` (`plan_jobs`)

- [x] 4.1 Thêm `_{h[:6]}` vào nhánh video/file
- [x] 4.2 Test: 2 post cùng timestamp, video khác nhau → path khác nhau
- [x] 4.3 Test: `post_timestamp` fallback `00000000_000000` vẫn không đè

**Bằng chứng:**

```
python audit_repro.py -> 4/4 OK, exit=0  ("Tất cả 4 lỗi P0 đã được sửa")
python -m unittest test_v72.TestVideoNameCollision -> Ran 4 tests, OK
python -m unittest test_v72 -> Ran 63 tests, OK
```

Test thứ tư kiểm chiều ngược lại: **cùng** một URL phải ra **cùng** path, nếu
không `clone_cached` sẽ không trúng và app tải trùng thay vì tái sử dụng file.

### Kết quả P0

| Lỗi | Trước | Sau |
|---|---|---|
| C1 banner báo sai | `_banner(True)` khi mọi user lỗi | `_banner(False)` |
| C2 media mất im lặng | lần 2 tạo 0 task | tạo 1 task, tải lại |
| C3 timeout vô hình | `failed=0`, không log | `failed=1` + log `[!]` |
| C4 đè tên file | trùng path `True` | trùng path `False` |

Điểm ước tính: **64 → 78**.

---

## Bước 5 — H1: đổi tên `selectors.py`

**File:** `selectors.py` → `xf_selectors.py`, `xenforo_parse.py`, `downloader.py`

- [x] 5.1 `git mv selectors.py xf_selectors.py`
- [x] 5.2 Sửa `import selectors as S` ở 2 file
- [x] 5.3 Test: `import selectors` trả về module stdlib (`DefaultSelector` tồn tại)
- [x] 5.4 Test: `asyncio.SelectorEventLoop()` tạo được

**Bằng chứng:**

```
python -c "import selectors; print(selectors.__file__)"
  -> ...\Python310\lib\selectors.py     (trước: .\selectors.py)
python -c "import selectors; print(hasattr(selectors,'DefaultSelector'))"  -> True
python -c "import asyncio; asyncio.SelectorEventLoop()"                    -> OK
python -m unittest test_v72 -> Ran 67 tests, OK
```

Thực tế phải sửa **3 file** (kế hoạch ghi 2): `downloader.py`, `xenforo_parse.py`,
`test_v72.py`.

**Negative control** — kiểm rằng test thật sự bắt được lỗi:

```
Copy-Item xf_selectors.py selectors.py   -> FAILED (failures=2, errors=1)
Remove-Item selectors.py                 -> OK
```

Test chống trùng tên với danh sách module chuẩn (`selectors`, `types`, `queue`,
`code`, `copy`, ...) nên lần sau ai đặt tên file trùng sẽ bị chặn ngay.

---

## Bước 6 — H2: đổi theme giữa lúc quét

**File:** `v72.py`

- [x] 6.1 Tách `_apply_running_state()` — set trạng thái nút theo `current_loop`
- [x] 6.2 Gọi ở cuối `_build_ui()` và trong `_safe_change_buttons_state`
- [x] 6.3 Chuyển `_bind_keys()` vào cuối `_build_ui()` để phím tắt sống lại sau rebuild
- [x] 6.4 `toggle_theme` không reset `_had_error`/`_last_detail`/bộ đếm
- [x] 6.5 Test: toggle mid-scan → nút Quét vẫn disabled, Dừng vẫn normal, `Return` còn binding

**Bằng chứng:**

```
python -m unittest test_v72.TestThemeSwitchMidScan -> Ran 5 tests, OK
python -m unittest test_v72 -> Ran 72 tests, OK
```

Kiểm trực tiếp trên GUI thật (trước → sau):

```
mid-scan:            scan=disabled | stop=normal
AFTER theme switch:  scan=disabled | stop=normal     (trước khi sửa: normal | disabled)
   entry Return binding = CO    (trước: MAT)
   Ctrl+Return binding  = CO    (trước: MAT)
```

**Phát hiện thêm khi sửa:** `toggle_theme` còn **xoá sạch nội dung người dùng đã
gõ** — destroy widget là mất text trong ô Username, ô URL bài viết và ô lọc.
Đã lưu/khôi phục cả ba. Không có trong kế hoạch ban đầu, phát hiện lúc kiểm tra
thực tế.

**Ghi chú thiết kế:** `_is_running()` đọc `current_loop` thay vì màu/state của
nút. Nếu suy ra từ nút thì chính cái bug này sẽ tự tái sinh: hàm được gọi để
*sửa* trạng thái nút lại đang *đọc* trạng thái nút vừa bị reset.

---

## Bước 7 — H3: khoá chống chạy chồng

**File:** `v72.py` (`_launch`, `_focused_primary`)

- [x] 7.1 Guard đầu `_launch`: nếu loop đang chạy → log cảnh báo, return
- [x] 7.2 `_focused_primary` kiểm tra trạng thái trước khi gọi
- [x] 7.3 Test: gọi `_launch` 2 lần liên tiếp → chỉ 1 engine

**Bằng chứng:**

```
Ctrl+Enter khi đang quét            -> 0 engine khởi động
bấm Quét 1 User khi đang quét       -> 0
bấm Quét 1 Thớt khi đang quét       -> 0
bấm Cập nhật toàn bộ khi đang quét  -> 0
sau khi loop đóng, bấm lại          -> 1   (đúng, phải cho chạy)

python -m unittest test_v72.TestRunGuard -> Ran 4 tests, OK
python -m unittest test_v72 -> Ran 76 tests, OK
```

**Ghi chú thiết kế:** khoá đặt ở `_launch` chứ không chỉ ở trạng thái nút. Nút
disable chỉ chặn được đường bấm chuột; `_focused_primary` (Ctrl+Enter và phím
Enter ở ô nhập) gọi thẳng hàm start nên đi vòng qua. Đã kiểm cả 4 đường vào.

`start_update_all_thread` được kiểm **trước** khi `local_users.refresh()` — vì
refresh ghi vào SQLite, không nên chen vào giữa phiên đang đọc/ghi cùng DB.

**Phát hiện thêm:** test GUI để lại nhiễu Tcl (`invalid command name ..._safe_log`,
`application has been destroyed`) do `after(0)` còn treo lúc destroy root. Thêm
`root.update()` vào `tearDown` để xả hết callback — output test giờ sạch.

---

## Bước 8 — M4: `download_dir` tiêm qua constructor

**File:** `engine.py`, `v72.py`

Fallback sang `~/RPHANG` làm cache và media nằm hai nơi khác nhau.

- [x] 8.1 `CrawlerEngine.__init__` nhận `download_dir=None` (mặc định `config.DOWNLOAD_DIR`)
- [x] 8.2 `crawl_thread` dùng `self.download_dir`
- [x] 8.3 `v72.run_async_engine` truyền `self.download_dir`
- [x] 8.4 Test: fallback → cache và media cùng gốc

**Bằng chứng:**

```
mặc định              -> download_dir == config.DOWNLOAD_DIR   : True
khi fallback (tiêm)   -> C:\Users\test\RPHANG
cache và media cùng gốc: True
crawl_thread còn đọc config.DOWNLOAD_DIR? False
crawl_thread dùng self.download_dir?      True

python -m unittest test_v72.TestDownloadDirInjection -> Ran 4 tests, OK
python -m unittest test_v72 -> Ran 80 tests, OK
```

**Ghi chú:** test thứ ba chốt bằng `inspect.getsource` — nếu sau này ai thêm lại
`config.DOWNLOAD_DIR` vào `crawl_thread`, test fail ngay. Test thứ tư dựng đúng
kịch bản fallback (cache và media trong cùng thư mục tạm) và kiểm `thread_folder`
nằm dưới gốc đó.

---

## Bước 9 — M5: deadlock `TAB_SEM=1`

**File:** `engine.py` (`crawl_link`)

`crawl_link` giữ `tab_semaphore` rồi `crawl_thread` acquire lại.

- [x] 9.1 Bỏ `async with self.tab_semaphore` ở `crawl_link` (crawl_thread đã tự lo)
- [x] 9.2 Hoặc: `crawl_thread(..., already_locked=True)` để bỏ acquire lồng
- [x] 9.3 Clamp `TAB_SEM >= 1` và cảnh báo nếu < 2
- [x] 9.4 Test: `TAB_SEM=1`, `crawl_link` hoàn tất trong timeout

**Bằng chứng:**

```
TAB_SEM=1 -> crawl_link HOAN TAT (khong deadlock)
config._clamp(0)=1 | _clamp(-5)=1 | _clamp('x')=1

python -m unittest test_v72.TestTabSemaphoreNesting -> Ran 3 tests, OK
python -m unittest test_v72 -> Ran 83 tests, OK
```

**Negative control** — chạy đúng kịch bản test trên engine của commit trước khi sửa:

```
OLD engine (b04aa01) TAB_SEM=1 -> DEADLOCK  <-- test mới bắt được lỗi này
```

**Cách sửa:** chọn 9.1 — thu hẹp phạm vi `async with self.tab_semaphore` xuống
chỉ còn khối dò tác giả, đưa `crawl_thread(...)` ra ngoài (nó tự acquire). Đơn
giản hơn 9.2 vì không phải thêm tham số và không có hai đường code khác nhau.

Kèm `config._clamp()` cho cả 4 semaphore: `Semaphore(0)` là khoá chết ngay từ
đầu, giá trị âm thì asyncio ném `ValueError` lúc khởi tạo.

---

## Bước 10 — M3: test hermetic

**File:** `test_v72.py`

3 test mở `crawler_cache.db` trong thư mục tải thật.

- [x] 10.1 `setUpModule`: đặt `config.DOWNLOAD_DIR` + `os.environ["RPHANG_DIR"]` về temp
- [x] 10.2 `tearDownModule`: dọn temp
- [x] 10.3 Chuyển 4 case của `audit_repro.py` thành test thật
- [x] 10.4 Test chạy được khi `E:\` không tồn tại (mô phỏng CI)

**Bằng chứng:**

```
Xác nhận lỗi trước khi sửa: crawler_cache.db production bị sửa lúc 03:45:24
  (chính là lần chạy test ngay trước đó)

Sau khi sửa:
  tồn tại: True | size: 442368
  mtime trước: 1793825124.7247849
  mtime sau  : 1793825124.7247849
  BỊ GHI BỞI TEST? False
  temp dir sót lại: 0

python -m unittest test_v72.TestSuiteIsHermetic -> Ran 3 tests, OK
python -m unittest test_v72 -> Ran 86 tests, OK
```

**Negative control** (vô hiệu `setUpModule` để mô phỏng trạng thái cũ):

```
failures: 3 -> test phát hiện được việc test chạm vào thư mục thật
```

**Hai điều chỉnh so với kế hoạch:**

1. **10.3 hoãn.** Bốn case của `audit_repro.py` đã được phủ bằng test thật rồi
   (C1→`TestEngineBanner`, C2→`TestDedupeWithinThread`, C3→`TestTimeoutIsNotSilence`,
   C4→`TestVideoNameCollision`). Chuyển thêm sẽ tạo test trùng, không thêm giá trị.

2. **Sửa thêm một lỗi phát sinh:** `tearDownModule` gọi `rmtree(ignore_errors=True)`
   nhưng `MediaCache` chưa `close()` nên Windows khoá file → thư mục tạm ở lại mãi.
   Đã đóng cache trong `finally` của cả 3 test dựng app, và thêm retry + `gc.collect()`
   trong `tearDownModule`. Kiểm lại: `temp dir sót lại: 0`.

---

## Bước 11 — M1 + M6: race thật & bounded queue

**File:** `downloader.py`, `engine.py`

- [x] 11.1 `_racing_stop` dùng `asyncio.wait(FIRST_COMPLETED)` + task stop-waiter, bỏ vòng poll 50ms
- [x] 11.2 `crawl_user` dùng `asyncio.Queue` + N worker thay `gather` toàn bộ
- [x] 11.3 `crawl_thread` giới hạn `pending` (flush khi vượt ngưỡng)
- [x] 11.4 Đo: số wakeup/giây giảm, RAM ổn định với box lớn

**Bằng chứng — đo trên code thật, so với commit trước khi sửa:**

```
M1: số lần gọi asyncio.wait trong MỘT lần _racing_stop (hạn 1000ms)
  code cu : 21 lan   (poll moi 50ms)
  code moi:  1 lan   (race that)

  Với DOWNLOAD_TIMEOUT_MS=40000 và 10 file song song:
  code cu : 800 x 10 = 8.000 lan danh thuc
  code moi:   1 x 10 =    10 lan          -> giam 800 lan

M1: độ chính xác timeout
  budget= 300ms -> thoi gian thuc 296ms
  budget=1000ms -> thoi gian thuc 1006ms   (khong con tre 50ms)

M6: số task đồng thời, mô phỏng 300 đơn vị việc
  code cu (gather tat ca) : dinh 300 task song cung luc
  code moi (co drain)     : dinh  79 task  -> giam 3.8 lan
  PENDING_LIMIT = 80

python -m unittest test_v72.TestNoBusyPoll test_v72.TestPendingIsBounded -> Ran 6 tests, OK
python -m unittest test_v72 -> Ran 92 tests, OK
```

**Phép đo đầu tiên của tôi bị sai:** dùng một ticker 5ms để đếm "số lần event
loop thức" — nhưng chính ticker đó tạo 64 lần thức/giây nên che mất khác biệt
(64 vs 64, "giảm 1.0 lần"). Đo lại bằng cách đếm trực tiếp số lần gọi
`asyncio.wait`, mới ra 21 vs 1. Ghi lại vì đây là bẫy dễ mắc: đo nhiễu của
chính dụng cụ đo.

**Ghi chú thiết kế:** `_stop_waiter` vẫn poll 0.25s thay vì `asyncio.sleep(vô
hạn)`. Sleep vô hạn giữ timer trong loop và làm chậm shutdown; 4 lần/giây chỉ
để kiểm một cờ là không đáng kể, so với 20 lần/giây cũ cho mỗi file. Nếu sau này
`stop_event` đổi sang `asyncio.Event` thì bỏ hẳn được vòng poll.

---

## Bước 12 — H4: streaming download

**File:** `downloader.py`

- [ ] 12.1 Ghi theo chunk thay `response.body()` — **KHÔNG KHẢ THI, xem dưới**
- [x] 12.2 Thêm `MAX_FILE_MB` vào `config.py`, cắt khi vượt
- [x] 12.3 Kiểm `Content-Length` khớp bytes ghi
- [x] 12.4 Test: file giả 50MB → RSS không tăng tương ứng
- [x] 12.5 Ghi nhận giới hạn của Playwright bằng test (chống tái phát giả định)

**Kế hoạch sai ở điểm 12.1.** Kế hoạch ban đầu giả định Playwright có API
streaming. Kiểm thực tế:

```
APIResponse methods: ['body','dispose','headers','headers_array','json','ok',
                      'on','once','remove_listener','status','status_text','text','url']
APIRequestContext.get: (..., max_retries, ...) -> APIResponse
thuộc tính stream/chunk: []
=> body() nạp TOÀN BỘ payload; không có cách đọc theo chunk
```

Vậy **không thể** streaming qua `context.request`. Hai lựa chọn thật sự:

| Cách | Đánh đổi |
|---|---|
| Giữ `context.request` | Không stream được, nhưng dùng chung cookie/session/CDP |
| Chuyển sang `aiohttp`/`httpx` | Stream được, nhưng mất cookie phiên XenForo và Referer/tls của trình duyệt — media cần đăng nhập sẽ 403 |

Chọn **giữ `context.request`** và làm hai chốt khả thi thay thế.

**Bằng chứng:**

```
file 600MB > MAX_FILE_MB=512:
   ok=0 failed=1 | file tạo ra? False
   log: [!] Bỏ qua tệp > 512MB (600MB)
   (body() KHÔNG bị gọi — assert trong test chứng minh)

content-length 1000 nhưng chỉ nhận 400:
   ok=0 failed=1 | file tạo ra? False
   log: [!] Nhận thiếu dữ liệu (400/1000 byte)

file bình thường 400 byte: ok=1 | file tạo ra? True
thiếu content-length (chunked):  ok=1  (không chặn mù)

python -m unittest test_v72.TestDownloadIntegrityGuards -> Ran 6 tests, OK
python -m unittest test_v72 -> Ran 98 tests, OK
```

**Rủi ro còn lại (ghi lại, không giấu):** file lớn hơn `MAX_FILE_MB` mà server
**không** gửi `content-length` vẫn được nạp trọn vào RAM. Đây là giới hạn của
thư viện, không phải của code này. Nếu cần xử lý triệt để thì phải đổi đường tải
sang HTTP client riêng và tự quản lý cookie — đó là thay đổi kiến trúc, không
phải một bước sửa lỗi.

Test `test_playwright_has_no_streaming_api` sẽ **fail** nếu sau này Playwright
thêm streaming — lúc đó hãy làm lại 12.1 cho đúng.

---

## Bước 13 — N1/N2/N3: tài liệu & backoff

- [ ] 13.1 `COCOC_PATH`: implement thật (đọc `os.environ`) hoặc bỏ khỏi thông báo
- [ ] 13.2 Backoff có jitter: `base * 2**attempt + random.uniform(0, 1)`
- [ ] 13.3 `extract_post_media` → nêu rõ là mutating, hoặc copy soup
- [ ] 13.4 Kiểm dung lượng đĩa trước khi tải
- [ ] 13.5 Cập nhật README khớp hành vi mới

**Bằng chứng:** README diff

---

## Nhật ký thực hiện

| Ngày | Bước | Kết quả | Ghi chú |
|---|---|---|---|
| 2026-11-05 | — | Đánh giá hoàn tất | 64/100, 4 lỗi P0 đã kiểm chứng |
| 2026-11-05 | 0 | Baseline chốt | 52 test OK; `audit_repro.py` báo 4/4 lỗi; thêm `requirements.txt` |
| 2026-11-05 | 1 | C1 xong | `state{"ok"}` thay closure rebind; +3 test → 55 |
| 2026-11-05 | 2 | C2 xong | `seen_hashes` chỉ ghi khi OK; +2 test → 57 |
| 2026-11-05 | 3 | C3 xong | sentinel `_TIMEOUT`; +2 test → 59 |
| 2026-11-05 | 4 | C4 xong | hash vào tên video/file; +4 test → 63. **Hết P0** |
| 2026-11-05 | 5 | H1 xong | `selectors.py` → `xf_selectors.py`; +4 test → 67 |
| 2026-11-05 | 6 | H2 xong | `_apply_running_state`, bind lại phím, giữ input; +5 test → 72 |
| 2026-11-05 | 7 | H3 xong | khoá ở `_launch`, chặn 4 đường vào; +4 test → 76 |
| 2026-11-05 | 8 | M4 xong | tiêm `download_dir`; +4 test → 80 |
| 2026-11-05 | 9 | M5 xong | bỏ acquire lồng + clamp semaphore; +3 test → 83. **Hết P1** |

## Trạng thái kiểm chứng cuối (sau bước 9)

```
python audit_repro.py      -> Tất cả 4 lỗi P0 đã được sửa.        (exit 0)
python -m unittest test_v72 -> Ran 83 tests, OK
python _check_palette.py    -> Tat ca cap dat WCAG 2.2 AA.        (exit 0)
python -c "import selectors, asyncio" -> default selectors OK
```

## Việc còn lại

| Bước | Nội dung | Ưu tiên |
|---|---|---|
| 10 | M3 — test hermetic | P3 |
| 11 | M1+M6 — race thật & bounded queue | P2 |
| 12 | H4 — streaming download | P2 |
| 13 | N1/N2/N3 — tài liệu, backoff, giới hạn dung lượng | P3 |
