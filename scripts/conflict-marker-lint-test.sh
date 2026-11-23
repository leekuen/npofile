#!/usr/bin/env bash
# scripts/conflict-marker-lint.sh 與 .githooks/pre-commit 的測試（源專案 v5.39.0）。守門工具自己也要有測試。
#
# 在暫存的 git repo 裡真的做衝突合併、cherry-pick、rebase（身分用環境變數帶進去，不依賴這台機器的 git 設定）。
# 不碰真的 repo、不連網路。要驗的事：
#   ・標記殘留要被擋、解乾淨放行、markdown 7 個等號標題底線不誤報、舊檔本來就有標記而這次沒動不擋；
#   ・pre-commit 真的擋得到 merge／cherry-pick 解衝突後的 commit；檢查自己跑不起來時只警告、放行；
#   ・`git rebase --continue` 擋不到（這是推送前要用 --range 再掃一次的原因，也是「故意種該紅的」）→ --range 擋得到；
#   ・--range：遠端 sha 全 0 → 對 origin/stage 的 merge-base；連 origin/stage 都沒有 → 被推的 commit 整棵都查；
#     遠端不認得 → 結束碼 2（不能當成沒標記）；
#   ・整棵掃描只看追蹤檔案，從子資料夾跑也是掃整棵；不是 git 版本庫 → 結束碼 2。
# 驗證本身：LINT=<別版 lint> 可換成「什麼都不擋」的版本，應有案例變紅。
set -uo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
LINT_SRC="${LINT:-$SRC/scripts/conflict-marker-lint.sh}"
# 從 git hook 裡被叫起來時，環境會帶著 GIT_DIR／GIT_WORK_TREE／GIT_INDEX_FILE，
# 沙盒裡的 git 會全部打到真的 repo。先清掉。
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX
# 使用者自己的 git 設定（簽章、hooksPath、diff 的預設行為）不帶進沙盒
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com

fail=0
T="[conflict-marker-lint-test]"
err() { echo "${T} ✗ $1" >&2; fail=1; }
ok() { echo "${T} ✓ $1"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
TMP="$(cd "$TMP" && pwd -P)"
# 暫存目錄本身萬一位在某個 repo 底下，「不是 git 版本庫」那一條會測到那個 repo 上。叫 git 往上找到沙盒為止。
export GIT_CEILING_DIRECTORIES="$TMP"
ZERO=0000000000000000000000000000000000000000

R="$TMP/repo"
mkdir -p "$R/scripts" "$R/.githooks" "$TMP/plain"
cp "$LINT_SRC" "$R/scripts/conflict-marker-lint.sh"
cp "$SRC/.githooks/pre-commit" "$R/.githooks/pre-commit"
chmod +x "$R/.githooks/pre-commit"
cd "$R" || exit 1
git init -q . 2>/dev/null || { echo "${T} ✗ 沙盒建不起來：git init" >&2; exit 1; }
# 這個沙盒的 .githooks/ 裡只有 pre-commit；鋪底的 commit 一律帶 --no-verify，要測 hook 的那幾步才不帶
git config core.hooksPath .githooks
g() { git "$@"; }

# 測試檔自己不能有行首的衝突標記（不然整棵掃描會掃到自己），所以用變數組出來
MK_OPEN='<<<<<<<'
MK_MID='======='
MK_CLOSE='>>>>>>>'

check() {  # check <說明> <期望結束碼> <實際結束碼>
  if [ "$3" = "$2" ]; then ok "$1"; else err "$1（期望 ${2} 實際 ${3}）"; sed 's/^/      /' "$TMP/out" 2>/dev/null | head -8 >&2; fi
}
said() {  # said <說明> <上一步的輸出裡要有的字>
  if grep -qF -- "$2" "$TMP/out"; then ok "$1"; else err "$1（輸出裡找不到「${2}」）"; sed 's/^/      /' "$TMP/out" | head -8 >&2; fi
}
lint() { bash scripts/conflict-marker-lint.sh "$@" >"$TMP/out" 2>&1; echo $?; }

printf 'a\nb\nc\n' > f.txt
g add f.txt scripts .githooks 2>/dev/null
g commit -qm base --no-verify
BASE=$(git rev-parse HEAD)
git update-ref refs/remotes/origin/stage "$BASE"

# 兩條互相衝突的分支
g checkout -qb left "$BASE"; printf 'a\nLEFT\nc\n' > f.txt; g add f.txt; g commit -qm left --no-verify; LEFT=$(git rev-parse HEAD)
g checkout -qb right "$BASE"; printf 'a\nRIGHT\nc\n' > f.txt; g add f.txt; g commit -qm right --no-verify; RIGHT=$(git rev-parse HEAD)

# 1. merge 衝突、標記殘留 → pre-commit 擋
g checkout -q left
g merge right >/dev/null 2>&1
g add f.txt
g commit -qm "merge with markers" >"$TMP/out" 2>&1
check "merge 衝突、標記殘留 → pre-commit 擋（commit 沒寫進去）" 1 "$([ "$(git rev-parse HEAD)" = "$LEFT" ] && echo 1 || echo 0)"
said "擋下訊息指出檔案與行號（f.txt:2）" 'f.txt:2'
said "擋下訊息講出是 pre-commit 擋的" '[pre-commit] ⛔'
# 2. 解乾淨 → 放行
printf 'a\nLEFT+RIGHT\nc\n' > f.txt; g add f.txt
g commit -qm "merge resolved" >"$TMP/out" 2>&1
check "解乾淨後 commit → 放行" 0 "$([ "$(git rev-parse HEAD)" != "$LEFT" ] && echo 0 || echo 1)"
if grep -q '⛔' "$TMP/out" || grep -q '⚠️' "$TMP/out"; then err "解乾淨後 commit：不該有擋下或警告的訊息"; else ok "解乾淨後 commit：沒有擋下或警告的訊息"; fi

# 3. markdown 7 個等號標題底線 → 放行（git diff --check 會誤報）
g checkout -q "$BASE"; g checkout -qb md
printf 'Title\n=======\ntext\n' > doc.md; g add doc.md
check "markdown 7 個等號標題底線 → --staged 放行" 0 "$(lint --staged)"
# 4. 舊檔本來就有標記、這次沒動 → 放行
printf 'x\n%s HEAD\ny\n%s\nz\n%s b\n' "$MK_OPEN" "$MK_MID" "$MK_CLOSE" > old.txt
g add doc.md old.txt; g commit -qm "old markers" --no-verify
printf 'new\n' > other.txt; g add other.txt
check "舊檔有標記、這次沒動 → --staged 放行" 0 "$(lint --staged)"
# 同一件事走 hook：真的 commit 一次（這一步不帶 --no-verify）。hook 要是掃整棵而不是只看這次的新增行，這裡會被擋
HEAD_BEFORE=$(git rev-parse HEAD)
g commit -qm "unrelated file" >"$TMP/out" 2>&1
check "舊檔有標記、這次 commit 沒動到它 → pre-commit 放行" 0 "$([ "$(git rev-parse HEAD)" != "$HEAD_BEFORE" ] && echo 0 || echo 1)"
# 5. 新增的行有標記 → 擋，而且行號對；內容剛好是 "++ " 開頭的新增行不被當成檔頭
printf '++ not a header\nok\n%s HEAD\n' "$MK_OPEN" > new.txt; g add new.txt
RC=$(lint --staged); check "新增行有標記 → --staged 擋" 1 "$RC"
said "行號是 3（前面有 \"++ \" 開頭的新增行也沒算錯）" 'new.txt:3:'
g reset -q new.txt; rm -f new.txt
# 縮排的標記（文件範例）→ 放行
printf '    %s HEAD\n' "$MK_OPEN" > indented.md; g add indented.md
check "縮排的標記（文件範例）→ 放行" 0 "$(lint --staged)"
g reset -q indented.md; rm -f indented.md
# 行首是 8 個以上的 < 或 >（不是 git 產生的標記，例：文件裡的分隔線）→ 放行
printf '%s< eight\n%s>\n' "$MK_OPEN" "$MK_CLOSE" > eight.txt; g add eight.txt
check "行首 8 個 < 或 >（不是衝突標記）→ --staged 放行" 0 "$(lint --staged)"
g reset -q eight.txt; rm -f eight.txt
# 只有結尾標記、後面沒接字（>>>>>>> 單獨一行）→ 擋
printf 'x\n%s\n' "$MK_CLOSE" > tail.txt; g add tail.txt
check "只剩結尾標記單獨一行 → --staged 擋" 1 "$(lint --staged)"
g reset -q tail.txt; rm -f tail.txt
# 使用者的 git 設了 diff.noprefix（差異不印 a/ b/ 前綴）→ 回報的檔名要完整（模板內補的）
git config diff.noprefix true
printf '%s HEAD\n' "$MK_OPEN" > np.txt; g add np.txt
RC=$(lint --staged); check "設了 diff.noprefix：新增行有標記 → --staged 照樣擋" 1 "$RC"
said "設了 diff.noprefix：--staged 回報的檔名完整（np.txt:1:）" ' np.txt:1:'
g reset -q np.txt; rm -f np.txt
git config --unset diff.noprefix

# 6. cherry-pick 衝突、標記殘留 → pre-commit 擋
g checkout -q -B pick "$LEFT"
g cherry-pick "$RIGHT" >/dev/null 2>&1
g add f.txt
HEAD_BEFORE=$(git rev-parse HEAD)
GIT_EDITOR=true g cherry-pick --continue >"$TMP/out" 2>&1
check "cherry-pick --continue 帶標記 → pre-commit 擋" 0 "$([ "$(git rev-parse HEAD)" = "$HEAD_BEFORE" ] && echo 0 || echo 1)"
g cherry-pick --abort >/dev/null 2>&1

# 7. rebase 衝突、不解直接 add → rebase --continue：pre-commit 擋不到（這就是推送前要再掃一次的原因），--range 擋得到
g checkout -q -B left2 "$LEFT"
g rebase right >/dev/null 2>&1
g add f.txt
GIT_EDITOR=true g rebase --continue >"$TMP/out" 2>&1
NEW=$(git rev-parse HEAD)
git show "$NEW:f.txt" > "$TMP/rebased.txt" 2>/dev/null
if [ "$NEW" != "$LEFT" ] && grep -q "^$MK_OPEN" "$TMP/rebased.txt"; then
  ok "（確認）rebase --continue 帶標記的 commit 被寫進去，pre-commit 擋不到"
else
  err "測試前提不成立：rebase --continue 沒有留下標記（git 行為變了？推送前那一道可能不再需要，請重新評估）"
fi
git update-ref refs/remotes/origin/stage "$RIGHT"
check "--range 擋得到 rebase 留下的標記" 1 "$(lint --range "$RIGHT" "$NEW")"
said "--range 的訊息指出檔案與行號（f.txt:2）" ' f.txt:2:'
check "--range 遠端 sha 全 0 → 對 origin/stage 的 merge-base，擋得到" 1 "$(lint --range "$ZERO" "$NEW")"
check "--range 遠端 sha 全 0、被推的 commit 就是 origin/stage 那一個（沒有新東西）→ 放行" 0 "$(lint --range "$ZERO" "$RIGHT")"
git config diff.noprefix true
RC=$(lint --range "$RIGHT" "$NEW"); check "設了 diff.noprefix：--range 照樣擋" 1 "$RC"
said "設了 diff.noprefix：--range 回報的檔名完整（f.txt:2:）" ' f.txt:2:'
git config --unset diff.noprefix
# 8. --range：乾淨的範圍放行；遠端不認得 → 2（不能把空輸出當成沒標記）
check "--range 乾淨的範圍 → 放行" 0 "$(lint --range "$BASE" "$LEFT")"
check "--range 遠端 sha 本機不認得 → 結束碼 2" 2 "$(lint --range 1111111111111111111111111111111111111111 "$NEW")"
said "遠端 sha 本機不認得：講明這次沒有檢查" '這次沒有檢查'
check "--range 少參數 → 結束碼 2" 2 "$(lint --range "$BASE")"
# 新專案第一次推：遠端 sha 全 0、本機連 origin/stage 都沒有 → 被推的 commit 整棵都查（模板內補的）
git update-ref -d refs/remotes/origin/stage
check "--range 遠端全 0、沒有 origin/stage：被推的 commit 裡有標記 → 擋" 1 "$(lint --range "$ZERO" "$NEW")"
said "沒有 origin/stage：訊息指出檔案與行號（f.txt:2）" ' f.txt:2:'
check "--range 遠端全 0、沒有 origin/stage：被推的 commit 乾淨 → 放行" 0 "$(lint --range "$ZERO" "$LEFT")"
git update-ref refs/remotes/origin/stage "$RIGHT"

# 9. 整棵掃描：只看追蹤檔案；有標記擋、乾淨放行
g checkout -q "$BASE"; g checkout -qb tree
check "整棵掃描：乾淨 → 放行" 0 "$(lint)"
printf '%s HEAD\nx\n' "$MK_OPEN" > untracked.txt
check "整棵掃描：未追蹤的檔案有標記 → 不看" 0 "$(lint)"
g add untracked.txt
check "整棵掃描：追蹤的檔案有標記 → 擋" 1 "$(lint)"
said "整棵掃描：訊息有檔案與行號（untracked.txt:1:）" ' untracked.txt:1: '
# 從子資料夾跑也是掃整棵（模板內補的：git grep 預設只看目前資料夾以下）
mkdir -p sub
( cd sub && bash ../scripts/conflict-marker-lint.sh >"$TMP/out" 2>&1 ); RC=$?
check "整棵掃描：人在子資料夾、標記在上層的檔 → 照樣擋" 1 "$RC"
g reset -q untracked.txt; rm -f untracked.txt
# 行首 8 個 < 不是衝突標記 → 整棵掃描也放行
printf '%s< eight\n' "$MK_OPEN" > eight.txt; g add eight.txt
check "整棵掃描：行首 8 個 <（不是衝突標記）→ 放行" 0 "$(lint)"
g reset -q eight.txt; rm -f eight.txt
# 不是 git 版本庫 → 2，而且不能說成檢查過了
( cd "$TMP/plain" && bash "$R/scripts/conflict-marker-lint.sh" >"$TMP/out" 2>&1 ); RC=$?
check "整棵掃描：不是 git 版本庫 → 結束碼 2" 2 "$RC"
said "不是 git 版本庫：講明這次沒有檢查" '這次沒有檢查'
# 10. 不認得的參數 → 2
check "不認得的參數 → 結束碼 2" 2 "$(lint --bogus)"
# git 自己出狀況（這裡用壞掉的 index 模擬）→ 2：版本庫裡明明有標記，不能因為 git 沒回東西就當成沒有
BK="$TMP/broken"
mkdir -p "$BK/scripts"
cp "$LINT_SRC" "$BK/scripts/conflict-marker-lint.sh"
( cd "$BK" && git init -q . && printf '%s HEAD\n' "$MK_OPEN" > m.txt && git add m.txt scripts \
  && git -c core.hooksPath=/dev/null commit -qm base && printf 'garbage' > .git/index ) >/dev/null 2>&1 \
  || { echo "${T} ✗ 沙盒建不起來：index 壞掉的版本庫" >&2; exit 1; }
( cd "$BK" && bash scripts/conflict-marker-lint.sh >"$TMP/out" 2>&1 ); RC=$?
check "整棵掃描：git 讀不了版本庫（index 壞掉）→ 結束碼 2" 2 "$RC"
said "整棵掃描：git 讀不了版本庫時講明這次沒有檢查" '這次沒有檢查'
( cd "$BK" && bash scripts/conflict-marker-lint.sh --staged >"$TMP/out" 2>&1 ); RC=$?
check "--staged：讀不到暫存區（index 壞掉）→ 結束碼 2" 2 "$RC"
said "--staged：讀不到暫存區時講明這次沒有檢查" '這次沒有檢查'

# 11. pre-commit：檢查自己跑不起來 → 警告「這次沒有檢查」、commit 照常進行（不因工具壞掉擋工作）
printf 'x\n' > broken1.txt; g add broken1.txt
printf '#!/usr/bin/env bash\nexit 2\n' > scripts/conflict-marker-lint.sh
HEAD_BEFORE=$(git rev-parse HEAD)
g commit -qm "lint cannot run" >"$TMP/out" 2>&1
check "pre-commit：檢查回結束碼 2（自己跑不起來）→ commit 照常進行" 0 "$([ "$(git rev-parse HEAD)" != "$HEAD_BEFORE" ] && echo 0 || echo 1)"
said "pre-commit：檢查跑不起來時講明這次沒有檢查" '這次沒有檢查'
rm -f scripts/conflict-marker-lint.sh
printf 'y\n' > broken2.txt; g add broken2.txt
HEAD_BEFORE=$(git rev-parse HEAD)
g commit -qm "lint missing" >"$TMP/out" 2>&1
check "pre-commit：檢查的檔案不在 → commit 照常進行" 0 "$([ "$(git rev-parse HEAD)" != "$HEAD_BEFORE" ] && echo 0 || echo 1)"
said "pre-commit：檢查的檔案不在時講明這次沒有檢查" '這次沒有檢查'
cp "$LINT_SRC" scripts/conflict-marker-lint.sh

[ "$fail" = 0 ] && echo "${T} 全部通過" || exit 1
