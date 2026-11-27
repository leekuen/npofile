"""集團歸戶的規則只寫在這裡（口徑見 tickets/LK-23）。

- 公司 A 的董監事裡有代表法人出任的（法人名稱含「公司」）→ A 跟那個法人同一群；
  兩家公司共用同一個法人董事 → 同一群；法人董事本身就是另一家捐款公司 → 也同一群。
- 政府機關、國發基金、勞動基金、郵政、信託專戶、財團法人／社團法人這類法人董事不算：
  它們在很多公司都有席次，不代表同一個集團。
- 只用法人關係，不用同名的個人董事長（同名同姓會誤連；個人姓名也不存）。
- 集團名稱＝群裡被最多公司共用的法人（同票數取名字短的、再依筆劃順序）。
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
    juristic: tuple[str, ...]  # 法人董監事名稱


@dataclass
class Cluster:
    anchor: str
    members: list[int] = field(default_factory=list)


def build_clusters(companies: list[Company]) -> list[Cluster]:
    """把公司依法人董事連成群；只回兩家以上的群。純函式，測試直接餵資料。"""
    parent: dict[tuple, tuple] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    by_key: dict[str, int] = {}
    for c in companies:
        for n in c.names:
            if n:
                by_key.setdefault(identity_key(n), c.id)
    shown: dict[str, str] = {}  # 法人的比對用名稱 → 第一次看到的寫法
    for c in companies:
        node = ("c", c.id)
        find(node)
        for j in c.juristic:
            if not eligible(j):
                continue
            key = identity_key(j)
            shown.setdefault(key, j.strip())
            union(node, ("j", key))
            other = by_key.get(key)
            if other is not None and other != c.id:
                union(node, ("c", other))

    comps: dict[tuple, list[int]] = defaultdict(list)
    for c in companies:
        comps[find(("c", c.id))].append(c.id)

    own_key = {c.id: {identity_key(n) for n in c.names if n} for c in companies}
    juristic_of = {c.id: {identity_key(j) for j in c.juristic if eligible(j)} for c in companies}
    clusters = []
    for ids in comps.values():
        if len(ids) < MIN_MEMBERS:
            continue
        votes: dict[str, int] = defaultdict(int)
        for i in ids:
            for key in juristic_of[i]:
                votes[key] += 1
        for i in ids:  # 群裡的法人董事本身就是成員之一（母公司）：自己也算一票
            for key in own_key[i]:
                if key in votes:
                    votes[key] += 1
        anchor_key = min(votes, key=lambda k: (-votes[k], len(shown[k]), shown[k]))
        clusters.append(Cluster(anchor=shown[anchor_key], members=sorted(ids)))
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

    with_juristic = sum(1 for c in companies if any(eligible(j) for j in c.juristic))
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
