from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from npofile_crawler import judicial, mohw
from npofile_crawler.http import PoliteClient
from npofile_crawler.sources import SOURCES

from crawling.ingest import ensure_sources, org_names, run_source
from crawling.models import CrawlerSource
from orgs import period


class Command(BaseCommand):
    help = "執行爬蟲：crawl fia｜crawl mohw --limit 20｜crawl all｜crawl judicial --archive <整包解壓的資料夾>"

    def add_arguments(self, parser):
        parser.add_argument("sources", nargs="+", help="來源代號（fia、mohw、judicial…）或 all（不含 judicial）")
        parser.add_argument("--limit", type=int, default=None, help="最多抓幾筆（覆蓋後台設定）")
        parser.add_argument("--force", action="store_true", help="停用的來源也照跑")
        parser.add_argument(
            "--group", action="append", default=[],
            help="只抓指定的公益勸募團體編號（網址 fundgroupDetails/ 後面的數字，可重複；限 mohw_activities）",
        )
        parser.add_argument(
            "--archive", default=None,
            help="司法院每月整包裁判書解壓後的資料夾（限 judicial；不連網、不受凌晨時段限制）",
        )

    def handle(self, *args, sources, limit, force, group, archive, **opts):
        ensure_sources()
        if sources == ["all"]:  # 有自己排程的來源（司法院）不跟著 all 跑
            qs = CrawlerSource.objects.exclude(key__in=[k for k, s in SOURCES.items() if not s.in_all])
        else:
            qs = CrawlerSource.objects.filter(key__in=sources)
        missing = set(sources) - {"all"} - set(qs.values_list("key", flat=True))
        if missing:
            raise CommandError(f"不認得的來源：{', '.join(sorted(missing))}")
        failed = False
        for source in qs:
            if not source.enabled and not force:
                self.stdout.write(f"略過（已停用）：{source.name}")
                continue
            self.stdout.write(f"開始：{source.name}")
            items, client = None, None
            if group:
                if source.key != "mohw_activities":
                    raise CommandError("--group 只能搭配 mohw_activities")
                client = PoliteClient(min_interval=settings.CRAWLER_MIN_INTERVAL)
                items = mohw.fetch_activities_for(
                    client, group, settings.DONOR_INDIVIDUAL_THRESHOLD, period.since_roc_year()
                )
            if archive:
                if source.key != "judicial":
                    raise CommandError("--archive 只能搭配 judicial")
                items = judicial.iter_archive(archive, org_names(), limit)
            try:
                run = run_source(source, limit=limit, items=items, min_interval=settings.CRAWLER_MIN_INTERVAL)
            finally:
                if client is not None:
                    client.close()
            self.stdout.write(
                f"{run.get_status_display()}：抓到 {run.fetched}、新資料 {run.created}、上架 {run.applied}、"
                f"待審核 {run.pending}、失敗 {run.failed}" + (f"\n錯誤：{run.error}" if run.error else "")
            )
            failed |= run.status != run.Status.SUCCESS
            # 每次都是整批重抓、比對後才決定哪些是新的，所以「成功卻一筆都沒抓到」幾乎都是來源網站改版、
            # 解析不到東西。不當成成功，排程才會發通知（LK-12）。
            src = SOURCES.get(source.key)
            if run.status == run.Status.SUCCESS and run.fetched == 0 and limit != 0 and not (src and src.may_be_empty):
                self.stderr.write(f"警告：{source.name} 一筆都沒抓到，來源網站可能改版或暫時沒有回應")
                failed = True
        if failed:
            raise CommandError("有來源執行失敗，看上面的錯誤或後台的執行紀錄")
