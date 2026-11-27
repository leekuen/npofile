"""集團歸戶的規則只寫在這裡（口徑見 tickets/LK-23）。

- 每家公司只認一個「上層」：代表法人出任董監事、佔最多席的那個法人（名稱含「公司」；同席數比持股，再同就不認）。
  上層本身也有上層就一路往上找，最上面那個法人＝集團；上層一樣的公司同一群，上層本身是捐款公司也算進去。
  不用「共用任何一個法人董事就同一群」：合資公司（例：台北金融大樓、悠遊卡）的董事來自好幾個集團，
  這樣連會把富邦、證交所、中華電信、公股銀行串成一群（2026-11-27 本機實測）。
- 政府機關、國發基金、勞動基金、郵政、信託專戶、財團法人／社團法人這類法人董事不算：
  它們在很多公司都有席次，不代表同一個集團。
- 只用法人關係，不用同名的個人董事長（同名同姓會誤連；個人姓名也不存）。
- 集團名稱＝最上面那個法人。
- 管理員指定過的公司（group_manual）不參與自動歸戶；管理員建立的集團（manual）重算時不動。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Count, Q, QuerySet, Sum
from npofile_crawler.donors import identity_key

from . import period
from .models import CompanyGroup, Donor

MIN_MEMBERS = 2

# 不拿來歸戶的法人董事：名稱沒有「公司」的（機關、基金會、基金）一律不算，另外再擋公股與信託這類
NOT_GROUP_RE = re.compile(
    r"政府|行政院|基金管理會|委員會|國庫|勞動基金|郵政|信託|受託|專戶|財團法人|社團法人|公所|部$|局$"
)
COMPANY_SUFFIX_RE = re.compile(r"(股份)?有限公司$")


def eligible(juristic_name: str) -> bool:
    name = (juristic_name or "").strip()
    return "公司" in name and not NOT_GROUP_RE.search(name)


def short_name(name: str) -> str:
    """畫面上的集團名稱：「富邦金融控股股份有限公司」→「富邦金融控股」。"""
    return COMPANY_SUFFIX_RE.sub("", (name or "").strip()) or name


@dataclass
class Company:
    id: int
    names: tuple[str, ...]  # 清冊上的名稱與登記名稱
    juristic: tuple[dict, ...]  # 法人董監事：{"name", "seats", "shares"}


@dataclass
class Cluster:
    anchor: str
    members: list[int] = field(default_factory=list)


def _rows(juristic) -> list[dict]:
    """舊格式（只存名稱字串）當成一席、持股不明。"""
    return [j if isinstance(j, dict) else {"name": str(j), "seats": 1, "shares": 0} for j in juristic or ()]


def parent_of(juristic) -> str | None:
    """佔最多席的可歸戶法人；同席數比持股；再同就不認（看不出是哪一個）。"""
    rows = [j for j in _rows(juristic) if eligible(j.get("name", ""))]
    if not rows:
        return None
    rank = sorted(rows, key=lambda j: (-int(j.get("seats") or 0), -int(j.get("shares") or 0)))
    top = rank[0]
    if len(rank) > 1 and (rank[1].get("seats"), rank[1].get("shares")) == (top.get("seats"), top.get("shares")):
        return None
    return top["name"].strip()


def build_clusters(companies: list[Company]) -> list[Cluster]:
    """每家公司往上找到最上面的法人，同一個的歸成一群；只回兩家以上的群。純函式，測試直接餵資料。"""
    by_key: dict[str, Company] = {}
    for c in companies:
        for n in c.names:
            if n:
                by_key.setdefault(identity_key(n), c)
    parent_key: dict[int, str | None] = {}
    shown: dict[str, str] = {}
    for c in companies:
        p = parent_of(c.juristic)
        parent_key[c.id] = identity_key(p) if p else None
        if p:
            shown.setdefault(identity_key(p), p)

    def root(c: Company) -> str | None:
        """一路往上：上層是捐款公司就接著看它的上層。繞成一圈（互相持股）時，圈上每家都取同一個（名稱排最前的）。"""
        key = parent_key[c.id]
        path: list[str] = []
        while key is not None:
            if key in path:
                return min(path[path.index(key):])
            path.append(key)
            up = by_key.get(key)
            if up is None or parent_key[up.id] is None:
                return key
            key = parent_key[up.id]
        return None

    members: dict[str, set[int]] = defaultdict(set)
    for c in companies:
        r = root(c)
        if r is None:
            continue
        members[r].add(c.id)
        head = by_key.get(r)
        if head is not None:
            members[r].add(head.id)
    clusters = [
        Cluster(anchor=by_key[k].names[0] if k in by_key else shown[k], members=sorted(ids))
        for k, ids in members.items()
        if len(ids) >= MIN_MEMBERS
    ]
    return sorted(clusters, key=lambda c: c.anchor)


@transaction.atomic
def recompute() -> dict:
    """依每家公司存的法人董監事重新歸戶。回傳統計（給指令印、寫進票）。"""
    auto = Donor.objects.filter(kind=Donor.Kind.COMPANY, group_manual=False)
    companies = [
        Company(id=d["id"], names=(d["name"], d["registered_name"]), juristic=tuple(d["juristic_directors"] or ()))
        for d in auto.exclude(directors_checked_at__isnull=True).values("id", "name", "registered_name", "juristic_directors")
    ]
    clusters = build_clusters(companies)
    existing = {g.anchor: g for g in CompanyGroup.objects.filter(manual=False)}
    keep: set[int] = set()
    assigned: dict[int, int] = {}
    for cl in clusters:
        group = existing.get(cl.anchor)
        if group is None:
            group = CompanyGroup.objects.create(name=cl.anchor, anchor=cl.anchor)
        keep.add(group.pk)
        for donor_id in cl.members:
            assigned[donor_id] = group.pk
    by_group: dict[int, list[int]] = defaultdict(list)
    for donor_id, gid in assigned.items():
        by_group[gid].append(donor_id)
    auto.exclude(pk__in=assigned).exclude(group__isnull=True).update(group=None)
    for gid, ids in by_group.items():
        Donor.objects.filter(pk__in=ids).update(group_id=gid)
    removed, _ = CompanyGroup.objects.filter(manual=False).exclude(pk__in=keep).delete()

    with_juristic = sum(1 for c in companies if any(eligible(j["name"]) for j in _rows(c.juristic)))
    with_any = sum(1 for c in companies if c.juristic)
    return {
        "checked": len(companies),
        "with_juristic_any": with_any,
        "with_juristic": with_juristic,
        "excluded_only": with_any - with_juristic,
        "groups": len(clusters),
        "grouped": len(assigned),
        "removed_groups": removed,
    }


# ---- 前台讀的查詢（可見規則跟 donor_rules 一樣：只算公開的企業、近 5 年）----

def _member_q(prefix: str = "members__") -> Q:
    return Q(**{f"{prefix}kind": Donor.Kind.COMPANY, f"{prefix}hidden": False})


def public_groups() -> QuerySet[CompanyGroup]:
    """有兩家以上公開、近 5 年有捐款的成員才算一個集團。合計＝旗下各公司近 5 年捐款相加。"""
    donation = _member_q() & period.donation_q("members__donations__")
    return (
        CompanyGroup.objects.annotate(
            total=Sum("members__donations__amount", filter=donation),
            member_count=Count("members", filter=donation, distinct=True),
            org_count=Count("members__donations__organization", filter=donation, distinct=True),
            donation_count=Count("members__donations", filter=donation, distinct=True),
        )
        .filter(member_count__gte=MIN_MEMBERS)
    )


def group_members(group: CompanyGroup) -> QuerySet[Donor]:
    from . import donor_rules

    return donor_rules.public_donors().filter(group=group, kind=Donor.Kind.COMPANY).order_by("-total", "name")


def group_label(name: str, member_count: int) -> str:
    return f"{short_name(name)} 等 {member_count} 家"


def donor_group(donor: Donor) -> dict | None:
    """企業頁的「所屬集團」：集團要在前台看得到才寫。"""
    if not donor.group_id:
        return None
    g = public_groups().filter(pk=donor.group_id).first()
    if not g:
        return None
    return {"id": g.pk, "name": g.name, "label": group_label(g.name, g.member_count), "member_count": g.member_count}
