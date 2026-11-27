"""勸募活動的抓取進度：哪些活動這次要抓、抓到哪裡（口徑見 tickets/LK-13）。

規則只寫在這裡：
1. 從沒抓過的活動先抓（新的年度在前）。
2. 列表上的實募金額跟上次檢查時不同 → 重抓（金額變了，清冊多半也更新了）。
3. 還沒有清冊：活動頁有清冊連結（上次下載失敗），或活動結束未滿 12 個月（或還沒結束）→ 每 7 天再看一次。
4. 對不到團體的：每 30 天再試一次（團體可能後來才建）。
其餘不再開頁面。活動列表：今年與明年每次都翻（新活動在這裡），過去的年度 7 天翻一次（看實募金額變了沒）。活動要等資料真的寫進資料庫（flush）才記成已檢查，中途停下的下次會重抓。
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from django.db.models import Max, Q
from django.utils import timezone
from npofile_crawler.mohw import ActivityCard, ActivityPlan

from orgs import period
from orgs.models import Organization

from .models import ActivityProgress, CrawlRecord

RECHECK_EVERY = timedelta(days=7)
WAIT_FOR_LIST = timedelta(days=365)
RETRY_UNMATCHED = timedelta(days=30)
RELIST_PAST_YEARS = timedelta(days=7)
GROUP_SOURCES = ("mohw", "mohw_activities", "mohw_violations")
UPDATE_FIELDS = (
    "ubn", "end_date", "checked_raised", "donors_raised", "has_donor_link", "has_donor_list", "unmatched_reason",
    "checked_at",
)


def priority(row: ActivityProgress, raised: int | None, now, today: date) -> int | None:
    """數字越小越先抓；None＝這次不抓。"""
    if row.checked_at is None:
        return 0
    if row.unmatched_reason:
        return 3 if now - row.checked_at >= RETRY_UNMATCHED else None
    if raised != row.checked_raised:
        return 1
    if not row.has_donor_list and now - row.checked_at >= RECHECK_EVERY:
        if row.has_donor_link or row.end_date is None or today - row.end_date < WAIT_FOR_LIST:
            return 2
    return None


def known_group_ubns() -> dict[str, str]:
    """團體名稱 → 統編：之前對到過的活動，加上團體頁抓過的組織（同名對到不同統編的不算，改用查詢）。"""
    pairs: set[tuple[str, str]] = set(
        ActivityProgress.objects.exclude(ubn="").values_list("org_name", "ubn").distinct()
    )
    pairs |= set(
        CrawlRecord.objects.filter(kind="org", source__key__in=GROUP_SOURCES)
        .values_list("payload__name", "ubn").distinct()
    )
    names = Counter(name for name, _ in pairs)
    unique = {name: ubn for name, ubn in pairs if name and names[name] == 1}
    existing: set[str] = set()
    ubns = sorted(set(unique.values()))
    for i in range(0, len(ubns), 900):
        existing |= set(Organization.objects.filter(ubn__in=ubns[i : i + 900]).values_list("ubn", flat=True))
    return {name: ubn for name, ubn in unique.items() if ubn in existing}


class DbActivityPlan(ActivityPlan):
    def __init__(self):
        self.rows: dict[str, ActivityProgress] = {}
        self.dirty: set[str] = set()
        self.groups: dict[str, str] | None = None
        self.this_roc = timezone.localdate().year - 1911

    def should_list(self, year: int) -> bool:
        """今年、明年每次都翻（新活動在這裡出現）；過去的年度 7 天翻一次，看實募金額有沒有變。"""
        if year >= self.this_roc:
            return True
        last = ActivityProgress.objects.filter(roc_year=year).aggregate(m=Max("listed_at"))["m"]
        return last is None or timezone.now() - last >= RELIST_PAST_YEARS

    def stored_cards(self, year: int) -> list[ActivityCard]:
        return [
            ActivityCard(aid=r.activity_id, name=r.name, org_name=r.org_name, raised=r.listed_raised, year=r.roc_year)
            for r in ActivityProgress.objects.filter(roc_year=year).order_by("activity_id")
        ]

    def select(self, cards: list[ActivityCard], listed: bool = True) -> list[ActivityCard]:
        self._sync_listing(cards, listed)
        if self.groups is None:
            self.groups = known_group_ubns()
        now, today = timezone.now(), timezone.localdate()
        ranked = []
        for order, card in enumerate(cards):
            p = priority(self.rows[card.aid], card.raised, now, today)
            if p is not None:
                ranked.append((p, order, card))
        return [card for _, _, card in sorted(ranked, key=lambda t: t[:2])]

    def _sync_listing(self, cards: list[ActivityCard], listed: bool) -> None:
        ids = [c.aid for c in cards]
        for i in range(0, len(ids), 900):
            self.rows.update(ActivityProgress.objects.in_bulk(ids[i : i + 900], field_name="activity_id"))
        if not listed:
            return  # 卡片是上次記下的，不用回寫
        now = timezone.now()
        new, changed = [], []
        for c in cards:
            row = self.rows.get(c.aid)
            values = {"name": c.name[:300], "org_name": c.org_name[:200], "roc_year": c.year, "listed_raised": c.raised,
                      "listed_at": now}
            if row is None:
                new.append(ActivityProgress(activity_id=c.aid, **values))
            else:
                for k, v in values.items():
                    setattr(row, k, v)
                changed.append(row)
        ActivityProgress.objects.bulk_create(new, batch_size=500, ignore_conflicts=True)
        ActivityProgress.objects.bulk_update(changed, ["name", "org_name", "roc_year", "listed_raised", "listed_at"],
                                             batch_size=500)
        if new:
            for i in range(0, len(ids), 900):
                self.rows.update(ActivityProgress.objects.in_bulk(ids[i : i + 900], field_name="activity_id"))

    def ubn_for(self, org_name: str) -> str | None:
        return self.groups.get(org_name)

    def need_donors(self, card: ActivityCard) -> bool:
        row = self.rows[card.aid]
        return not row.has_donor_list or card.raised != row.donors_raised

    def done(self, card: ActivityCard, ubn: str, *, end_date, has_donor_link: bool, donors_fetched: bool) -> None:
        row = self.rows[card.aid]
        row.ubn, row.end_date, row.has_donor_link = ubn, end_date, has_donor_link
        row.checked_raised, row.unmatched_reason, row.checked_at = card.raised, "", timezone.now()
        if donors_fetched:
            row.has_donor_list, row.donors_raised = True, card.raised
        self.groups[card.org_name] = ubn
        self.dirty.add(card.aid)

    def unmatched(self, card: ActivityCard, reason: str) -> None:
        row = self.rows[card.aid]
        row.unmatched_reason, row.checked_at = reason[:100], timezone.now()
        self.dirty.add(card.aid)

    def flush(self) -> None:
        """前面產生的資料已經寫進資料庫了，才把對應的活動記成已檢查。"""
        if not self.dirty:
            return
        ActivityProgress.objects.bulk_update([self.rows[a] for a in self.dirty], UPDATE_FIELDS, batch_size=500)
        self.dirty.clear()


def summary(since_roc: int | None = None) -> dict[str, int]:
    """近 5 年活動的進度：已抓＋還沒抓＋對不到＝活動數。"""
    qs = ActivityProgress.objects.filter(roc_year__gte=since_roc or period.since_roc_year())
    unmatched = ~Q(unmatched_reason="")
    return {
        "total": qs.count(),
        "done": qs.filter(checked_at__isnull=False, unmatched_reason="").count(),
        "with_list": qs.filter(has_donor_list=True).count(),
        "pending": qs.filter(checked_at__isnull=True).count(),
        "unmatched": qs.filter(unmatched).count(),
    }


def summary_text(since_roc: int | None = None) -> str:
    s = summary(since_roc)
    return (f"近 5 年活動 {s['total']:,} 個，已抓 {s['done']:,} 個（有清冊 {s['with_list']:,} 份），"
            f"還沒抓 {s['pending']:,} 個，對不到 {s['unmatched']:,} 個")
