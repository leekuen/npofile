"""同一位捐款人的不同寫法合成一筆（規則見 tickets/LK-16；比對規則本身在 npofile_crawler.donors.identity_key）。

資料庫更新（migration 0006）與 `merge_donors` 指令共用這支，所以只用傳進來的 model、只用 update／delete，不依賴 Donor.save()。
"""

from __future__ import annotations

from collections import defaultdict

from django.db import transaction
from django.db.models import Count
from npofile_crawler.donors import identity_key, normalize

REGISTRY_FIELDS = ("ubn", "registered_name", "representative", "capital", "address", "registry_checked_at")


def _keep_order(donor, donation_count: dict[int, int]):
    """保留哪一筆的名稱：管理員指定過類型的 → 有統一編號的 → 捐款筆數多的 → 先建的。"""
    return (not donor.kind_manual, not donor.ubn, -donation_count.get(donor.pk, 0), donor.pk)


@transaction.atomic
def merge_donors(Donor, Donation) -> dict[str, int]:
    donors = list(Donor.objects.all())
    counts = dict(Donation.objects.filter(donor__isnull=False).values_list("donor").annotate(n=Count("id")))
    groups: dict[str, list] = defaultdict(list)
    for d in donors:
        groups[identity_key(d.name)[:200]].append(d)

    merged = renamed = 0
    for key, members in groups.items():
        members.sort(key=lambda d: _keep_order(d, counts))
        keep, others = members[0], members[1:]
        changes: dict = {}
        if others:
            other_ids = [d.pk for d in others]
            Donation.objects.filter(donor_id__in=other_ids).update(donor_id=keep.pk)
            if any(d.hidden for d in members) and not keep.hidden:
                changes["hidden"] = True  # 寧可少顯示：任一筆被隱藏，合併後就隱藏
            if not keep.ubn:
                source = next((d for d in others if d.ubn), None)
                if source is not None:
                    changes.update({f: getattr(source, f) for f in REGISTRY_FIELDS})
            Donor.objects.filter(pk__in=other_ids).delete()
            merged += len(others)
        name = normalize(keep.name)[:200]
        if name != keep.name:
            changes["name"] = name
            renamed += 1
        if key != keep.name_key:
            changes["name_key"] = key
        if changes:
            Donor.objects.filter(pk=keep.pk).update(**changes)
    return {"merged": merged, "renamed": renamed, "donors": len(groups)}
