"""組織理念（LK-54）：組織頁頂端與推薦卡（LK-52）要顯示的那一段「這個組織在做什麼」，唯一出處。

優先順序：
1. 管理員在後台改過的（OrgMission.locked）
2. 主管機關名冊的成立宗旨（LK-32 RegistryEntry.purpose，官方資料）；一句話介紹取原文第一句
3. 組織官網抓到、管理員核准的（OrgMission）
都沒有回 None。"""

from __future__ import annotations

from collections.abc import Iterable

from npofile_crawler.mission import first_sentence

from .models import Organization, OrgMission, RegistryEntry

REGISTRY_METHOD = OrgMission.Method.FIRST_SENTENCE


def _from_registry(entry: RegistryEntry) -> dict:
    return {
        "summary": first_sentence(entry.purpose),
        "text": entry.purpose,
        "origin": "registry",
        "origin_label": f"{entry.authority}名冊" if entry.authority else entry.source_name,
        "source_name": entry.source_name,
        "source_url": entry.source_url,
        "summary_method": REGISTRY_METHOD,
        "summarized_by_site": True,
        "fetched_on": entry.data_date.isoformat() if entry.data_date else None,
    }


def _from_site(m: OrgMission) -> dict:
    return {
        "summary": m.summary,
        "text": m.text,
        "origin": "manual" if m.locked else "website",
        "origin_label": "本站整理" if m.locked else "組織官網",
        "source_name": m.source_name,
        "source_url": m.source_url,
        "summary_method": m.summary_method,
        # 一句話是本站濃縮的（不是組織自己寫的那一句），前台要標「由本站摘要」
        "summarized_by_site": m.summary_method != OrgMission.Method.MANUAL,
        "fetched_on": m.fetched_on.isoformat() if m.fetched_on else None,
    }


def pick(mission: OrgMission | None, registries: Iterable[RegistryEntry]) -> dict | None:
    if mission is not None and mission.locked:
        return _from_site(mission)
    entry = next((r for r in registries if (r.purpose or "").strip()), None)
    if entry is not None:
        return _from_registry(entry)
    if mission is not None and mission.summary:
        return _from_site(mission)
    return None


def for_org(org: Organization) -> dict | None:
    """組織頁用（registry_entries 已預先載入就不再查）。"""
    try:
        mission = org.mission
    except OrgMission.DoesNotExist:
        mission = None
    return pick(mission, org.registry_entries.all())


def summaries(org_ids: Iterable[int]) -> dict[int, dict]:
    """推薦卡（LK-52）一次拿多個組織：{組織 id: 同 for_org 的內容}；沒有理念的組織不在裡面。兩個查詢。"""
    ids = list(org_ids)
    missions = {m.organization_id: m for m in OrgMission.objects.filter(organization_id__in=ids)}
    regs: dict[int, list[RegistryEntry]] = {}
    for r in RegistryEntry.objects.filter(organization_id__in=ids).exclude(purpose="").order_by("authority", "id"):
        regs.setdefault(r.organization_id, []).append(r)
    out = {}
    for i in ids:
        picked = pick(missions.get(i), regs.get(i, []))
        if picked is not None:
            out[i] = picked
    return out
