"""法院登記公告重新對組織（LK-31）：組織名冊更新後，之前對不到的公告可能對得到了。"""

from __future__ import annotations

from django.db.models import QuerySet
from npofile_crawler.judicial import CourtMatcher

from .models import CourtRegistration, Organization


def matcher() -> CourtMatcher:
    return CourtMatcher(Organization.objects.values_list("ubn", "name", "city").iterator(chunk_size=5000))


def rematch(queryset: QuerySet | None = None, m: CourtMatcher | None = None) -> int:
    """管理員沒指定過的公告重新比對；回傳組織有變動的筆數。"""
    qs = (queryset if queryset is not None else CourtRegistration.objects.all()).filter(org_manual=False)
    m = m or matcher()
    ubn_to_id = {}
    changed = []
    for reg in qs.only("id", "name", "court", "organization_id").iterator(chunk_size=2000):
        ubn = m.match(reg.name, reg.court)
        if ubn and ubn not in ubn_to_id:
            ubn_to_id[ubn] = Organization.objects.filter(ubn=ubn).values_list("id", flat=True).first()
        org_id = ubn_to_id.get(ubn) if ubn else None
        if org_id != reg.organization_id:
            reg.organization_id = org_id
            changed.append(reg)
    CourtRegistration.objects.bulk_update(changed, ["organization"], batch_size=500)
    return len(changed)
