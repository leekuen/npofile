"""財政部「非營利事業機關團體資料集」（政府資料開放平臺 dataset 34147）。"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator

from .http import PoliteClient
from .items import Item

SOURCE_URL = "https://eip.fia.gov.tw/data/BGMOPEN99.csv"
SOURCE_NAME = "財政部非營利事業機關團體資料集"

# 「最近異動原因」代碼 → 營運狀態；沒列到的都算營運中
STATUS_BY_REASON = {"11": "cancelled", "17": "revoked", "18": "closed"}

UBN_RE = re.compile(r"^\d{8}$")


def parse_csv(text: str, limit: int | None = None) -> Iterator[Item]:
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    next(reader, None)
    count = 0
    for row in reader:
        if len(row) < 5 or not UBN_RE.match(row[0].strip()):
            continue
        ubn, name, city, _changed, reason = (c.strip() for c in row[:5])
        if not name:
            continue
        yield Item(
            kind="org",
            ubn=ubn,
            data={
                "name": name,
                "city": city.replace("臺北縣", "新北市"),
                "status": STATUS_BY_REASON.get(reason, "active"),
            },
            source_url=SOURCE_URL,
        )
        count += 1
        if limit and count >= limit:
            return


def fetch(client: PoliteClient, limit: int | None = None) -> Iterator[Item]:
    resp = client.get(SOURCE_URL)
    yield from parse_csv(resp.content.decode("utf-8-sig", errors="replace"), limit=limit)
