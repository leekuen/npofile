"""「近 5 年」只在這裡定義（口徑見 tickets/LK-07）：民國年度今年往前 4 年的 1 月 1 日起，未來年度照收。

年度募款、專案、捐款、排行、揭露指數都用這裡；裁罰不受限（永久保留）。
"""

from __future__ import annotations

from datetime import date

from django.db.models import Q
from django.utils import timezone

YEARS = 5


def today() -> date:
    return timezone.localdate()


def since_roc_year(ref: date | None = None) -> int:
    return (ref or today()).year - 1911 - (YEARS - 1)


def window_start(ref: date | None = None) -> date:
    return date(since_roc_year(ref) + 1911, 1, 1)


def in_window(roc_year: int | None, ref: date | None = None) -> bool:
    """年度不明的（沒有日期、名稱也沒寫年度）算在內，不因為缺資料就藏起來。"""
    return roc_year is None or roc_year >= since_roc_year(ref)


def annual_q(prefix: str = "") -> Q:
    return Q(**{f"{prefix}year__gte": since_roc_year()})


def project_q(prefix: str = "") -> Q:
    return Q(**{f"{prefix}period_year__gte": since_roc_year()}) | Q(**{f"{prefix}period_year__isnull": True})


def grant_q(prefix: str = "") -> Q:
    return Q(**{f"{prefix}year__gte": since_roc_year()})


def donation_q(prefix: str = "") -> Q:
    """有專案的看專案年度；手動輸入、沒掛專案的看捐款日期（沒日期算在內）。"""
    p = prefix
    return (
        Q(**{f"{p}project__isnull": False}) & project_q(f"{p}project__")
    ) | (
        Q(**{f"{p}project__isnull": True})
        & (Q(**{f"{p}donated_on__gte": window_start()}) | Q(**{f"{p}donated_on__isnull": True}))
    )
