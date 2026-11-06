"""Giao diện Fluent của XenForo Crawler — tách từ gui_fluent.py (P2.1).

Cấu trúc:
    worker.py   — QThread chạy engine (WorkerSignals, CrawlWorker)
    log_view.py — widget nhật ký + bảng màu + swallow()
    crawler_view.py — trang quét chính
    settings_view.py — trang cài đặt
    main_window.py   — cửa sổ chính
    __init__         — main() giữ đường chạy cũ: python gui_fluent.py

VÌ SAO TÁCH: gui_fluent.py lên 1507 dòng chứa 5 class + hàm tiện ích + main().
Lỗi bug thường trốn ở file dài vì review không đọc hết; từng lần sửa phải cuộn
tìm đoạn liên quan. Mỗi file sau tách < 600 dòng, một việc một file.
"""

from ui.log_view import swallow, LOG_COLORS_LIGHT, LOG_COLORS_DARK, detect_log_tag
from ui.worker import WorkerSignals, CrawlWorker
from ui.crawler_view import CrawlerInterface
from ui.settings_view import SettingsInterface
from ui.main_window import MainWindow, main

__all__ = [
    "swallow", "LOG_COLORS_LIGHT", "LOG_COLORS_DARK", "detect_log_tag",
    "WorkerSignals", "CrawlWorker",
    "CrawlerInterface", "SettingsInterface", "MainWindow", "main",
]
