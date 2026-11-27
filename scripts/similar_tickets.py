#!/usr/bin/env python3
"""開新票時列出標題相近的既有票（框架 v5.2.0）：只提醒、不擋。

用法：<票檔名一行一個> | python3 scripts/similar_tickets.py "<新票短題>" "<新票號>"
檔名可以帶路徑（tickets/LK-19-政府補助….md），同一張票出現在好幾條分支只算一次。

為什麼：多條 session 同時開票，票號不會撞（new-ticket 會先問遠端），但**內容**會撞——
「政府補助：加上勞動部」與「政府補助：衛福部…」、一張大票的一部分被另一張票做掉卻沒人回頭標。
比對用中文兩字一組（bigram）：共用兩組以上、而且佔新標題的兩成以上才列，避免「協會」「計畫」這種常見詞洗版。
"""

from __future__ import annotations

import re
import sys

PUNCT = re.compile(r"[\s\-_:：、，,。．.（）()「」『』/／【】\[\]！!？?＋+·・]+")
# 標題裡太常見、單獨共用不代表同一件事的兩字組
COMMON = {"功能", "頁面", "畫面", "資料", "顯示", "管理", "修正", "調整", "新增", "改版", "支援"}


def bigrams(text: str) -> set[str]:
    parts = [p for p in PUNCT.split(text) if p]
    grams: set[str] = set()
    for p in parts:
        if re.fullmatch(r"[A-Za-z0-9]+", p):
            if len(p) >= 3:
                grams.add(p.lower())
            continue
        grams |= {p[i : i + 2] for i in range(len(p) - 1)}
    return grams - COMMON


def parse(name: str) -> tuple[str, str] | None:
    base = name.strip().split("/")[-1]
    m = re.match(r"^([A-Za-z]+-\d+)-(.+?)(\.md)?$", base)
    return (m.group(1), m.group(2)) if m else None


def similar(title: str, new_id: str, names: list[str], limit: int = 5) -> list[tuple[str, str, int]]:
    mine = bigrams(title)
    if not mine:
        return []
    seen: dict[str, str] = {}
    for n in names:
        parsed = parse(n)
        if parsed and parsed[0] != new_id:
            seen.setdefault(parsed[0], parsed[1])
    hits = []
    for tid, t in seen.items():
        shared = len(mine & bigrams(t))
        if shared >= 2 and shared / len(mine) >= 0.2:
            hits.append((tid, t, shared))
    hits.sort(key=lambda h: (-h[2], h[0]))
    return hits[:limit]


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    hits = similar(sys.argv[1], sys.argv[2], sys.stdin.read().splitlines())
    if hits:
        print("[new-ticket] ⚠️ 標題相近的既有票（先看是不是同一件事，或該接在舊票上；舊大票被拆做的部分記得回頭標）：")
        for tid, t, _ in hits:
            print(f"    {tid}  {t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
