"""衛福部「公益勸募管理系統」sasw.mohw.gov.tw/app39 的勸募團體頁。

一個團體頁同時有：團體資訊、近五年裁處資訊、歷年募款達成情形、歷年活動列表。
"""

from __future__ import annotations

import logging
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from urllib.parse import quote, urljoin
from xml.etree.ElementTree import ParseError

import httpx
from bs4 import BeautifulSoup, Tag

from . import donors
from .http import PoliteClient
from .items import Item, money, roc_date

BASE = "https://sasw.mohw.gov.tw"
INDEX_URL = BASE + "/app39/fundgroup/fundgroupIndex?offset={offset}&max={size}"
GROUP_URL = BASE + "/app39/fundgroup/fundgroupDetails/{gid}"
SOURCE_NAME = "衛生福利部公益勸募管理系統"

GROUP_ID_RE = re.compile(r"/fundgroupDetails/(\d+)")
ACTIVITY_ID_RE = re.compile(r"/fundactivityDetails/(\d+)")
VIOLATION_ID_RE = re.compile(r"/violationDetails/(\d+)")
CITY_RE = re.compile(r"^(.{2}[縣市])")


def _text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _section(soup: BeautifulSoup, title: str) -> Tag | None:
    for h3 in soup.find_all("h3"):
        if title in _text(h3):
            return h3.find_parent(class_="title-2")
    return None


def _next_block(start: Tag | None, css_class: str) -> Tag | None:
    """從標題區塊往後找第一個帶 css_class 的兄弟節點，遇到 <hr> 就停（下一段了）。"""
    if start is None:
        return None
    for sib in start.find_next_siblings():
        if sib.name == "hr":
            return None
        if css_class in (sib.get("class") or []):
            return sib
        found = sib.find(class_=css_class)
        if found:
            return found
    return None


def normalize_city(address: str) -> str:
    m = CITY_RE.match((address or "").replace("台", "臺"))
    return m.group(1) if m else ""


def parse_index(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    ids: list[str] = []
    for a in soup.select("a.card-sg[href]"):
        m = GROUP_ID_RE.search(a["href"])
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


NAME_YEAR_RE = re.compile(r"^\s*(\d{2,3})\s*年")


def name_roc_year(name: str) -> int | None:
    """「114年度《行動音樂教室》…」→ 114；名稱沒寫年度回 None。"""
    m = NAME_YEAR_RE.match(name or "")
    return int(m.group(1)) if m else None


def parse_group(html: str, url: str, since_roc: int | None = None) -> list[Item]:
    """since_roc：只收這個民國年度（含）以後的年度募款與專案；裁處不受限。"""
    soup = BeautifulSoup(html, "html.parser")
    crumb = soup.select_one("li.breadcrumb-item.active")
    name = _text(crumb)
    if not name and soup.title:
        name = _text(soup.title).split("|")[0].strip()

    info: dict[str, str] = {}
    website = ""
    purposes: list[str] = []
    for box in soup.select("div.item-box"):
        left, right = box.select_one(".left"), box.select_one(".right")
        key = _text(left)
        if not key or right is None:
            continue
        if key == "團體網址":
            a = right.find("a", href=True)
            website = a["href"].strip() if a else ""
        elif key == "勸募用途":
            purposes = [_text(lbl) for lbl in right.select(".sg-label")]
        else:
            info[key] = _text(right)

    ubn = info.get("統一編號", "").strip()
    if not re.fullmatch(r"\d{8}", ubn):
        return []

    registered = info.get("團體登記地址", "")
    contact = info.get("團體聯絡地址", "")
    items = [
        Item(
            kind="org",
            ubn=ubn,
            data={
                "name": name,
                "org_type": info.get("團體類型", ""),
                "phone": info.get("團體電話", ""),
                "website": website,
                "registered_address": registered,
                "contact_address": contact,
                "purposes": "、".join(p for p in purposes if p),
                "city": normalize_city(registered) or normalize_city(contact),
            },
            source_url=url,
        )
    ]

    # 近五年裁處資訊
    penalty_block = _next_block(_section(soup, "裁處資訊"), "card-box")
    if penalty_block is not None:
        for card in penalty_block.select("a.card-violation"):
            href = urljoin(BASE, card.get("href", ""))
            m = VIOLATION_ID_RE.search(href)
            date_node = card.select_one(".date .right")
            items.append(
                Item(
                    kind="penalty",
                    ubn=ubn,
                    data={
                        "decided_on": roc_date(_text(date_node)),
                        "authority": "",
                        "content": _text(card.select_one(".punish-text")),
                        "fine_text": _text(card.select_one(".punish-price")),
                    },
                    source_url=href,
                    external_id=m.group(1) if m else "",
                )
            )

    # 歷年募款達成情形
    bi_table = soup.select_one("div.bi-table")
    if bi_table is not None:
        for row in bi_table.select("div.item"):
            cells = [_text(c) for c in row.select(".td .content")]
            if len(cells) < 3 or not cells[0].isdigit():
                continue
            if since_roc and int(cells[0]) < since_roc:
                continue
            items.append(
                Item(
                    kind="annual",
                    ubn=ubn,
                    data={"year": int(cells[0]), "raised": money(cells[1]) or 0, "target": money(cells[2]) or 0},
                    source_url=url,
                    external_id=cells[0],
                )
            )

    # 歷年活動列表（團體頁只列最近幾筆）
    activity_block = _next_block(_section(soup, "歷年活動列表"), "table-list-box")
    if activity_block is not None:
        for row in activity_block.select("div.item"):
            cells = [_text(c) for c in row.select(".td .content")]
            link = row.find("a", href=ACTIVITY_ID_RE)
            if not cells or not cells[0]:
                continue
            year = name_roc_year(cells[0])
            if since_roc and year is not None and year < since_roc:
                continue
            href = urljoin(BASE, link["href"]) if link else url
            m = ACTIVITY_ID_RE.search(href)
            cells += [""] * (5 - len(cells))
            items.append(
                Item(
                    kind="project",
                    ubn=ubn,
                    data={
                        "name": cells[0],
                        "category": "公益勸募活動",
                        "target": money(cells[1]),
                        "raised": money(cells[2]),
                        "result_filed_on": roc_date(cells[3]),
                        "closed_filed_on": roc_date(cells[4]),
                    },
                    source_url=href,
                    external_id=m.group(1) if m else cells[0],
                )
            )
    return items


ACTIVITY_INDEX_URL = BASE + "/app39/fundactivity/fundactivityIndex?qorg={org}&offset={offset}&max={size}"
ACTIVITY_URL = BASE + "/app39/fundactivity/fundactivityDetails/{aid}"
DONORS_RE = re.compile(r"/fundactivity/downloadDonors\?refid=\d+")
# 衛福部的 downloadDonors 會先讓請求等約 120 秒（2026-11-28 實測 120.1–120.6 秒，連小清冊也一樣），
# 才轉到 iframeDownload 給檔案；逾時設 120 秒會每一份都差一點拿不到（LK-40）
DONOR_FILE_TIMEOUT = 300.0
# 2026-11-28 起衛福部的清冊下載等完 120 秒後只回 4 個位元組「null」（網站端的問題，換 cookie、瀏覽器點都一樣）。
# 連續這麼多份都是空檔就這一輪不再下載清冊（每份還是要白等 2 分鐘），只抓活動頁；沒抓到的下一輪會再試（LK-40）
MAX_EMPTY_DONOR_FILES = 3
EMPTY_DONOR_FILE = object()  # _donor_list 的回傳：衛福部回空檔（跟「下載或解析失敗」分開算）
log = logging.getLogger(__name__)


def parse_activity_index(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    ids: list[str] = []
    for a in soup.select("a.card-sa[href]"):
        m = ACTIVITY_ID_RE.search(a["href"])
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def parse_activity(html: str, url: str, ubn: str) -> tuple[Item | None, str | None]:
    """勸募活動頁 → （補充專案欄位的 project Item, 捐贈人資料下載網址）。"""
    soup = BeautifulSoup(html, "html.parser")
    m = ACTIVITY_ID_RE.search(url)
    if not m:
        return None, None
    info: dict[str, str] = {}
    for box in soup.select("div.item-box, div.location"):
        left, right = box.select_one(".left"), box.select_one(".right")
        key = _text(left)
        if key and right is not None and key not in info:
            info[key] = _text(right)
    name = _text(soup.select_one("li.breadcrumb-item.active"))
    if not name:
        return None, None
    for card in soup.select("div.fa-inner-card"):
        topic, content = card.select_one(".topic"), card.select_one(".content")
        if topic and content is not None:
            info.setdefault(_text(topic), content.get_text("、", strip=True))
    data = {
        "name": name,
        "start_date": roc_date(info.get("勸募活動開始", "")),
        "end_date": roc_date(info.get("勸募活動結束", "")),
        "target": money(info.get("預募金額", "")),
        "raised": money(info.get("實募金額", "")),
        "permit_no": info.get("活動許可文號", ""),
        "region": info.get("活動地區", ""),
        "category": info.get("勸募用途", ""),
        "description": info.get("活動目的", "")[:2000],
    }
    data.update(parse_filings(soup))
    link = soup.find("a", href=DONORS_RE)
    donors_url = urljoin(BASE, link["href"]) if link else None
    return Item(kind="project", ubn=ubn, data=data, source_url=url, external_id=m.group(1)), donors_url


DUE_RE = re.compile(r"完成期限[：:]\s*(\d{2,3}/\d{1,2}/\d{1,2})")
FILINGS = {"成果備查": "result", "結案備查": "closed"}


def parse_filings(soup: BeautifulSoup) -> dict:
    """活動頁的成果備查、結案備查（口徑見 tickets/LK-43）。

    每一段是 <h3>標題</h3> 之後到下一條 <hr> 為止：「完成期限」是法定期限（成果＝勸募期滿後 30 日，公益勸募條例第 18 條；
    結案＝財物使用計畫執行完竣後 30 日，第 20 條），不是完成日；有公開徵信網址、下載檔或「已完成備查」＝已備查；
    紅色「逾期備查」＝過了期限（不論後來有沒有補交）。頁面沒有這一段就不回傳那幾個欄位。
    """
    out: dict = {}
    for h3 in soup.find_all("h3"):
        prefix = FILINGS.get(_text(h3))
        if not prefix:
            continue
        parts = []
        for sib in h3.find_parent("div").find_next_siblings():
            if sib.name == "hr":
                break
            parts.append(sib)
        text = " ".join(_text(x) for x in parts)
        due = DUE_RE.search(text)
        done = any(x.select_one(".link-box, a.item-d, .finish-badge") for x in parts) or "已完成備查" in text
        out[f"{prefix}_due_on"] = roc_date(due.group(1)) if due else None
        out[f"{prefix}_done"] = bool(done)
        out[f"{prefix}_late"] = "逾期備查" in text
    return out


def list_activity_ids(client: PoliteClient, org_name: str, page_size: int = 10) -> list[str]:
    ids: list[str] = []
    offset = 0
    while True:
        url = ACTIVITY_INDEX_URL.format(org=quote(org_name), offset=offset, size=page_size)
        page = parse_activity_index(client.get(url).text)
        fresh = [i for i in page if i not in ids]
        if not fresh:
            return ids
        ids.extend(fresh)
        offset += len(page)


ACTIVITY_YEAR_URL = (
    BASE + "/app39/fundactivity/fundactivityIndex?qorg=&qyyy={year}&qtitle=&qactiveArea=&qactiveArea2=&qestNo="
    "&offset={offset}&max={size}"
)
GROUP_SEARCH_URL = BASE + "/app39/fundgroup/fundgroupIndex?qdisplayName={name}"
RAISED_RE = re.compile(r"實募\s*NT\$?\s*([\d,]+)")


@dataclass(frozen=True)
class ActivityCard:
    """活動列表上的一張卡片：不用開活動頁就知道是誰辦的、目前實募多少。"""

    aid: str
    name: str
    org_name: str
    raised: int | None
    year: int


def parse_activity_cards(html: str, year: int) -> list[ActivityCard]:
    soup = BeautifulSoup(html, "html.parser")
    cards: list[ActivityCard] = []
    for a in soup.select("a.card-sa[href]"):
        m = ACTIVITY_ID_RE.search(a["href"])
        if not m or any(c.aid == m.group(1) for c in cards):
            continue
        raised = RAISED_RE.search(_text(a.select_one(".sa-number")))
        cards.append(ActivityCard(
            aid=m.group(1),
            name=_text(a.select_one(".sa-title")) or a.get("title", "").strip(),
            org_name=_text(a.select_one(".sa-group")),
            raised=money(raised.group(1)) if raised else None,
            year=year,
        ))
    return cards


def list_activity_cards(client: PoliteClient, year: int, page_size: int = 9) -> list[ActivityCard]:
    """某個勸募年度的所有活動（列表一頁 9 張，翻到沒有新卡片為止）。"""
    cards: list[ActivityCard] = []
    seen: set[str] = set()
    offset = 0
    while True:
        page = parse_activity_cards(client.get(ACTIVITY_YEAR_URL.format(year=year, offset=offset, size=page_size)).text, year)
        fresh = [c for c in page if c.aid not in seen]
        if not fresh:
            return cards
        cards.extend(fresh)
        seen.update(c.aid for c in fresh)
        offset += len(page)


def exact_group_ids(search_html: str, name: str) -> list[str]:
    """團體查詢結果裡，名稱完全相同的團體編號（可能不只一個）。"""
    soup = BeautifulSoup(search_html, "html.parser")
    ids: list[str] = []
    for a in soup.select("a.card-sg[href]"):
        m = GROUP_ID_RE.search(a["href"])
        if m and a.get("title", "").strip() == name.strip() and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


class ActivityPlan:
    """決定這次要抓哪些活動、記住抓到哪裡。預設（爬蟲單獨跑）：全部都抓、什麼都不記。
    後端換成記在資料庫的版本（crawling/progress.py），才能每晚接著抓、只抓新的與有變的。"""

    def should_list(self, year: int) -> bool:
        """這個年度要不要重新翻活動列表（不翻就用上次記下的卡片）。"""
        return True

    def stored_cards(self, year: int) -> list[ActivityCard]:
        return []

    def select(self, cards: list[ActivityCard], listed: bool = True) -> list[ActivityCard]:
        return cards

    def ubn_for(self, org_name: str) -> str | None:
        return None

    def need_donors(self, card: ActivityCard) -> bool:
        return True

    def done(self, card: ActivityCard, ubn: str, *, end_date, has_donor_link: bool, donors_fetched: bool,
             filings: dict | None = None) -> None:
        pass

    def unmatched(self, card: ActivityCard, reason: str) -> None:
        log.warning("活動 %s 的申請單位「%s」對不到團體：%s", card.aid, card.org_name, reason)


def fetch_activities(client: PoliteClient, limit: int | None = None,
                     threshold: int = donors.DEFAULT_INDIVIDUAL_THRESHOLD, since_roc: int | None = None,
                     plan: ActivityPlan | None = None, this_roc: int | None = None) -> Iterator[Item]:
    """依勸募年度（去年 → since_roc，再今年、明年）一年一年處理：列出活動 → plan 挑出要抓的 → 活動頁＋需要的話下載清冊。
    列完一年就先抓那一年，時間上限短也抓得到東西。limit 算的是活動數。
    第一次遇到的申請單位：用名稱查團體、抓一次團體頁（組織才建得起來）。"""
    plan = plan or ActivityPlan()
    this_roc = this_roc or date.today().year - 1911
    groups: dict[str, tuple[str | None, str]] = {}  # 申請單位 → (統編, 對不到的原因)；同一次執行同名只查一次
    seen: set[str] = set()
    count = 0
    empty_streak = 0  # 連續幾份清冊衛福部回空檔
    # 去年 → 往前到 since_roc，再今年、明年：清冊在活動結束後才有，已結束的年度先抓，不讓進行中的活動佔掉時間上限
    # （補齊之後過去的年度 7 天才翻一次，平常很快就輪到今年）
    first = since_roc if since_roc and since_roc < this_roc else this_roc
    for year in [*range(this_roc - 1, first - 1, -1), this_roc, this_roc + 1]:
        listed = plan.should_list(year)
        cards = [c for c in (list_activity_cards(client, year) if listed else plan.stored_cards(year)) if c.aid not in seen]
        seen.update(c.aid for c in cards)
        for card in plan.select(cards, listed):
            if limit and count >= limit:
                return
            if card.org_name not in groups:
                ubn = plan.ubn_for(card.org_name)
                reason = ""
                if ubn is None:
                    ubn, reason, group_items = _find_group(client, card.org_name, since_roc)
                    yield from group_items
                groups[card.org_name] = (ubn, reason)
            ubn, reason = groups[card.org_name]
            if not ubn:
                plan.unmatched(card, reason)
                continue
            count += 1
            url = ACTIVITY_URL.format(aid=card.aid)
            project, donors_url = parse_activity(client.get(url).text, url, ubn)
            if project is None:
                plan.unmatched(card, "活動頁讀不到")
                continue
            yield project
            fetched = False
            if donors_url and plan.need_donors(card) and empty_streak < MAX_EMPTY_DONOR_FILES:
                item = _donor_list(client, donors_url, project, ubn, url, threshold)
                if item is EMPTY_DONOR_FILE:
                    empty_streak += 1
                    if empty_streak == MAX_EMPTY_DONOR_FILES:
                        log.warning("衛福部連續 %d 份清冊都回空檔，這一輪先不下載清冊、只抓活動頁", empty_streak)
                elif item is not None:
                    empty_streak = 0
                    yield item
                    fetched = True
            plan.done(card, ubn, end_date=project.data.get("end_date"), has_donor_link=bool(donors_url),
                      donors_fetched=fetched,
                      filings={k: v for k, v in project.data.items() if k.startswith(("result_", "closed_"))})


def _find_group(client: PoliteClient, name: str, since_roc: int | None) -> tuple[str | None, str, list[Item]]:
    """用名稱查團體：名稱完全相同的只有一個才算，並抓它的團體頁（統編、基本資料、年度募款、裁處）。"""
    gids = exact_group_ids(client.get(GROUP_SEARCH_URL.format(name=quote(name))).text, name)
    if not gids:
        return None, "團體列表查無此名稱", []
    if len(gids) > 1:
        return None, "同名團體不只一個", []
    group_url = GROUP_URL.format(gid=gids[0])
    items = parse_group(client.get(group_url).text, group_url, since_roc=since_roc)
    org = next((i for i in items if i.kind == "org"), None)
    if org is None:
        return None, "團體頁讀不到統一編號", []
    return org.ubn, "", items


def _donor_list(client: PoliteClient, donors_url: str, project: Item, ubn: str, url: str, threshold: int) -> Item | object | None:
    try:
        # 大型團體的清冊有好幾 MB、十幾萬列，下載給長一點的時間
        data = client.get(donors_url, timeout=DONOR_FILE_TIMEOUT).content
        if data.strip() in (b"", b"null"):
            log.warning("衛福部回空檔（不是清冊）%s：%r", donors_url, data[:20])
            return EMPTY_DONOR_FILE
        result = donors.summarize(donors.parse_ods(data), threshold)
    except (httpx.HTTPError, zipfile.BadZipFile, ParseError) as exc:
        # 一份清冊壞掉不拖垮其他活動；下次重跑會再試（內容沒存，不會被去重擋掉）
        log.warning("捐贈人清冊下載或解析失敗 %s：%s", donors_url, exc)
        return None
    return Item(
        kind="donor_list",
        ubn=ubn,
        data={"project_name": project.data["name"], **result},
        source_url=url,
        external_id=project.external_id,
    )


def fetch_activities_for(client: PoliteClient, group_ids, threshold: int = donors.DEFAULT_INDIVIDUAL_THRESHOLD,
                         since_roc: int | None = None) -> Iterator[Item]:
    """每個團體：列出所有勸募活動 → 活動頁補專案欄位 → 有捐贈人資料就下載清冊整理成 donor_list。"""
    for gid in group_ids:
        group_url = GROUP_URL.format(gid=gid)
        group_items = parse_group(client.get(group_url).text, group_url, since_roc=since_roc)
        org = next((i for i in group_items if i.kind == "org"), None)
        if org is None:
            continue
        yield from group_items  # 團體頁的資料一起帶上：這個來源單獨跑也是完整的
        for aid in list_activity_ids(client, org.data["name"]):
            url = ACTIVITY_URL.format(aid=aid)
            project, donors_url = parse_activity(client.get(url).text, url, org.ubn)
            if project is None:
                continue
            start = project.data.get("start_date")
            year = start.year - 1911 if start else name_roc_year(project.data["name"])
            if since_roc and year is not None and year < since_roc:
                continue  # 舊活動：不收、也不下載清冊
            yield project
            if donors_url:
                item = _donor_list(client, donors_url, project, org.ubn, url, threshold)
                if item is not None and item is not EMPTY_DONOR_FILE:
                    yield item


def list_group_ids(client: PoliteClient, limit: int | None = None, page_size: int = 10) -> Iterator[str]:
    seen: set[str] = set()
    offset = 0
    while True:
        ids = parse_index(client.get(INDEX_URL.format(offset=offset, size=page_size)).text)
        fresh = [i for i in ids if i not in seen]
        if not fresh:
            return
        for gid in fresh:
            seen.add(gid)
            yield gid
            if limit and len(seen) >= limit:
                return
        offset += len(ids)


def fetch(client: PoliteClient, limit: int | None = None, since_roc: int | None = None) -> Iterator[Item]:
    for gid in list_group_ids(client, limit=limit):
        url = GROUP_URL.format(gid=gid)
        yield from parse_group(client.get(url).text, url, since_roc=since_roc)
