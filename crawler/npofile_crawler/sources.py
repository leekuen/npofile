"""來源登記表：後端只透過這裡認識有哪些來源。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from . import fia, judicial, mohw, violations
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
    # org_names＝資料庫裡所有組織的 {名稱: 統編}、judicial_credentials＝司法院 API 帳密
    options: tuple[str, ...] = ()
    # 新建來源設定時要不要自動上架；None＝跟 official 一樣（政府資料直接上架）
    auto_approve: bool | None = None
    # True＝一次跑下來沒有新資料是常態（例：今天的判決沒有一則牽涉到組織），不當成來源壞掉
    may_be_empty: bool = False
    # False＝新建時先停用（例：要先設定帳號才能跑）
    enabled_by_default: bool = True
    # False＝不跟著 crawl all 跑，有自己的排程（例：司法院 API 只在凌晨開放）
    in_all: bool = True

    @property
    def default_auto_approve(self) -> bool:
        return self.official if self.auto_approve is None else self.auto_approve

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
               "政府公開資料：每個團體的所有勸募活動與捐贈人清冊；「每次最多抓幾筆」算的是團體數",
               data_name=mohw.SOURCE_NAME, options=("threshold", "since_roc")),
        Source("mohw_violations", "衛生福利部公益勸募管理系統（違規公告，全部年度）", mohw.BASE + "/app39/violation/violationIndex",
               True, violations.fetch,
               "政府公開資料：所有年度的裁處（團體頁只列近五年）；「每次最多抓幾筆」算的是公告筆數",
               data_name=mohw.SOURCE_NAME, options=("since_roc",)),
        # 判決是政府資料，但「哪則判決跟哪個組織有關」是我們比對出來的，一律進待審核
        Source("judicial", judicial.SOURCE_NAME, judicial.PORTAL_URL, True, judicial.fetch,
               "政府公開資料：組織牽涉其中的刑事與行政判決（比對組織名稱，全部進待審核）；"
               "要先在 server/.env 設定司法院帳號，且只能在每天 00:00–06:00 執行；「每次最多抓幾筆」算的是讀了幾則判決",
               options=("org_names", "judicial_credentials"), auto_approve=False, may_be_empty=True,
               enabled_by_default=False, in_all=False),
    )
}
