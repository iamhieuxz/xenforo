"""XenForo Crawler V72 — Giao diện Windows 11 Fluent Design (PySide6 + QFluentWidgets).

TỆP NÀY GIỜ LÀ SHIM. Code thật đã tách sang package `ui/` (P2.1 trong
DE-XUAT-CAI-TIEN.md) vì gui_fluent.py lên 1507 dòng — 5 class + tiện ích +
main() trong một tệp. Mọi đường chạy cũ vẫn như cũ:

    python gui_fluent.py        (tệp này)
    from gui_fluent import MainWindow, CrawlWorker, ...

Nếu bạn import trực tiếp từ gui_fluent, các tên dưới đây vẫn có — giữ lại để
các script và test không phải đổi chỗ nào hết.
"""

from ui import (  # noqa: F401 — re-export có chủ ý cho tương thích ngược
    MainWindow,
    CrawlWorker,
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
