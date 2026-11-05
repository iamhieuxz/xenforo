# Bỏ cổng 9222 — kết quả thực hiện

> Trạng thái: **HOÀN TẤT** — đã triển khai, đã kiểm chứng.
> Ngày: 2026-11-06

---

## Câu hỏi ban đầu

> "Có thể bỏ cổng 9222 để tận dụng session có sẵn trên Cốc Cốc không?"

**Trả lời: CÓ.** Và tốt hơn dự kiến — bạn **không cần** dùng Cốc Cốc.

---

## Hai phát hiện quyết định

### 1. Login 1 lần là dùng mãi — vì profile cố định

Đo được: `user_data_dir` là một thư mục cố định trên ổ. Trình duyệt ghi cookie
vào đó, lần sau mở lại đọc từ chính thư mục đó.

```
PHẦN 1 — profile CỐ ĐỊNH
  Lần 1 (đăng nhập) : đặt được cookie = True
  Lần 2 (mở lại)    : còn cookie = True
  Lần 3 (mở lại)    : còn cookie = True
  => LOGIN 1 LẦN, CÁC PHIÊN SAU TỰ ĐỘNG PASS

PHẦN 2 — profile MỚI mỗi lần (đối chứng)
  => mỗi lần đổi thư mục = mất session, phải login lại
```

### 2. Profile hiện tại của app ĐÃ có session

Không cần chuyển sang trình duyệt khác để lấy session — nó đã có sẵn:

```
Profile: %LOCALAPPDATA%\V72Crawler\v72_crawl
  268 cookie, 79 host
  rphang.beer   xf_user    hết hạn 2027-10-22 (còn 350 ngày)  <-- cookie đăng nhập
  Session cookie (mất khi đóng trình duyệt): 0
```

`xf_user` là cookie xác thực XenForo, còn hạn 350 ngày, không phải session cookie.
Nghĩa là **đã đăng nhập và đã lưu**.

Vậy vấn đề không phải "profile nào", mà là **cách kết nối**: app đang dùng
`connect_over_cdp` tới cổng 9222 thay vì mở trình duyệt trực tiếp.

---

## Điều đã triển khai

### `config.py` — thêm chế độ

```python
BROWSER_MODE = "persistent"     # "persistent" (mới) | "cdp" (dự phòng)
SESSION_BROWSER = "chrome"      # "chrome" | "coccoc" | "edge"
SESSION_PROFILE = ""            # rỗng = profile riêng của app
SESSION_HEADLESS = True
SESSION_EXTRA_ARGS = ["--no-sandbox", "--disable-crash-reporter"]
```

Mặc định `persistent` — **không dùng cổng TCP nào**. `cdp` giữ nguyên làm dự phòng.

### `session_source.py` — module mới

Tách khỏi `engine` để test được không cần Playwright:

| Hàm | Việc |
|---|---|
| `default_session_profile(browser)` | Profile **cố định** theo trình duyệt |
| `resolve_profile()` | Ưu tiên `SESSION_PROFILE`, không thì mặc định |
| `find_installed_profiles()` | Dò profile Chrome/Cốc Cốc/Edge trên máy |
| `is_browser_running(browser)` | Trình duyệt có đang chạy (tasklist) |
| `profile_is_writable(path)` | Kiểm quyền ghi **trước** khi mở |
| `copy_profile(src, dst)` | Copy profile, bỏ cache, báo file bị bỏ |
| `read_cookie_summary(profile)` | Đọc tóm tắt cookie khi trình duyệt đóng |

### `engine.py` — hai nhánh

```python
async def connect(self, p):
    mode = config.BROWSER_MODE
    if mode == "cdp":
        return await self._connect_cdp(p)      # đường cũ
    return await self._connect_persistent(p)   # mặc định, không cần cổng
```

`_connect_persistent()` kiểm **trước khi mở**:

1. Có exe trình duyệt không — `find_browser_for("chrome")` (không trộn loại:
   profile Chrome đưa cho Cốc Cốc sẽ hỏng dữ liệu).
2. Profile ghi được không — thiếu quyền thì Chromium báo "Failed to create a
   ProcessSingleton", thông báo đó không nói được nguyên nhân thật.
3. Trình duyệt đang chạy trên chính profile đó không — nếu có sẽ bị khoá.

Thêm `close_browser()`: ở mode persistent phải đóng context (của app), ở mode
CDP **không đóng** (trình duyệt là của người dùng).

### `gui_fluent.py` — nút Đăng nhập

Trang Cài đặt có nhóm **Phiên đăng nhập**:

- Thẻ **Đăng nhập** → mở trình duyệt **có cửa sổ** với đúng `user_data_dir`
  mà lúc quét sẽ dùng. Đăng nhập xong đóng lại là xong.
- Hiển thị trình duyệt đang dùng, đường dẫn profile, và cảnh báo nếu trình duyệt
  đang chạy.

---

## Kiểm chứng

### Test tự động — 207 test xanh

```
test_v72.py               154 test   OK
test_review_fixes.py       21 test   OK
test_persistent_mode.py    24 test   OK
test_gui_fluent.py          8 test   OK
```

### Kiểm chứng đầu-cuối với trình duyệt thật

**`probe_persistent_mode.py` — 8/8 PASS** trên code thật:

```
[*] Trình duyệt: chrome.exe | profile: ... | ẩn
[PASS] connect() trả về context
[PASS] mở và render page được
[PASS] ctx.request.get hoạt động          status=200
[PASS] close_browser() không ném exception
[PASS] _browser đã reset
[PASS] context sau close không dùng được
[PASS] lần 1 đặt được cookie
[PASS] lần 2 còn cookie (session sống)    <- đây là cả câu hỏi của bạn
```

**`probe_cdp.py` — 13/13 PASS**: cổng CDP vẫn được kiểm soát đúng làm dự phòng.

**`audit_repro.py` — 4/4**: các lỗi P0 vẫn đã sửa.

### Vì sao dùng Chrome chứ không Cốc Cốc

Đo được trên máy bạn:

| | Chrome | Cốc Cốc |
|---|---|---|
| Đang chạy | **Không** (0 process) | **Có** (16 process) |
| Dùng profile được ngay | **Có** | Không — phải đóng trước |

Đó là lý do `SESSION_BROWSER = "chrome"` là mặc định.

---

## Rào cản kỹ thuật đã xác định (không khắc phục được)

### Chromium khoá độc quyền file `Cookies`

Khi trình duyệt đang chạy:

```
Network/Cookies          BI KHOÁ    (360448 bytes)  <- độc quyền
Preferences              đọc được   (100592 bytes)
History                  đọc được   (9338880 bytes)
Web Data                 đọc được   (196608 bytes)
Network/Network Persistent State      đọc được   (112770 bytes)
```

**Chỉ `Cookies` bị khoá**, mọi file khác đọc bình thường. Vì vậy đây không phải
sandbox chặn tiến trình gọi — là Chromium giữ khoá SQLite độc quyền. Không có
quyền nào vượt được, kể cả Administrator.

Hệ quả: muốn dùng profile của trình duyệt đang chạy thì **phải đóng nó**. App
kiểm tra điều này và báo rõ thay vì thất bại với thông báo khó hiểu.

### Đường giải mã cookie: chạy được nhưng không cần

Đã kiểm chứng để biết giới hạn:

```
Local State encrypted_key: prefix b'DPAPI' (279B)
[OK] DPAPI giải mã key: 32B
[OK] example.com/secret_ck = 'HELLO_WORLD_12345'   (AES-256-GCM v10)
```

Hoạt động đầy đủ. **Nhưng không dùng**, vì:

1. Từ bản 127, Chrome/Cốc Cốc có thể dùng **App-Bound Encryption (`v20`)** — khoá
   gắn với tiến trình Chrome qua service hệ thống, không giải mã ngoài Chrome được.
   **Chưa xác định được** Cốc Cốc 154 dùng `v10` hay `v20`, vì không đọc được file
   cookie thật khi nó đang chạy.
2. Không cần. Đưa profile cho trình duyệt thì **chính nó** giải mã cookie bằng khoá
   của nó. Không đụng DPAPI, không cần biết v10 hay v20.

---

## Cách dùng

### Lần đầu (chỉ một lần)

```
1. Mở app:  python gui_fluent.py
2. Vào Cài đặt → Phiên đăng nhập → bấm "Đăng nhập"
3. Trình duyệt mở ra → đăng nhập diễn đàn
4. ĐÓNG trình duyệt đó
5. Bấm "Quét" — phiên đã được dùng lại
```

### Các lần sau

Không làm gì cả. Mở app, bấm Quét. Session đã nằm trong profile.

### Muốn dùng profile Chrome có sẵn

```python
# config.py
SESSION_BROWSER = "chrome"
SESSION_PROFILE = r"C:\Users\<bạn>\AppData\Local\Google\Chrome\User Data"
```

**Phải đóng Chrome trước.** App sẽ báo nếu nó đang chạy.

### Quay lại chế độ cũ

```python
BROWSER_MODE = "cdp"
```

---

## Còn lại / rủi ro

| Việc | Trạng thái |
|---|---|
| Kiểm chứng trên profile Chrome **thật** (đọc `xf_user`) | **Chưa làm được** — sandbox chặn ghi `%LOCALAPPDATA%` nên Chromium không tạo được ProcessSingleton. Cần bạn chạy trên phiên bình thường. |
| Cốc Cốc 154 dùng v10 hay v20 | **Chưa xác định** — không đọc được cookie khi Cốc Cốc đang chạy. Không ảnh hưởng thiết kế vì không dùng đường giải mã. |
| Áp dụng persistent cho `v72.py` (Tkinter) | **Chưa làm** — đã làm cho Qt (`gui_fluent.py`). Cơ chế dùng chung nên chỉ cần thêm nút tương tự. |
| Rủi ro: app ghi vào profile thật | Có. Chỉ nên dùng nếu chấp nhận. Mặc định (profile riêng) không có rủi ro này. |