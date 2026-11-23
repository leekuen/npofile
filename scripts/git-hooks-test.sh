#!/usr/bin/env bash
# .githooks/pre-push、.githooks/post-commit、scripts/setup-hooks.sh 的測試
# （.githooks/pre-commit 的測試跟它呼叫的檢查放在一起：scripts/conflict-marker-lint-test.sh）。
#
# 分三段：
#   一、pre-push：把 git 會餵給 hook 的那幾行（<本地 ref> <本地 sha> <遠端 ref> <遠端 sha>）從檔案餵進去，
#       看每一道關卡該擋的擋、不該擋的不擋；最後對沙盒裡的遠端真的推幾次，確認被擋的推送沒有進到遠端。
#   二、post-commit：在沙盒裡真的 commit，看遠端有沒有多出那條分支。
#   三、setup-hooks.sh：只在沙盒的副本上跑，看 core.hooksPath 被設成什麼。
#
# 走查交代、條件確認兩道用的是真的那兩支檢查（scripts/walkthrough_record_lint.py、
# scripts/unconfirmed-conditions.sh）——這裡只驗 pre-push 接得對不對（推哪條分支才查、結束碼怎麼處理）；
# 它們認哪些寫法，由各自的測試在管。
#
# 全部在暫存資料夾裡自己建的版本庫上跑，要測的檔案都是複製進去的：不看也不動範本自己這一棵的 git 設定，
# 不連網路（遠端是沙盒裡的 bare 版本庫）。
#
# 改這支測試時別踩的三件事：
#   ・這支測試自己也會被 bash32-var-lint 與 conflict-marker-lint 掃到——有問題的範例不能直接寫在這裡，
#     一律用 printf 現場組出來（錢字號放在變數 D、衝突標記放在變數 MK_OPEN）。
#   ・hook 與檢查的輸出先收進檔案，案例沒過才印出來——免得全部通過時畫面上還看得到它們自己的 ⛔。
#   ・鋪底用的 git 指令一律走 fx（不讓任何 hook 跑）；要測 hook 的那一步才用一般的 git。
set -uo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
# 從 git hook 裡被叫起來時，環境會帶著 GIT_DIR／GIT_INDEX_FILE 這些，沙盒裡的 git 會全部打到真的版本庫。先清掉。
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX
# 使用者自己的 git 設定（簽章、hooksPath、預設分支名）不帶進沙盒
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
export GIT_EDITOR=true GIT_MERGE_AUTOEDIT=no
# 票規的生效日固定下來：兩支票的檢查才不會跟著範本 scripts/framework-config.sh 當下的設定值變
export TICKET_RULES_SINCE=2025-06-01

fail=0
T="[git-hooks-test]"
err() { echo "${T} ✗ $1" >&2; fail=1; }
ok() { echo "${T} ✓ $1"; }

TMP="$(mktemp -d)"
# chmod：有一條案例會把沙盒裡的 .git 設成唯讀，中途斷掉也要刪得掉
trap 'chmod -R u+w "$TMP" 2>/dev/null; rm -rf "$TMP"' EXIT
# macOS 的暫存目錄會經過一層連結（/var → /private/var）。統一成實際路徑，比對路徑才對得起來。
TMP="$(cd "$TMP" && pwd -P)"
# 叫 git 往上找版本庫時到沙盒為止（沙盒一律放在暫存資料夾的「子資料夾」，這個上限才擋得到）
export GIT_CEILING_DIRECTORIES="$TMP"
mkdir -p "$TMP/cwd"

must() { "$@" >/dev/null 2>&1 || { echo "${T} ✗ 沙盒建不起來：$*" >&2; exit 1; }; }
show() { sed 's/^/      /' "$TMP/out" 2>/dev/null | head -8 >&2; }
check() {  # check <說明> <期望結束碼> <實際結束碼>
  if [ "$3" = "$2" ]; then ok "$1"; else err "$1（期望 ${2} 實際 ${3}）"; show; fi
}
same() {  # same <說明> <期望的字> <實際的字>
  if [ "$3" = "$2" ]; then ok "$1"; else err "$1（期望「${2}」實際「${3}」）"; show; fi
}
said() {  # said <說明> <上一步的輸出裡要有的字>
  if grep -qF -- "$2" "$TMP/out"; then ok "$1"; else err "$1（輸出裡找不到「${2}」）"; show; fi
}
unsaid() {  # unsaid <說明> <上一步的輸出裡不該有的字>
  if grep -qF -- "$2" "$TMP/out"; then err "$1（輸出裡不該有「${2}」）"; show; else ok "$1"; fi
}
silent() {  # silent <說明>：上一步完全沒有輸出
  if [ -s "$TMP/out" ]; then err "$1（不該有任何輸出）"; show; else ok "$1"; fi
}

MK_OPEN='<<<<<<<'
D='$'
ZERO=0000000000000000000000000000000000000000
UNKNOWN=1111111111111111111111111111111111111111

# fx：鋪底用的 git，不讓任何 hook 跑
fx() { git -c core.hooksPath=/dev/null "$@"; }
# put <目的資料夾> <相對路徑…>：把範本裡的檔案複製進沙盒
put() {
  local dst="$1" f
  shift
  for f in "$@"; do
    mkdir -p "$dst/$(dirname "$f")"
    cp "$SRC/$f" "$dst/$f" || { echo "${T} ✗ 沙盒建不起來：找不到 ${f}" >&2; exit 1; }
  done
}

# ═════════ 沙盒：一個放了 hooks 與四支檢查的版本庫，三個 bare 遠端 ═════════
R="$TMP/repo"
put "$R" .githooks/pre-commit .githooks/pre-push .githooks/post-commit \
  scripts/setup-hooks.sh scripts/conflict-marker-lint.sh scripts/bash32-var-lint.sh \
  scripts/walkthrough_record_lint.py scripts/unconfirmed-conditions.sh
chmod +x "$R"/.githooks/*
cd "$R" || exit 1
must git init -q .
must git symbolic-ref HEAD refs/heads/stage
printf 'sandbox\n' > README.md
must fx add README.md .githooks scripts
must fx commit -q -m base
BASE="$(git rev-parse HEAD)"

# new_origin <路徑>：建一個 bare 遠端，stage 與 prod 都指到 BASE
new_origin() {
  must git init -q --bare "$1"
  must git --git-dir="$1" symbolic-ref HEAD refs/heads/stage
  ( cd "$R" && fx push -q "$1" "$BASE:refs/heads/stage" "$BASE:refs/heads/prod" ) >/dev/null 2>&1 \
    || { echo "${T} ✗ 沙盒建不起來：遠端 ${1} 鋪不了底" >&2; exit 1; }
}
O="$TMP/origin.git"        # 一、pre-push 逐條案例用
OE="$TMP/origin-e2e.git"   # 一、真的推用
OC="$TMP/origin-pc.git"    # 二、post-commit 用
new_origin "$O"
new_origin "$OE"
new_origin "$OC"
must git remote add origin "$O"
must fx fetch -q origin

# 幾個「要推的 commit」，各自從 BASE 長出一個 commit
start() { must fx checkout -q -B "$1" "$BASE"; }
commit_all() { must fx add -- "$@"; must fx commit -q -m fixture; }
# 假票的內文刻意避開另一道檢查的觸發字，測這一道時才不會被另一道擋下
w_ticket() {  # w_ticket <yes|no>：〈這次可能會弄壞什麼〉有一條 W1；yes＝開發備註裡交代走過了
  mkdir -p tickets
  printf -- '---\nid: TK-12\nstatus: 開發中\ncreated: 2025-06-10\n---\n\n# 示範票\n\n## 這次可能會弄壞什麼\n\n- W1 清單頁的排序\n\n## 開發備註\n\n- 根因：略\n' > tickets/TK-12-示範票.md
  if [ "$1" = yes ]; then
    printf -- '- 走查（真人眼看）W1 清單頁的排序：順序跟原本一樣\n' >> tickets/TK-12-示範票.md
  fi
}
c_ticket() {  # c_ticket <那一列的「狀態 | 回答日 |」>：〈條件確認〉有一列
  mkdir -p tickets
  printf -- '---\nid: TK-13\nstatus: 開發中\ncreated: 2025-06-10\n---\n\n## 需求細節\n\n略\n\n## 這次可能會弄壞什麼\n\n不適用：只改文字\n\n## 條件確認\n\n| 條件（含分母） | 符合 | 擋掉 | 狀態 | 回答日 |\n|---|---|---|---|---|\n| 條件甲（分母：100 張） | 10 張 | 90 張 | %s\n' "$1" > tickets/TK-13-示範票二.md
}

start fx-mark
printf 'doc\n%s HEAD\nx\n' "$MK_OPEN" > notes.md
commit_all notes.md
S_MARK="$(git rev-parse HEAD)"    # 有沒解掉的衝突標記（notes.md 第 2 行）
start fx-clean
printf 'ok\n' > ok.txt
commit_all ok.txt
S_CLEAN="$(git rev-parse HEAD)"   # 乾淨
start fx-wbad
w_ticket no
commit_all tickets
S_WBAD="$(git rev-parse HEAD)"    # 票的 W1 沒交代走查
start fx-wok
w_ticket yes
commit_all tickets
S_WOK="$(git rev-parse HEAD)"     # 票的 W1 交代了
start fx-cbad
c_ticket '未確認 | |'
commit_all tickets
S_CBAD="$(git rev-parse HEAD)"    # 〈條件確認〉有一列未確認
start fx-cok
c_ticket '已確認 | 2025-06-10 |'
commit_all tickets
S_COK="$(git rev-parse HEAD)"     # 〈條件確認〉都已確認
start work                        # 工作樹回到乾淨的 BASE

# ═════════ 一、pre-push：逐條餵 stdin ═════════
IN="$TMP/stdin"
# one／also：照 git 的格式寫一行（also 是再加一行）：<本地 ref> <本地 sha> <遠端 ref> <遠端 sha>
one() { printf '%s %s %s %s\n' "$1" "$2" "$3" "$4" >"$IN"; }
also() { printf '%s %s %s %s\n' "$1" "$2" "$3" "$4" >>"$IN"; }
to_stage() { one refs/heads/stage "$1" refs/heads/stage "${2:-$BASE}"; }  # to_stage <要推的 sha> [遠端現況 sha]
to_prod() { one refs/heads/prod "$1" refs/heads/prod "${2:-$BASE}"; }
to_dev() { one refs/heads/feature/TK-12 "$1" refs/heads/feature/TK-12 "$ZERO"; }
pp() { ( cd "$R" && bash .githooks/pre-push origin "$O" <"$IN" >"$TMP/out" 2>&1 ); echo $?; }

: >"$IN"
code=$(pp)
check "pre-push：沒有要推的東西 → 放行" 0 "$code"
silent "pre-push：沒有要推的東西 → 什麼都不跑（沒有輸出）"

# 開發分支：內容再有問題也不查（自動推每次 commit 都會經過這裡，不能拖慢、不能擋）
to_dev "$S_MARK"
code=$(pp)
check "pre-push：推開發分支（有衝突標記）→ 不查、放行" 0 "$code"
silent "pre-push：推開發分支（有衝突標記）→ 什麼都不跑（沒有輸出）"
to_dev "$S_WBAD"
code=$(pp)
check "pre-push：推開發分支（票的 W 沒交代）→ 不查、放行" 0 "$code"
to_dev "$S_CBAD"
code=$(pp)
check "pre-push：推開發分支（條件未確認）→ 不查、放行" 0 "$code"
one refs/heads/stage-backup "$S_MARK" refs/heads/stage-backup "$ZERO"
code=$(pp)
check "pre-push：推名字只是以 stage 開頭的分支（stage-backup，有衝突標記）→ 不查" 0 "$code"
one refs/tags/v1 "$S_MARK" refs/tags/v1 "$ZERO"
code=$(pp)
check "pre-push：推標籤（有衝突標記）→ 不查" 0 "$code"

# 乾淨的 stage／prod
to_stage "$S_CLEAN"
code=$(pp)
check "pre-push：推 stage、乾淨 → 放行" 0 "$code"
unsaid "pre-push：乾淨的 stage → 沒有擋下的訊息" "⛔"
unsaid "pre-push：乾淨的 stage → 沒有警告" "⚠️"
unsaid "pre-push：乾淨的 stage → 沒有哪一道說這次沒有檢查" "這次沒有檢查"
to_prod "$S_CLEAN"
code=$(pp)
check "pre-push：推 prod、乾淨 → 放行" 0 "$code"
unsaid "pre-push：乾淨的 prod → 沒有擋下的訊息" "⛔"
unsaid "pre-push：乾淨的 prod → 沒有哪一道說這次沒有檢查" "這次沒有檢查"

# 衝突標記：stage、prod 都查
to_stage "$S_MARK"
code=$(pp)
check "pre-push：推 stage、範圍內有衝突標記 → 擋" 1 "$code"
said "pre-push：衝突標記 → 指出檔案與行號（notes.md:2）" "notes.md:2"
said "pre-push：衝突標記 → 講明是哪一道擋的" "[pre-push] ⛔ 推送範圍內有沒解掉的衝突標記"
to_prod "$S_MARK"
code=$(pp)
check "pre-push：推 prod、範圍內有衝突標記 → 擋" 1 "$code"
said "pre-push：推 prod 的衝突標記 → 講明是哪一道擋的" "[pre-push] ⛔ 推送範圍內有沒解掉的衝突標記"
# 看的是「推到哪裡」，不是本機那條分支叫什麼
one refs/heads/feature/TK-12 "$S_MARK" refs/heads/stage "$BASE"
code=$(pp)
check "pre-push：把開發分支直接推成遠端的 stage（有衝突標記）→ 擋" 1 "$code"
one refs/heads/stage "$S_MARK" refs/heads/feature/TK-12 "$ZERO"
code=$(pp)
check "pre-push：把本機的 stage 推成遠端的開發分支 → 不查" 0 "$code"

# 走查交代：只查推 stage
to_stage "$S_WBAD"
code=$(pp)
check "pre-push：推 stage、票的 W 編號沒交代走查 → 擋" 1 "$code"
said "pre-push：走查交代 → 講明是哪一道擋的" "[pre-push] ⛔ 有票的 W 編號沒交代走查"
said "pre-push：走查交代 → 看得到是哪一張票（TK-12）" "TK-12"
to_prod "$S_WBAD"
code=$(pp)
check "pre-push：推 prod、票的 W 編號沒交代走查 → 這一道不查、放行" 0 "$code"
unsaid "pre-push：推 prod（票的 W 沒交代）→ 沒有擋下的訊息" "⛔"
to_stage "$S_WOK"
code=$(pp)
check "pre-push：推 stage、票的 W 編號都交代了 → 放行" 0 "$code"
unsaid "pre-push：W 編號都交代了 → 沒有擋下的訊息" "⛔"

# 條件確認：只查推 stage
to_stage "$S_CBAD"
code=$(pp)
check "pre-push：推 stage、〈條件確認〉有一列還沒確認 → 擋" 1 "$code"
said "pre-push：條件確認 → 講明是哪一道擋的" "[pre-push] ⛔ 有票的〈條件確認〉或〈數字口徑〉還沒經案主確認"
said "pre-push：條件確認 → 看得到是哪一張票（TK-13）" "TK-13"
to_prod "$S_CBAD"
code=$(pp)
check "pre-push：推 prod、〈條件確認〉有一列還沒確認 → 這一道不查、放行" 0 "$code"
unsaid "pre-push：推 prod（條件未確認）→ 沒有擋下的訊息" "⛔"
to_stage "$S_COK"
code=$(pp)
check "pre-push：推 stage、〈條件確認〉每一列都已確認 → 放行" 0 "$code"
unsaid "pre-push：條件都已確認 → 沒有擋下的訊息" "⛔"

# 某一道檢查自己跑不起來 → 講明「這次沒有檢查」、放行（不因工具壞掉擋工作，也不把沒查說成查過）
# stub <檔> <sh|py>：把沙盒裡的那支檢查換成「一跑就回結束碼 2」的替身
stub() {
  case "$2" in
    py) printf 'import sys\nsys.exit(2)\n' > "$R/$1" ;;
    *) printf '#!/usr/bin/env bash\nexit 2\n' > "$R/$1" ;;
  esac
}
for spec in \
  "scripts/conflict-marker-lint.sh|sh|衝突標記檢查跑不起來" \
  "scripts/walkthrough_record_lint.py|py|走查交代檢查跑不起來" \
  "scripts/unconfirmed-conditions.sh|sh|條件確認檢查跑不起來" \
  "scripts/bash32-var-lint.sh|sh|bash 3.2 變數檢查跑不起來"; do
  f="${spec%%|*}"
  rest="${spec#*|}"
  kind="${rest%%|*}"
  name="${rest#*|}"
  to_stage "$S_CLEAN"
  stub "$f" "$kind"
  code=$(pp)
  check "pre-push：${name}（回結束碼 2）→ 放行" 0 "$code"
  said "pre-push：${name}（回結束碼 2）→ 講出是哪一道" "${name}"
  said "pre-push：${name}（回結束碼 2）→ 講明這次沒有檢查" "這次沒有檢查"
  rm -f "$R/$f"
  code=$(pp)
  check "pre-push：${name}（檔案不在）→ 放行" 0 "$code"
  said "pre-push：${name}（檔案不在）→ 講出是哪一道" "${name}"
  put "$R" "$f"
done
# 一道跑不起來，後面幾道照樣要查
stub scripts/conflict-marker-lint.sh sh
to_stage "$S_WBAD"
code=$(pp)
check "pre-push：衝突標記檢查跑不起來時，後面的走查交代照樣查（W 沒交代 → 擋）" 1 "$code"
put "$R" scripts/conflict-marker-lint.sh
stub scripts/walkthrough_record_lint.py py
to_stage "$S_CBAD"
code=$(pp)
check "pre-push：走查交代檢查跑不起來時，後面的條件確認照樣查（未確認 → 擋）" 1 "$code"
put "$R" scripts/walkthrough_record_lint.py
# 用真的檢查：遠端現況的 sha 本機不認得（別人推過、自己還沒 fetch）→ 衝突標記那一道查不了
to_stage "$S_CLEAN" "$UNKNOWN"
code=$(pp)
check "pre-push：遠端現況的 sha 本機不認得 → 放行" 0 "$code"
said "pre-push：遠端現況的 sha 本機不認得 → 講明衝突標記這一道這次沒有檢查" "衝突標記檢查跑不起來"

# bash 3.2 變數寫法：量的是目前工作樹（還沒進版控的也算）
printf 'n=1\necho "%sn：壞"\n' "$D" > "$R/bad.sh"
to_stage "$S_CLEAN"
code=$(pp)
check "pre-push：工作樹裡有腳本的變數後面直接接全形字 → 推 stage 擋" 1 "$code"
said "pre-push：bash 3.2 變數寫法 → 講明是哪一道擋的" "[pre-push] ⛔ bash32-var-lint 沒過"
said "pre-push：bash 3.2 變數寫法 → 指出檔案與行號（bad.sh:2:）" "bad.sh:2:"
to_prod "$S_CLEAN"
code=$(pp)
check "pre-push：工作樹裡有腳本的變數後面直接接全形字 → 推 prod 也擋" 1 "$code"
stub scripts/unconfirmed-conditions.sh sh
to_stage "$S_CLEAN"
code=$(pp)
check "pre-push：條件確認檢查跑不起來時，後面的 bash 3.2 變數檢查照樣查（寫錯 → 擋）" 1 "$code"
put "$R" scripts/unconfirmed-conditions.sh
to_dev "$S_CLEAN"
code=$(pp)
check "pre-push：工作樹裡有腳本的變數後面直接接全形字 → 推開發分支不查" 0 "$code"
silent "pre-push：推開發分支 → 連 bash 3.2 變數檢查都不跑（沒有輸出）"
# 刪遠端分支：沒有東西要查（工作樹裡那支寫錯的腳本還在，也不該因此被擋）
one "(delete)" "$ZERO" refs/heads/stage "$BASE"
code=$(pp)
check "pre-push：刪掉遠端的 stage → 放行" 0 "$code"
silent "pre-push：刪掉遠端的 stage → 什麼都不跑（沒有輸出）"
rm -f "$R/bad.sh"
one "(delete)" "$ZERO" refs/heads/stage "$BASE"
also refs/heads/prod "$S_MARK" refs/heads/prod "$BASE"
code=$(pp)
check "pre-push：同一次先刪遠端的 stage、再推有衝突標記的 prod → 照樣擋" 1 "$code"

# 第一次推（遠端還沒有這條分支，遠端 sha 全 0）照查
to_prod "$S_MARK" "$ZERO"
code=$(pp)
check "pre-push：第一次推 prod（遠端還沒有這條分支）、有衝突標記 → 擋" 1 "$code"
to_stage "$S_WBAD" "$ZERO"
code=$(pp)
check "pre-push：第一次推 stage、票的 W 編號沒交代 → 擋" 1 "$code"
to_stage "$S_CLEAN" "$ZERO"
code=$(pp)
check "pre-push：第一次推 stage、乾淨 → 放行" 0 "$code"
# 新專案：本機連 origin/stage 都還沒有
must git update-ref -d refs/remotes/origin/stage
to_stage "$S_MARK" "$ZERO"
code=$(pp)
check "pre-push：新專案第一次推 stage（本機還沒有 origin/stage）、有衝突標記 → 擋" 1 "$code"
said "pre-push：新專案第一次推 stage → 指出檔案與行號（notes.md:2）" "notes.md:2"
to_stage "$S_CLEAN" "$ZERO"
code=$(pp)
check "pre-push：新專案第一次推 stage、乾淨 → 放行" 0 "$code"
unsaid "pre-push：新專案第一次推 stage、乾淨 → 沒有哪一道說這次沒有檢查" "這次沒有檢查"
must git update-ref refs/remotes/origin/stage "$BASE"

# 一次推兩條
to_dev "$S_MARK"
also refs/heads/stage "$S_CLEAN" refs/heads/stage "$BASE"
code=$(pp)
check "pre-push：一次推兩條——開發分支有衝突標記、stage 乾淨 → 放行" 0 "$code"
unsaid "pre-push：一次推兩條（開發分支有衝突標記、stage 乾淨）→ 沒有擋下的訊息" "⛔"
to_dev "$S_CLEAN"
also refs/heads/stage "$S_MARK" refs/heads/stage "$BASE"
code=$(pp)
check "pre-push：一次推兩條——開發分支乾淨（排在前面）、stage 有衝突標記 → 擋" 1 "$code"
to_stage "$S_CLEAN"
also refs/heads/prod "$S_MARK" refs/heads/prod "$BASE"
code=$(pp)
check "pre-push：一次推兩條——stage 乾淨、prod 有衝突標記 → 擋" 1 "$code"
to_stage "$S_WBAD"
also refs/heads/prod "$S_CLEAN" refs/heads/prod "$BASE"
code=$(pp)
check "pre-push：一次推兩條——stage 的票 W 沒交代、prod 乾淨 → 擋" 1 "$code"
to_prod "$S_WBAD"
also refs/heads/stage "$S_CLEAN" refs/heads/stage "$BASE"
code=$(pp)
check "pre-push：一次推兩條——prod 的票 W 沒交代、stage 乾淨 → 放行（推 prod 不查這一道）" 0 "$code"
to_prod "$S_CBAD"
also refs/heads/stage "$S_CLEAN" refs/heads/stage "$BASE"
code=$(pp)
check "pre-push：一次推兩條——prod 的條件未確認、stage 乾淨 → 放行（推 prod 不查這一道）" 0 "$code"

# ═════════ 一之二、真的推：啟用 hooks 之後，對沙盒裡的遠端推 ═════════
remote_of() { git --git-dir="$1" rev-parse -q --verify "refs/heads/$2" 2>/dev/null || true; }  # remote_of <遠端> <分支>
E="$TMP/e2e"
must git clone -q "$OE" "$E"
cd "$E" || exit 1
( cd "$TMP/cwd" && bash "$E/scripts/setup-hooks.sh" >"$TMP/out" 2>&1 )
check "真的推：在剛 clone 下來的版本庫跑 setup-hooks.sh → 結束碼 0" 0 "$?"
same "真的推：hooks 啟用了（core.hooksPath 是 .githooks）" ".githooks" "$(git config --get core.hooksPath 2>/dev/null || true)"

# 1. stage 上混進衝突標記（用不跑 hook 的方式提交，模擬 rebase --continue 這類 pre-commit 擋不到的路）
printf 'doc\n%s HEAD\nx\n' "$MK_OPEN" > notes.md
must fx add notes.md
must fx commit -q -m "marker slipped in"
git push origin stage >"$TMP/out" 2>&1
code=$?
if [ "$code" != 0 ]; then ok "真的推：stage 有衝突標記 → 推送沒有成功"; else err "真的推：stage 有衝突標記 → 推送沒有成功（結束碼是 0）"; show; fi
same "真的推：stage 有衝突標記 → 遠端的 stage 沒有動" "$BASE" "$(remote_of "$OE" stage)"
said "真的推：stage 有衝突標記 → 看得到是 pre-push 擋的" "[pre-push] ⛔ 推送範圍內有沒解掉的衝突標記"

# 2. 修掉再 commit（hooks 開著：pre-commit 放行、post-commit 不自動推 stage），然後推得上去
printf 'doc\nx\n' > notes.md
must git add notes.md
git commit -q -m "resolve" >"$TMP/out" 2>&1
check "真的推：修掉衝突標記後 commit → 成功" 0 "$?"
said "真的推：在 stage 上 commit → post-commit 講明不自動推" "stage 是受保護分支"
same "真的推：在 stage 上 commit → 遠端的 stage 沒有被自動推上去" "$BASE" "$(remote_of "$OE" stage)"
git push origin stage >"$TMP/out" 2>&1
check "真的推：修乾淨的 stage → 推得上去" 0 "$?"
same "真的推：修乾淨的 stage → 遠端的 stage 指到新的 commit" "$(git rev-parse HEAD)" "$(remote_of "$OE" stage)"
unsaid "真的推：修乾淨的 stage → 沒有擋下的訊息" "⛔"

# 3. 開發分支帶著衝突標記：post-commit 自動推，pre-push 不查（--no-verify 只跳過 pre-commit）
must git checkout -q --no-track -b feature/TK-7 origin/stage
printf 'draft\n%s HEAD\n' "$MK_OPEN" > draft.md
must git add draft.md
git commit -q --no-verify -m "wip with marker" >"$TMP/out" 2>&1
check "真的推：開發分支 commit（內容有衝突標記）→ 成功" 0 "$?"
same "真的推：開發分支有衝突標記也照樣自動推上去（pre-push 不查開發分支）" "$(git rev-parse HEAD)" "$(remote_of "$OE" feature/TK-7)"

# 4. 把這條有問題的開發分支直接推成遠端的 stage／prod → 擋
STAGE_NOW="$(remote_of "$OE" stage)"
git push origin feature/TK-7:stage >"$TMP/out" 2>&1
code=$?
if [ "$code" != 0 ]; then ok "真的推：把有衝突標記的開發分支推成遠端的 stage → 推送沒有成功"; else err "真的推：把有衝突標記的開發分支推成遠端的 stage → 推送沒有成功（結束碼是 0）"; show; fi
same "真的推：把有衝突標記的開發分支推成遠端的 stage → 遠端的 stage 沒有動" "$STAGE_NOW" "$(remote_of "$OE" stage)"
git push origin feature/TK-7:prod >"$TMP/out" 2>&1
code=$?
if [ "$code" != 0 ]; then ok "真的推：把有衝突標記的開發分支推成遠端的 prod → 推送沒有成功"; else err "真的推：把有衝突標記的開發分支推成遠端的 prod → 推送沒有成功（結束碼是 0）"; show; fi
same "真的推：把有衝突標記的開發分支推成遠端的 prod → 遠端的 prod 沒有動" "$BASE" "$(remote_of "$OE" prod)"

# ═════════ 二、post-commit：真的 commit ═════════
C="$TMP/pc"
must git clone -q "$OC" "$C"
cd "$C" || exit 1
must git config core.hooksPath .githooks
refs() { git --git-dir="$OC" for-each-ref --format='%(refname) %(objectname)'; }
upstream_of() { git rev-parse --abbrev-ref "$1@{upstream}" 2>/dev/null || true; }

# 開發分支：commit 完遠端就有（分支照 scripts/new-worktree.sh 的開法：--no-track，沒有上游）
must git checkout -q --no-track -b feature/TK-12 origin/stage
printf 'one\n' > one.txt
must git add one.txt
git commit -q -m "TK-12: one" >"$TMP/out" 2>&1
check "post-commit：開發分支 commit → 成功" 0 "$?"
same "post-commit：開發分支 commit 後，遠端出現那條分支、指到新的 commit" "$(git rev-parse HEAD)" "$(remote_of "$OC" feature/TK-12)"
same "post-commit：第一次推順便把上游設成 origin/feature/TK-12" "origin/feature/TK-12" "$(upstream_of feature/TK-12)"
said "post-commit：講出已經推到 origin" "已推送 feature/TK-12 到 origin"
printf 'two\n' > two.txt
must git add two.txt
git commit -q -m "TK-12: two" >"$TMP/out" 2>&1
same "post-commit：同一條分支再 commit 一次 → 遠端跟著前進" "$(git rev-parse HEAD)" "$(remote_of "$OC" feature/TK-12)"

# 受保護分支：永遠不自動推
for b in stage prod main master; do
  must git checkout -q --no-track -B "$b" origin/stage
  before="$(refs)"
  printf '%s\n' "$b" > "p-$b.txt"
  must git add "p-$b.txt"
  git commit -q -m "on $b" >"$TMP/out" 2>&1
  check "post-commit：在 ${b} 上 commit → 成功" 0 "$?"
  same "post-commit：在 ${b} 上 commit → 遠端完全沒變（不自動推）" "$before" "$(refs)"
  said "post-commit：在 ${b} 上 commit → 講明是受保護分支" "${b} 是受保護分支"
done

# 沒有叫 origin 的遠端：commit 照常、什麼都不做
N="$TMP/noremote"
put "$N" .githooks/pre-commit .githooks/pre-push .githooks/post-commit scripts/conflict-marker-lint.sh
chmod +x "$N"/.githooks/*
cd "$N" || exit 1
must git init -q .
must git symbolic-ref HEAD refs/heads/feature/TK-12
must git config core.hooksPath .githooks
printf 'x\n' > x.txt
must git add x.txt .githooks scripts
HEAD_BEFORE="$(git rev-parse -q --verify HEAD 2>/dev/null || true)"
git commit -q -m "first" >"$TMP/out" 2>&1
check "post-commit：沒有設任何遠端 → commit 照常成功" 0 "$?"
same "post-commit：沒有設任何遠端 → commit 真的寫進去了" yes "$([ "$(git rev-parse -q --verify HEAD 2>/dev/null || true)" != "$HEAD_BEFORE" ] && echo yes || echo no)"
unsaid "post-commit：沒有設任何遠端 → 什麼都不做（沒有推送的訊息）" "[post-commit]"
must git remote add backup "$OC"
before="$(refs)"
printf 'y\n' > y.txt
must git add y.txt
git commit -q -m "second" >"$TMP/out" 2>&1
check "post-commit：只有別的名字的遠端（沒有 origin）→ commit 照常成功" 0 "$?"
same "post-commit：只有別的名字的遠端（沒有 origin）→ 不推到那個遠端" "$before" "$(refs)"
unsaid "post-commit：只有別的名字的遠端（沒有 origin）→ 沒有推送的訊息" "[post-commit]"

# origin 連不到：commit 照常成功，只提示
cd "$C" || exit 1
must git checkout -q --no-track -b feature/TK-20 origin/stage
must git remote set-url origin "$TMP/nowhere.git"
HEAD_BEFORE="$(git rev-parse HEAD)"
printf 'off\n' > off.txt
must git add off.txt
git commit -q -m "offline" >"$TMP/out" 2>&1
check "post-commit：origin 連不到 → commit 照常成功" 0 "$?"
same "post-commit：origin 連不到 → commit 真的寫進去了" yes "$([ "$(git rev-parse HEAD)" != "$HEAD_BEFORE" ] && echo yes || echo no)"
said "post-commit：origin 連不到 → 提示沒推上去、要自己補推" "沒推上去"
( bash .githooks/post-commit >"$TMP/out" 2>&1 )
check "post-commit：推不上去時 hook 自己的結束碼還是 0" 0 "$?"
must git remote set-url origin "$OC"

# 遠端那條分支比較新（別人先推了）：不硬蓋，只提示
X="$TMP/other"
must git clone -q "$OC" "$X"
( cd "$X" && fx checkout -q -b feature/TK-21 origin/stage && printf 'theirs\n' > theirs.txt \
  && fx add theirs.txt && fx commit -q -m theirs && fx push -q origin feature/TK-21 ) >/dev/null 2>&1 \
  || { echo "${T} ✗ 沙盒建不起來：別人的 clone 推不上去" >&2; exit 1; }
THEIRS="$(git -C "$X" rev-parse HEAD)"
must git checkout -q --no-track -b feature/TK-21 origin/stage
printf 'mine\n' > mine.txt
must git add mine.txt
git commit -q -m "mine" >"$TMP/out" 2>&1
check "post-commit：遠端那條分支比較新 → commit 照常成功" 0 "$?"
said "post-commit：遠端那條分支比較新 → 提示沒推上去" "沒推上去"
same "post-commit：遠端那條分支比較新 → 沒有蓋掉別人的 commit" "$THEIRS" "$(remote_of "$OC" feature/TK-21)"

# 不在任何分支上（detached HEAD）：不推
must git checkout -q --detach origin/stage
before="$(refs)"
printf 'd\n' > d.txt
must git add d.txt
git commit -q -m "detached" >"$TMP/out" 2>&1
check "post-commit：不在任何分支上（detached HEAD）commit → 成功" 0 "$?"
same "post-commit：不在任何分支上 → 遠端完全沒變" "$before" "$(refs)"
unsaid "post-commit：不在任何分支上 → 沒有推送的訊息" "[post-commit]"

# rebase／merge／cherry-pick／revert 進行中：不推。標記是 git 在動作進行中自己放在 .git 裡的；
# 哪些指令的哪個時間點會留著標記隨 git 版本而不同，所以這裡直接放標記、直接叫 hook，一個一個驗。
must git checkout -q --no-track -b feature/TK-30 origin/stage
gd="$(git rev-parse --git-dir)"
i=0
for marker in rebase-merge rebase-apply MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
  i=$((i + 1))
  printf '%s\n' "$i" > "m$i.txt"
  must fx add "m$i.txt"
  must fx commit -q -m "wip $i"
  before="$(remote_of "$OC" feature/TK-30)"
  case "$marker" in
    rebase-*) mkdir "${gd:?}/${marker}" ;;
    *) git rev-parse HEAD > "${gd:?}/${marker}" ;;
  esac
  ( bash .githooks/post-commit >"$TMP/out" 2>&1 )
  code=$?
  rm -rf "${gd:?}/${marker}"
  check "post-commit：${marker} 還在（動作進行到一半）→ 結束碼 0" 0 "$code"
  same "post-commit：${marker} 還在（動作進行到一半）→ 不推" "$before" "$(remote_of "$OC" feature/TK-30)"
  silent "post-commit：${marker} 還在（動作進行到一半）→ 沒有任何訊息"
done
( bash .githooks/post-commit >"$TMP/out" 2>&1 )
same "post-commit：標記都不在了 → 推上去" "$(git rev-parse HEAD)" "$(remote_of "$OC" feature/TK-30)"

# 真的 rebase 一次：過程中產生的 commit 不推
must git checkout -q --no-track -b feature/TK-31 origin/stage
printf 'r1\n' > r1.txt
must fx add r1.txt
must fx commit -q -m r1
printf 'r2\n' > r2.txt
must fx add r2.txt
must fx commit -q -m r2
must fx checkout -q --detach origin/stage
printf 'nb\n' > newbase.txt
must fx add newbase.txt
must fx commit -q -m "new base"
NEWBASE="$(git rev-parse HEAD)"
must fx checkout -q feature/TK-31
git rebase "$NEWBASE" >"$TMP/out" 2>&1
check "post-commit：真的 rebase 一次 → rebase 成功" 0 "$?"
same "post-commit：rebase 過程中產生的 commit → 不推（遠端沒有那條分支）" "" "$(remote_of "$OC" feature/TK-31)"
unsaid "post-commit：rebase 過程中 → 沒有推送的訊息" "[post-commit]"

# 在 git worktree 開的工作區裡 commit：一樣自動推（用的是工作區自己那一棵的 hook）
must git worktree add --no-track -b feature/AMY-3 "$C/.claude/worktrees/AMY-3" origin/stage
cd "$C/.claude/worktrees/AMY-3" || exit 1
printf 'w\n' > w.txt
must git add w.txt
git commit -q -m "AMY-3: in worktree" >"$TMP/out" 2>&1
check "post-commit：在工作區（git worktree）裡 commit → 成功" 0 "$?"
same "post-commit：在工作區裡 commit → 遠端出現那條分支、指到新的 commit" "$(git rev-parse HEAD)" "$(remote_of "$OC" feature/AMY-3)"
same "post-commit：在工作區裡 commit → 上游設成 origin/feature/AMY-3" "origin/feature/AMY-3" "$(upstream_of feature/AMY-3)"
cd "$C" || exit 1

# 自動推的時候關掉帳密輸入提示（模板內補的）：把 pre-push 換成記錄器，看 git push 拿到的環境變數
must git checkout -q --no-track -b feature/TK-40 origin/stage
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "${GIT_TERMINAL_PROMPT:-unset}" > "%s"\nexit 0\n' "$TMP/prompt.txt" > .githooks/pre-push
printf 't\n' > t.txt
must git add t.txt
GIT_TERMINAL_PROMPT=1 git commit -q -m "prompt" >"$TMP/out" 2>&1
same "post-commit：自動推的時候把 GIT_TERMINAL_PROMPT 設成 0（遠端要帳密時不讓 commit 停著等輸入）" "0" "$(cat "$TMP/prompt.txt" 2>/dev/null || true)"
put "$C" .githooks/pre-push

# ═════════ 三、setup-hooks.sh：只在沙盒的副本上跑 ═════════
# mk_tpl <資料夾>：放一份 hooks 與 setup-hooks.sh（還不是 git 版本庫）
mk_tpl() { put "$1" .githooks/pre-commit .githooks/pre-push .githooks/post-commit scripts/setup-hooks.sh; }
# 一律從別的資料夾呼叫：setup-hooks.sh 設定的是「腳本所在的那一棵」，不是呼叫的人站的地方
setup() { ( cd "$TMP/cwd" && bash "$1/scripts/setup-hooks.sh" >"$TMP/out" 2>&1 ); echo $?; }
hp() { git -C "$1" config --get core.hooksPath 2>/dev/null || true; }  # hp <資料夾>：目前的 core.hooksPath
xbits() {  # xbits <資料夾>：三支 hook 都有執行權限就印 yes
  if [ -x "$1/.githooks/pre-commit" ] && [ -x "$1/.githooks/pre-push" ] && [ -x "$1/.githooks/post-commit" ]; then
    echo yes
  else
    echo no
  fi
}

# 全新的版本庫
FR="$TMP/fresh"
mk_tpl "$FR"
must git -C "$FR" init -q .
chmod -x "$FR"/.githooks/*
code=$(setup "$FR")
check "setup-hooks：全新的版本庫 → 結束碼 0" 0 "$code"
same "setup-hooks：core.hooksPath 設成相對路徑 .githooks" ".githooks" "$(hp "$FR")"
said "setup-hooks：啟用訊息講出第 1 件事（commit 前擋衝突標記）" "commit 前擋沒解乾淨的合併衝突標記"
said "setup-hooks：啟用訊息講出第 2 件事（推 stage／prod 前的關卡）" "推 stage／prod 前先跑通用關卡"
said "setup-hooks：啟用訊息講出第 3 件事（開發分支 commit 後自動推）" "開發分支每次 commit 後自動推到 origin"
unsaid "setup-hooks：啟用訊息不提 make dev（範本沒有那回事）" "make dev"
same "setup-hooks：順便補上三支 hook 的執行權限" yes "$(xbits "$FR")"

# 可以重複跑
chmod -x "$FR"/.githooks/*
code=$(setup "$FR")
check "setup-hooks：再跑一次 → 結束碼 0" 0 "$code"
same "setup-hooks：再跑一次 → 值還是 .githooks" ".githooks" "$(hp "$FR")"
same "setup-hooks：再跑一次 → 設定裡還是只有一筆" 1 "$(git -C "$FR" config --get-all core.hooksPath 2>/dev/null | wc -l | tr -d ' ')"
said "setup-hooks：再跑一次 → 講明已經啟用了" "已經啟用了"
same "setup-hooks：再跑一次 → 執行權限掉了也補回來" yes "$(xbits "$FR")"

# 不是 git 版本庫：略過
PL="$TMP/plain"
mk_tpl "$PL"
code=$(setup "$PL")
check "setup-hooks：不是 git 版本庫 → 結束碼 0" 0 "$code"
said "setup-hooks：不是 git 版本庫 → 講明略過" "略過"
unsaid "setup-hooks：不是 git 版本庫 → 不說成已啟用" "已啟用"
same "setup-hooks：不是 git 版本庫 → 沒有自己建出 .git" no "$([ -e "$PL/.git" ] && echo yes || echo no)"

# core.hooksPath 已經是別的值
OT="$TMP/taken"
mk_tpl "$OT"
must git -C "$OT" init -q .
mkdir -p "$OT/.other-hooks" "$TMP/elsewhere-hooks"
must git -C "$OT" config core.hooksPath .other-hooks
code=$(setup "$OT")
check "setup-hooks：已經指到別的、存在的資料夾（相對路徑）→ 結束碼 1" 1 "$code"
same "setup-hooks：已經指到別的、存在的資料夾（相對路徑）→ 原本的值沒被蓋掉" ".other-hooks" "$(hp "$OT")"
said "setup-hooks：已經指到別的、存在的資料夾 → 印出目前的值" "目前的值：.other-hooks"
said "setup-hooks：已經指到別的、存在的資料夾 → 印出要換過來的那條指令" "git config core.hooksPath .githooks"
unsaid "setup-hooks：已經指到別的、存在的資料夾 → 不說成已啟用" "已啟用"
must git -C "$OT" config core.hooksPath "$TMP/elsewhere-hooks"
code=$(setup "$OT")
check "setup-hooks：已經指到別的、存在的資料夾（固定路徑）→ 結束碼 1" 1 "$code"
same "setup-hooks：已經指到別的、存在的資料夾（固定路徑）→ 原本的值沒被蓋掉" "$TMP/elsewhere-hooks" "$(hp "$OT")"
# 指到不存在的資料夾（例：指進一個已經收掉的工作區）→ 等於所有 hook 都沒在跑，改回來
must git -C "$OT" config core.hooksPath .claude/worktrees/gone/.githooks
code=$(setup "$OT")
check "setup-hooks：指到不存在的資料夾 → 結束碼 0" 0 "$code"
same "setup-hooks：指到不存在的資料夾 → 改成 .githooks" ".githooks" "$(hp "$OT")"
said "setup-hooks：指到不存在的資料夾 → 講出原本的值" "原本是「.claude/worktrees/gone/.githooks」"
said "setup-hooks：指到不存在的資料夾 → 講明那個資料夾不存在" "那個資料夾不存在"
must git -C "$OT" config core.hooksPath /dev/null
code=$(setup "$OT")
check "setup-hooks：原本被設成 /dev/null（hook 全關）→ 結束碼 0" 0 "$code"
same "setup-hooks：原本被設成 /dev/null → 改成 .githooks" ".githooks" "$(hp "$OT")"
# 就是這一棵的 .githooks，只是寫法不同 → 統一成相對路徑
must git -C "$OT" config core.hooksPath "$OT/.githooks"
code=$(setup "$OT")
check "setup-hooks：寫成固定路徑的同一個 .githooks → 結束碼 0" 0 "$code"
same "setup-hooks：寫成固定路徑的同一個 .githooks → 改成相對路徑" ".githooks" "$(hp "$OT")"
said "setup-hooks：寫成固定路徑的同一個 .githooks → 講明改成相對路徑" "已改成相對路徑"
ln -s "$OT" "$TMP/taken-link"
must git -C "$OT" config core.hooksPath "$TMP/taken-link/.githooks"
code=$(setup "$OT")
check "setup-hooks：經過符號連結指到同一個 .githooks → 結束碼 0" 0 "$code"
same "setup-hooks：經過符號連結指到同一個 .githooks → 改成相對路徑" ".githooks" "$(hp "$OT")"
must git -C "$OT" config core.hooksPath ./.githooks
code=$(setup "$OT")
check "setup-hooks：寫成 ./.githooks → 結束碼 0" 0 "$code"
same "setup-hooks：寫成 ./.githooks → 統一寫成 .githooks" ".githooks" "$(hp "$OT")"
said "setup-hooks：寫成 ./.githooks → 講明是同一個資料夾" "同一個資料夾"

# 相對路徑：主目錄與工作區各跑各自那一棵的 hook
WR="$TMP/wtrepo"
mk_tpl "$WR"
cd "$WR" || exit 1
must git init -q .
must git symbolic-ref HEAD refs/heads/stage
must fx add .githooks scripts
must fx commit -q -m base
must fx worktree add --no-track -b feature/TK-50 "$WR/.claude/worktrees/TK-50"
printf '#!/usr/bin/env bash\necho main >> "%s"\n' "$TMP/which.log" > "$WR/.githooks/pre-commit"
printf '#!/usr/bin/env bash\necho wt >> "%s"\n' "$TMP/which.log" > "$WR/.claude/worktrees/TK-50/.githooks/pre-commit"
code=$(setup "$WR")
check "setup-hooks：有工作區的版本庫 → 結束碼 0" 0 "$code"
( cd "$WR" && printf 'a\n' > a.txt && git add a.txt && git commit -q -m "in main" ) >/dev/null 2>&1
( cd "$WR/.claude/worktrees/TK-50" && printf 'b\n' > b.txt && git add b.txt && git commit -q -m "in worktree" ) >/dev/null 2>&1
same "setup-hooks：跑一次，主目錄與工作區各跑各自那一棵的 hook" "main,wt" "$(paste -sd, "$TMP/which.log" 2>/dev/null || true)"
# 從工作區裡的那一份跑也一樣：設定是整個版本庫共用的
must git config --unset core.hooksPath
code=$(setup "$WR/.claude/worktrees/TK-50")
check "setup-hooks：從工作區裡的那一份跑 → 結束碼 0" 0 "$code"
same "setup-hooks：從工作區裡的那一份跑 → 主目錄也生效" ".githooks" "$(hp "$WR")"

# 全域設定已經指到別處（別的工具裝的 hooks）→ 不動，講出設定來源
GL="$TMP/globalset"
mk_tpl "$GL"
must git -C "$GL" init -q .
mkdir -p "$TMP/global-hooks"
printf '[core]\n\thooksPath = %s\n' "$TMP/global-hooks" > "$TMP/global.cfg"
( cd "$TMP/cwd" && GIT_CONFIG_GLOBAL="$TMP/global.cfg" bash "$GL/scripts/setup-hooks.sh" >"$TMP/out" 2>&1 )
check "setup-hooks：全域設定已經指到別處 → 結束碼 1" 1 "$?"
same "setup-hooks：全域設定已經指到別處 → 這個版本庫自己的設定沒有被寫入" "" "$(git -C "$GL" config --local --get core.hooksPath 2>/dev/null || true)"
said "setup-hooks：全域設定已經指到別處 → 講出設定來源是哪個檔" "global.cfg"

# 範本放在另一個版本庫底下、自己還沒 git init → 不動外面那個版本庫
must mkdir -p "$TMP/outer"
must git -C "$TMP/outer" init -q .
mk_tpl "$TMP/outer/inner"
code=$(setup "$TMP/outer/inner")
check "setup-hooks：放在另一個版本庫底下、自己還不是版本庫 → 結束碼 1" 1 "$code"
same "setup-hooks：放在另一個版本庫底下 → 外面那個版本庫的設定沒有被動到" "" "$(hp "$TMP/outer")"
said "setup-hooks：放在另一個版本庫底下 → 講明這裡不是版本庫的最上層" "最上層"

# 找不到 .githooks/ → 不設定（設了等於把所有 hook 關掉）
NH="$TMP/nohooks"
mk_tpl "$NH"
must git -C "$NH" init -q .
rm -rf "$NH/.githooks"
code=$(setup "$NH")
check "setup-hooks：找不到 .githooks/ → 結束碼 1" 1 "$code"
same "setup-hooks：找不到 .githooks/ → 沒有設定" "" "$(hp "$NH")"
said "setup-hooks：找不到 .githooks/ → 講明找不到" "找不到 .githooks/"

# git 設定寫不進去 → 不能說成已啟用（root 什麼都寫得進去，這一條就不跑）
if [ "$(id -u)" != 0 ]; then
  LK="$TMP/locked"
  mk_tpl "$LK"
  must git -C "$LK" init -q .
  chmod 555 "$LK/.git"
  code=$(setup "$LK")
  chmod 755 "$LK/.git"
  check "setup-hooks：git 設定寫不進去 → 結束碼 1" 1 "$code"
  said "setup-hooks：git 設定寫不進去 → 講明寫不進去" "寫不進 git 設定"
  unsaid "setup-hooks：git 設定寫不進去 → 不說成已啟用" "已啟用"
fi

[ "$fail" = 0 ] && echo "${T} 全部通過" || exit 1
