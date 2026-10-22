"""Cache SQLite: đã tải URL nào, nằm ở file nào.

filename lưu ĐƯỜNG DẪN TUYỆT ĐỐI. Bản cũ lưu basename rồi kiểm tra bằng
os.path.join(folder, basename) nên gần như không bao giờ trúng cache -> cùng
một ảnh bị tải lại ở mọi thread.
"""

import os
import sqlite3
from datetime import datetime


class MediaCache:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA busy_timeout=5000;")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS media_index (
                url_clean_hash TEXT PRIMARY KEY,
                filename TEXT,
                downloaded_at TEXT
            )
        """)
        self.conn.commit()

    def record(self, url_hash, abs_path):
        self.conn.execute(
            "INSERT OR REPLACE INTO media_index VALUES (?, ?, ?)",
            (url_hash, os.path.abspath(abs_path), datetime.now().isoformat()))
        self.conn.commit()

    def path_for(self, url_hash):
        """Đường dẫn file đã tải, hoặc None. Dữ liệu cũ (basename) bị bỏ qua."""
        row = self.conn.execute(
            "SELECT filename FROM media_index WHERE url_clean_hash = ?", (url_hash,)
        ).fetchone()
        if row and row[0] and os.path.isabs(row[0]) and os.path.exists(row[0]):
            return row[0]
        return None

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


class LocalUserIndex:
    """Danh sách user đã có trên ổ, đọc nhanh từ SQLite thay vì quét thư mục mỗi lần.

    Đo trên máy thật: os.listdir lần đầu 514ms, các lần sau ~2ms. Cache vào DB
    để lần mở app kế tiếp vào thẳng dropdown, không phải chờ quét ổ.
    """

    def __init__(self, conn):
        self.conn = conn
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS local_users (
                folder_name TEXT PRIMARY KEY,
                last_seen TEXT
            )
        """)
        self.conn.commit()

    def refresh(self, root_dir):
        """Quét thư mục gốc, đồng bộ vào DB. Folder mất trên ổ thì đánh dấu
        stale (giữ row, set last_seen NULL) để bạn còn thấy mà biết là đã xoá.
        """
        found = []
        try:
            with os.scandir(root_dir) as it:
                for e in it:
                    if e.is_dir() and e.name != "__pycache__":
                        found.append(e.name)
        except OSError:
            return 0

        now = datetime.now().isoformat()
        self.conn.execute("UPDATE local_users SET last_seen = NULL")
        self.conn.executemany(
            "INSERT INTO local_users (folder_name, last_seen) VALUES (?, ?) "
            "ON CONFLICT(folder_name) DO UPDATE SET last_seen = excluded.last_seen",
            [(n, now) for n in found])
        self.conn.commit()
        return len(found)

    def names(self):
        """Folder còn trên ổ, sắp xếp A-Z."""
        rows = self.conn.execute(
            "SELECT folder_name FROM local_users "
            "WHERE last_seen IS NOT NULL ORDER BY folder_name COLLATE NOCASE"
        ).fetchall()
        return [r[0] for r in rows]

    def stale_names(self):
        """Folder đã bị xoá khỏi ổ nhưng row vẫn còn - để bạn tự xử lý."""
        rows = self.conn.execute(
            "SELECT folder_name FROM local_users "
            "WHERE last_seen IS NULL ORDER BY folder_name COLLATE NOCASE"
        ).fetchall()
        return [r[0] for r in rows]