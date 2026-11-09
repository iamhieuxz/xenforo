# Đề xuất cải tiến — XenForo Crawler

> Ngày lập: 2026-11-06
> Căn cứ: review đợt 2 (commit `9ba7da0`), 243 test, 18 script probe
> Mỗi mục đều kèm **bằng chứng đo được**, không phải cảm nhận.

---

## Bảng tổng hợp

| Ưu tiên | Việc | Trạng thái | Ảnh hưởng |
|---|---|---|---|
| **P0** | 5 lỗi nghiêm trọng | ✅ Xong | Mất toàn bộ media, mất thông báo |
| **P1** | Dọn 13,52 GB trùng lặp | ✅ Script xong, chờ duyệt xoá | Ổ đĩa |
| **P1** | Hash theo nội dung | ✅ Xong | Ngăn trùng lặp mới |
| **P1** | Xoá `v72.py` (code chết) | ⚠️ **Đề xuất sai** — xem P1.3 | — |
| **P2** | Tách `gui_fluent.py` | ✅ Xong | 1507 → 6 file, dài nhất 595 dòng |
| **P2** | Tách `test_v72.py` | ✅ Xong | 2388 → 6 file, 154 test giữ nguyên |
| **P2** | Giảm `except: pass` | ✅ 76 → 67, 11 chỗ nguy hiểm có `swallow()` | Nguồn lỗi 1+2 |
| **P2** | Gộp biến cấu hình trình duyệt | ✅ Xong | `BROWSER` duy nhất, 2 biến cũ là alias |
| **P2** | Vá lỗi `QApplication` ở nút Sao chép | ✅ Xong | 3 test hồi quy + negative control |
| **P3** | Chuyển sang `logging` chuẩn | ⬜ | Bảo trì |
| **P3** | `pyproject.toml` + `ruff` | ⬜ | Bắt lỗi sớm |

---

## P0 — Đã hoàn tất

### Lỗi 1 (nặng nhất): `_cookie_header` chưa khởi tạo

**Triệu chứng đo được:**

```
AttributeError: 'Downloader' object has no attribute '_cookie_header'
dispatch 2 task
gather trả về: {'ok': 0, 'failed': 0, 'image': 0, ...}
lỗi trong callback: 2
```

App báo **"0 mới, 0 lỗi"** trong khi **không file nào được tải**.

**Nguyên nhân chuỗi (3 tầng, phải sửa cả 3):**

1. `Downloader.__init__` thiếu `self._cookie_header = ""` → `_fetch_streaming` đọc thuộc tính không tồn tại
2. `_fetch` gọi `_fetch_streaming` **không bọc `try`** → `AttributeError` lan ra task
3. `counted()` gọi `fut.result()` **không bọc `try`** → exception bị asyncio nuốt, `state["failed"]` không tăng

**Đã sửa:** khởi tạo ở `__init__`, bọc `try` ở `_fetch`, bọc `try` ở `counted()` + ghi vào `_task_errors`, và `_report_thread` in ra log.

**Kiểm chứng lại:** `{'ok': 2, 'failed': 0}` với file 501 KB + 21 KB tải thật.

> Đây chính là nguồn "7 lỗi" người dùng thấy — không phải 7 lỗi riêng lẻ, mà một lỗi lặp 7 lần.

### Lỗi 2: `QTimer.singleShot` từ worker thread không bao giờ chạy

**Đo được:**

```
main thread   -> fired=1  OK
worker thread -> fired=0  KHÔNG CHẠY
```

3 chỗ trong `gui_fluent.py` mắc lỗi. Hệ quả: thông báo "đã mở trình duyệt", "khởi động thất bại", log từ thread — **tất cả biến mất im lặng**.

**Đã sửa:** thay bằng `Signal` (`sig_ui_notify`, `sig_ui_login_opened`, `sig_ui_log`). Qt tự dùng QueuedConnection khi phát từ thread khác, handler chạy trên GUI thread.

**Kiểm chứng:** thông báo lỗi hiện ra (trước: 0).

### Lỗi 3: `NameError` khi mở trình duyệt thất bại

```python
except Exception as e:
    QTimer.singleShot(0, lambda: InfoBar.error(content=f"{e}"))
```

Python 3 **xoá biến `e`** sau block `except`:

```
>>> NameError: name 'e' is not defined
```

Đúng lúc cần báo lỗi nhất thì app crash thêm. **Đã sửa:** tính chuỗi `msg` ngay trong `except`.

### Lỗi 4: Nút Đăng nhập mở sai trình duyệt

```
mode=cdp      → dùng coccoc + profile thật (783 cookie, có xf_user)
nút Đăng nhập → mở chrome + profile TẠM F:\XENFORO2\tmp...
```

Đăng nhập xong cookie ghi vào chỗ khác nên lần quét sau vẫn không thấy phiên. **Đã sửa:** rẽ nhánh theo `BROWSER_MODE`.

### Lỗi 5: Lỗi task không được báo

`_task_errors` được thu thập nhưng `_report_thread` không dùng. **Đã sửa:** in ra log.

### Kèm theo: ghi nhật ký ra file

Bản trước chỉ giữ log trong RAM — đóng app là mất. Đó là lý do khi người dùng báo "7 lỗi" thì không có gì để đọc lại.

`session_log.py` + `check_log.py`:

```
<thư mục tải>/logs/session-YYYYMMDD-HHMMSS.log

16:33:37.773 INFO  [system  ] [*] Bắt đầu quét
16:33:37.773 ERROR [-] [-] Lỗi tải tệp: timeout
16:33:37.773 WARN  [-] [!] Bỏ qua 3 tệp
```

- Ghi ngay sau từng dòng (flush) → app bị kill vẫn còn log
- Bắt exception chưa xử lý kèm traceback
- Tự xoay vòng, giữ 30 phiên
- Tự phân loại theo nội dung, không chỉ tag

---

## P1 — Việc tiếp theo

### P1.1 — Dọn 13,52 GB trùng lặp

**Đo được trên ổ thật:**

| | |
|---|---|
| Folder có media | 323 |
| Tổng file | 3 140 |
| **File thừa** | **418** |
| **Dung lượng thừa** | **13,52 GB** |
| Tỷ lệ | **13,3 %** |

Cùng một video, 2 file, md5 giống hệt:

```
11 496 403 B  [20250415_145826]_main_video_001.mp4        md5=547dbfb5bec8be6a...
11 496 403 B  [20250415_145826]_main_video_001_7d7620.mp4 md5=547dbfb5bec8be6a...
```

**Phân loại nguyên nhân:**

| Loại | Số nhóm | Ghi chú |
|---|---|---|
| Cũ (không hash) + mới (có hash) | **413** | Nợ từ 28/10, trước khi sửa lỗi C4 |
| Cùng ảnh, hash khác | **5** | Đang phát sinh |

Xác nhận bằng mốc thời gian: file không hash tạo `2026-10-28 15:47`, file có hash tạo `2026-11-06 14:39`.

**Đã làm:** `clean_duplicates.py` — quét, so md5, giữ bản có hash, báo cáo dung lượng thu hồi. Mặc định **dry-run**, chỉ xoá khi có `--apply` + gõ `XOA`.

**Kết quả dry-run trên ổ thật (`E:\HIDE\RPHANG`):**

```
file đã xét        : 3107
nhóm trùng         : 416
file thừa          : 416
dung lượng thu hồi : 13.5 GB
thời gian quét     : 209.6s   (băm 27 GB nội dung)

Theo nguyên nhân:
   412 nhóm  bản cũ không hash, giữ bản có hash
     4 nhóm  cả hai đều có hash -> trùng đang phát sinh
```

**Chốt an toàn đã kiểm:**

| Chốt | Cách kiểm |
|---|---|
| Dry-run mặc định | Không có `--apply` → không xoá (có test) |
| So **nội dung** không so tên | Cùng tên gốc khác nội dung → giữ cả hai (có test) |
| Giữ bản có hash | `rank()` ưu tiên file có hậu tố 6 hex |
| Chỉ xoá trong thư mục tải | `verify_inside()` dùng `commonpath` |
| Không xoá khi bản giữ đã mất | Kiểm `os.path.exists(keep)` trước |
| File bị khoá thì bỏ qua | `md5_of()` trả None khi PermissionError |

> **Cần người dùng duyệt trước khi chạy `--apply`.**

### P1.2 — Hash theo nội dung

**Vấn đề:** `url_hash()` tính trên **URL**, không phải nội dung:

```python
def url_hash(url):
    return hashlib.md5(url.split('?')[0].split('#')[0].encode('utf-8')).hexdigest()
```

Cùng một ảnh ở 2 URL (thumbnail vs bản đầy đủ) → 2 hash → 2 file. Đó là 5 nhóm đang phát sinh.

**Đã làm:**

1. `cache.py`: thêm cột `content_hash` + index. Tự **migrate** DB cũ (`ALTER TABLE`), dữ liệu cũ giữ nguyên với `content_hash = NULL`.
2. `cache.record()`: đổi sang ghi **theo tên cột** (`INSERT ... (url_clean_hash, filename, downloaded_at, content_hash)`). Bản cũ dùng `VALUES (?,?,?)` theo vị trí — thêm cột là hỏng ngay.
3. `cache.path_for_content()`: tìm file đã có cùng nội dung, **kiểm file còn tồn tại** trước khi trả về (dòng cache trỏ file đã xoá mà vẫn tin thì hardlink sẽ hỏng).
4. `fast_fetch.download_to_file()`: băm md5 **trong lúc ghi** — không tốn I/O thêm.
5. `downloader._fetch_streaming()`: sau khi tải, nếu nội dung đã có thì tạo **hardlink** thay vì giữ bản sao.

**Kiểm chứng:** hai URL khác nhau cùng nội dung → **cùng inode**, 0 byte thêm:

```
lan 1: {'ok': 1, 'failed': 0, 'image': 1}
lan 2: {'ok': 1, 'failed': 0, 'image': 1}
f1: 501781 B   f2: 501781 B
cung inode (hardlink): True
deduped   : 1
cache: h1 content_hash=bdfd856236999d0a
       h2 content_hash=bdfd856236999d0a
```

**An toàn:** tạo hardlink ra `.lnk` **trước**, chỉ `os.replace` khi thành công. Không bao giờ xoá bản vừa tải khi chưa có thay thế. Nếu FS không hỗ trợ hardlink thì giữ bản vừa tải (không phải lỗi).

### ⚠️ P1.3 — Xoá `v72.py`: ĐỀ XUẤT NÀY SAI

Tôi đề xuất xoá `v72.py` vì "chỉ `README` nhắc tới". **Kiểm tra lại thì sai:**

```
test_v72.py dòng 31:  from v72
test_v72.py dòng 942, 1109, 1128, 1466, 1536, 1609, 2115:  import v72

7 test class dùng v72:
  TestLogColors, TestDownloadProgress, TestDirInjection, TestRunGuard,
  TestThemeSwitchMidScan, TestCloseWhileCrawling, TestSuiteIsHermetic
```

`v72.py` vẫn là **GUI Tkinter đang hoạt động** (được `README` ghi là "giao diện truyền thống"), và 7 nhóm test còn kiểm nó.

**Vậy phải chọn một trong hai, không thể lơ lửng:**

| Lựa chọn | Việc phải làm | Hệ quả |
|---|---|---|
| **A. Giữ `v72.py`** | Không làm gì | 1040 dòng phải bảo trì song song |
| **B. Bỏ `v72.py`** | Chuyển 7 test class sang `gui_fluent`, hoặc xoá nếu chỉ kiểm GUI cũ | Mất "giao diện truyền thống" |

**Đề xuất:** chọn **B** nếu bạn chỉ dùng `gui_fluent.py`. Nhưng cần bạn xác nhận — tôi không tự xoá một GUI đang chạy được.

---

## P2 — Chất lượng mã nguồn

### P2.1 — Tách `gui_fluent.py` — ✅ XONG

**Đã làm:** tách 1507 dòng thành package `ui/`:

```
ui/
├── __init__.py     (26)   re-export để mọi import cũ vẫn chạy
├── log_view.py     (166)  bảng màu, glyph map, swallow(), insert_formatted
├── worker.py       (126)  WorkerSignals, CrawlWorker
├── crawler_view.py (397)  CrawlerInterface
├── settings_view.py(340)  SettingsInterface
└── main_window.py  (595)  MainWindow + main()
```

File dài nhất 595 dòng (từ 1507). `gui_fluent.py` giờ là **shim 29 dòng**
re-export — `python gui_fluent.py` và `from gui_fluent import MainWindow`
vẫn chạy như cũ, không chỗ nào phải đổi.

**Test bắt được lỗi trong lúc tách:** thiếu `QFont` import (5 test error),
3 test inspect source phải trỏ vào module mới thay shim.

### P2.2 — Tách `test_v72.py` — ✅ XONG

**Đã làm:** tách 2388 dòng / 154 test thành 5 file theo module nguồn:

```
test_common.py      — setUpModule/tearDownModule/soup_of chung cho cả 5
test_parse_v2.py    (30 test) xenforo_parse + xf_selectors
test_cache_v2.py    (21 test) cache + local user index
test_download_v2.py (28 test) downloader + fast_fetch
test_engine_v2.py   (38 test) engine + browser_launcher
test_tk_v2.py       (37 test) GUI Tkinter (v72.py)
```

`test_v72.py` trở thành **aggregator** — giữ nguyên tên nên mọi lệnh cũ
(`python -m unittest test_v72`) vẫn chạy đúng. Dùng `load_tests` nên
**KHÔNG trùng lặp test**: 154 test sau tách = đúng 154 trước tách.

Lợi ích: chạy riêng một nhóm (`test_parse_v2`) mất 0,01s thay vì cả 7s;
file dài nhất 701 dòng thay vì 2388.

### P2.3 — Giảm `except: pass` (70 chỗ)

| File | Số chỗ |
|---|---|
| `gui_fluent.py` | 18 |
| `session_log.py` | 8 |
| `downloader.py` | 6 |
| `engine.py` | 5 |
| `fast_fetch.py` | 3 |
| `cache.py` | 1 |

**Đây là lý do gốc khiến lỗi 1 và 2 tồn tại lâu:** lỗi bị nuốt nên không ai thấy.

**Đề xuất:** không xoá hết — nhiều chỗ cố ý (dọn dẹp không được làm chết app). Nhưng phải **log lại** trước khi nuốt:

```python
except Exception as e:
    log_debug(f"bỏ qua: {type(e).__name__}: {e}")   # thay vì pass
```

### P2.4 — Gộp biến cấu hình trình duyệt

**Hiện tại có hai biến cho hai mode:**

```python
CDP_BROWSER = "coccoc"        # mode cdp
SESSION_BROWSER = "chrome"    # mode persistent
```

Lệch nhau → đây chính là nguồn lỗi 4.

**Đề xuất:** một biến `BROWSER = "coccoc"` + `USE_REAL_PROFILE` quyết định profile. Mode chỉ quyết định **cách kết nối**, không quyết định **trình duyệt nào**.

### P2.5 — Lỗi hồi quy do chính P2.1 để lại — ✅ ĐÃ VÁ

**Triệu chứng:** bấm nút "Sao chép" ở trang Quét Media → không có gì vào clipboard, stderr in traceback:

```
AttributeError: module 'ui.crawler_view' has no attribute 'QApplication'
```

**Nguyên nhân:** khi tách `gui_fluent.py` (1507 dòng) thành package `ui/`, module
`ui/crawler_view.py` dùng `QApplication.clipboard()` ở `_copy_log()` nhưng danh
sách import chỉ có `QWidget, QVBoxLayout, QHBoxLayout, QGridLayout` — thiếu
`QApplication`. Bản gốc trước khi tách có import này.

**Vì sao 261 test không bắt được:** không test nào gọi `_copy_log`. Đây đúng là
loại lỗi mà chính P2.1 ghi nhận ("test bắt được lỗi trong lúc tách: thiếu `QFont`
import") — nhưng lần đó chỉ bắt được phần đã có test chạm tới.

**Đã vá:**

1. `ui/crawler_view.py`: thêm `QApplication` vào import QtWidgets, kèm chú thích
   nêu rõ vì sao không được bỏ.
2. `test_gui_fluent.py`: thêm `TestCopyLogButton` (3 test) — chốt cả hai tầng:
   - `test_module_exposes_qapplication` kiểm thẳng namespace module (bắt đúng
     lớp lỗi thiếu import, không phụ thuộc clipboard)
   - `test_copy_log_puts_text_on_clipboard` gọi `_copy_log()` thật rồi đọc lại
     clipboard
   - `test_copy_log_on_empty_log_does_not_raise` kiểm nhánh cảnh báo

**Kiểm chứng bằng negative control:** gỡ `QApplication` khỏi import rồi chạy lại
→ 1 fail + 1 error; phục hồi → xanh. Test thật sự bắt được lỗi, không phải xanh
cho có.

**Kèm theo — dọn cảnh báo tĩnh:** `pyflakes` giờ sạch trên toàn bộ module
(`ui/` 0 cảnh báo). Đã xoá 12 import/biến chết: `os`/`ComboBox`/`make_log_font`/
`format_log_text` (crawler_view), `QTextCursor`/`QTextBlockFormat` (log_view),
`asyncio`/`re`/`subprocess` (main_window), `TextEdit`/`swallow`/`proc`
(settings_view), `config` (worker), `time` (session_log), `ignore`
(session_source), `CrawlWorker` trùng dòng (gui_fluent), `f`-string vô nghĩa
(clean_duplicates).

> Ghi chú: `session_source.copy_profile` có biến `ignore = shutil.ignore_patterns(...)`
> nhưng **không truyền cho ai** — `os.walk` tự lọc `dirs[:]` thủ công. Biến chết
> này gây hiểu nhầm là có hai cơ chế lọc. Đã gộp thành một hằng `_SKIP_DIRS`
> dùng cho cả hai chỗ.

---

## P3 — Kiến trúc

### P3.1 — Chuyển sang `logging` chuẩn

`session_log.py` hiện là tự viết. Dùng `logging` của Python sẽ có sẵn: rotation (`RotatingFileHandler`), level, handler, format, thread-safe.

**Lợi ích:** bớt ~200 dòng tự bảo trì.

**Rủi ro:** `logging` mặc định không flush mỗi dòng như bản hiện tại — cần đặt `delay=False` và handler flush, nếu không mất log khi crash giữa chừng.

### P3.2 — `pyproject.toml` + `ruff`

Hiện không có công cụ bắt lỗi tĩnh tự động. `pyflakes` phát hiện được lỗi 3 (`undefined name 'e'`) ngay lập tức, nhưng chỉ chạy khi tôi nhớ ra.

**Đề xuất:**

```toml
[tool.ruff]
line-length = 100
select = ["E", "F", "W", "B", "UP"]   # B = bugbear: bắt lỗi logic
```

Chạy trong CI hoặc pre-commit để lỗi loại này không lọt vào bản chạy.

---

## Điểm mạnh cần giữ

| Điểm | Bằng chứng |
|---|---|
| **Kỷ luật kiểm chứng** | 18 script probe; mỗi kết luận đều đo được, không suy đoán |
| **HTTP-first** | 14,2 trang/giây so với 11,6 của trình duyệt; không tốn RAM render |
| **Streaming tải file** | 5 file 133 MB: RAM +80 MB → **+0 MB**, nhanh hơn 3 % |
| **Cache khử trùng lặp** | 2 987 media, 1 557 thread trong SQLite |
| **Test hermetic** | 243 test, 35 giây, không cần mạng, không đụng dữ liệu thật |
| **Chú thích "vì sao"** | Giải thích **tại sao**, kèm số đo — không chỉ mô tả code làm gì |
| **Dừng sớm** | 1 336 trang box → chỉ đọc vài trang đầu khi bài đã có |

## Bài học từ review này

1. **Ba lần tôi đo sai và tự phát hiện** — `glob.glob()` hiểu `[` `]` là ký tự đặc biệt; test không bắt được lỗi vì test sai chỗ; test hồi quy báo fail vì comment của chính tôi.

2. **Một lỗi có thể nằm ở 3 tầng.** Lỗi 1 phải sửa cả `__init__`, `_fetch`, và `counted()`. Sửa một tầng thì lỗi vẫn còn, chỉ đổi chỗ biểu hiện.

3. **`except: pass` là kẻ thù của việc debug.** 70 chỗ nuốt lỗi là lý do hai lỗi nghiêm trọng tồn tại qua nhiều lần sửa mà không ai thấy.

4. **Không có log thì không debug được.** Người dùng báo "7 lỗi" nhưng không có file nào để đọc — mọi chẩn đoán phải đoán lại từ đầu.

---
---

# Đợt review 2026-11-08 — Mã nguồn hiện tại (sau các đợt sửa trước)

> Ngày lập: 2026-11-08
> Phạm vi: 12 file mã nguồn + test suite
> Căn cứ: đọc mã + script probe tái hiện từng lỗi + chạy `ruff`
> Trạng thái: **chưa sửa gì** — báo cáo để quyết định thứ tự ưu tiên
> Lưu ý: các mục P0–P3 ở trên là lịch sử các đợt trước, giữ nguyên để đối chiếu.

---

## Bảng tổng hợp

| # | Mức | Vấn đề | File | Trạng thái |
|---|---|---|---|---|
| 1 | 🔴 Nghiêm trọng | Bài bị đánh dấu "đã xong" khi chưa tải xong | `engine.py` | Đã tái hiện |
| 2 | 🔴 Nghiêm trọng | File HTML bị lưu thành ảnh/video | `fast_fetch.py` | Đã tái hiện |
| 3 | 🔴 Nghiêm trọng | `url_hash()` cắt query → va chạm hash | `downloader.py` | Đã tái hiện |
| 4 | 🔴 Nghiêm trọng | Cookie bị gửi sang domain thứ ba | `fast_fetch.py` | Chỉ đọc mã |
| 5 | 🟠 Trung bình | Thống kê bị thổi phồng do tiêu đề bài | `ui/worker.py` | Đã tái hiện |
| 6 | 🟠 Trung bình | GUI báo "thành công" dù có lỗi | `ui/log_view.py` | Đã tái hiện |
| 7 | 🟠 Trung bình | `LocalUserIndex` không dùng chung khoá | `cache.py` | Đã tái hiện |
| 8 | 🟠 Trung bình | File quá lớn bị tải lại nhiều lần | `fast_fetch.py` | Đã tái hiện |
| 9 | 🟡 Thấp | Config chết (3 biến không ai đọc) | `config.py` | Đã xác nhận |
| 10 | 🟡 Thấp | `--no-sandbox` bật mặc định | `config.py` | Đã xác nhận |
| 11 | 🟡 Thấp | Biến chưa định nghĩa trong test | `test_review_round2.py` | Ruff F821 |

---

## 🔴 Nghiêm trọng

### 1. Bài bị đánh dấu "đã xong" khi chưa tải xong

**File:** `engine.py` → `crawl_thread()` (khoảng dòng 747)

**Triệu chứng:** `self.cache.remember_thread_date(...)` được gọi khi `pages_done > 0`, bất kể `self.stop_event.is_set()` đã bật hay `stats.get("failed", 0) > 0`.

**Hậu quả:** với `STOP_ON_KNOWN_THREAD = True`, lần chạy sau bỏ qua **vĩnh viễn** các bài chỉ tải được một phần. Người dùng mất media mà không có bất kỳ cảnh báo nào.

**Nguyên nhân gốc:** điều kiện "bài đã xong" không tách khỏi điều kiện "bài tải thành công".

**Cách sửa:**

```python
if pages_done > 0 and not self.stop_event.is_set() and stats.get("failed", 0) == 0:
    self.cache.remember_thread_date(...)
```

### 2. File HTML bị lưu thành ảnh/video

**File:** `fast_fetch.py` → `download_to_file()`

**Triệu chứng:** mã đọc `res.content_type` nhưng không kiểm tra `NON_MEDIA_CONTENT_TYPES`.

**Hậu quả:** khi server trả HTTP 200 kèm trang đăng nhập hoặc trang Cloudflare, nội dung HTML được ghi thành `.jpg`/`.mp4`, tính MD5 rồi **ghi vào cache như tải thành công**. File hỏng đó không bao giờ được tải lại, và người dùng thấy "tải xong" dù mở ra là trang lỗi.

**Cách sửa:** gặp `text/html` / `text/plain` thì xoá file tạm, trả lỗi, không ghi cache.

**Lưu ý khi sửa:** cache hiện có thể đã chứa các bản ghi HTML sai. Sau khi vá cần quét lại để dọn, nếu không bài đã "tải xong" vẫn bị bỏ qua.

### 3. `url_hash()` cắt query → va chạm hash

**File:** `downloader.py` → `url_hash()`

**Mã hiện tại:** `url.split('?')[0]`

**Hậu quả:** XenForo phục vụ media qua các route có query là tham số chứ không phải định danh:

- `proxy.php?image=...&hash=...`
- `index.php?attachments/...`

Các URL này khác nhau **chỉ ở query**, nên sau khi cắt sẽ cho cùng một hash → bị coi là trùng → **bỏ sót tải file**.

**Cách sửa:** chỉ cắt query khi path đã đủ phân biệt; giữ nguyên query cho route proxy/attachment. Cần kiểm tra cả cache đã tạo vì hash cũ đã va chạm.

### 4. Cookie bị gửi sang domain thứ ba

**File:** `fast_fetch.py` (nơi nạp/gắn cookie)

**Triệu chứng:** toàn bộ cookie trình duyệt được gắn vào cả URL ảnh/video ở host bên ngoài.

**Hậu quả:** phiên đăng nhập XenForo có thể bị gửi cho host không liên quan. Đây là rủi ro lộ thông tin đăng nhập.

**Cách sửa:** lọc cookie theo host trước khi gắn vào request.

> Trạng thái: **chỉ đọc mã, chưa tái hiện được** bằng probe. Cần kiểm chứng lại trước khi sửa.

---

## 🟠 Trung bình

### 5. Thống kê bị thổi phồng do tiêu đề bài

**File:** `ui/worker.py` → `log_bridge()`

**Mã hiện tại:** regex `(\d+)\s+ảnh` chạy trên **mọi** dòng log, kể cả tiêu đề bài.

**Tái hiện:** dòng `Bài 1: Tuyển tập 120 ảnh đẹp 30 video` làm cộng thêm **120 ảnh và 30 video** vào số liệu tải.

**Cách sửa:** chỉ áp regex cho dòng tổng kết có marker cố định (ví dụ `Tải xong:`).

### 6. GUI báo "Đồng bộ thành công" dù có lỗi

**File:** `ui/log_view.py` → `detect_log_tag()`

**Mã hiện tại:** `_MARKER_RE = re.compile(r"^(\[\*\]|\[-\]|\[!\]|...)")` — có `^` nhưng **không bỏ khoảng trắng đầu dòng**.

**Tái hiện:** dòng thụt lề `   [!] Cảnh báo: ...` không khớp → rơi về tag `dim` → `self.had_error` không bao giờ bật → GUI hiện **"Đồng bộ thành công!"** dù đã có nhiều lỗi.

**Cách sửa:** `message = message.lstrip()` trước khi match.

### 7. `LocalUserIndex` không dùng chung khoá với `MediaCache`

**File:** `cache.py` (khoảng dòng 189)

**Mã hiện tại:** `getattr(conn, "_lock", threading.RLock())`

**Nguyên nhân:** `sqlite3.Connection` **không có** thuộc tính `_lock`, nên `getattr` luôn trả về `RLock()` mới → mỗi index có khoá riêng.

**Hậu quả:** GUI quét user và worker ghi cache dùng chung một connection nhưng **không được bảo vệ chéo** → race condition.

**Cách sửa:** truyền `MediaCache._lock` vào constructor của `LocalUserIndex`.

### 8. File quá lớn bị tải lại nhiều lần

**File:** `fast_fetch.py` → xử lý `_TooBig`

**Mã hiện tại:** đặt `res.status = 0`, `res.error = "vượt giới hạn X MB"`, nhưng vòng lặp chỉ dừng khi lỗi chứa `"quá lớn"`.

**Hậu quả:** không khớp chuỗi → vòng lặp retry `MAX_RETRIES` lần, **mỗi lần tải lại tới `MAX_FILE_MB`** → lãng phí băng thông và thời gian (tệ nhất ~512 MB vô ích).

**Cách sửa:** dùng cờ rõ ràng (`res.fatal = True`) thay vì so khớp chuỗi — tránh lỗi tương tự tái diễn khi đổi câu chữ.

---

## 🟡 Thấp

### 9. Config chết

`config.py` có `THREAD_MAX_PAGES`, `MAX_OPEN_TABS`, `MEMORY_SOFT_LIMIT_MB` — không nơi nào đọc tới.

**Đề xuất:** bỏ chúng, hoặc nối vào engine/downloader nếu chúng vốn có ý định làm trần. Giữ lại biến không dùng tạo ảo giác rằng giới hạn đang hoạt động.

### 10. `--no-sandbox` bật mặc định

**File:** `config.py`

Chromium chạy không sandbox là rủi ro nếu nội dung trang web không đáng tin. **Đề xuất:** tắt mặc định, chỉ bật qua tuỳ chọn khi môi trường thực sự cần.

### 11. Biến chưa định nghĩa trong test

**File:** `test_review_round2.py` — ruff báo `F821` (undefined name). Test này có thể đang fail âm thầm hoặc bị bỏ qua.

---

## Khoảng trống kiểm thử

**264 test pass** — nhưng **không test nào** bao phủ các lỗi 1, 2, 5, 6, 7, 8.

Khi sửa, thêm mỗi lỗi một test nhỏ, theo đúng kỷ luật của đợt trước: **gỡ fix → test phải đỏ**, dán lại fix → test phải xanh (negative control).

---

## Thứ tự ưu tiên đề xuất

| Bước | Việc | Lý do | Trạng thái |
|---|---|---|---|
| 1 | Lỗi 1 + Lỗi 2 | Gây mất dữ liệu **âm thầm** — không cảnh báo, không log | ✅ **ĐÃ SỬA** |
| 2 | Lỗi 3 | Bỏ sót tải file, tệ nhất là ảnh trùng nội dung | ✅ **ĐÃ SỬA** |
| 3 | Lỗi 4 | Rủi ro lộ phiên đăng nhập (cần tái hiện trước) | ⬜ |
| 4 | Lỗi 5–8 | Báo cáo sai + lãng phí tài nguyên | ⬜ |
| 5 | Lỗi 9–11 | Dọn dẹp | ⬜ |

---

## Sửa hoàn tất — 2026-11-08

### ✅ Lỗi 1: Bài bị đánh dấu "đã xong" khi chưa xong

**File sửa:** `engine.py` (dòng 743–748)

**Thay đổi:**
```python
# Trước: 
if self.cache is not None and pages_done > 0:
    self.cache.remember_thread_date(thread_key, date_prefix, folder)

# Sau:
if (self.cache is not None and pages_done > 0
    and not self.stop_event.is_set()
    and stats.get("failed", 0) == 0):
    self.cache.remember_thread_date(thread_key, date_prefix, folder)
```

**Kiểm chứng:** 273 test pass (264 cũ + 9 test mới).

### ✅ Lỗi 2: File HTML bị lưu thành ảnh/video

**File sửa:** `fast_fetch.py` (dòng 291–304)

**Thay đổi:** Sau khi đọc header, kiểm tra `Content-Type`. Nếu là `text/html` hoặc `text/plain` → xoá file tạm, trả lỗi, không ghi cache:

```python
res.content_type = (r.headers.get("Content-Type") or "").lower()

# Nếu server trả HTML/plain text thay vì media (ví dụ: trang đăng nhập,
# Cloudflare, lỗi), xoá file tạm và báo lỗi. KHÔNG ghi cache.
if res.content_type.startswith("text/html") or res.content_type.startswith("text/plain"):
    res.error = f"sai loại file: {res.content_type} (có thể trang lỗi/đăng nhập)"
    return res
```

**Kiểm chứng:** Test mock HTTP response trả `text/html` → file tạm bị xoá, `result.error` chứa `"text/html"`.

### ✅ Lỗi 3: `url_hash()` cắt query → va chạm hash

**File sửa:** `downloader.py` (dòng 77–87)

**Thay đổi:** Giữ query nếu URL chứa `proxy.php` hoặc `attachments` (vì query là định danh), cắt query cho các URL khác:

```python
def url_hash(url):
    """Hash URL. Giữ query cho route proxy/attachment vì query là định danh."""
    path_and_query = url.split('#')[0]  # Xoá fragment
    if 'proxy.php' in path_and_query or 'attachments' in path_and_query:
        # Giữ toàn bộ URL với query
        return hashlib.md5(path_and_query.encode('utf-8')).hexdigest()
    else:
        # Các URL khác, xoá query vì path đủ phân biệt
        return hashlib.md5(path_and_query.split('?')[0].encode('utf-8')).hexdigest()
```

**Kiểm chứng:** Test `proxy.php?image=abc&hash=123` khác `proxy.php?image=def&hash=456` → hash khác; `image.jpg?v=1` giống `image.jpg?v=2` → hash giống.

---

## Phạm vi chưa kiểm tra

- Chưa đo hiệu năng (throughput, RAM, I/O).
- Chưa chạy thử trên site XenForo thật.
- Lỗi 4 mới chỉ đọc mã, chưa tái hiện.
- Cache cũ có thể còn chứa bản ghi HTML sai từ lỗi 2. Sau khi deploy nên quét lại để dọn cache.
