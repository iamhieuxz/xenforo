"""Bóc DOM XenForo. Hàm thuần: nhận soup + url trả về dữ liệu, không đụng mạng/Tk."""

import os
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import selectors as S


def make_soup(html):
    try:
        return BeautifulSoup(html, 'lxml')
    except Exception:
        return BeautifulSoup(html, 'html.parser')


def clean_name(name):
    """Tên file an toàn cho Windows."""
    if not name:
        return "Untitled"
    name = str(name).replace('\xa0', ' ')
    name = re.sub(r'[\r\n\t]', ' ', name)
    name = re.sub(r'[\\/*?:"<>|]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'[\s.]+$', '', name)
    if not name:
        return "Untitled"
    reserved = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
                "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}
    if name.upper() in reserved:
        name = "_" + name
    return name.strip()[:180]


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


def resolve_author(soup):
    """Tác giả gốc của thread."""
    node = soup.select_one('.p-description a.username')
    if node:
        return node.text.strip()
    first = soup.select_one("article.message--post[data-author]")
    return first.get('data-author', '').strip() if first else ""


def parse_thread_links(soup, page_url):
    """Trả về (danh sách link thread, url trang kế tiếp) của 1 trang box."""
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
    next_url = urljoin(page_url, nxt['href']) if nxt and nxt.get('href') else None
    return links, next_url


def _strip_junk(post):
    """Gỡ quote, quảng cáo, chữ ký, reactions khỏi post (phải trước khi quét media)."""
    for q in post.find_all(['blockquote', 'div'], class_=S.QUOTE_RE):
        q.decompose()
    # Quảng cáo nằm trong <div class="ad-container"> bao quanh <img>, nên class trên
    # chính thẻ media không đủ: phải gỡ cả wrapper.
    for el in post.find_all(['div', 'aside', 'section', 'ins'], class_=S.AD_RE):
        el.decompose()
    for tag, cls in S.DROP_TAGS:
        for el in post.find_all(tag, class_=cls):
            el.decompose()


def post_timestamp(post):
    t = post.select_one('header.message-attribution time.u-dt') or post.select_one('time.u-dt')
    if t and t.get('data-time'):
        try:
            return datetime.fromtimestamp(int(t['data-time'])).strftime('%Y%m%d_%H%M%S')
        except (ValueError, OSError, OverflowError):
            pass
    return "00000000_000000"


def extract_post_media(post, page_url):
    """Trả về (images, videos, files) của 1 post."""
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


def thread_meta(soup):
    """Trả về (tiêu đề đã làm sạch, tiền tố ngày YYYY-MM-DD)."""
    title = "Untitled_Post"
    node = soup.find('h1', class_='p-title-value')
    if node:
        for label in node.find_all(['a', 'span'], class_=S.LABEL_RE):
            label.decompose()
        raw = re.sub(r'^[\[\(].*?[\]\)]\s*', '', node.get_text(separator=' ', strip=True)).strip()
        title = clean_name(raw)
    title = title[:80].strip().rstrip('.')

    date_prefix = "0000-00-00"
    t = soup.select_one('.p-description time.u-dt') or soup.select_one('.p-description time')
    if t and t.get('data-time'):
        try:
            date_prefix = datetime.fromtimestamp(int(t['data-time'])).strftime('%Y-%m-%d')
        except (ValueError, OSError, OverflowError):
            pass
    return title, date_prefix


def thread_folder(base_dir, author, title, date_prefix):
    return os.path.join(base_dir, clean_name(author), f"[{date_prefix}] {title}")


def next_page_url(soup, page_url):
    """Link 'Trang sau' của trang hiện tại, hoặc None."""
    nxt = soup.find('a', class_=S.PAGENAV_NEXT_RE)
    return urljoin(page_url, nxt['href']) if nxt and nxt.get('href') else None