from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from npofile_crawler import esg
from npofile_crawler.http import PoliteClient

from orgs import company_esg
from orgs.models import CompanyESG


class Command(BaseCommand):
    help = "下載上市櫃公司 ESG 彙總資料（證交所、櫃買中心 OpenAPI），寫入並對到企業捐款人（LK-39；每週排程）"

    def add_arguments(self, parser):
        parser.add_argument("--if-empty", action="store_true", help="已經有資料就不抓（container 啟動時用）")
        parser.add_argument("--link-only", action="store_true", help="不下載，只重新對一次企業捐款人（每天排程用：新抓進來的捐款人不用等週日）")

    def handle(self, *args, if_empty=False, link_only=False, **opts):
        if link_only:
            self.stdout.write(f"對到企業捐款人 {company_esg.link_donors()} 筆")
            return
        if if_empty and CompanyESG.objects.exists():
            self.stdout.write("已經有公司 ESG 資料，略過")
            return
        failed = []
        with PoliteClient(min_interval=settings.CRAWLER_MIN_INTERVAL, timeout=120) as client:
            for market, result in esg.fetch(client):
                if isinstance(result, Exception):
                    failed.append(f"{market.label}：{result}")
                    self.stderr.write(f"{market.label}公司 ESG 下載失敗：{result}")
                    continue
                created, updated = company_esg.store(result)
                self.stdout.write(f"{market.label}：{len(result)} 家（新增 {created}、更新 {updated}）")
        linked = company_esg.link_donors()
        self.stdout.write(f"對到企業捐款人 {linked} 筆")
        if failed:
            raise CommandError("；".join(failed))
