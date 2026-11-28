"""上市櫃公司 ESG 寫入與對捐款人（LK-39，口徑見 tickets/LK-39）。

- 寫入：一家公司一個報告年度一筆，(市場, 代號, 年度) 相同就更新。內容照公司申報原值，不走審核
  （跟商工登記一樣，是政府公開的申報資料）。
- 對捐款人：只對企業類捐款人。捐款人有統編 → 只用統編對；沒有統編 → 公司全名的比對寫法（identity_key）相同才對。
  管理員解除過的公司（任一年度 link_blocked）不再自動對。
- 前台只顯示最新一個報告年度。
"""

from __future__ import annotations

from django.db import transaction
from npofile_crawler.donors import identity_key

from .models import CompanyESG, Donor

DATA_FIELDS = (
    "name", "short_name", "ubn", "website", "published_on",
    "scope1", "scope1_verified", "scope2", "scope2_verified", "scope3", "scope3_verified",
    "renewable_ratio", "female_manager_ratio", "salary_median",
    "climate_governance", "climate_strategy", "climate_actions", "transition_plan", "climate_targets", "source_name", "source_url",
)


def store(records: list[dict]) -> tuple[int, int]:
    """回傳（新增, 更新）筆數。同一份跑兩次結果一樣。"""
    created = updated = 0
    blocked = set(CompanyESG.objects.filter(link_blocked=True).values_list("market", "code"))
    with transaction.atomic():
        for rec in records:
            defaults = {f: rec.get(f) if rec.get(f) is not None else _blank(f) for f in DATA_FIELDS}
            obj, was_created = CompanyESG.objects.update_or_create(
                market=rec["market"], code=rec["code"], report_year=rec["report_year"], defaults=defaults
            )
            if was_created and (obj.market, obj.code) in blocked:
                obj.link_blocked = True
                obj.save(update_fields=["link_blocked"])
            created += was_created
            updated += not was_created
    return created, updated


def _blank(field: str):
    """數字欄沒填存 None，文字欄存空字串。"""
    f = CompanyESG._meta.get_field(field)
    return None if f.null else ""


def link_donors() -> int:
    """重新對一次所有公司（沒被解除的）。回傳對到的筆數。"""
    companies = Donor.objects.filter(kind=Donor.Kind.COMPANY)
    by_ubn = {}
    for pk, ubn in companies.exclude(ubn="").values_list("pk", "ubn"):
        by_ubn.setdefault(ubn, pk)
    by_name = dict(companies.filter(ubn="").values_list("name_key", "pk"))
    linked = 0
    with transaction.atomic():
        for esg in CompanyESG.objects.filter(link_blocked=False):
            donor_id = by_ubn.get(esg.ubn) if esg.ubn else None
            if donor_id is None:
                donor_id = by_name.get(identity_key(esg.name))
            if esg.donor_id != donor_id:
                esg.donor_id = donor_id
                esg.save(update_fields=["donor"])
            linked += donor_id is not None
    return linked


def unlink(queryset) -> int:
    """管理員解除對應：同一家公司的每個年度都解除並擋住，重抓也不接回。"""
    keys = set(queryset.values_list("market", "code"))
    n = 0
    for market, code in keys:
        n += CompanyESG.objects.filter(market=market, code=code).update(donor=None, link_blocked=True)
    return n


def latest_for(donor: Donor) -> CompanyESG | None:
    return donor.esg_reports.filter(link_blocked=False).order_by("-report_year", "-published_on").first()
