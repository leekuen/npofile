from django.core.management.base import BaseCommand

from orgs.donor_merge import merge_donors
from orgs.models import Donation, Donor


class Command(BaseCommand):
    help = "依最新的名稱規則整理捐款人名稱，同一位的不同寫法（台／臺、空白、(股)…）合成一筆；規則改了之後跑"

    def handle(self, *args, **opts):
        s = merge_donors(Donor, Donation)
        self.stdout.write(f"合併掉 {s['merged']} 筆重複的捐款人、整理了 {s['renamed']} 個名稱；現在共 {s['donors']} 位捐款人")
