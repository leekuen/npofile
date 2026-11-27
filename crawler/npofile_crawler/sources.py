"""來源登記表：後端只透過這裡認識有哪些來源。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from . import fia, mohw
from .http import PoliteClient
from .items import Item


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    url: str
    official: bool
    fetch: Callable[[PoliteClient, int | None], Iterator[Item]]


SOURCES = {
    s.key: s
    for s in (
        Source("fia", fia.SOURCE_NAME, fia.SOURCE_URL, True, fia.fetch),
        Source("mohw", mohw.SOURCE_NAME, mohw.BASE + "/app39/", True, mohw.fetch),
    )
}
