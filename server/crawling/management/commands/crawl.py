from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from npofile_crawler import mohw
from npofile_crawler.http import PoliteClient
from npofile_crawler.sources import SOURCES

from crawling.ingest import ensure_sources, run_source
from crawling.models import CrawlerSource, CrawlRun
from orgs import period


def recent_success_days(source: CrawlerSource) -> int | None:
    """設了 every_days 的來源（每月檢查的名冊，LK-32）：上次成功距今還不到 every_days 天就回傳隔了幾天，否則 None。"""
    src = SOURCES.get(source.key)
    if not (src and src.every_days):
        return None
    last = source.runs.filter(status=CrawlRun.Status.SUCCESS).order_by("-started_at").first()
    if last is None:
        return None
    days = (timezone.now() - last.started_at).days
    return days if days < src.every_days else None


class Command(BaseCommand):
    help = "執行爬蟲：crawl fia｜crawl mohw --limit 20｜crawl all"

    def add_arguments(self, parser):
        parser.add_argument("sources", nargs="+", help="來源代號（fia、mohw）或 all")
        parser.add_argument("--limit", type=int, default=None, help="最多抓幾筆（覆蓋後台設定）")
        parser.add_argument("--force", action="store_true", help="停用的來源、每月檢查還沒到期的也照跑")
        parser.add_argument(
            "--group", action="append", default=[],
            help="只抓指定的公益勸募團體編號（網址 fundgroupDetails/ 後面的數字，可重複；限 mohw_activities）",
        )

    def handle(self, *args, sources, limit, force, group, **opts):
        ensure_sources()
        qs = CrawlerSource.objects.all() if sources == ["all"] else CrawlerSource.objects.filter(key__in=sources)
        missing = set(sources) - {"all"} - set(qs.values_list("key", flat=True))
        if missing:
            raise CommandError(f"不認得的來源：{', '.join(sorted(missing))}")
        failed = False
        for source in qs:
            if not source.enabled and not force:
                self.stdout.write(f"略過（已停用）：{source.name}")
                continue
            if sources == ["all"] and not force and (days := recent_success_days(source)) is not None:
                self.stdout.write(f"略過（{days} 天內檢查過，每 {SOURCES[source.key].every_days} 天檢查一次）：{source.name}")
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
            try:
                run = run_source(source, limit=limit, items=items, min_interval=settings.CRAWLER_MIN_INTERVAL)
            finally:
                if client is not None:
                    client.close()
            self.stdout.write(
                f"{run.get_status_display()}：抓到 {run.fetched}、新資料 {run.created}、上架 {run.applied}、"
                f"待審核 {run.pending}、失敗 {run.failed}" + (f"\n錯誤：{run.error}" if run.error else "")
                + (f"\n{run.note}" if run.note else "")
            )
            failed |= run.status != run.Status.SUCCESS
            # 每次都是整批重抓、比對後才決定哪些是新的，所以「成功卻一筆都沒抓到」幾乎都是來源網站改版、
            # 解析不到東西。不當成成功，排程才會發通知（LK-12）。
            # 例外：勸募活動只抓新的與有變的（LK-13），補齊後某晚一筆都不用抓是正常的，改看活動列表有沒有讀到卡片。
            listed = getattr(run, "listed_cards", None)
            nothing = listed == 0 if listed is not None else run.fetched == 0
            if run.status == run.Status.SUCCESS and nothing and limit != 0:
                self.stderr.write(f"警告：{source.name} 一筆都沒抓到，來源網站可能改版或暫時沒有回應")
                failed = True
        if failed:
            raise CommandError("有來源執行失敗，看上面的錯誤或後台的執行紀錄")
