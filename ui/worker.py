"""QThread chạy engine trong event loop riêng. Tách từ gui_fluent.py (P2.1)."""

import asyncio
import threading

from PySide6.QtCore import QThread, Signal, QObject

import config
from cache import MediaCache
from engine import CrawlerEngine

from ui.log_view import detect_log_tag, swallow

import re


class WorkerSignals(QObject):
    """Signals để truyền dữ liệu an toàn từ async crawler loop sang Qt GUI thread."""
    sig_log = Signal(str, str)             # (message, tag)
    sig_status = Signal(str, str, str)     # (status_text, color_type, detail)
    sig_stats = Signal(int, int, int, str) # (images, videos, errors, detail)
    sig_finished = Signal(bool, bool, str) # (is_stopped, had_error, detail)


class CrawlWorker(QThread):
    """Worker QThread quản lý vòng đời của CrawlerEngine trong event loop riêng."""

    def __init__(self, cache: MediaCache, download_dir: str, stop_event: threading.Event,
                 coro_factory, parent=None):
        super().__init__(parent)
        self.cache = cache
        self.download_dir = download_dir
        self.stop_event = stop_event
        self.coro_factory = coro_factory
        self.signals = WorkerSignals()
        self.current_loop: asyncio.AbstractEventLoop = None
        self.engine: CrawlerEngine = None
        self.had_error = False
        self._n_image = 0
        self._n_video = 0
        self._n_error = 0
        self._last_detail = ""

    def log_bridge(self, message: str, tag=None):
        """Hàm logger được truyền vào engine. Tự động phân tích thống kê và gửi Signal."""
        tag = detect_log_tag(message, tag)
        if tag in ("error", "summary") and message.lstrip().startswith("["):
            self.had_error = True

        m_img = re.search(r"(\d+)\s+ảnh", message)
        if m_img:
            self._n_image += int(m_img.group(1))

        m_vid = re.search(r"(\d+)\s+video", message)
        if m_vid:
            self._n_video += int(m_vid.group(1))

        m_err = re.search(r"(\d+)\s+tệp lỗi", message)
        if m_err:
            self._n_error += int(m_err.group(1))
        elif re.search(r"tệp lỗi", message):
            self._n_error += 1

        parts = []
        if self._n_image or self._n_video:
            parts.append(f"{self._n_image} ảnh · {self._n_video} video")
        if self._n_error:
            parts.append(f"{self._n_error} tệp lỗi")
        self._last_detail = " | ".join(parts)

        self.signals.sig_log.emit(message, tag)
        if parts:
            self.signals.sig_stats.emit(
                self._n_image, self._n_video, self._n_error, self._last_detail)

    def emergency_cleanup(self):
        """Dọn dẹp khẩn cấp khi người dùng bấm Dừng."""
        self.stop_event.set()
        loop = self.current_loop
        if loop and not loop.is_closed():
            try:
                if self.engine:
                    loop.call_soon_threadsafe(self.engine.emergency_cleanup)
            except RuntimeError as e:
                # Loop có thể đã đóng giữa lúc bấm Dừng và lúc chạy dòng này.
                # Nuốt nhưng để lại dấu vết: dọn dẹp thất bại -> tab có thể
                # còn mở, cần biết thay vì im lặng.
                swallow("emergency_cleanup", e)

    def run(self):
        # Event loop phải chạy trên đúng thread này: asyncio quản lý theo
        # thread, tạo ở thread khác rồi run ở đây là lỗi "attached to loop".
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.current_loop = loop
        try:
            self.engine = CrawlerEngine(
                self.cache, self.log_bridge, self.stop_event, download_dir=self.download_dir
            )
            loop.run_until_complete(self.coro_factory(self.engine))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.had_error = True
            msg = f"[-] Lỗi nghiêm trọng trong tiến trình: {e}"
            self.signals.sig_log.emit(msg, "error")
            self.signals.sig_finished.emit(self.stop_event.is_set(), True, str(e)[:200])
            return
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception as e:
                # Dọn task còn treo lúc thoát. Thất bại thì loop vẫn đóng bên
                # dưới, nhưng "Task was destroyed but it is pending" sẽ lộ ra
                # stderr — giờ còn nằm trong log phiên.
                swallow("worker_cleanup", e)
            loop.close()
            self.current_loop = None

        stopped = self.stop_event.is_set()
        detail = self._last_detail
        self.signals.sig_finished.emit(stopped, self.had_error, detail)
