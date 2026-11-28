"""各縣市「違反勞動基準法事業單位及事業主公布總表」（LK-29）。

勞基法第 80-1 條：違反者由主管機關公布事業單位名稱、負責人姓名、處分日期、違反條文、罰鍰。
各縣市在政府資料開放平臺各上架一份，欄位名稱不太一樣；每個縣市一個 `LaborSpec`，要加縣市多一行設定。

只收非營利組織的處分：名稱含財團法人／社團法人／基金會／協會／學會，或名稱跟站上組織對得上（照 LK-19 的比對規則）。
對得上的帶統編；名稱像非營利組織但對不上的，統編留空送進審核清單，讓管理員指定組織或退回。
**負責人姓名不讀、不存。**
"""

from __future__ import annotations

import hashlib
import io
import re
import time
import zipfile
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


def to_items(spec: LaborSpec, rows: Iterable[dict], matcher: OrgMatcher, skip_docs: Iterable[str] = ()) -> Iterator[Item]:
    skip = {doc_key(d) for d in skip_docs}
    for row in rows:
        if doc_key(row["document_no"]) in skip:
            continue  # 勞動部全國系統（LK-37）已收過同一張處分
        hit = matcher.match(row["name"])
        if hit is None and not NPO_NAME_RE.search(row["name"]):
            continue  # 一般公司行號
        yield to_item(spec, row, hit[0] if hit else "")


def fetch(client: PoliteClient, limit: int | None = None, orgs: Iterable[tuple[str, str]] = (),
          spec: LaborSpec = TAIPEI, labor_docs: Iterable[str] = ()) -> Iterator[Item]:
    """資料集裡的 CSV（每月更新的整份總表）→ 非營利組織的處分。limit 算的是 Item 數。
    labor_docs：別的勞動來源（勞動部全國系統）已收過的處分字號，不收第二次。"""
    matcher = OrgMatcher(orgs)
    labor_docs = list(labor_docs)
    meta = client.get(DATASET_API.format(id=spec.dataset)).json()["result"]
    count = 0
    for d in meta.get("distribution", []):
        url = d.get("resourceDownloadUrl") or ""
        if (d.get("resourceFormat") or "").upper() != "CSV" or not url:
            continue
        for item in to_items(spec, rows_from_table(csv_table(client.get(url).content), spec), matcher, labor_docs):
            if limit is not None and count >= limit:
                return
            count += 1
            yield item


def fetcher(spec: LaborSpec):
    def run(client: PoliteClient, limit: int | None = None, orgs: Iterable[tuple[str, str]] = (),
            labor_docs: Iterable[str] = ()) -> Iterator[Item]:
        return fetch(client, limit, orgs, spec, labor_docs)

    return run


# ── 勞動部「違反勞動法令事業單位（雇主）查詢系統」（LK-37）──────────────────────
#
# 22 縣市＋勞動部、勞保局、職安署、科學園區的處分彙整在一起，涵蓋 10 部勞動法規。
# 查詢頁表單（先 GET 拿 cookie 與 _csrf_token）→ POST /Download/（downloadType=3＝CSV）回一個 zip，
# 裡面 5 份 CSV（A～E，各一組法規），每份第一行是標題「違反雇主清冊」、第二行是表頭。
# 下載檔是完整歷史（不只查詢頁說的近 3 年）；按名稱關鍵字查，站上不能不給條件整份下載。
# 2026-11-28 實測：本專案的 User-Agent、一般表單送出就拿得到，不用無頭瀏覽器。
#
# **「事業單位名稱(負責人)」的負責人要切掉不存**；自然人開的事業會寫成「王小明即財團法人…」，「即」前面也切掉。

MOL_KEY = "mol_labor"
MOL_SITE = "https://announcement.mol.gov.tw/"
MOL_DOWNLOAD = MOL_SITE + "Download/"
MOL_SOURCE_NAME = "勞動部違反勞動法令事業單位（雇主）查詢系統"
# 名稱查詢是「包含」：前五個照 LK-29 的非營利組織字樣，後面是名冊裡常見、前五個抓不到的
MOL_KEYWORDS = ("財團法人", "社團法人", "基金會", "協會", "學會", "促進會", "教會", "聯合會", "總會")

# 下載檔 A～E 各一組法規
MOL_LAW_GROUPS = {
    "A": "勞動基準法／最低工資法／性別平等工作法",
    "B": "職業安全衛生法",
    "C": "工會法／外送員權益保障及外送平臺管理法",
    "D": "就業服務法／中高齡者及高齡者就業促進法",
    "E": "勞工退休金條例／勞工職業災害保險及保護法",
}

MOL_HEADERS = {
    "縣市／單位別": "unit",
    "縣市/單位別": "unit",
    "公告日期": "announced",
    "處分日期": "decided",
    "處分字號": "document_no",
    # 名稱欄表頭是「事業單位名稱(負責人)\n自然人姓名」；_header 會去掉空白與括號
    "事業單位名稱負責人自然人姓名": "name",
    "事業單位名稱負責人": "name",
    "事業單位名稱": "name",
    "違反法規條款": "articles",
    "法條敘述": "violation",
    "罰鍰金額": "fine",
    "處分金額／滯納金": "fine",
    "處分金額/滯納金": "fine",
    "職業災害之罹災人數": "victims",
    "備註": "note",
    # 職災發生地點、日期不讀（地點有時是住址）
}

# 「縣市／單位別」→ 處分機關全名。六都寫到勞動局／勞工局（處分書就是它們發的）；
# 其他縣市的局處名稱各縣市不同、又常改組，寫到縣市政府為止，不猜局處名
MOL_AUTHORITIES = {
    "臺北市": "臺北市政府勞動局",
    "新北市": "新北市政府勞工局",
    "桃園市": "桃園市政府勞動局",
    "臺中市": "臺中市政府勞工局",
    "臺南市": "臺南市政府勞工局",
    "高雄市": "高雄市政府勞工局",
    "產業園區管理局": "經濟部產業園區管理局",
    "新竹科學園區": "國家科學及技術委員會新竹科學園區管理局",
    "中部科學園區": "國家科學及技術委員會中部科學園區管理局",
    "南部科學園區": "國家科學及技術委員會南部科學園區管理局",
    "勞動部勞工保險局": "勞動部勞工保險局",
    "勞動部勞動基金運用局": "勞動部勞動基金運用局",
    "職業安全衛生署": "勞動部職業安全衛生署",
    "勞動部": "勞動部",
}
_COUNTY_RE = re.compile(r"^[一-鿿]{2}[縣市]$")

_NPO_WORDS = r"(?:財團法人|社團法人|基金會|協會|學會|促進會|教會|聯合會|總會)"
# 括號後面接著 2～4 個字（中間可有間隔號）就結束：那是負責人姓名
_OWNER_AFTER_PAREN_RE = re.compile(r"[)）]\s*([一-鿿][一-鿿·．]{1,4})$")
# 括號後面接的是機構（例「(某某)附設幼兒園」「(某某)托嬰中心」）就不是姓名
_FACILITY_RE = re.compile(r"[園院所會班館部局處校站社室家坊屋司廠店場]|中心|附設|附屬|分院")
# 「王小明即財團法人…」：「即」前面是自然人姓名（最多 6 個字，後面接得上非營利組織字樣才切）
_OWNER_HEAD_RE = re.compile(r"^[^\s()（）]{1,6}?即(?=.*" + _NPO_WORDS + ")")
# 「某某教養院(承辦單位：財團法人…)」「某某幼兒園(委託財團法人…辦理)」：括號裡的才是經營的組織
_OPERATOR_RE = re.compile(
    r"[(（](?:承辦單位|受託單位|委託單位|經營單位)?[:：]?(?:委託|委由)?"
    r"([^()（）]*?(?:法人|基金會|協會|學會|教會|總會|聯合會|促進會))(?:辦理|經營|承辦)?[)）]"
)
LATE_FEE_RE = re.compile(r"滯納金")
COMPANY_RE = re.compile(r"公司|商行|工作室")


def mol_authority(unit: str) -> str:
    unit = (unit or "").strip().replace("台", "臺")
    if unit in MOL_AUTHORITIES:
        return MOL_AUTHORITIES[unit]
    if _COUNTY_RE.match(unit):
        return f"{unit}政府"
    return unit


def _strip_last_group(name: str) -> str:
    """去掉結尾那組括號（括號裡還有括號也整組去掉，例「(陳宜妙(解任))」）。"""
    depth = 0
    for i in range(len(name) - 1, -1, -1):
        ch = name[i]
        if ch in ")）":
            depth += 1
        elif ch in "(（":
            depth -= 1
            if depth == 0:
                return name[:i].rstrip()
    return name


def strip_owner(raw: str) -> str:
    """「事業單位名稱(負責人)」→ 事業單位名稱。負責人姓名一律不留，2026-11-28 全量實跑看到的寫法：
    ・結尾一組括號（含括號裡再有括號）：整組切掉；沒括號照原樣
    ・括號沒寫完「某某育幼院(釋某某」：從沒配對的左括號切到底
    ・姓名寫在經營組織括號後面「某某醫院(委託某某法人經營)王小明」「…辦理) 王小明」：切掉後面的姓名、留下括號
    ・自然人「王小明即財團法人…」：切掉「即」前面"""
    name = " ".join((raw or "").split())
    if (m := _OWNER_AFTER_PAREN_RE.search(name)) and not _FACILITY_RE.search(m.group(1)):
        name = name[:m.start(1)].rstrip()
    elif name.endswith((")", "）")):
        name = _strip_last_group(name)
    elif (i := _unclosed_paren(name)) is not None:
        name = name[:i].rstrip()
    return _OWNER_HEAD_RE.sub("", name).strip()


def _unclosed_paren(name: str) -> int | None:
    last_open: list[int] = []
    for i, ch in enumerate(name):
        if ch in "(（":
            last_open.append(i)
        elif ch in ")）" and last_open:
            last_open.pop()
    return last_open[0] if last_open else None


def operator_name(name: str) -> str:
    """名稱括號裡寫的經營組織（委託、承辦）；沒有回空字串。"""
    m = _OPERATOR_RE.search(name)
    return m.group(1).strip() if m else ""


def mol_rows_from_csv(data: bytes, group: str = "") -> Iterator[dict]:
    index: dict[str, int] | None = None
    for cells in csv_table(data):
        if index is None:
            found = {MOL_HEADERS[_header(c)]: i for i, c in enumerate(cells) if _header(c) in MOL_HEADERS}
            if {"name", "document_no"} <= set(found):
                index = found
            continue

        def get(key: str) -> str:
            i = index.get(key)
            return (cells[i] or "").strip() if i is not None and i < len(cells) else ""

        name, doc = strip_owner(get("name")), " ".join(get("document_no").split())
        if not name or not doc:
            continue
        yield {
            "group": group,
            "unit": get("unit"),
            "name": name,
            "document_no": doc,
            "announced_on": roc_date(get("announced")),
            "decided_on": roc_date(get("decided")),
            "articles": _split(get("articles")),
            "violations": _split(get("violation")),
            "fine": money(get("fine")),
            "victims": money(get("victims")),
            "note": get("note"),
        }


def mol_rows_from_zip(data: bytes) -> Iterator[dict]:
    """下載回來的 zip：檔名「announcement-A-….csv」的字母是法規組別。"""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in sorted(zf.infolist(), key=lambda i: i.filename):
            m = re.search(r"-([A-Z])-", info.filename)
            yield from mol_rows_from_csv(zf.read(info), m.group(1) if m else "")


def mol_penalty_id(row: dict) -> str:
    """處分字號＋名稱：勞保局一張處分書（同一個字號）會列好幾個單位，只用字號會互相蓋掉。"""
    key = "|".join([row["document_no"], normalize(row["name"])])
    return f"{MOL_KEY}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:20]}"


def doc_key(document_no: str) -> str:
    """跨來源比對處分字號用（臺北市總表與勞動部系統的寫法可能差全半形括號、空白）。"""
    return normalize(str(document_no or "")).replace(" ", "")


def mol_to_item(row: dict, ubn: str) -> Item:
    late_fee = any(LATE_FEE_RE.search(v) for v in row["violations"])
    content = "；".join(x for x in ("、".join(row["articles"]), "；".join(row["violations"])) if x)
    if late_fee:  # 勞退條例第 19 條：金額常只有幾百元，寫清楚不是罰鍰，讀者才分得出輕重
        content = f"加徵滯納金：{content}"
    if row["victims"]:
        content = f"{content}（職業災害罹災 {row['victims']} 人）"
    fine_text = f"{'加徵滯納金' if late_fee else '罰鍰'}新臺幣 {row['fine']:,} 元" if row["fine"] else ""
    unit = row["unit"].replace("台", "臺")
    return Item(
        kind="penalty",
        ubn=ubn,
        external_id=mol_penalty_id(row),
        source_url=MOL_SITE,
        data={
            "category": "labor",
            "org_name": row["name"],
            "county": unit,
            "law_group": MOL_LAW_GROUPS.get(row["group"], ""),
            "authority": mol_authority(unit),
            "decided_on": row["decided_on"],
            "announced_on": row["announced_on"],
            "document_no": row["document_no"],
            "content": content or "違反勞動法令",
            "fine_text": fine_text,
            "reason": row["note"],
        },
    )


def mol_to_items(rows: Iterable[dict], matcher: OrgMatcher, skip_docs: Iterable[str] = ()) -> Iterator[Item]:
    """名稱像非營利組織或對得上站上組織才收；別的勞動來源（臺北市總表）已收過的處分字號不再收。"""
    skip = {doc_key(d) for d in skip_docs}
    seen: set[str] = set()
    for row in rows:
        if doc_key(row["document_no"]) in skip:
            continue
        hit = matcher.match(row["name"])
        if hit is None and (op := operator_name(row["name"])):
            hit = matcher.match(op)
        if hit is None and (not NPO_NAME_RE.search(row["name"]) or COMPANY_RE.search(row["name"])):
            continue  # 一般公司行號（「艾協會藥聯股份有限公司」這種名稱剛好含「協會」的也算）
        item = mol_to_item(row, hit[0] if hit else "")
        if item.external_id in seen:  # 不同關鍵字會查到同一筆（例：財團法人＋基金會）
            continue
        seen.add(item.external_id)
        yield item


MOL_RETRIES = 2
MOL_RETRY_WAIT = 10.0  # 秒


def mol_download(client: PoliteClient, keyword: str, retries: int = MOL_RETRIES, wait: float = MOL_RETRY_WAIT) -> bytes:
    """2026-11-28 實測：同一天第二輪整批下載時，偶爾有一個關鍵字回 HTML 而不是 zip，隔一下重拿 token 再送就好；
    重試幾次都不是 zip 才當失敗（可能被防火牆擋下或網站改版）。"""
    content_type = ""
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(wait * attempt)
        page = client.get(MOL_SITE)
        m = re.search(r'name="_csrf_token"\s+value="([^"]+)"', page.text)
        if not m:
            raise RuntimeError("勞動部查詢頁找不到 _csrf_token（網站可能改版）")
        form = {"_csrf_token": m.group(1), "CITYNO": "", "UNITNAME": keyword, "DOCstartDate": "", "DOCEndDate": "",
                "REGNUMBER": "", "REGNO": "", "FINE": "", "downloadType": "3",
                **{f"sortName{i}": "" for i in range(1, 6)}, **{f"Page{i}": "1" for i in range(1, 6)}}
        resp = client.post(MOL_DOWNLOAD, data=form, headers={"Referer": MOL_SITE, "Origin": MOL_SITE.rstrip("/")})
        if resp.content[:2] == b"PK":
            return resp.content
        content_type = resp.headers.get("content-type") or ""
    raise RuntimeError(f"勞動部下載「{keyword}」重試 {retries} 次都不是 zip（{content_type}；可能被防火牆擋下或網站改版）")


def fetch_mol(client: PoliteClient, limit: int | None = None, orgs: Iterable[tuple[str, str]] = (),
              labor_docs: Iterable[str] = ()) -> Iterator[Item]:
    """每個關鍵字下載一次（查詢頁拿 token＋下載，兩個請求）。limit 算的是 Item 數。
    labor_docs：別的勞動來源已收過的處分字號（後端給），同一張處分不收第二次。"""
    matcher = OrgMatcher(orgs)
    rows = (row for kw in MOL_KEYWORDS for row in mol_rows_from_zip(mol_download(client, kw)))
    for count, item in enumerate(mol_to_items(rows, matcher, labor_docs)):
        if limit is not None and count >= limit:
            return
        yield item
