"""Cấu hình tập trung. Đổi ở đây, không rải trong các module khác."""

import os

# Thư mục gốc. Trỏ biến môi trường RPHANG_DIR để chạy thử không cần sửa code.
DOWNLOAD_DIR = os.environ.get('RPHANG_DIR', r"E:\HIDE\RPHANG")

# ---------- Nhật ký ra file ----------
# Bản trước chỉ giữ log trong RAM nên đóng app là mất. Khi cần debug một phiên
# đã qua thì không còn gì để đọc — mọi chẩn đoán phải đoán lại. Đây là lý do
# có các thiết lập dưới.
#
# Mỗi phiên một file, tên có timestamp: session-20261106-143812.log
# Ghi ngay sau từng dòng (flush) để app bị kill vẫn còn log tới dòng cuối.
LOG_DIR = os.environ.get("V72_LOG_DIR") or os.path.join(DOWNLOAD_DIR, "logs")

# Số phiên giữ lại. Mỗi phiên vài trăm KB; 30 phiên khoảng vài MB.
LOG_KEEP_SESSIONS = 30

# Mức thấp nhất được ghi: DEBUG | INFO | WARN | ERROR.
# DEBUG ghi cả dòng "bỏ qua", "trùng" — hữu ích khi rà lỗi, nhưng file to hơn.
LOG_MIN_LEVEL = os.environ.get("V72_LOG_LEVEL", "DEBUG")

# Tắt hẳn ghi file (đặt V72_LOG_FILE=0) nếu không muốn tạo thư mục logs.
LOG_TO_FILE = os.environ.get("V72_LOG_FILE", "1") not in ("0", "false", "False")

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
BROWSER_PROFILE = "v72_crawl"   # profile riêng của app (mặc định)

# Trình duyệt dùng cho mode CDP: "chrome" | "coccoc" | "edge".
#
# Vì sao cần khai báo rõ: trước đây launch() gọi find_browser() và lấy ứng viên
# ĐẦU TIÊN trong danh sách — mà danh sách xếp Cốc Cốc trước Chrome. Kết quả là
# bấm Quét thì app mở một cửa sổ Cốc Cốc trắng trơn bên cạnh trình duyệt bạn
# đang dùng, không cookie, không extension. Đó chính là "một đống bùi nhùi".
CDP_BROWSER = os.environ.get("V72_CDP_BROWSER", "coccoc")

# Profile thật của trình duyệt để DÙNG LẠI PHIÊN ĐÃ ĐĂNG NHẬP.
#
# Đặt USE_REAL_PROFILE = True thì app mở profile gốc của Cốc Cốc/Chrome thay vì
# profile riêng của app. Nhờ vậy có ngay cookie, extension và phiên đăng nhập —
# không phải đăng nhập lại.
#
# ĐO ĐƯỢC (máy người dùng, 2026-11): profile Cốc Cốc có 783 cookie, trong đó
# xf_user cho rphang.show / rphang.beer / rphang.fish / rphang.now / rphang.shop
# / xamvn.* / thiendia5.com. Profile riêng của app chỉ có 5 cookie.
#
# ĐIỀU KIỆN: phải ĐÓNG HẾT trình duyệt trước. Chromium giữ khoá độc quyền trên
# file Cookies của profile đang mở (đo được: chỉ file đó bị khoá), nên không mở
# được cổng debug trên profile đang chạy.
#
# RỦI RO: app ghi vào profile thật (cookie, history, extension state). Chấp nhận
# được khi bạn muốn dùng phiên có sẵn; đổi về False nếu muốn profile tách riêng.
USE_REAL_PROFILE = os.environ.get("V72_USE_REAL_PROFILE", "1") not in ("0", "false", "False")

# ---------- Cách điều khiển trình duyệt ----------
# "cdp" — nối vào cổng debug của Chrome ĐANG CHẠY (mặc định).
#   Bạn mở Chrome như bình thường, đăng nhập, rồi app bám vào chính cửa sổ đó.
#   App KHÔNG mở thêm cửa sổ nào, KHÔNG tạo profile mới.
#   Nhược điểm đã đo: một tiến trình lạ chiếm cổng làm app tưởng Chromium sẵn
#   sàng; "localhost" resolve ra ::1 trước 127.0.0.1 nên request có thể bị
#   refuse; xung đột với công cụ khác cũng muốn cổng 9222. App đã có
#   probe_port() phân biệt ba trạng thái để báo rõ từng trường hợp.
#
# "persistent" — Playwright tự mở trình duyệt với profile riêng của app.
#   Không cần cổng TCP. Nhưng đây là profile MỚI: trắng trơn, không có cookie,
#   không có extension, không có bookmark -> phải đăng nhập lại từ đầu. Đó là
#   lý do đổi mặc định về "cdp".
#
# Đổi bằng biến môi trường V72_BROWSER_MODE nếu muốn thử cả hai.
BROWSER_MODE = os.environ.get("V72_BROWSER_MODE", "cdp")

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

# ---------- Tốc độ dò ----------
# Tải HTML bằng HTTP thuần, song song, KHÔNG qua trình duyệt.
#
# Đo được trên rphang.show (8 trang box):
#     HTTP thuần, 8 luồng      0,56s  -> 14,2 trang/giây
#     Trình duyệt, 8 song song 0,69s  -> 11,6 trang/giây
# HTTP nhanh hơn và không tốn RAM render (~55 MB/tab). Hai box người dùng theo
# dõi có 989 + 347 = 1.336 trang: HTTP 8 luồng khoảng 95 giây.
#
# Trình duyệt chỉ dùng khi HTTP thất bại (trang cần JS, hoặc bị thử thách).
USE_HTTP_FIRST = True
HTTP_WORKERS = 12       # số request song song; 8-16 là vùng an toàn đã đo
HTTP_TIMEOUT = 30
HTTP_RETRIES = 2        # số lần thử lại khi lỗi mạng/5xx

# Chỉ quét bài MỚI: dừng đọc trang box khi cả trang toàn thread đã có trong
# SQLite. 1.336 trang là quá nhiều để quét lại mỗi lần; bài mới luôn nằm ở
# trang đầu.
STOP_ON_KNOWN_THREAD = True
BOX_MAX_PAGES = 0       # 0 = không giới hạn; đặt 20 nếu chỉ muốn 20 trang mới nhất

# Số trang thread tối đa được duyệt (thread có thể tới 19 trang).
THREAD_MAX_PAGES = 0    # 0 = không giới hạn

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
#
# Hai box đầu là box người dùng theo dõi, đặt lên trước cho tiện chọn. Đã đo
# quy mô thật (2026-11): clip-sex-phim-sex có 31 thread/trang × 989 trang;
# nhat-ky-may-mua có 30 × 347. Với STOP_ON_KNOWN_THREAD bật, lần chạy sau chỉ
# đọc vài trang đầu là dừng.
BOX_PRESETS = [
    "https://rphang.show/box/clip-sex-phim-sex.86/",
    "https://rphang.show/box/nhat-ky-may-mua.140/",
    "https://rphang.beer/box/clip-sex-phim-sex.86/",
    "https://rphang.beer/box/nhat-ky-may-mua.140/",
    "https://rphang.kim/box/nhat-ky-may-mua.140/",
    "https://rphang.beer/box/thap-cam-box.6/",
    "https://rphang.beer/box/thap-cam-mien-bac.99/",
    "https://rphang.beer/box/some-swing-yoni-mien-bac.116/",
]