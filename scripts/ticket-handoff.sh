#!/usr/bin/env bash
# 把已經開好的票「搬」進開發用的工作區（源專案 v4.81.0）。
#
# 為什麼要這支：開票通常在別的工作區（例如放設計圖的那條分支）做，要開工時得把票搬到自己的
# 開發分支——複製票、標「開發中」填 owner、提交、再從原本那條分支刪掉避免同一張票住在兩條分支。
# 源專案曾在一個 session 裡手動做了八次，每次約六個指令，被 zsh 的萬用字元與 `git rm` 擋住過兩次。
#
# 用法：
#   scripts/ticket-handoff.sh <目標工作區名稱> <票號> [<票號> ...] [--from <來源工作區名稱>] [--dry-run]
#   例：scripts/ticket-handoff.sh TK-12 TK-12 TK-14
#
#   目標工作區要先存在（make worktree n=<名稱>）。
#   來源預設自動找：掃所有工作區的 tickets/，票號相符的檔只准剛好一個來源，多個就要 --from 指名。
#   票已經在目標裡（同票號的檔）就只更新狀態，不搬。
#   --dry-run 只印會做什麼，不動任何檔案。
#   環境變數 CO_AUTHOR 有設就會附在 commit 訊息末尾（例：CO_AUTHOR="Co-Authored-By: ..."）。
#
# 它做的事（每張票）：
#   1. 複製到目標 tickets/；frontmatter 的 status 若是「待開發」改「開發中」、owner 空白才填
#      claude-cc-<目標名稱>（已有值就不動）。內文一個字都不改。
#   2. 目標 git add（指名檔案）；全部票處理完後在目標提交一次。
#   3. 來源那份：被版控追蹤就 git rm 並提交；沒被追蹤就直接刪。
# 不做的事：不推送、不動主目錄的檔案內容。
#
# 註：macOS 內建 bash 是 3.2，這支不用 mapfile／關聯陣列。
set -uo pipefail

target_name=""
tickets=()
from_name=""
dry=0
while [ $# -gt 0 ]; do
  case "$1" in
    --from) from_name="${2:-}"; shift 2 ;;
    --dry-run) dry=1; shift ;;
    -h|--help) sed -n 2,24p "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "[handoff] 不認得的選項：$1" >&2; exit 2 ;;
    *) if [ -z "$target_name" ]; then target_name="$1"; else tickets+=("$1"); fi; shift ;;
  esac
done
if [ -z "$target_name" ] || [ ${#tickets[@]} -eq 0 ]; then
  echo "用法：$0 <目標工作區名稱> <票號> [...] [--from <來源>] [--dry-run]" >&2; exit 2
fi

MAIN_ROOT="$(git worktree list --porcelain | head -1 | sed 's/^worktree //')"
target="$MAIN_ROOT/.claude/worktrees/$target_name"
[ -d "$target" ] || { echo "[handoff] 找不到目標工作區：${target}（先 make worktree n=${target_name}）" >&2; exit 2; }

trees=()
while IFS= read -r line; do trees+=("$line"); done < <(git worktree list --porcelain | sed -n 's/^worktree //p')

find_ticket() { # $1=票號 → 每個來源印一行「工作區路徑<TAB>檔名」（排除目標）
  local num="$1" t f
  for t in "${trees[@]}"; do
    [ "$t" = "$target" ] && continue
    for f in "$t"/tickets/"$num"-*.md; do
      [ -f "$f" ] && printf '%s\t%s\n' "$t" "$(basename "$f")"
    done
  done
}

moved=()
src_trees=()
for num in "${tickets[@]}"; do
  existing=""
  for f in "$target"/tickets/"$num"-*.md; do [ -f "$f" ] && existing="$(basename "$f")"; done

  src=""; fname=""
  if [ -n "$existing" ]; then
    fname="$existing"
    echo "[handoff] $num 已在目標裡（${fname}），只更新狀態"
  else
    if [ -n "$from_name" ]; then
      want="$MAIN_ROOT/.claude/worktrees/$from_name"
      cands="$(find_ticket "$num" | awk -F'\t' -v s="$want" '$1==s')"
    else
      cands="$(find_ticket "$num")"
    fi
    n=$(printf '%s' "$cands" | grep -c . || true)
    if [ "$n" -eq 0 ]; then echo "[handoff] ❌ 找不到 $num 的票（沒有任何工作區有它）" >&2; exit 1; fi
    if [ "$n" -gt 1 ]; then
      echo "[handoff] ❌ $num 同時出現在多個工作區，請用 --from 指名來源：" >&2
      printf '%s\n' "$cands" | awk -F'\t' '{print "   " $1}' >&2; exit 1
    fi
    src="$(printf '%s' "$cands" | cut -f1)"; fname="$(printf '%s' "$cands" | cut -f2)"
    echo "[handoff] ${num}：$src → $target"
  fi

  [ "$dry" -eq 1 ] && continue

  if [ -n "$src" ]; then cp "$src/tickets/$fname" "$target/tickets/$fname" || exit 1; fi
  # frontmatter（第一個 --- 到第二個 ---）：待開發→開發中、owner 空白才填；內文一個字都不動
  TARGET_NAME="$target_name" python3 - "$target/tickets/$fname" <<'PYEOF' || exit 1
import os, re, sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
m = re.match(r"---\n(.*?)\n---\n", s, re.S)
if m:
    fm = m.group(1)
    fm = re.sub(r"^status:\s*待開發.*$", "status: 開發中", fm, count=1, flags=re.M)
    fm = re.sub(r"^owner:[ \t]*(#.*)?$", "owner: claude-cc-" + os.environ["TARGET_NAME"], fm, count=1, flags=re.M)
    s = "---\n" + fm + "\n---\n" + s[m.end():]
    open(p, "w", encoding="utf-8").write(s)
PYEOF
  git -C "$target" add -- "tickets/$fname" || exit 1
  moved+=("$fname"); src_trees+=("$src")
done

if [ "$dry" -eq 1 ]; then echo "[handoff] （dry-run：沒有動任何檔案）"; exit 0; fi

specs=()
for fname in "${moved[@]}"; do specs+=("tickets/$fname"); done
msg="tickets: ${tickets[*]} 領票並移到 $target_name 開發"
[ -n "${CO_AUTHOR:-}" ] && msg="$msg

$CO_AUTHOR"
if ! git -C "$target" diff --cached --quiet -- "${specs[@]}"; then
  git -C "$target" commit -q -m "$msg" -- "${specs[@]}" || { echo "[handoff] ❌ 目標提交失敗" >&2; exit 1; }
  echo "[handoff] ✅ 目標已提交：$(git -C "$target" log --oneline -1)"
else
  echo "[handoff] 目標沒有需要提交的變更（票早已是開發中）"
fi

# 來源清掉（只清這次搬走的檔）
i=0
for fname in "${moved[@]}"; do
  src="${src_trees[$i]}"; i=$((i+1))
  [ -z "$src" ] && continue
  if git -C "$src" ls-files --error-unmatch -- "tickets/$fname" >/dev/null 2>&1; then
    smsg="tickets: $fname 移到 $target_name"
    [ -n "${CO_AUTHOR:-}" ] && smsg="$smsg

$CO_AUTHOR"
    git -C "$src" rm -q -f -- "tickets/$fname" \
      && git -C "$src" commit -q -m "$smsg" -- "tickets/$fname" \
      && echo "[handoff] ✅ 來源已刪並提交：$src"
  else
    rm -f "$src/tickets/$fname" && echo "[handoff] ✅ 來源（未追蹤）已刪：$src/tickets/$fname"
  fi
done
echo "[handoff] 完成：${#moved[@]} 張。"
