"""組織官網：找近 5 年的財務報告、年報、工作／成果報告（LK-17）。

從官網首頁出發，跟著「財務、年報、資訊公開、徵信」這類連結最多走兩層、每個網站最多讀 MAX_PAGES 頁，
只在同一個網站裡往下走；遵守 robots.txt。找到的 PDF／Google 雲端檔案依標題與網址判斷年度與種類。
給了 extractor（financials.ClaudeExtractor）才會下載報告、讀出年度財務數字。

Item 種類：
- document：{year, doc_kind, title, url, found_on}
- financial：{year, audited, <financials.AMOUNT_FIELDS>…, document_url, document_title, method}
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from .http import USER_AGENT, PoliteClient
from .items import Item

log = logging.getLogger(__name__)

SOURCE_NAME = "組織官網"
MAX_PAGES = 20
MAX_DEPTH = 2
MAX_PDF_BYTES = 20 * 1024 * 1024  # Claude 一個請求最多 32MB，base64 會再大三分之一

# 社群、表單、短網址：不是組織自己的網站，不爬
SKIP_HOSTS = (
    "facebook.com", "fb.com", "fb.me", "instagram.com", "line.me", "lin.ee", "youtube.com", "youtu.be",
    "twitter.com", "x.com", "linktr.ee", "forms.gle", "threads.net", "medium.com",
)

# 往下走的連結：導覽到「資訊公開」那一類頁面
NAV_RE = re.compile(
    r"財務|財報|年報|年度報告|徵信|資訊公開|公開資訊|資訊揭露|透明|決算|工作報告|成果報告|成果|關於|"
    r"annual|financ|report|disclosure|transparen|about",
    re.I,
)
# 文件種類：先排除「打算做的」與捐款名單，再依序判斷
EXCLUDE_RE = re.compile(
    r"工作計[畫劃]|預算|計畫書|徵信|名單|名冊|清冊|捐贈人|捐款人|芳名|收據|募款活動|勸募活動|章程|budget|plan", re.I
)
KIND_PATTERNS = (
    ("financial", re.compile(r"財務|財報|查核|決算|收支|資產負債|audit|financ", re.I)),
    ("annual", re.compile(r"年報|年度報告|annual", re.I)),
    ("work", re.compile(r"工作報告|成果報告|成果|服務報告|活動報告|impact", re.I)),
)
KIND_LABELS = {"financial": "財務報告", "annual": "年報", "work": "工作／成果報告"}
ROC_YEAR_RE = re.compile(r"(?<!\d)(?:民國\s*)?(1[01]\d)\s*(?:年|學年)")
# 「113勸募收支彙總表」這種開頭就是民國年、後面直接接中文的標題
LEADING_ROC_RE = re.compile(r"^(1[01]\d)(?=[\u4e00-\u9fff])")
AD_YEAR_RE = re.compile(r"(?<!\d)(20[0-3]\d)(?!\d)")
DRIVE_FILE_RE = re.compile(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?)", re.I)


@dataclass(frozen=True)
class DocLink:
    year: int  # 民國
    doc_kind: str  # financial | annual | work
    title: str
    url: str
    found_on: str

    def item(self, ubn: str) -> Item:
        return Item(
            "document", ubn,
            {"year": self.year, "doc_kind": self.doc_kind, "title": self.title, "url": self.url, "found_on": self.found_on},
            source_url=self.found_on, external_id=url_id(self.url),
        )


def url_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_crawlable_site(url: str) -> bool:
    if not url or not url.lower().startswith(("http://", "https://")):
        return False
    host = _host(url)
    if not host or "@" in url.split("//", 1)[1].split("/", 1)[0]:
        return False
    if host == "docs.google.com" or host.endswith("google.com"):
        return False
    return not any(host == h or host.endswith("." + h) for h in SKIP_HOSTS)


def find_year(text: str) -> int | None:
    """回傳民國年度；同時有民國與西元時以民國為準（標題多半寫民國，網址常帶上傳日期的西元）。"""
    m = ROC_YEAR_RE.search(text)
    if m:
        return int(m.group(1))
    m = AD_YEAR_RE.search(text)
    if m:
        return int(m.group(1)) - 1911
    m = LEADING_ROC_RE.match(text.strip())
    return int(m.group(1)) if m else None


def classify(text: str) -> str | None:
    if EXCLUDE_RE.search(text):
        return None
    for kind, pattern in KIND_PATTERNS:
        if pattern.search(text):
            # 公益勸募的收支表只算單一勸募活動，不是整個組織的財報：當成成果報告列出、不讀數字
            return "work" if kind == "financial" and "勸募" in text else kind
    return None


def is_document_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(".pdf") or bool(DRIVE_FILE_RE.search(url))


def _clean(text: str) -> str:
    text = re.sub("[\u200b-\u200f\ufeff]", "", text or "")  # 編輯器留下的零寬字元
    return re.sub(r"\s+", " ", text).strip()


GENERIC_TITLES = re.compile(r"^(pdf|下載|點我下載|點此下載|檔案下載|按此下載|詳全文|全文|download|more|查看|連結)$", re.I)
CONTEXT_LEVELS = 4
CONTEXT_MAX = 200


def _context(a, year: int | None, kind: str | None) -> tuple[int | None, str | None, str]:
    """連結文字只寫「PDF」「2023」時，往外一層一層看（表格列、區塊標題）補年度與種類。

    例：「財務報表 2023 2024 2022」這一塊裡的「2023」連結 → 2023 年的財務報告。
    外層字太多（整頁導覽列）就停；種類在哪一層看到排除字（工作計畫、預算）就整個不收。"""
    ctx = ""
    for depth, parent in enumerate(a.parents):
        if depth >= CONTEXT_LEVELS or parent.name in ("body", "html", "[document]"):
            break
        text = _clean(parent.get_text(" "))
        if len(text) > CONTEXT_MAX:
            break
        ctx = ctx or text
        if year is None:
            year = find_year(text)
        if kind is None:
            if EXCLUDE_RE.search(text):
                return year, None, ctx
            kind = classify(text)
        if year is not None and kind is not None:
            break
    return year, kind, ctx


def parse_links(html: str, page_url: str) -> tuple[list[DocLink], list[str]]:
    """一頁裡的（報告檔、要往下走的同站連結）。年度與種類先看連結自己的字和網址，看不出來才看外面那一層。"""
    soup = BeautifulSoup(html, "html.parser")
    docs: dict[str, DocLink] = {}
    nav: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urljoin(page_url, href).split("#", 1)[0]
        own = _clean(" ".join([a.get_text(" "), a.get("title", ""), a.get("aria-label", "")]))
        url_text = unquote(urlparse(url).path)
        if is_document_url(url):
            if url in docs:
                continue
            own_all = f"{own} {url_text}"
            if EXCLUDE_RE.search(own_all):
                continue
            year, kind = find_year(own_all), classify(own_all)
            ctx = ""
            if year is None or kind is None:
                year, kind, ctx = _context(a, year, kind)
            if year is None or kind is None:
                continue
            filename = url_text.rsplit("/", 1)[-1]
            if own and not GENERIC_TITLES.match(own) and not re.fullmatch(r"[\d\s年度]+", own):
                title = own
            elif filename.lower().endswith(".pdf") and not re.fullmatch(r"[\d_\-]+\.pdf", filename.lower()):
                title = filename[:-4]
            else:
                title = f"{year} 年度{KIND_LABELS[kind]}"
            docs[url] = DocLink(year, kind, title[:200], url, page_url)
        elif _host(url) == _host(page_url) and (NAV_RE.search(own) or NAV_RE.search(unquote(url))):
            nav.append(url)
    return list(docs.values()), nav


class _Robots:
    def __init__(self, client: PoliteClient, site: str):
        self.parser: RobotFileParser | None = None
        root = f"{urlparse(site).scheme}://{urlparse(site).netloc}/robots.txt"
        try:
            resp = client.get(root)
            parser = RobotFileParser()
            parser.parse(resp.text.splitlines())
            self.parser = parser
        except Exception:  # 沒有 robots.txt（404）或讀不到：照一般禮貌爬取
            self.parser = None

    def allowed(self, url: str) -> bool:
        return self.parser is None or self.parser.can_fetch(USER_AGENT, url)


def discover(client: PoliteClient, website: str, since_roc: int | None = None, max_pages: int = MAX_PAGES) -> list[DocLink]:
    """走官網找報告；同一份檔案只留一筆。單頁讀不到就略過那一頁，不讓整個網站失敗。"""
    robots = _Robots(client, website)
    queue: list[tuple[str, int]] = [(website, 0)]
    seen: set[str] = set()
    found: dict[str, DocLink] = {}
    pages = 0
    while queue and pages < max_pages:
        url, depth = queue.pop(0)
        if url in seen or not robots.allowed(url):
            continue
        seen.add(url)
        try:
            resp = client.get(url)
        except Exception as exc:
            log.info("orgsite: skip %s (%s)", url, exc)
            continue
        pages += 1
        if "html" not in resp.headers.get("content-type", "html"):
            continue
        page_url = str(resp.url)
        if depth == 0 and _host(page_url) != _host(website) and not is_crawlable_site(page_url):
            return []  # 首頁轉到臉書之類
        docs, nav = parse_links(resp.text, page_url)
        for d in docs:
            if since_roc is None or d.year >= since_roc:
                found.setdefault(d.url, d)
        if depth < MAX_DEPTH:
            queue.extend((n, depth + 1) for n in nav if n not in seen)
    return sorted(found.values(), key=lambda d: (-d.year, d.doc_kind, d.url))


def download_url(url: str) -> str:
    """Google 雲端的檢視頁換成直接下載的網址。"""
    if "drive.google.com" in url:
        m = re.search(r"/file/d/([\w-]+)", url)
        file_id = m.group(1) if m else (parse_qs(urlparse(url).query).get("id") or [""])[0]
        if file_id:
            return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url


def download_pdf(client: PoliteClient, url: str) -> bytes | None:
    try:
        resp = client.get(download_url(url))
    except Exception as exc:
        log.info("orgsite: download failed %s (%s)", url, exc)
        return None
    body = resp.content
    if not body.startswith(b"%PDF") or len(body) > MAX_PDF_BYTES:
        return None  # 雲端的病毒掃描確認頁、太大的檔、其實不是 PDF
    return body


KIND_PRIORITY = {"financial": 0, "annual": 1, "work": 2}


def pick_for_extraction(docs: Iterable[DocLink]) -> list[DocLink]:
    """每年挑一份來讀數字：財務報告優先，其次年報；工作／成果報告通常沒有完整報表，不讀。"""
    best: dict[int, DocLink] = {}
    for d in docs:
        if d.doc_kind == "work":
            continue
        cur = best.get(d.year)
        if cur is None or KIND_PRIORITY[d.doc_kind] < KIND_PRIORITY[cur.doc_kind]:
            best[d.year] = d
    return [best[y] for y in sorted(best, reverse=True)]


Extractor = Callable[[bytes, int, str], "dict | None"]


def fetch(client: PoliteClient, limit: int | None = None, since_roc: int | None = None,
          targets: Iterable[tuple[str, str]] = (), extractor: Extractor | None = None,
          seen_docs: frozenset[str] | set[str] = frozenset()) -> Iterator[Item]:
    """targets：（統編, 官網）依序爬；limit 算的是組織數。seen_docs：已經讀過數字的檔案網址，不再讀（省費用）。"""
    done = 0
    for ubn, website in targets:
        if limit is not None and done >= limit:
            return
        if not is_crawlable_site(website):
            continue
        done += 1
        try:
            docs = discover(client, website, since_roc)
        except Exception as exc:  # 某個網站整個掛掉不影響其他組織
            log.warning("orgsite: %s %s failed: %s", ubn, website, exc)
            continue
        for d in docs:
            yield d.item(ubn)
        if extractor is None:
            continue
        for d in pick_for_extraction(docs):
            if d.url in seen_docs:
                continue
            pdf = download_pdf(client, d.url)
            if pdf is None:
                continue
            data = extractor(pdf, d.year, d.title)
            if not data:
                continue
            year = data.pop("year", None) or d.year
            if since_roc is not None and year < since_roc:
                continue
            yield Item(
                "financial", ubn,
                {"year": year, **data, "document_url": d.url, "document_title": d.title},
                source_url=d.url, external_id=str(year),
            )
