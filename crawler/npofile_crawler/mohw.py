"""衛福部「公益勸募管理系統」sasw.mohw.gov.tw/app39 的勸募團體頁。

一個團體頁同時有：團體資訊、近五年裁處資訊、歷年募款達成情形、歷年活動列表。
"""

from __future__ import annotations

import logging
import re
import zipfile
from collections.abc import Iterator
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
DONOR_FILE_TIMEOUT = 120.0
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
    link = soup.find("a", href=DONORS_RE)
    donors_url = urljoin(BASE, link["href"]) if link else None
    return Item(kind="project", ubn=ubn, data=data, source_url=url, external_id=m.group(1)), donors_url


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


def fetch_activities(client: PoliteClient, limit: int | None = None,
                     threshold: int = donors.DEFAULT_INDIVIDUAL_THRESHOLD, since_roc: int | None = None) -> Iterator[Item]:
    yield from fetch_activities_for(client, list_group_ids(client, limit=limit), threshold, since_roc)


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
                try:
                    # 大型團體的清冊有好幾 MB、十幾萬列，下載給長一點的時間
                    data = client.get(donors_url, timeout=DONOR_FILE_TIMEOUT).content
                    result = donors.summarize(donors.parse_ods(data), threshold)
                except (httpx.HTTPError, zipfile.BadZipFile, ParseError) as exc:
                    # 一份清冊壞掉不拖垮整個團體；下次重跑會再試（內容沒存，不會被去重擋掉）
                    log.warning("捐贈人清冊下載或解析失敗 %s：%s", donors_url, exc)
                    continue
                yield Item(
                    kind="donor_list",
                    ubn=org.ubn,
                    data={"project_name": project.data["name"], **result},
                    source_url=url,
                    external_id=project.external_id,
                )


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
