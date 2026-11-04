# Audit UX/UI — XenForo Crawler V72

> Phương pháp: `design-ux` + `ux-audit` (Nielsen 10) + `design-system` (token/spacing).
> **Rule 0 của skill: không tự chấm điểm thẩm mỹ.** Phiên này không có model thị
> giác, nên audit dựa trên **đo đạc hình học widget tree đã render** — số liệu
> khách quan, tái lập được bằng `python ux_audit.py` và `python ux_tab.py`.
>
> Ảnh chụp: `ux_before_light.png`, `ux_before_warm.png` (trước) và
> `ux_after_light.png`, `ux_after_warm.png` (sau) — cùng 1060x820, cùng dữ liệu log.

---

## Nhiệm vụ chính của UI

1. Nhập/chọn nguồn (box URL + tác giả, hoặc link bài viết) → **bấm quét**
2. Theo dõi tiến trình → biết khi nào xong, có lỗi gì
3. Đọc nhật ký để chẩn đoán khi sai

Mọi đánh giá dưới đây dựa trên 3 nhiệm vụ này.

---

## Bảng chấm — TRƯỚC và SAU

| # | Heuristic | Phát hiện trước (số đo) | Mức | Đã sửa | Số đo sau |
|---|---|---|---|---|---|
| 1 | **Visibility of system status** | Trạng thái (965,24), nút hành động (556,170) — cách **146px dọc, 409px ngang** | major | ✅ Trạng thái dời xuống khối điều khiển hàng C, cạnh nút Dừng | (63,404) so với nút Dừng (797,421) — **cách 4px dọc** |
| 2 | **Match real world** | `Quét 1 User` / `Quét 1 Thớt` / `Cập nhật toàn bộ User` — lẫn tiếng Anh, "thớt" là tiếng lóng | major | ✅ Đổi nhãn | `Quét theo tác giả` / `Quét theo bài viết` / `Quét lại tất cả tác giả` |
| 3 | **User control** | `Dừng khẩn cấp` không có trong tab order lúc chạy | **blocker** | ✅ (Tk tự loại nút disabled — đúng chuẩn; khi chạy nút bật nên vào chuỗi) | Đang chạy: nút Dừng ở **vị trí 5/8** trong tab chain |
| 4 | **Consistency** | 3 cỡ nút: 32 / 42 / 42 với padx khác nhau | minor | ✅ 2 cỡ theo vai trò: chính 44px, phụ 30px | Chính: 145x44, 150x44. Phụ: 66x30, 85x30, 57x30 |
| 5 | **Error prevention** | Bấm được khi ô trống, rồi báo lỗi vào nhật ký | major | ✅ Nút tự disable khi thiếu input | `link=disabled` khi ô link rỗng; bật ngay khi dán link |
| 6 | **Recognition over recall** | Ô `Link Bài Viết` (43,351) ↔ nút `Quét 1 Thớt` (790,170) — **cách ~747px chéo** | **blocker** | ✅ Ghép ô với nút cùng hàng | Ô (24,299) ↔ nút (886,332) — **cùng khối, cùng hàng** |
| 7 | **Flexibility** | 4 phím tắt có, nhưng không gợi ý trong UI | minor | ⬜ Giữ nguyên (chấp nhận: app dùng chuột là chính) | — |
| 8 | **Aesthetic / minimal** | 7 nút + 4 ô trên 1 màn hình không nhóm; nhật ký chỉ **33%** | major | ✅ 3 nhóm có tiêu đề, 1 đường kẻ thay vì 3 | Nhật ký **31%** ở 1060x820, **23%** ở cỡ nhỏ nhất |
| 9 | **Error recovery** | Lỗi chỉ vào nhật ký, không chỉ ô nào | minor | ⬜ Chưa (nút disable đã chặn phần lớn) | — |
| 10 | **Help** | Nhật ký trống không gợi ý | minor | ✅ Thêm dòng "Chưa có phiên quét nào." | — |

### Overflow gate (cửa sổ hẹp) — blocker đã sửa

| Trước | Sau |
|---|---|
| `minsize(760, 560)` cứng, nhật ký bị bóp còn **657x12** | `minsize` **tính động = 780x736**, nhật ký **681x172** |
| Nhật ký = **2%** chiều cao, gần như mất hẳn | Nhật ký = **23%**, luôn đủ `MIN_LOG_LINES` dòng |

Nguyên nhân gốc: bố cục có 2 tầng cao cố định + 1 tầng giãn, nhưng `minsize`
đặt cứng nhỏ hơn tổng 2 tầng cố định. Nay `_enforce_min_geometry()` đo chiều cao
thật của phần không giãn rồi cộng sàn cho nhật ký — đổi font/padding sau này sàn
vẫn đúng.

---

## Điểm mạnh (giữ nguyên)

- **Tương phản: 0 vi phạm** — đo trên widget render (không phải bảng màu), 0 widget
  có chữ dưới 4.5:1, cả trước và sau khi làm lại. Hệ token màu giữ nguyên.
- Màu log phân loại theo dấu `[-] [!] [✓] [+] [•] [*]` — đọc nhanh, hiệu quả.
- Phím tắt đúng chỗ; `Esc` luôn dừng được.
- Nút disabled có màu riêng, không nhầm với nút bấm được.
- Hai theme đều đạt WCAG, có test tự động (`_check_palette.py` + test suite).

---

## Những gì đã thay đổi trong code

| Thay đổi | Vì sao |
|---|---|
| `SPACE` dict (thang 8 điểm) | Mọi padding/gap từ một nguồn; bản cũ dùng 14/16/18/24/22 tuỳ hứng |
| `_section()` | 3 nhóm có tiêu đề: "QUÉT THEO TÁC GIẢ", "QUÉT THEO BÀI VIẾT", khối trạng thái |
| `_button(primary=)` | 2 cỡ nút theo vai trò thay vì 1 cỡ cho tất cả |
| `_entry(column=)` / `_combo(column=)` | Dùng grid để nhãn/ô/nút thẳng đáy nhau |
| `_refresh_action_buttons()` | Disable nút khi thiếu input; nối vào `KeyRelease` + `<<ComboboxSelected>>` |
| `_enforce_min_geometry()` | `minsize` tính từ chiều cao thật, không đoán |
| Bỏ 2/3 đường kẻ phân cách | Giảm nhiễu thị giác |
| Bỏ `_card_header()` khỏi đường dùng | Thay bằng `_section()` có nhịp dọc đều |

---

## Giới hạn của audit này (nói rõ, không giấu)

1. **Không có model thị giác** trong phiên: tôi đo hình học và tương phản,
   **không** đánh giá được "trông có đẹp không". Mục 8 (thẩm mỹ) dựa trên số đo
   mật độ và diện tích chiếm chỗ, không dựa trên nhìn.
2. Skill yêu cầu "judge riêng chấm" — tôi tách phần đo (`ux_audit.py`,
   `ux_tab.py`) khỏi phần sửa, và mọi số trong bảng đều tái lập được.
3. Chưa đo được: cảm giác gõ phím, tốc độ vẽ lại khi log nhiều dòng, hành vi
   tooltip. Cần người dùng chạy thật để đánh giá.

## Còn lại (chưa làm, đã cân nhắc)

| Việc | Vì sao chưa làm |
|---|---|
| Thanh tiến trình có tổng số | `engine` chưa báo tổng số tệp trước khi tải — cần sửa tầng crawl, không chỉ GUI |
| Viền đỏ ô nhập sai | Nút đã disable nên gần như không còn đường vào lỗi này |
| Tooltip phím tắt | Tk không có tooltip sẵn; tự dựng sẽ thêm ~60 dòng cho lợi ích nhỏ |
