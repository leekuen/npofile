#!/usr/bin/env bash
# 收掉用完的工作區（git worktree）（源專案 v4.14.0）。
#
# 為什麼要這支：工作區開了沒人收，機器上會愈積愈多（源專案一度累到 9 個），
# 開場簡報的「平行現場」就會長到讀不動，也看不出哪些還活著。
#
# ⚠️ 工作區可能有別條 session 正掛在裡面工作。工作已 commit 且合進 stage 的話收掉不會掉資料，
# 但對方的所在目錄會憑空消失。所以：**指名收要自己判斷、整批收一定先看過再確認**——
# `--merged` 預設只印出「會收哪些」，真的要動手得再加 --yes。
#
# 用法：
#   scripts/worktree-clean.sh --list         # 列出現況，不動任何東西（預設）
#   scripts/worktree-clean.sh <名稱>         # 收掉指定的（分支已合進 stage 才一併刪分支），例：TK-12
#   scripts/worktree-clean.sh --merged       # 只預覽：列出「可收」的有哪些，不動手
#   scripts/worktree-clean.sh --merged --yes # 真的整批收掉
#   make worktree-list ／ make worktree-clean n=TK-12
set -uo pipefail
# 呼叫的人現在站在哪個工作區——要在下面的 cd 之前記下來。
# 用絕對路徑叫主目錄那一份腳本時，腳本自己的位置是主目錄，看不出「你人其實站在要收的那個工作區裡」。
CALLER_TOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
cd "$(dirname "$0")/.."
git rev-parse --git-dir >/dev/null 2>&1 || { echo "[worktree] 不在 git repo 內" >&2; exit 2; }

# 注意：在工作區裡跑時，`git rev-parse --show-toplevel` 回傳的是「這個工作區」，
# 不是主目錄。要取主目錄得看 worktree list 的第一筆。
MAIN_ROOT="$(git worktree list --porcelain | sed -n '1s/^worktree //p')"
HERE="$(git rev-parse --show-toplevel)"

# 整合／正式分支：永遠不刪。停在它們上面的工作區收掉時，只是把分支釋放出來
PROTECTED_BRANCHES='stage prod main master'

arg="${1:---list}"

list_worktrees() {  # 路徑<TAB>分支（跳過主目錄）
  git worktree list --porcelain | awk '
    /^worktree /  { path=substr($0,10) }
    /^branch /    { br=substr($0,8); sub("refs/heads/","",br); print path "\t" br }
    /^detached$/  { print path "\t(detached)" }
  ' | tail -n +2
}

short_path() { echo "${1#$MAIN_ROOT/}"; }

is_protected() {
  local p
  for p in $PROTECTED_BRANCHES; do [ "$1" = "$p" ] && return 0; done
  return 1
}

# 這個工作區是不是「你現在所在的」：腳本自己所在的那一份，或呼叫時站的位置
in_use_here() {
  [ "$1" = "$HERE" ] && return 0
  [ -n "$CALLER_TOP" ] && [ "$1" = "$CALLER_TOP" ] && return 0
  return 1
}

# 「已合進 stage」跟誰比：預設是遠端的 stage（origin/stage）；還沒設遠端、或還沒推過 stage 的專案
# 用本機的 stage；兩個都沒有就一律不判「已合流」——寧可留著，也不用猜的。
# 兩邊都寫完整的 ref 名稱（源專案 v4.78.1）：只寫分支名，遇到同名 tag 時 git 會先解析成 tag
# （警告常常又被吞掉），比到的就不是那條分支。
STAGE_REF=""
resolve_stage_ref() {
  if git show-ref --verify --quiet refs/remotes/origin/stage; then STAGE_REF="refs/remotes/origin/stage"
  elif git show-ref --verify --quiet refs/heads/stage; then STAGE_REF="refs/heads/stage"
  else STAGE_REF=""; fi
}
resolve_stage_ref
merged_into_stage() {
  [ -n "$STAGE_REF" ] && git merge-base --is-ancestor "refs/heads/$1" "$STAGE_REF" 2>/dev/null
}

# 「剛動過的不算可收」（源專案 v4.22.0）：git 乾淨不等於沒人在用——剛 commit 完、正要做下一步的工作區，
# 看起來跟「做完了」一模一樣，收掉它，那條 session 的所在目錄會當場消失。
# 用最後一次 commit 的時間當活躍度的代理：一小時內有 commit 的，整批收（--merged）先跳過；
# 指名收的是你自己點名的那一個，不擋。算法要跟開場簡報（agent-status.sh）列「可以直接收」的那一段一致。
RECENT_SECS=3600
NOW_S="$(date +%s)"
recent_minutes() {  # recent_minutes <工作區路徑>：一小時內有 commit → 印「幾分鐘前」並回 0；否則回 1
  local last
  last="$(git -C "$1" log -1 --format=%ct 2>/dev/null)" || return 1
  [ -n "$last" ] || return 1
  [ $((NOW_S - last)) -lt "$RECENT_SECS" ] || return 1
  echo $(( (NOW_S - last) / 60 ))
}

# 回傳這個工作區的狀態字串，並以結束碼表示「可不可以收」（0＝可收）
state_of() {
  local path="$1" br="$2" dirty
  dirty=$(git -C "$path" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  if is_protected "$br"; then
    # 停在 stage／prod 上的工作區會擋住合流樞紐（主目錄要拿 stage）。
    # 這種工作區「應該」被收掉——收工作區只是釋放分支，不會刪掉分支本身。
    # 這裡曾經判成「不可收」，方向剛好相反，導致 stage 被佔住沒人能處理（源專案 v4.19.0 修正）。
    if [ "$dirty" -gt 0 ]; then
      echo "佔用 $br 分支且有 $dirty 個未提交・先處理未提交再收"; return 1
    fi
    echo "佔用 $br 分支・建議收掉把分支還給主目錄（分支本身保留）"; return 0
  fi
  if [ "$dirty" -gt 0 ]; then
    echo "$dirty 個未提交・先處理完再收"; return 1
  fi
  if [ "$br" = "(detached)" ]; then
    echo "detached HEAD・手動確認後再收"; return 1
  fi
  if [ -z "$STAGE_REF" ]; then
    echo "找不到 stage 分支，判斷不了有沒有合流・保留"; return 1
  fi
  if merged_into_stage "$br"; then
    echo "已合進 stage・可收"; return 0
  fi
  echo "尚未合進 stage・保留"; return 1
}

if [ "$arg" = "--list" ]; then
  echo "[worktree] 目前的工作區（主目錄 ${MAIN_ROOT##*/} 不列）："
  n=0
  while IFS=$'\t' read -r path br; do
    [ -z "$path" ] && continue
    n=$((n+1))
    if st=$(state_of "$path" "$br") && mins=$(recent_minutes "$path"); then
      st="${st}（${mins} 分鐘前才 commit，整批收會先跳過）"
    fi
    mark=" "; in_use_here "$path" && mark="→"
    printf "  %s %-32s %-40s %s\n" "$mark" "$(short_path "$path")" "$br" "$st"
  done < <(list_worktrees)
  if [ "$n" -eq 0 ]; then
    echo "  （沒有額外的工作區）"
  elif [ "$STAGE_REF" = "refs/heads/stage" ]; then
    echo "  （遠端還沒有 stage：「已合進 stage」是跟本機的 stage 比）"
  elif [ -z "$STAGE_REF" ]; then
    echo "  ⚠️ 找不到 stage 分支（遠端、本機都沒有）：分不出哪些已經合流，全部先保留——整合分支固定叫 stage"
  fi
  echo
  echo "收掉可收的：scripts/worktree-clean.sh --merged（先預覽，加 --yes 才真的收）"
  exit 0
fi

# ── 收之前先搶救被 gitignore 的 cache/（源專案 v5.21.0）─────────────────────
# `cache/` 在 .gitignore 裡：`git worktree remove` 不會因為它而拒絕，而是整個刪掉。
# 設計圖、展示素材照規定放 `cache/demos/`，討論紀錄與提案放 `cache/discussions/`，
# 所以收工作區常常就是在刪設計圖與審過的提案檔（源專案有過：審完的提案檔、
# 一次收二十幾個工作區時的設計圖，都是這樣沒的）。
# 做法：remove 之前把所有檔複製到主目錄 cache/rescued/<工作區名>-<時刻>/、逐檔比 sha256；
# 任何一步失敗就不收這個工作區。cache/discussions/ 另外複製回主目錄 cache/discussions/（不覆蓋）。
# 放在這支腳本裡，因為它是所有收法的必經點（指名收、整批收都走 remove_one）；
# 直接打 `git worktree remove`、或別的工具清掉閒置的工作區，不經過這裡、擋不到。
# 下面排除的是 hook 的旗標檔（「讀過設計規範了」的記號、放行檔），搶救了只是雜訊：
rescue_find() {  # rescue_find <cache 目錄> <find 的動作…>：套排除後列出一般檔
  local dir="$1"; shift
  ( cd "$dir" 2>/dev/null && find . -type f \
      ! -path './.ui-design-ok.*' ! -path './.mockup-text-ok.*' \
      ! -path './ui-design-override' ! -path './hotfix-override' ! -path './git-scope-override' "$@" )
}
rescue_sha() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" </dev/null | cut -d' ' -f1
  else shasum -a 256 "$1" </dev/null | cut -d' ' -f1; fi
}
RESCUE_MARK=""; RESCUE_N=0; RESCUE_DEST=""

rescue_fail() {  # rescue_fail <工作區路徑> <原因>
  echo "[worktree] ⚠️ 搶救 cache/ 失敗（$2）→ 不收 $(short_path "$1")"
  [ -n "$RESCUE_DEST" ] && echo "[worktree]    已複製的留在 ${RESCUE_DEST#$MAIN_ROOT/}（不刪）"
  [ -n "$RESCUE_MARK" ] && rm -f "$RESCUE_MARK"
  RESCUE_MARK=""
  return 1
}

rescue_discussions() {  # 把工作區裡 cache/discussions/ 的檔複製回主目錄（同名不覆蓋）
  local src="$1/cache/discussions" rel t new=0 same=0 conf=0 newer
  [ -d "$src" ] || return 0
  while IFS= read -r -d '' rel; do
    rel="${rel#./}"; t="$MAIN_ROOT/cache/discussions/$rel"
    if [ ! -e "$t" ]; then
      if mkdir -p "$(dirname "$t")" && cp -p "$src/$rel" "$t" </dev/null; then new=$((new+1))
      else echo "[worktree] ⚠️ discussions/$rel 複製回主目錄失敗（完整備份在 ${RESCUE_DEST#$MAIN_ROOT/}）"; fi
    elif cmp -s "$src/$rel" "$t" </dev/null; then same=$((same+1))
    else
      conf=$((conf+1)); newer="比較舊"; [ "$src/$rel" -nt "$t" ] && newer="比較新"
      echo "[worktree]    ⚠️ cache/discussions/$rel 主目錄已有不同內容的同名檔，沒覆蓋（工作區裡那份${newer}，在 ${RESCUE_DEST#$MAIN_ROOT/}）"
    fi
  done < <(cd "$src" && find . -type f -print0)
  echo "[worktree]    discussions 複製回主目錄：新增 ${new}・相同略過 ${same}・同名不同內容 ${conf}"
}

rescue_cache() {  # rescue_cache <工作區路徑>；失敗回 1（呼叫端就不收這個工作區）
  local path="$1" src="$1/cache" name stamp dest rel i=1 n=0 a b kb nl
  RESCUE_MARK=""; RESCUE_N=0; RESCUE_DEST=""
  [ -d "$src" ] || return 0
  [ -n "$(rescue_find "$src" -print | head -n1)" ] || return 0
  name="${path##*/}"; stamp="$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$MAIN_ROOT/cache/rescued" || { rescue_fail "$path" "建不了 cache/rescued/"; return 1; }
  dest="$MAIN_ROOT/cache/rescued/${name}-${stamp}"
  until mkdir "$dest" 2>/dev/null; do
    i=$((i+1)); dest="$MAIN_ROOT/cache/rescued/${name}-${stamp}-$i"
    [ "$i" -gt 99 ] && { rescue_fail "$path" "建不了目的資料夾 cache/rescued/（不可寫、硬碟滿或撞名）"; return 1; }
  done
  RESCUE_DEST="$dest"
  RESCUE_MARK="$MAIN_ROOT/cache/rescued/.mark-${name}-${stamp}-$$"
  : > "$RESCUE_MARK" || { RESCUE_MARK=""; rescue_fail "$path" "建不了標記檔"; return 1; }
  while IFS= read -r -d '' rel; do
    rel="${rel#./}"
    mkdir -p "$dest/$(dirname "$rel")" && cp -p "$src/$rel" "$dest/$rel" </dev/null \
      || { rescue_fail "$path" "複製失敗：cache/$rel"; return 1; }
    a="$(rescue_sha "$src/$rel")"; b="$(rescue_sha "$dest/$rel")"
    { [ -n "$a" ] && [ "$a" = "$b" ]; } || { rescue_fail "$path" "sha256 不一致：cache/$rel"; return 1; }
    n=$((n+1))
  done < <(rescue_find "$src" -print0)
  RESCUE_N="$n"
  if [ "$n" -eq 0 ]; then rm -f "$RESCUE_MARK"; rmdir "$dest" 2>/dev/null; RESCUE_MARK=""; RESCUE_DEST=""; return 0; fi
  kb="$(du -sk "$dest" 2>/dev/null | cut -f1)"
  nl="$(cd "$src" && find . -type l -o \( ! -type f ! -type d \) | wc -l | tr -d ' ')"
  [ "${nl:-0}" -gt 0 ] && echo "[worktree]    另有 ${nl} 個符號連結／特殊檔沒搶救"
  echo "[worktree]    已搶救 cache/ ${n} 個檔（約 ${kb:-?} KB）→ ${dest#$MAIN_ROOT/}"
  rescue_discussions "$path"
  kb="$(du -sk "$MAIN_ROOT/cache/rescued" 2>/dev/null | cut -f1)"
  # 不自動清 cache/rescued/：裡面是「差點被刪掉的東西」，要不要留只有人能判斷；累積太多才提醒
  [ "${kb:-0}" -gt 512000 ] && echo "[worktree]    cache/rescued/ 已累積約 $((kb/1024)) MB，記得請使用者決定要不要清；內容可能含敏感或大量檔"
  return 0
}

# 複製期間 session 可能還在寫：remove 前再看一次，有檔比標記檔新（ctime，抓得到 cp -p 保留舊 mtime 的覆寫）
# 或檔數變了就不收。純改名檔數與 ctime 都不變，但內容已用舊檔名搶救到，不掉資料。
rescue_recheck() {  # rescue_recheck <工作區路徑>
  [ -n "$RESCUE_MARK" ] || return 0
  local src="$1/cache" changed cnt
  changed="$(rescue_find "$src" -cnewer "$RESCUE_MARK" -print | head -n1)"
  cnt="$(rescue_find "$src" -print0 | tr -cd '\0' | wc -c | tr -d ' ')"
  if [ -n "$changed" ] || [ "$cnt" != "$RESCUE_N" ]; then
    rescue_fail "$1" "搶救期間有檔變動；重跑會再開一份新的備份資料夾。請確認沒人在用後重跑；變動的例子：${changed:-檔數 ${RESCUE_N}→${cnt}}"
    return 1
  fi
  rm -f "$RESCUE_MARK"; RESCUE_MARK=""
  return 0
}

remove_one() {
  local path="$1" br="$2" st
  if in_use_here "$path"; then
    echo "[worktree] ⚠️ 跳過 $(short_path "$path")：你正在這個工作區裡面，換個位置再收"
    return 1
  fi
  st=$(state_of "$path" "$br") || { echo "[worktree] ⚠️ 跳過 $(short_path "$path")：$st"; return 1; }
  rescue_cache "$path" </dev/null || return 1
  rescue_recheck "$path" || return 1
  git worktree remove "$path" 2>/dev/null || {
    echo "[worktree] ⚠️ 移除失敗：$(short_path "$path")（可能有 session 正在裡面工作）"
    [ -n "$RESCUE_DEST" ] && echo "[worktree]    cache/ 已先備份在 ${RESCUE_DEST#$MAIN_ROOT/}；重跑會再開一份新的"
    return 1; }
  echo "[worktree] ✅ 已移除 $(short_path "$path")"
  # 保護分支（stage／prod／main／master）永遠不刪，只把它釋放出來
  if is_protected "$br"; then
    echo "[worktree]    分支 $br 已釋放，主目錄現在可以 checkout 它了（分支保留）"
  elif [ "$FETCH_OK" != 1 ]; then
    # fetch 失敗時，本機記得的遠端狀態可能是舊的（例：遠端的 stage 被退回過），
    # 不拿過期的資訊去刪分支（源專案 v4.78.1）。工作區收掉了，commit 都還在這條分支上。
    echo "[worktree]    fetch 失敗，分支 $br 先留著（確認不了它是不是真的還在遠端的 stage 裡；確認後自己刪：git branch -d ${br}）"
  elif git -C "$MAIN_ROOT" branch -d "$br" >/dev/null 2>&1; then
    # 用 -d 不用 -D：留著 git 自己的那一道檢查。分支設了上游（推過、有自己的遠端分支）時 git 拿上游來比，
    # 沒設的話拿「執行位置所在的分支」來比——所以指定在主目錄跑：主目錄固定停在 stage。
    echo "[worktree]    分支 $br 已合進 stage，一併刪除"
  else
    echo "[worktree]    分支 $br 先留著：commit 都已經在 stage 裡，但 git 自己的檢查沒過（它的上游、或主目錄現在所在的分支，還沒有這些 commit）"
    echo "[worktree]    主目錄追上最新的 stage 之後再刪：git branch -d $br"
  fi
  return 0
}

# 判斷「合流了沒」之前先同步遠端。還沒設遠端的專案沒有東西可以同步——那不算失敗，本機的 stage 就是全部。
FETCH_OK=1
if git remote get-url origin >/dev/null 2>&1; then
  git fetch origin --prune --quiet 2>/dev/null \
    || { FETCH_OK=0; echo "[worktree] ⚠️ fetch 失敗，合流判斷可能不準（照本機記得的遠端狀態判斷；收掉的工作區，分支會先留著）"; }
fi
resolve_stage_ref   # fetch 之後再看一次：遠端的 stage 可能是這次才抓到的

if [ "$arg" = "--merged" ]; then
  # 預設只預覽。整批收很可能收到別條 session 正掛著的工作區，
  # 資料不會掉（都已 commit 並合進 stage）但對方的所在目錄會突然不見，所以要先看過再確認。
  if [ "${2:-}" != "--yes" ]; then
    echo "[worktree] 預覽：以下工作區可以收（加 --yes 才會真的收）"
    n=0; held=""
    while IFS=$'\t' read -r path br; do
      [ -z "$path" ] && continue
      in_use_here "$path" && continue
      state_of "$path" "$br" >/dev/null || continue
      if mins=$(recent_minutes "$path"); then
        held="${held}  · $(short_path "$path")  ($br)・${mins} 分鐘前才 commit"$'\n'
      else
        n=$((n+1)); echo "  · $(short_path "$path")  ($br)"
      fi
    done < <(list_worktrees)
    [ "$n" -eq 0 ] && echo "  （沒有可收的）"
    if [ -n "$held" ]; then
      echo
      echo "先留著（已合流又乾淨，但一小時內才 commit 過，可能還有 session 在裡面）："
      printf '%s' "$held"
      echo "  確認沒人在用的話指名收：scripts/worktree-clean.sh <名稱>"
    fi
    echo
    echo "⚠️ 先確認這些工作區沒有別條 session 正在用（它們的所在目錄會消失）。"
    echo "   確定要收：scripts/worktree-clean.sh --merged --yes"
    exit 0
  fi
  done_n=0
  while IFS=$'\t' read -r path br; do
    [ -z "$path" ] && continue
    if ! in_use_here "$path" && state_of "$path" "$br" >/dev/null && mins=$(recent_minutes "$path"); then
      echo "[worktree] ⏳ 跳過 $(short_path "$path")：${mins} 分鐘前才 commit，可能還有 session 在裡面（確認沒人在用就指名收）"
      continue
    fi
    remove_one "$path" "$br" && done_n=$((done_n+1))
  done < <(list_worktrees)
  echo "[worktree] 收掉 $done_n 個。"
  exit 0
fi

target="$MAIN_ROOT/.claude/worktrees/$arg"
found=""
while IFS=$'\t' read -r path br; do
  [ "$path" = "$target" ] && found="$br"
done < <(list_worktrees)

if [ -z "$found" ]; then
  echo "[worktree] 找不到工作區：$arg" >&2
  echo "           現況：scripts/worktree-clean.sh --list" >&2
  exit 2
fi
remove_one "$target" "$found"
