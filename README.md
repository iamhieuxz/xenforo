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

App dùng Playwright ở chế độ kết nối CDP, nên **không cần** `playwright install` (không dùng browser do Playwright tải về).

## Chạy

```bash
python v72.py
```

Lần chạy đầu, app tự mở trình duyệt ở cổng debug 9222 bằng profile riêng tại `%LOCALAPPDATA%\V72Crawler\v72_crawl`. Muốn tự mở trình duyệt trước, đặt `AUTO_LAUNCH_BROWSER = False` trong `config.py`.

Muốn chạy thử mà không đụng ổ thật, trỏ thư mục gốc sang nơi khác:

```bash
set RPHANG_DIR=D:\test-rphang
python v72.py
```

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
├── v72.py             # Điểm vào: GUI Tkinter, bảng màu, vòng đời tiến trình
├── engine.py          # Điều phối Playwright: duyệt box -> duyệt thread -> bóc media
├── downloader.py      # Lập kế hoạch tải, tải song song, đếm thống kê
├── xenforo_parse.py   # Bóc DOM XenForo (hàm thuần, không đụng mạng)
├── selectors.py       # Regex và hằng dùng chung cho phần bóc DOM
├── cache.py           # Cache SQLite: media đã tải + danh sách user local
├── browser_launcher.py# Tự mở trình duyệt ở cổng CDP 9222
├── config.py          # Toàn bộ tham số nằm ở đây
├── test_v72.py        # 52 test
├── _check_palette.py  # Self-check tương phản WCAG cho cả hai bảng màu
└── browser.lnk        # Shortcut trình duyệt, dùng tay khi cần
```

Ranh giới tầng: `v72.py` chỉ lo giao diện, `engine.py` lo điều phối, `downloader.py` lo tải file, `xenforo_parse.py` và `selectors.py` là hàm thuần. Nhờ vậy phần bóc DOM test được không cần mạng.

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
| `SETTLE_MS` | `0` | Thời gian chờ thêm sau khi trang render |
| `MAX_RETRIES` | `3` | Số lần thử lại khi mở trang |
| `DOWNLOAD_TIMEOUT_MS` | `40000` | Timeout tải một file |
| `NAV_TIMEOUT_MS` | `45000` | Timeout điều hướng trang |
| `STOP_TIMEOUT_MS` | `2000` | Timeout rút ngắn khi đang dừng |
| `BOX_PRESETS` | 6 URL mẫu | Danh sách gợi ý trong dropdown |

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
python -m unittest test_v72
```

52 test, chạy khoảng 1 giây. Phần lớn không cần mạng: phần bóc DOM, đếm thống kê, cache, dừng khẩn cấp đều dùng dữ liệu giả.

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
- Số liệu thống kê trên góc phải được đọc từ chuỗi log mà engine in ra, không phải từ bộ đếm riêng. Sửa câu chữ trong `engine.py` thì số liệu sẽ không cập nhật, trạng thái vẫn đúng.
- Chưa có kiểm thử tự động cho `toggle_theme`; việc này mới kiểm bằng tay.
- Media chỉ lấy từ nội dung bài viết. Ảnh trong avatar, chữ ký cuối bài và thanh cảm xúc bị loại có chủ đích.
- Một thread nhiều trang được app bấm "Trang sau" để lấy hết, nhưng mỗi trang phải render xong mới sang trang kế tiếp nên thread dài sẽ chậm.
