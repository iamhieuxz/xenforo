"""SHIM tương thích ngược — điểm vào chính đã chuyển sang app.py.

Tệp này chỉ re-export từ package `ui/` để 19 file test/probe/script cũ dùng
`import gui_fluent` hoặc `from gui_fluent import MainWindow` vẫn chạy mà
không cần sửa. Chạy app thì dùng:

    python app.py
"""

from ui import (  # noqa: F401 — re-export có chủ ý cho tương thích ngược
    MainWindow,
    CrawlWorker,
    WorkerSignals,
    CrawlerInterface,
    SettingsInterface,
    swallow,
    detect_log_tag,
    LOG_COLORS_LIGHT,
    LOG_COLORS_DARK,
    main,
)

if __name__ == "__main__":
    main()
