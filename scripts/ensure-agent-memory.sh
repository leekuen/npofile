#!/usr/bin/env bash
# 讓這個工作區（worktree）的 agent 記憶接回主目錄那一份（源專案 v4.51.0）。
#
# 為什麼要這支：Claude 的記憶庫路徑是用**工作目錄**算出來的
# （~/.claude/projects/<路徑裡不是英數的字元都換成 - 的 slug>/memory/）。工作區的路徑不一樣
# ⇒ 算出另一個資料夾 ⇒ **空的**。而框架規定「一條 session 一個工作區」，等於絕大多數
# 開發 session 都在零記憶下跑：先前累積的規則一條都讀不到，還會把早就記過的事當新發現。
# （源專案實測：十幾個工作區的對應目錄沒有一個有 memory/，主目錄那份有幾十條。）
#
# 用 symlink 不用複製：記憶要**雙向**共通——工作區裡學到的事，主目錄下次要看得到。
# 複製會分岔成兩份各自演化的筆記，比沒有更糟。
# 代價：兩條 session 同時寫 MEMORY.md 會後寫的蓋掉先寫的（既有風險，非本支造成）。
#
# 用法：scripts/ensure-agent-memory.sh [工作區路徑]   # 預設為 $PWD
#   由 scripts/new-worktree.sh（開工作區時）與 scripts/session-start-hook.sh（每個 session
#   兜底，涵蓋 harness 自己開、不走 new-worktree.sh 的那些工作區）呼叫。
#   安靜設計：只有「真的接上」或「接不上」才輸出，已接上或不需要就沉默。
#   主目錄還沒有記憶庫（沒用過記憶、或用的不是 Claude）→ 沒得接，安靜結束。
set -uo pipefail

# 路徑裡不是英數的字元一律換成 -。源專案只換 / 和 .（它的路徑剛好沒有別的字元）；
# 實測底線也會被換，只換那兩個的話，專案放在名稱帶底線的資料夾時會算到別的資料夾、安靜地接不上。
slug() { printf '%s' "$1" | sed 's/[^A-Za-z0-9]/-/g'; }

target="${1:-$PWD}"
cd "$target" 2>/dev/null || exit 0
target="$PWD"   # 正規化成絕對路徑

git rev-parse --git-dir >/dev/null 2>&1 || exit 0
main="$(git worktree list --porcelain 2>/dev/null | head -1 | sed 's/^worktree //')"
[ -n "$main" ] || exit 0
[ "$main" = "$target" ] && exit 0          # 自己就是主目錄，不用接

mem_main="$HOME/.claude/projects/$(slug "$main")/memory"
[ -d "$mem_main" ] || exit 0               # 主目錄還沒有記憶庫，沒得接

mem_wt="$HOME/.claude/projects/$(slug "$target")/memory"
[ -L "$mem_wt" ] && exit 0                 # 已經接上了
if [ -d "$mem_wt" ]; then
  # 真目錄且有東西 → 這個工作區自己寫過記憶，不可覆蓋，交給人處理
  if [ -n "$(find "$mem_wt" -name '*.md' 2>/dev/null | head -1)" ]; then
    echo "[memory] ⚠️  $(basename "$target") 有自己的記憶檔，未接回主庫（避免覆蓋）：$mem_wt" >&2
    exit 0
  fi
  rmdir "$mem_wt" 2>/dev/null || exit 0
fi

mkdir -p "$(dirname "$mem_wt")"
if ln -s "$mem_main" "$mem_wt" 2>/dev/null; then
  echo "[memory] ✅ 已接上 agent 記憶（$(find -L "$mem_main" -name '*.md' 2>/dev/null | wc -l | tr -d ' ') 條）——**本 session 可能已錯過載入，下一個 session 起生效**" >&2
else
  echo "[memory] ⚠️  接不上 agent 記憶，這個工作區的 session 讀不到既有規則" >&2
fi
