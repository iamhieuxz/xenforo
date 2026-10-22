"""Cấu hình tập trung. Đổi ở đây, không rải trong các module khác."""

import os

# Thư mục gốc. Trỏ biến môi trường RPHANG_DIR để chạy thử không cần sửa code.
DOWNLOAD_DIR = os.environ.get('RPHANG_DIR', r"E:\HIDE\RPHANG")

# Chrome phải chạy --remote-debugging-port=9222
CDP_URL = "http://localhost:9222"
CDP_PORT = 9222

# App tự mở trình duyệt ở cổng debug khi khởi động. Tắt nếu bạn tự mở tay.
AUTO_LAUNCH_BROWSER = True
BROWSER_PROFILE = "v72_crawl"   # profile riêng, không đụng phiên đang dùng

TAB_SEM = 5            # số tab Playwright mở đồng thời
DOWNLOAD_SEM = 10      # số request tải đồng thời
THREAD_SEM = 2         # số thread 1 user được bóc đồng thời
USER_SEM = 2           # số user được xử lý đồng thời

SETTLE_MS = 0           # XenForo render server-side: đo thực tế settle=0 vẫn ra đủ 20 post.
                        # Tăng lên nếu bạn thấy thiếu bài (mạng chậm thì bọc thêm wait_for_selector).
MAX_RETRIES = 3
DOWNLOAD_TIMEOUT_MS = 40000
NAV_TIMEOUT_MS = 45000
# Khi đang dừng, timeout tải rút xuống còn ngắn. Playwright hiểu timeout là thời
# gian chờ I/O mỗi lần đọc, nên một video lớn vẫn giữ request sống tới
# DOWNLOAD_TIMEOUT_MS nếu không rút -> nút Dừng trông như treo.
STOP_TIMEOUT_MS = 2000

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