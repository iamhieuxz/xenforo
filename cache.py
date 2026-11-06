"""Cache SQLite: đã tải URL nào, nằm ở file nào.

filename lưu ĐƯỜNG DẪN TUYỆT ĐỐI. Bản cũ lưu basename rồi kiểm tra bằng
os.path.join(folder, basename) nên gần như không bao giờ trúng cache -> cùng
một ảnh bị tải lại ở mọi thread.

VỀ THREAD SAFETY: `sqlite3.connect(check_same_thread=False)` chỉ tắt PHÉP KIỂM
của Python, không làm connection thread-safe. Đo thực tế với 4 thread × 300 lần
ghi: 3 exception ("not an error", "no more rows available") và chỉ 322/1200
dòng được ghi — mất 73% dữ liệu, trong khi engine vẫn báo "đã tải xong" nên lần
quét sau tải lại toàn bộ.

Vì vậy mọi truy cập đi qua một RLock. Đây là mức khoá thô, nhưng tần suất ghi
thấp (mỗi file một lần) nên không thành điểm nghẽn.
"""

import os
import sqlite3
import threading
from datetime import datetime


class MediaCache:
    def __init__(self, db_path):
        self._lock = threading.RLock()
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
        # Ngày mở thread + folder đã dùng, để folder KHÔNG đổi tên giữa các lần
        # quét khi server lần sau không trả ngày.
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS thread_index (
                thread_key TEXT PRIMARY KEY,
                date_prefix TEXT,
                folder TEXT,
                updated_at TEXT
            )
        """)
        self._migrate()
        self.conn.commit()

    # ---------- nâng cấp lược đồ ----------

    def _columns(self, table):
        """Tên các cột hiện có của một bảng."""
        try:
            return {r[1] for r in self.conn.execute(
                f"PRAGMA table_info({table})").fetchall()}
        except sqlite3.Error:
            return set()

    def _migrate(self):
        """Thêm cột còn thiếu. Chạy trên DB cũ mà không mất dữ liệu.

        VÌ SAO CẦN content_hash: `url_clean_hash` băm theo URL, không theo nội
        dung. Đo trên ổ thật: cùng một ảnh ở hai URL (thumbnail và bản đầy đủ)
        sinh hai hash khác nhau -> hai file giống hệt, 13,3 % dung lượng thư
        viện bị lặp. Có content_hash thì nhận ra "file này đã có" và hardlink
        thay vì giữ bản sao.

        NULL cho dữ liệu cũ là chấp nhận được: những dòng đó vẫn dùng được qua
        `path_for()`, chỉ không tham gia khử trùng lặp theo nội dung cho tới khi
        được băm lại.
        """
        cols = self._columns("media_index")
        if "content_hash" not in cols:
            try:
                self.conn.execute(
                    "ALTER TABLE media_index ADD COLUMN content_hash TEXT")
            except sqlite3.Error:
                pass
        try:
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_media_content "
                "ON media_index(content_hash)")
        except sqlite3.Error:
            pass

    def record(self, url_hash, abs_path, content_hash=None):
        """Ghi một media đã tải.

        Dùng TÊN CỘT tường minh, không dùng VALUES (?,?,?): bản cũ dùng vị trí
        nên thêm cột content_hash là INSERT hỏng ngay (sai số cột).
        """
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO media_index "
                "(url_clean_hash, filename, downloaded_at, content_hash) "
                "VALUES (?, ?, ?, ?)",
                (url_hash, os.path.abspath(abs_path),
                 datetime.now().isoformat(), content_hash))
            self.conn.commit()

    def path_for_content(self, content_hash, exclude=None):
        """Đường dẫn file ĐÃ CÓ cùng nội dung, hoặc None.

        `exclude` là đường dẫn vừa tải — không được trả về chính nó, nếu không
        chỗ gọi sẽ hardlink file vào chính nó.

        Chỉ trả đường dẫn còn tồn tại trên đĩa: dòng cache trỏ file đã bị xoá
        mà vẫn tin thì hardlink sẽ hỏng.
        """
        if not content_hash:
            return None
        with self._lock:
            rows = self.conn.execute(
                "SELECT filename FROM media_index WHERE content_hash = ? "
                "ORDER BY downloaded_at DESC LIMIT 20", (content_hash,)
            ).fetchall()

        ex = os.path.normcase(os.path.abspath(exclude)) if exclude else None
        for (fn,) in rows:
            if not fn:
                continue
            try:
                ap = os.path.abspath(fn)
                if ex and os.path.normcase(ap) == ex:
                    continue
                if os.path.isfile(ap) and os.path.getsize(ap) > 0:
                    return ap
            except OSError:
                continue
        return None

    def path_for(self, url_hash):
        """Đường dẫn file đã tải, hoặc None. Dữ liệu cũ (basename) bị bỏ qua."""
        with self._lock:
            row = self.conn.execute(
                "SELECT filename FROM media_index WHERE url_clean_hash = ?", (url_hash,)
            ).fetchone()
        if row and row[0] and os.path.isabs(row[0]) and os.path.exists(row[0]):
            return row[0]
        return None

    # ---------- ngày mở thread ----------
    def thread_date(self, thread_key):
        """Ngày YYYY-MM-DD đã biết của thread, hoặc None."""
        with self._lock:
            row = self.conn.execute(
                "SELECT date_prefix FROM thread_index WHERE thread_key = ?", (thread_key,)
            ).fetchone()
        return row[0] if row and row[0] else None

    def remember_thread_date(self, thread_key, date_prefix, folder=None):
        """Ghi nhớ ngày + folder của thread.

        Mục đích: XenForo có lúc không trả ngày (thiếu .p-description, trang lỗi,
        theme khác). Không nhớ thì mỗi lần quét lại ra folder khác -> app coi là
        bài mới và tải lại toàn bộ dù file đã nằm trên đĩa.
        """
        if not date_prefix and not folder:
            return
        with self._lock:
            self.conn.execute(
                "INSERT INTO thread_index (thread_key, date_prefix, folder, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(thread_key) DO UPDATE SET "
                "  date_prefix = COALESCE(NULLIF(excluded.date_prefix, ''), date_prefix), "
                "  folder      = COALESCE(excluded.folder, folder), "
                "  updated_at  = excluded.updated_at",
                (thread_key, date_prefix or "", folder, datetime.now().isoformat()))
            self.conn.commit()

    def close(self):
        with self._lock:
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
        self._lock = getattr(conn, "_lock", threading.RLock())
        with self._lock:
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
        with self._lock:
            self.conn.execute("UPDATE local_users SET last_seen = NULL")
            self.conn.executemany(
                "INSERT INTO local_users (folder_name, last_seen) VALUES (?, ?) "
                "ON CONFLICT(folder_name) DO UPDATE SET last_seen = excluded.last_seen",
                [(n, now) for n in found])
            self.conn.commit()
        return len(found)

    def names(self):
        """Folder còn trên ổ, sắp xếp A-Z."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT folder_name FROM local_users "
                "WHERE last_seen IS NOT NULL ORDER BY folder_name COLLATE NOCASE"
            ).fetchall()
        return [r[0] for r in rows]

    def stale_names(self):
        """Folder đã bị xoá khỏi ổ nhưng row vẫn còn - để bạn tự xử lý."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT folder_name FROM local_users "
                "WHERE last_seen IS NULL ORDER BY folder_name COLLATE NOCASE"
            ).fetchall()
        return [r[0] for r in rows]