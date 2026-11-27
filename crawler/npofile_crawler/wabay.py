"""挖貝 WaBay 群眾集資平台 wabay.tw 的集資專案（LK-15）。

只照 robots.txt 抓 `/projects` 列表與 `/projects/<代號>` 專案頁（`/organizations/`、`/api/` 禁止，不碰）。
服務條款禁止重製網站內容，所以只取事實欄位：名稱、提案者統編、金額、人次、期間、網址；不取介紹文案與圖片。

公開列表只列進行中的專案，已結束的要靠後端記得代號（`revisit`），在結束後回頭再看幾次。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date

import httpx
from bs4 import BeautifulSoup

from .http import PoliteClient
from .items import Item, money

BASE = "https://wabay.tw"
INDEX_URL = BASE + "/projects?locale=zh-TW&page={page}"
PROJECT_URL = BASE + "/projects/{slug}"
SOURCE_NAME = "挖貝 WaBay 群眾集資"
CHANNEL = "crowdfunding"
MAX_PAGES = 50

log = logging.getLogger(__name__)

# 列表卡片的連結都帶 ?context=…；分類、排序那些是 /projects?…，不會對到
SLUG_RE = re.compile(r'href="/projects/([A-Za-z0-9][A-Za-z0-9_-]{0,49})\?context=')
UBN_RE = re.compile(r"^\d{8}$")
DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


def list_slugs(html: str) -> list[str]:
    """列表頁上的專案代號（保持出現順序、去重）。"""
    return list(dict.fromkeys(SLUG_RE.findall(html)))


def _lines(soup: BeautifulSoup) -> list[str]:
    for tag in soup(["script", "style"]):
        tag.decompose()
    return [t for t in (x.strip() for x in soup.get_text("\n").split("\n")) if t]


def _after(lines: list[str], label: str, start: int = 0) -> tuple[int, str]:
    """label 那一行的位置，與下一行的內容；找不到回 (-1, "")。"""
    try:
        i = lines.index(label, start)
    except ValueError:
        return -1, ""
    return i, lines[i + 1] if i + 1 < len(lines) else ""


def _date(text: str) -> date | None:
    m = DATE_RE.search(text or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


@dataclass
class Project:
    slug: str
    name: str
    proposer: str
    ubn: str
    tags: list[str]
    start_date: date | None
    end_date: date | None
    long_term: bool
    target: int | None         # 一次性目標；有定期定額的專案目標是每月的，不記
    raised: int | None         # 一次性的募得：沒有定期定額＝已募集；有＝單次贊助
    monthly: int | None        # 每月定期定額
    backers: int | None

    @property
    def url(self) -> str:
        return PROJECT_URL.format(slug=self.slug)

    def description(self) -> str:
        """我們自己組的一句話（不放抓取日期：內容沒變就不產生新的待審資料）。"""
        parts = []
        if self.monthly is not None:
            parts.append(f"定期定額每月 {self.monthly:,} 元")
            if self.raised is not None:
                parts.append(f"單次贊助 {self.raised:,} 元")
        elif self.raised is not None:
            parts.append(f"已募集 {self.raised:,} 元")
        text = "、".join(parts)
        if self.backers is not None:
            text += f"，{self.backers:,} 人參與" if text else f"{self.backers:,} 人參與"
        return f"挖貝群眾集資：{text}（挖貝頁面顯示的即時金額）"


def parse_project(html: str, slug: str) -> Project | None:
    """專案頁 → Project；頁面結構認不出來回 None。"""
    soup = BeautifulSoup(html, "html.parser")
    name = ""
    for node in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(node.string or "")
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "CreativeWork":
            name = (data.get("name") or "").strip()
    lines = _lines(soup)

    top, _ = _after(lines, "已募集")
    if top < 0:
        return None
    if not name:
        name = lines[top - 2] if top >= 2 else ""

    # 已募集區塊：目標 TWD$ X（/ 月）、TWD$ Y（/ 月）、N 人參與、（定期定額 TWD$ / 月、單次贊助 TWD$）、專案時間
    end_i, period = _after(lines, "專案時間", top)
    block = lines[top:end_i if end_i > 0 else top + 30]
    target_text = next((l for l in block if l.startswith("目標")), "")
    monthly_i, monthly_text = _after(block, "定期定額")
    once_i, once_text = _after(block, "單次贊助")
    has_monthly = monthly_i >= 0

    amounts = [i for i, l in enumerate(block) if l.startswith("TWD$")]
    headline = money(block[amounts[0]]) if amounts else None
    backers_i, _ = _after(block, "人參與")
    backers = money(block[backers_i - 1]) if backers_i > 0 else None

    if has_monthly:
        raised = money(once_text) if once_i >= 0 else None
        monthly = money(monthly_text)
        target = None
    else:
        raised, monthly = headline, None
        target = money(target_text)

    start, _, end = period.partition("~")
    long_term = "長期集資" in end

    proposer_i, proposer = _after(lines, "提案者名稱")
    _, ubn = _after(lines, "統一編號", max(proposer_i, 0))
    tags = []
    for l in lines[:top]:
        if l == "►":
            break
        if l.startswith("#") and l[1:] not in tags:
            tags.append(l[1:])

    return Project(
        slug=slug, name=name, proposer=proposer, ubn=ubn if UBN_RE.match(ubn) else "", tags=tags,
        start_date=_date(start), end_date=None if long_term else _date(end), long_term=long_term,
        target=target, raised=raised, monthly=monthly, backers=backers,
    )


def to_item(p: Project) -> Item:
    return Item(
        kind="project",
        ubn=p.ubn,
        external_id=p.slug,
        source_url=p.url,
        data={
            "name": p.name,
            "channel": CHANNEL,
            "category": "、".join(p.tags)[:100],
            "start_date": p.start_date,
            "end_date": p.end_date,
            "target": p.target,
            "raised": p.raised,
            "monthly_raised": p.monthly,
            "backers": p.backers,
            "description": p.description(),
        },
        extra={"proposer": p.proposer},
    )


def fetch(client: PoliteClient, limit: int | None = None, revisit: Iterable[str] = ()) -> Iterator[Item]:
    """翻完進行中的列表，再補看 revisit（後端給：已收過、還沒結束太久的專案代號）。
    提案者沒有統編的不回傳（多半是個人提案）；統編在不在資料庫由後端判斷。limit 算專案數。"""
    slugs: list[str] = []
    for page in range(1, MAX_PAGES + 1):
        found = [s for s in list_slugs(client.get(INDEX_URL.format(page=page)).text) if s not in slugs]
        if not found:
            break
        slugs.extend(found)
    slugs.extend(s for s in dict.fromkeys(revisit) if s not in slugs)

    count = 0
    for slug in slugs:
        if limit is not None and count >= limit:
            return
        try:
            resp = client.get(PROJECT_URL.format(slug=slug) + "?locale=zh-TW")
        except httpx.HTTPStatusError as exc:
            # 專案被下架（404）不算整個來源失敗，跳過這一個
            if exc.response is not None and exc.response.status_code == 404:
                log.warning("wabay project gone: %s", slug)
                continue
            raise
        count += 1
        project = parse_project(resp.text, slug)
        if project is None:
            log.warning("wabay project page not recognised: %s", slug)
            continue
        if not project.ubn:
            continue
        yield to_item(project)
