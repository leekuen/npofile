#!/usr/bin/env bash
# PreToolUse hook（matcher: Edit|Write|MultiEdit|NotebookEdit）：「動 UI 前先套 ui-design skill」的機制化閘門。
# 當 agent 要寫入「畫面層檔案」時，檢查本 session 是否已啟動過 ui-design skill
# （由 ui-design-mark-hook.sh 留下的標記）；沒有就擋下（exit 2），要求先套 skill。
# 由 .claude/settings.json 的 hooks.PreToolUse 呼叫。
#
# 「畫面層檔案」＝ scripts/framework-config.sh 的 UI_PATH_GLOBS（每個專案的畫面放哪裡不一樣，
# 所以做成設定；空陣列＝這個專案沒有畫面或還沒決定範圍，閘門不擋）。
# 邊界（誠實聲明）：hook 只能靠路徑判斷，無法真的分辨這次修改是不是「UI 設計」——
# 對畫面層檔案的純邏輯／錯字修正也會被擋。此時經使用者同意後 touch cache/ui-design-override 放行，
# 完事刪除該檔（比照 ticket-gate 的 hotfix-override）。
set -uo pipefail
# Windows（Git Bash/MSYS）上 `pwd` 回傳 posix 式路徑（/c/...），但 harness 傳進來的
# file_path 是 Windows 式（C:\...）；兩邊比對不上，閘門會整個不擋（已實測釘住，見
# worktree-gates-test.sh）。`pwd -W` 在 Git Bash 上印 Windows 式路徑，非 Windows 平台
# 這個選項不存在、指令會失敗，退回原本的 `pwd`。
ROOT="$(cd "$(dirname "$0")/.." && { pwd -W 2>/dev/null || pwd; })"
# 先給預設值再讀設定：設定檔沒有這個變數（從舊版升級、還沒補）時，開了 set -u 的 bash 3.2
# 連取陣列長度都會報 unbound variable——閘門會變成每次寫檔都噴一行錯誤、卻什麼都不擋。
UI_PATH_GLOBS=()
[ -f "$ROOT/scripts/framework-config.sh" ] && . "$ROOT/scripts/framework-config.sh"

# 先把 stdin 讀完再做任何判斷：還沒讀就結束，送資料進來的那一端會收到 broken pipe
read -r -d '' PAYLOAD <<'PYEOF' || true
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
ti = d.get("tool_input") or {}
print(ti.get("file_path") or ti.get("notebook_path") or "")
print((d.get("session_id") or "").strip())
PYEOF

MAPPED=$(python3 -c "$PAYLOAD" 2>/dev/null || true)
FILE_PATH=$(printf '%s\n' "$MAPPED" | sed -n '1p')
SID=$(printf '%s\n' "$MAPPED" | sed -n '2p')
# Windows 式路徑用反斜線，下面所有 case 樣式與字首比對都假設正斜線。
FILE_PATH="${FILE_PATH//\\//}"

# 沒設定畫面層範圍 → 閘門不擋
[ ${#UI_PATH_GLOBS[@]} -eq 0 ] && exit 0

# 拿不到路徑（非檔案類工具）→ 放行
[ -z "$FILE_PATH" ] && exit 0

# 相對 repo 根目錄的路徑。
# 工作區裡的檔案要先把 <…>/.claude/worktrees/<名稱>/ 那段去掉（源專案 v4.76.0）——
# 不去掉的話，從主目錄開的 session 寫工作區的畫面檔，路徑開頭是 .claude/worktrees/…，
# 對不上任何一條樣式就一律放行；而規定的開發方式正是在工作區裡做。
WT=""
case "$FILE_PATH" in
  */.claude/worktrees/*/*)
    after="${FILE_PATH#*/.claude/worktrees/}"
    REL="${after#*/}"
    WT="${FILE_PATH%%/.claude/worktrees/*}/.claude/worktrees/${after%%/*}"
    ;;
  "$ROOT"/*) REL="${FILE_PATH#"$ROOT"/}" ;;
  *) exit 0 ;;   # repo 外的檔案不歸這個閘門管
esac

# override 逃生門：使用者確認「這次不是 UI 設計工作」後暫時放行，事後刪檔。
# 在工作區裡 touch 的也算（agent 的所在目錄常常就是工作區）。
[ -f "$ROOT/cache/ui-design-override" ] && exit 0
[ -n "$WT" ] && [ -f "$WT/cache/ui-design-override" ] && exit 0

# case 的 * 會跨 / 比對整段字串，所以 "web/*.tsx" 涵蓋 web/ 底下任何一層的 .tsx
is_ui=0
for g in "${UI_PATH_GLOBS[@]}"; do
  # shellcheck disable=SC2254
  case "$REL" in
    $g) is_ui=1; break ;;
  esac
done

# 非畫面層檔案 → 放行
[ "$is_ui" = 1 ] || exit 0

# session key（與 mark hook 的算法必須一致）
if [ -n "$SID" ]; then KEY="$SID"; else KEY="day-$(date +%Y%m%d)"; fi

# 本 session 已套過 ui-design skill → 放行
[ -f "$ROOT/cache/.ui-design-ok.$KEY" ] && exit 0

cat >&2 <<EOF
🎨 [ui-design-gate] 動 UI 前先套 ui-design skill：
  你正要寫入畫面層檔案（${REL}），但本 session 還沒啟動過 ui-design skill。
  請先啟動 Skill: ui-design（過一遍通用 UI/UX 檢查清單）再改，避免第一版就有明顯 UI 問題。
  若這次確實不是 UI 設計工作（例如只改字串錯字），經使用者同意後：
    mkdir -p cache && touch cache/ui-design-override   # 放行；完事後 rm cache/ui-design-override
  （哪些路徑算畫面層：scripts/framework-config.sh 的 UI_PATH_GLOBS）
EOF
exit 2
