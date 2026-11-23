#!/usr/bin/env bash
# worktree-clean.sh 的測試：收工作區之前，該搶救的有沒有搶救、該擋的有沒有擋。
#
# 一、收之前先把被 gitignore 的 cache/ 搶救到主目錄（源專案 v5.21.0）
#   為什麼要有：`git worktree remove` 會連被忽略的 cache/ 一起刪，而設計圖照規定放 cache/demos/，
#   源專案審過的提案檔與設計圖就這樣沒了。搶救這段是「刪東西之前的保險」，
#   保險本身壞了不會有人發現，所以要有牙：
#   · 完整搶救（含中文與空白路徑）、排除清單的檔不收、空的不建資料夾
#   · discussions 回主目錄但不覆蓋同名不同內容
#   · 搶救失敗、搶救期間檔案被動過（新增、保留舊 mtime 的覆寫）→ 工作區不能被收
#   · --merged --yes 的迴圈不會被搶救吃掉 stdin
# 二、「可不可以收」的判斷（源專案 v4.14.0、v4.19.0、v4.22.0、v4.78.1）
#   · --list、--merged 只看不動；有未提交的、還沒合進 stage 的不收；整合／正式分支永遠不刪
#   · 一小時內才 commit 過的，整批收先跳過（指名收不擋）
#   · 合流判斷之前要先 fetch；同名 tag 不能頂替分支被判成「已合流」；fetch 失敗時工作區照收、分支不刪
#   · 還沒設遠端的專案跟本機的 stage 比；連 stage 都沒有就全部保留
#
# 全部在沙盒裡跑（假的 origin、腳本複製進 $TMP/repo/scripts/），真的工作區完全不碰。
# du、cp 換成替身：du 讓測試能在「搶救完、再檢查之前」偷改工作區裡的檔，cp 能把副本弄壞。
set -uo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"

fail=0
err() { echo "[worktree-clean-rescue-test] ✗ $1" >&2; fail=1; }
ok() { echo "[worktree-clean-rescue-test] ✓ $1"; }
# has <整段文字> <要找的字>：不用「echo | grep -q」——開了 pipefail，grep 找到就先走，前面那一段會被當成失敗
has() { case "$1" in *"$2"*) return 0 ;; esac; return 1; }

TMP="$(mktemp -d)"
trap 'chmod -R u+w "$TMP" 2>/dev/null; rm -rf "$TMP"' EXIT
# git worktree list 回傳的是實體路徑（macOS 的暫存目錄是符號連結），比對前先換成一樣的
TMP="$(cd "$TMP" && pwd -P)"

# 沙盒不吃使用者的 git 設定；從 git hook 裡跑時前三個變數會指向真的 repo，也要拿掉
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
# commit 時間預設放在過去：一小時內才 commit 過的工作區，整批收會先跳過（要測那一條時才用現在的時間）
export GIT_AUTHOR_DATE="2020-01-01T00:00:00" GIT_COMMITTER_DATE="2020-01-01T00:00:00"

mkdir -p "$TMP/bin"
REAL_DU="$(command -v du)"; REAL_CP="$(command -v cp)"
export REAL_DU REAL_CP
# du 替身：腳本搶救完會用 du 量備份的大小（在「再檢查」之前），借這個時機偷改工作區裡的檔
cat > "$TMP/bin/du" <<'EOF'
#!/bin/sh
if [ -n "${LATE_CMD:-}" ]; then eval "$LATE_CMD"; fi
exec "$REAL_DU" "$@"
EOF
# cp 替身：CORRUPT_COPY=1 時複製完偷偷弄壞副本（驗 sha256 比對真的會擋）
cat > "$TMP/bin/cp" <<'EOF'
#!/bin/sh
"$REAL_CP" "$@" || exit $?
if [ -n "${CORRUPT_COPY:-}" ]; then for last; do :; done; echo corrupt >> "$last"; fi
EOF
chmod +x "$TMP/bin/cp" "$TMP/bin/du"
export PATH="$TMP/bin:$PATH"

# mkrepo <目錄> <分支名>：開一個放了被測腳本的 repo，第一筆提交在指定的分支上
mkrepo() {
  git init -q "$1" && git -C "$1" checkout -q -b "$2"
  mkdir -p "$1/scripts" "$1/.claude/worktrees"
  cp "$SRC/scripts/worktree-clean.sh" "$1/scripts/"
  printf '.claude/\ncache/\n' > "$1/.gitignore"
  echo base > "$1/base.txt"
  git -C "$1" add scripts/worktree-clean.sh .gitignore base.txt >/dev/null 2>&1
  git -C "$1" commit -q -m base >/dev/null 2>&1
}
# commit <目錄> <檔名>：在那個目錄提交一個新檔
commit() { echo "$2" > "$1/$2" && git -C "$1" add "$2" && git -C "$1" commit -q -m "$2" >/dev/null 2>&1; }

O="$TMP/origin.git"
R="$TMP/repo"
WT="$R/.claude/worktrees"
git init -q --bare "$O"
mkrepo "$R" stage
mkdir -p "$R/cache/discussions"
git -C "$R" remote add origin "$O"
git -C "$R" push -q origin stage >/dev/null 2>&1

g() { git -C "$R" "$@" >/dev/null 2>&1; }
newwt() { git -C "$R" worktree add -q -b "feature/$1" "$WT/$1" stage >/dev/null 2>&1; }
clean() { ( cd "$R" && bash scripts/worktree-clean.sh "$@" 2>&1 ); }
rescued_of() { ls -d "$R/cache/rescued/$1"-* 2>/dev/null | head -n1; }
has_branch() { git -C "$R" show-ref --verify --quiet "refs/heads/$1"; }
# row <輸出> <工作區名>：--list／預覽裡講那個工作區的那一列
row() { printf '%s\n' "$1" | grep -F -- "worktrees/$2 " || true; }

# ══ 一、cache/ 搶救 ══════════════════════════════════════════════════

# ── 1. 完整搶救：中文與空白路徑、排除清單、discussions ─────────────
newwt T1
C="$WT/T1/cache"
mkdir -p "$C/demos/設計 圖" "$C/discussions"
echo '<html>a</html>' > "$C/demos/a.html"
echo '<html>b</html>' > "$C/demos/設計 圖/b 檔.html"
echo new > "$C/discussions/只在工作區.md"
echo same > "$C/discussions/same.md";  echo same > "$R/cache/discussions/same.md"
echo tree > "$C/discussions/conf.md";  echo main > "$R/cache/discussions/conf.md"
touch -t 202001010000 "$R/cache/discussions/conf.md"
echo tree-old > "$C/discussions/older.md"; echo main-new > "$R/cache/discussions/older.md"
touch -t 202001010000 "$C/discussions/older.md"
echo x > "$C/.ui-design-ok.abc"; echo x > "$C/.mockup-text-ok.abc"
echo x > "$C/ui-design-override"; echo x > "$C/hotfix-override"; echo x > "$C/git-scope-override"
ln -s demos/a.html "$C/link-to-a"
out=$(clean T1)
[ ! -d "$WT/T1" ] && ok "有 cache/ 的工作區照樣收得掉" || err "T1 沒被收：$out"
D=$(rescued_of T1)
[ -n "$D" ] && ok "搶救資料夾以 <工作區名>-<時刻> 命名" || err "沒有 cache/rescued/T1-*"
if [ -n "$D" ]; then
  cmp -s "$D/demos/a.html" <(echo '<html>a</html>') && cmp -s "$D/demos/設計 圖/b 檔.html" <(echo '<html>b</html>') \
    && ok "中文與空白路徑的檔完整搶救" || err "demos 內容不對"
  [ -f "$D/discussions/只在工作區.md" ] && ok "discussions 也在完整備份裡" || err "備份缺 discussions"
  bad=""
  for f in .ui-design-ok.abc .mockup-text-ok.abc ui-design-override hotfix-override git-scope-override link-to-a; do
    [ -e "$D/$f" ] || [ -L "$D/$f" ] && bad="$bad $f"
  done
  [ -z "$bad" ] && ok "排除清單的檔（hook 旗標）與符號連結沒被搶救" || err "不該搶救的被收了：$bad"
fi
[ "$(cat "$R/cache/discussions/只在工作區.md" 2>/dev/null)" = new ] && ok "discussions 只在工作區裡的檔複製回主目錄" || err "主目錄沒有 discussions/只在工作區.md"
[ "$(cat "$R/cache/discussions/conf.md")" = main ] && ok "同名不同內容不覆蓋主目錄那份" || err "conf.md 被覆蓋了"
has "$out" 'conf.md' && has "$out" '工作區裡那份比較新' && ok "摘要列出衝突並註明工作區裡比較新" || err "摘要沒列 conf.md 或沒註明新舊：$out"
has "$out" '1 個符號連結' && ok "符號連結沒搶救、摘要有列數量" || err "摘要沒列符號連結：$out"
has "$out" '工作區裡那份比較舊' && ok "工作區裡比較舊的同名檔也註明比較舊" || err "沒註明比較舊：$out"
[ -z "$(ls -A "$R/cache/rescued" | grep '^\.mark-')" ] && ok "標記檔用完就刪" || err "標記檔殘留"

# ── 2. 只有排除檔／沒有 cache/ → 不建資料夾 ─────────────────────────
newwt T2; mkdir -p "$WT/T2/cache"; echo x > "$WT/T2/cache/ui-design-override"
newwt T3
out=$(clean T2); out3=$(clean T3)
{ [ ! -d "$WT/T2" ] && [ ! -d "$WT/T3" ]; } && ok "只有排除檔／沒有 cache/ 的工作區照收" || err "T2/T3 沒被收：$out $out3"
{ [ -z "$(rescued_of T2)" ] && [ -z "$(rescued_of T3)" ]; } && ok "沒東西可救就不建資料夾" || err "不該有 rescued 資料夾"
has_branch feature/T3 && err "T3 已合進 stage，分支應一併刪除：$out3" || ok "已合進 stage 的分支一併刪除"

# ── 3. 搶救失敗 → 工作區不能收 ─────────────────────────────────────
newwt T4; mkdir -p "$WT/T4/cache"; echo precious > "$WT/T4/cache/p.html"
mkdir -p "$R/cache/rescued"; chmod 555 "$R/cache/rescued"
out=$(clean T4)
chmod 755 "$R/cache/rescued"
{ [ -d "$WT/T4" ] && [ "$(cat "$WT/T4/cache/p.html")" = precious ]; } && ok "搶救失敗（目的地不可寫）時工作區與 cache/ 都留著" || err "搶救失敗卻收了工作區：$out"
has "$out" '搶救 cache/ 失敗' && ok "失敗原因有印" || err "沒印失敗原因：$out"

# ── 4. 搶救期間檔案被動 → 工作區不能收 ─────────────────────────────
newwt T5; mkdir -p "$WT/T5/cache"; echo v1 > "$WT/T5/cache/f.html"
out=$(LATE_CMD="echo late > '$WT/T5/cache/late.html'" clean T5)
{ [ -d "$WT/T5" ] && has "$out" '搶救期間有檔變動'; } && ok "搶救期間新增檔 → 不收" || err "新增檔沒擋住：$out"

newwt T6; mkdir -p "$WT/T6/cache"; echo v1 > "$WT/T6/cache/f.html"; touch -t 202001010000 "$WT/T6/cache/f.html"
out=$(LATE_CMD="echo v2-longer > '$WT/T6/cache/f.html'; touch -t 202001010000 '$WT/T6/cache/f.html'" clean T6)
{ [ -d "$WT/T6" ] && has "$out" '搶救期間有檔變動'; } && ok "覆寫並保留舊 mtime → 靠 ctime 擋住" || err "保留舊 mtime 的覆寫沒擋住：$out"

newwt T10; mkdir -p "$WT/T10/cache"; echo a > "$WT/T10/cache/a.html"; echo b > "$WT/T10/cache/b.html"
out=$(LATE_CMD="rm -f '$WT/T10/cache/b.html'" clean T10)
{ [ -d "$WT/T10" ] && has "$out" '搶救期間有檔變動'; } && ok "搶救期間刪檔（檔數變少）→ 不收" || err "刪檔沒擋住：$out"

# ── 4b. 副本被弄壞（sha256 不一致）→ 工作區不能收 ───────────────────
newwt T9; mkdir -p "$WT/T9/cache"; echo good > "$WT/T9/cache/g.html"
out=$(CORRUPT_COPY=1 clean T9)
{ [ -d "$WT/T9" ] && has "$out" 'sha256 不一致'; } && ok "副本與原檔 sha256 不一致 → 不收" || err "壞副本沒擋住：$out"

# ── 5. 整批收（--merged --yes）：每個都處理，stdin 沒被吃掉；上面留著的也能重試成功 ───
newwt T7; newwt T8
for t in T7 T8; do mkdir -p "$WT/$t/cache/demos"; echo "$t" > "$WT/$t/cache/demos/x.html"; done
out=$(clean --merged --yes)
left=$(ls "$WT" 2>/dev/null | tr '\n' ' ')
[ -z "${left// /}" ] && ok "--merged --yes 把所有可收的都收了（含前面被擋的 T4/T5/T6 重試）" || err "還有工作區留著：${left}｜${out}"
for t in T7 T8; do
  D=$(rescued_of $t)
  [ -n "$D" ] && [ "$(cat "$D/demos/x.html" 2>/dev/null)" = "$t" ] && ok "$t 在整批收的路徑上也被搶救" || err "$t 沒被搶救"
done
D=$(rescued_of T4); [ -n "$D" ] && [ "$(cat "$D/p.html" 2>/dev/null)" = precious ] && ok "T4 重試後搶救成功" || err "T4 重試後沒有備份"

# ══ 二、「可不可以收」的判斷 ══════════════════════════════════════════
# 佈置的先後有講究：N1 的 commit 用現在的時間，它合進 stage 之後 stage 的最新一筆就是「剛剛」，
# 之後才開、自己沒有 commit 的工作區會跟著被當成剛動過——所以 N1 排在後面。
# M1：已合進 stage 又乾淨 → 可收，分支一併刪
newwt M1; commit "$WT/M1" m1.txt
g merge -q --no-edit feature/M1; g push -q origin stage
# U1：有 commit 還沒合進 stage → 保留
newwt U1; commit "$WT/U1" u1.txt
# D1：沒有自己的 commit，但有未提交的檔 → 保留
newwt D1; echo wip > "$WT/D1/wip.txt"
# TG：有還沒合的 commit，但有人打了同名 tag 指到 stage 上——tag 不能頂替分支被判成「已合流」
newwt TG; commit "$WT/TG" tg.txt
g tag feature/TG stage
# on-prod：停在正式分支上的工作區 → 可以收（把分支釋放出來），但 prod 分支本身永遠不刪
g branch prod stage
git -C "$R" worktree add -q "$WT/on-prod" prod >/dev/null 2>&1
# N1：已合流又乾淨，但剛剛才 commit → 整批收先跳過，指名收可以
newwt N1
( unset GIT_AUTHOR_DATE GIT_COMMITTER_DATE; commit "$WT/N1" n1.txt )
g merge -q --no-edit feature/N1; g push -q origin stage
# F1：由「別台機器」合進遠端的 stage（用網址推，本機記得的 origin/stage 不會跟著動）
#     → 一定要先 fetch 才看得出它已經合流；主目錄的 stage 還沒有它，所以分支先留著
newwt F1; commit "$WT/F1" f1.txt
git -C "$WT/F1" push -q "$O" HEAD:stage >/dev/null 2>&1
[ "$(git -C "$R" rev-parse origin/stage)" != "$(git -C "$O" rev-parse stage)" ] \
  && ok "前提：本機記得的 origin/stage 還沒看到 F1（腳本得自己 fetch）" \
  || err "前提不成立：本機的 origin/stage 已經是最新，測不到 fetch"
stage_sha_before=$(git -C "$O" rev-parse stage)
all_there() { local t; for t in M1 U1 D1 TG on-prod N1 F1; do [ -d "$WT/$t" ] || return 1; done; }

# ── 6. --list：只列現況，不動任何東西 ───────────────────────────────
out=$(clean --list)
all_there && ok "--list 不動任何工作區" || err "--list 之後有工作區不見了：$(ls "$WT" | tr '\n' ' ')"
has "$(row "$out" M1)" '已合進 stage・可收' && ok "--list：已合流又乾淨的標「可收」" || err "--list 的 M1 不對：$(row "$out" M1)"
has "$(row "$out" U1)" '尚未合進 stage・保留' && ok "--list：沒合的標「保留」" || err "--list 的 U1 不對：$(row "$out" U1)"
has "$(row "$out" D1)" '1 個未提交' && ok "--list：有未提交的講出幾個" || err "--list 的 D1 不對：$(row "$out" D1)"
has "$(row "$out" TG)" '尚未合進 stage・保留' && ok "--list：同名 tag 指到 stage 的分支仍是「保留」" || err "--list 的 TG 不對：$(row "$out" TG)"
has "$(row "$out" on-prod)" '佔用 prod 分支' && ok "--list：停在正式分支上的講出佔用哪一條" || err "--list 的 on-prod 不對：$(row "$out" on-prod)"
has "$(row "$out" N1)" '分鐘前才 commit' && ok "--list：剛 commit 過的有註明整批收會跳過" || err "--list 的 N1 不對：$(row "$out" N1)"

# ── 7. --merged（不加 --yes）：只預覽 ───────────────────────────────
out=$(clean --merged)
all_there && ok "--merged 不加 --yes 只預覽、不動手" || err "預覽就把工作區收掉了：$(ls "$WT" | tr '\n' ' ')"
can="${out%%先留著*}"; held=""; has "$out" '先留著' && held="${out#*先留著}"
for t in M1 on-prod F1; do
  has "$(row "$can" $t)" "worktrees/$t" && ok "預覽列出 ${t}" || err "預覽沒列出 ${t}：$out"
done
for t in U1 D1 TG; do
  [ -z "$(row "$out" $t)" ] && ok "預覽沒列 ${t}" || err "預覽不該列出 ${t}：$out"
done
{ [ -z "$(row "$can" N1)" ] && has "$held" 'worktrees/N1 '; } \
  && ok "預覽：剛 commit 過的 N1 不在可收清單，另外列在「先留著」" || err "預覽的 N1 位置不對：$out"

# ── 8. 指名收：不可收的擋下來（結束碼不是 0），找不到的講清楚 ─────────
out=$(clean U1); rc=$?
{ [ -d "$WT/U1" ] && [ "$rc" -ne 0 ] && has "$out" '尚未合進 stage'; } && ok "指名收沒合的 U1 → 不收" || err "U1 沒擋住（結束碼 ${rc}）：$out"
out=$(clean D1); rc=$?
{ [ -d "$WT/D1" ] && [ "$rc" -ne 0 ] && has "$out" '未提交'; } && ok "指名收有未提交的 D1 → 不收" || err "D1 沒擋住（結束碼 ${rc}）：$out"
out=$(clean TG); rc=$?
{ [ -d "$WT/TG" ] && [ "$rc" -ne 0 ]; } && ok "指名收 TG（同名 tag 指到 stage）→ 不收" || err "TG 被同名 tag 騙過去了（結束碼 ${rc}）：$out"
out=$(clean NOPE); rc=$?
{ [ "$rc" = 2 ] && has "$out" '找不到工作區'; } && ok "指名一個不存在的 → 結束碼 2" || err "不存在的名稱沒講清楚（結束碼 ${rc}）：$out"
# 人站在要收的工作區裡，用絕對路徑叫主目錄那一份腳本：也要認得出來
out=$( cd "$WT/M1" && bash "$R/scripts/worktree-clean.sh" M1 2>&1 ); rc=$?
{ [ -d "$WT/M1" ] && [ "$rc" -ne 0 ] && has "$out" '你正在這個工作區裡面'; } \
  && ok "站在 M1 裡面叫主目錄的腳本收 M1 → 不收" || err "站在裡面還是收了（結束碼 ${rc}）：$out"

# ── 9. --merged --yes：真的收，只收該收的 ───────────────────────────
out=$(clean --merged --yes)
for t in M1 on-prod F1; do
  [ ! -d "$WT/$t" ] && ok "--yes 收掉 ${t}" || err "--yes 沒收 ${t}：$out"
done
for t in U1 D1 TG N1; do
  [ -d "$WT/$t" ] && ok "保留 ${t}" || err "${t} 不該被收：$out"
done
has "$out" '跳過 .claude/worktrees/N1' && has "$out" '分鐘前才 commit' && ok "--yes 有講 N1 為什麼跳過" || err "沒講 N1 為什麼跳過：$out"
has_branch feature/M1 && err "feature/M1 已合進 stage，分支應一併刪除" || ok "feature/M1 分支一併刪除"
{ has_branch feature/F1 && has "$out" '分支 feature/F1 先留著'; } \
  && ok "主目錄的 stage 還沒有 F1 的 commit → 分支先留著並講原因" || err "feature/F1 的處理不對：$out"
has_branch prod && ok "prod 分支本身保留" || err "prod 分支被刪了"
has_branch stage && ok "stage 分支本身保留" || err "stage 分支被刪了"
has_branch feature/U1 && has_branch feature/TG && ok "沒合的分支都還在（含同名 tag 的 TG）" || err "沒合的分支被刪了"
[ "$(git -C "$O" rev-parse stage)" = "$stage_sha_before" ] && ok "遠端的 stage 沒被動到" || err "遠端的 stage 被動到了"

# ── 10. 剛 commit 過的：指名收可以 ──────────────────────────────────
out=$(clean N1)
[ ! -d "$WT/N1" ] && ok "指名收剛 commit 過的 N1 → 收得掉（是你自己點名的）" || err "指名收 N1 沒收：$out"

# ── 11. fetch 失敗：工作區照收，但分支不刪 ──────────────────────────
# 本機記得的遠端狀態可能是舊的（例：遠端的 stage 被退回過），確認不了就不刪
newwt X1
mv "$O" "$O.offline"
out=$(clean X1)
mv "$O.offline" "$O"
[ ! -d "$WT/X1" ] && ok "fetch 失敗：已合流的工作區照收" || err "fetch 失敗：X1 沒收：$out"
{ has_branch feature/X1 && has "$out" 'fetch 失敗'; } && ok "fetch 失敗：分支保留並講原因" || err "fetch 失敗還是刪了 feature/X1，或沒講原因：$out"

# ── 12. 還沒設遠端的專案：跟本機的 stage 比 ─────────────────────────
S="$TMP/solo"; mkrepo "$S" stage
git -C "$S" worktree add -q -b feature/L1 "$S/.claude/worktrees/L1" stage >/dev/null 2>&1
git -C "$S" worktree add -q -b feature/L2 "$S/.claude/worktrees/L2" stage >/dev/null 2>&1
commit "$S/.claude/worktrees/L2" l2.txt
out=$( cd "$S" && bash scripts/worktree-clean.sh --list 2>&1 )
{ has "$(row "$out" L1)" '已合進 stage・可收' && has "$(row "$out" L2)" '尚未合進 stage・保留' && has "$out" '遠端還沒有 stage'; } \
  && ok "沒有遠端：--list 跟本機的 stage 比，並講明是跟本機比" || err "沒有遠端時 --list 不對：$out"
out=$( cd "$S" && bash scripts/worktree-clean.sh --merged --yes 2>&1 )
{ [ ! -d "$S/.claude/worktrees/L1" ] && [ -d "$S/.claude/worktrees/L2" ]; } \
  && ok "沒有遠端：已合進本機 stage 的收掉、沒合的留著" || err "沒有遠端時整批收不對：$out"
has "$out" 'fetch 失敗' && err "沒有遠端不該報 fetch 失敗：$out" || ok "沒有遠端不算 fetch 失敗"
git -C "$S" show-ref --verify --quiet refs/heads/feature/L1 && err "沒有遠端：feature/L1 應一併刪除：$out" || ok "沒有遠端：已合流的分支照樣一併刪除"

# ── 13. 連 stage 分支都沒有：分不出誰已經合流，全部保留 ──────────────
Z="$TMP/nostage"; mkrepo "$Z" main
git -C "$Z" worktree add -q -b feature/Z1 "$Z/.claude/worktrees/Z1" main >/dev/null 2>&1
out=$( cd "$Z" && bash scripts/worktree-clean.sh --merged --yes 2>&1 )
{ [ -d "$Z/.claude/worktrees/Z1" ] && has "$out" '找不到 stage 分支'; } \
  && ok "沒有 stage 分支：不收，並講找不到 stage" || err "沒有 stage 分支時不該收：$out"

# ── 14. 工作區佔著 stage（主目錄停在別的分支）：收掉只是把分支還回來，stage 本身不能被刪（模板內補的）──
# 第 9 節的「stage 分支本身保留」是主目錄自己停在 stage 上，git 本來就不刪正在用的分支，守不住「stage 是保護分支」這個設定
P="$TMP/onstage"; mkrepo "$P" stage
git -C "$P" checkout -q -b parking >/dev/null 2>&1
git -C "$P" worktree add -q "$P/.claude/worktrees/on-stage" stage >/dev/null 2>&1
out=$( cd "$P" && bash scripts/worktree-clean.sh --list 2>&1 )
has "$(row "$out" on-stage)" '佔用 stage 分支' && ok "--list：佔著 stage 的工作區講出佔用哪一條" || err "--list 的 on-stage 不對：$(row "$out" on-stage)"
out=$( cd "$P" && bash scripts/worktree-clean.sh on-stage 2>&1 )
{ [ ! -d "$P/.claude/worktrees/on-stage" ] && has "$out" '分支 stage 已釋放'; } && ok "收掉佔著 stage 的工作區：分支釋放出來" || err "佔著 stage 的工作區沒收掉，或沒講分支已釋放：$out"
git -C "$P" show-ref --verify --quiet refs/heads/stage && ok "收掉佔著 stage 的工作區後，stage 分支本身還在" || err "stage 分支被刪了：$out"

[ "$fail" = 0 ] && echo "[worktree-clean-rescue-test] OK" || { echo "[worktree-clean-rescue-test] FAILED"; exit 1; }
