"""揭露徽章（口徑見 tickets/LK-42）：給組織貼在官網的小圖，讀組織上存的揭露層級。

不放組織名稱（避免被拿去冒用時看起來像本站替某組織背書）；一定由本站即時產生，組織改不了。
"""

from __future__ import annotations

from html import escape

from .scoring import LEVEL_MEDALS, MAX_LEVEL

LABEL = "NPOFile 揭露層級"
HEIGHT = 20
# 右半邊底色，跟前台 LevelBadge 同色系（web/components/ui.tsx MEDAL_STYLES），選深一階讓白字對比夠
LEVEL_COLORS = {
    0: "#6b7280",  # 未分級：灰
    1: "#b45309",  # 銅
    2: "#52525b",  # 銀
    3: "#a16207",  # 金
    4: "#0369a1",  # 鑽石
}
LABEL_COLOR = "#1e1b4b"  # 左半邊：站上的靛藍主色（brand-950）
MUTED = "#6b7280"
INACTIVE_TEXT = "不分層級"
UNKNOWN_TEXT = "未收錄"


def _text_width(text: str) -> int:
    """估字寬（font-size 11）：中日韓全形 11px、其他 6.5px；SVG 沒辦法量字，估寬一點比切字好。"""
    w = 0.0
    for ch in text:
        w += 11 if ord(ch) > 0x2E80 else 6.5
    return int(round(w))


def status_text(level: int | None, active: bool | None) -> tuple[str, str]:
    """回傳（右半邊文字, 底色）。level/active 是 None 表示本站查無此統編。"""
    if level is None or active is None:
        return UNKNOWN_TEXT, MUTED
    if not active:
        return INACTIVE_TEXT, MUTED
    n = max(0, min(MAX_LEVEL, level))
    return LEVEL_MEDALS[n], LEVEL_COLORS[n]


def render(level: int | None, active: bool | None) -> str:
    value, color = status_text(level, active)
    pad = 6
    lw = _text_width(LABEL) + pad * 2
    vw = _text_width(value) + pad * 2
    total = lw + vw
    title = f"{LABEL}：{value}"
    font = "'Noto Sans TC','PingFang TC','Microsoft JhengHei',Verdana,sans-serif"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="{HEIGHT}" role="img" '
        f'aria-label="{escape(title)}">'
        f"<title>{escape(title)}</title>"
        f'<clipPath id="r"><rect width="{total}" height="{HEIGHT}" rx="4"/></clipPath>'
        f'<g clip-path="url(#r)">'
        f'<rect width="{lw}" height="{HEIGHT}" fill="{LABEL_COLOR}"/>'
        f'<rect x="{lw}" width="{vw}" height="{HEIGHT}" fill="{color}"/>'
        f"</g>"
        f'<g fill="#fff" font-family="{font}" font-size="11" text-anchor="middle">'
        f'<text x="{lw / 2:.1f}" y="14">{escape(LABEL)}</text>'
        f'<text x="{lw + vw / 2:.1f}" y="14" font-weight="bold">{escape(value)}</text>'
        f"</g></svg>"
    )
