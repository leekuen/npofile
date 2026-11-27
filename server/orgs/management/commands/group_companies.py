from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F, Q, Sum
from django.utils import timezone
from npofile_crawler import gcis
from npofile_crawler.http import PoliteClient

from orgs import groups
from orgs.models import Donor

RECHECK_DAYS = 30


class Command(BaseCommand):
    help = (
        "集團歸戶（LK-23）：查有統編的捐款企業的董監事（每家每月重查一次、捐得多的先查、每秒一個請求），"
        "再依法人董事重新歸戶"
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=500, help="這次最多查幾家的董監事（0＝不查，只重新歸戶）")
        parser.add_argument("--days", type=int, default=RECHECK_DAYS, help="董監事多久重查一次（天）")

    def handle(self, *args, limit, days, **opts):
        due = Q(directors_checked_at__isnull=True) | Q(directors_checked_at__lt=timezone.now() - timedelta(days=days))
        qs = (
            Donor.objects.filter(due, kind=Donor.Kind.COMPANY)
            .exclude(ubn="")
            .annotate(given=Sum("donations__amount"))
            .order_by(F("given").desc(nulls_last=True), "pk")
        )
        checked = 0
        if limit:
            with PoliteClient(min_interval=settings.CRAWLER_MIN_INTERVAL) as client:
                for donor in qs[:limit]:
                    donor.juristic_directors = gcis.juristic_directors(client, donor.ubn)
                    donor.directors_checked_at = timezone.now()
                    donor.save(update_fields=["juristic_directors", "directors_checked_at"])
                    checked += 1
        stats = groups.recompute()
        self.stdout.write(
            f"這次查了 {checked} 家的董監事。已查過 {stats['checked']} 家：有法人董監事 {stats['with_juristic_any']} 家，"
            f"其中 {stats['excluded_only']} 家只有政府、基金、信託這類法人（不拿來歸戶）；"
            f"歸成 {stats['groups']} 個集團、共 {stats['grouped']} 家，拿掉 {stats['removed_groups']} 個已不成立的集團"
        )
