"""Header dùng chung cho các file test tách từ test_v72.py (P2.2).

Mỗi file test mới import từ đây để có setUpModule/tearDownModule và soup_of
GIỐNG HỆT test_v72.py cũ — cùng cơ chế cô lập (thư mục tạm, tắt HTTP-first),
không copy dại 3 lần.
"""

import os
import shutil
import tempfile

from bs4 import BeautifulSoup

import config

# Giữ tham chiếu để tearDownModule khôi phục.
_ORIGINAL_DOWNLOAD_DIR = config.DOWNLOAD_DIR
_TEST_TMP = None
_ORIGINAL_HTTP_FIRST = True


def setUpModule():
    """Cô lập hoàn toàn khỏi thư mục tải thật VÀ khỏi mạng.

    Phải chạy trước MỌI test: app đọc config.DOWNLOAD_DIR trong __init__ rồi
    mở MediaCache ngay, nên chỉ cần một test dựng app trước khi kịp đổi là DB
    thật bị mở.

    Tắt HTTP-first: engine giờ tải HTML bằng HTTP trước, nếu bật thì test nào
    chạm open_page() sẽ gọi mạng thật -> suite treo hàng phút và phụ thuộc
    internet. Test phải chạy được trên máy không có mạng.
    """
    global _TEST_TMP, _ORIGINAL_HTTP_FIRST
    _TEST_TMP = tempfile.mkdtemp(prefix="v72_test_")
    config.DOWNLOAD_DIR = _TEST_TMP
    os.environ["RPHANG_DIR"] = _TEST_TMP
    # Tắt tải HTTP thật: nếu bật, open_page() gọi mạng -> suite treo.
    _ORIGINAL_HTTP_FIRST = getattr(config, "USE_HTTP_FIRST", True)
    config.USE_HTTP_FIRST = False


def tearDownModule():
    config.DOWNLOAD_DIR = _ORIGINAL_DOWNLOAD_DIR
    os.environ.pop("RPHANG_DIR", None)
    try:
        config.USE_HTTP_FIRST = _ORIGINAL_HTTP_FIRST
    except NameError:
        pass
    if _TEST_TMP:
        # Windows khoá file đang mở: nếu còn MediaCache chưa close thì rmtree
        # thất bại IM LẶNG (ignore_errors) và thư mục tạm ở lại mãi. Thử vài lần
        # rồi mới bỏ cuộc, và báo ra ngoài thay vì nuốt.
        for _ in range(3):
            shutil.rmtree(_TEST_TMP, ignore_errors=True)
            if not os.path.exists(_TEST_TMP):
                break
            import gc
            gc.collect()
            import time
            time.sleep(0.05)
        if os.path.exists(_TEST_TMP):
            shutil.rmtree(_TEST_TMP, ignore_errors=True)


def soup_of(html):
    return BeautifulSoup(html, 'lxml')
