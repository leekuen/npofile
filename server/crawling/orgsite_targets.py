"""組織官網來源（orgsite）的參數：要爬哪些組織、用什麼讀報告數字、哪些檔案已經讀過（LK-17）。"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from django.conf import settings
from django.db.models import F, OuterRef, Subquery
from django.utils import timezone
from npofile_crawler import orgsite

from orgs.models import Organization

from .models import CrawlerSource, CrawlRecord, OrgSiteCheck

log = logging.getLogger(__name__)


def targets() -> Iterator[tuple[str, str]]:
    """有官網的組織，從沒爬過的先、再來是最久沒爬的。爬蟲拿走一個就記一次時間（拿走才記，沒跑到的下次優先）。"""
    last = OrgSiteCheck.objects.filter(ubn=OuterRef("ubn")).values("checked_at")[:1]
    qs = (
        Organization.objects.exclude(website="")
        .annotate(last_checked=Subquery(last))
        # 沒爬過的（NULL）排最前面：PostgreSQL 預設把 NULL 排最後、SQLite 排最前，要明講
        .order_by(F("last_checked").asc(nulls_first=True), "-disclosure_level", "ubn")
        .values_list("ubn", "website")
    )
    for ubn, website in qs.iterator():
        if not orgsite.is_crawlable_site(website):
            continue
        OrgSiteCheck.objects.update_or_create(ubn=ubn, defaults={"website": website[:500], "checked_at": timezone.now()})
        yield ubn, website


def extractor():
    """有設 ANTHROPIC_API_KEY 才讀報告數字（會產生 API 費用）；沒設就只收報告清單。"""
    if not settings.ANTHROPIC_API_KEY:
        return None
    try:
        from npofile_crawler.financials import ClaudeExtractor

        import anthropic
    except ImportError:
        log.warning("orgsite: 設了 ANTHROPIC_API_KEY 但沒裝 anthropic 套件，這次只收報告清單")
        return None
    return ClaudeExtractor(anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY), model=settings.FINANCIAL_EXTRACT_MODEL)


def seen_docs(source: CrawlerSource) -> set[str]:
    """已經讀過數字的檔案網址（不論核准或退回），不再花錢重讀。"""
    payloads = CrawlRecord.objects.filter(source=source, kind=CrawlRecord.Kind.FINANCIAL).values_list("payload", flat=True)
    return {p.get("document_url") for p in payloads if p.get("document_url")}


def options(source: CrawlerSource) -> dict:
    return {"targets": targets(), "extractor": extractor(), "seen_docs": seen_docs(source)}
