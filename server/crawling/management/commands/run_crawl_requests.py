import io
import traceback
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from crawling.models import CrawlRequest

# 執行中卻這麼久沒結束：多半是 container 重啟、程式被中斷，標成失敗才不會永遠卡住後面的請求
STALE_AFTER = timedelta(hours=12)
# 執行紀錄只留最後這麼多字
OUTPUT_LIMIT = 20000


class Command(BaseCommand):
    help = "跑後台排入的完整爬取請求（LK-26）。排程每分鐘呼叫一次；沒有請求就什麼都不做，一次只跑一個。"

    def handle(self, *args, **opts):
        now = timezone.now()
        stale = CrawlRequest.objects.filter(status=CrawlRequest.Status.RUNNING, started_at__lt=now - STALE_AFTER)
        for req in stale:
            req.status = CrawlRequest.Status.FAILED
            req.finished_at = now
            req.output = (req.output + "\n中斷：超過 12 小時沒有跑完（container 可能重啟過），請重新排入").strip()
            req.save(update_fields=["status", "finished_at", "output"])

        with transaction.atomic():
            if CrawlRequest.objects.filter(status=CrawlRequest.Status.RUNNING).exists():
                return
            # 不用 skip_locked：兩個程式同時搶時，後到的會等前一個寫成「執行中」，再看就搶不到、直接結束，
            # 不會去拿下一筆、變成同時跑兩個
            req = (
                CrawlRequest.objects.select_for_update()
                .filter(status=CrawlRequest.Status.QUEUED)
                .order_by("requested_at")
                .first()
            )
            if req is None:
                return
            req.status = CrawlRequest.Status.RUNNING
            req.started_at = timezone.now()
            req.save(update_fields=["status", "started_at"])

        keys = list(req.sources.values_list("key", flat=True))
        self.stdout.write(f"完整爬取 #{req.pk} 開始：{', '.join(keys)}")
        out = io.StringIO()
        ok = True
        # 跟每晚的排程一樣：先爬，再清掉近 5 年以外的資料、重算揭露層級
        for name, args in (("crawl", keys), ("prune_old_records", []), ("recompute_scores", [])):
            out.write(f"==> {name} {' '.join(args)}\n")
            try:
                call_command(name, *args, stdout=out, stderr=out)
            except CommandError as e:
                ok = False
                out.write(f"{e}\n")
            except Exception:
                ok = False
                out.write(traceback.format_exc())

        req.status = CrawlRequest.Status.DONE if ok else CrawlRequest.Status.FAILED
        req.finished_at = timezone.now()
        req.output = out.getvalue()[-OUTPUT_LIMIT:]
        req.save(update_fields=["status", "finished_at", "output"])
        self.stdout.write(f"完整爬取 #{req.pk}：{req.get_status_display()}")
