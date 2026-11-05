"""Kiểm chứng cổng CDP sau khi sửa. Thay cho bản probe cũ (đã lỗi thời).

Chạy: python probe_cdp.py
"""
import http.server
import json
import socket
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import browser_launcher as B
import config


class ChromiumLike(http.server.BaseHTTPRequestHandler):
    """Giả lập /json/version của Chromium."""

    def do_GET(self):
        body = json.dumps({
            "Browser": "Chrome/152.0.7977.124",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/abc",
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class NotChromium(http.server.BaseHTTPRequestHandler):
    """Server thường: trả 200 nhưng body không phải JSON của CDP."""

    def do_GET(self):
        body = b"<html>hello, I am some other service</html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def with_server(handler, fn):
    srv = http.server.HTTPServer(("127.0.0.1", config.CDP_PORT), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)
    try:
        return fn()
    finally:
        srv.shutdown()
        srv.server_close()


results = []


def check(name, got, want, note=""):
    ok = got == want
    results.append(ok)
    mark = "PASS" if ok else "FAIL"
    print(f"   [{mark}] {name}")
    print(f"          thuc te={got!r}  mong doi={want!r}")
    if note:
        print(f"          {note}")


print("=" * 78)
print("1. CDP_URL phải suy ra từ CDP_PORT (không còn hai literal rời)")
print("=" * 78)
check("CDP_URL chứa đúng CDP_PORT",
      f":{config.CDP_PORT}" in config.CDP_URL, True)
check("CDP_URL dùng 127.0.0.1 thay vì localhost (tránh IPv6 ::1)",
      "localhost" not in config.CDP_URL, True,
      "Windows resolve localhost ra ::1 trước, Chromium chỉ bind IPv4")

print()
print("=" * 78)
print("2. Cổng đóng")
print("=" * 78)
check("probe_port -> closed", B.probe_port()["state"], "closed")
check("is_port_open -> False", B.is_port_open(), False)

print()
print("=" * 78)
print("3. Cổng bị server KHÁC chiếm (không phải CDP)")
print("=" * 78)


def run_impostor():
    st = B.probe_port()
    check("probe_port -> not_chromium", st["state"], "not_chromium", st["detail"])
    check("is_port_open -> False (không bị đánh lừa)", B.is_port_open(), False)
    ok, msg = B.launch()
    check("launch() từ chối và nói rõ bị chiếm", ok, False)
    print(f"          thong bao: {msg[:110]}")
    check("thong bao co nhac CDP_PORT", "CDP_PORT" in msg, True)


with_server(NotChromium, run_impostor)

print()
print("=" * 78)
print("4. Cổng có Chromium thật")
print("=" * 78)


def run_chromium():
    st = B.probe_port()
    check("probe_port -> ready", st["state"], "ready", st["detail"])
    check("is_port_open -> True", B.is_port_open(), True)
    ok, msg = B.launch()
    check("launch() dùng luôn, không mở thêm", ok, True)
    print(f"          thong bao: {msg[:110]}")


with_server(ChromiumLike, run_chromium)

print()
print("=" * 78)
print("5. Dọn tiến trình (shutdown)")
print("=" * 78)
check("shutdown() khi chưa mở gì -> False", B.shutdown(), False)
check("_launched_process đã reset", B._launched_process, None)

print()
print("=" * 78)
print(f"KET QUA: {sum(results)}/{len(results)} PASS")
print("=" * 78)
sys.exit(0 if all(results) else 1)
