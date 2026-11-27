"""NPOFile 爬蟲：把公開來源抓下來、解析成 `Item`，寫進資料庫由後端負責。"""

from .items import Item

__all__ = ["Item"]
