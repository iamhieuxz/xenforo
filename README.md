# XenForo Crawler V72

Ứng dụng desktop quét media từ diễn đàn XenForo và tải về ổ. Viết bằng Python + Tkinter, điều khiển trình duyệt qua cổng debug CDP của Playwright.

Mục tiêu của dự án: gom ảnh, video và file đính kèm của một chuyên mục (box) hoặc một bài viết, tải song song, bỏ qua thứ đã có, và cho phép dừng ngay khi đang tải.

## Mục lục

- [Tính năng](#tính-năng)
- [Yêu cầu](#yêu-cầu)
- [Cài đặt](#cài-đặt)
- [Chạy](#chạy)
- [Cách dùng](#cách-dùng)
- [Cấu trúc dự án](#cấu-trúc-dự-án)
- [Luồng hoạt động](#luồng-hoạt-động)
- [Cấu hình](#cấu-hình)
- [Phím tắt](#phím-tắt)
- [Giao diện](#giao-diện)
- [Kiểm thử](#kiểm-thử)
- [Xử lý sự cố](#xử-lý-sự-cố)
- [Giới hạn đã biết](#giới-hạn-đã-biết)

## Tính năng

- Quét theo chuyên mục: duyệt toàn bộ thread trong một box, mỗi thread một tab, giới hạn 5 tab chạy song song.
- Quét theo bài viết: dán link một thread, lấy media ngay trong bài đó.
- Quét đa luồng nhiều user: bấm một lần, app tự quét toàn bộ user đã có trên ổ.
- Tải song song 10 request cùng lúc, tên file gồm timestamp bài viết, số thứ tự và tên gốc.
- Cache SQLite ghi nhớ URL nào đã tải và nằm ở file nào, lần sau bỏ qua.
- Dừng khẩn cấp: huỷ request đang treo trong khoảng 2 giây thay vì chờ hết timeout 40 giây.
- Nhật ký có màu theo loại thông báo, lọc theo từ khoá, sao chép, xóa.
- Hai bảng màu sáng và tối, đổi qua nút "Giao diện", nhớ lựa chọn giữa các lần mở.

## Yêu cầu

| Thành phần | Yêu cầu |
| --- | --- |
| Python | 3.10 trở lên |
| Hệ điều hành | Windows (app dùng `ctypes` để bật thanh tiêu đề tối) |
| Trình duyệt | Chrome, Cốc Cốc hoặc Edge, bản >= 136 |

Chrome từ bản 136 trở lên từ chối cổng debug không phải cổng mặc định của chính profile đó. Vì vậy app luôn tự mở trình duyệt với `--user-data-dir` riêng, tách khỏi profile bạn đang dùng.

Thư viện Python:

```
playwright==1.54.0
aiofiles==25.1.0
beautifulsoup4==4.15.0
lxml==6.1.1
```

## Cài đặt

```bash
git clone https://github.com/iamhieuxz/xenforo.git
cd xenforo

python -m venv .venv
.venv\Scripts\activate

pip install playwright==1.54.0 aiofiles==25.1.0 beautifulsoup4==4.15.0 lxml==6.1.1
```

App dùng Playwright để điều khiển trình duyệt có sẵn trên máy, nên **không cần**
`playwright install` (không dùng browser do Playwright tải về).

## Chạy

**1. Giao diện Windows 11 Fluent Design (Khuyên dùng - PySide6 + PyQt-Fluent-Widgets):**
```bash
python gui_fluent.py
```
Giao diện Acrylic/Mica hiện đại, thẻ bo góc, thanh tiến trình động, thông báo toast popup (InfoBar), trang Cài đặt tùy chỉnh thư mục lưu trữ và theme trực quan.

**2. Giao diện truyền thống Tkinter:**
```bash
python v72.py
```

Muốn chạy thử mà không đụng ổ thật, trỏ thư mục gốc sang nơi khác:

```bash
set RPHANG_DIR=D:\test-rphang
python gui_fluent.py
```

## Hai chế độ điều khiển trình duyệt

Đặt `BROWSER_MODE` trong `config.py`.

### `persistent` (mặc định) — không cần cổng

Playwright tự mở trình duyệt với một profile **cố định** tại
`%LOCALAPPDATA%\V72Crawler\session_<trình duyệt>`.

- **Không dùng cổng TCP nào.** Playwright nói chuyện qua pipe.
- **Đăng nhập một lần là dùng mãi.** Session lưu trong profile, sống qua các lần
  mở/đóng (đã kiểm chứng: mở/đóng 3 lần liên tiếp vẫn còn cookie).
- Nút **Đăng nhập** ở trang Cài đặt mở trình duyệt có cửa sổ để bạn đăng nhập,
  rồi phiên quét sẽ dùng lại chính profile đó.

```python
BROWSER_MODE = "persistent"
SESSION_BROWSER = "chrome"      # "chrome" | "coccoc" | "edge"
SESSION_PROFILE = ""            # rỗng = dùng profile riêng của app
SESSION_HEADLESS = True         # False để thấy cửa sổ khi quét
```

### `cdp` — đường cũ, giữ làm dự phòng

Nối vào cổng debug của một trình duyệt đang chạy (`--remote-debugging-port`).
Dùng khi môi trường không cho Playwright tự mở trình duyệt.

> **Vì sao `persistent` là mặc định:** cổng TCP 9222 có ba vấn đề đã đo được —
> (1) một tiến trình bất kỳ chiếm cổng làm app tưởng Chromium đã sẵn sàng;
> (2) `localhost` resolve ra `::1` trước `127.0.0.1` nên request có thể bị từ chối;
> (3) xung đột với mọi công cụ khác muốn dùng cổng 9222.

### Dùng session đăng nhập có sẵn

Ba cách, từ an toàn đến tiện:

| Cách | An toàn | Session |
|---|---|---|
| Để trống `SESSION_PROFILE` (mặc định) | Cao nhất — profile riêng của app | Đăng nhập một lần qua nút **Đăng nhập** |
| Trỏ vào profile **đã copy** | Cao — app chỉ ghi vào bản copy | Có sẵn, nhưng là bản chụp |
| Trỏ vào profile **thật** của trình duyệt | Thấp — app ghi vào dữ liệu bạn đang dùng | Có sẵn, luôn mới nhất |

```python
# Ví dụ dùng profile Chrome có sẵn (phải ĐÓNG Chrome trước)
SESSION_BROWSER = "chrome"
SESSION_PROFILE = r"C:\Users\<bạn>\AppData\Local\Google\Chrome\User Data"
```

**Bắt buộc phải đóng trình duyệt trước.** Đo được: khi trình duyệt đang chạy nó
giữ khoá độc quyền trên đúng file `Cookies` trong profile:

```
Network/Cookies        BI KHOÁ    <- độc quyền
Preferences            đọc được
History                đọc được
Web Data               đọc được
```

Chỉ file `Cookies` bị khoá — không phải vấn đề quyền của tiến trình gọi, không có
quyền nào vượt được. App sẽ báo rõ nếu phát hiện trình duyệt đang chạy.

**Cảnh báo:** profile chứa cookie, mật khẩu đã lưu và lịch sử duyệt web. Chỉ dùng
cách thứ ba khi bạn chấp nhận app ghi vào dữ liệu đó.

## Cách dùng

1. **Link Chuyên Mục (Box URL)** — chọn trong dropdown hoặc gõ tay. Ô này dùng cho cả quét user và quét toàn bộ.
2. **Username quét đơn** — dropdown liệt kê các user đã có trên ổ, lấy từ SQLite nên mở app là có ngay. Gõ tay cũng được.
3. **Nhập Link Bài Viết (URL)** — dán link một thread để quét riêng bài đó.

Ba nút bấm:

| Nút | Việc |
| --- | --- |
| Quét 1 User | Quét chuyên mục, chỉ lấy media của một tác giả trong danh sách user |
| Quét 1 Thớt | Quét một bài viết theo link bạn dán |
| Cập nhật toàn bộ User | Quét lại toàn bộ user đang có trên ổ, chạy đa luồng |

Trong lúc chạy, ba nút trên bị vô hiệu hóa, chỉ còn "Dừng khẩn cấp". Góc trên phải hiện trạng thái (SẴN SÀNG / ĐANG QUÉT / ĐÃ DỪNG / CÓ LỖI) kèm số liệu đếm được: ảnh, video, lỗi.

## Cấu trúc dự án

```
xenforo/
├── gui_fluent.py      # Điểm vào chính: Giao diện Windows 11 Fluent Design (PySide6 + Fluent-Widgets)
├── v72.py             # Điểm vào phụ: Giao diện Tkinter truyền thống
├── engine.py          # Điều phối Playwright: duyệt box -> duyệt thread -> bóc media
├── downloader.py      # Lập kế hoạch tải, tải song song, đếm thống kê
├── xenforo_parse.py   # Bóc DOM XenForo (hàm thuần, không đụng mạng)
├── xf_selectors.py    # Regex và hằng dùng chung cho phần bóc DOM (tránh đụng stdlib selectors)
├── cache.py           # Cache SQLite: media đã tải + danh sách user local
├── browser_launcher.py# Dò trình duyệt, kiểm tra cổng CDP (chế độ dự phòng)
├── session_source.py  # Profile trình duyệt: dò, kiểm tra khoá, copy
├── config.py          # Toàn bộ tham số nằm ở đây
├── test_v72.py        # 154 test cho core engine, parser, downloader, cache
├── test_review_fixes.py   # 21 test hồi quy sau đợt review
├── test_persistent_mode.py# 24 test cho chế độ persistent
├── test_gui_fluent.py     # 8 test cho giao diện Qt
├── _check_palette.py  # Self-check tương phản WCAG cho bảng màu Tkinter
└── browser.lnk        # Shortcut trình duyệt, dùng tay khi cần
```

Ranh giới tầng: `gui_fluent.py` và `v72.py` chỉ lo giao diện, `engine.py` lo điều phối, `downloader.py` lo tải file, `xenforo_parse.py` và `xf_selectors.py` là hàm thuần. Nhờ vậy phần bóc DOM test được không cần mạng.

## Luồng hoạt động

```
Bấm nút
  -> run_async_engine tạo event loop mới trong thread riêng
  -> CrawlerEngine.connect: thử cổng 9222, tự mở trình duyệt nếu chưa có
  -> duyệt box, thu thập link thread (có visited-set chống lặp vô hạn)
  -> mỗi thread: tab Playwright, chờ render, bóc DOM
  -> xenforo_parse tách ảnh / video / file, loại bỏ smilie, avatar, quảng cáo
  -> downloader tải song song, cache tra trước khi tải
  -> ghi log theo dấu [-] [!] [✓] [+] [•] [*]
```

Có semaphore ở bốn tầng: 5 tab, 10 request tải, 2 thread cho một user, 2 user song song. Số này chỉnh trong `config.py`.

## Cấu hình

Toàn bộ tham số nằm trong `config.py`:

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `DOWNLOAD_DIR` | `E:\HIDE\RPHANG` | Thư mục gốc. Ghi đè bằng biến môi trường `RPHANG_DIR` |
| `CDP_PORT` | `9222` | Cổng debug của trình duyệt |
| `AUTO_LAUNCH_BROWSER` | `True` | Tự mở trình duyệt khi khởi động |
| `BROWSER_PROFILE` | `v72_crawl` | Tên profile riêng, không đụng phiên đang dùng |
| `TAB_SEM` | `5` | Số tab Playwright mở đồng thời |
| `DOWNLOAD_SEM` | `10` | Số request tải đồng thời |
| `THREAD_SEM` | `2` | Số thread của một user bóc đồng thời |
| `USER_SEM` | `2` | Số user xử lý đồng thời |
| `PENDING_LIMIT` | `80` | Số task tải được phép tồn tại cùng lúc trong một thread |
| `MAX_FILE_MB` | `512` | Trần kích thước một tệp. `0` = không giới hạn |
| `SETTLE_MS` | `0` | Thời gian chờ thêm sau khi trang render |
| `MAX_RETRIES` | `3` | Số lần thử lại khi mở trang |
| `DOWNLOAD_TIMEOUT_MS` | `40000` | Timeout tải một file |
| `NAV_TIMEOUT_MS` | `45000` | Timeout điều hướng trang |
| `STOP_TIMEOUT_MS` | `2000` | Timeout rút ngắn khi đang dừng |
| `BOX_PRESETS` | 6 URL mẫu | Danh sách gợi ý trong dropdown |

Bốn biến semaphore được kẹp sàn `>= 1` lúc nạp config: `Semaphore(0)` là khoá
chết ngay từ đầu, còn giá trị âm thì asyncio ném `ValueError`.

Về `MAX_FILE_MB`: Playwright 1.54 **không có API streaming** cho
`context.request` — `body()` nạp toàn bộ payload vào RAM. Vì vậy trần này được
kiểm bằng `content-length` **trước khi** gọi `body()`. Nếu server không gửi
`content-length` (chunked encoding) thì file vẫn phải tải trọn, nên trần không
áp dụng được trong trường hợp đó.

Về `SETTLE_MS`: XenForo render server-side, đo thực tế `settle=0` vẫn ra đủ 20 post. Tăng lên nếu bạn thấy thiếu bài, hoặc bọc thêm `wait_for_selector` khi mạng chậm.

## Phím tắt

| Phím | Việc |
| --- | --- |
| `Ctrl+Enter` | Chạy nút tương ứng với ô đang có con trỏ |
| `Esc` | Dừng khẩn cấp |
| `Ctrl+F` | Nhảy vào ô lọc nhật ký |
| `Ctrl+L` | Xóa nhật ký |

## Giao diện

Hai bảng màu, cùng hue hổ phách:

- **Sáng** (`light`) — nền kem, thẻ trắng, nút vàng chữ tối.
- **Tối ấm** (`warm`) — nền nâu tối, thẻ nâu sẫm, nút vàng chữ sáng.

Mọi cặp chữ trên nền đều đạt WCAG 2.2 AA, kiểm tự động bằng:

```bash
python _check_palette.py
```

Lựa chọn được lưu ở `~/.xenforo_theme`, nên mở lại app vẫn giữ bảng màu đã chọn.

## Kiểm thử

```bash
python -m unittest test_v72 test_review_fixes test_persistent_mode test_gui_fluent
```

**207 test**, chạy khoảng 12 giây:

| File | Số test | Phạm vi |
|---|---|---|
| `test_v72.py` | 154 | Core: bóc DOM, downloader, cache, engine |
| `test_review_fixes.py` | 21 | Hồi quy cho các lỗi tìm thấy trong đợt review |
| `test_persistent_mode.py` | 24 | Chế độ persistent, profile, session |
| `test_gui_fluent.py` | 8 | Giao diện Qt |

Phần lớn không cần mạng và không mở trình duyệt thật. Ba script kiểm chứng
đầu-cuối chạy tay (có mạng):

```bash
python probe_cdp.py              # 13/13 — kiểm soát cổng CDP
python probe_persistent_mode.py  # 8/8   — mode persistent với trình duyệt thật
python audit_repro.py            # 4/4   — các lỗi P0 đã sửa
```

Test **hermetic**: `setUpModule` trỏ `config.DOWNLOAD_DIR` và biến
`RPHANG_DIR` về thư mục tạm, nên suite không mở và không ghi
`crawler_cache.db` của thư viện thật. Nhờ vậy chạy được trên máy CI không
có ổ `E:`.

Test tương phản màu nằm trong test suite, duyệt cả hai bảng màu. Chạy thêm self-check độc lập:

```bash
python _check_palette.py
```

## Xử lý sự cố

**"Lỗi: Thất bại khi kết nối CDP cổng 9222!"**

Trình duyệt chưa mở ở chế độ debug. Kiểm tra:

```bash
curl http://localhost:9222/json/version
```

Không phản hồi thì trình duyệt chưa chạy với cờ đúng. Nếu bản Chrome >= 136, cần profile riêng:

```bash
chrome.exe --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\V72Crawler\v72_crawl"
```

**Ảnh tải về bị lưu thành file rác (mở ra là HTML)**

Cloudflare hoặc 404 trả về HTML thay vì ảnh. `selectors.py` lọc các content-type này, nhưng nếu server trả 200 kèm HTML thì lọt lưới. Xóa file rác trong thư mục tải và chạy lại.

**Cùng một ảnh bị tải lại nhiều lần**

Cache lưu đường dẫn tuyệt đối. Nếu bạn di chuyển thư mục gốc, cache cũ trỏ tới đường dẫn không còn tồn tại và app tải lại. Xóa `crawler_cache.db` trong thư mục gốc để bắt đầu lại.

**Nút Dừng không ăn**

`STOP_TIMEOUT_MS` rút timeout tải xuống 2 giây, nhưng một request đã vào giữa chừng vẫn sống tới `DOWNLOAD_TIMEOUT_MS`. Hạ `DOWNLOAD_TIMEOUT_MS` nếu bạn muốn dừng gọn hơn.

**Cốc Cốc mở ra nhưng không có cổng 9222**

Khi Cốc Cốc đã chạy, nó bỏ qua cờ debug và chỉ mở tab. Đóng hẳn trình duyệt rồi mở lại app.

## Giới hạn đã biết

- Chỉ chạy được trên Windows. Phần bật thanh tiêu đề tối dùng `ctypes` và `dwmapi`.
- Số liệu thống kê trên góc phải được đọc từ chuỗi log mà engine in ra, không phải từ bộ đếm riêng. Sửa câu chữ trong `engine.py` thì số liệu sẽ không cập nhật, trạng thái vẫn đúng. Ngoài ra con số này là **giá trị của thread gần nhất**, không phải tổng tích luỹ của cả phiên.
- **Không tải theo luồng (streaming).** Playwright 1.54 không có API stream cho `context.request`; `body()` nạp trọn payload vào RAM. `MAX_FILE_MB` chặn được file lớn *khi server gửi `content-length`*; server dùng chunked encoding thì vẫn tải trọn. Muốn xử lý triệt để phải đổi sang HTTP client riêng và tự quản lý cookie phiên.
- Media chỉ lấy từ nội dung bài viết. Ảnh trong avatar, chữ ký cuối bài và thanh cảm xúc bị loại có chủ đích.
- Một thread nhiều trang được app bấm "Trang sau" để lấy hết, nhưng mỗi trang phải render xong mới sang trang kế tiếp nên thread dài sẽ chậm.
- `xenforo_parse.extract_post_media()` **sửa** cây soup truyền vào (gỡ quote/quảng cáo bằng `decompose()`). Cần bản không sửa input thì dùng `extract_post_media_copy()`.
- Folder của một bài được đặt theo ngày mở thread. Nếu server không trả ngày ở bất kỳ nguồn nào, folder dùng nhãn `[khong-ngay]` — **ổn định giữa các lần quét**, không đổi tên. Ngày đã biết được lưu trong bảng `thread_index` của SQLite và dùng lại cho các lần sau.

## Phạm vi quét

Khi quét theo tác giả, app chỉ mở **thread của đúng tác giả đó**. Bộ lọc được giữ
qua mọi trang: XenForo trả link phân trang trần (không mang `?starter=`), nên app
tự gắn lại query string của trang hiện tại. Nếu không, từ trang 2 trở đi box sẽ
hiện toàn bộ thread của mọi người — đó là lỗi cũ làm app mở cả nghìn bài.

Tác giả được đọc từ `data-author` **trên item của trang danh sách**, nên lọc xảy
ra trước khi mở thread. Nhật ký nói rõ:

```
[+] TRAICUBE: 3 thread trong 5 trang (97 bài người khác đã bỏ qua).
```

## Quét lại một bài đã có

Dán link và bấm **Quét 1 Thớt** — kể cả khi bài đã tải trước đó, app **luôn chạy đầy đủ**: duyệt hết các trang, đọc hết comment của chủ thớt, đếm media, rồi mới quyết định tải gì. Nó không lướt qua dựa trên việc "đã có trong SQLite".

Nhật ký luôn nói rõ đã làm gì:

```
[✓] TACGIA: Bài 1 tải mới 2 ảnh [6 bài của chủ thớt, 1 bài người khác bỏ qua, 1 trang]
[•] TACGIA: Bài 1 đã có đủ 7 media, trên đĩa có 7 tệp [...] — không cần tải lại.
[!] Đĩa chỉ có 3/7 tệp. Có thể file đã bị xoá hoặc di chuyển; chạy lại để tải bù.
[!] Trong folder có 9 tệp nhưng bài chỉ có 7 media — có thể còn bản sao từ lần quét trước.
```

Hai dòng cảnh báo cuối là điểm khác biệt so với bản cũ: trước đây nếu cache nói "đã có" thì app im lặng bỏ qua, kể cả khi file trên đĩa đã bị xoá.
