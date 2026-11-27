"""經濟部商工登記公開資料（公司登記基本資料）：用公司全名查統一編號。不需金鑰。"""

from __future__ import annotations

import json
from urllib.parse import quote

from .http import PoliteClient

API = "https://data.gcis.nat.gov.tw/od/data/api/6BBA2268-1367-4B42-9CCA-BC17499EBE8C"
SOURCE_NAME = "經濟部商工登記公示資料"


def query_url(name: str) -> str:
    # 這支 API 只認 %20，不認 +，所以自己組查詢字串
    flt = quote(f"Company_Name like {name} and Company_Status eq 01")
    return f"{API}?$format=json&$filter={flt}&$skip=0&$top=20"


def pick_exact(name: str, body: str) -> dict | None:
    """只接受名稱完全相同的那一家；簡稱、部分相同一律不連（例：「星巴克」）。"""
    try:
        rows = json.loads(body) if body.strip() else []
    except json.JSONDecodeError:
        return None
    for row in rows:
        if row.get("Company_Name", "").strip() == name.strip():
            return {
                "ubn": row.get("Business_Accounting_NO", ""),
                "registered_name": row["Company_Name"],
                "representative": row.get("Responsible_Name", ""),
                "capital": row.get("Paid_In_Capital_Amount") or row.get("Capital_Stock_Amount") or None,
                "address": row.get("Company_Location", ""),
            }
    return None


def lookup(client: PoliteClient, name: str) -> dict | None:
    if "公司" not in name:
        return None
    return pick_exact(name, client.get(query_url(name)).text)


# 公司登記董監事資料集（LK-23）：依統編列出每位董監事與其代表的法人。
DIRECTORS_API = "https://data.gcis.nat.gov.tw/od/data/api/4E5F7653-1B91-4DDC-99D5-468530FAE396"


def directors_url(ubn: str) -> str:
    flt = quote(f"Business_Accounting_NO eq {ubn}")
    return f"{DIRECTORS_API}?$format=json&$filter={flt}&$skip=0&$top=500"


def parse_juristic_directors(body: str) -> list[dict]:
    """董監事裡代表法人出任的那些法人：名稱、佔幾席、持股數（照第一次出現的順序）。
    個人姓名不留：只用法人關係歸戶。"""
    try:
        rows = json.loads(body) if body.strip() else []
    except json.JSONDecodeError:
        return []
    found: dict[str, dict] = {}
    for row in rows if isinstance(rows, list) else []:
        name = (row.get("Juristic_Person_Name") or "").strip()
        if not name:
            continue
        entry = found.setdefault(name, {"name": name, "seats": 0, "shares": 0})
        entry["seats"] += 1
        try:
            entry["shares"] = max(entry["shares"], int(row.get("Person_Shareholding") or 0))
        except (TypeError, ValueError):
            pass
    return list(found.values())


def juristic_directors(client: PoliteClient, ubn: str) -> list[dict]:
    return parse_juristic_directors(client.get(directors_url(ubn)).text)
