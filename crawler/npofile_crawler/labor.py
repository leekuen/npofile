"""各縣市「違反勞動基準法事業單位及事業主公布總表」（LK-29）。

勞基法第 80-1 條：違反者由主管機關公布事業單位名稱、負責人姓名、處分日期、違反條文、罰鍰。
各縣市在政府資料開放平臺各上架一份，欄位名稱不太一樣；每個縣市一個 `LaborSpec`，要加縣市多一行設定。

只收非營利組織的處分：名稱含財團法人／社團法人／基金會／協會／學會，或名稱跟站上組織對得上（照 LK-19 的比對規則）。
對得上的帶統編；名稱像非營利組織但對不上的，統編留空送進審核清單，讓管理員指定組織或退回。
**負責人姓名不讀、不存。**
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from .grants import DATASET_API, DATASET_PAGE, OrgMatcher, csv_table, normalize
from .http import PoliteClient
from .items import Item, money, roc_date

NPO_NAME_RE = re.compile(r"財團法人|社團法人|基金會|協會|學會")

# 表頭（去空白、去括號後）→ 欄位代號。負責人姓名刻意不列，讀不到就不會存到
DEFAULT_HEADERS = {
    "公告日期": "announced",
    "處分日期": "decided",
    "處分字號": "document_no",
    "事業單位或事業主之名稱": "name",
    "事業單位名稱": "name",
    "違反勞動基準法條款": "articles",
    "違反法規條款": "articles",
    "違反法規內容": "violation",
    "罰鍰金額": "fine",
    "備註": "note",
}


@dataclass(frozen=True)
class LaborSpec:
    key: str        # 來源代號（crawl 指令用）
    dataset: int    # data.gov.tw 資料集編號
    county: str
    authority: str  # 處分機關
    headers: dict = field(default_factory=lambda: dict(DEFAULT_HEADERS))

    @property
    def source_name(self) -> str:
        return f"{self.authority} 違反勞動基準法事業單位公布總表"


TAIPEI = LaborSpec("tpe_labor", 121435, "臺北市", "臺北市政府勞動局")
SPECS = (TAIPEI,)


def _header(text: str) -> str:
    return re.sub(r"[\s()（）]", "", text or "")


def _split(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[;；\n]", text or "") if p.strip()]


def rows_from_table(table: Iterable[list[str]], spec: LaborSpec) -> Iterator[dict]:
    index: dict[str, int] | None = None
    for cells in table:
        if index is None:
            found = {spec.headers[_header(c)]: i for i, c in enumerate(cells) if _header(c) in spec.headers}
            if {"name", "document_no"} <= set(found):
                index = found
            continue

        def get(key: str) -> str:
            i = index.get(key)
            return (cells[i] or "").strip() if i is not None and i < len(cells) else ""

        name, doc = " ".join(get("name").split()), get("document_no")
        if not name or not doc:
            continue
        yield {
            "name": name,
            "document_no": doc,
            "announced_on": roc_date(get("announced")),
            "decided_on": roc_date(get("decided")),
            "articles": _split(get("articles")),
            "violations": _split(get("violation")),
            "fine": money(get("fine")),
            "note": get("note"),
        }


def penalty_id(spec: LaborSpec, row: dict) -> str:
    """同一筆＝處分機關＋處分字號；臺北市有一個字號同時列了兩家，所以再加上名稱。"""
    key = "|".join([spec.authority, row["document_no"], normalize(row["name"])])
    return f"{spec.key}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:20]}"


def to_item(spec: LaborSpec, row: dict, ubn: str) -> Item:
    content = "；".join(x for x in ("、".join(row["articles"]), "、".join(row["violations"])) if x)
    return Item(
        kind="penalty",
        ubn=ubn,
        external_id=penalty_id(spec, row),
        source_url=DATASET_PAGE.format(id=spec.dataset),
        data={
            "category": "labor",
            "org_name": row["name"],
            "county": spec.county,
            "authority": spec.authority,
            "decided_on": row["decided_on"],
            "announced_on": row["announced_on"],
            "document_no": row["document_no"],
            "content": content or "違反勞動基準法",
            "fine_text": f"罰鍰新臺幣 {row['fine']:,} 元" if row["fine"] else "",
            "reason": row["note"],
        },
    )


def to_items(spec: LaborSpec, rows: Iterable[dict], matcher: OrgMatcher) -> Iterator[Item]:
    for row in rows:
        hit = matcher.match(row["name"])
        if hit is None and not NPO_NAME_RE.search(row["name"]):
            continue  # 一般公司行號
        yield to_item(spec, row, hit[0] if hit else "")


def fetch(client: PoliteClient, limit: int | None = None, orgs: Iterable[tuple[str, str]] = (),
          spec: LaborSpec = TAIPEI) -> Iterator[Item]:
    """資料集裡的 CSV（每月更新的整份總表）→ 非營利組織的處分。limit 算的是 Item 數。"""
    matcher = OrgMatcher(orgs)
    meta = client.get(DATASET_API.format(id=spec.dataset)).json()["result"]
    count = 0
    for d in meta.get("distribution", []):
        url = d.get("resourceDownloadUrl") or ""
        if (d.get("resourceFormat") or "").upper() != "CSV" or not url:
            continue
        for item in to_items(spec, rows_from_table(csv_table(client.get(url).content), spec), matcher):
            if limit is not None and count >= limit:
                return
            count += 1
            yield item


def fetcher(spec: LaborSpec):
    def run(client: PoliteClient, limit: int | None = None, orgs: Iterable[tuple[str, str]] = ()) -> Iterator[Item]:
        return fetch(client, limit, orgs, spec)

    return run
