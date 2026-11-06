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
| **P2** | Tách `gui_fluent.py` | ⬜ | 1407 dòng |
| **P2** | Tách `test_v72.py` | ⬜ | 2388 dòng |
| **P2** | Giảm `except: pass` | ⬜ | 70 chỗ |
| **P2** | Gộp biến cấu hình trình duyệt | ⬜ | Nguồn lỗi 4 |
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

### P2.1 — Tách `gui_fluent.py` (1407 dòng)

Hiện chứa: `WorkerSignals`, `CrawlWorker`, `CrawlerInterface`, `SettingsInterface`, `MainWindow`, hàm `main()`, và toàn bộ logic theme/log.

**Đề xuất:**

```
ui/
├── worker.py       # WorkerSignals, CrawlWorker
├── crawler_view.py # CrawlerInterface
├── settings_view.py# SettingsInterface
├── main_window.py  # MainWindow
└── theme.py        # load/save theme, bảng màu
```

### P2.2 — Tách `test_v72.py` (2388 dòng, 154 test)

**Đề xuất tách theo module nguồn:**

```
test_parse.py      # xenforo_parse
test_download.py   # downloader, fast_fetch
test_cache.py      # cache
test_engine.py     # engine
test_gui.py        # v72 / gui_fluent
```

Lợi ích: chạy test một phần nhanh hơn, tìm test hỏng dễ hơn, file dưới ngưỡng 1000 dòng.

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
