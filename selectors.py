"""Regex và hằng dùng chung cho phần bóc DOM.

HTML class là danh sách token. Regex cũ (r'quote|bbCodeBlock', r'balloon|ad|banner')
khớp chuỗi con -> "js-selectToQuote" dính "quote" (xoá sạch thân bài),
"download"/"attachment" dính "ad" (bỏ sót media thật).

Dùng regex neo ^...$ : bs4 so regex class_ với TỪNG TOKEN, nên vừa khớp đúng token
vừa không dính class chứa chuỗi đó. Không dùng set/list cho class_ vì bs4 so chuỗi
có phân biệt HOA/thường -> {'bbcodeblock'} không khớp "bbCodeBlock".
"""

import re

STRUCT_THREAD_RE = re.compile(r'structItem--thread', re.I)
STRUCT_TITLE_RE = re.compile(r'structItem-title', re.I)
PAGENAV_NEXT_RE = re.compile(r'pageNav-jump--next', re.I)
LBCONTAINER_RE = re.compile(r'lbContainer|js-lbImage|lbContainer-zoomer', re.I)
PAGE_NUM_RE = re.compile(r'/page-\d+/?$', re.I)
LABEL_RE = re.compile(r'label', re.I)

QUOTE_RE = re.compile(r'^(?:quote|bbCodeBlock)$', re.I)
AD_RE = re.compile(r'^(?:ad|ads|advertisement|balloon|quangcao|banner|ad-container|ad-wrapper)$', re.I)

# Thẻ bỏ khỏi post trước khi quét media: (tag, class)
DROP_TAGS = (('aside', 'message-signature'), ('div', 'message-cell--user'), ('div', 'reactionsBar'))

# Ảnh/smilie XenForo đi kèm mọi post, không phải media của tác giả.
NOISE_URL_PARTS = ('smilie', 'avatar', 'emoji', 'styles/default')

VIDEO_EXT = ('.mp4', '.mov', '.webm', '.m4v', '.avi', '.mkv')
IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif', '.bmp')
FILE_EXT = ('.zip', '.rar', '.7z', '.pdf', '.epub', '.doc', '.docx', '.xls', '.xlsx')

# XenForo tên attachment là /attachments/ten.zip.12345/ -> phải chấp nhận đuôi + số bịa
# + dấu / cuối. Không có phần này thì mọi attachment rơi vào nhánh ảnh.
FILE_URL_RE = re.compile(r'\.(zip|rar|7z|pdf|epub|docx?|xlsx?)(?:\.\d+)?/?$', re.I)
IMAGE_URL_RE = re.compile(r'\.(jpg|jpeg|png|gif|webp|avif|bmp)(?:\.\d+)?/?$', re.I)
VIDEO_URL_RE = re.compile(r'\.(mp4|mov|webm|m4v|avi|mkv)(?:\.\d+)?/?$', re.I)

# content-type này nghĩa là Cloudflare/404 trả về HTML -> lưu ra .jpg là file rác.
NON_MEDIA_CONTENT_TYPES = ('text/html', 'text/plain')

# Status lỗi vĩnh viễn, retry chỉ tốn thêm thời gian.
RETRY_STATUSES = frozenset({429})


def class_hit(pattern, element):
    """class HTML là danh sách token -> so từng token với regex đã neo."""
    return any(pattern.search(c) for c in (element.get('class') or ()))


def dedupe(seq):
    """Giữ thứ tự, bỏ trùng."""
    return list(dict.fromkeys(seq))