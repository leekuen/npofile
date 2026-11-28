"""官網成立宗旨來源（orgsite_mission，LK-54）的參數：要找哪些組織、用什麼濃縮一句話、哪些原文已經送審過。"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from django.conf import settings
from django.db.models import F, OuterRef, Subquery
from django.utils import timezone
from npofile_crawler import mission, orgsite

from orgs.models import Organization, OrgMission, RegistryEntry

from .models import CrawlerSource, CrawlRecord, OrgMissionCheck

log = logging.getLogger(__name__)


def targets() -> Iterator[tuple[str, str, str]]:
    """有官網、主管機關名冊沒有宗旨（官方的優先，官網只補空白的）、管理員也沒改過理念的組織；
    從沒找過的先、再來是最久沒找的。爬蟲拿走一個就記一次時間。"""
    last = OrgMissionCheck.objects.filter(ubn=OuterRef("ubn")).values("checked_at")[:1]
    has_registry = RegistryEntry.objects.exclude(purpose="").exclude(organization=None).values("organization_id")
    locked = OrgMission.objects.filter(locked=True).values("organization_id")
    qs = (
        Organization.objects.exclude(website="")
        .exclude(id__in=has_registry)
        .exclude(id__in=locked)
        .annotate(last_checked=Subquery(last))
        .order_by(F("last_checked").asc(nulls_first=True), "-disclosure_level", "ubn")
        .values_list("ubn", "name", "website")
    )
    for ubn, name, website in qs.iterator():
        if not orgsite.is_crawlable_site(website):
            continue
        OrgMissionCheck.objects.update_or_create(ubn=ubn, defaults={"website": website[:500], "checked_at": timezone.now()})
        yield ubn, name, website


def summarizer():
    """有 ANTHROPIC_API_KEY 才請 Claude 濃縮；沒有（或沒裝 anthropic 套件）回 None，一句話介紹改取原文第一句。"""
    if not settings.ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
    except ImportError:
        log.warning("orgsite_mission: 設了 ANTHROPIC_API_KEY 但沒裝 anthropic 套件，一句話介紹改取原文第一句")
        return None
    return mission.ClaudeSummarizer(
        anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY), model=settings.MISSION_SUMMARY_MODEL,
        max_calls=settings.MISSION_SUMMARY_MAX_PER_RUN or None,
    )


def seen(source: CrawlerSource) -> dict[str, str]:
    """每個組織最近一次送審的原文雜湊（不論核准、退回或還在等）：原文沒變就不再送審、不再花錢摘要。"""
    out: dict[str, str] = {}
    rows = (CrawlRecord.objects.filter(source=source, kind=CrawlRecord.Kind.MISSION)
            .order_by("created_at", "id").values_list("ubn", "payload"))
    for ubn, payload in rows.iterator():
        if payload.get("text"):
            out[ubn] = mission.text_hash(payload["text"])
    return out


def options(source: CrawlerSource) -> dict:
    return {"mission_targets": targets(), "summarizer": summarizer(), "mission_seen": seen(source)}
