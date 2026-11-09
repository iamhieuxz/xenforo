"""Bóc DOM XenForo. Không đụng mạng và không đụng Tk.

Lưu ý về tính thuần: hầu hết hàm ở đây là thuần (nhận soup + url trả dữ liệu).
Ngoại lệ có chủ đích là extract_post_media(), vì nó gỡ node rác khỏi cây soup
bằng decompose() — xem docstring của hàm đó.
"""

import os
import re
from datetime import datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

import xf_selectors as S


def make_soup(html):
    try:
        return BeautifulSoup(html, 'lxml')
    except Exception:
        return BeautifulSoup(html, 'html.parser')


# Tên thiết bị Windows cấm dùng làm tên file, KỂ CẢ khi có phần mở rộng:
# "con.txt" vẫn bị PermissionError. Bản cũ chỉ so khớp nguyên chuỗi nên
# "con.txt" lọt qua -> ghi file thất bại giữa lúc tải.
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def clean_name(name):
    """Tên file an toàn cho Windows.

    Ba lỗi đã đo được ở bản cũ, đều làm hỏng việc ghi file:
    1. Ký tự NUL (\\x00) không bị loại -> open() ném
       "ValueError: embedded null character", media hỏng mà không rõ vì sao.
    2. Tên thiết bị chỉ bị chặn khi KHỚP NGUYÊN CHUỖI; "con.txt" lọt qua rồi
       bị Windows từ chối với PermissionError.
    3. Không giới hạn theo ngân sách độ dài còn lại của đường dẫn: cắt cứng 180
       ký tự vẫn có thể đẩy đường dẫn đầy đủ vượt MAX_PATH 260 của Windows.
       Ở đây trả về tên đã cắt; chỗ gọi tự tính thêm ngân sách folder.
    """
    if not name:
        return "Untitled"
    name = str(name).replace('\xa0', ' ')
    name = re.sub(r'[\r\n\t]', ' ', name)
    # Loại ký tự điều khiển, gồm cả NUL. Giữ dấu tiếng Việt (>= 0x20).
    name = "".join(ch for ch in name if ch >= " " and ch != "\x7f")
    name = re.sub(r'[\\/*?:"<>|]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'[\s.]+$', '', name)
    if not name:
        return "Untitled"

    # Kiểm theo phần TRƯỚC dấu chấm đầu tiên: "con.txt" -> "CON".
    stem = name.split(".")[0].upper()
    if stem in _WIN_RESERVED:
        name = "_" + name
    return name.strip()[:MAX_NAME_LEN]


# Trần độ dài một thành phần tên. 180 ký tự là mức an toàn cho folder lồng nhau
# trên Windows: 260 (MAX_PATH) - ~60 cho phần gốc và 2 cấp folder - ~40 cho
# timestamp + hash + đuôi file.
MAX_NAME_LEN = 120


def get_url_filename(url):
    """Tên file suy ra từ URL. Trả về chuỗi rỗng nếu không suy ra được."""
    try:
        if 'proxy.php' in url:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(url)
            if 'proxy.php' in parsed.path:
                qs = parse_qs(parsed.query)
                if 'image' in qs:
                    return get_url_filename(qs['image'][0])
        clean_url = url.split('?')[0].split('#')[0]
        segments = [s for s in clean_url.split('/') if s]
        if not segments:
            return ""
        last_segment = segments[-1]
        if '.' in last_segment:
            parts = last_segment.split('.')
            if parts[-1].isdigit() and len(parts) > 1:
                last_segment = ".".join(parts[:-1])
        if last_segment.isdigit() and len(segments) > 1 and segments[-2] == 'attachments':
            return f"attachment_{last_segment}"
        generic_names = ['video.mp4', 'download', 'attachment', 'index.php', 'file.php', 'view', 'proxy.php']
        if len(segments) > 1 and (last_segment.lower() in generic_names or last_segment.isdigit()):
            return f"{segments[-2]}_{last_segment}"
        return last_segment
    except Exception:
        return ""


def ext_for(url, allowed, default):
    """Đuôi file theo loại media. URL không rõ đuôi -> default."""
    base = get_url_filename(url)
    m = re.search(r'\.([A-Za-z0-9]{1,5})$', base)
    if not m:
        return default
    ext = '.' + m.group(1).lower()
    return ext if ext in allowed else default


def normalize_to_first_page(url):
    """Bỏ /page-N để luôn bắt đầu từ trang 1."""
    clean_url = url.split('#')[0].split('?')[0]
    clean_url = S.PAGE_NUM_RE.sub('/', clean_url)
    if not clean_url.endswith('/'):
        clean_url += '/'
    return clean_url


def is_noise_url(src):
    return any(x in src.lower() for x in S.NOISE_URL_PARTS)


# Class của add-on quảng cáo SAM (Sponsored Ad Manager) trên rphang.show.
# Đo được: một thread có 15 khối `samCodeUnit` và 19 `samItem` nằm NGAY BÊN
# TRONG `message-body`, xen giữa nội dung thật. Không loại thì banner quảng cáo
# bị coi là media của bài và bị tải về.
SAM_AD_CLASSES = ("samCodeUnit", "samItem", "samAd", "samSponsored",
                  "samVideoOverlay")


def strip_ads(soup):
    """Xoá quảng cáo của add-on SAM khỏi soup, tại chỗ.

    Gọi TRƯỚC khi bóc media. XenForo chuẩn không có các class này nên hàm
    không làm gì trên site khác — an toàn để gọi vô điều kiện.
    """
    removed = 0
    for cls in SAM_AD_CLASSES:
        for node in soup.find_all(class_=cls):
            if node.parent is not None:
                node.decompose()
                removed += 1
    return removed


def resolve_author(soup):
    """Tác giả gốc của thread."""
    node = soup.select_one('.p-description a.username')
    if node:
        return node.text.strip()
    first = soup.select_one("article.message--post[data-author]")
    return first.get('data-author', '').strip() if first else ""


def parse_thread_links(soup, page_url):
    """Trả về (danh sách link thread, url trang kế tiếp) của 1 trang box.

    QUAN TRỌNG: url trang kế được dựng lại để GIỮ query string của trang hiện
    tại (ví dụ `?starter=traicube`). XenForo trả link phân trang trần
    (`/box/x.6/page-2`), không mang filter — nếu dùng thẳng link đó thì từ trang
    2 trở đi box hiện TOÀN BỘ thread của mọi tác giả, và app tải cả nghìn bài
    rồi mới lọc ở bước sau. Đây chính là lỗi "giới hạn trong box mà quét cả
    nghìn bài".
    """
    links = []
    for item in soup.find_all('div', class_=S.STRUCT_THREAD_RE):
        title_div = item.find('div', class_=S.STRUCT_TITLE_RE)
        if not title_div:
            continue
        a_tag = title_div.find('a', attrs={"data-tp-primary": "on"})
        if not a_tag:
            for link in title_div.find_all('a', href=True):
                if '/t/' in link['href'] and 'starter' not in link['href']:
                    a_tag = link
                    break
        if a_tag and a_tag.get('href'):
            full = S.PAGE_NUM_RE.sub('/', urljoin(page_url, a_tag['href']).split('#')[0])
            links.append(full)

    nxt = soup.find('a', class_=S.PAGENAV_NEXT_RE)
    next_url = None
    if nxt and nxt.get('href'):
        next_url = with_query_of(urljoin(page_url, nxt['href']), page_url)
    return links, next_url


def with_query_of(url, source_url):
    """Gắn query string của `source_url` vào `url` nếu url đó chưa có query.

    Tách riêng để test được và để chỗ gọi đọc rõ ý: "mang bộ lọc sang trang sau".
    Không bao giờ ghi đè query đã có — link phân trang có sẵn tham số riêng thì
    phải giữ nguyên.

    Giữ cả DẤU `/` cuối path: XenForo phân biệt `/box/x.6/page-2` với
    `/box/x.6/page-2/`. Thiếu dấu `/` thì URL trang 2 và trang 3 có thể chuẩn
    hoá về cùng một dạng, làm visited-set tưởng là lặp và dừng sớm.
    """
    parts = urlsplit(url)
    if parts.query:
        return url
    src = urlsplit(source_url)
    if not src.query:
        return url
    path = parts.path
    # Đồng bộ kiểu có/không có `/` cuối với trang nguồn, để các trang cùng một
    # dạng URL — visited-set so sánh chuỗi nên dạng khác nhau là "trang khác".
    src_has_slash = src.path.endswith('/')
    if src_has_slash and not path.endswith('/'):
        path += '/'
    elif not src_has_slash and path.endswith('/'):
        path = path.rstrip('/')
    return urlunsplit((parts.scheme, parts.netloc, path, src.query, parts.fragment))


def thread_starter(soup):
    """Tác giả mở thread, đọc từ trang danh sách box (không cần mở thread).

    XenForo đặt `data-author` trên item của box, nên lọc được NGAY ở bước danh
    sách: chỉ mở những thread của tác giả cần quét, thay vì mở hết rồi bỏ qua.
    Trả "" nếu không đọc được (khi đó chỗ gọi phải mở thread để kiểm).
    """
    for attr in ('data-author', 'data-last-author'):
        v = soup.get(attr)
        if v and v.strip():
            return v.strip()
    node = soup.select_one('.structItem-parts a.username, a.username')
    return node.get_text(strip=True) if node else ""


def soup_of_single(item):
    """Bọc một item box thành soup riêng để dùng lại parse_thread_links.

    parse_thread_links() quét cả trang; khi đã lọc được item nào cần lấy, ta chỉ
    muốn link của chính item đó, không phải cả trang.
    """
    return BeautifulSoup(str(item), 'lxml')


def _strip_junk(post):
    """Gỡ quote, quảng cáo, chữ ký, reactions khỏi post (phải trước khi quét media)."""
    for q in post.find_all(['blockquote', 'div'], class_=S.QUOTE_RE):
        q.decompose()
    # Quảng cáo nằm trong <div class="ad-container"> bao quanh <img>, nên class trên
    # chính thẻ media không đủ: phải gỡ cả wrapper.
    for el in post.find_all(['div', 'aside', 'section', 'ins'], class_=S.AD_RE):
        el.decompose()
    # Add-on SAM trên rphang.show chèn quảng cáo NGAY TRONG .message-body, xen
    # giữa nội dung thật. Đo được trên một thread: 15 khối samCodeUnit, 19
    # samItem — trong đó có banner và video quảng cáo. Không gỡ thì chúng bị
    # coi là media của bài và bị tải về.
    for cls in SAM_AD_CLASSES:
        for el in post.find_all(class_=cls):
            el.decompose()
    for tag, cls in S.DROP_TAGS:
        for el in post.find_all(tag, class_=cls):
            el.decompose()


def _date_from_time_tag(tag):
    """Lấy ngày từ một thẻ <time>. Thử data-time rồi tới thuộc tính datetime.

    XenForo ghi ngày theo hai kiểu tuỳ theme/build: `data-time` (epoch giây) và
    `datetime` (ISO 8601). Chỉ đọc `data-time` như bản cũ là bỏ sót khá nhiều.
    """
    if not tag:
        return None
    raw = tag.get('data-time')
    if raw:
        try:
            return datetime.fromtimestamp(int(raw))
        except (ValueError, OSError, OverflowError, TypeError):
            pass
    iso = tag.get('datetime')
    if iso:
        try:
            # '2023-11-14T22:13:20+0000' hoặc có dấu hai chấm ở offset
            return datetime.fromisoformat(iso.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            try:
                return datetime.strptime(iso[:19], '%Y-%m-%dT%H:%M:%S')
            except (ValueError, TypeError):
                pass
    return None


def _date_from_meta(soup):
    """Ngày từ thẻ meta chuẩn SEO. Nhiều XenForo có sẵn để chia sẻ Facebook."""
    for prop, attr in (("article:published_time", "property"),
                       ("article:published_time", "name"),
                       ("og:article:published_time", "property")):
        node = soup.find('meta', attrs={attr: prop})
        if node and node.get('content'):
            try:
                return datetime.fromisoformat(node['content'].replace('Z', '+00:00'))
            except (ValueError, TypeError):
                pass
    return None


def thread_start_date(soup):
    """Ngày mở thread, thử lần lượt mọi nguồn. Trả datetime hoặc None.

    Thứ tự ưu tiên theo độ tin cậy: mô tả thread (ngày tác giả đăng) trước, rồi
    meta SEO, rồi thẻ time đầu tiên trong bài. Bản cũ chỉ thử ĐÚNG một selector
    `.p-description time.u-dt`; thiếu nó là ra 0000 và folder đổi tên giữa các
    lần quét -> app tải lại toàn bộ dù file đã có.
    """
    t = soup.select_one('.p-description time.u-dt') \
        or soup.select_one('.p-description time')
    d = _date_from_time_tag(t)
    if d:
        return d

    d = _date_from_meta(soup)
    if d:
        return d

    for t in soup.select('time.u-dt')[:3]:
        d = _date_from_time_tag(t)
        if d:
            return d
    for t in soup.select('time[datetime]')[:3]:
        d = _date_from_time_tag(t)
        if d:
            return d

    return None


def post_timestamp(post):
    """Thời điểm post dạng YYYYMMDD_HHMMSS.

    Không trả chuỗi 00000000 nữa khi thiếu ngày: trả chuỗi RỖNG để caller biết là
    "không xác định" và tự quyết định (engine dùng nhãn khác cho trường hợp này).
    Giữ hàm thuần: không đọc cache, không đụng mạng.
    """
    d = _date_from_time_tag(post.select_one('header.message-attribution time.u-dt')) \
        or _date_from_time_tag(post.select_one('time.u-dt')) \
        or _date_from_time_tag(post.select_one('header.message-attribution time')) \
        or _date_from_time_tag(post.select_one('time[datetime]'))
    return d.strftime('%Y%m%d_%H%M%S') if d else ""


def extract_post_media(post, page_url):
    """Trả về (images, videos, files) của 1 post.

    Hàm này SỬA (mutate) cây soup truyền vào: _strip_junk() gọi decompose() để gỡ
    quote/quảng cáo/chữ ký, mà decompose() xoá node khỏi cây gốc. Gọi lần hai trên
    cùng đối tượng sẽ ra kết quả khác lần đầu.

    Trước đây docstring của module ghi "hàm thuần", gây hiểu nhầm. Giữ nguyên hành
    vi mutate vì engine chỉ dùng mỗi post một lần, và gỡ node là cách rẻ nhất để
    loại media rác. Cần bản không đụng input thì dùng extract_post_media_copy().
    """
    _strip_junk(post)

    imgs, vids, files = [], [], []
    body = post.select_one('.message-body')
    attach = post.select_one('.message-attachments')
    nodes = [n for n in (body, attach) if n] or [post]

    for node in nodes:
        for img in node.find_all('img'):
            if S.class_hit(S.AD_RE, img):
                continue
            src = img.get('data-src') or img.get('src') or img.get('data-url')
            if src and not src.startswith('data:') and not is_noise_url(src):
                imgs.append(urljoin(page_url, src))

        for lb in node.find_all(['div', 'a'], class_=S.LBCONTAINER_RE):
            if S.class_hit(S.AD_RE, lb):
                continue
            src = lb.get('data-src') or lb.get('data-url') or lb.get('href')
            if src and not src.startswith('data:') and not is_noise_url(src):
                imgs.append(urljoin(page_url, src))

        for v in node.find_all('video'):
            if S.class_hit(S.AD_RE, v):
                continue
            v_src = v.get('src') or v.get('data-src') or v.get('data-url')
            if v_src and not v_src.startswith('data:'):
                vids.append(urljoin(page_url, v_src))
            if v.get('data-id'):
                vids.append(urljoin(page_url, f"/video/play/{v.get('data-id')}/video.mp4"))
            for source in v.find_all('source'):
                src = source.get('src') or source.get('data-src')
                if src and not src.startswith('data:'):
                    vids.append(urljoin(page_url, src))

        for a_tag in node.find_all('a', href=True):
            if S.class_hit(S.AD_RE, a_tag):
                continue
            file_url = urljoin(page_url, a_tag['href'])
            clean_href = file_url.split('?')[0].split('#')[0]
            text = a_tag.get_text().lower()
            low = clean_href.lower()

            # Đuôi file phải được nhận diện TRƯỚC nhánh '/attachments/' bắt-tay-mọi:
            # XenForo tên attachment là /attachments/ten.zip.12345/, nếu kiểm
            # '/attachments/' trước thì .zip/.pdf rơi vào imgs và bị lưu thành .jpg.
            if S.FILE_URL_RE.search(low):
                files.append(file_url)
            elif S.VIDEO_URL_RE.search(low) or '/video/play/' in low or 'attachment-files' in low \
                    or any(e in text for e in S.VIDEO_EXT):
                vids.append(file_url)
            elif S.IMAGE_URL_RE.search(low):
                imgs.append(file_url)
            elif '/attachments/' in low or 'proxy.php?image' in file_url.lower():
                # Không rõ đuôi: XenForo hay phục vụ ảnh qua attachment hoặc proxy.php.
                imgs.append(file_url)

        for iframe in node.find_all('iframe'):
            ifr = iframe.get('src') or iframe.get('data-src')
            if ifr:
                vids.append(urljoin(page_url, ifr))

    return S.dedupe(imgs), S.dedupe(vids), S.dedupe(files)


def extract_post_media_copy(post, page_url):
    """Như extract_post_media nhưng KHÔNG sửa input (làm việc trên bản sao).

    Dùng khi cần gọi nhiều lần trên cùng một cây soup, hoặc khi giữ soup để bóc
    phần khác sau đó.
    """
    import copy as _copy
    return extract_post_media(_copy.copy(post), page_url)


def thread_meta(soup):
    """Trả về (tiêu đề đã làm sạch, tiền tố ngày YYYY-MM-DD hoặc "")."""
    title = "Untitled_Post"
    node = soup.find('h1', class_='p-title-value')
    if node:
        for label in node.find_all(['a', 'span'], class_=S.LABEL_RE):
            label.decompose()
        raw = re.sub(r'^[\[\(].*?[\]\)]\s*', '', node.get_text(separator=' ', strip=True)).strip()
        title = clean_name(raw)
    title = title[:80].strip().rstrip('.')

    d = thread_start_date(soup)
    return title, (d.strftime('%Y-%m-%d') if d else "")


def thread_key(url):
    """Khoá ổn định của một thread, dùng để nhớ "đã xử lý xong".

    Lấy phần id số ở cuối đường dẫn. Hai dạng đều gặp trên rphang.show:
        /t/<slug>.<id>/           (theme UI.X)
        /threads/<slug>.<id>/     (XenForo chuẩn)
        /t/<slug>.<id>/page-3      (khi đang ở trang sau)

    Dùng id chứ không dùng slug: slug đổi khi chủ bài sửa tiêu đề, còn id thì
    không. Dùng slug làm khoá sẽ khiến bài cũ bị coi là bài mới sau mỗi lần
    sửa tiêu đề, và tải lại toàn bộ.
    """
    if not url:
        return ""
    import re as _re
    m = _re.search(r"\.(\d+)(?:/|$|\?)", url)
    if m:
        return m.group(1)
    # Dự phòng: lấy cụm số dài nhất ở cuối
    m = _re.search(r"/(\d+)/?$", url.split("?")[0])
    return m.group(1) if m else ""


def thread_folder(base_dir, author, title, date_prefix):
    """Đường dẫn folder của một thread.

    date_prefix rỗng thì KHÔNG ghi "[ ]" trơ: dùng nhãn "khong-ngay" để folder
    vẫn ổn định qua các lần quét. Trước đây rỗng/0000 đều tạo tên khác nhau ở
    mỗi lần chạy, làm app tưởng là bài mới và tải lại từ đầu.

    Cắt tiêu đề theo NGÂN SÁCH CÒN LẠI của đường dẫn, không cắt cứng một số:
    Windows giới hạn MAX_PATH 260 ký tự cho đường dẫn tuyệt đối (khi không
    dùng tiền tố \\\\?\\). Đo được: base_dir sâu + tiêu đề 200 ký tự vẫn cho ra
    đường dẫn 281 ký tự, và mọi lần ghi file sau đó đều thất bại. Ngân sách phải
    tính từ base_dir thật và chừa chỗ cho tên file media.
    """
    stamp = clean_name(date_prefix) if date_prefix else "khong-ngay"
    safe_author = clean_name(author)
    prefix = f"[{stamp}] "

    # Chừa chỗ cho: tên file media dài nhất app sinh ra
    # ("[YYYYMMDD_HHMMSS]_media_0123_<slug>_abcdef.jpg") + đường dẫn tương đối.
    MEDIA_HEADROOM = 60
    fixed = len(os.path.abspath(base_dir)) + 1 + len(safe_author) + 1 + len(prefix)
    budget = 260 - MEDIA_HEADROOM - fixed
    budget = max(32, min(budget, MAX_NAME_LEN))

    safe_title = clean_name(title)[:budget].strip() or "Untitled"
    return os.path.join(base_dir, safe_author, f"{prefix}{safe_title}")


def next_page_url(soup, page_url):
    """Link 'Trang sau' của trang hiện tại, hoặc None."""
    nxt = soup.find('a', class_=S.PAGENAV_NEXT_RE)
    return urljoin(page_url, nxt['href']) if nxt and nxt.get('href') else None


def resolve_box_url(soup, page_url):
    """Box URL từ breadcrumb của trang thread, hoặc None.

    XenForo đặt breadcrumb trong nav.p-breadcrumbs. Link chứa '/box/' là
    chuyên mục mà bài viết thuộc về. Dùng để tự động điền ô Box URL khi
    user quét 1 bài viết — lần sau bấm "Quét tác giả" không cần chọn lại box.
    """
    if not soup:
        return None
    for a in soup.select(".p-breadcrumbs li a"):
        href = a.get("href", "")
        if "/box/" in href:
            full = urljoin(page_url, href)
            # Chuẩn hoá: bỏ query/fragment, giữ trailing slash
            clean = full.split("?")[0].split("#")[0]
            if not clean.endswith("/"):
                clean += "/"
            return clean
    return None