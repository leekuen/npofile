"""衛福部社會及家庭署「社會福利民間資源友善查詢網」：全國性社會福利財團法人的年度決算（LK-25）。

財團法人法第 25 條：財團法人每年結束後五個月內把前一年度工作報告與財務報表送主管機關備查，
備查後一個月內主動公開。全國性社福財團法人報衛福部，社家署在這個網站逐家、逐年公開。

網站前台是單頁程式，背後的公開 JSON：
- `POST /api/main/foundBasic/found/searchFront`：財團法人清單（分頁，一頁 12 筆跟網站一樣）
- `GET  /api/main/foundBasic/found/getDetail/{foundUUID}/{西元年}`：該年度的預算、決算資料
- `POST /api/main/foundSettlement/settlementReport/print/FF0100`：把決算資料印成「年度決算總表」PDF

決算總表是網站用財團法人填報的資料統一產生的，每家版面相同；從裡面的「收支餘絀表」讀
「捐贈收入」「收入合計」（當年度與前一年度兩欄，只取當年度那欄，前一年度看前一年自己的表）。
PDF 只有名稱、沒有統編；名稱對組織用呼叫端給的名冊，跟補助（grants）同一套比對。
"""

from __future__ import annotations

import io
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTChar, LTContainer
from pdfminer.pdfparser import PDFSyntaxError
from pdfminer.psparser import PSException

from .grants import OrgMatcher
from .http import PoliteClient
from .items import Item

BASE = "https://swft.sfaa.gov.tw"
API = BASE + "/api"
SITE_URL = BASE + "/fund/fh0300"
SOURCE_NAME = "衛生福利部社會及家庭署 社會福利民間資源友善查詢網"
PAGE_SIZE = 12

MONEY_RE = re.compile(r"^-?[\d,]+$")
YEAR_RE = re.compile(r"^(\d{2,3})年度$")


@dataclass(frozen=True)
class Foundation:
    uuid: str
    no: str      # 財團法人代碼，例 A0001
    name: str


def list_foundations(client: PoliteClient) -> Iterator[Foundation]:
    page, seen = 1, 0
    while True:
        body = {"serviceObject": [""], "serviceType": [""], "cities": [""], "name": "", "page": page, "pageSize": PAGE_SIZE}
        data = client.post(f"{API}/main/foundBasic/found/searchFront", json=body).json()
        rows = data.get("resultList") or []
        for r in rows:
            if r.get("uuid") and r.get("name"):
                yield Foundation(uuid=r["uuid"], no=r.get("no") or "", name=r["name"].strip())
        seen += len(rows)
        total = (data.get("pagination") or {}).get("total") or 0
        if not rows or seen >= total:
            return
        page += 1


def settlement_of(detail: dict) -> dict | None:
    """getDetail 的回應 → 決算填報那一筆（沒有就是那年還沒備查或沒公開）。"""
    rows = detail.get("fSRSettlementReportList") or []
    return rows[0] if rows and rows[0].get("uuid") else None


def print_settlement(client: PoliteClient, s: dict) -> bytes:
    body = {"settlementReportUUID": s["uuid"], "foundUUID": s["foundUUID"], "year": s["year"],
            "accountUUID": "", "fromPublic": True}
    return client.post(f"{API}/main/foundSettlement/settlementReport/print/FF0100", json=body).content


# ── PDF 解析 ───────────────────────────────────────────────────────────────


def _chars(obj) -> Iterator[LTChar]:
    for o in obj:
        if isinstance(o, LTChar):
            yield o
        elif isinstance(o, LTContainer):
            yield from _chars(o)


def _words(page) -> list[tuple[float, float, float, str]]:
    """一頁的字依「看起來的行」組成詞：(行座標, 起點, 終點, 文字)。

    報表頁是橫印（頁面轉 90°），PDF 座標裡同一行的字 x 相同、閱讀方向是 y 遞減；
    沒轉的頁同一行 y 相同、閱讀方向 x 遞增。字距超過字寬 1.2 倍就斷成另一個詞（欄位之間）。"""
    rot = getattr(page, "rotate", 0) % 360
    rows: dict[int, list[tuple[float, float, str]]] = defaultdict(list)
    for c in _chars(page):
        x, y = (c.x0 + c.x1) / 2, (c.y0 + c.y1) / 2
        if rot == 90:
            row, col, size = x, -y, c.y1 - c.y0
        elif rot == 270:
            row, col, size = -x, y, c.y1 - c.y0
        else:
            row, col, size = -y, x, c.x1 - c.x0
        rows[round(row / 2)].append((col, size, c.get_text()))
    out = []
    for r, cs in rows.items():
        cs.sort()
        cur, start, last, last_size = "", 0.0, 0.0, 0.0
        for col, size, t in cs:
            if t.isspace():
                if cur:
                    out.append((r * 2, start, last, cur))
                    cur = ""
                continue
            if cur and col - last > max(size, last_size) * 1.2:
                out.append((r * 2, start, last, cur))
                cur = ""
            if not cur:
                start = col
            cur += t
            last, last_size = col, size
        if cur:
            out.append((r * 2, start, last, cur))
    return out


def parse_settlement(pdf: bytes) -> dict[int, dict[str, int]]:
    """決算總表 PDF → {民國年度: {"donation": 捐贈收入, "income_total": 收入合計}}。

    只看本會的「收支餘絀表」（附屬作業組織另有一張，不算）；讀不到的項目就不放，不猜。
    檔案壞掉或不是 PDF 回空的（那一年就只記「有決算、讀不到數字」，不中斷整批）。"""
    try:
        return _parse_settlement(pdf)
    except (PDFSyntaxError, PSException, ValueError, KeyError):
        return {}


def _parse_settlement(pdf: bytes) -> dict[int, dict[str, int]]:
    for page in extract_pages(io.BytesIO(pdf)):
        ws = _words(page)
        texts = [w[3] for w in ws]
        # 附屬作業組織那張表的標題列是「某某基金會 附屬作業組織」（單獨一個詞）；本會的表只有「附屬作業組織收入」這種科目
        if "收支餘絀表" not in texts or "捐贈收入" not in texts or "附屬作業組織" in texts:
            continue
        mid = lambda w: (w[1] + w[2]) / 2  # noqa: E731
        years = [(int(m.group(1)), w) for w in ws if (m := YEAR_RE.match(w[3]))]
        amounts = [w for w in ws if w[3].startswith("金額")]
        if not years or not amounts:
            continue
        cols = {y: mid(min(amounts, key=lambda a: abs(mid(a) - mid(yw)))) for y, yw in years}
        result: dict[int, dict[str, int]] = {}
        for label, key in (("捐贈收入", "donation"), ("收入合計", "income_total")):
            lab = next((w for w in ws if w[3] == label), None)
            if lab is None:
                continue
            nums = [w for w in ws if MONEY_RE.match(w[3]) and abs(w[0] - lab[0]) <= 3]
            for y, x in cols.items():
                if not nums:
                    continue
                n = min(nums, key=lambda w: abs(mid(w) - x))
                if abs(mid(n) - x) < 140:
                    result.setdefault(y, {})[key] = int(n[3].replace(",", ""))
        return result
    return {}


# ── 抓取 ───────────────────────────────────────────────────────────────────


def report_id(f: Foundation, roc_year: int) -> str:
    return f"{f.no or f.uuid}-{roc_year}"


def fetch(client: PoliteClient, limit: int | None = None, since_roc: int | None = None,
          orgs: Iterable[tuple[str, str]] = (), have: Iterable[str] = ()) -> Iterator[Item]:
    """近 5 年（到去年）每家每年一份決算，對到組織的一筆一個 Item。

    have：已經收過的來源編號（例 A0001-114），不再抓——決算備查後不會再變，每天只補新公開的。
    limit 算的是下載的決算份數。名稱對不到組織的財團法人整家跳過（不下載它的決算）。"""
    matcher = OrgMatcher(orgs)
    done = set(have)
    count = 0
    for f in list_foundations(client):
        hit = matcher.match(f.name)
        if hit is None or hit[1]:  # 決算是整個法人的，對到「某某附設某某」這種的不算
            continue
        ubn = hit[0]
        years = client.get(f"{API}/main/foundBasic/found/getYearList/{f.uuid}/Y").json().get("yearList") or []
        for ad in sorted({int(y) for y in years if str(y).isdigit()}, reverse=True):
            roc = ad - 1911
            if since_roc is not None and roc < since_roc:
                continue
            if report_id(f, roc) in done:
                continue
            detail = client.get(f"{API}/main/foundBasic/found/getDetail/{f.uuid}/{ad}").json()
            s = settlement_of(detail)
            if s is None:  # 今年度只有預算、還沒有決算
                continue
            if limit is not None and count >= limit:
                return
            count += 1
            values = parse_settlement(print_settlement(client, s)).get(roc, {})
            yield Item(
                kind="financial",
                ubn=ubn,
                external_id=report_id(f, roc),
                source_url=SITE_URL,
                data={
                    "year": roc,
                    "donation": values.get("donation"),
                    "income_total": values.get("income_total"),
                    "statement": "決算總表",
                    "filer_name": f.name,
                    "filer_no": f.no,
                },
            )
