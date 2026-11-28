"""來源登記表：後端只透過這裡認識有哪些來源。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from . import environment, fia, grants, judicial, labor, mohw, orgsite, registries, swft, twnpos, violations, wabay
from .http import PoliteClient
from .items import Item


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    url: str
    official: bool
    fetch: Callable[[PoliteClient, int | None], Iterator[Item]]
    description: str = ""
    # 寫進資料時掛的來源名稱；同一個網站的不同抓法共用一個，才不會把同一個專案存成兩份
    data_name: str = ""
    # fetch 另外收哪些參數（後端依設定給值）：threshold＝清冊個人門檻、since_roc＝只收這個民國年度起、
    # plan＝記住抓到哪裡的 mohw.ActivityPlan（後端用資料庫版本）、revisit＝要回頭再看的專案編號、orgs＝（統編, 名稱）名冊、
    # orgs_city＝（統編, 名稱, 所在縣市）名冊、seen_regs＝已存過的法院登記公告編號、floor_reached＝法院登記公告回補完了沒、listed＝列表讀到幾筆（[0]，給 crawl 判斷網站改版）、
    # targets＝要爬的（統編, 官網）、extractor＝讀報告數字的 financials.ClaudeExtractor（沒設金鑰是 None）、seen_docs＝已讀過數字的檔案網址
    # have＝已經收過的財報編號（不再下載）、moenv_api_key＝環境部開放資料 API 金鑰、since_date＝上次成功抓取往前推的日期（只抓新的）
    options: tuple[str, ...] = ()
    # 統編不在組織資料庫的資料不存（例：挖貝上公司提的商品集資），不進審核清單
    known_orgs_only: bool = False
    # 先審核的來源：同一筆（同編號）核准過之後，數字更新直接上架，不再每天進審核清單
    update_approved: bool = False
    # 整份重新下載的年更資料（LK-32）：「crawl all」距上次成功不到這麼多天就略過（0＝每次都跑）；指名跑不受限
    every_days: int = 0
    # 要設了這個設定（環境變數）才跑得動：沒設時「crawl all」略過、不當成失敗；指名跑會失敗並寫明原因（LK-36）
    requires_setting: str = ""

    @property
    def record_name(self) -> str:
        return self.data_name or self.name


SOURCES = {
    s.key: s
    for s in (
        Source("fia", fia.SOURCE_NAME, fia.SOURCE_URL, True, fia.fetch, "政府公開資料：組織名冊"),
        Source("mohw", mohw.SOURCE_NAME, mohw.BASE + "/app39/", True, mohw.fetch,
               "政府公開資料：團體基本資料、歷年募款、近五年裁處", options=("since_roc",)),
        Source("mohw_activities", "衛生福利部公益勸募管理系統（勸募活動與捐贈人清冊）", mohw.BASE + "/app39/",
               True, mohw.fetch_activities,
               "政府公開資料：近 5 年的勸募活動與捐贈人清冊，每次接著上次的進度、只抓新的與有變動的；"
               "「每次最多抓幾筆」算的是活動數",
               data_name=mohw.SOURCE_NAME, options=("threshold", "since_roc", "plan")),
        Source("mohw_violations", "衛生福利部公益勸募管理系統（違規公告，全部年度）", mohw.BASE + "/app39/violation/violationIndex",
               True, violations.fetch,
               "政府公開資料：所有年度的裁處（團體頁只列近五年）；「每次最多抓幾筆」算的是公告筆數",
               data_name=mohw.SOURCE_NAME, options=("since_roc",)),
        Source("wabay", wabay.SOURCE_NAME, wabay.BASE + "/projects", False, wabay.fetch,
               "群眾集資平台：非營利組織在挖貝提的集資專案（依提案者統編對組織；只收收錄的組織）；"
               "每天抓進行中的專案，結束後 14 天內再回頭看；不影響揭露指數",
               options=("revisit",), known_orgs_only=True, update_approved=True),
        Source("mohw_grants", grants.MOHW.name, grants.DATASET_PAGE.format(id=grants.MOHW.id), True, grants.fetch_mohw,
               "政府公開資料：衛福部（含社家署、健保署、疾管署等）每季公開的補(捐)助核定案件；"
               "近 5 年每年取最新一季的累計表，受補助對象名稱跟組織名稱完全相同才收（「某某附設某某」算給上層法人）",
               options=("since_roc", "orgs")),
        Source("esf_grants", grants.ESF.name, grants.DATASET_PAGE.format(id=grants.ESF.id), True, grants.fetch_esf,
               "政府公開資料：勞動部就業安定基金（多元就業開發方案、職業訓練、身障就業等）每季公開的補(捐)助核定案件；"
               "近 5 年每年取最新一季的累計表，對組織的規則同衛福部補助",
               options=("since_roc", "orgs")),
        # LK-30：更多部會，規則都同衛福部補助
        *(
            Source(key, spec.name, grants.DATASET_PAGE.format(id=spec.id), True, grants.fetcher(spec),
                   f"政府公開資料：{what}每季公開的補(捐)助核定案件；近 5 年每年取最新一季的累計表，對組織的規則同衛福部補助",
                   options=("since_roc", "orgs"))
            for key, spec, what in (
                ("k12ea_grants", grants.K12EA, "教育部國民及學前教育署"),
                ("wda_grants", grants.WDA, "勞動部勞動力發展署及所屬分署（公務預算與特別預算；寫「對個人」的列不收）"),
                ("nidf_grants", grants.NIDF, "新住民發展基金（內政部移民署）對個人及團體"),
                ("oac_grants", grants.OAC, "海洋委員會（含海巡署、海保署等所屬；111、112 年只公開 PDF，讀不到）"),
            )
        ),
        *(
            Source(spec.key, spec.source_name, labor.DATASET_PAGE.format(id=spec.dataset), True, labor.fetcher(spec),
                   f"政府公開資料：{spec.county}依勞動基準法第 80-1 條公布的違反事業單位（每月更新的總表）；"
                   "只收名稱像非營利組織或對得上站上組織的處分，負責人姓名不存；"
                   "名稱像非營利組織但對不上的，進審核清單（統編空白）等管理員指定組織或退回",
                   options=("orgs",))
            for spec in labor.SPECS
        ),
        Source("moenv_penalties", environment.SOURCE_NAME, environment.DATASET_PAGE, True, environment.fetch,
               "政府公開資料：各縣市環保局與環境部對列管事業的污染源裁處（每天更新）；用統一編號對組織，只收站上已有的組織，"
               "不進審核清單；第一次全部回補，之後每天只抓上次以來新匯入的。違規人名稱與地址不存。要設 MOENV_API_KEY 才會跑",
               options=("orgs", "moenv_api_key", "since_date", "listed"), known_orgs_only=True,
               requires_setting="MOENV_API_KEY"),
        Source("judicial", judicial.SOURCE_NAME, judicial.LIST_PAGE, True, judicial.fetch,
               "政府公開資料：司法院每天公告的社團法人、財團法人設立、變更、解散、清算登記（108-12-09 起全部保留）；"
               "法人名稱跟組織名稱完全相同且唯一才連（同名的用法院所在縣市挑），對不到的記下不顯示、後台可手動指定；"
               "董事、監察人姓名不存；不改財政部名冊的營運狀態。第一次會回補全部，之後每天只抓新的；「每次最多抓幾筆」算的是公告筆數",
               options=("orgs_city", "seen_regs", "floor_reached", "listed")),
        Source("orgsite", "組織官網（年報與財務報告）", "", False, orgsite.fetch,
               "組織自己官網公開的近 5 年財務報告、年報、工作／成果報告；設了 ANTHROPIC_API_KEY 才會讀出報告裡的數字"
               "（會產生 API 費用）。「每次最多抓幾筆」算的是組織數",
               data_name=orgsite.SOURCE_NAME, options=("since_roc", "targets", "extractor", "seen_docs")),
        Source("swft", swft.SOURCE_NAME, swft.SITE_URL, True, swft.fetch,
               "政府公開資料：全國性社會福利財團法人送衛福部備查的年度決算，從「年度決算總表」讀收入、支出、餘絀與資產負債（寫進年度財務）；"
               "近 5 年、到去年為止，已收過的年度不再下載；名稱跟組織完全相同才收；「每次最多抓幾筆」算的是決算份數",
               options=("since_roc", "orgs", "have")),
        Source("twnpos", twnpos.SOURCE_NAME, twnpos.SITE_URL, False, twnpos.fetch,
               "自律聯盟會員自己上傳的年度財務報告（公開雲端資料夾的 PDF），讀出捐款收入與收入合計；掃描檔用影像辨識，"
               "讀不到就只留報告連結；近 5 年，已收過的年度不再下載；名稱跟組織完全相同才收；"
               "影像辨識很慢，每次最多跑的分鐘數到了就停，下次接著抓",
               options=("since_roc", "orgs", "have"), known_orgs_only=True),
        Source("moe_registry", registries.MOE_NAME, registries.DATASET_PAGE.format(id=registries.MOE_DATASET), True,
               registries.fetch_moe,
               "政府公開資料：教育部主管的教育財團法人名冊（主管機關、登記財產、成立宗旨、服務對象、基金會狀態）；"
               "每月檢查一次。名稱跟組織名稱完全相同且唯一才連起來，對不上的記在「主管機關名冊」等管理員指定；"
               "董事長、執行長、聯絡人的姓名與聯絡方式不存",
               options=("orgs",), every_days=30),
        Source("einvoice_codes", registries.EINVOICE_NAME, registries.DATASET_PAGE.format(id=registries.EINVOICE_DATASET),
               True, registries.fetch_einvoice,
               "政府公開資料：電子發票受捐贈機關或團體的捐贈碼；每月檢查一次。用統一編號對組織，統編不在組織名冊的不顯示",
               every_days=30),
    )
}
