"""上市櫃公司企業 ESG 資訊揭露彙總資料（LK-39）。證交所、櫃買中心的 OpenAPI，不需金鑰，整份下載。

- 公司基本資料（上市 t187ap03_L、上櫃 mopsfin_t187ap03_O）：只讀公司代號、全名、簡稱、統編、網址。
  董事長、總經理、發言人、電話、電子郵件一律不讀（不存個人姓名與聯絡方式）。
- ESG 只讀四個主題：1 溫室氣體排放、2 能源管理、5 人力發展、8 氣候相關議題管理。
- 欄名有時夾空白（例「員工薪資平均數(仟元/人) 」），上市、上櫃的單位寫法也不同，所以欄名去空白後用開頭比對。
- 空白、N/A、- 一律當沒填。公司申報的文字照存，不改寫。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from .http import PoliteClient

SOURCE_NAME_LISTED = "臺灣證券交易所 上市公司企業 ESG 資訊揭露彙總資料"
SOURCE_NAME_OTC = "證券櫃檯買賣中心 上櫃公司企業 ESG 資訊揭露彙總資料"
TOPICS = (1, 2, 5, 8)


@dataclass(frozen=True)
class Market:
    key: str  # listed | otc
    label: str
    base: str
    company_endpoint: str
    topic_endpoint: str  # 帶 {n}
    source_name: str
    # 公司基本資料的欄名（上櫃是英文）
    code_field: str
    name_field: str
    short_field: str
    ubn_field: str
    web_field: str

    def url(self, endpoint: str) -> str:
        return self.base + endpoint


LISTED = Market(
    "listed", "上市", "https://openapi.twse.com.tw/v1/opendata/", "t187ap03_L", "t187ap46_L_{n}",
    SOURCE_NAME_LISTED, "公司代號", "公司名稱", "公司簡稱", "營利事業統一編號", "網址",
)
OTC = Market(
    "otc", "上櫃", "https://www.tpex.org.tw/openapi/v1/", "mopsfin_t187ap03_O", "t187ap46_O_{n}",
    SOURCE_NAME_OTC, "SecuritiesCompanyCode", "CompanyName", "CompanyAbbreviation", "UnifiedBusinessNo.", "WebAddress",
)
MARKETS = (LISTED, OTC)

EMPTY = {"", "N/A", "NA", "n/a", "-", "－", "—"}


CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(value) -> str:
    """去掉申報文字裡夾帶的控制字元（實測華碩有 0x1c），換行保留。"""
    text = CONTROL.sub("", str(value or "")).replace("\r\n", "\n").strip()
    return "" if text in EMPTY else text


def _norm_key(key: str) -> str:
    return re.sub(r"\s+", "", key or "")


def pick(row: dict, prefix: str) -> str:
    """欄名去空白後開頭相同就算（欄名很長、單位寫法上市上櫃不同）。"""
    want = _norm_key(prefix)
    for key, value in row.items():
        if _norm_key(key).startswith(want):
            return clean(value)
    return ""


def number(text: str) -> Decimal | None:
    text = clean(text).replace(",", "").rstrip("%").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def integer(text: str) -> int | None:
    n = number(text)
    return int(n) if n is not None else None


def roc_date(text: str) -> date | None:
    """出表日期「1151128」＝民國 115 年 11 月 28 日。"""
    m = re.fullmatch(r"(\d{2,3})(\d{2})(\d{2})", clean(text))
    if not m:
        return None
    try:
        return date(int(m[1]) + 1911, int(m[2]), int(m[3]))
    except ValueError:
        return None


def website(text: str) -> str:
    url = clean(text)
    if url and not re.match(r"https?://", url, re.I):
        url = "https://" + url
    return url


# 每個主題讀哪些欄：(存成的欄位, 欄名開頭, 轉換)
FIELDS: dict[int, tuple[tuple[str, str, Callable[[str], object]], ...]] = {
    1: (
        ("scope1", "範疇一排放量", number),
        ("scope1_verified", "範疇一取得驗證", clean),
        ("scope2", "範疇二排放量", number),
        ("scope2_verified", "範疇二取得驗證", clean),
        ("scope3", "範疇三排放量", number),
        ("scope3_verified", "範疇三取得驗證", clean),
    ),
    2: (("renewable_ratio", "使用率(再生能源/總能源)", number),),
    5: (
        ("female_manager_ratio", "管理職女性主管佔比", number),
        ("salary_median", "非擔任主管之全時員工薪資中位數", integer),
    ),
    8: (
        ("climate_governance", "董事會與管理階層對於氣候相關風險與機會之監督及治理", clean),
        ("climate_strategy", "辨識之氣候風險與機會如何影響企業之業務、策略及財務", clean),
        ("climate_actions", "極端氣候事件及轉型行動對財務之影響", clean),
        ("transition_plan", "若有因應管理氣候相關風險之轉型計畫", clean),
        ("climate_targets", "若有設定氣候相關目標", clean),
    ),
}


def parse_market(market: Market, companies: list[dict], topics: dict[int, list[dict]]) -> list[dict]:
    """一家公司一筆（同一個報告年度）。至少有一個主題有資料的公司才回傳。"""
    base = {}
    for row in companies:
        code = clean(row.get(market.code_field))
        if code:
            base[code] = row
    merged: dict[tuple[str, int], dict] = {}
    for n in TOPICS:
        for row in topics.get(n, []):
            code = clean(row.get("公司代號"))
            year = integer(row.get("報告年度", ""))
            if not code or year is None:
                continue
            rec = merged.get((code, year))
            if rec is None:
                info = base.get(code, {})
                rec = merged[(code, year)] = {
                    "market": market.key,
                    "code": code,
                    "name": clean(info.get(market.name_field)) or clean(row.get("公司名稱")),
                    "short_name": clean(info.get(market.short_field)) or clean(row.get("公司名稱")),
                    "ubn": re.sub(r"\D", "", clean(info.get(market.ubn_field)))[:8],
                    "website": website(info.get(market.web_field, "")),
                    "report_year": year,
                    "published_on": roc_date(row.get("出表日期", "")),
                    "source_name": market.source_name,
                    "source_url": market.url(market.topic_endpoint.format(n=8)),
                }
                for fields in FIELDS.values():
                    for field, _, conv in fields:
                        rec[field] = conv("")
            for field, prefix, conv in FIELDS[n]:
                rec[field] = conv(pick(row, prefix))
            published = roc_date(row.get("出表日期", ""))
            if published and (rec["published_on"] is None or published > rec["published_on"]):
                rec["published_on"] = published
    return [r for r in merged.values() if any(r[f] not in (None, "") for fs in FIELDS.values() for f, _, _ in fs)]


def fetch_market(client: PoliteClient, market: Market) -> list[dict]:
    companies = client.get(market.url(market.company_endpoint)).json()
    topics = {n: client.get(market.url(market.topic_endpoint.format(n=n))).json() for n in TOPICS}
    return parse_market(market, companies, topics)


def fetch(client: PoliteClient) -> Iterator[tuple[Market, list[dict] | Exception]]:
    """一個市場失敗不影響另一個：失敗的回傳例外，由呼叫端記下來。"""
    for market in MARKETS:
        try:
            yield market, fetch_market(client, market)
        except Exception as exc:  # noqa: BLE001 — 網路、JSON 格式錯都要記下來繼續
            yield market, exc
