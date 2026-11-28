"""工程會「拒絕往來廠商」公告（LK-41，data.gov.tw 5988）：政府採購法第 101 條停權的廠商。

整份名單一個 JSON（約 2.2 MB、一千多筆），只放公告中的；到期後就從名單消失，我們照 LK-07 永久保留、不跟著刪。
每筆有廠商統一編號（`Corporation_Number`），直接對組織統編，**只收站上已有的組織**，不用名稱比對、不進審核清單。

`Corporation_Number` 有時是數字（前導 0 會掉，要補滿 8 碼）、有時是字串；個人廠商是遮罩的身分證號，整筆跳過。
負責人（`Supplier_Principal`）、身分證（`Supplier_Principal_ID`）、聯絡人與電話、地址**不讀、不存**。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator
from datetime import date

from .http import PoliteClient
from .items import Item, roc_date as _roc_date

API = "https://web.pcc.gov.tw/vms/rvlm/rvlmPublicSearch/queryRVFile/json"
DATASET_PAGE = "https://data.gov.tw/dataset/5988"
SOURCE_NAME = "行政院公共工程委員會 拒絕往來廠商公告"
GPA_LAW = "政府採購法第101條第1項"

UBN_RE = re.compile(r"^\d{8}$")
CLAUSE_RE = re.compile(r"^\s*(\d+)\s*(.*)$")
# 「沒有異議／申訴」的寫法：不寫進理由
EMPTY_TEXT = {"", "無", "無。", "-", "－"}


def _text(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def ubn(value) -> str:
    """統編：數字補滿 8 碼；不是 8 碼數字（個人的遮罩身分證、空白）回空字串。"""
    if isinstance(value, int) and not isinstance(value, bool):
        text = f"{value:08d}" if 0 < value < 10**8 else ""
    else:
        text = _text(value)
        if text.isdigit() and len(text) < 8:
            text = text.zfill(8)
    return text if UBN_RE.match(text) else ""


def roc_date(text) -> date | None:
    """民國日期加時間「1150409 00:00」→ 2026-04-09（只取日期）。"""
    return _roc_date(_text(text).split(" ")[0])


def roc_display(d: date | None) -> str:
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}" if d else ""


def clauses(text) -> list[tuple[str, str]]:
    """「1 容許他人借用…;2 借用或冒用…」→ [("1", "容許他人借用…"), ("2", "借用或冒用…")]，同一款重複的只留一次。"""
    out: list[tuple[str, str]] = []
    for part in _text(text).split(";"):
        m = CLAUSE_RE.match(part)
        if m and (m.group(1), m.group(2)) not in out:
            out.append((m.group(1), m.group(2).strip()))
    return out


def penalty_id(rec: dict) -> str:
    """同一筆＝統編＋案號＋生效日＋案名（同一家同一天、案號都寫「無」的不同案件要分得開）。"""
    key = "|".join((ubn(rec.get("Corporation_Number")), _text(rec.get("Case_no")), _text(rec.get("Effective_Date")),
                    _text(rec.get("Case_Name"))))
    return f"pcc-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:20]}"


def to_item(rec: dict) -> Item | None:
    number = ubn(rec.get("Corporation_Number"))
    effective = roc_date(rec.get("Effective_Date"))
    if not number or effective is None:
        return None
    expire = roc_date(rec.get("Expire_Date"))
    duration = _text(rec.get("Effective_Duration"))
    period = "～".join(x for x in (roc_display(effective), roc_display(expire)) if x)
    head = "停權" + (f" {duration}" if duration else "") + (f"（{period}）" if period else "")

    items = clauses(rec.get("GPA101_Caluse"))
    other_law = _text(rec.get("Suitable_Law"))
    if items:
        law = GPA_LAW + "、".join(f"第{n}款" for n, _ in items)
        basis = "政府採購法第 101 條第 1 項" + "；".join(f"第 {n} 款 {desc}".rstrip() for n, desc in items)
    elif other_law:
        law, basis = other_law.replace(" ", ""), f"依{other_law}"
    else:
        law, basis = GPA_LAW, "政府採購法第 101 條第 1 項"

    case_no = _text(rec.get("Case_no"))
    reasons = [f"採購案：{name}" if (name := _text(rec.get("Case_Name"))) else ""]
    for label, key in (("犯罪情形", "Crime_Info"), ("判決字號", "Judgment_Doc_No"), ("異議／申訴結果", "Appeal_Result")):
        value = _text(rec.get(key))
        if value not in EMPTY_TEXT:
            reasons.append(f"{label}：{value}")
    return Item(
        kind="penalty",
        ubn=number,
        external_id=penalty_id(rec),
        source_url=DATASET_PAGE,
        data={
            "category": "procurement",
            "org_name": _text(rec.get("Corporation_Name")),
            "authority": _text(rec.get("Announce_Agency_Name")),
            "decided_on": effective,
            "expires_on": expire,
            "document_no": "" if case_no in EMPTY_TEXT else case_no,
            "law": law,
            "content": f"{head}：{basis}",
            "reason": "\n".join(r for r in reasons if r),
        },
    )


def records(payload: dict) -> list[dict]:
    try:
        rows = payload["Rvlmd_List"]["Rvlmd"]
    except (KeyError, TypeError):
        raise RuntimeError(f"工程會拒絕往來廠商 JSON 格式不對：{str(payload)[:100]}") from None
    if isinstance(rows, dict):  # 只有一筆時可能不是陣列
        rows = [rows]
    if not isinstance(rows, list):
        raise RuntimeError("工程會拒絕往來廠商 JSON 的 Rvlmd 不是清單")
    return rows


def fetch(client: PoliteClient, limit: int | None = None, orgs: Iterable[tuple[str, str]] = (),
          listed: list[int] | None = None) -> Iterator[Item]:
    """整份名單讀一次，只產出統編在 orgs 名冊裡的。limit 算的是 Item 數；listed[0] 記讀到幾筆（給 crawl 判斷來源是不是改版）。"""
    known = {u for u, *_ in orgs}
    rows = records(client.get(API).json())
    if listed is not None:
        listed[0] += len(rows)
    count = 0
    for rec in rows:
        if ubn(rec.get("Corporation_Number")) not in known:
            continue
        item = to_item(rec)
        if item is None:
            continue
        if limit is not None and count >= limit:
            return
        count += 1
        yield item
