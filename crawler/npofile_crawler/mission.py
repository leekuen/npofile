"""組織官網：成立宗旨與一句話介紹（LK-54）。

從官網首頁找「關於我們／宗旨／緣起／理念」這類同站連結，最多讀 MAX_ABOUT_PAGES 頁；找官網與禮貌爬取沿用
orgsite（LK-17：同一套 is_crawlable_site、robots.txt）。每頁先找「宗旨／使命／理念」標題底下那一段，
沒有再找寫著「本會／本基金會…致力」的段落，都沒有才用首頁的 meta description。

一句話介紹（40 字內）：給了 summarizer（ClaudeSummarizer，要 ANTHROPIC_API_KEY）就請 Claude 濃縮，
沒給或 Claude 失敗就取原文第一句（first_sentence）。

Item 種類：
- mission：{text, summary, summary_method: claude | first_sentence, page_url}；external_id 固定 "mission"
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from .http import PoliteClient
from .items import Item
from .orgsite import _clean, _host, _Robots, is_crawlable_site

log = logging.getLogger(__name__)

SOURCE_NAME = "組織官網（成立宗旨）"
MAX_ABOUT_PAGES = 4
MAX_TEXT = 1000
SUMMARY_MAX = 40
MIN_TEXT = 15

# 要點進去看的連結（分數高的先讀）
ABOUT_PATTERNS = (
    (3, re.compile(r"宗旨|使命|理念|緣起|成立目的|mission", re.I)),
    (2, re.compile(r"關於|簡介|介紹|認識|沿革|願景|about|who-?we-?are|intro|vision", re.I)),
)
# 段落標題：底下那一段就是宗旨
HEAD_RE = re.compile(r"(?:成立)?宗旨|使命|理念|緣起|成立目的|設立目的|mission", re.I)
# 同一行「宗旨：……」
INLINE_RE = re.compile(r"(?:成立宗旨|本會宗旨|宗旨|使命|理念|成立目的|設立目的)\s*[:：為是]\s*(.{%d,})" % MIN_TEXT)
# 沒有標題時，像在介紹自己的段落
SELF_RE = re.compile(r"本會|本協會|本基金會|本學會|本中心|我們|致力|宗旨|成立於|創立於|服務")
# 不是在講組織在做什麼的段落
NOISE_RE = re.compile(r"版權|copyright|cookie|隱私|地址|電話|傳真|e-?mail|統一編號|捐款專線|劃撥|帳號|登入|訂閱|瀏覽人次", re.I)
DROP_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "form", "aside", "iframe", "svg")
HEAD_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "dt", "th", "legend")
BLOCK_TAGS = ("p", "div", "li", "dd", "td", "section", "article", "span")
SENTENCE_END = "。！？!?；;\n"


@dataclass(frozen=True)
class Mission:
    text: str
    page_url: str


def about_links(html: str, page_url: str) -> list[str]:
    """首頁上要點進去看的同站連結，分數高的在前；同分照出現順序。"""
    soup = BeautifulSoup(html, "html.parser")
    scored: dict[str, tuple[int, int]] = {}
    for i, a in enumerate(soup.find_all("a", href=True)):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urljoin(page_url, href).split("#", 1)[0]
        if _host(url) != _host(page_url) or url.rstrip("/") == page_url.rstrip("/"):
            continue
        if re.search(r"\.(?:pdf|docx?|xlsx?|jpe?g|png|zip)$", urlparse(url).path, re.I):
            continue
        text = _clean(" ".join([a.get_text(" "), a.get("title", "")]))
        if len(text) > 30:  # 一整段文章裡的連結，不是選單
            text = ""
        hay = f"{text} {unquote(urlparse(url).path)}"
        score = next((s for s, p in ABOUT_PATTERNS if p.search(hay)), 0)
        if score and (url not in scored or scored[url][0] < score):
            scored[url] = (score, scored.get(url, (0, i))[1])
    return [u for u, _ in sorted(scored.items(), key=lambda kv: (-kv[1][0], kv[1][1]))]


def _menu_like(text: str) -> bool:
    """「認識創世 創世故事 創世宗旨 組織架構 …」：一串短詞，是選單不是一段話。"""
    words = text.split()
    return len(words) >= 5 and sum(map(len, words)) / len(words) < 7


def _link_heavy(el) -> bool:
    """大部分的字都是連結（選單、相關文章列表）。"""
    total = len(_clean(el.get_text(" ")))
    linked = sum(len(_clean(a.get_text(" "))) for a in el.find_all("a"))
    return total > 0 and linked / total > 0.5


def _usable(text: str) -> bool:
    return len(text) >= MIN_TEXT and not NOISE_RE.search(text) and not _menu_like(text)


def _after_heading(head) -> str:
    """標題後面的文字：同一層往後讀，讀到下一個標題或夠長就停；標題自己在一段裡（「宗旨：…」）就取那一段。"""
    parent = head.parent
    if parent is not None and parent.name in ("p", "li", "dd", "td"):
        label = _clean(head.get_text(" "))
        rest = _clean(parent.get_text(" ")).split(label, 1)[-1].lstrip(" :：")
        if _usable(rest):
            return rest
    parts: list[str] = []
    inside = set(map(id, head.descendants))
    for sib in head.find_all_next(limit=60):
        if id(sib) in inside:
            continue
        if sib.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if parts:
                break
            continue
        if sib.name not in ("p", "li", "dd", "td", "div", "span"):
            continue
        if sib.find(["p", "li", "dd", "div"]):  # 外層容器：讓裡面那幾段自己被讀
            continue
        if _link_heavy(sib):
            continue
        text = _clean(sib.get_text(" "))
        if parts and any(text in p for p in parts):  # span 在已讀過的 p 裡
            continue
        if not text or text in parts:
            continue
        if NOISE_RE.search(text):
            break
        parts.append(text)
        if sum(len(p) for p in parts) >= 300:
            break
    return _clean(" ".join(parts))


def extract(html: str) -> str | None:
    """一頁裡的宗旨原文；找不到回 None。"""
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    description = _clean(meta.get("content", "")) if meta else ""
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()
    # 1. 「宗旨」「使命」標題底下那一段
    for head in soup.find_all(HEAD_TAGS):
        label = _clean(head.get_text(" "))
        if not label or len(label) > 20 or not HEAD_RE.search(label):
            continue
        text = _after_heading(head)
        if _usable(text):
            return text[:MAX_TEXT]
    # 2. 同一段裡寫「宗旨：……」
    for block in soup.find_all(BLOCK_TAGS):
        if block.find(BLOCK_TAGS):
            continue
        m = INLINE_RE.search(_clean(block.get_text(" ")))
        if m and _usable(m.group(1)):
            return m.group(1)[:MAX_TEXT]
    # 3. 像在介紹自己的段落（夠長、不是頁尾資訊）
    for p in soup.find_all(["p", "div"]):
        if p.find(["p", "div"]) or _link_heavy(p):
            continue
        text = _clean(p.get_text(" "))
        if 30 <= len(text) and SELF_RE.search(text) and _usable(text):
            return text[:MAX_TEXT]
    # 4. 首頁的 meta description
    if len(description) >= 20 and _usable(description):
        return description[:MAX_TEXT]
    return None


LABEL_RE = re.compile(r"^(?:(?:本會|本協會|本基金會)?(?:成立)?(?:宗旨|使命|理念|緣起)\s*[:：]\s*|關於\S{1,10}\s+)")


def first_sentence(text: str, limit: int = SUMMARY_MAX) -> str:
    """原文第一句（沒設金鑰時的一句話介紹）；超過 limit 字截斷、補「…」。"""
    text = LABEL_RE.sub("", _clean(text))
    cut = next((i for i, ch in enumerate(text) if ch in SENTENCE_END), len(text))
    sentence = text[:cut].strip(" ，,、")
    if len(sentence) > limit:
        sentence = sentence[: limit - 1].rstrip(" ，,、") + "…"
    return sentence


PROMPT = """以下是「{name}」官網或主管機關名冊上的成立宗旨。請用一句話（不超過 {limit} 個中文字）告訴捐款人這個組織在做什麼、幫助誰。
只根據原文，不要加原文沒有的事；不要寫組織名稱開頭，不要加引號或句號以外的標點收尾。只回那一句話。

原文：
{text}"""


class ClaudeSummarizer:
    """summarizer(組織名稱, 原文) → 一句話；API 出錯、被拒絕、太長都回 None（改用第一句），不中斷爬蟲。"""

    method = "claude"

    def __init__(self, client=None, model: str = "claude-haiku-5-5", max_calls: int | None = None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.max_calls = max_calls
        self.calls = 0

    def __call__(self, name: str, text: str) -> str | None:
        if self.max_calls is not None and self.calls >= self.max_calls:
            return None
        self.calls += 1
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[{"role": "user", "content": PROMPT.format(name=name, limit=SUMMARY_MAX, text=text[:MAX_TEXT])}],
            )
        except Exception as exc:  # 金鑰錯、額度用完：這一筆改用第一句
            log.warning("mission: summary failed for %s: %s", name, exc)
            return None
        if response.stop_reason == "refusal":
            return None
        out = _clean(next((b.text for b in response.content if b.type == "text"), "")).strip("「」\"' ")
        if not out or len(out) > SUMMARY_MAX + 5:
            return None
        return out


Summarizer = Callable[[str, str], "str | None"]


def summarize(name: str, text: str, summarizer: Summarizer | None) -> tuple[str, str]:
    """（一句話介紹, 摘要方式）。"""
    if summarizer is not None:
        out = summarizer(name, text)
        if out:
            return out, getattr(summarizer, "method", "claude")
    return first_sentence(text), "first_sentence"


def text_hash(text: str) -> str:
    return hashlib.sha1(_clean(text).encode("utf-8")).hexdigest()[:20]


def discover(client: PoliteClient, website: str) -> Mission | None:
    """首頁＋最多 MAX_ABOUT_PAGES 個關於頁；關於頁找得到就用關於頁的，都沒有才用首頁自己的。"""
    robots = _Robots(client, website)
    if not robots.allowed(website):
        return None
    try:
        resp = client.get(website)
    except Exception as exc:
        log.info("mission: skip %s (%s)", website, exc)
        return None
    if "html" not in resp.headers.get("content-type", "html"):
        return None
    home_url = str(resp.url)
    if _host(home_url) != _host(website) and not is_crawlable_site(home_url):
        return None  # 首頁轉到臉書之類
    home_html = resp.text
    for url in about_links(home_html, home_url)[:MAX_ABOUT_PAGES]:
        if not robots.allowed(url):
            continue
        try:
            page = client.get(url)
        except Exception as exc:
            log.info("mission: skip %s (%s)", url, exc)
            continue
        if "html" not in page.headers.get("content-type", "html"):
            continue
        text = extract(page.text)
        if text:
            return Mission(text, str(page.url))
    text = extract(home_html)
    return Mission(text, home_url) if text else None


def fetch(client: PoliteClient, limit: int | None = None, mission_targets: Iterable[tuple[str, str, str]] = (),
          summarizer: Summarizer | None = None, mission_seen: Mapping[str, str] | None = None) -> Iterator[Item]:
    """mission_targets：（統編, 名稱, 官網）依序爬，limit 算組織數。
    mission_seen：{統編: 上次抓到的原文 text_hash}；原文沒變就不再送出（不重摘要、不重進審核清單）。"""
    seen = mission_seen or {}
    done = 0
    for ubn, name, website in mission_targets:
        if limit is not None and done >= limit:
            return
        if not is_crawlable_site(website):
            continue
        done += 1
        try:
            found = discover(client, website)
        except Exception as exc:  # 某個網站整個掛掉不影響其他組織
            log.warning("mission: %s %s failed: %s", ubn, website, exc)
            continue
        if found is None or seen.get(ubn) == text_hash(found.text):
            continue
        summary, method = summarize(name, found.text, summarizer)
        yield Item(
            "mission", ubn,
            {"text": found.text, "summary": summary, "summary_method": method, "page_url": found.page_url},
            source_url=found.page_url, external_id="mission",
        )
