#!/usr/bin/env bash
# scripts/bash32-var-lint.sh 與 scripts/dup-file-lint.sh 的測試（模板內補的：源專案這兩支沒有自己的測試）。
#
# 兩支 lint 都把「腳本所在位置的上一層」當成要掃的資料夾，所以每個案例都把 lint 複製進暫存資料夾裡的沙盒再跑，
# 不看範本自己這一棵（範本本身是不是 git 版本庫都不影響結果）。
#
# 改這支測試時別踩的兩件事：
#   ・這支測試自己也是 *.sh，會被 bash32-var-lint 掃到——有問題的範例不能直接寫在這裡，
#     一律用 printf 現場組出來（錢字號放在變數 D 裡）。
#   ・lint 的輸出先收進檔案，案例沒過才印出來——免得全部通過時畫面上還看得到 lint 自己的 ✗／❌。
set -uo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com

fail=0
T="[repo-lints-test]"
err() { echo "${T} ✗ $1" >&2; fail=1; }
ok() { echo "${T} ✓ $1"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
TMP="$(cd "$TMP" && pwd -P)"
export GIT_CEILING_DIRECTORIES="$TMP"
mkdir -p "$TMP/cwd" "$TMP/bin"

must() { "$@" >/dev/null 2>&1 || { echo "${T} ✗ 沙盒建不起來：$*" >&2; exit 1; }; }
show() { sed 's/^/      /' "$TMP/out" 2>/dev/null | head -8 >&2; }
check() {  # check <說明> <期望結束碼> <實際結束碼>
  if [ "$3" = "$2" ]; then ok "$1"; else err "$1（期望 ${2} 實際 ${3}）"; show; fi
}
said() {  # said <說明> <上一步的輸出裡要有的字>
  if grep -qF -- "$2" "$TMP/out"; then ok "$1"; else err "$1（輸出裡找不到「${2}」）"; show; fi
}
unsaid() {  # unsaid <說明> <上一步的輸出裡不該有的字>
  if grep -qF -- "$2" "$TMP/out"; then err "$1（輸出裡不該有「${2}」）"; show; else ok "$1"; fi
}
# sandbox <資料夾> <lint 檔名>：放一份 lint 進去（還不是 git 版本庫）
sandbox() {
  mkdir -p "$1/scripts"
  cp "$SRC/scripts/$2" "$1/scripts/$2" || { echo "${T} ✗ 沙盒建不起來：找不到 scripts/${2}" >&2; exit 1; }
}

# ───────── bash32-var-lint ─────────
D='$'
BR="$TMP/b"
sandbox "$BR" bash32-var-lint.sh
cd "$BR" || exit 1
must git init -q .
must git add scripts/bash32-var-lint.sh
must git -c core.hooksPath=/dev/null commit -q -m base
# 一律從別的資料夾呼叫：lint 掃的是「腳本所在的那一棵」，不是呼叫的人站的地方
b32() { ( cd "$TMP/cwd" && bash "$1/scripts/bash32-var-lint.sh" >"$TMP/out" 2>&1 ); echo $?; }

code=$(b32 "$BR")
check "bash32：乾淨的版本庫 → 過" 0 "$code"
said "bash32：過的時候講出掃了幾個檔（這裡只有 lint 自己 1 個）" "OK（掃了 1 個檔）"

printf 'num=1\necho "%snum：好"\n' "$D" > a.sh
must git add a.sh
code=$(b32 "$BR")
check "bash32：變數名後面直接接全形冒號 → 擋" 1 "$code"
said "bash32：訊息指出檔案與行號（a.sh:2:）" "a.sh:2:"
must git rm -q -f a.sh

printf 'count=3\necho "共 %scount個"\n' "$D" > b.sh
must git add b.sh
code=$(b32 "$BR")
check "bash32：變數名後面直接接中文字 → 擋" 1 "$code"
must git rm -q -f b.sh

# clean_case <說明> <printf 格式> [參數…]：把內容寫成追蹤中的 c.sh，期望不擋
clean_case() {
  local title="$1"; shift
  # shellcheck disable=SC2059
  printf "$@" > c.sh
  must git add c.sh
  code=$(b32 "$BR")
  check "$title" 0 "$code"
  must git rm -q -f c.sh
}
clean_case "bash32：加了大括號再接全形字 → 不擋" 'num=1\necho "%s{num}：好"\n' "$D"
clean_case "bash32：註解行（含縮排的註解）裡的寫法 → 不擋" '# 說明 %snum：好\n  # 也是 %snum：好\n' "$D" "$D"
clean_case "bash32：位置參數後面接全形括號 → 不擋" 'echo "%s1（第一個參數）"\n' "$D"
clean_case "bash32：變數名後面接半形冒號 → 不擋" 'num=1\necho "%snum: ok"\n' "$D"

printf 'echo "%sname，你好"\n' "$D" > new.sh
code=$(b32 "$BR")
check "bash32：還沒進版控的新 *.sh → 照樣擋" 1 "$code"
said "bash32：還沒進版控的新檔，訊息指出檔案與行號（new.sh:1:）" "new.sh:1:"
rm -f new.sh

mkdir -p .githooks
printf '#!/usr/bin/env bash\necho "%sname，你好"\n' "$D" > .githooks/pre-x
code=$(b32 "$BR")
check "bash32：.githooks/ 底下沒有副檔名的檔（還沒進版控）→ 擋" 1 "$code"
said "bash32：.githooks/ 底下的檔，訊息指出檔案與行號（.githooks/pre-x:2:）" ".githooks/pre-x:2:"
must git add .githooks/pre-x
code=$(b32 "$BR")
check "bash32：.githooks/ 底下沒有副檔名的檔（追蹤中）→ 擋" 1 "$code"
must git rm -q -f .githooks/pre-x

mkdir -p tools/deep
printf 'echo "%sname，你好"\n' "$D" > "tools/deep/工具 腳本.sh"
code=$(b32 "$BR")
check "bash32：子資料夾裡、檔名有空白與中文的 *.sh → 擋" 1 "$code"
said "bash32：檔名有空白與中文時，訊息裡的檔名完整" "tools/deep/工具 腳本.sh:1:"
rm -rf tools

printf 'echo "%sname，你好"\n' "$D" > notes.txt
code=$(b32 "$BR")
check "bash32：不是 *.sh、也不在 .githooks/ 底下的檔 → 不掃" 0 "$code"
rm -f notes.txt

printf 'build/\n' > .gitignore
mkdir -p build
printf 'echo "%sname，你好"\n' "$D" > build/gen.sh
code=$(b32 "$BR")
check "bash32：被 .gitignore 忽略的檔 → 不掃" 0 "$code"
said "bash32：被忽略的檔不算進掃描數（還是 1 個）" "OK（掃了 1 個檔）"
rm -rf build .gitignore

printf 'echo ok\n' > gone.sh
must git add gone.sh
rm -f gone.sh
code=$(b32 "$BR")
check "bash32：檔案刪了但還沒 commit → 照常跑完" 0 "$code"
said "bash32：刪掉的檔不算進掃描數（還是 1 個）" "OK（掃了 1 個檔）"
unsaid "bash32：刪掉的檔不會讓 perl 抱怨開不了檔" "No such file"
must git rm -q --cached gone.sh

printf 'echo ok\n' > t1.sh
printf 'echo ok\n' > t2.sh
must git add t1.sh
code=$(b32 "$BR")
check "bash32：追蹤中的與還沒進版控的乾淨檔 → 過" 0 "$code"
said "bash32：追蹤中的與還沒進版控的都算進掃描數（3 個）" "OK（掃了 3 個檔）"
must git rm -q -f t1.sh
rm -f t2.sh

# 不是 git 版本庫：不可以一個檔都沒掃就說 OK
NB="$TMP/nb"
sandbox "$NB" bash32-var-lint.sh
code=$(b32 "$NB")
check "bash32：不是 git 版本庫、沒有問題 → 過" 0 "$code"
said "bash32：不是 git 版本庫時講明是改用 find 掃的、掃了幾個" "改用 find 掃了 1 個檔"
printf 'echo "%sname，你好"\n' "$D" > "$NB/x.sh"
code=$(b32 "$NB")
check "bash32：不是 git 版本庫 → 照樣擋（不是沒掃就說 OK）" 1 "$code"
said "bash32：不是 git 版本庫時訊息一樣指出檔案與行號（x.sh:1:）" "x.sh:1:"
rm -f "$NB/x.sh"
mkdir -p "$NB/.githooks"
printf 'echo "%sname，你好"\n' "$D" > "$NB/.githooks/pre-x"
code=$(b32 "$NB")
check "bash32：不是 git 版本庫，.githooks/ 底下的檔 → 擋" 1 "$code"
rm -rf "$NB/.githooks"
mkdir -p "$NB/.claude/worktrees/TK-12"
printf 'echo "%sname，你好"\n' "$D" > "$NB/.claude/worktrees/TK-12/bad.sh"
code=$(b32 "$NB")
check "bash32：不是 git 版本庫，.claude/worktrees/ 底下別的工作區 → 不掃" 0 "$code"
rm -rf "$NB/.claude"

# 是 git 版本庫、但 git 列不出檔案（index 壞掉）：一樣退回 find，不可以安靜放行
BC="$TMP/bc"
sandbox "$BC" bash32-var-lint.sh
must git -C "$BC" init -q
printf 'garbage' > "$BC/.git/index"
printf 'echo "%sname，你好"\n' "$D" > "$BC/x.sh"
code=$(b32 "$BC")
check "bash32：git 列不出檔案（index 壞掉）→ 改用 find，照樣擋" 1 "$code"
rm -f "$BC/x.sh"
code=$(b32 "$BC")
check "bash32：git 列不出檔案、沒有問題 → 過" 0 "$code"
said "bash32：git 列不出檔案時講明是改用 find 掃的" "改用 find 掃了 1 個檔"

# 沒有 perl：PATH 裡只留 dirname（lint 開頭要用），其他指令都找不到
ln -s "$(command -v dirname)" "$TMP/bin/dirname"
code=$( ( cd "$TMP/cwd" && PATH="$TMP/bin" "${BASH:-/bin/bash}" "$BR/scripts/bash32-var-lint.sh" >"$TMP/out" 2>&1 ); echo $? )
check "bash32：找不到 perl → 結束碼 2（不是過）" 2 "$code"
said "bash32：找不到 perl 時講明這次沒有檢查" "這次沒有檢查"

# ───────── dup-file-lint ─────────
DR="$TMP/d"
sandbox "$DR" dup-file-lint.sh
cd "$DR" || exit 1
must git init -q .
must git add scripts/dup-file-lint.sh
dup() { ( cd "$TMP/cwd" && bash "$1/scripts/dup-file-lint.sh" >"$TMP/out" 2>&1 ); echo $?; }

code=$(dup "$DR")
check "dup-file：乾淨的版本庫 → 過" 0 "$code"
said "dup-file：過的時候印 OK" "OK（版控內沒有疑似複製檔）"

# dup_case <期望結束碼> <檔名>：把這個檔名加進版控跑一次，查完移掉
dup_case() {
  mkdir -p "$(dirname "$2")"
  printf 'x\n' > "$2"
  must git add -- "$2"
  code=$(dup "$DR")
  if [ "$1" = 1 ]; then
    check "dup-file：版控內有「${2}」→ 擋" 1 "$code"
    said "dup-file：訊息列出「${2}」" "  $2"
  else
    check "dup-file：版控內有「${2}」→ 不擋" 0 "$code"
  fi
  must git rm -q -f -- "$2"
}
dup_case 1 "app/util 2.py"
dup_case 1 "web/page copy.ts"
dup_case 1 "a/b/c 3.json"
dup_case 1 "deploy 9.yml"
dup_case 1 "util 2.py"
dup_case 1 "文件 2.sh"
dup_case 0 "報價 2024.pdf"
dup_case 0 "步驟 1.png"
dup_case 0 "設定 1.json"
dup_case 0 "報價 2.pdf"
dup_case 0 "batch 10.py"
dup_case 0 "normal.py"
dup_case 0 "v2.py"
dup_case 0 "copy.py"
dup_case 0 "my copy.txt"

mkdir -p app
printf 'x\n' > "app/a 2.py"
printf 'x\n' > "app/b copy.js"
must git add -- "app/a 2.py" "app/b copy.js"
code=$(dup "$DR")
check "dup-file：一次兩個複製檔 → 擋" 1 "$code"
said "dup-file：講出有幾個（2 個）" "有 2 個疑似複製檔"
must git rm -q -f -- "app/a 2.py" "app/b copy.js"

printf 'x\n' > "draft 2.py"
code=$(dup "$DR")
check "dup-file：還沒進版控的「draft 2.py」→ 不算（只看版控內的）" 0 "$code"
rm -f "draft 2.py"

ND="$TMP/nd"
sandbox "$ND" dup-file-lint.sh
printf 'x\n' > "$ND/util 2.py"
code=$(dup "$ND")
check "dup-file：不是 git 版本庫 → 結束碼 0" 0 "$code"
said "dup-file：不是 git 版本庫時講明略過" "略過"
unsaid "dup-file：不是 git 版本庫時不印成檢查通過" "OK"

DC="$TMP/dc"
sandbox "$DC" dup-file-lint.sh
must git -C "$DC" init -q
printf 'garbage' > "$DC/.git/index"
code=$(dup "$DC")
check "dup-file：git 列不出檔案（index 壞掉）→ 結束碼 2" 2 "$code"
said "dup-file：列不出檔案時講明這次沒有檢查" "這次沒有檢查"

[ "$fail" = 0 ] && echo "${T} 全部通過" || exit 1
