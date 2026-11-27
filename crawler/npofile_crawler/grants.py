"""政府對民間團體及個人補(捐)助（LK-19 衛福部主管、LK-24 勞動部就業安定基金）。

依《中央政府各機關對民間團體及個人補(捐)助預算執行應注意事項》第 7 點，各機關每季公開核定的補(捐)助案件。
衛福部（含社會及家庭署、健保署、疾管署等所屬）的彙總表放在政府資料開放平臺 dataset 44952，
每年度一份「截至第 N 季止」的累計表：同一年取季數最大的那份就是那年最新、最完整的。

各機關照同一套規定公開，欄位大致相同（括號半形全形、有沒有「項次」「補(捐)助機關」欄、日期寫法各家不同）；
每個資料集一個 `DatasetSpec`，要加新的部會多一行設定。

表上的受補助對象只有名稱、沒有統編；名稱對組織由呼叫端給的組織名冊（`orgs`）比對，對不到的不回傳
（多半是醫院診所、社區發展協會、公會、個人，不在收錄的非營利組織裡）。
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from xml.etree.ElementTree import iterparse

from .donors import _ROW, _cells
from .http import PoliteClient
from .items import Item, money, roc_date

DATASET_API = "https://data.gov.tw/api/v2/rest/dataset/{id}"
DATASET_PAGE = "https://data.gov.tw/dataset/{id}"


@dataclass(frozen=True)
class DatasetSpec:
    id: int
    name: str                           # 存進資料的來源名稱
    title_re: re.Pattern | None = None  # 資料集裡只拿標題符合的檔（None＝全部）
    agency: str = ""                    # 表上沒有「補(捐)助機關」欄時用這個


# 衛福部主管：同一個資料集還有「補(捐)助情形季報表」「補助地方政府情形表」，只拿逐筆列出受補助對象的彙總表；
# 標題寫法每年不太一樣：「對民間團體及個人補(捐)助經費彙總表」「公務團體個人補(捐)助彙總表」
TITLE_RE = re.compile(r"團體及?個人補\(捐\)助(?:經費)?彙總表")
MOHW = DatasetSpec(44952, "衛生福利部 對民間團體及個人補(捐)助經費彙總表", TITLE_RE)
# 勞動部就業安定基金（多元就業開發方案、職業訓練、身障就業等）：資料集裡每季一份，就是要的那種表
ESF = DatasetSpec(128781, "勞動部 就業安定基金對民間團體及個人之補(捐)助情形季報表", None, "勞動部")

DATASET_ID = MOHW.id
SOURCE_NAME = MOHW.name
YEAR_RE = re.compile(r"(\d{3})(?=年|第)")
QUARTER_RE = re.compile(r"第\s*(\d)\s*季")
ROC_TEXT_DATE_RE = re.compile(r"(\d{2,3})年(\d{1,2})月(\d{1,2})日")

# 表頭比對前拿掉所有括號（半形全形都有人用，也有人省略「(含累積金額)」的括號）
HEADERS = {
    "項次": "seq",
    "補捐助機關": "agency",
    "受補捐助對象所歸屬之直轄市或縣市": "county",
    "受補捐助對象": "recipient",
    "補捐助事項或用途": "purpose",
    "核准日期": "approved",
    "補捐助金額含累積金額": "amount",
}

PAREN_TAIL_RE = re.compile(r"\([^()]*\)$")
ATTACHED_RE = re.compile(r"^(.+?(?:基金會|協會|法人|教會|醫院|學會|總會|聯合會|促進會|服務會|慈善會))(附設|附屬)(.+)$")


@dataclass(frozen=True)
class GrantFile:
    year: int      # 民國年度
    quarter: int   # 截至第幾季
    fmt: str       # CSV｜ODS
    url: str
    dataset: int = DATASET_ID


def pick_files(distributions: Iterable[dict], since_roc: int | None = None, spec: DatasetSpec = MOHW) -> list[GrantFile]:
    """資料集的檔案清單 → 每年度季數最大的那份累計表（新年度在前）。"""
    best: dict[int, GrantFile] = {}
    for d in distributions:
        title = d.get("resourceDescription") or ""
        fmt = (d.get("resourceFormat") or "").upper()
        url = d.get("resourceDownloadUrl") or ""
        y = YEAR_RE.search(title)
        if spec.title_re is not None and not spec.title_re.search(title):
            continue
        if not (y and url and fmt in ("CSV", "ODS")):
            continue
        q = QUARTER_RE.search(title)
        f = GrantFile(int(y.group(1)), int(q.group(1)) if q else 4, fmt, url, spec.id)
        if since_roc is not None and f.year < since_roc:
            continue
        # 同一年同一季兩種格式都有時用 CSV（解析快）
        cur = best.get(f.year)
        if cur is None or (f.quarter, f.fmt == "CSV") > (cur.quarter, cur.fmt == "CSV"):
            best[f.year] = f
    return [best[y] for y in sorted(best, reverse=True)]


def _clean(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _header(text: str) -> str:
    return re.sub(r"[()（）]", "", _clean(text))


def _date(text: str):
    """「1140528」「114/05/28」「114年05月28日」都認。"""
    m = ROC_TEXT_DATE_RE.fullmatch(text)
    if m:
        return roc_date(f"{m.group(1)}/{m.group(2)}/{m.group(3)}")
    return roc_date(text)


def rows_from_table(table: Iterable[list[str]]) -> Iterator[dict]:
    """表格的列 → 每筆補助（表頭依欄名找；總計、合計、註解列跳過）。"""
    index: dict[str, int] | None = None
    for cells in table:
        if index is None:
            found = {HEADERS[_header(c)]: i for i, c in enumerate(cells) if _header(c) in HEADERS}
            if {"recipient", "amount"} <= set(found):
                index = found
            continue
        if not cells:
            continue
        # 有「項次」欄的表：項次不是數字的是總計、合計、註解列
        seq = index.get("seq")
        if seq is not None and not (cells[seq] if seq < len(cells) else "").strip().isdigit():
            continue

        def get(key: str) -> str:
            i = index.get(key)
            return (cells[i] or "").strip() if i is not None and i < len(cells) else ""

        recipient = get("recipient")
        amount = money(get("amount"))
        if not recipient or amount is None:
            continue
        dates = [d for d in (_date(x) for x in re.split(r"[\s、,]+", get("approved")) if x) if d]
        yield {
            "agency": get("agency"),
            "county": get("county"),
            "recipient": " ".join(recipient.split()),
            "purpose": " ".join(get("purpose").split()),
            "approved_on": min(dates) if dates else None,
            "approved_dates": [d.isoformat() for d in sorted(dates)],
            "amount": amount,
        }


def csv_table(data: bytes) -> Iterator[list[str]]:
    # 大多是 UTF-8，勞動部有幾季是 Big5
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp950", errors="replace")
    yield from csv.reader(io.StringIO(text))


def ods_table(data: bytes) -> Iterator[list[str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf, zf.open("content.xml") as fh:
        for _event, elem in iterparse(fh, events=("end",)):
            if elem.tag != _ROW:
                continue
            cells = _cells(elem)
            elem.clear()
            yield cells


def normalize(name: str) -> str:
    return _clean(name).replace("臺", "台").replace("（", "(").replace("）", ")")


class OrgMatcher:
    """名稱 → 統編。只認「正規化後完全相同、而且只有一個組織叫這個名字」；
    「X附設Y」「X(台中分事務所)」歸給上層的 X（同樣要完全相同且唯一）。不做模糊比對。"""

    def __init__(self, orgs: Iterable[tuple[str, str]]):
        by_name: dict[str, set[str]] = defaultdict(set)
        for ubn, name in orgs:
            if ubn and name:
                by_name[normalize(name)].add(ubn)
        self._by_name = by_name

    def _unique(self, name: str) -> str | None:
        ubns = self._by_name.get(name)
        return next(iter(ubns)) if ubns and len(ubns) == 1 else None

    def match(self, recipient: str) -> tuple[str, str] | None:
        """回傳（統編, 附設單位名稱；直接對到時是空字串）；對不到回 None。"""
        name = normalize(recipient)
        if ubn := self._unique(name):
            return ubn, ""
        trimmed = PAREN_TAIL_RE.sub("", name)
        if trimmed != name and (ubn := self._unique(trimmed)):
            return ubn, ""
        m = ATTACHED_RE.match(trimmed)
        if m and (ubn := self._unique(m.group(1))):
            # 正規化只換字不改長度：附設單位名稱從原文切，保留「臺」與全形括號
            return ubn, _clean(recipient)[m.start(3):m.end(3)]
        return None


def grant_id(year: int, row: dict, seq: int = 1) -> str:
    """同一案件跨季累計金額會變，編號不能含金額：年度＋機關＋對象＋事項＋最早核准日；
    同一份表裡這幾項全同的（例：分兩次核定、分列兩行）加流水號，不互相蓋掉。"""
    key = "|".join([str(year), row["agency"], normalize(row["recipient"]), row["purpose"],
                    row["approved_on"].isoformat() if row["approved_on"] else ""])
    suffix = f"-{seq}" if seq > 1 else ""
    return f"{year}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}{suffix}"


def to_items(f: GrantFile, rows: Iterable[dict], matcher: OrgMatcher, agency: str = "") -> Iterator[Item]:
    seen: dict[str, int] = defaultdict(int)
    for row in rows:
        if not row["agency"] and agency:
            row = {**row, "agency": agency}
        hit = matcher.match(row["recipient"])
        if hit is None:
            continue
        ubn, facility = hit
        base = grant_id(f.year, row)
        seen[base] += 1
        yield Item(
            kind="grant",
            ubn=ubn,
            external_id=grant_id(f.year, row, seen[base]),
            source_url=DATASET_PAGE.format(id=f.dataset),
            data={**row, "year": f.year, "quarter": f.quarter, "facility": facility},
        )


def fetch(client: PoliteClient, limit: int | None = None, since_roc: int | None = None,
          orgs: Iterable[tuple[str, str]] = (), spec: DatasetSpec = MOHW) -> Iterator[Item]:
    """近 5 年每年最新一份累計表，對到組織的補助一筆一個 Item。limit 算的是 Item 數。"""
    matcher = OrgMatcher(orgs)
    meta = client.get(DATASET_API.format(id=spec.id)).json()["result"]
    count = 0
    for f in pick_files(meta.get("distribution", []), since_roc, spec):
        data = client.get(f.url).content
        table = csv_table(data) if f.fmt == "CSV" else ods_table(data)
        for item in to_items(f, rows_from_table(table), matcher, spec.agency):
            if limit is not None and count >= limit:
                return
            count += 1
            yield item


def fetch_mohw(client: PoliteClient, limit: int | None = None, since_roc: int | None = None,
               orgs: Iterable[tuple[str, str]] = ()) -> Iterator[Item]:
    return fetch(client, limit, since_roc, orgs, MOHW)


def fetch_esf(client: PoliteClient, limit: int | None = None, since_roc: int | None = None,
              orgs: Iterable[tuple[str, str]] = ()) -> Iterator[Item]:
    return fetch(client, limit, since_roc, orgs, ESF)
