#!/usr/bin/env bash
# 開一個隔離的工作區（git worktree）給這條 session 用（源專案 v4.14.0：一條 session 一個工作區）。
#
# 為什麼要這支：多條 session 共用同一個工作目錄時，一方 checkout／commit 會把另一方
# 未提交的工作掃走、或提交到錯的分支（源專案為此撞過好幾次）。
# 工作區把檔案隔開，但 `git worktree add` 不會帶不進版控的本機檔案（環境變數檔、本機設定檔…），
# 少了它們檢查會直接紅、環境也起不來，所以照 scripts/framework-config.sh 的 WORKTREE_COPY_GLOBS 一併補齊。
#
# 用法：
#   scripts/new-worktree.sh <名稱> [基底分支]      # 預設基底 origin/stage
#   scripts/new-worktree.sh TK-12                 # → .claude/worktrees/TK-12，分支 feature/TK-12
#   scripts/new-worktree.sh AMY-3-通知中心         # 名稱可以是「票號-短名」
#   scripts/new-worktree.sh FW-5.1                # 改協作框架用的工作區（名稱可以帶點）
#   scripts/new-worktree.sh TK-13 origin/feature/TK-12
#       # 這張票相依的票（depends）還沒進 stage：從那張票的分支開，不必等它先上 stage（源專案 v5.16.0）
#   make worktree n=TK-12 [base=origin/feature/TK-11]
#
# 收工清理見 scripts/worktree-clean.sh。
set -uo pipefail
cd "$(dirname "$0")/.."
git rev-parse --git-dir >/dev/null 2>&1 || { echo "[worktree] 不在 git repo 內" >&2; exit 2; }
# 一律在「主目錄」底下開，不管這支是從主目錄還是從別的工作區執行——
# `git rev-parse --show-toplevel` 在工作區裡回傳的是那個工作區，用它會把新的工作區
# 巢狀建在別人裡面（源專案實測踩過）。主目錄固定是 worktree list 的第一筆。
ROOT="$(git worktree list --porcelain | sed -n '1s/^worktree //p')"
cd "$ROOT" || { echo "[worktree] 進不了主目錄：$ROOT" >&2; exit 2; }

# 專案設定（要複製哪些本機檔案）讀主目錄那一份——要複製的檔案也在主目錄。
# 先宣告再 source：設定檔不在、或還沒有這個變數時，bash 3.2 在 set -u 下展開沒宣告的陣列會直接報錯。
WORKTREE_COPY_GLOBS=()
# shellcheck disable=SC1091
[ -f scripts/framework-config.sh ] && . scripts/framework-config.sh

name="${1:-}"
base="${2:-}"

if [ -z "$name" ]; then
  cat >&2 <<'USAGE'
[worktree] 用法：scripts/new-worktree.sh <名稱> [基底分支]
  <名稱>  票號或短名，例：TK-12、AMY-3-通知中心、FW-5.1
  預設基底分支：origin/stage（還沒有遠端的 stage 時，用本機的 stage）
  票相依的票還沒進 stage 時，基底寫那張票的分支，例：origin/feature/TK-12
USAGE
  exit 2
fi

# 名稱會變成目錄名與分支名的一部分：不可含 /、不可以 - 開頭，其餘照 git 對分支名的規定
# （中文、點都可以，例：AMY-3-通知中心、FW-5.1）
case "$name" in
  */*|-*) echo "[worktree] 名稱不可含 / 或以 - 開頭：$name" >&2; exit 2 ;;
esac

wt_dir=".claude/worktrees/$name"
branch="feature/$name"

if ! git check-ref-format --branch "$branch" >/dev/null 2>&1; then
  echo "[worktree] 這個名稱不能當分支名：${name}（不可含空白、連續兩個點、~ ^ : ? * [ 與反斜線，開頭結尾不可以是點）" >&2
  exit 2
fi

if [ -e "$wt_dir" ]; then
  echo "[worktree] 已存在：$wt_dir" >&2
  echo "           要重開請先 scripts/worktree-clean.sh $name" >&2
  exit 2
fi

if git show-ref --verify --quiet "refs/heads/$branch"; then
  echo "[worktree] 分支已存在：$branch" >&2
  echo "           若要接續既有分支：git worktree add $wt_dir $branch" >&2
  exit 2
fi

# 基底要新：多條 session 平行時，本機的 origin/stage 常常是舊的。還沒設遠端的專案沒有東西可以同步。
if git remote get-url origin >/dev/null 2>&1; then
  echo "[worktree] 同步遠端…"
  git fetch origin --prune --quiet 2>/dev/null || echo "[worktree] ⚠️ fetch 失敗，改用本機現有的資料（基底可能不是最新）"
fi

# 基底：預設 origin/stage。遠端還沒有 stage（還沒設遠端、或還沒推過）就用本機的 stage；
# 連本機都沒有就停下來講清楚——不拿目前所在的分支頂替，那樣會把別條線還沒合流的東西一起帶進來。
if [ -z "$base" ]; then
  if git show-ref --verify --quiet refs/remotes/origin/stage; then
    base="origin/stage"
  elif git show-ref --verify --quiet refs/heads/stage; then
    base="stage"
    echo "[worktree] 遠端還沒有 stage，改從本機的 stage 開"
  else
    cat >&2 <<'NOSTAGE'
[worktree] 找不到 stage 分支（遠端與本機都沒有），不知道要從哪裡開。
           stage 是整合分支，所有 feature/* 都從它開。兩條路選一條：
             · 先讓這個 repo 有 stage：把目前的分支改名（git branch -m stage）或另開一條（git switch -c stage）；
               還沒有任何提交的話，先完成第一次提交
             · 或用第二個參數指定基底：scripts/new-worktree.sh <名稱> <基底分支>
NOSTAGE
    exit 2
  fi
elif ! git rev-parse --verify --quiet "${base}^{commit}" >/dev/null 2>&1; then
  echo "[worktree] 找不到基底：$base" >&2
  echo "           那條分支還沒推上遠端的話，改用本機的分支名（例：feature/TK-12），或請那條 session 先推上去" >&2
  exit 2
fi

echo "[worktree] 建立 ${wt_dir}（分支 ${branch}，基底 ${base}）"
# --no-track：新分支不把基底當成自己的上游。不加的話，從 origin/stage 開的分支在第一次推上遠端之前
# 會一直「追蹤 stage」，實測有兩個後果：
#   · 不帶參數的 git push 被 git 拒絕，而它給的第一個建議是「git push origin HEAD:stage」——照做就直接推進整合分支；
#   · 推送前的同步檢查（scripts/git-sync-gate-hook.sh）拿 stage 的進度來量，stage 一有新東西，這條分支的第一次推送就被擋。
# 源專案靠「commit 後自動推送」在第一筆 commit 就把上游改成分支自己的遠端分支；
# 這裡的自動推送要另外啟用（make hooks），不能假設有，所以開的時候就不追蹤。
git worktree add --no-track -b "$branch" "$wt_dir" "$base" || exit 1

# ── 本機檔案：git worktree 不會帶不進版控的檔案過來 ─────────────────────────
# 照 WORKTREE_COPY_GLOBS（相對主目錄的 shell 樣式）從主目錄複製到新工作區的同一個相對位置。
# 這些檔案常常是祕密（環境變數檔）：這裡只做 cp——不打開、不印內容，只印檔名。
# 工作區裡已經有的（進版控的同名檔，例：.env.example）不覆蓋。
# 只複製檔案、不複製目錄：相依套件這類目錄整個搬過去，會把主目錄裡過期的那一份原樣帶進新工作區。
copy_local_files() {
  local IFS=     # 樣式只做萬用字元展開、不照空白拆開（路徑裡有空白也行）
  local pat f n=0
  for pat in "${WORKTREE_COPY_GLOBS[@]}"; do
    case "$pat" in
      "") continue ;;
      /*|..|../*|*/..|*/../*)
        echo "[worktree] ⚠️ 略過樣式 ${pat}：要寫相對主目錄的路徑，不可以用 .. 往上"; continue ;;
    esac
    for f in $pat; do
      case "$f" in .|..|*/.|*/..) continue ;; esac
      if [ -d "$f" ]; then
        echo "[worktree] ⚠️ 略過目錄 ${f}：只複製檔案（相依套件這類目錄，請在工作區裡自己安裝）"
        continue
      fi
      [ -f "$f" ] || continue             # 樣式沒有相符的檔案時會原樣留下，在這裡濾掉
      [ -e "$wt_dir/$f" ] && continue     # 工作區裡已經有了，不覆蓋
      if mkdir -p "$(dirname "$wt_dir/$f")" 2>/dev/null && cp -p "$f" "$wt_dir/$f" 2>/dev/null; then
        [ "$n" -eq 0 ] && echo "[worktree] ✅ 已從主目錄複製本機檔案（只複製、沒有打開內容）："
        echo "             $f"
        n=$((n + 1))
      else
        echo "[worktree] ⚠️ 複製失敗：${f}（請自己補到 ${wt_dir}/${f}）"
      fi
    done
  done
  [ "$n" -gt 0 ] || echo "[worktree] 沒有複製任何本機檔案（WORKTREE_COPY_GLOBS 列的，主目錄沒有、或工作區裡已經有了）"
}
if [ "${#WORKTREE_COPY_GLOBS[@]}" -gt 0 ]; then
  copy_local_files
fi

# ── agent 記憶：接回主目錄那一份（源專案 v4.51.0）──────────────────────────
# 為什麼：Claude 的記憶庫路徑是由工作目錄算出來的，新工作區算出來是空的一份；
# 而開發一律在工作區做 ⇒ 多數開發 session 會讀不到累積下來的規則。
# 細節與取捨全寫在那支腳本的檔頭。
[ -f "$ROOT/scripts/ensure-agent-memory.sh" ] && bash "$ROOT/scripts/ensure-agent-memory.sh" "$ROOT/$wt_dir"

echo "[worktree] ✅ 完成：$wt_dir"
echo
echo "接下來："
echo "  cd $wt_dir"
echo
echo "注意："
echo "  · 開發都在這個工作區做，主目錄只做合流（merge／push／盯部署）。"
echo "  · 不要在工作區內 checkout stage——stage 被佔住，別條 session 就不能合流了。"
echo "  · 只帶了 WORKTREE_COPY_GLOBS 列的本機檔案；相依套件這類目錄不會帶過來，要用就在工作區裡自己安裝。"
echo "  · 收工：scripts/worktree-clean.sh $name"
