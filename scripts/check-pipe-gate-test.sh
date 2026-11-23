#!/usr/bin/env bash
# check-pipe-gate-hook.sh 的自動化測試（源專案 v4.90.0）。守門工具自己也要有測試。
#
# 「該放行的」跟「該擋的」一樣要釘住：這道閘門每一條 Bash 指令都會經過，
# 誤擋到 `grep "make check" Makefile | head` 這種只是提到的指令，大家就會開始繞它。
#
# 全部在沙盒裡跑：把 hook 複製進 $TMP/repo/scripts/，旁邊放測試自己寫的 framework-config.sh。
# 測的是閘門怎麼判斷，不是這個專案的清單現在列了什麼——專案改了 NO_PIPE_COMMANDS，這裡不該跟著紅。
# 最後一段才拿真的 hook 配真的設定檔，確認清單上每一筆都擋得到。
set -uo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"

fail=0
err() { echo "[check-pipe-gate-test] ✗ $1" >&2; fail=1; }
ok() { echo "[check-pipe-gate-test] ✓ $1"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
R="$TMP/repo"
mkdir -p "$R/scripts"
cp "$SRC/scripts/check-pipe-gate-hook.sh" "$R/scripts/"
HOOK="$R/scripts/check-pipe-gate-hook.sh"

config() {  # config <framework-config.sh 的內容>
  printf '%s\n' "$1" > "$R/scripts/framework-config.sh"
}
payload() {  # payload <指令> -> 寫進 $TMP/payload.json
  python3 -c 'import json,sys;print(json.dumps({"tool_input":{"command":sys.argv[1]}}))' "$1" > "$TMP/payload.json"
}
run() {  # run <hook> <指令> -> echo exit code
  # 從檔案餵 stdin、不接管線：接管線的話這支測試開了 pipefail，拿到的會是前一段的結束碼而不是 hook 的
  payload "$2"
  bash "$1" < "$TMP/payload.json" >/dev/null 2>&1
  echo $?
}
expect() {  # expect <期望 exit> <說明> <指令>
  local code; code=$(run "$HOOK" "$3")
  [ "$code" = "$1" ] && ok "$2" || err "$2（期望 exit $1，實際 ${code}）"
}

FULL='NO_PIPE_COMMANDS=("make check" "make ticket-lint" "npm test" "pytest" "./scripts/ticket-lint.sh")'
config "$FULL"

# ── 該擋的：檢查指令後面直接接管線 ─────────────────────────
expect 2 "make check | tail → 擋"                        'make check | tail -3'
expect 2 "管線前後沒空白 → 擋"                           'make check|tail -3'
expect 2 "2>&1 之後接管線 → 擋"                          'make check 2>&1 | tail -20'
expect 2 "|& → 擋"                                       'make check |& tail -1'
expect 2 "接 grep 數行數 → 擋"                           'npm test -- --ci | grep -c FAIL'
expect 2 "接 tee（一樣吞掉結束碼）→ 擋"                  'make check | tee /tmp/out.txt'
expect 2 "cd 之後跑檢查接管線 → 擋"                      'cd sub && make check | tail'
expect 2 "前一段通過才跑的檢查接管線 → 擋"               'pytest -q && make check | tail -1'
expect 2 "前面帶環境變數 → 擋"                           'FOO=1 make check | tail -1'
expect 2 "time 開頭 → 擋"                                'time make check | tail'
expect 2 "多行裡其中一行 → 擋"                           $'echo start\nmake check | tail -1\necho done'
expect 2 "反斜線換行之後才接管線 → 擋"                   $'make check \\\n  | tail -1'

# ── 該擋的：同一支指令的各種寫法 ───────────────────────────
expect 2 "make 的目標前面有選項（-C sub）→ 擋"           'make -C sub check | tail'
expect 2 "make 的目標後面帶變數 → 擋"                    'make check fix=1 | tail'
expect 2 "清單上另一個 make 目標 → 擋"                   'make ticket-lint | tail -5'
expect 2 "gmake（make 的另一個名字）→ 擋"                'gmake check | tail'
expect 2 "指令後面還有參數 → 擋"                         'npm test -- --ci 2>&1 | tail -3'
expect 2 "虛擬環境裡的路徑 → 擋"                         '.venv/bin/pytest -q | tail -1'
expect 2 "python3 -m 的寫法 → 擋"                        'python3 -m pytest -q | tail -1'
expect 2 "腳本用 ./ 開頭 → 擋"                           './scripts/ticket-lint.sh | tail'
expect 2 "腳本不帶 ./ → 擋"                              'scripts/ticket-lint.sh | tail'
expect 2 "用 bash 跑腳本 → 擋"                           'bash scripts/ticket-lint.sh 2>&1 | tail -1'

# ── 該擋的：包在別的指令裡跑 ───────────────────────────────
expect 2 "env 包起來 → 擋"                               'env FOO=1 make check | tail'
expect 2 "timeout 包起來 → 擋"                           'timeout 600 make check | tail'
expect 2 "uv run 包起來 → 擋"                            'uv run pytest -q | tail -3'
expect 2 "docker compose exec → 擋"                      'docker compose exec -T web pytest -q | tail -2'
expect 2 "docker run … sh -c 整個接管線 → 擋"            'docker run --rm -v "$PWD:/app" img sh -c "pytest -q && echo ok" | tail -5'
expect 2 "sh -c 的引號裡自己接管線 → 擋"                 'sh -c "make check | tail -1"'
expect 2 "bash -lc 的引號裡自己接管線 → 擋"              'bash -lc "make check | tail -1"'
expect 2 "bash -o pipefail -c 的引號裡自己接管線 → 照擋" 'bash -o pipefail -c "make check | tail -1"'
expect 2 "docker … sh -c 的引號裡自己接管線 → 擋"        'docker run --rm img sh -c "pytest -q | tail -1"'
expect 2 "xargs 帶著跑、輸出再接管線 → 擋"               'git diff --name-only | xargs pytest | tail'
expect 2 "包裝的選項值名字很像、後面才是檢查 → 擋"       'uv run --with pytest-cov pytest -q | tail'
expect 2 "檢查自己的參數裡有 install → 照擋"             'timeout 600 npm test -- --grep install | tail'
expect 2 "指令替換 \$( ) 裡接管線 → 擋"                  'out=$(make check | tail -1)'

# ── 該擋的：整組收尾之後才接管線 ───────────────────────────
expect 2 "括號整組接管線 → 擋"                           '(cd sub && make check) | tail'
expect 2 "括號跟管線黏在一起 → 擋"                       '(cd sub && make check)| tail'
expect 2 "括號之後先轉向再接管線 → 擋"                   '(cd sub && make check) 2>&1 | tail'
expect 2 "大括號整組接管線 → 擋"                         '{ make check; } | tail'
expect 2 "大括號之後先轉向再接管線 → 擋"                 '{ make check; } 2>&1 | tail -3'
expect 2 "for 迴圈整組接管線 → 擋"                       'for d in a b; do make -C "$d" check; done | tail'
expect 2 "while 迴圈整組接管線 → 擋"                     'while read -r d; do make -C "$d" check; done < dirs.txt | tail'
expect 2 "if 整組接管線 → 擋"                            'if make check; then echo ok; fi | tail'
expect 2 "if 的條件裡接管線 → 擋"                        'if ! make check | tail -1; then echo x; fi'
expect 2 "case 整組接管線 → 擋"                          'case "$x" in a) make check ;; esac | tail'
expect 2 "迴圈裡包 if、整組接管線 → 擋"                  'for d in a b; do if [ -d "$d" ]; then make -C "$d" check; fi; done | tail'

# ── 該擋的：註解與 heredoc 不能把後面的指令藏起來 ──────────
expect 2 "註解一行、下一行檢查接管線 → 擋"               $'# 跑檢查\nmake check | tail -3'
expect 2 "註解裡有撇號 → 擋"                             $'# don\'t skip this\nmake check | tail -3'
expect 2 "檢查接管線、行尾才是註解 → 擋"                 'make check | tail -3  # 看最後幾行'
expect 2 '前面有 "${#陣列[@]}"（# 不是註解）→ 擋'        'echo "${#arr[@]}"; make check | tail'
expect 2 '前面有沒加引號的 ${#陣列[@]} → 擋'             'echo ${#arr[@]}; make check | tail'
expect 2 "單引號裡的 # 不是註解 → 擋"                    "echo 'a # b'; make check | tail"
expect 2 "雙引號裡的 # 不是註解 → 擋"                    'echo "a # b"; make check | tail'
expect 2 "heredoc 內文有撇號、後面檢查接管線 → 擋"       $'cat > notes.txt <<EOF\nit\'s fine\nEOF\nmake check | tail -1'
expect 2 "註解裡有撇號、下一行整組接管線 → 擋"           $'# don\'t skip this\n(cd sub && make check) | tail'
expect 2 "heredoc 內文有撇號、後面整組接管線 → 擋"       $'cat > notes.txt <<EOF\nit\'s fine\nEOF\n(cd sub && make check) | tail -1'

# ── 該放行的：檢查沒接管線 ─────────────────────────────────
expect 0 "直接跑 → 放行"                                 'make check'
expect 0 "|| 接後續（不是管線）→ 放行"                   'make check || echo 沒過'
expect 0 "導到檔案 → 放行"                               'make check > /tmp/c.txt 2>&1; echo "exit=$?"'
expect 0 "導到檔案再讀尾段 → 放行"                       'make check > out.txt 2>&1; tail -5 out.txt'
expect 0 "&> 導到檔案 → 放行"                            'make check &> out.txt'
expect 0 ">| 覆寫導向（不是管線）→ 放行"                 'make check >| out.txt'
expect 0 "丟到背景跑 → 放行"                             'make check > out.txt 2>&1 &'
expect 0 "檢查之後另一段才接管線 → 放行"                 'make check; git status --short | head'
expect 0 "檢查通過才做的下一段接管線 → 放行"             'make check && echo ok | cat'
expect 0 "管線在前、檢查在最後一段 → 放行"               'git diff --name-only | xargs pytest'
expect 0 "括號整組沒接管線 → 放行"                       '(cd sub && make check); ls | head'
expect 0 "括號整組導到檔案 → 放行"                       '(cd sub && make check) > out.txt 2>&1; tail out.txt'
expect 0 "大括號整組導到檔案 → 放行"                     '{ make check; } > out.txt 2>&1'
expect 0 "case 的分支裡跑檢查、管線在別處 → 放行"        'case "$x" in a) make check ;; esac; ls | tail'
expect 0 "檢查沒接管線、行尾註解裡有 | → 放行"           'make check  # 不要接 | tail'

# ── 該放行的：只是提到這些字 ───────────────────────────────
expect 0 "grep 找這些字 → 放行"                          'grep -n "make check" Makefile | head -30'
expect 0 "grep -rn 找指令名稱 → 放行"                    'grep -rn "pytest" . | head'
expect 0 "echo 的內容 → 放行"                            'echo "先跑 make check 再推" | cat'
expect 0 "commit 訊息裡寫到 → 放行"                      'git commit -m "ci: make check | tail 不要這樣寫" && git log --oneline | head -3'
expect 0 "看腳本內容 → 放行"                             'cat scripts/ticket-lint.sh | head -20'
expect 0 "行尾註解裡寫到 → 放行"                         'ls | head  # make check | tail'
expect 0 "整行註解裡寫到 → 放行"                         $'# make check | tail -3 不要這樣寫\nls'
expect 0 "heredoc 內文裡寫到 → 放行"                     $'cat > notes.md <<EOF\nmake check | tail -3\nEOF\nls | head'
expect 0 "加引號的 heredoc 內文裡寫到 → 放行"            $'cat > notes.md <<\'EOF\'\nmake check | tail -3\nEOF\nls | head'
expect 0 "問指令裝在哪（command -v）→ 放行"              'command -v pytest | head -1'
expect 0 "裝套件（uv pip install）→ 放行"                'uv pip install pytest 2>&1 | tail -3'
expect 0 "裝套件（sudo apt-get install）→ 放行"          'sudo apt-get install -y pytest | tail -2'
expect 0 "容器裡裝套件 → 放行"                           'docker compose exec web pip install pytest | tail'
expect 0 "xargs grep 找指令名稱 → 放行"                  'git ls-files | xargs grep -l pytest | head'
expect 0 "裝套件（poetry add）→ 放行"                    'poetry add --group dev pytest | tail'
expect 0 "別的工具的 -c（grep -c）後面不是指令 → 放行"   'git ls-files | xargs grep -c "make check | tail" | head'

# ── 該放行的：不在清單上 ───────────────────────────────────
expect 0 "別的 make 目標 → 放行"                         'make help | tail -5'
expect 0 "同一支工具的別的子指令 → 放行"                 'npm run build | tail'
expect 0 "名字只有開頭一樣的指令 → 放行"                 'pytest-watch | tail'
expect 0 "名字只有開頭一樣的檔案 → 放行"                 'cat pytest.ini | head'
expect 0 "一般指令接管線 → 放行"                         'ls -la | head'
expect 0 "迴圈整組接管線、裡面沒有檢查 → 放行"           'for f in a b; do echo "$f"; done | tail'
expect 0 "空的指令 → 放行"                               ''

# ── 解析不了（引號不成對）：退回逐行比對，寧可漏擋也不亂擋 ──
expect 2 "引號不成對、行首就是檢查接管線 → 擋"           $'make check | tail -1\necho "沒收尾'
expect 2 "引號不成對、檢查先轉向再接管線 → 擋"           $'pytest -q 2>&1 | tail -1\necho "沒收尾'
expect 2 "引號不成對、腳本接管線 → 擋"                   $'./scripts/ticket-lint.sh | tail\necho "沒收尾'
expect 2 "引號不成對、腳本不帶 ./ → 擋"                  $'scripts/ticket-lint.sh | tail\necho "沒收尾'
expect 0 "引號不成對、沒有檢查接管線 → 放行"             $'ls | head\necho "沒收尾'
expect 0 "引號不成對、只是提到 → 放行"                   'grep "make check | tail'
expect 0 "引號不成對、檢查用 || 接後續 → 放行"           'make check || echo "沒收尾'
expect 0 "引號不成對、heredoc 內文裡寫到 → 放行"         $'cat > n.md <<EOF\nmake check | tail -3\nEOF\necho "沒收尾'

# ── 擋下時要講得出是哪一支、怎麼改寫、清單在哪 ─────────────
payload 'cd sub && npm test -- --ci 2>&1 | tail -3'
msg="$(bash "$HOOK" 2>&1 >/dev/null < "$TMP/payload.json")"
case "$msg" in *"（npm test）"*) ok "擋下訊息：點名是清單上哪一筆" ;; *) err "擋下訊息沒點名是哪一筆：$msg" ;; esac
case "$msg" in *導到檔案*NO_PIPE_COMMANDS*) ok "擋下訊息：講出改寫方式與清單在哪" ;; *) err "擋下訊息缺改寫方式或清單位置：$msg" ;; esac
# 訊息教的改寫方式自己要過得了閘門，不然照著改還是被擋
expect 0 "訊息教的改寫方式（導到檔案、印結束碼）→ 放行"  'npm test > /tmp/check.txt 2>&1; echo "exit=$?"'
expect 0 "訊息教的改寫方式（再讀尾段）→ 放行"            'tail -40 /tmp/check.txt'

# ── 讀不懂的輸入：安靜放行，不是報錯 ───────────────────────
raw() {  # raw <說明> <stdin 內容>
  printf '%s' "$2" > "$TMP/payload.json"
  bash "$HOOK" < "$TMP/payload.json" >/dev/null 2>&1
  local code=$?
  [ "$code" = 0 ] && ok "$1 → 安靜放行" || err "$1（期望 exit 0，實際 ${code}）"
}
raw "空的輸入" ''
raw "不是 JSON 的輸入" '這不是 JSON'
raw "沒有 command 的輸入（不是 Bash 工具）" '{"tool_input":{"file_path":"a.py"}}'
raw "command 不是字串" '{"tool_input":{"command":["make","check"]}}'

# ── 設定：清單決定守備範圍 ─────────────────────────────────
config 'NO_PIPE_COMMANDS=("npm test")'
expect 0 "清單沒列的指令 → 不擋"                         'make check | tail -3'
expect 2 "清單有列的指令 → 擋"                           'npm test | tail -3'
config 'NO_PIPE_COMMANDS=()'
expect 0 "清單是空的 → 什麼都不擋"                       'make check | tail -3'
config 'PROJECT_NAME="demo"'
expect 0 "設定檔沒有 NO_PIPE_COMMANDS → 放行"            'make check | tail -3'
payload 'make check | tail -3'
msg="$(bash "$HOOK" 2>&1 >/dev/null < "$TMP/payload.json")"
[ -z "$msg" ] && ok "設定檔沒有 NO_PIPE_COMMANDS → 不印任何錯誤" || err "設定檔沒有 NO_PIPE_COMMANDS 時印了東西：$msg"
rm -f "$R/scripts/framework-config.sh"
expect 0 "連設定檔都沒有 → 放行"                         'make check | tail -3'

# ── 真的 hook 配真的設定檔：清單上每一筆都擋得到 ───────────
REAL="$SRC/scripts/check-pipe-gate-hook.sh"
(
  NO_PIPE_COMMANDS=()
  # shellcheck disable=SC1091
  [ -f "$SRC/scripts/framework-config.sh" ] && . "$SRC/scripts/framework-config.sh"
  [ "${#NO_PIPE_COMMANDS[@]}" -gt 0 ] && printf '%s\n' "${NO_PIPE_COMMANDS[@]}"
) > "$TMP/entries.txt" 2>/dev/null
n=0
while IFS= read -r entry; do
  [ -n "$entry" ] || continue
  n=$((n + 1))
  code=$(run "$REAL" "${entry} | tail -1")
  [ "$code" = 2 ] && ok "真的設定檔列的「${entry}」接管線 → 擋" || err "真的設定檔列的「${entry}」接管線沒被擋（期望 exit 2，實際 ${code}）"
done < "$TMP/entries.txt"
[ "$n" -gt 0 ] || echo "[check-pipe-gate-test] （注意）scripts/framework-config.sh 的 NO_PIPE_COMMANDS 是空的：這道閘門目前不擋任何指令"
code=$(run "$REAL" 'ls -la | head')
[ "$code" = 0 ] && ok "真的 hook：一般指令接管線 → 放行" || err "真的 hook 把一般指令擋下來了（期望 exit 0，實際 ${code}）"

[ "$fail" = 0 ] && echo "[check-pipe-gate-test] 全部通過" || exit 1
