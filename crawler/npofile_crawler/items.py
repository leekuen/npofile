from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date

KINDS = ("org", "annual", "project", "penalty", "donor_list", "grant", "document", "financial", "court_reg", "registry", "einvoice", "site_donor_list")


@dataclass
class Item:
    """一筆解析好的資料。kind 決定 data 的欄位，見各來源模組。"""

    kind: str
    ubn: str
    data: dict
    source_url: str = ""
    external_id: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown kind: {self.kind}")

    def content_hash(self, source_key: str) -> str:
        body = json.dumps(
            {"s": source_key, "k": self.kind, "u": self.ubn, "x": self.external_id, "d": self.data},
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        )
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def payload(self) -> dict:
        return json.loads(json.dumps(self.data, ensure_ascii=False, default=_json_default))


def _json_default(value):
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"not serializable: {type(value)}")


def roc_date(text: str) -> date | None:
    """民國日期 '113/05/31' 或 '1130531' / '0910222' → date；解析不了回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    try:
        if "/" in text:
            y, m, d = (int(p) for p in text.split("/"))
        elif text.isdigit() and len(text) in (6, 7):
            y, m, d = int(text[:-4]), int(text[-4:-2]), int(text[-2:])
        else:
            return None
        return date(y + 1911, m, d)
    except ValueError:
        return None


def money(text: str) -> int | None:
    digits = "".join(ch for ch in (text or "") if ch.isdigit())
    return int(digits) if digits else None
