"""AGGREGATOR cho các test tách từ file này (P2.2 trong DE-XUAT-CAI-TIEN.md).

TỆP NÀY TỪNG CHỨA 154 test / 2388 dòng. File dài khiến: review không đọc hết
nên bug trốn được; tìm test hỏng phải cuộn cả nghìn dòng; sửa một nhóm phải
chạm cả tệp trong git diff.

Giờ code nằm ở 5 file theo module nguồn — một việc một file:

    test_parse_v2.py     (30 test) xenforo_parse + xf_selectors
    test_cache_v2.py     (21 test) cache + local user index
    test_download_v2.py  (28 test) downloader + fast_fetch
    test_engine_v2.py    (38 test) engine + browser_launcher
    test_tk_v2.py        (37 test) GUI Tkinter (v72.py)

Tất cả dùng chung setUpModule/tearDownModule từ test_common.py — cùng cơ chế
cô lập (thư mục tạm + tắt HTTP-first) như bản cũ, không copy 5 lần.

Chạy như cũ:

    python -m unittest test_v72            # chạy cả 5 file
    python -m unittest test_parse_v2       # chạy riêng một nhóm

Việc giữ tên test_v72 làm aggregator: mọi lệnh/CI/tài liệu đang trỏ tới tên
này vẫn chạy đúng, không cần đổi chỗ nào khác.
"""

import unittest


def _load(extra_modules):
    """Nạp các module test tách và trả TestSuite gộp."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    import sys
    for m in extra_modules:
        __import__(m)
        suite.addTests(loader.loadTestsFromModule(sys.modules[m]))
    return suite


def load_tests(loader, tests, pattern):
    """Hook của unittest: `python -m unittest test_v72` tự dùng bộ này.

    Nhờ load_tests mà aggregator KHÔNG tự chạy chính nó (không có test ở đây
    nên không trùng lặp), chỉ gộp 5 module con.
    """
    return _load([
        "test_parse_v2",
        "test_cache_v2",
        "test_download_v2",
        "test_engine_v2",
        "test_tk_v2",
    ])


if __name__ == "__main__":
    unittest.main()
