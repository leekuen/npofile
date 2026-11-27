from django.apps import AppConfig


class OrgsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "orgs"
    verbose_name = "組織資料"

    def ready(self):
        from . import signals  # noqa: F401
