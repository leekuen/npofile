from django.core.management.base import BaseCommand
from npofile_crawler.donors import ANONYMOUS, classify

from orgs.models import Donor


class Command(BaseCommand):
    help = "依最新的名稱規則重新分類捐款人（管理員指定過類型的不動；新規則判成匿名的也不動，交給管理員隱藏）"

    def handle(self, *args, **opts):
        changed = 0
        for donor in Donor.objects.filter(kind_manual=False).iterator():
            kind = classify(donor.name)
            if kind != ANONYMOUS and kind != donor.kind:
                donor.kind = kind
                donor.save(update_fields=["kind"])
                changed += 1
        self.stdout.write(f"重新分類了 {changed} 位捐款人")
