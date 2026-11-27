from django.core.management.base import BaseCommand
from django.db import transaction

from crawling.models import ActivityProgress, CrawlRecord
from orgs import period
from orgs.models import AnnualFundraising, Donation, FinancialReport, Grant, Organization, Project
from orgs.signals import suspend_scoring
from orgs.scoring import recompute


class Command(BaseCommand):
    help = "刪掉近 5 年以前的年度募款、專案（連同捐款與清冊摘要）、手動捐款、政府補助與財報；裁罰一律不刪"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="只算會刪幾筆，不刪")

    def handle(self, *args, dry_run, **opts):
        since = period.since_roc_year()
        annual = AnnualFundraising.objects.exclude(period.annual_q())
        projects = Project.objects.exclude(period.project_q())
        donations = Donation.objects.exclude(period.donation_q())
        grants = Grant.objects.exclude(period.grant_q())  # 政府補助（LK-19）
        reports = FinancialReport.objects.exclude(period.financial_q())  # 組織財報（LK-25）
        # 舊清冊的原始內容也很佔空間；只刪清冊，團體頁其他紀錄留作歷史
        old_ids = list(projects.values_list("external_id", flat=True))
        records = CrawlRecord.objects.filter(kind="donor_list", external_id__in=old_ids) if old_ids else CrawlRecord.objects.none()
        progress = ActivityProgress.objects.filter(roc_year__lt=since)  # 舊活動的抓取進度（LK-13）
        counts = {
            "年度募款": annual.count(),
            "專案": projects.count(),
            "捐款紀錄": donations.count(),
            "政府補助": grants.count(),
            "財報": reports.count(),
            "清冊原始紀錄": records.count(),
            "活動抓取進度": progress.count(),
        }
        summary = "、".join(f"{k} {v} 筆" for k, v in counts.items())
        if dry_run:
            self.stdout.write(f"（試算）民國 {since} 年以前：{summary}")
            return
        touched = set(annual.values_list("organization_id", flat=True)) | set(projects.values_list("organization_id", flat=True))
        with transaction.atomic(), suspend_scoring():
            donations.delete()
            grants.delete()
            reports.delete()
            projects.delete()
            annual.delete()
            records.delete()
            progress.delete()
        recompute(Organization.objects.filter(pk__in=touched))
        self.stdout.write(f"已刪除民國 {since} 年以前：{summary}；裁罰紀錄不動")
