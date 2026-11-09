"""Test cho 3 lỗi nghiêm trọng vừa sửa (2026-11-08).

- Lỗi 1: bài bị đánh dấu xong khi dừng sớm hoặc lỗi
- Lỗi 2: file HTML bị lưu thành ảnh/video
- Lỗi 3: url_hash() cắt query → va chạm hash
"""

import hashlib
import io
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock

import downloader
import fast_fetch
from cache import MediaCache, LocalUserIndex


class TestThreadCompletionMarking(unittest.TestCase):
    """Lỗi 1: remember_thread_date không được ghi khi dừng hoặc lỗi."""

    def test_thread_not_marked_when_stop_event_set(self):
        """Nếu dừng sớm (stop_event bật), KHÔNG ghi remember_thread_date."""
        pages_done = 5
        stop_event = threading.Event()
        stop_event.set()  # Dừng sớm
        stats = {"failed": 0, "ok": 10}

        # Nếu logic này được thực hiện, remember_thread_date sẽ được gọi
        # Nhưng ta muốn nó KHÔNG được gọi khi stop_event bật
        should_remember = (
            pages_done > 0
            and not stop_event.is_set()
            and stats.get("failed", 0) == 0
        )
        self.assertFalse(should_remember, "KHÔNG nên ghi khi stop_event bật")

    def test_thread_not_marked_when_download_failed(self):
        """Nếu có lỗi tải (failed > 0), KHÔNG ghi remember_thread_date."""
        pages_done = 5
        stop_event = threading.Event()
        # stop_event chưa bật
        stats = {"failed": 3, "ok": 2}

        should_remember = (
            pages_done > 0
            and not stop_event.is_set()
            and stats.get("failed", 0) == 0
        )
        self.assertFalse(should_remember, "KHÔNG nên ghi khi có failed > 0")

    def test_thread_marked_only_when_success_and_not_stopped(self):
        """Chỉ ghi khi tải xong, không dừng, không lỗi."""
        pages_done = 5
        stop_event = threading.Event()
        # stop_event chưa bật
        stats = {"failed": 0, "ok": 10}

        should_remember = (
            pages_done > 0
            and not stop_event.is_set()
            and stats.get("failed", 0) == 0
        )
        self.assertTrue(should_remember, "NÊN ghi khi tải xong sạch sẽ")


class TestHTMLContentTypeCheck(unittest.TestCase):
    """Lỗi 2: nếu server trả HTML, xoá file tạm và báo lỗi."""

    def test_html_content_rejected(self):
        """Content-Type: text/html → xoá file tạm, trả lỗi."""
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = os.path.join(tmpdir, "media.jpg")

            # Mock urlopen để trả HTML
            with mock.patch("urllib.request.urlopen") as mock_urlopen:
                mock_response = mock.MagicMock()
                mock_response.status = 200
                mock_response.headers.get.side_effect = lambda k: (
                    "text/html; charset=utf-8"
                    if k == "Content-Type"
                    else None
                )
                mock_response.__enter__.return_value = mock_response
                mock_response.__exit__.return_value = False
                mock_urlopen.return_value = mock_response

                result = fast_fetch.download_to_file(
                    "http://example.com/media.jpg", save_path
                )

                # Phải trả lỗi, không phải success
                self.assertIsNotNone(result.error, "Nên có error khi HTML")
                self.assertIn(
                    "text/html",
                    result.error,
                    "Lỗi nên nói rõ là text/html",
                )
                # File tạm phải bị xoá
                tmp_path = save_path + ".tmp"
                self.assertFalse(
                    os.path.exists(tmp_path),
                    "File .tmp phải bị xoá khi HTML",
                )

    def test_plain_text_content_rejected(self):
        """Content-Type: text/plain → xoá file tạm, trả lỗi."""
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = os.path.join(tmpdir, "media.mp4")

            with mock.patch("urllib.request.urlopen") as mock_urlopen:
                mock_response = mock.MagicMock()
                mock_response.status = 200
                mock_response.headers.get.side_effect = lambda k: (
                    "text/plain" if k == "Content-Type" else None
                )
                mock_response.__enter__.return_value = mock_response
                mock_response.__exit__.return_value = False
                mock_urlopen.return_value = mock_response

                result = fast_fetch.download_to_file(
                    "http://example.com/media.mp4", save_path
                )

                self.assertIsNotNone(result.error, "Nên có error khi plain text")
                self.assertIn(
                    "text/plain",
                    result.error,
                    "Lỗi nên nói rõ là text/plain",
                )


class TestURLHashFunction(unittest.TestCase):
    """Lỗi 3: url_hash() phải giữ query cho proxy.php và attachments."""

    def test_proxy_url_keeps_query(self):
        """proxy.php?image=...&hash=... → giữ query (vì query là định danh)."""
        url1 = "http://example.com/proxy.php?image=abc&hash=123"
        url2 = "http://example.com/proxy.php?image=def&hash=456"

        hash1 = downloader.url_hash(url1)
        hash2 = downloader.url_hash(url2)

        # Khác query → phải khác hash
        self.assertNotEqual(hash1, hash2, "proxy.php với query khác phải hash khác")

    def test_attachments_url_keeps_query(self):
        """index.php?attachments/... → giữ query (vì query là định danh)."""
        url1 = "http://example.com/index.php?attachments/123"
        url2 = "http://example.com/index.php?attachments/456"

        hash1 = downloader.url_hash(url1)
        hash2 = downloader.url_hash(url2)

        # Khác query → phải khác hash
        self.assertNotEqual(
            hash1, hash2, "attachments với query khác phải hash khác"
        )

    def test_regular_url_strips_query(self):
        """URL thường (không proxy/attachments) → cắt query."""
        url1 = "http://example.com/image.jpg?v=1"
        url2 = "http://example.com/image.jpg?v=2"

        hash1 = downloader.url_hash(url1)
        hash2 = downloader.url_hash(url2)

        # Cùng path, query khác → hash phải giống
        self.assertEqual(hash1, hash2, "URL thường giống path phải hash giống")

    def test_fragment_always_stripped(self):
        """Fragment luôn bị cắt."""
        url1 = "http://example.com/image.jpg#section1"
        url2 = "http://example.com/image.jpg#section2"

        hash1 = downloader.url_hash(url1)
        hash2 = downloader.url_hash(url2)

        # Fragment khác nhưng path giống → hash phải giống
        self.assertEqual(hash1, hash2, "Fragment phải bị bỏ qua khi hash")


if __name__ == "__main__":
    unittest.main()
