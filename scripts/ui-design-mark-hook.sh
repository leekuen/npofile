#!/usr/bin/env bash
# PreToolUse hook（matcher: Skill）：偵測「ui-design skill 被啟動」並留下本 session 標記，
# 供 ui-design-gate-hook.sh 判斷「動 UI 前有沒有先套 skill」。
# 由 .claude/settings.json 的 hooks.PreToolUse 呼叫。
# 職責單純：只寫標記 + 印出可視化 banner，永不擋（exit 0）。
# 邊界（誠實聲明）：只認得「透過 Skill 工具啟動 ui-design」這個事實；
# 若用別的方式讀 skill 內容，這裡偵測不到（gate 會擋，需手動套 skill 或用 override）。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

read -r -d '' PAYLOAD <<'PYEOF' || true
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
ti = d.get("tool_input") or {}
skill = (ti.get("skill") or ti.get("name") or "").strip()
sid = (d.get("session_id") or "").strip()
print(skill)
print(sid)
PYEOF

MAPPED=$(python3 -c "$PAYLOAD" 2>/dev/null || true)
SKILL=$(printf '%s\n' "$MAPPED" | sed -n '1p')
SID=$(printf '%s\n' "$MAPPED" | sed -n '2p')

# 只認 ui-design（容許 plugin 前綴，如 foo:ui-design）
case "$SKILL" in
  ui-design|*:ui-design|*/ui-design) ;;
  *) exit 0 ;;
esac

# session key：有 session_id 用它，沒有則退回當日（與 gate 的算法必須一致）
if [ -n "$SID" ]; then KEY="$SID"; else KEY="day-$(date +%Y%m%d)"; fi

mkdir -p "$ROOT/cache" 2>/dev/null || true
touch "$ROOT/cache/.ui-design-ok.$KEY" 2>/dev/null || true

# 可視化：讓「skill 已啟動」在工作過程中看得到
echo "🎨 [ui-design] skill 已啟動 — 本 session 的 UI 編輯閘門已解鎖（畫面層檔案可寫入）。" >&2
exit 0
