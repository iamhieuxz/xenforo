"""Cấu hình tập trung. Đổi ở đây, không rải trong các module khác."""

import os

# Thư mục gốc. Trỏ biến môi trường RPHANG_DIR để chạy thử không cần sửa code.
DOWNLOAD_DIR = os.environ.get('RPHANG_DIR', r"E:\HIDE\RPHANG")

# Chrome phải chạy --remote-debugging-port=9222
# Đặt CDP_PORT trước rồi suy ra URL. Trước đây hai giá trị là hai literal độc
# lập: đổi CDP_PORT sang 9333 thì CDP_URL vẫn là localhost:9222 -> app nói
# "đổi cổng được" nhưng thực chất kết nối sai cổng cũ.
#
# Dùng 127.0.0.1 chứ KHÔNG dùng localhost: trên Windows, localhost resolve ra
# ::1 (IPv6) TRƯỚC 127.0.0.1, trong khi Chromium --remote-debugging-port chỉ
# bind IPv4. Khi ::1 được ưu tiên, request tới localhost bị refuse/timeout dù
# trình duyệt đang chạy đúng.
CDP_PORT = 9222
CDP_HOST = "127.0.0.1"
CDP_URL = f"http://{CDP_HOST}:{CDP_PORT}"

# App tự mở trình duyệt ở cổng debug khi khởi động. Tắt nếu bạn tự mở tay.
AUTO_LAUNCH_BROWSER = True
BROWSER_PROFILE = "v72_crawl"   # profile riêng, không đụng phiên đang dùng

# ---------- Cách điều khiển trình duyệt ----------
# "persistent" — Playwright tự mở trình duyệt với profile CỐ ĐỊNH (khuyên dùng).
#   Không cần cổng TCP nào; Playwright nói chuyện qua pipe. Session đăng nhập
#   lưu trong profile nên đăng nhập một lần là dùng mãi (đã kiểm chứng: sống
#   qua 3 lần mở/đóng liên tiếp).
# "cdp" — nối vào cổng debug của trình duyệt đang chạy (đường cũ).
#   Giữ lại làm dự phòng khi môi trường không cho Playwright tự mở trình duyệt.
#
# Vì sao "persistent" là mặc định: cổng TCP 9222 có ba nhược điểm đã đo được —
#   (1) một tiến trình bất kỳ chiếm cổng làm app tưởng Chromium đã sẵn sàng;
#   (2) "localhost" resolve ra ::1 trước 127.0.0.1 nên request có thể bị refuse;
#   (3) xung đột với mọi công cụ khác cũng muốn cổng 9222.
BROWSER_MODE = os.environ.get("V72_BROWSER_MODE", "persistent")

# Trình duyệt dùng cho mode "persistent": "chrome" | "coccoc" | "" (tự dò).
# "chrome" được khuyên: Cốc Cốc thường đang chạy sẵn và khoá độc quyền file
# Cookies, nên muốn dùng profile Cốc Cốc thì phải đóng nó trước mỗi phiên.
SESSION_BROWSER = os.environ.get("V72_SESSION_BROWSER", "chrome")

# Thư mục profile cho mode "persistent". Rỗng = mặc định
#   %LOCALAPPDATA%\V72Crawler\session_<browser>
# Đặt một đường dẫn tuyệt đối nếu muốn dùng profile có sẵn (ví dụ profile Chrome
# bạn đã đăng nhập) — xem README mục "Dùng session đăng nhập có sẵn".
SESSION_PROFILE = os.environ.get("V72_SESSION_PROFILE", "")

# Chạy ẩn (headless) khi quét. Đặt False để thấy cửa sổ trình duyệt đang làm việc.
SESSION_HEADLESS = os.environ.get("V72_SESSION_HEADLESS", "1") not in ("0", "false", "False")

# Cờ thêm khi mở trình duyệt ở mode persistent. "--no-sandbox" cần cho một số môi
# trường bị hạn chế quyền (đo được: thiếu nó thì trình duyệt thoát ngay với mã
# 0xFFFF0001). Để rỗng nếu máy bạn chạy bình thường và muốn sandbox bảo vệ.
SESSION_EXTRA_ARGS = ["--no-sandbox", "--disable-crash-reporter"]

# ---------- Giảm bộ nhớ ----------
# App chỉ cần DOM để tìm URL media, KHÔNG cần nhìn thấy ảnh. Chặn tải ảnh/media/
# font ở tầng mạng giảm mạnh RAM và băng thông.
#
# Đo được trên máy thật: mỗi tab Chromium ngốn ~55 MB. Với TAB_SEM=5 là ~600 MB
# chỉ để giữ tab, chưa kể base 322 MB của trình duyệt. Tắt ảnh không làm giảm
# RAM/tab nhiều, nhưng giảm thời gian render và băng thông rõ rệt — trang về
# nhanh hơn nên tab được đóng sớm hơn, tổng RAM đỉnh thấp hơn.
BLOCK_IMAGES = True     # chặn ảnh/font/media: chỉ tải HTML/CSS/JS cần thiết
BLOCK_FONTS = True

# Giới hạn cứng để RAM không vượt ngưỡng:
MAX_OPEN_TABS = 4       # số tab Chromium được tồn tại cùng lúc (cứng, không chỉ semaphore)
MEMORY_SOFT_LIMIT_MB = 1200   # vượt ngưỡng này thì log cảnh báo (không tự kill)

TAB_SEM = 5            # số tab Playwright mở đồng thời
DOWNLOAD_SEM = 10      # số request tải đồng thời
THREAD_SEM = 2         # số thread 1 user được bóc đồng thời
USER_SEM = 2           # số user được xử lý đồng thời

# Chặn cấu hình làm app treo: Semaphore(0) là khoá chết ngay từ đầu, còn giá trị
# âm thì asyncio ném ValueError. Việc acquire lồng nhau ở crawl_link đã được bỏ,
# nhưng vẫn giữ sàn 1 để không ai đặt 0 rồi thắc mắc sao app im lặng.
def _clamp(value, low=1):
    try:
        return max(low, int(value))
    except (TypeError, ValueError):
        return low


TAB_SEM = _clamp(TAB_SEM)
DOWNLOAD_SEM = _clamp(DOWNLOAD_SEM)
THREAD_SEM = _clamp(THREAD_SEM)
USER_SEM = _clamp(USER_SEM)

SETTLE_MS = 0           # XenForo render server-side: đo thực tế settle=0 vẫn ra đủ 20 post.
                        # Tăng lên nếu bạn thấy thiếu bài (mạng chậm thì bọc thêm wait_for_selector).
MAX_RETRIES = 3
DOWNLOAD_TIMEOUT_MS = 40000
NAV_TIMEOUT_MS = 45000
# Số task tải được phép tồn tại cùng lúc trong một thread. Vượt ngưỡng thì engine
# chờ bớt trước khi bóc trang tiếp. Không có nó, thread dài (20 trang × 20 post ×
# 20 ảnh) tạo hàng nghìn task cùng sống dù chỉ DOWNLOAD_SEM cái thực chạy.
PENDING_LIMIT = 80
# Khi đang dừng, timeout tải rút xuống còn ngắn. Playwright hiểu timeout là thời
# gian chờ I/O mỗi lần đọc, nên một video lớn vẫn giữ request sống tới
# DOWNLOAD_TIMEOUT_MS nếu không rút -> nút Dừng trông như treo.
STOP_TIMEOUT_MS = 2000

# Trần kích thước một tệp. 0 = không giới hạn.
# LƯU Ý: Playwright 1.54 KHÔNG có API streaming cho context.request — body() nạp
# toàn bộ payload vào RAM. Vì vậy đây là chốt duy nhất chống hết RAM: kiểm
# content-length TRƯỚC khi gọi body(). Server không gửi content-length thì vẫn
# phải tải trọn (chặn mù sẽ bỏ sót media thật).
MAX_FILE_MB = 512

# Danh sách box gợi ý trong dropdown. Ô nhập vẫn gõ tay được: đổi tên miền
# (rphang.kim -> rphang.beer) hoặc đổi hẳn đường dẫn đều chạy, không ép vào list.
BOX_PRESETS = [
    "https://rphang.kim/box/nhat-ky-may-mua.140/",
    "https://rphang.beer/box/nhat-ky-may-mua.140/",
    "https://rphang.beer/box/thap-cam-box.6/",
    "https://rphang.beer/box/thap-cam-mien-bac.99/",
    "https://rphang.beer/box/some-swing-yoni-mien-bac.116/",
    "https://rphang.beer/box/clip-sex-phim-sex.86/",
]