from django.conf import settings
from django.core.management.base import BaseCommand
from npofile_crawler import judicial
from npofile_crawler.http import PoliteClient

from orgs.court_match import rematch
from orgs.models import CourtRegistration


class Command(BaseCommand):
    help = "法院登記公告重新對組織（管理員指定過的不動），對到了但還沒讀過內頁的補抓內頁（每秒一個請求）"

    def add_arguments(self, parser):
        parser.add_argument("--details", type=int, default=200, help="最多補抓幾篇內頁（0＝不抓）")

    def handle(self, *args, details, **opts):
        n = rematch()
        self.stdout.write(f"重新比對：{n} 筆的組織有變動")
        todo = CourtRegistration.objects.filter(organization__isnull=False, detail_fetched=False).exclude(source_url="")
        done = 0
        if details:
            with PoliteClient(min_interval=settings.CRAWLER_MIN_INTERVAL) as client:
                for reg in todo.order_by("-posted_on")[:details]:
                    d = judicial.fetch_details(client, reg.source_url, reg.case_type)
                    reg.registered_on = d["registered_on"]
                    reg.property_total = d["property_total"]
                    reg.change_items = d["change_items"]
                    reg.detail_fetched = True
                    reg.save(update_fields=["registered_on", "property_total", "change_items", "detail_fetched", "updated_at"])
                    done += 1
        self.stdout.write(f"補抓內頁：{done} 篇（還有 {todo.count()} 篇沒讀）")
