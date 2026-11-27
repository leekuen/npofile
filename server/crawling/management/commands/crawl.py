from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from crawling.ingest import ensure_sources, run_source
from crawling.models import CrawlerSource


class Command(BaseCommand):
    help = "執行爬蟲：crawl fia｜crawl mohw --limit 20｜crawl all"

    def add_arguments(self, parser):
        parser.add_argument("sources", nargs="+", help="來源代號（fia、mohw）或 all")
        parser.add_argument("--limit", type=int, default=None, help="最多抓幾筆（覆蓋後台設定）")
        parser.add_argument("--force", action="store_true", help="停用的來源也照跑")

    def handle(self, *args, sources, limit, force, **opts):
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
            self.stdout.write(f"開始：{source.name}")
            run = run_source(source, limit=limit, min_interval=settings.CRAWLER_MIN_INTERVAL)
            self.stdout.write(
                f"{run.get_status_display()}：抓到 {run.fetched}、新資料 {run.created}、上架 {run.applied}、"
                f"待審核 {run.pending}、失敗 {run.failed}" + (f"\n錯誤：{run.error}" if run.error else "")
            )
            failed |= run.status != run.Status.SUCCESS
        if failed:
            raise CommandError("有來源執行失敗，看上面的錯誤或後台的執行紀錄")
