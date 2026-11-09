"""XenForo Crawler V72 — Điểm vào chính.

Chạy:
    python app.py

Code giao diện thật nằm trong package `ui/`. Tệp này chỉ re-export để giữ
tương thích ngược: mọi script và test cũ dùng `import gui_fluent` hoặc
`from gui_fluent import MainWindow` vẫn chạy như trước (xem gui_fluent.py).
"""

from ui import main

if __name__ == "__main__":
    main()
