"""主管機關名冊與電子發票捐贈碼（LK-32）。兩份都是政府資料開放平臺上整份下載的 CSV，每月檢查一次。

- 教育部主管教育財團法人基本資料（dataset 117679，ws.moe.edu.tw，cp950）：一家一列、沒有統編，
  名稱對組織照補助的規則（grants.OrgMatcher：正規化後完全相同且唯一）。對不上的照樣回傳（統編留空），
  後端記下不顯示，管理員可在後台手動指定組織。
- 受捐贈機關或團體捐贈碼清單（dataset 31868，dataset.einvoice.nat.gov.tw，UTF-8 BOM）：有統編，直接對。

教育部名冊上的董事長、執行長、聯絡人姓名／職稱／電話／電子郵件一律不讀進來（票：不存個人姓名與聯絡方式）。
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Iterable, Iterator
from datetime import date, datetime

from .grants import DATASET_API, DATASET_PAGE, OrgMatcher, normalize
from .http import PoliteClient
from .items import Item, money

MOE_DATASET = 117679
MOE_NAME = "教育部主管教育財團法人基本資料"
MOE_AUTHORITY = "教育部"
EINVOICE_DATASET = 31868
EINVOICE_NAME = "財政部電子發票受捐贈機關或團體捐贈碼清單"

# 只讀這些欄；名冊上其他欄（董事長、執行長、聯絡人、地址、成立背景…）不讀
MOE_HEADERS = {
    "基金會名稱": "name",
    "設立許可文號": "permit_no",
    "西元年": "y",
    "月份": "m",
    "日": "d",
    "許可設立財產總額(元)": "permitted_assets",
    "最新法人登記證書之財產總額/基金(元)": "registered_assets",
    "成立宗旨": "purpose",
    "主要業務": "main_business",
    "服務對象": "service_targets",
    "主要業務類別": "business_category",
    "基金會狀態": "status",
}
EINVOICE_HEADERS = {
    "受捐贈機關或團體名稱": "name",
    "捐贈碼": "code",
    "受捐贈機關或團體簡稱": "short_name",
    "受捐贈機關或團體統編": "ubn",
    "縣市": "county",
}


def _header(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lstrip("﻿")).replace("（", "(").replace("）", ")")


def _rows(text: str, headers: dict[str, str]) -> Iterator[dict[str, str]]:
    index: dict[str, int] | None = None
    for cells in csv.reader(io.StringIO(text)):
        if index is None:
            found = {headers[_header(c)]: i for i, c in enumerate(cells) if _header(c) in headers}
            if "name" in found:
                index = found
            continue
        if not any(c.strip() for c in cells):
            continue
        yield {k: (cells[i].strip() if i < len(cells) else "") for k, i in index.items()}


def decode_moe(data: bytes) -> str:
    """教育部的檔是 Big5（cp950）；之後若改成 UTF-8 也認。"""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp950", errors="replace")


def _founded(row: dict) -> date | None:
    try:
        return date(int(row.get("y", "")), int(row.get("m", "")), int(row.get("d", "")))
    except ValueError:
        return None


def parse_moe(text: str) -> Iterator[dict]:
    for row in _rows(text, MOE_HEADERS):
        name = " ".join(row["name"].split())
        if not name:
            continue
        yield {
            "authority": MOE_AUTHORITY,
            "name": name,
            "permit_no": row.get("permit_no", ""),
            "founded_on": _founded(row),
            "permitted_assets": money(row.get("permitted_assets", "")),
            "registered_assets": money(row.get("registered_assets", "")),
            "purpose": row.get("purpose", ""),
            "main_business": row.get("main_business", ""),
            "service_targets": row.get("service_targets", ""),
            "business_category": row.get("business_category", ""),
            "status": row.get("status", ""),
        }


def registry_id(authority: str, name: str) -> str:
    """名冊上同一家用名稱認（教育部名冊的設立許可文號有空白、重複，不能當編號）。"""
    key = f"{authority}|{normalize(name)}"
    return "reg-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def moe_items(rows: Iterable[dict], matcher: OrgMatcher, data_date: date | None) -> Iterator[Item]:
    for row in rows:
        hit = matcher.match(row["name"])
        # 「某某附設某某」不是名冊上的那一家：只認名稱直接對到的
        ubn = hit[0] if hit and not hit[1] else ""
        yield Item(
            kind="registry",
            ubn=ubn,
            external_id=registry_id(row["authority"], row["name"]),
            source_url=DATASET_PAGE.format(id=MOE_DATASET),
            data={**row, "data_date": data_date},
        )


def parse_einvoice(text: str) -> Iterator[Item]:
    for row in _rows(text.lstrip("﻿"), EINVOICE_HEADERS):
        code = row.get("code", "").strip()
        ubn = re.sub(r"\D", "", row.get("ubn", ""))
        if not code:
            continue
        if ubn and len(ubn) < 8:
            ubn = ubn.zfill(8)
        yield Item(
            kind="einvoice",
            ubn=ubn if len(ubn) == 8 else "",
            external_id=code,
            source_url=DATASET_PAGE.format(id=EINVOICE_DATASET),
            data={
                "code": code,
                "name": " ".join(row["name"].split()),
                "short_name": row.get("short_name", "").strip(),
                "county": row.get("county", "").strip(),
            },
        )


def _meta(client: PoliteClient, dataset: int) -> dict:
    return client.get(DATASET_API.format(id=dataset)).json()["result"]


def _csv_url(meta: dict) -> str:
    for d in meta.get("distribution", []):
        if (d.get("resourceFormat") or "").upper() == "CSV" and d.get("resourceDownloadUrl"):
            return d["resourceDownloadUrl"]
    raise ValueError("資料集裡找不到 CSV 檔")


def meta_date(meta: dict) -> date | None:
    try:
        return datetime.strptime((meta.get("modifiedDate") or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def fetch_moe(client: PoliteClient, limit: int | None = None, orgs: Iterable[tuple[str, str]] = ()) -> Iterator[Item]:
    meta = _meta(client, MOE_DATASET)
    text = decode_moe(client.get(_csv_url(meta)).content)
    for i, item in enumerate(moe_items(parse_moe(text), OrgMatcher(orgs), meta_date(meta))):
        if limit is not None and i >= limit:
            return
        yield item


def fetch_einvoice(client: PoliteClient, limit: int | None = None) -> Iterator[Item]:
    meta = _meta(client, EINVOICE_DATASET)
    text = client.get(_csv_url(meta)).content.decode("utf-8-sig", errors="replace")
    for i, item in enumerate(parse_einvoice(text)):
        if limit is not None and i >= limit:
            return
        yield item
