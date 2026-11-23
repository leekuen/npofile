#!/usr/bin/env bash
# 框架版號取號：**先問遠端，再決定下一號**（源專案 v4.45.0）。
#
# 為什麼要一支腳本：源專案曾經一個晚上撞號兩次——
# 都是讀本機的 `docs/FRAMEWORK.md` 決定下一號，而別條 session 已經佔走了那個號、
# 只是還沒推上來或這邊還沒 fetch。**與票號撞號是同一個競爭條件**（取號 vs 推送），
# 而票號那一半早就有 `new-ticket.sh` 在擋，版號這一半沒有。
#
# 票號可以用「作者前綴」給每個人獨立空間，版號不行——框架版號**天生是全域的**，
# 所以只能靠「取號前掃過所有遠端分支」把窗口縮到最小。
#
# 用法：
#   scripts/next-framework-version.sh            # 印出建議的下一個 MINOR（同 --minor）
#   scripts/next-framework-version.sh --patch    # 下一個 PATCH
#   scripts/next-framework-version.sh --major    # 下一個 MAJOR
#   make next-framework-version [level=patch|minor|major]
# 版號印在標準輸出（只有一行），說明印在標準錯誤——可以直接 v=$(scripts/next-framework-version.sh)。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOC="docs/FRAMEWORK.md"
LEVEL="${1:---minor}"
case "$LEVEL" in
  --minor|--patch|--major) ;;
  *) echo "[framework-version] 不認得的參數：${LEVEL}（只收 --minor／--patch／--major，不給就是 --minor）" >&2; exit 2 ;;
esac

# 掃全部遠端分支，不只 stage——**已經寫好、還在別人 feature 分支上**的版號
# 正是撞號的來源（同 new-ticket.sh 的理由）。
if git -C "$ROOT" fetch --all --prune >/dev/null 2>&1; then
  refs=$(git -C "$ROOT" for-each-ref --format='%(refname)' refs/remotes/ 2>/dev/null | grep -v '/HEAD$')
  # grep -c 數到 0 時會印 0 並回傳失敗；後面接 `|| echo 0` 會再多印一個 0（還沒設遠端的新專案每次都會遇到）
  echo "[framework-version] 已 fetch 全部遠端（納入 $(printf '%s\n' "$refs" | grep -c . || true) 條分支）" >&2
else
  echo "[framework-version][warn] fetch 失敗（離線）——只看本機，撞號風險較高" >&2
  refs=""
fi

# 版號只認兩個地方（本機檔與每條遠端分支上的那一份，都用同一套抽法）：
#   (1) 檔頭那一行「框架版本：vX.Y.Z」——只認整份檔第一次出現的那一行，簡報讀的也是它
#   (2) 決策紀錄表每一列的第一格（行首「| vX.Y.Z |」）
# 不能把整份檔的 vX.Y.Z 全撈出來取最大：決策紀錄的內文會寫「源專案 v5.46.0」這種來歷，
# 那是別的專案的版號，拿它來算，下一號會直接跳到別人的號碼上。
# awk 把輸入讀到完才結束（不中途離開），上游不會因為管線提早關掉而出錯；切字只切 ASCII 的部分。
collect() {
  awk '
    !hdr && /框架版本：v[0-9]+\.[0-9]+\.[0-9]+/ {
      hdr = 1; n = split($0, part, "框架版本：")
      for (i = 2; i <= n; i++)
        if (match(part[i], /^v[0-9]+\.[0-9]+\.[0-9]+/)) { print substr(part[i], 1, RLENGTH); break }
    }
    /^\|[ \t]*v[0-9]+\.[0-9]+\.[0-9]+[ \t]*\|/ {
      cell = $0; sub(/^\|[ \t]*/, "", cell); sub(/[ \t]*\|.*$/, "", cell); print cell
    }
  ' 2>/dev/null
}
all=$( { cat "$ROOT/$DOC" 2>/dev/null | collect
         for ref in $refs; do git -C "$ROOT" show "$ref:$DOC" 2>/dev/null | collect; done; } )

max=$(printf '%s\n' "$all" | tr -d 'v' | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)
if [ -z "$max" ]; then
  echo "[framework-version] 找不到任何版號，請自行決定" >&2
  exit 1
fi
IFS=. read -r MA MI PA <<< "$max"
case "$LEVEL" in
  --patch) next="v${MA}.${MI}.$((PA + 1))" ;;
  --major) next="v$((MA + 1)).0.0" ;;
  --minor) next="v${MA}.$((MI + 1)).0" ;;
esac
echo "[framework-version] 目前最大：v${max}（含所有遠端分支）" >&2
echo "$next"
