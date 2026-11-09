# BỘ NHẬN DIỆN THƯƠNG HIỆU & HỆ THỐNG LOGO: XENFORO DOWNLOAD
*Áp dụng các chuẩn mực từ kỹ năng `logo-image-design` và `design-theme-guide`*

---

## 1. Triết lý Thiết kế & Ý nghĩa Biểu trưng (Brand Mark)
- **Tên dự án:** `XenForo Download`
- **Ý nghĩa biểu trưng:**
  - **Chữ 'X' cách điệu hai cánh đan chéo:** Thể hiện nhận diện cốt lõi của nền tảng XenForo (biểu tượng hội thoại, diễn đàn cộng đồng kết nối).
  - **Mũi tên Download sắc nét hướng xuống tâm:** Biểu thị hành động tải xuống dữ liệu, hình ảnh, video với tốc độ cao, độ chính xác tuyệt đối.
  - **Vòng cung gia tốc (Speed Arc Tray):** Thể hiện sự hỗ trợ của công nghệ tải đa luồng, mượt mà và hiện đại.
  - **Khung Squircle công nghệ cao (High-tech Dark Frame):** Phù hợp hoàn hảo với ngôn ngữ Windows 11 Fluent UI & macOS/Web hiện đại.

---

## 2. Bảng mã màu Nhận diện Thương hiệu (Color Tokens)

| Vai trò (Semantic Role) | Tên Token | Mã Hex (Light/Dark) | Ý nghĩa / Cách dùng |
|---|---|---|---|
| **Màu thương hiệu chính** | `color.brand.primary` | `#FF7A00` / `#E65100` | XenForo Orange truyền thống, năng động và nổi bật |
| **Màu công nghệ tương phản** | `color.brand.tech` | `#38BDF8` / `#0284C7` | High-speed Cyan / Blue thể hiện luồng tải kỹ thuật số |
| **Nền biểu tượng (Dark)** | `color.surface.dark` | `#0F172A` | Slate tối sâu thẳm, cao cấp, chuẩn Fluent Design |
| **Đường viền phụ trợ** | `color.stroke.subtle` | `#334155` | Tạo chiều sâu và độ tương phản viền cho icon |
| **Màu mũi tên / Điểm nhấn** | `color.accent.white` | `#F8FAFC` | Màu trắng tinh khiết, tương phản cao trên nền màu |

---

## 3. Danh mục Tệp tin Đồ họa Đã khởi tạo (Asset Register)

Các tệp tin được lưu tại thư mục [`assets/`](./assets/):

1. **`assets/logo.svg`**: Master Vector Mark (512x512) - biểu tượng chính squircle vector, không vỡ nét ở mọi kích thước.
2. **`assets/logo_horizontal.svg`**: Horizontal Lockup (1000x300) - biểu tượng kèm chữ thương hiệu `XENFORO DOWNLOAD` và tagline phụ vụ cho banner, trang web, README.
3. **`assets/app_icon.ico`**: Windows Application Icon đa kích thước (16x16, 32x32, 48x48, 64x64, 128x128, 256x256). Đã được nạp trực tiếp vào thanh tiêu đề và taskbar của cửa sổ chính app.
4. **`assets/logo_512.png`**, **`logo_256.png`**, **`logo_64.png`**, **`logo_32.png`**: Bộ ảnh raster trong suốt tối ưu cho từng vị trí hiển thị (Splash screen, Taskbar, Header UI, Favicon).

---

## 4. Tích hợp Đồng bộ trực tiếp vào Ứng dụng
- **Cửa sổ ứng dụng (`ui/main_window.py`)**:
  - Tiêu đề cửa sổ chuẩn hóa thành: `XenForo Download — V72 Fluent`.
  - Nạp tự động `app_icon.ico` / `logo_256.png` qua `setWindowIcon`.
- **Giao diện quét (`ui/crawler_view.py`)**:
  - Tích hợp Logo 48x48 bo tròn mượt mà vào góc trái tiêu đề trang.
  - Đồng bộ tiêu đề trang thành `XenForo Download`.
