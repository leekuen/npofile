"""公益勸募管理系統「違規公告」總表：所有年度的裁處（團體頁只列近五年）。

違規公告只寫團體名稱、沒有統編：用名稱到團體查詢頁找出團體，再從團體頁拿統編。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from urllib.parse import quote

from bs4 import BeautifulSoup

from . import mohw
from .http import PoliteClient
from .items import Item, roc_date

log = logging.getLogger(__name__)

INDEX_URL = mohw.BASE + "/app39/violation/violationIndex?offset={offset}&max={size}"
DETAIL_URL = mohw.BASE + "/app39/violation/violationDetails/{vid}"
GROUP_SEARCH_URL = mohw.BASE + "/app39/fundgroup/fundgroupIndex?qdisplayName={name}"
# 「新北市政府新北府社團字第…號」「衛生福利部衛部救字第…號」→ 開頭的機關名稱
AUTHORITY_RE = re.compile(r"^(.+?(?:政府|部|署|局|委員會))")


def parse_index(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    ids: list[str] = []
    for a in soup.select("a.card-violation[href]"):
        m = mohw.VIOLATION_ID_RE.search(a["href"])
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def parse_detail(html: str, url: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    m = mohw.VIOLATION_ID_RE.search(url)
    fields: dict[str, str] = {}
    for item in soup.select(".inner-box-content .item"):
        key = mohw._text(item.select_one(".left")).rstrip("：:")
        fields[key] = mohw._text(item.select_one(".right"))
    name = fields.get("勸募團體", "")
    if not m or not name:
        return None
    date_text = mohw._text(soup.select_one(".inner-head-between .right")).replace("處分日期：", "")

    def section(title: str) -> str:
        block = mohw._next_block(mohw._section(soup, title), "inner-content")
        if block is None:
            return ""
        # 處分內容區塊裡的紅框是罰鍰，另外取
        for red in block.select(".bg-red"):
            red.extract()
        return mohw._text(block)

    content_block = mohw._next_block(mohw._section(soup, "處分內容"), "inner-content")
    fine = mohw._text(content_block.select_one(".bg-red")) if content_block else ""
    document_no = fields.get("文號", "")
    auth = AUTHORITY_RE.match(document_no)
    return {
        "id": m.group(1),
        "group_name": name,
        "decided_on": roc_date(date_text),
        "document_no": document_no,
        "authority": auth.group(1) if auth else "",
        "content": section("處分內容") or mohw._text(soup.select_one(".inner-box-content .bottom")),
        "fine_text": fine,
        "reason": section("處分理由"),
    }


def find_group_id(search_html: str, name: str) -> str | None:
    """團體查詢結果裡，名稱完全相同的那一個。"""
    soup = BeautifulSoup(search_html, "html.parser")
    for a in soup.select("a.card-sg[href]"):
        if a.get("title", "").strip() == name.strip():
            m = mohw.GROUP_ID_RE.search(a["href"])
            if m:
                return m.group(1)
    return None


def fetch(client: PoliteClient, limit: int | None = None, since_roc: int | None = None) -> Iterator[Item]:
    groups: dict[str, list[Item] | None] = {}
    seen: list[str] = []
    offset = 0
    while True:
        ids = [i for i in parse_index(client.get(INDEX_URL.format(offset=offset, size=9)).text) if i not in seen]
        if not ids:
            return
        for vid in ids:
            seen.append(vid)
            url = DETAIL_URL.format(vid=vid)
            data = parse_detail(client.get(url).text, url)
            if data is None:
                continue
            name = data["group_name"]
            if name not in groups:
                gid = find_group_id(client.get(GROUP_SEARCH_URL.format(name=quote(name))).text, name)
                if gid is None:
                    log.warning("違規公告 %s 的團體「%s」在團體查詢找不到，略過", vid, name)
                    groups[name] = None
                else:
                    group_url = mohw.GROUP_URL.format(gid=gid)
                    groups[name] = mohw.parse_group(client.get(group_url).text, group_url, since_roc=since_roc)
                    yield from groups[name]
            group_items = groups[name]
            org = next((i for i in group_items or [] if i.kind == "org"), None)
            if org is None:
                continue
            yield Item(
                kind="penalty",
                ubn=org.ubn,
                data={k: data[k] for k in ("decided_on", "authority", "document_no", "content", "fine_text", "reason")},
                source_url=url,
                external_id=vid,
            )
            if limit and len(seen) >= limit:
                return
        offset += len(ids)
