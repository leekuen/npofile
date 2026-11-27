"""來源登記表：後端只透過這裡認識有哪些來源。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from . import fia, mohw, violations, wabay
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
    # plan＝記住抓到哪裡的 mohw.ActivityPlan（後端用資料庫版本）、revisit＝要回頭再看的專案編號
    options: tuple[str, ...] = ()
    # 統編不在組織資料庫的資料不存（例：挖貝上公司提的商品集資），不進審核清單
    known_orgs_only: bool = False
    # 先審核的來源：同一筆（同編號）核准過之後，數字更新直接上架，不再每天進審核清單
    update_approved: bool = False

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
    )
}
