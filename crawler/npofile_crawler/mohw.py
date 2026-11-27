"""衛福部「公益勸募管理系統」sasw.mohw.gov.tw/app39 的勸募團體頁。

一個團體頁同時有：團體資訊、近五年裁處資訊、歷年募款達成情形、歷年活動列表。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

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


def parse_group(html: str, url: str) -> list[Item]:
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
                        "authority": "衛生福利部或地方主管機關（公益勸募條例）",
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


def fetch(client: PoliteClient, limit: int | None = None) -> Iterator[Item]:
    for gid in list_group_ids(client, limit=limit):
        url = GROUP_URL.format(gid=gid)
        yield from parse_group(client.get(url).text, url)
