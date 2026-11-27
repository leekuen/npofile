#!/usr/bin/env bash
# PreToolUse hook（matcher: Edit|Write|MultiEdit|NotebookEdit）：示意圖交出去之前，
# 把 ui-design「這句話在做什麼工作」那張分類表推到眼前。
#
# 為什麼是這個時點（源專案 v4.47.0）：「多餘文字」是被退回最大宗的一類，而源專案統計過，
# 這類退回有六成發生在示意圖階段。示意圖放在 cache/demos/，而 cache/ 不進版控，
# 任何掃 git diff 的做法永遠看不到它。寫這個檔是整條路徑上唯一一個
# 「大宗缺陷會經過、又真的有檔案事件」的地方。
#
# 邊界（誠實聲明）：這是**提醒**，不是檢查。hook 只能 exit 2 擋下一次工具呼叫，
# 沒有辦法判斷你有沒有照做，也不能代你派 subagent（PreToolUse 發動不了 Agent 工具）。
# 它能保證的只有一件事：**你在寫示意圖的當下，那張表在你眼前**——這類缺陷的成因
# 正是「寫之前沒有先看畫面上已經有什麼」。
# 放行要自己 touch 標記檔，不自動放行：那一行留在紀錄裡，是「表看過了」的痕跡。
set -uo pipefail
# Windows（Git Bash/MSYS）上 `pwd` 回傳 posix 式路徑（/c/...），但 harness 傳進來的
# file_path 是 Windows 式（C:\...）；兩邊比對不上，閘門會整個不擋（已實測釘住，見
# worktree-gates-test.sh）。`pwd -W` 在 Git Bash 上印 Windows 式路徑，非 Windows 平台
# 這個選項不存在、指令會失敗，退回原本的 `pwd`。
ROOT="$(cd "$(dirname "$0")/.." && { pwd -W 2>/dev/null || pwd; })"

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

# 拿不到路徑（非檔案類工具）→ 放行
[ -z "$FILE_PATH" ] && exit 0

# 相對 repo 根目錄的路徑；工作區裡的示意圖（<…>/.claude/worktrees/<名稱>/cache/demos/…）也算——
# 開發規定在工作區裡做，不去掉那段路徑就一張都攔不到（同 ticket-gate／ui-design-gate 的教訓）。
WT=""
case "$FILE_PATH" in
  */.claude/worktrees/*/*)
    after="${FILE_PATH#*/.claude/worktrees/}"
    REL="${after#*/}"
    WT="${FILE_PATH%%/.claude/worktrees/*}/.claude/worktrees/${after%%/*}"
    ;;
  "$ROOT"/*) REL="${FILE_PATH#"$ROOT"/}" ;;
  *) exit 0 ;;
esac

# 只管示意圖（cache/demos/ 底下的 html）
case "$REL" in
  cache/demos/*.html|cache/demos/*.htm) ;;
  *) exit 0 ;;
esac

# session key（與其他 hook 同一套算法）
if [ -n "$SID" ]; then KEY="$SID"; else KEY="day-$(date +%Y%m%d)"; fi

# 本 session 已經看過表 → 放行（標記放主目錄或工作區的 cache/ 都算）
[ -f "$ROOT/cache/.mockup-text-ok.$KEY" ] && exit 0
[ -n "$WT" ] && [ -f "$WT/cache/.mockup-text-ok.$KEY" ] && exit 0

cat >&2 <<'EOF'
📝 [mockup-text-gate] 示意圖上的每一句話，先查它在做什麼工作

  「多餘文字」是最常被退回的一類，而且多半在示意圖這一關就被抓到。
  逐句對照 ui-design「這句話在做什麼工作」那張表
  （全文在 .agents/skills/ui-design/references/07-restraint.md）：

  ── 必須有，不進判斷 ──────────────────────────────
  攔截一個動作、講後果   例：「送出之後，這張單會退回上一關，要繼續嗎？」
  回報系統自己做了什麼   例：「已自動指派給王小明」
  空狀態那一句           例：「還沒有任何訂單」＋下一步

  ── 要處置 ────────────────────────────────────
  解釋現在為什麼是這個狀態  → 造成它的是他上一個動作嗎？是 → 刪
  重述畫面上已經有的東西    → 縮短到只剩畫面上沒有的那一段
                             （最常重複：對象的名字／時間地點／規則的解釋／標題那半句）
  教人怎麼操作介面          → 句子不動，開票改介面
  講看的人不需要知道的事    → 刪；開發理由進票或程式註解
                             （最常見：出處／內部理由、圖表與數字卡上的口徑補述）

  示意圖還要多過一關：**註解自成一層、可以整批關掉**。
  關掉之後畫面上剩下的，才是使用者真的會看到的字。
  交圖時主動說明哪些是 UI、哪些是註解，不要讓看圖的人自己猜。

  看過了就放行（這一行會留在紀錄裡，代表表確實被讀過）：
EOF
# cache/ 不進版控，新開的工作區裡不存在，所以 mkdir 要一起給——
# 只印 touch 的話那行會直接失敗（源專案這支 hook 第一次實測就踩到）。
printf '    mkdir -p cache && touch %s\n' "cache/.mockup-text-ok.$KEY" >&2
exit 2
