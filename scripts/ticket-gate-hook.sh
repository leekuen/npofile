#!/usr/bin/env bash
# PreToolUse hook：「無票不開發」的機制化閘門。
# 當 agent 要 Edit/Write 產品程式碼（PRODUCT_DIRS，見 scripts/framework-config.sh）時，
# 檢查 tickets/ 是否存在「待開發 / 開發中」的功能票；沒有就擋下（exit 2）。
# 由 .claude/settings.json 的 hooks.PreToolUse 呼叫。
#
# 工作區（源專案 v4.76.0）：開發規定在 .claude/worktrees/<名稱>/ 裡做。先把那段路徑去掉再判斷，
# 否則從主目錄開的 session 寫工作區的檔案時，路徑對不上任何產品目錄，一律放行——
# 這種洞不會報錯，只會安靜地什麼都不擋（由 scripts/worktree-gates-test.sh 釘住）。
#   - 工作區名稱是票號（make worktree n=<票號> 開的）→ 看**那一張票**是不是待開發／開發中；
#   - 名稱不是票號（harness 自動開的、或一次做多張的）→ 退回舊規則
#     「全站有任何待開發／開發中的票就放行」（擋下會卡死正在跑的別條 session，
#     而這類工作區沒有可以對照的單一票）。
# 邊界（誠實聲明）：舊規則那一支只能檢查「有沒有可開發的票」，無法判斷本次修改屬於哪張票。
set -uo pipefail
# Windows（Git Bash/MSYS）上 `pwd` 回傳 posix 式路徑（/c/...），但 harness 傳進來的
# file_path 是 Windows 式（C:\...）；兩邊比對不上，閘門會整個不擋（已實測釘住，見
# worktree-gates-test.sh）。`pwd -W` 在 Git Bash 上印 Windows 式路徑，非 Windows 平台
# 這個選項不存在、指令會失敗，退回原本的 `pwd`。
ROOT="$(cd "$(dirname "$0")/.." && { pwd -W 2>/dev/null || pwd; })"
# 先給預設值再讀設定：設定檔沒有這個變數（從舊版升級、還沒補）時，開了 set -u 的 bash 3.2
# 連取陣列長度都會報 unbound variable——閘門會變成每次寫檔都噴一行錯誤、卻什麼都不擋。
PRODUCT_DIRS=()
[ -f "$ROOT/scripts/framework-config.sh" ] && . "$ROOT/scripts/framework-config.sh"

# 先把 stdin 讀完再做任何判斷：還沒讀就結束，送資料進來的那一端會收到 broken pipe
FILE_PATH=$(python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
ti = d.get("tool_input") or {}
print(ti.get("file_path") or ti.get("notebook_path") or "")
' 2>/dev/null || true)
# 同一個理由：Windows 式路徑用反斜線，下面所有 case 樣式與字首比對都假設正斜線。
FILE_PATH="${FILE_PATH//\\//}"

# 尚未設定產品目錄（初始化前）→ 閘門不擋
[ ${#PRODUCT_DIRS[@]} -eq 0 ] && exit 0

# 拿不到路徑（非檔案類工具）→ 放行
[ -z "$FILE_PATH" ] && exit 0

# 工作區裡的檔案：把 <…>/.claude/worktrees/<名稱>/ 那段去掉，剩下的才是 repo 內路徑
WT=""
WT_NAME=""
case "$FILE_PATH" in
  */.claude/worktrees/*/*)
    after="${FILE_PATH#*/.claude/worktrees/}"
    WT_NAME="${after%%/*}"
    REL="${after#*/}"
    WT="${FILE_PATH%%/.claude/worktrees/*}/.claude/worktrees/$WT_NAME"
    ;;
  "$ROOT"/*) REL="${FILE_PATH#"$ROOT"/}" ;;
  *) exit 0 ;;
esac

# 只閘產品程式碼目錄；框架檔、docs、tickets、cache、scripts 一律放行
hit=0
for d in "${PRODUCT_DIRS[@]}"; do
  d="${d%/}"
  case "$REL" in
    "$d"/*) hit=1; break ;;
  esac
done
[ "$hit" -eq 0 ] && exit 0

# 紅燈救火豁免：使用者明確同意後 touch cache/hotfix-override（不進 git），
# 修完必須刪除該檔並補票（規則見 AGENTS.md「Ticket 工作流」）。
# 在工作區裡 touch 的也算（agent 的所在目錄常常就是工作區）。
[ -f "$ROOT/cache/hotfix-override" ] && exit 0
[ -n "$WT" ] && [ -f "$WT/cache/hotfix-override" ] && exit 0

# 工作區名稱是票號 → 只看那一張票（票可能還只在主目錄、沒進工作區的分支，兩邊都找）
if printf '%s' "$WT_NAME" | grep -qE '^[A-Z]+[0-9]*-[0-9]+$'; then
  tf=""
  for dir in "$WT/tickets" "$ROOT/tickets"; do
    for f in "$dir/$WT_NAME"-*.md; do
      [ -f "$f" ] && { tf="$f"; break 2; }
    done
  done
  if [ -z "$tf" ]; then
    state="找不到這張票"
  else
    state="$(sed -n 's/^status: *\([^ #]*\).*/\1/p' "$tf" | head -1)"
    case "$state" in 待開發 | 開發中) exit 0 ;; esac
    state="狀態是「${state:-空白}」"
  fi
  cat >&2 <<EOF
[ticket-gate] 無票不開發：這個工作區（${WT_NAME}）對應的票${state}，
產品程式碼（${REL}）的修改已被擋下。
- 同一張票還要繼續改 → 先跟使用者確認，把票的 status 改回「開發中」。
- 是另一件事 → 走 /pm 開新票，再用 make worktree n=<新票號> 開工作區。
- 紅燈救火（不改行為）→ 經使用者明確同意後執行
  \`mkdir -p cache && touch cache/hotfix-override\` 暫時放行；修完刪除該檔。
EOF
  exit 2
fi

# 其他情況（主目錄、名稱不是票號的工作區）→ 舊規則：有任何「待開發 / 開發中」的票就放行
if grep -lE '^status: *(待開發|開發中)' "$ROOT"/tickets/*-*.md >/dev/null 2>&1; then
  exit 0
fi

cat >&2 <<EOF
[ticket-gate] 無票不開發：tickets/ 目前沒有任何「待開發 / 開發中」的功能票，
產品程式碼（${PRODUCT_DIRS[*]}）的修改已被擋下。
- 新功能 / 行為修改 → 先走 /pm 確認角色與目的、開票，再從 /dev 依票開發。
- 紅燈救火（不改行為）→ 經使用者明確同意後執行
  \`mkdir -p cache && touch cache/hotfix-override\` 暫時放行；修完刪除該檔，行為有變要補票。
EOF
exit 2
