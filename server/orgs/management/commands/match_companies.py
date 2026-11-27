from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F, Sum
from django.utils import timezone
from npofile_crawler import gcis
from npofile_crawler.http import PoliteClient

from orgs.models import Donor


class Command(BaseCommand):
    help = "用經濟部商工登記查企業捐款人的統一編號（只接受名稱完全相同的公司；查過的不重查；捐得多的先查）"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=200, help="這次最多查幾家")
        parser.add_argument("--recheck", action="store_true", help="查過但沒對到的也重查")

    def handle(self, *args, limit, recheck, **opts):
        qs = Donor.objects.filter(kind=Donor.Kind.COMPANY, ubn="", name__contains="公司")
        if not recheck:
            qs = qs.filter(registry_checked_at__isnull=True)
        matched = checked = 0
        with PoliteClient(min_interval=settings.CRAWLER_MIN_INTERVAL) as client:
            # 捐得多的先查：排程每晚有上限，集團歸戶（LK-23）最需要的是大額捐款企業
            qs = qs.annotate(given=Sum("donations__amount")).order_by(F("given").desc(nulls_last=True), "pk")
            for donor in qs[:limit]:
                hit = gcis.lookup(client, donor.name)
                donor.registry_checked_at = timezone.now()
                if hit:
                    for field in ("ubn", "registered_name", "representative", "capital", "address"):
                        setattr(donor, field, hit[field] or getattr(donor, field))
                    matched += 1
                donor.save()
                checked += 1
        self.stdout.write(f"查了 {checked} 家，對到 {matched} 家")
