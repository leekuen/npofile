"""組織或它底下的資料一變動就重算揭露指數；爬蟲大量寫入時暫停，寫完再整批重算。"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from . import scoring
from .models import AnnualFundraising, Donation, Organization, Penalty, Project

_suspended: ContextVar[bool] = ContextVar("scoring_suspended", default=False)


@contextmanager
def suspend_scoring():
    token = _suspended.set(True)
    try:
        yield
    finally:
        _suspended.reset(token)


def _refresh(org_id) -> None:
    if _suspended.get() or org_id is None:
        return
    scoring.recompute(Organization.objects.filter(pk=org_id))


@receiver(post_save, sender=Organization)
def _org_saved(sender, instance, raw=False, **kwargs):
    if not raw:
        _refresh(instance.pk)


@receiver([post_save, post_delete], sender=AnnualFundraising)
@receiver([post_save, post_delete], sender=Donation)
@receiver([post_save, post_delete], sender=Project)
@receiver([post_save, post_delete], sender=Penalty)
def _child_changed(sender, instance, raw=False, **kwargs):
    if not raw:
        _refresh(instance.organization_id)
