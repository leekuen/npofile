"""環境部「列管事業污染源裁處資料」（LK-36，data.gov.tw 34101，API ems_p_46）。

各縣市環保局與環境部對列管事業的裁處，每天更新；每筆有事業的統一編號（`ban`），直接對組織統編，
**只收站上已有的組織**，不用名稱比對、不進審核清單。

API 要金鑰（免費，自己到環境部開放資料平台申請），由後端從環境變數 `MOENV_API_KEY` 給；
不用資料集頁面上公開的金鑰。

只讀需要的欄位：違規人名稱（`transgress_name`，可能是個人或工程名稱）、事業與違規地址**不讀、不存**。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator
from datetime import date

from .http import PoliteClient
from .items import Item

API = "https://data.moenv.gov.tw/api/v2/ems_p_46"
DATASET_PAGE = "https://data.gov.tw/dataset/34101"
SOURCE_NAME = "環境部 列管事業污染源裁處資料"
PAGE_SIZE = 1000  # API 一次最多 1000 筆

UBN_RE = re.compile(r"^\d{8}$")
# 裁處機關欄位只寫縣市（例「臺北市」），補成機關全名；其他寫法（例「桃環處」「環境部」）照原樣
SPECIAL_AUTHORITY = {"金門縣": "金門縣環境保護局", "連江縣": "連江縣環境資源局"}


def authority(county: str) -> str:
    county = (county or "").strip()
    if county in SPECIAL_AUTHORITY:
        return SPECIAL_AUTHORITY[county]
    if re.fullmatch(r"\S{2}[市縣]", county):
        return f"{county}政府環境保護局"
    return county or "環境部"


def _date(text: str) -> date | None:
    try:
        return date.fromisoformat((text or "").strip()[:10])
    except ValueError:
        return None


def _money(text: str) -> int:
    try:
        return int(float((text or "0").replace(",", "")))
    except ValueError:
        return 0


def penalty_id(rec: dict) -> str:
    """同一筆＝管制編號＋裁處機關＋裁處書字號。"""
    key = "|".join((rec.get(k) or "").strip() for k in ("ems_no", "county_name", "document_no"))
    return f"moenv-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:20]}"


def to_item(rec: dict) -> Item | None:
    ubn = (rec.get("ban") or "").strip()
    doc = (rec.get("document_no") or "").strip()
    if not UBN_RE.match(ubn) or not doc:
        return None
    law = " ".join((rec.get("transgress_law") or "").split())
    subject = " ".join((rec.get("subject") or "").split())
    fine = _money(rec.get("penalty_money"))
    reason = (rec.get("openinfor") or "").strip()
    results = [f"{label}：{v}" for label, key in (("訴願結果", "petition_results"), ("行政訴訟結果", "appeal_or_rescind"))
               if (v := (rec.get(key) or "").strip())]
    if results:
        reason = "\n".join(x for x in (reason, "；".join(results)) if x)
    return Item(
        kind="penalty",
        ubn=ubn,
        external_id=penalty_id(rec),
        source_url=DATASET_PAGE,
        data={
            "category": "environment",
            "org_name": (rec.get("fac_name") or "").strip(),
            "county": (rec.get("county_name") or "").strip(),
            "authority": authority(rec.get("county_name")),
            "decided_on": _date(rec.get("penalty_date")),
            "violated_on": _date(rec.get("transgress_date")),
            "document_no": doc,
            "law": law,
            "content": "；".join(x for x in (f"違反{law}" if law else "", subject) if x) or "違反環境保護法令",
            "fine_text": f"罰鍰新臺幣 {fine:,} 元" if fine else "",
            "reason": reason,
        },
    )


def _get_page(client: PoliteClient, api_key: str, offset: int, tries: int = 3) -> list:
    """一頁 1000 筆。違規事實全文偶爾帶控制字元（放寬解析）；回應偶爾斷在一半（重抓，最多 tries 次）。"""
    params = {"api_key": api_key, "format": "JSON", "limit": PAGE_SIZE, "offset": offset, "sort": "ImportDate desc"}
    for attempt in range(tries):
        resp = client.get(API, params=params)
        try:
            page = json.loads(resp.text, strict=False)
        except ValueError:
            if not resp.text.lstrip().startswith("[") or attempt == tries - 1:
                raise RuntimeError(f"環境部 API 第 {offset} 筆起的回應不是資料：{resp.text[:60]!r}…{resp.text[-60:]!r}") from None
            continue
        if not isinstance(page, list):
            raise RuntimeError(f"環境部 API 回應格式不對：{str(page)[:100]}")
        return page
    return []


def fetch(client: PoliteClient, limit: int | None = None, orgs: Iterable[tuple[str, str]] = (),
          moenv_api_key: str = "", since_date: date | None = None, listed: list[int] | None = None) -> Iterator[Item]:
    """依匯入時間新到舊翻頁；since_date 有給時，整頁的裁處日都早於它就停（第一次跑沒給＝全量回補）。
    只產出統編在 orgs 名冊裡的。limit 算的是 Item 數；listed[0] 記讀到幾筆（給 crawl 判斷來源是不是改版）。"""
    if not moenv_api_key:
        raise RuntimeError("沒有設定 MOENV_API_KEY（環境部開放資料 API 金鑰，到 data.moenv.gov.tw 免費申請）")
    ubns = {u for u, *_ in orgs}
    count, offset = 0, 0
    while True:
        page = _get_page(client, moenv_api_key, offset)
        if listed is not None:
            listed[0] += len(page)
        for rec in page:
            if (rec.get("ban") or "").strip() not in ubns:
                continue
            item = to_item(rec)
            if item is None:
                continue
            if limit is not None and count >= limit:
                return
            count += 1
            yield item
        if len(page) < PAGE_SIZE:
            return
        if since_date is not None:
            dates = [d for d in (_date(r.get("penalty_date")) for r in page) if d]
            if dates and max(dates) < since_date:
                return
        offset += PAGE_SIZE
