# Bỏ cổng 9222 để dùng session Cốc Cốc có sẵn — đánh giá khả thi

> Mọi kết luận dưới đây đều từ **thực nghiệm trên máy bạn**, không suy đoán.
> Script tái lập: `probe_cdp.py`, `probe_persistent.py`.

---

## Kết luận ngắn

**KHẢ THI**, nhưng **không phải bằng cách đọc cookie** — mà bằng cách **để trình
duyệt tự mở profile của nó**. Đây là điểm mấu chốt, và nó thay đổi toàn bộ thiết kế.

Điều kiện bắt buộc: **Cốc Cốc phải đóng** trong lúc lấy profile.

---

## Bằng chứng thực nghiệm

### 1. `launch_persistent_context` chạy được với Cốc Cốc 154 — 4/4 PASS

```
executable : C:\Program Files\CocCoc\Browser\Application\browser.exe
version    : 154.0.8037.106

[PASS] launch_persistent_context thành công
[PASS] mở được page
[PASS] đọc được DOM          (nội dung: 'XIN CHAO')
[PASS] add_cookies / cookies() hoạt động
```

Playwright 1.54 pin Chromium cũ hơn Cốc Cốc 154 rất nhiều, nhưng vẫn điều khiển
được. **Không cần cổng 9222, không cần `connect_over_cdp`.**

Đo thêm: khởi động **0.56s**, mở tab mới **0.04s**, `ctx.request.get` trả 200.
Tức là vẫn tải media được như hiện tại.

### 2. Session **có** lưu qua các lần chạy

Thí nghiệm 3 lần mở/đóng liên tiếp trên cùng profile:

```
LAN 1: đặt cookie qua document.cookie  -> DB ghi 1 cookie (encrypted 70B)
SAU MO LAI: document.cookie = 'realck=realval'   <- session sống
```

Lưu ý quan trọng tôi phát hiện khi làm: `ctx.add_cookies()` **không** ghi xuống
đĩa ngay (đo được 0 cookie sau khi mở lại ở cả 4 biến thể headless/wait/goto).
Chỉ cookie đặt qua trang web mới được persist. Đây là hành vi của Playwright,
không phải lỗi — nhưng nếu làm tính năng "đăng nhập rồi lưu" thì phải biết.

### 3. Rào cản thật: **Chromium khoá độc quyền file Cookies**

Đây là phát hiện quyết định. Khi Cốc Cốc đang chạy:

```
Network/Cookies                      BI KHOA    (360448 bytes)  <- độc quyền
Preferences                          DOC DUOC   (100592 bytes)
History                              DOC DUOC   (9338880 bytes)
Web Data                             DOC DUOC   (196608 bytes)
Network/Network Persistent State      DOC DUOC   (112770 bytes)
```

**Chỉ `Cookies` bị khoá.** Mọi file khác đọc bình thường. Vì vậy đây **không
phải** sandbox chặn tôi — đây là Chromium giữ khoá SQLite độc quyền trên đúng
file cookie. Không có quyền nào vượt được, kể cả Administrator.

Hệ quả: **không thể đọc cookie khi trình duyệt đang chạy.** Phải đóng nó.

### 4. Đường giải mã cookie: chạy được, nhưng KHÔNG cần

Tôi vẫn kiểm chứng để biết giới hạn. Trên profile do Playwright tạo:

```
Local State encrypted_key: prefix b'DPAPI' (279B)
[OK] DPAPI giải mã key: 32B
[OK] example.com/secret_ck = 'HELLO_WORLD_12345'   (AES-GCM v10)
```

Tức là đường `DPAPI → AES-256-GCM` hoạt động đầy đủ.

**Nhưng không nên dùng đường này**, vì hai lý do:

1. Chrome/Cốc Cốc từ bản 127 dùng **App-Bound Encryption (`v20`)**, khoá gắn với
   tiến trình Chrome qua service hệ thống — giải mã ngoài Chrome là không được.
   Tôi **chưa xác định được** Cốc Cốc 154 dùng `v10` hay `v20`, vì không đọc
   được file cookie thật khi nó đang chạy. Đây là **ẩn số chưa giải**.
2. Không cần thiết. Nếu đưa nguyên profile cho trình duyệt, **chính nó** giải mã
   cookie bằng khoá của nó. Không phải đụng tới DPAPI, không phải quan tâm v10/v20.

---

## Hai phương án

### Phương án A — Copy profile rồi mở trên bản copy (KHUYÊN DÙNG)

```
1. Người dùng đóng hẳn Cốc Cốc
2. Copy  <CocCoc>\User Data  ->  %LOCALAPPDATA%\V72Crawler\coc_session
   (bỏ qua Cache/Code Cache/GPUCache: đo được copy phần cần thiết rất nhanh)
3. launch_persistent_context(user_data_dir=<bản copy>, executable_path=<Cốc Cốc>)
4. Trình duyệt tự giải mã cookie bằng khoá của nó -> đã đăng nhập
```

**Đã chứng minh:** bước 3 chạy được (4/4 PASS); bước 2 chỉ thất bại đúng ở file
`Cookies` **vì Cốc Cốc còn chạy** — đóng nó là hết.

Ưu: không đụng profile thật, không rủi ro hỏng dữ liệu người dùng.
Nhược: session là **bản chụp**, đăng nhập mới trong Cốc Cốc thật không tự sang.

### Phương án B — Mở thẳng profile thật

```
1. Đóng Cốc Cốc
2. launch_persistent_context(user_data_dir=<User Data thật>)
```

Ưu: luôn dùng session mới nhất, không cần copy.
Nhược: app ghi vào profile thật (cookie, history, extension state). Nếu app
crash giữa chừng có thể để lại profile hỏng. **Rủi ro cao hơn A.**

> Tôi **chưa kiểm chứng được** phương án B: môi trường hiện tại chặn ghi vào
> `%LOCALAPPDATA%\...\User Data` nên trình duyệt không tạo được ProcessSingleton.
> Đây là giới hạn môi trường test, **không phải kết luận sản phẩm**. Cần bạn
> chạy thử trên phiên bình thường.

### Phương án C — Giữ nguyên cổng 9222 (hiện tại)

Không dùng session có sẵn; người dùng đăng nhập trong profile riêng của app
(`V72Crawler\v72_crawl`, đã có sẵn Cookies DB). Đây là trạng thái hiện tại và
**vẫn hoạt động tốt** — tôi vừa gia cố phần kiểm soát cổng.

---

## Điều KHÔNG khả thi (nói rõ để khỏi mất thời gian)

| Ý tưởng | Vì sao không |
|---|---|
| Đọc cookie khi Cốc Cốc đang chạy | Chromium khoá độc quyền file `Cookies`. Đã đo. |
| Giải mã cookie ngoài trình duyệt | Nếu là `v20` (App-Bound, từ bản 127) thì không được. Chưa xác định Cốc Cốc 154 dùng loại nào. |
| Dùng `--remote-debugging-port` trên profile đang chạy | Tiến trình thứ hai bị từ chối: `exit 0xFFFF0001`. Đã đo với `browser.exe` và `chrome.exe`. |
| Bật cổng debug cho một tab đang mở sẵn | Chrome không hỗ trợ; cổng chỉ bật lúc khởi động. |

---

## Kế hoạch triển khai (nếu bạn duyệt phương án A)

| Bước | Việc | Kiểm chứng |
|---|---|---|
| 1 | `session_source.py`: dò profile Cốc Cốc/Chrome, kiểm tra đang chạy (`_listening_pid` + `tasklist`), copy an toàn bỏ qua cache | Copy xong, so số file & kích thước |
| 2 | `engine.connect()`: thêm nhánh `mode="persistent"` bên cạnh `mode="cdp"` | `probe_persistent.py` 4/4 PASS hiện có |
| 3 | `config.py`: thêm `BROWSER_MODE = "persistent" \| "cdp"`, `SESSION_PROFILE` | Đổi mode chạy được cả hai |
| 4 | GUI: nút "Dùng phiên Cốc Cốc", cảnh báo phải đóng trình duyệt | Manual: đóng Cốc Cốc -> bấm -> đã đăng nhập |
| 5 | Giữ nguyên CDP làm đường dự phòng | 154 test cũ vẫn xanh |

**Rủi ro cần bạn quyết:**

- Copy profile chứa toàn bộ cookie, mật khẩu đã lưu, lịch sử. Đây là dữ liệu
  nhạy cảm nằm trong `V72Crawler\`. Cần bạn đồng ý.
- Session là bản chụp: đăng nhập mới trong Cốc Cốc sẽ không tự sang. Cần nút
  "làm mới phiên" (copy lại).

---

## Việc tôi đã sửa xong trong đợt review này

Không phải đề xuất — đã sửa và có test:

| Lỗi | Bằng chứng trước | Sau |
|---|---|---|
| **MediaCache mất dữ liệu** khi 2 thread cùng ghi | 4 thread × 300 = **322/1200 dòng**, 3 exception | **1200/1200, 0 lỗi** (thêm `RLock`) |
| **CDP_URL không theo CDP_PORT** | Đổi port → vẫn nối 9222 | Suy ra từ `CDP_PORT` |
| **`localhost` resolve ra `::1`** | Chromium bind IPv4 → refuse | Dùng `127.0.0.1` |
| **`is_port_open` bị đánh lừa** | Server lạ chiếm cổng → `True` | `probe_port()` phân biệt 3 trạng thái |
| **`launch()` bỏ qua khi cổng bị chiếm** | Trả "đã sẵn sàng" rồi connect fail | Báo rõ PID đang giữ cổng |
| **Trình duyệt mồ côi** | Mỗi lần chạy để lại 1 cửa sổ | `shutdown()` dọn tiến trình do app mở |
| **`clean_name` giữ ký tự NUL** | `ValueError: embedded null character` | 12/12 tên ghi được |
| **Tên thiết bị có đuôi lọt** | `con.txt` → `PermissionError` | Chặn theo phần trước dấu chấm |
| **MAX_PATH vượt 260** | Đường dẫn 281 ký tự | Ngân sách động, ≤ 260 |
| **`crawl_users` gather hết** | 500 user → 500 coroutine | **2 worker** cố định |
| **`reload_storage` khi đang quét** | Đóng DB giữa lúc worker ghi | Từ chối + cảnh báo |

Test: **154 + 8 + 21 = 183 test xanh** (`test_v72`, `test_gui_fluent`, `test_review_fixes`),
`audit_repro.py` 4/4, `probe_cdp.py` 13/13.
