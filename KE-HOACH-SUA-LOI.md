# Kế hoạch sửa lỗi — XenForo Crawler V72

> Nguồn: [DANH-GIA-CODEBASE.md](DANH-GIA-CODEBASE.md)
> Quy tắc làm việc: **mỗi bước một commit**, chạy `python audit_repro.py` + `python -m unittest test_v72`
> trước và sau khi sửa. Chỉ tick khi có bằng chứng cụ thể ở cột "Bằng chứng".

**Điểm hiện tại: 64/100.** Mục tiêu: P0 → 78, P0+P1 → 85.

---

## Bảng tiến độ

| Bước | Nội dung | Mức | Ưu tiên | Trạng thái |
|---|---|---|---|---|
| 0 | Baseline & khung kiểm chứng | — | Bắt buộc | [x] |
| 1 | C1 — `nonlocal ok` | 🔴 | P0 | [x] |
| 2 | C2 — `seen_hashes` chỉ ghi khi thành công | 🔴 | P0 | [x] |
| 3 | C3 — phân loại TIMEOUT | 🔴 | P0 | [x] |
| 4 | C4 — trùng tên video/file | 🔴 | P0 | [ ] |
| 5 | H1 — đổi tên `selectors.py` | 🟠 | P1 | [ ] |
| 6 | H2 — đổi theme giữa lúc quét | 🟠 | P1 | [ ] |
| 7 | H3 — khoá chống chạy chồng | 🟠 | P1 | [ ] |
| 8 | M4 — `download_dir` tiêm qua constructor | 🟡 | P1 | [ ] |
| 9 | M5 — deadlock `TAB_SEM=1` | 🟡 | P1 | [ ] |
| 10 | M3 — test hermetic | 🟡 | P3 | [ ] |
| 11 | M1+M6 — race thật & bounded queue | 🟡 | P2 | [ ] |
| 12 | H4 — streaming download | 🟠 | P2 | [ ] |
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

- [ ] 4.1 Thêm `_{h[:6]}` vào nhánh video/file
- [ ] 4.2 Test: 2 post cùng timestamp, video khác nhau → path khác nhau
- [ ] 4.3 Test: `post_timestamp` fallback `00000000_000000` vẫn không đè

**Bằng chứng:** `audit_repro.py` → `c4 ... OK`

---

## Bước 5 — H1: đổi tên `selectors.py`

**File:** `selectors.py` → `xf_selectors.py`, `xenforo_parse.py`, `downloader.py`

- [ ] 5.1 `git mv selectors.py xf_selectors.py`
- [ ] 5.2 Sửa `import selectors as S` ở 2 file
- [ ] 5.3 Test: `import selectors` trả về module stdlib (`DefaultSelector` tồn tại)
- [ ] 5.4 Test: `asyncio.SelectorEventLoop()` tạo được

**Bằng chứng:** `python -c "import selectors; print(selectors.__file__)"` → đường dẫn stdlib

---

## Bước 6 — H2: đổi theme giữa lúc quét

**File:** `v72.py`

- [ ] 6.1 Tách `_apply_running_state()` — set trạng thái nút theo `current_loop`
- [ ] 6.2 Gọi ở cuối `_build_ui()` và trong `_safe_change_buttons_state`
- [ ] 6.3 Chuyển `_bind_keys()` vào cuối `_build_ui()` để phím tắt sống lại sau rebuild
- [ ] 6.4 `toggle_theme` không reset `_had_error`/`_last_detail`/bộ đếm
- [ ] 6.5 Test: toggle mid-scan → nút Quét vẫn disabled, Dừng vẫn normal, `Return` còn binding

**Bằng chứng:** test 6.5 xanh

---

## Bước 7 — H3: khoá chống chạy chồng

**File:** `v72.py` (`_launch`, `_focused_primary`)

- [ ] 7.1 Guard đầu `_launch`: nếu loop đang chạy → log cảnh báo, return
- [ ] 7.2 `_focused_primary` kiểm tra trạng thái trước khi gọi
- [ ] 7.3 Test: gọi `_launch` 2 lần liên tiếp → chỉ 1 engine

**Bằng chứng:** test 7.3 xanh

---

## Bước 8 — M4: `download_dir` tiêm qua constructor

**File:** `engine.py`, `v72.py`

Fallback sang `~/RPHANG` làm cache và media nằm hai nơi khác nhau.

- [ ] 8.1 `CrawlerEngine.__init__` nhận `download_dir=None` (mặc định `config.DOWNLOAD_DIR`)
- [ ] 8.2 `crawl_thread` dùng `self.download_dir`
- [ ] 8.3 `v72.run_async_engine` truyền `self.download_dir`
- [ ] 8.4 Test: fallback → cache và media cùng gốc

**Bằng chứng:** test 8.4 xanh

---

## Bước 9 — M5: deadlock `TAB_SEM=1`

**File:** `engine.py` (`crawl_link`)

`crawl_link` giữ `tab_semaphore` rồi `crawl_thread` acquire lại.

- [ ] 9.1 Bỏ `async with self.tab_semaphore` ở `crawl_link` (crawl_thread đã tự lo)
- [ ] 9.2 Hoặc: `crawl_thread(..., already_locked=True)` để bỏ acquire lồng
- [ ] 9.3 Clamp `TAB_SEM >= 1` và cảnh báo nếu < 2
- [ ] 9.4 Test: `TAB_SEM=1`, `crawl_link` hoàn tất trong timeout

**Bằng chứng:** test 9.4 xanh

---

## Bước 10 — M3: test hermetic

**File:** `test_v72.py`

3 test mở `crawler_cache.db` trong thư mục tải thật.

- [ ] 10.1 `setUpModule`: đặt `config.DOWNLOAD_DIR` + `os.environ["RPHANG_DIR"]` về temp
- [ ] 10.2 `tearDownModule`: dọn temp
- [ ] 10.3 Chuyển 4 case của `audit_repro.py` thành test thật
- [ ] 10.4 Test chạy được khi `E:\` không tồn tại (mô phỏng CI)

**Bằng chứng:** suite xanh trong môi trường không có `E:\`

---

## Bước 11 — M1 + M6: race thật & bounded queue

**File:** `downloader.py`, `engine.py`

- [ ] 11.1 `_racing_stop` dùng `asyncio.wait(FIRST_COMPLETED)` + task stop-waiter, bỏ vòng poll 50ms
- [ ] 11.2 `crawl_user` dùng `asyncio.Queue` + N worker thay `gather` toàn bộ
- [ ] 11.3 `crawl_thread` giới hạn `pending` (flush khi vượt ngưỡng)
- [ ] 11.4 Đo: số wakeup/giây giảm, RAM ổn định với box lớn

**Bằng chứng:** benchmark trước/sau

---

## Bước 12 — H4: streaming download

**File:** `downloader.py`

- [ ] 12.1 Ghi theo chunk thay `response.body()`
- [ ] 12.2 Thêm `MAX_FILE_MB` vào `config.py`, cắt khi vượt
- [ ] 12.3 Kiểm `Content-Length` khớp bytes ghi
- [ ] 12.4 Test: file giả 50MB → RSS không tăng tương ứng

**Bằng chứng:** số đo RSS

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
