#!/usr/bin/env bash
# git-scope-gate-hook.sh 的自動化測試（源專案 v4.78.0）。守門工具自己也要有測試。
#
# 重點案例（源專案踩過的）：一條指令同時有一段 Python（含 `from . import x`）和一個指名檔案的
# `git add`，閘門把 Python 那一行的「.」當成 `git add .` 擋下——所以「該放行的」跟「該擋的」一樣要釘住。
#
# 全部在沙盒裡跑：把 hook 複製進 $TMP/repo/scripts/，hook 算出來的 ROOT 就是沙盒——
# override 檔、用來判斷「是不是資料夾」的目錄都是沙盒自己的，不碰真的工作樹。
set -uo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"

fail=0
err() { echo "[git-scope-gate-test] ✗ $1" >&2; fail=1; }
ok() { echo "[git-scope-gate-test] ✓ $1"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
R="$TMP/repo"
mkdir -p "$R/scripts" "$R/tickets" "$R/cache" "$TMP/elsewhere/onlyhere"
cp "$SRC/scripts/git-scope-gate-hook.sh" "$R/scripts/"
HOOK="$R/scripts/git-scope-gate-hook.sh"

payload() {  # payload <指令> [執行目錄] -> 寫進 $TMP/payload.json
  python3 -c 'import json,sys;print(json.dumps({"tool_input":{"command":sys.argv[1]},"cwd":sys.argv[2]}))' \
    "$1" "${2:-}" > "$TMP/payload.json"
}
run() {  # run <指令> [執行目錄] -> echo exit code
  # 從檔案餵 stdin、不接管線：接管線的話這支測試開了 pipefail，拿到的會是前一段的結束碼而不是 hook 的
  payload "$1" "${2:-}"
  bash "$HOOK" < "$TMP/payload.json" >/dev/null 2>&1
  echo $?
}
expect() {  # expect <期望 exit> <說明> <指令> [執行目錄]
  local code; code=$(run "$3" "${4:-}")
  [ "$code" = "$1" ] && ok "$2" || err "$2（期望 exit $1，實際 ${code}）"
}

# ── 該擋的：git add 的範圍 ──────────────────────────────────
expect 2 "git add -A → 擋"                     'git add -A'
expect 2 "git add . → 擋"                      'git add .'
expect 2 "git add 資料夾 → 擋"                 'git add tickets/'
expect 2 "cd 之後 git add . → 擋"              'cd src && git add . && git commit -m x'
expect 2 "多行裡真的有 git add . → 擋"         $'echo hi\ngit add .'
expect 2 "-p 之後又 git add . → 後半照擋"      'git add -p a.py; git add .'
expect 2 "--patch 之後 git add -A → 後半照擋"  'git add --patch a.py && git add -A'
expect 2 "反斜線換行接 . → 擋"                 $'git add \\\n  .'
expect 2 "反斜線換行接資料夾 → 擋"             $'git add a.py \\\n  tickets/'
expect 2 "合併旗標 -Av → 擋"                   'git add -Av'
expect 2 "資料夾少打斜線 → 擋"                 'git add tickets'
expect 2 "結尾是 / 的名字（這裡沒有這個資料夾）→ 擋" 'git add notyet/'
expect 2 "引號包住的資料夾 → 擋"               'git add "tickets/"'
expect 2 "git add .. → 擋"                     'git add ..'
expect 2 "git add -u → 擋"                     'git add -u'
expect 2 "git add * → 擋"                      'git add *'
expect 2 "執行目錄底下的資料夾（少打斜線）→ 擋" 'git add onlyhere' "$TMP/elsewhere"
expect 2 "絕對路徑指到資料夾 → 擋"             "git add $TMP/elsewhere/onlyhere"

# ── 該擋的：git commit -a ──────────────────────────────────
expect 2 "git commit -am → 擋"                 'git commit -am "x"'
expect 2 "git commit -a -m → 擋"               'git add a.py && git commit -a -m x'
expect 2 "git commit --all → 擋"               'git commit --all -m x'

# ── 該擋的：相對 commit 指法 ────────────────────────────────
expect 2 "git reset HEAD^ → 擋"                'git reset --mixed HEAD^'
expect 2 "git rebase HEAD~3 → 擋"              'git rebase -i HEAD~3'
expect 2 "git revert HEAD~2 → 擋"              'git revert HEAD~2'

# ── 該擋的：git 與子指令中間夾了全域選項（跨工作樹用 -C 正是規定的寫法）────
expect 2 "git -C <路徑> add -A → 擋"            'git -C /tmp/wt add -A'
expect 2 "git -C \"有空白的路徑\" add . → 擋"    'git -C "/tmp/my wt" add .'
expect 2 "git --no-pager -C <路徑> add 資料夾 → 擋" 'git --no-pager -C /tmp/wt add tickets/'
expect 2 "git -C <路徑> commit -am → 擋"        'git -C /tmp/wt commit -am x'
expect 2 "git -C <路徑> reset HEAD~1 → 擋"      'git -C /tmp/wt reset --hard HEAD~1'
expect 2 "git -c 設定 add -A → 擋"              'git -c user.name=x add -A'
expect 2 "git --git-dir= --work-tree= add . → 擋" 'git --git-dir=/tmp/wt/.git --work-tree=/tmp/wt add .'

# ── 該放行的 ───────────────────────────────────────────────
expect 0 "指名檔案 → 放行"                     'git add a.py b/c.py'
expect 0 "git add -p → 放行"                   'git add -p'
expect 0 "git add -p .（互動挑，範圍再大也是一塊一塊選）→ 放行" 'git add -p .'
expect 0 "不是 git 指令 → 放行"                'ls -la'
expect 0 "指名雜湊 reset → 放行"               'git reset --mixed abc1234'
expect 0 "Python 裡的 from . import、git add 全是指名檔案 → 放行" \
  $'python3 - <<PY\ns += "from . import pkg"\nPY\ngit add src/app/a.py docs/README.md; git status'
expect 0 "git add 後面接別的指令（ls ./、訊息裡有 .）→ 放行" 'git add a.py && ls ./ && git commit -m "x ."'
expect 0 "兩段都指名、其中一段 -p → 放行"      'git add -p a.py; git add b.py'
expect 0 "引號包住的檔名 → 放行"               'git add "src/app/a.py"'
expect 0 "commit 訊息裡寫到 -a → 放行"         'git add a.py && git commit -m "remove -a flag"'
expect 0 "git commit --amend → 放行"           'git add a.py && git commit --amend --no-edit'
expect 0 "一般 git commit -m → 放行"           'git add a.py && git commit -q -m "add a thing"'
expect 0 "檔名裡有 A → 放行"                   'git add scripts/Abc.py'
expect 0 "git -C <路徑> add 指名檔案 → 放行"    'git -C /tmp/wt add a.py'
expect 0 "git -C <路徑> status → 放行"          'git -C /tmp/wt status --short'
expect 0 "git -C <路徑> commit -m → 放行"       'git -C /tmp/wt commit -m "x"'
expect 0 "git -C <路徑> reset 指名雜湊 → 放行"  'git -C /tmp/wt reset --hard abc1234'
expect 0 "git log HEAD~3..HEAD（只是看）→ 放行" 'git log --oneline HEAD~3..HEAD'
expect 0 "git diff HEAD^（只是看）→ 放行"       'git diff HEAD^ -- a.py'
expect 0 "名字在這裡不是資料夾 → 當檔名放行"    'git add onlyhere'

# ── 逃生口：cache/git-scope-override ───────────────────────
touch "$R/cache/git-scope-override"
expect 0 "有 git-scope-override → git add -A 放行"   'git add -A'
expect 0 "有 git-scope-override → reset HEAD^ 放行"  'git reset --mixed HEAD^'
rm -f "$R/cache/git-scope-override"
expect 2 "override 刪掉之後 → 照擋"                  'git add -A'

# ── 擋下時要講得出怎麼改寫、逃生口在哪 ─────────────────────
payload 'git add -A'
msg="$(bash "$HOOK" 2>&1 >/dev/null < "$TMP/payload.json")"
case "$msg" in *指名到檔案*git-scope-override*) ok "git add 擋下訊息：講出改寫方式與逃生口" ;; *) err "git add 擋下訊息缺改寫方式或逃生口：$msg" ;; esac
payload 'git reset --mixed HEAD^'
msg="$(bash "$HOOK" 2>&1 >/dev/null < "$TMP/payload.json")"
case "$msg" in *雜湊*git-scope-override*) ok "reset 擋下訊息：講出改寫方式與逃生口" ;; *) err "reset 擋下訊息缺改寫方式或逃生口：$msg" ;; esac

# ── 讀不懂的輸入：安靜放行，不是報錯 ───────────────────────
: > "$TMP/payload.json"
bash "$HOOK" < "$TMP/payload.json" >/dev/null 2>&1
code=$?
[ "$code" = 0 ] && ok "空的輸入 → 安靜放行" || err "空的輸入（期望 exit 0，實際 ${code}）"
printf '這不是 JSON' > "$TMP/payload.json"
bash "$HOOK" < "$TMP/payload.json" >/dev/null 2>&1
code=$?
[ "$code" = 0 ] && ok "不是 JSON 的輸入 → 安靜放行" || err "不是 JSON 的輸入（期望 exit 0，實際 ${code}）"
printf '{"tool_input":{"file_path":"a.py"}}' > "$TMP/payload.json"
bash "$HOOK" < "$TMP/payload.json" >/dev/null 2>&1
code=$?
[ "$code" = 0 ] && ok "沒有 command 的輸入（不是 Bash 工具）→ 安靜放行" || err "沒有 command 的輸入（期望 exit 0，實際 ${code}）"

[ "$fail" = 0 ] && echo "[git-scope-gate-test] 全部通過" || exit 1
