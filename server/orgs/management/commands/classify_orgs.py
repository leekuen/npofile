from django.core.management.base import BaseCommand

from orgs.categorize import categorize


class Command(BaseCommand):
    help = "依分類規則重算所有組織的領域與服務對象（管理員指定或拿掉的不動）"

    def handle(self, *args, **opts):
        s = categorize()
        self.stdout.write(f"新增 {s['added']}、移除 {s['removed']}、改來源 {s['changed']} 筆分類")
