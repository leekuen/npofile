from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _seed_sources(sender, **kwargs):
    from .ingest import ensure_sources

    ensure_sources()


class CrawlingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "crawling"
    verbose_name = "爬蟲與審核"

    def ready(self):
        post_migrate.connect(_seed_sources, sender=self)
