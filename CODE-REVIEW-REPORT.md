# Code Review Report — XenForo Crawler V72

> **Thời điểm review:** 2026-11-08  
> **Phạm vi:** Toàn bộ codebase (~2,100 LOC Python)  
> **Phương pháp:** Multi-axis review theo skill `code-review-and-quality` (5 trục: Correctness, Readability, Architecture, Security, Performance)  
> **Baseline:** Đánh giá trước đó (DANH-GIA-CODEBASE.md) đã sửa P0-P3, điểm 64 → 88

> **CẬP NHẬT 2026-11-08 (đợt sửa):** đã sửa **BUG-1 (M2)**, **BUG-2 (H4 phần
> dư)** và **SEC-1** theo khuyến nghị, kèm 10 test hồi quy mới trong
> [test_review_round3.py](test_review_round3.py). Các mục bên dưới giữ nguyên
> mô tả lỗi gốc làm hồ sơ; dấu ✅ đánh dấu mục đã xử lý. Chi tiết bằng chứng
> từng bước xem mục "Đợt 3" trong [KE-HOACH-SUA-LOI.md](KE-HOACH-SUA-LOI.md).

---

## Tóm tắt

| Trục | Điểm | Nhận xét chính |
|------|------|----------------|
| Correctness | 7/10 | Còn 2 lỗi confirmed (M2, H4), 1 lỗi tiềm ẩn |
| Readability | 9/10 | Docstring xuất sắc, naming rõ ràng |
| Architecture | 8.5/10 | Phân tầng sạch, nhưng có coupling ngầm |
| Security | 8/10 | Cookie handling tốt, thiếu input validation ở một số chỗ |
| Performance | 7.5/10 | Streaming download đã fix, nhưng RAM vẫn có thể phình |

**Điểm tổng: 80/100 — B+** (giảm nhẹ so với 88 do phát hiện thêm vấn đề)

---

## Lỗi còn tồn tại (Confirmed Bugs)

### ✅ BUG-1: Bộ đếm thống kê ghi đè thay vì cộng dồn (M2 - ĐÃ SỬA)

**File:** `v72.py`, hàm `_track_stats` (dòng 651-683)

**Vấn đề:** 
```python
m = re.search(r"(\d+)\s+ảnh", message)
if m:
    self._n_image = int(m.group(1))  # ← GÁN, không phải CỘNG
```

Khi nhiều thread báo cáo kết quả:
- Thread 1: "8 ảnh và 2 video" → `_n_image = 8`
- Thread 2: "1 ảnh" → `_n_image = 1` (ghi đè!)
- UI hiển thị: "1 ảnh" thay vì "9 ảnh"

**Severity:** Required (ảnh hưởng trực tiếp đến UX, người dùng thấy sai số liệu)

**Đã sửa (2026-11-08):** 4 phép gán `=` → `+=` trong `_track_stats` (v72.py),
khớp semantics mà bản PySide6 (`ui/worker.py:log_bridge`) đã dùng từ trước.
Counter reset mỗi phiên đã có sẵn ở `_launch()` (v72.py:937) — cả hai khoá
chặt bằng test `test_launch_resets_counters`. Kiểm chứng:
`test_review_round3.py` → `test_second_thread_does_not_erase_first`
(8 ảnh + 1 ảnh = 9, không phải 1).

---

### ✅ BUG-2: Nạp nguyên file vào RAM ở đường browser fallback (H4 - ĐÃ SỬA PHẦN DƯ)

**File:** `downloader.py`, hàm `_fetch_browser` (dòng 454)

**Vấn đề:**
```python
body = await response.body()  # ← Nạp TOÀN BỘ file vào RAM
```

Đường HTTP streaming (`_fetch_streaming`) đã fix, nhưng khi HTTP thất bại và rơi về Playwright browser, code vẫn dùng `response.body()` nạp toàn bộ payload. Với `DOWNLOAD_SEM=10` và video 100MB+, RAM có thể phình 1GB+.

**Severity:** Optional (chỉ xảy ra khi HTTP-first thất bại, nhưng vẫn là rủi ro)

**Context từ code comment (dòng 296-306):**
> "Playwright 1.54 KHÔNG có API streaming cho context.request — body() nạp toàn bộ payload vào RAM."

**Đã sửa (2026-11-08):** `_too_big()` vốn đã chặn TRƯỚC `body()` dựa trên
content-length — nhưng server dùng chunked (không header) thì lưới đó là mù
và file 2 GB vẫn được ghi đủ xuống đĩa dù MAX_FILE_MB=512. Đã thêm lưới
SAU `body()`: `len(body) > limit` → log + `"FAILED"`, không ghi file. Phần
RAM spike trong lúc `body()` nạp không tránh được với Playwright 1.54 — đã
document rõ trong comment. Kiểm chứng: `test_chunked_oversize_body_is_rejected`
(body 2 MB, trần 1 MB → FAILED, không có file) + `test_small_body_still_saved`
(chống chặn nhầm).

---

### 🟡 BUG-3: Race condition tiềm ẩn trong `_remember_when_ok` callback

**File:** `downloader.py`, dòng 229-245

**Vấn đề:**
```python
def _remember_when_ok(self, h, save_path, seen_hashes):
    def _cb(fut):
        if fut.cancelled():
            return
        try:
            if fut.result() == "OK" and os.path.exists(save_path):
                seen_hashes[h] = save_path  # ← Mutate dict từ callback
        except Exception:
            pass
    return _cb
```

Callback này chạy khi task hoàn thành, mutate `seen_hashes` dict. Nếu nhiều task cùng hoàn thành gần như đồng thời và truy cập cùng key `h`, có thể xảy ra race condition nhỏ (dict assignment không atomic trong Python).

**Severity:** Nit (xác suất thấp vì hash collision hiếm, nhưng vẫn là design smell)

**Fix đề xuất:** Không cần fix ngay, nhưng nên document rằng `seen_hashes` chỉ được mutate từ callback sau khi task xong, không từ luồng chính.

---

## Vấn đề Architecture

### ARCH-1: Coupling ngầm giữa `v72.py` và log format của engine

**File:** `v72.py:_track_stats` phụ thuộc vào format string từ `downloader.count_files()`

`_track_stats` bóc số liệu bằng regex từ chuỗi log tiếng Việt ("8 ảnh và 2 video"). Nếu ai đó đổi format trong `count_files()`, stats sẽ im lặng hỏng.

**Fix đề xuất:** Engine nên trả structured data (dict) thay vì chỉ in log. GUI đọc từ dict, không parse string.

---

### ARCH-2: Global state trong `config.py`

**File:** `config.py`

Tất cả cấu hình là module-level variables. Khi test hoặc chạy nhiều instance, không thể isolate config.

**Severity:** Nit (acceptable cho tool cá nhân, nhưng sẽ thành vấn đề nếu scale)

---

## Vấn đề Security

### ✅ SEC-1: Không validate URL scheme trước khi fetch — ĐÃ SỬA

**File:** `engine.py:fetch_soup`, `downloader.py:_fetch_streaming`

**Vấn đề gốc:** URL bóc từ HTML diễn đàn (dữ liệu ngoài) qua `urljoin` vẫn
giữ scheme tuyệt đối — `urllib.request.urlopen` hỗ trợ sẵn `file://`, nên
một post chứa `<img src="file:///C:/...">` đọc file local rồi ghi vào thư
mục tải. (Parser đã lọc `data:` URI từ tầng extraction, nhưng không lọc
các scheme khác.)

**Đã sửa (2026-11-08):** thêm `ALLOWED_SCHEMES` + `scheme_ok()` trong
`fast_fetch.py`, chặn ở MỘT chỗ tầng HTTP — cả `fetch_one` (HTML) lẫn
`download_to_file` (media) đều được che. Đường Playwright không cần vì
APIRequestContext chỉ nhận http/https sẵn. `_fetch_streaming` fast-fail
cho URL rác (không ngủ backoff 3 lần). Kiểm chứng:
`test_fetch_one_rejects_file_url`, `test_download_to_file_rejects_file_url`
(file local KHÔNG bị sao chép), `test_streaming_fails_fast_on_scheme`
(< 1 giây).

---

### SEC-2: Cookie header logged (potential leak)

**File:** `engine.py:load_cookies` (dòng 331)

```python
self.log(f"[*] Đã lấy {len(pairs)} cookie từ phiên đang mở "
         f"(dùng cho tải nhanh, không lộ giá trị).", "system")
```

Comment nói "không lộ giá trị" nhưng nếu ai đó sửa code và log `pairs` thay vì `len(pairs)`, cookie sẽ bị lộ. Nên dùng constant hoặc assert.

**Severity:** Nit (hiện tại an toàn, nhưng fragile)

---

## Vấn đề Performance

### PERF-1: `_stop_waiter` poll mỗi 0.25s

**File:** `downloader.py:284-292`

```python
async def _stop_waiter(self):
    while not self.stop_event.is_set():
        await asyncio.sleep(0.25)
```

Poll 4 lần/giây là acceptable, nhưng có thể optimize bằng `asyncio.Event` thay vì polling:

```python
# Trong __init__:
self._stop_async_event = asyncio.Event()

# Wrapper để sync threading.Event → asyncio.Event:
def _sync_stop_event(self):
    if self.stop_event.is_set():
        self._stop_async_event.set()
```

**Severity:** Nit (hiệu năng hiện tại đủ tốt)

---

## Điểm mạnh (Giữ nguyên từ đánh giá trước)

1. **Ranh giới tầng thực sự sạch** — `xenforo_parse.py` là hàm thuần
2. **Văn hoá "sửa lỗi kèm giải thích nguyên nhân"** — docstring ghi rõ bug cũ
3. **Accessibility được tự động hoá** — `_check_palette.py` kiểm WCAG AA
4. **Ghi file nguyên tử + chống rò connection** — `tmp_path` → `os.replace()`
5. **Chống lặp vô hạn ở cả 2 tầng** — visited set cho box và thread
6. **Nút Dừng thực sự cắt được** — `_racing_stop` đua cờ dừng

---

## Khuyến nghị ưu tiên sửa

| Ưu tiên | Bug | Effort | Impact | Trạng thái |
|---------|-----|--------|--------|------------|
| **P0** | BUG-1 (stats ghi đè) | ~10 dòng | Cao (UX sai) | ✅ đã sửa |
| **P1** | BUG-2 (RAM browser fallback) | ~15 dòng | Trung bình | ✅ đã sửa (lưới sau body) |
| **P2** | SEC-1 (validate URL scheme) | ~20 dòng | Thấp (tool nội bộ) | ✅ đã sửa |
| **P3** | ARCH-1 (structured stats) | ~50 dòng | Medium-term | ⏳ để hở — cần refactor engine trả stats qua callback, tách khỏi đợt vá lỗi này |

---

## Phát hiện thêm trong lúc verify (ngoài phạm vi review, chưa sửa)

### ENV-1: `test_theme_switch_and_persistence` fail dưới DSH sandbox — lỗi môi trường, không phải regression

**Chứng minh đầy đủ trong `repro_theme.py`:**

1. `~/.xenforo_theme` đang chứa `"dark"` (từ lần chạy app/test ngoài sandbox trước đó).
2. Dưới sandbox, ghi ra `~` bị chặn → `_theme_file_path()` (append-open để dò đường ghi được) rơi về `.xenforo_theme` trong CWD → **save ghi CWD, load đọc HOME** — split-brain cùng kiểu M4 cũ.
3. Chạy với HOME sạch (redirect `USERPROFILE` sang thư mục trống) → test **PASS**.
4. Theme code không đổi so với HEAD (diff chỉ 1 dòng import), và 3 fix đợt này không chạm đường theme.

**Đề xuất sửa khi có dịp:** hoặc làm test hermetic (redirect theme path trong setUp), hoặc thống nhất `load`/`save` cùng một cơ chế chọn file — hiện load luôn ưu tiên HOME còn save chọn "nơi ghi được đầu tiên".

---

## Kết luận

Codebase **vẫn ở mức trên trung bình rõ rệt** so với tool crawler cùng loại. Các lỗi P0-P3 từ đánh giá trước đã được sửa đúng cách, có test coverage.

**Đợt sửa 2026-11-08** đã đóng 3 mục khuyến nghị (BUG-1, BUG-2, SEC-1):

```
python -m unittest test_v72                                          -> Ran 154 tests, OK
python -m unittest test_review_round3 test_review_round2 \
                   test_review_fixes test_critical_fixes             -> Ran 73 tests, OK
python -m unittest test_gui_fluent test_first_login \
                   test_persistent_mode                              -> 55/56 OK;
   1 fail = ENV-1 (theme, lỗi môi trường sandbox, chứng minh ở trên —
   pass khi HOME sạch, không liên quan thay đổi đợt này)
```

10 test hồi quy mới trong [test_review_round3.py](test_review_round3.py)
khoá chặt cả ba fix + hành vi reset counter mỗi phiên.

**Còn mở:** ARCH-1 (structured stats thay bóc regex — cần refactor engine)
và ENV-1 (theme split-brain dưới home read-only).

---

## Files reviewed

- `engine.py` (822 lines) ✅
- `downloader.py` (624 lines) ✅
- `config.py` (208 lines) ✅
- `cache.py` (238 lines) ✅
- `v72.py` (1040 lines, partial) ✅
- `xf_selectors.py` (referenced) ✅
