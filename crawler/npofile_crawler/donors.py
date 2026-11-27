"""捐贈人清冊：解析公益勸募系統的 ODS 檔、把捐款人名稱分成企業／團體／個人／匿名。

隱私：個人只保留「同一活動累計達門檻」者的姓名，其餘只回傳人數與金額，不往下游傳姓名。
"""

from __future__ import annotations

import re
import unicodedata
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from xml.etree.ElementTree import iterparse

from .items import money, roc_date

COMPANY, GROUP, INDIVIDUAL, ANONYMOUS = "company", "group", "individual", "anonymous"

# 匿名，以及金流平台／通路把很多筆小額捐款併成一筆的名稱（不是那家平台自己捐的）
ANON_RE = re.compile(
    r"不公開|匿名|有心人|善心人|無名氏|愛心人士|^MOMO$|LINE ?PAY|街口|超商|便利商店|門市捐款|發票捐贈", re.IGNORECASE
)
COMPANY_RE = re.compile(r"公司|企業社|商行|商號|工作室|銀行|實業|事務所|診所|藥局|有限|股份|保險|證券|行號")
GROUP_RE = re.compile(
    r"基金會|協會|學會|公會|扶輪社|獅子會|同濟會|青商會|教會|寺|宮|廟|禪|佛堂|功德會|學校|國小|國中|高中|高工|高商|大學|幼兒園|"
    r"社區發展|里辦公處|聯誼會|校友會|合作社|農會|漁會|醫院|小學|中學|實驗教育"
)
COMPANY_EN_RE = re.compile(
    r"\b(plc|inc|ltd|llc|corp|corporation|company|co\.|holdings|limited|gmbh|bank|bhd|pte)\b", re.IGNORECASE
)
GROUP_EN_RE = re.compile(
    r"\b(foundation|association|church|society|club|trust|funds?|ministry|ministries|temple|school|university|"
    r"college|rotary|lions|world vision)\b",
    re.IGNORECASE,
)
# 政府機關與宗教場所：名稱結尾判斷（「外交部」「台北真理堂」）
GROUP_SUFFIX_RE = re.compile(r"(部|署|局|政府|公所|議會|法院|委員會|辦公室|堂|宮|寺|廟|教會)$")
# 「王小明(同001772220)」「李素菁 (同 001179057)」：清冊的內部附註，分類前去掉
NOTE_RE = re.compile(r"[（(]\s*同\s*\d+\s*[)）]")
# 看不見的字元（零寬空白、方向控制、軟連字號…）：畫面上看不出來，卻會讓同一家變成兩家（LK-16）
INVISIBLE_RE = re.compile("[­᠎​-‏‪-‮⁠-⁯﻿]")
# 名稱後面附的統編：「米〇國際股份有限公司 統一編號：16230598」「青域設計有限公司 統編：54362423」
UBN_NOTE_RE = re.compile(r"\s*[(]?\s*(?:統一編號|統編)\s*[:]?\s*\d{8}\s*[)]?\s*$")
TRAILING_PUNCT_RE = re.compile(r"[\s。.,，、;；]+$")
SHARE_RE = re.compile(r"\(股\)(?:公司)?")

DEFAULT_INDIVIDUAL_THRESHOLD = 100_000


def normalize(name: str) -> str:
    """清冊上的寫法 → 顯示的名稱：去掉看不見的字元與附註、全形英數標點換成一般寫法、空白併成一個。"""
    name = unicodedata.normalize("NFKC", INVISIBLE_RE.sub("", name or ""))
    name = NOTE_RE.sub("", name)
    name = UBN_NOTE_RE.sub("", name)
    name = TRAILING_PUNCT_RE.sub("", " ".join(name.split()))
    return name


def identity_key(name: str) -> str:
    """判斷是不是同一位（只用來比對，不拿來顯示）：台當臺、不看空白、(股) 當股份有限公司、英文不分大小寫。"""
    key = normalize(name).replace("台", "臺").replace(" ", "")
    return SHARE_RE.sub("股份有限公司", key).casefold()


def classify(name: str) -> str:
    n = normalize(name)
    if not n or ANON_RE.search(n):
        return ANONYMOUS
    if COMPANY_RE.search(n) or COMPANY_EN_RE.search(n):
        return COMPANY
    if GROUP_RE.search(n) or GROUP_EN_RE.search(n) or GROUP_SUFFIX_RE.search(n):
        return GROUP
    # 其餘（個人姓名、英文名、夫妻並列、沒寫公司的店名）一律先當個人：隱私上比較保守
    return INDIVIDUAL


@dataclass
class DonorRow:
    receipt_no: str
    donated_on: str | None
    name: str
    amount: int
    purpose: str


_NS_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
_NS_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_ROW = f"{{{_NS_TABLE}}}table-row"
_CELL = f"{{{_NS_TABLE}}}table-cell"
_REPEAT = f"{{{_NS_TABLE}}}number-columns-repeated"
_P = f"{{{_NS_TEXT}}}p"

HEADERS = {
    "收據編號": "receipt_no",
    "捐贈日期": "date",
    "捐贈者名稱或姓名": "name",
    "捐贈金額": "amount",
    "捐贈用途": "purpose",
}


def _cells(row) -> list[str]:
    out: list[str] = []
    for cell in row.iter(_CELL):
        text = "\n".join("".join(p.itertext()) for p in cell.iter(_P)).strip()
        repeat = int(cell.get(_REPEAT, "1"))
        out.extend([text] * min(repeat, 50))  # 行尾常有上千個重複空格，只取前面
    return out


def parse_ods(data: bytes) -> Iterator[DonorRow]:
    """逐列串流解析，十幾萬列的清冊也不會一次載入整份 XML。"""
    with zipfile.ZipFile(BytesIO(data)) as zf, zf.open("content.xml") as fh:
        index: dict[str, int] | None = None
        for _event, elem in iterparse(fh, events=("end",)):
            if elem.tag != _ROW:
                continue
            cells = _cells(elem)
            elem.clear()
            if index is None:
                found = {HEADERS[c]: i for i, c in enumerate(cells) if c in HEADERS}
                if "name" in found and "amount" in found:
                    index = found
                continue
            def get(key: str) -> str:
                i = index.get(key)
                return cells[i] if i is not None and i < len(cells) else ""
            name = get("name")
            amount = money(get("amount"))
            if not name and amount is None:
                continue
            d = roc_date(get("date"))
            yield DonorRow(get("receipt_no"), d.isoformat() if d else None, name, amount or 0, get("purpose"))


def summarize(rows: Iterator[DonorRow], threshold: int = DEFAULT_INDIVIDUAL_THRESHOLD) -> dict:
    """把一份清冊整理成：要保留的逐筆（企業、團體、大額個人）＋摘要（小額個人、匿名只留數字）。"""
    kept: list[dict] = []
    individuals: dict[str, list[dict]] = defaultdict(list)  # 同一個人的不同寫法合起來算門檻（identity_key）
    summary = {
        "total_rows": 0,
        "total_amount": 0,
        "small_individual_count": 0,
        "small_individual_amount": 0,
        "anonymous_rows": 0,
        "anonymous_amount": 0,
        "threshold": threshold,
    }
    for r in rows:
        summary["total_rows"] += 1
        summary["total_amount"] += r.amount
        name = normalize(r.name)
        kind = classify(name)
        row = {"receipt_no": r.receipt_no, "donated_on": r.donated_on, "name": name, "kind": kind,
               "amount": r.amount, "purpose": r.purpose[:200]}
        if kind == ANONYMOUS:
            summary["anonymous_rows"] += 1
            summary["anonymous_amount"] += r.amount
        elif kind == INDIVIDUAL:
            individuals[identity_key(name)].append(row)
        else:
            kept.append(row)
    for name, rs in individuals.items():
        total = sum(x["amount"] for x in rs)
        if total >= threshold:
            kept.extend(rs)
        else:
            summary["small_individual_count"] += 1
            summary["small_individual_amount"] += total
    return {"summary": summary, "rows": kept}
