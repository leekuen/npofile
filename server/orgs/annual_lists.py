"""財團法人年度捐贈名單清冊的去重（LK-48，口徑見 tickets/LK-48〈數字口徑〉）。

同一筆錢可能出現在好幾份清冊：A 的支付清冊寫「捐給 B 50 萬」，B 的接受清冊也寫「A 捐 50 萬」，
衛福部勸募清冊上也可能有同一筆。同一年、同一對（捐款者、受捐組織）、同金額只算一次，留哪一筆的順序：
衛福部清冊（有日期、有收據）＞接受清冊（受捐組織自己列的）＞支付清冊。沒留下的標 duplicate，period.donation_q 一律不算。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from django.db.models.functions import ExtractYear

from .models import AnnualDonorList, Donation

RANK_MOHW, RANK_RECEIVE, RANK_PAY = 0, 1, 2


def _rank(direction: str | None) -> int:
    return RANK_MOHW if direction is None else (RANK_RECEIVE if direction == AnnualDonorList.Direction.RECEIVE else RANK_PAY)


def mark_duplicates(org_ids: Iterable[int]) -> int:
    """重算這些受捐組織的年度清冊捐款有沒有重複；回傳標成重複的筆數。衛福部清冊的捐款本身永遠不標。"""
    org_ids = set(org_ids)
    if not org_ids:
        return 0
    annual = list(
        Donation.objects.filter(organization_id__in=org_ids, annual_list__isnull=False, donor__isnull=False)
        .values("id", "organization_id", "donor_id", "year", "amount", "annual_list__direction", "duplicate")
    )
    if not annual:
        return 0
    groups: dict[tuple, list[tuple[int, int, bool]]] = defaultdict(list)  # key → [(順位, id, 目前 duplicate)]
    for d in annual:
        key = (d["organization_id"], d["donor_id"], d["year"], d["amount"])
        groups[key].append((_rank(d["annual_list__direction"]), d["id"], d["duplicate"]))
    # 衛福部清冊：同一年（捐款日期的西元年換民國）同一對同金額
    mohw = (
        Donation.objects.filter(organization_id__in=org_ids, annual_list__isnull=True, project__isnull=False,
                                donor__isnull=False, donated_on__isnull=False)
        .annotate(y=ExtractYear("donated_on"))
        .values_list("organization_id", "donor_id", "y", "amount")
    )
    for org_id, donor_id, y, amount in mohw:
        key = (org_id, donor_id, y - 1911, amount)
        if key in groups:
            groups[key].append((RANK_MOHW, 0, False))
    dup_ids, keep_ids = [], []
    for rows in groups.values():
        rows.sort()
        # 同一份清冊上同一位同金額的兩列是兩筆真的捐款，不互相去重：只拿「比自己順位高的另一種清冊」來比
        best = rows[0][0]
        for rank, pk, is_dup in rows:
            if pk == 0:
                continue
            should = rank > best
            if should != is_dup:
                (dup_ids if should else keep_ids).append(pk)
    if dup_ids:
        Donation.objects.filter(id__in=dup_ids).update(duplicate=True)
    if keep_ids:
        Donation.objects.filter(id__in=keep_ids).update(duplicate=False)
    return Donation.objects.filter(organization_id__in=org_ids, duplicate=True).count()
