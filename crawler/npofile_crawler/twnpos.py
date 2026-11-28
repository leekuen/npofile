"""台灣公益團體自律聯盟「好事大平台」會員財務報告（LK-25）。

自律聯盟會員每年 6 月繳交前一年度財務報告，聯盟放在各會員頁「瀏覽財務報告」連到的公開 Google 雲端資料夾，
檔名固定為「{民國年度}_financial-report_{會員編號}[_NN].pdf」。報告是各會員自己的財務報表（多半是會計師查核報告），
格式不一、多數是掃描檔：先讀 PDF 文字，讀不到再用影像辨識（OCR）。

找「捐款收入／捐贈收入」（有「…合計」優先）與「收入合計／收入總計」兩行，取最左邊的金額（本年度欄）；
捐款大於收入合計、或讀不到其中一個，就不給數字（只留報告連結），不猜。

網站前台資料來源：
- 會員清單：`https://api.oen.tw/api/donee/twnpos/articles?tags=…&limit=500`（網站自己一次要 500 筆）
- 會員頁：`https://twnpos.org.tw/team/{id}?_data=routes/team.$articleId`（Remix 的頁面資料）
- 雲端資料夾檔案清單：`https://drive.google.com/embeddedfolderview?id={資料夾}`（Google 給公開資料夾嵌入用的頁面）
- 下載：`https://drive.google.com/uc?export=download&id={檔案}`

會員桑基圖背後的試算表不公開，不從那裡取資料。
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from urllib.parse import quote

from pdfminer.high_level import extract_pages
from pdfminer.pdfparser import PDFSyntaxError
from pdfminer.psparser import PSException

from .grants import OrgMatcher
from .http import PoliteClient
from .items import Item
from .swft import _words

SITE = "https://twnpos.org.tw"
SITE_URL = SITE + "/team"
SOURCE_NAME = "台灣公益團體自律聯盟 好事大平台"
TAGS = ("一般民眾,中介團體&急難救助,老人,身心障礙者,兒童&青少年,心理衛生,成癮者,受刑人/更生人,原住民,LGBTQ+,"
        "家庭,疾病患者,婦女,環境保護&動物保護,街友")
LIST_URL = "https://api.oen.tw/api/donee/twnpos/articles?tags={tags}&locale=zh-TW&limit=500"
DRIVE_RE = re.compile(r"https://drive\.google\.com/[^\"'<> ]+")
DRIVE_ID_RE = re.compile(r"(?:/folders/|/file/d/|[?&]id=)([\w-]{10,})")
FILE_RE = re.compile(r"^(\d{3})_financial-report_([A-Z]\d{3,5})(?:_(\d+))?\.pdf$", re.I)
MAX_PDF_BYTES = 80_000_000   # 太大的檔（多半是整本年報掃描）不下載
OCR_PAGES = 15               # 影像辨識最多看前幾頁找收支表

# 影像辨識常把繁體認成簡體，比對科目名稱前先換回來
S2T = str.maketrans({"计": "計", "赠": "贈", "总": "總", "额": "額", "费": "費", "业": "業", "务": "務",
                     "补": "補", "资": "資", "际": "際", "项": "項"})
# 教會等宗教團體的捐款科目叫「奉獻收入」（辨識常多認一個字，例「奉獻献收入」）
DONATION_RE = re.compile(r"^(?:捐(?:款|贈|助)|奉獻.?)收入(?:合計|總計)?$")
TOTAL_RE = re.compile(r"^(?:(?:本期)?收入(?:合計|總計|總額)|總收入)$")
# 金額要有正確的千分位（辨識雜訊常把數字拆錯）；小於 1,000 的不算
AMOUNT_RE = re.compile(r"^\(?-?\d{1,3}(?:,\d{3})+\)?$")


@dataclass(frozen=True)
class Member:
    id: str
    no: str      # 會員編號，例 F0366
    name: str


@dataclass(frozen=True)
class ReportFile:
    year: int    # 民國年度
    file_id: str
    name: str

    @property
    def view_url(self) -> str:
        return f"https://drive.google.com/file/d/{self.file_id}/view"


def list_members(client: PoliteClient) -> list[Member]:
    data = client.get(LIST_URL.format(tags=quote(TAGS, safe=","))).json()
    out = []
    for a in (data.get("data") or {}).get("articles") or []:
        no = (a.get("subtitle") or "").replace("會員編號：", "").strip()
        if a.get("id") and a.get("title"):
            out.append(Member(id=a["id"], no=no, name=re.sub(r"\s+", "", a["title"])))
    return out


def report_link(client: PoliteClient, member: Member) -> str | None:
    """會員頁「瀏覽財務報告」的連結；短網址（supr.link）的頁面裡才有真正的雲端網址。"""
    post = client.get(f"{SITE}/team/{member.id}", params={"_data": "routes/team.$articleId"}).json().get("post") or {}
    for s in (post.get("i18nData") or {}).get("sections") or []:
        c = s.get("content") or {}
        if s.get("type") == "callToAction" and "財務" in (c.get("text") or "") and c.get("link"):
            link = c["link"]
            if "drive.google.com" not in link:
                m = DRIVE_RE.search(client.get(link).text)
                link = m.group(0) if m else None
            return link
    return None


def list_reports(client: PoliteClient, link: str) -> list[ReportFile]:
    m = DRIVE_ID_RE.search(link or "")
    if not m:
        return []
    html = client.get("https://drive.google.com/embeddedfolderview", params={"id": m.group(1)}).text
    ids = re.findall(r'href="https://drive\.google\.com/file/d/([\w-]+)/view', html)
    names = re.findall(r'class="flip-entry-title">([^<]+)<', html)
    best: dict[int, tuple[int, ReportFile]] = {}
    for name, fid in zip(names, ids):
        f = FILE_RE.match(name.strip())
        if not f:
            continue
        year, suffix = int(f.group(1)), int(f.group(3) or 0)
        # 同一年有「_01」等多份時取沒有編號的（正本），否則取編號最大的
        rank = 1000 if suffix == 0 else suffix
        if year not in best or rank > best[year][0]:
            best[year] = (rank, ReportFile(year=year, file_id=fid, name=name.strip()))
    return [rf for _, rf in sorted(best.values(), key=lambda x: -x[1].year)]


# ── 解析 ───────────────────────────────────────────────────────────────────


def pick_values(tokens: Iterable[tuple[float, float, float, str]], row_tol: float) -> dict[str, int] | None:
    """一頁的詞（行座標, 左, 右, 文字）→ 捐款收入與收入合計（本年度＝同一行最左邊的金額）。

    找不到捐款收入回 None；收入合計讀不到可以留空（有些表沒有這行，或辨識漏掉），但捐款大於收入合計就整頁不採用。"""
    toks = [(r, a, b, re.sub(r"\s", "", t.translate(S2T))) for r, a, b, t in tokens]

    def value(pattern: re.Pattern, prefer_subtotal: bool) -> int | None:
        labels = [t for t in toks if pattern.match(t[3])]
        if prefer_subtotal:
            labels = [t for t in labels if t[3].endswith(("合計", "總計"))] or labels
        for lab in labels:
            nums = sorted((t for t in toks if AMOUNT_RE.match(t[3]) and abs(t[0] - lab[0]) <= row_tol and t[1] > lab[2]),
                          key=lambda t: t[1])
            if nums:
                return int(nums[0][3].strip("()").replace(",", ""))
        return None

    donation, total = value(DONATION_RE, True), value(TOTAL_RE, False)
    if donation is None:
        return None
    if total is not None and donation > total:  # 對錯行了，整頁不採用
        return None
    return {"donation": donation, "income_total": total}


def _text_pages(pdf: bytes) -> Iterator[list]:
    for page in extract_pages(io.BytesIO(pdf)):
        yield _words(page)


def _ocr_pages(pdf: bytes) -> Iterator[list]:
    # 影像辨識的套件較大，只有遇到掃描檔才載入
    import pypdfium2 as pdfium
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    doc = pdfium.PdfDocument(pdf)
    for i in range(min(len(doc), OCR_PAGES)):
        result, _ = engine(doc[i].render(scale=2).to_numpy())
        yield [((b[0][1] + b[2][1]) / 2, b[0][0], b[1][0], t) for b, t, _conf in result or []]


def parse_report(pdf: bytes, ocr: bool = True) -> dict:
    """→ {"donation", "income_total", "method"}；讀不到數字時 donation/income_total 為 None。"""
    try:
        for words in _text_pages(pdf):
            if values := pick_values(words, row_tol=3):
                return {**values, "method": "文字"}
    except (PDFSyntaxError, PSException, ValueError, KeyError):
        pass
    if ocr:
        try:
            for words in _ocr_pages(pdf):
                if values := pick_values(words, row_tol=18):
                    return {**values, "method": "影像辨識"}
        except Exception:  # noqa: BLE001 — 單一檔案辨識失敗不中斷整批
            pass
    return {"donation": None, "income_total": None, "method": ""}


# ── 抓取 ───────────────────────────────────────────────────────────────────


def report_id(member: Member, year: int) -> str:
    return f"{member.no or member.id}-{year}"


def fetch(client: PoliteClient, limit: int | None = None, since_roc: int | None = None,
          orgs: Iterable[tuple[str, str]] = (), have: Iterable[str] = ()) -> Iterator[Item]:
    """近 5 年每位會員每年一份財務報告，對到組織的一筆一個 Item。limit 算的是下載的報告份數。

    have：已經收過的來源編號（例 F0366-114），不再下載；名稱對不到組織的會員整位跳過。"""
    matcher = OrgMatcher(orgs)
    done = set(have)
    count = 0
    for m in list_members(client):
        hit = matcher.match(m.name)
        if hit is None or hit[1]:
            continue
        link = report_link(client, m)
        if not link:
            continue
        for rf in list_reports(client, link):
            if since_roc is not None and rf.year < since_roc:
                continue
            if report_id(m, rf.year) in done:
                continue
            if limit is not None and count >= limit:
                return
            count += 1
            resp = client.get("https://drive.google.com/uc", params={"export": "download", "id": rf.file_id})
            pdf = resp.content
            values = parse_report(pdf) if len(pdf) <= MAX_PDF_BYTES and pdf[:4] == b"%PDF" else \
                {"donation": None, "income_total": None, "method": ""}
            yield Item(
                kind="financial",
                ubn=hit[0],
                external_id=report_id(m, rf.year),
                source_url=rf.view_url,
                data={
                    "year": rf.year,
                    "contributions": values["donation"],
                    "total_revenue": values["income_total"],
                    "document_url": rf.view_url,
                    "document_title": f"{m.name} {rf.year} 年度財務報告（自律聯盟）",
                    # 年度財務的「怎麼來的」：讀 PDF 文字＝text、影像辨識＝ocr、都讀不到就只留報告連結
                    "method": {"文字": "text", "影像辨識": "ocr"}.get(values["method"], "text"),
                    "notes": "掃描檔用影像辨識讀出，可能有誤" if values["method"] == "影像辨識" else "",
                    "filer_name": m.name,
                    "filer_no": m.no,
                },
            )
