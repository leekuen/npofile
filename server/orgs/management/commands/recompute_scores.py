from django.core.management.base import BaseCommand

from orgs import scoring


class Command(BaseCommand):
    help = "重算所有組織的揭露層級與近 5 年公開募款（「近五年」會隨日期移動，建議每天跑一次）"

    def handle(self, *args, **opts):
        self.stdout.write(f"已更新 {scoring.recompute()} 個組織的揭露層級")
