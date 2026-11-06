# Phân tích rphang.show — cấu trúc và khả năng cào

> Ngày phân tích: 2026-11-06
> Script tái lập: `analyze_rphang.py`

---

## Về "bypass Cloudflare" — không cần

Tôi kiểm tra trước khi viết bất kỳ dòng code nào. **Không có thử thách nào cả:**

```
https://rphang.show/box/clip-sex-phim-sex.86/   status=200  len=234064  challenge=False
https://rphang.show/box/nhat-ky-may-mua.140/    status=200  len=237283  challenge=False
```

- Header có `Server: cloudflare`, `CF-RAY` — tức là **có đi qua Cloudflare**
- Nhưng **không có** `cf-challenge`, `just a moment`, `challenge-platform`
- HTML trả về đầy đủ, `data-xf="2.3"` (XenForo 2.3) trong thẻ `<html>`

Và media tải được trực tiếp:

```
Ảnh  : status=200  type=image/jpeg    75 535 bytes
Video: status=200  type=video/mp4  10 012 662 bytes
```

**Kết luận:** chỉ cần request HTTP thường với User-Agent hợp lý. Cloudflare ở đây
đang ở chế độ proxy thường, không bật Bot Fight Mode cho đường dẫn này.

> Nếu sau này bật thử thách: đã có sẵn `BROWSER_MODE=cdp` dùng trình duyệt thật
> của bạn, vốn tự giải được challenge. Không cần kỹ thuật "bypass" đặc biệt nào —
> trình duyệt thật + cookie thật là cách duy nhất bền vững.

---

## Cấu trúc site

| Thành phần | Thực tế |
|---|---|
| Nền tảng | XenForo **2.3** |
| Theme | UI.X (đổi nhiều cấu trúc mặc định) |
| Add-on | SAM (Sponsored Ad Manager) chèn quảng cáo xen giữa bài |

### Điểm khác XenForo chuẩn — QUAN TRỌNG

| | XenForo chuẩn | rphang.show |
|---|---|---|
| URL thread | `/threads/<slug>.<id>/` | **`/t/<slug>.<id>/`** |
| Link box | phân trang `?page=2` | `/box/<slug>.<id>/page-2` |

Nếu code giả định `/threads/` thì **không tìm được thread nào**. Code hiện tại
đã dùng selector linh hoạt nên bóc được (đã kiểm chứng: 31 link/trang).

### Box cần theo dõi

| Box | URL | Thread/trang | Tổng trang |
|---|---|---|---|
| Clip Sex / Phim Sex | `/box/clip-sex-phim-sex.86/` | 31 | **989** |
| Nhật ký mây mưa | `/box/nhat-ky-may-mua.140/` | 30 | **347** |

Tổng cộng khoảng **1 336 trang box** nếu quét hết một lượt. Đây là lý do cần cơ
chế "chỉ quét bài mới" thay vì quét lại toàn bộ.

### Cấu trúc box (mỗi dòng)

```html
<div class="structItem structItem--thread" data-author="ngaotran98">
  <div class="structItem-title">
    <a href="/t/<slug>.<id>/">Tiêu đề</a>
  </div>
  ...
</div>
```

- `data-author` → tác giả là người mở thread
- `<div class="structItem-title">` → chứa link thread
- Phân trang: `/box/<slug>.<id>/page-N`

### Cấu trúc thread — media nằm ở đâu

```html
<article class="message--post" data-author="ngaotran98" data-content="post-4241534">
  <article class="message-body">
    <div class="bbWrapper">
      <!-- VIDEO -->
      <source src="/data/attachment-files/2024/08/<id>_<name>.mp4?hash=...&verify=..."/>
      <!-- ẢNH (attachment, KHÔNG phải /data/) -->
      <img src="/attachments/6100248299866013042_121-jpg.1060438/"/>
    </div>
  </article>
</article>
```

**Hai dạng media, đường dẫn khác nhau:**

| Loại | Đường dẫn | Ghi chú |
|---|---|---|
| Video | `/data/attachment-files/<năm>/<tháng>/<file>.mp4?hash=...&verify=...` | có token `verify` |
| Ảnh | `/attachments/<tên>-jpg.<id>/` | trả 302 → CDN ảnh thật |

Ảnh trả **redirect** (302) rồi mới tới file JPEG. Bộ tải hiện tại phải theo
redirect — Playwright/`APIResponse` tự làm việc này.

### Rác phải loại

Đo trên một thread thật:

```
samCodeUnit (quảng cáo add-on SAM):  15 khối
samItem                           :  19
reaction-image (emoji joypixels)  :  36
avatar (/data/avatars/)           :  23
```

Code hiện tại đã lọc được avatar/emoji (nhờ `is_noise_url`), nhưng **chưa lọc
quảng cáo SAM** — quảng cáo nằm *bên trong* `message-body` nên dễ bị bắt nhầm.

---

## Comment của chủ post — cách làm đúng

Yêu cầu: "download... comment của chủ post".

Trong XenForo, mỗi bài là một `<article class="message--post" data-author="...">`.
"Comment của chủ post" = các post **trong cùng thread** có `data-author` trùng
với tác giả thread. Thread mẫu có 19 trang:

```
[0] ngaotran98        post-4241534   media=95   <- chủ post, 95 file
[1] Darren            post-4241616   media= 0   <- người khác
[2] Timemtrongdem9    post-4241619   media= 0
[4] halimah           post-4241637   media= 1
...
trang kế: /t/<slug>/page-2
```

Code hiện tại đã lọc đúng: `crawl_thread` chỉ lấy post có `data-author` khớp
tác giả thread, và duyệt qua `next_page_url`. **Đã kiểm chứng hoạt động.**

---

## Những gì cần sửa

| # | Vấn đề | Mức độ |
|---|---|---|
| 1 | Quảng cáo SAM trong `bbWrapper` có thể lọt vào media | **Phải sửa** |
| 2 | 1 336 trang box — cần cơ chế "chỉ bài mới" | **Phải sửa** |
| 3 | Video attachment-files có token `verify` hết hạn — URL cache sẽ chết | Nên sửa |
| 4 | Thread nhiều trang (tới 19) — tải hết là nặng | Nên cân nhắc |

### Về token `verify` (điểm 3)

URL video có dạng:
```
/data/attachment-files/2024/08/<id>_<name>.mp4?hash=HxNNYSbS0J&verify=1793923200-cPBt...
```
`verify` chứa **timestamp** (`1793923200` ≈ năm 2026-11). Khi hết hạn, URL cũ
trả 403. Nghĩa là:

- **Không được cache URL** để tải lại sau nhiều ngày
- Phải lấy URL mới từ HTML mỗi lần chạy
- Nhưng **file đã tải rồi** vẫn khử trùng lặp bình thường (dựa trên hash URL
  sạch, không gồm token) — cơ chế hiện tại đã đúng vì `_clean_url` cắt query

Đã kiểm tra: hash dựa trên URL **sau khi cắt `?hash=&verify=`**, nên cùng một
video không bị tải lại dù token đổi. Tốt.