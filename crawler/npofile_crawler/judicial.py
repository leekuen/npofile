"""司法院裁判書：找出「組織真的牽涉其中」的刑事與行政判決。

資料怎麼來：
- 開放 API（要先在司法院資料開放平臺註冊帳號）：Auth 換 Token（6 小時有效）→ JList 給「7 天前那天」異動的
  判決編號（jid）→ JDoc 逐則取全文。服務時間只有每天 00:00–06:00（臺灣時間）。API 沒有搜尋功能。
- 歷年資料：平臺的每月整包（RAR，同樣要登入下載），解壓後一則判決一個 JSON，用 iter_archive 匯入。
- 裁判書查詢網站（judgment.judicial.gov.tw）有防機器人機制，不爬。

為什麼不是「名稱出現就算」：2026-11-27 用機構全名查到的 7 則判決全是誤報（別人案子裡指定的捐款對象、
機構的車被撞、員工薪資扣押、修改章程）。所以這裡只收：
1. 刑事（jid 法院代號最後一碼 M）與行政（A）判決；
2. 刑事只收侵占、詐欺、背信、偽造、性侵、兒少、洗錢、貪污等罪名（案由比對 SERIOUS_RE）；
3. 組織名稱出現的段落不是「給付／捐款給這個組織」；
4. 角色（被告／當事人／組織人員涉案／判決提及）寫進內容，全部進待審核，由人判斷。

判決被撤下（JDoc 回「查無資料…移除」）：依 API 使用規定要跟著刪，產生 deleted=True 的項目讓後端刪除。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from .http import PoliteClient
from .items import Item

log = logging.getLogger(__name__)

SOURCE_NAME = "司法院裁判書"
API = "https://data.judicial.gov.tw/jdg/api"
AUTH_URL = API + "/Auth"
LIST_URL = API + "/JList"
DOC_URL = API + "/JDoc"
PORTAL_URL = "https://opendata.judicial.gov.tw/"
VIEW_URL = "https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id={jid}"
TAIPEI = timezone(timedelta(hours=8))
SERVICE_HOURS = range(0, 6)

# 刑事案由：只收跟「錢被拿走、文件造假、人被傷害」有關的罪名
SERIOUS_RE = re.compile(
    r"侵占|詐欺|背信|偽造|變造|洗錢|貪污|圖利|妨害性自主|性侵|性騷擾|猥褻|強制性交|兒童及少年|兒少|"
    r"虐待|傷害|妨害自由|過失致死|業務過失|稅捐稽徵|商業會計|公益勸募|政府採購|個人資料|人口販運|毒品"
)
# 組織名稱前面出現這些字：多半是「給付／捐給這個組織」（緩刑條件、和解、公益捐）
PAYMENT_RE = re.compile(r"給付|支付|捐|匯款|匯入|轉帳")
DONATION_END_RE = re.compile(r"(?:與|予|給|至|到|向|元|捐款|捐贈|捐助)$")
DONATION_AFTER_RE = re.compile(r"^(?:之?(?:帳戶|劃撥帳號)|指定|作為公益|公益捐)")
# 組織名稱附近出現這些職稱：組織的人涉案
STAFF_RE = re.compile(
    r"董事長|董事|執行長|負責人|理事長|理事|總幹事|秘書長|主任|院長|園長|會長|社工|會計|出納|職員|員工|"
    r"教保員|保育員|生活輔導員|輔導員|所長|館長|牧師|住持"
)
PARTY_LABEL_RE = re.compile(
    r"(被告|原告|上訴人|被上訴人|抗告人|再審原告|再審被告|聲請人|相對人|自訴人|告訴人|參加人)$"
)
LEGAL_PREFIXES = ("財團法人", "社團法人")
MIN_KEY_LEN = 5  # 拿掉「財團法人」後少於 5 個字的名稱（例「慈雲宮」）太容易撞名，不比對
BUCKET = 4
WINDOW = 30
DELETED_MARK = "查無資料"


class JudicialError(RuntimeError):
    pass


# ── 名稱比對 ─────────────────────────────────────────────────────────


def normalize(text: str) -> str:
    """判決全文會在名稱中間斷行、用全形空白排版；臺／台混用。比對前一律去空白、臺→台。"""
    return re.sub(r"\s+", "", text or "").replace("臺", "台")


def _key(name: str) -> str:
    key = normalize(name)
    for p in LEGAL_PREFIXES:
        if key.startswith(p):
            key = key[len(p):]
    return key


class NameIndex:
    """組織名稱 → 統編。以名稱前 4 個字分桶，掃全文時每個位置查一次桶、取最長的相符名稱。"""

    def __init__(self, names: dict[str, str] | Iterable[tuple[str, str]]):
        pairs = names.items() if isinstance(names, dict) else names
        self._buckets: dict[str, list[tuple[str, str, str]]] = {}
        for name, ubn in pairs:
            key = _key(name)
            if len(key) < MIN_KEY_LEN:
                continue
            self._buckets.setdefault(key[:BUCKET], []).append((key, ubn, name))
        for bucket in self._buckets.values():
            bucket.sort(key=lambda t: -len(t[0]))

    def find(self, text: str) -> list[tuple[int, int, str, str]]:
        """回傳（起點, 終點, 統編, 組織名稱），位置是 normalize 後的全文。重疊時取最長的。"""
        hits: list[tuple[int, int, str, str]] = []
        i, n = 0, len(text)
        while i < n:
            bucket = self._buckets.get(text[i : i + BUCKET])
            if bucket:
                for key, ubn, name in bucket:
                    if text.startswith(key, i):
                        hits.append((i, i + len(key), ubn, name))
                        i += len(key)
                        break
                else:
                    i += 1
            else:
                i += 1
        return hits


# ── 判決解析 ─────────────────────────────────────────────────────────


@dataclass
class Judgment:
    jid: str
    year: str
    case: str
    no: str
    decided_on: date | None
    title: str
    text: str  # 原始全文（保留換行）
    pdf_url: str = ""

    @property
    def court_code(self) -> str:
        return self.jid.split(",", 1)[0]

    @property
    def kind(self) -> str:
        """法院代號最後一碼：M 刑事、V 民事、A 行政、P 公懲、C 憲法。"""
        return self.court_code[-1:]

    @property
    def case_no(self) -> str:
        return f"{self.year}年度{self.case}字第{self.no}號"

    @property
    def court(self) -> str:
        first = re.sub(r"\s+", "", self.text[:80])  # 法院名稱照原文顯示，不做臺／台統一
        m = re.match(r"(.+?法院(?:.{1,3}分院)?)", first)
        return m.group(1) if m else ""

    @property
    def url(self) -> str:
        return VIEW_URL.format(jid=quote(self.jid, safe=""))


def parse_doc(data: dict) -> Judgment | None:
    """JDoc 回應或整包裡的一則 JSON → Judgment。整包的全文欄位叫 JFULL，API 的在 JFULLX.JFULLCONTENT。"""
    jid = (data.get("JID") or "").strip()
    if not jid:
        return None
    full = data.get("JFULLX")
    if isinstance(full, dict):
        text, pdf = full.get("JFULLCONTENT") or "", full.get("JFULLPDF") or ""
    else:
        text, pdf = data.get("JFULL") or data.get("JFULLCONTENT") or "", data.get("JPDF") or ""
    raw_date = str(data.get("JDATE") or "").strip()
    try:
        decided = datetime.strptime(raw_date, "%Y%m%d").date() if raw_date else None
    except ValueError:
        decided = None
    return Judgment(
        jid=jid,
        year=str(data.get("JYEAR") or "").strip(),
        case=str(data.get("JCASE") or "").strip(),
        no=str(data.get("JNO") or "").strip(),
        decided_on=decided,
        title=str(data.get("JTITLE") or "").strip(),
        text=text,
        pdf_url=pdf,
    )


def worth_reading(jid: str) -> bool:
    """只看 jid 就能排除的（不必取全文）：民事、公懲、憲法。"""
    court = jid.split(",", 1)[0]
    return court[-1:] in ("M", "A")


def _header(norm: str) -> str:
    """當事人欄：主文之前。"""
    end = norm.find("主文")
    return norm[: end if end > 0 else 400]


def _main_text(text: str) -> str:
    norm = re.sub(r"[ \t　]+", "", text or "")
    m = re.search(r"主\s*文\s*\n(.+?)\n\s*(?:犯罪)?事\s*實|主\s*文\s*\n(.+?)\n\s*理\s*由", norm, re.S)
    body = (m.group(1) or m.group(2)) if m else ""
    return re.sub(r"\s+", "", body)[:500]


def classify(judgment: Judgment, start: int, end: int, norm: str) -> str | None:
    """組織在這則判決的角色；None＝不算（捐款對象等）。"""
    before = norm[max(0, start - WINDOW) : start]
    after = norm[end : end + WINDOW]
    stripped_before = before
    for p in LEGAL_PREFIXES:
        if stripped_before.endswith(p):
            stripped_before = stripped_before[: -len(p)]
    clause = re.split(r"[。；：]", stripped_before)[-1]
    if (PAYMENT_RE.search(clause) and DONATION_END_RE.search(clause)) or DONATION_AFTER_RE.search(after):
        return None
    header_end = len(_header(norm))
    if start < header_end:
        m = PARTY_LABEL_RE.search(stripped_before[-8:])
        label = m.group(1) if m else ""
        if not label:
            # 「被　　告」排版後變「被告」，但名稱前可能隔著其他字；往前找最近的當事人稱謂
            labels = list(re.finditer(r"被告|原告|上訴人|聲請人|相對人|自訴人|抗告人", norm[max(0, start - 40) : start]))
            label = labels[-1].group(0) if labels else ""
        if label:
            return f"組織為{label}"
    if STAFF_RE.search(before) or STAFF_RE.search(after):
        return "組織人員涉案"
    return "判決內容提及組織"


def match(judgment: Judgment, index: NameIndex) -> list[Item]:
    """一則判決 → 每個牽涉其中的組織一筆 penalty 項目。"""
    if judgment.kind not in ("M", "A"):
        return []
    if judgment.kind == "M" and not SERIOUS_RE.search(judgment.title):
        return []
    norm = normalize(judgment.text)
    roles: dict[str, tuple[str, str, int, int]] = {}
    rank = {"組織為": 0, "組織人員涉案": 1, "判決內容提及組織": 2}
    for start, end, ubn, name in index.find(norm):
        role = classify(judgment, start, end, norm)
        if role is None:
            continue
        current = roles.get(ubn)
        weight = next(v for k, v in rank.items() if role.startswith(k))
        if current is None or weight < next(v for k, v in rank.items() if current[0].startswith(k)):
            roles[ubn] = (role, name, start, end)
    items = []
    main = _main_text(judgment.text)
    kind_label = "刑事判決" if judgment.kind == "M" else "行政判決"
    for ubn, (role, name, start, end) in roles.items():
        excerpt = norm[max(0, start - 60) : end + 60]
        items.append(
            Item(
                kind="penalty",
                ubn=ubn,
                data={
                    "decided_on": judgment.decided_on,
                    "authority": judgment.court,
                    "document_no": judgment.case_no,
                    "content": f"{kind_label}：{judgment.title}（{role}）",
                    "fine_text": "",
                    "reason": "\n\n".join(p for p in (f"主文：{main}" if main else "", f"相關段落：…{excerpt}…") if p),
                },
                source_url=judgment.url,
                external_id=judgment.jid,
                extra={"role": role, "matched_name": name},
            )
        )
    return items


def deleted_item(jid: str) -> Item:
    """判決被撤下：後端看到 extra.deleted 就刪掉同一則判決的資料。"""
    return Item(kind="penalty", ubn="", data={}, external_id=jid, extra={"deleted": True})


# ── API ──────────────────────────────────────────────────────────────


def in_service_hours(now: datetime | None = None) -> bool:
    now = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    return now.hour in SERVICE_HOURS


class JudicialAPI:
    def __init__(self, client: PoliteClient, user: str, password: str):
        if not user or not password:
            raise JudicialError(
                "還沒設定司法院資料開放平臺的帳號：在 server/.env 填 JUDICIAL_API_USER、JUDICIAL_API_PASSWORD"
                f"（帳號到 {PORTAL_URL} 註冊）"
            )
        self.client = client
        self.user = user
        self.password = password
        self.token = ""

    def _post(self, url: str, body: dict):
        resp = self.client.post(url, json=body)
        try:
            return resp.json()
        except ValueError as exc:
            raise JudicialError(f"{url} 回傳的不是 JSON：{resp.text[:200]}") from exc

    def auth(self) -> str:
        data = self._post(AUTH_URL, {"user": self.user, "password": self.password})
        token = data.get("Token") if isinstance(data, dict) else None
        if not token:
            raise JudicialError(f"司法院 API 驗證失敗：{data}")
        self.token = token
        return token

    def changed(self) -> list[tuple[str, list[str]]]:
        data = self._post(LIST_URL, {"token": self.token or self.auth()})
        if isinstance(data, dict):
            raise JudicialError(f"取異動清單失敗：{data}")
        return [(d.get("date", ""), list(d.get("list") or [])) for d in data]

    def doc(self, jid: str) -> dict | None:
        """None＝判決已撤下。"""
        data = self._post(DOC_URL, {"token": self.token or self.auth(), "j": jid})
        if isinstance(data, dict) and "error" in data:
            if DELETED_MARK in str(data["error"]):
                return None
            raise JudicialError(f"取判決 {jid} 失敗：{data['error']}")
        return data


def fetch(
    client: PoliteClient,
    limit: int | None = None,
    org_names: dict[str, str] | None = None,
    judicial_credentials: tuple[str, str] = ("", ""),
    now: datetime | None = None,
) -> Iterator[Item]:
    """每天跑一次：取 7 天前異動的判決，逐則比對。limit 算的是讀了幾則判決全文。"""
    if not in_service_hours(now):
        raise JudicialError("司法院裁判書 API 只在每天 00:00–06:00（臺灣時間）提供服務，請排在這段時間執行")
    api = JudicialAPI(client, *judicial_credentials)
    api.auth()
    index = NameIndex(org_names or {})
    read = 0
    for _day, jids in api.changed():
        for jid in jids:
            if not worth_reading(jid):
                continue
            data = api.doc(jid)
            read += 1
            if data is None:
                yield deleted_item(jid)
            else:
                judgment = parse_doc(data)
                if judgment is not None:
                    yield from match(judgment, index)
            if limit and read >= limit:
                return


def iter_archive(folder: str | Path, org_names: dict[str, str], limit: int | None = None) -> Iterator[Item]:
    """每月整包解壓後的資料夾：底下每個 .json 是一則判決。"""
    index = NameIndex(org_names)
    read = 0
    for path in sorted(Path(folder).rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            log.warning("讀不懂 %s，略過", path)
            continue
        if not worth_reading(str(data.get("JID") or "")):
            continue
        judgment = parse_doc(data)
        read += 1
        if judgment is not None:
            yield from match(judgment, index)
        if limit and read >= limit:
            return
