#!/usr/bin/env bash
# git-sync-gate-hook.sh 的自動化測試（模板內補的；源專案這支閘門沒有測試）。守門工具自己也要有測試。
#
# 重點案例：
#   ・源專案 v4.19.1：hook 腳本永遠在主目錄底下，主目錄落後時，在工作區推送不能被誤擋——
#     量的要是實際推的那一棵。
#   ・模板內補的：`git -C <工作區> push`、`cd <工作區> && git push`——指令自己講了在哪裡推，就量那一棵。
#
# 全部在沙盒裡跑：一個假的遠端（bare repo）、一個主目錄（hook 複製到它的 scripts/ 底下，
# 所以 hook 算出來的主目錄就是沙盒的）、幾個工作區、一個用來「讓遠端往前走」的別人。
# 不碰真的 repo、不連網路。
set -uo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
# 從 git hook 裡被叫起來時，環境會帶著 GIT_DIR／GIT_WORK_TREE／GIT_INDEX_FILE，
# 沙盒裡的 git 會全部打到真的 repo。先清掉。
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
# 使用者自己的 git 設定（簽章、hooksPath、pull 的預設行為）不帶進沙盒
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com

fail=0
err() { echo "[git-sync-gate-test] ✗ $1" >&2; fail=1; }
ok() { echo "[git-sync-gate-test] ✓ $1"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# macOS 的暫存目錄會經過一層連結（/var → /private/var）。統一成實際路徑，
# 擋下訊息裡印的路徑才比對得起來。
TMP="$(cd "$TMP" && pwd -P)"
# 暫存目錄本身萬一位在某個 repo 底下，「不是 git 工作樹的資料夾」那幾條會測到那個 repo 上。
# 叫 git 往上找 repo 時到沙盒為止。
export GIT_CEILING_DIRECTORIES="$TMP"

O="$TMP/origin.git"   # 假的遠端
M="$TMP/main"         # 主目錄（hook 住在這裡）
W="$TMP/wt"           # 工作區：feature/TK-1
S="$TMP/sp ace"       # 工作區：feature/TK-2（路徑有空白）
N="$TMP/fresh"        # 工作區：feature/TK-9（全新分支，沒推過）
X="$TMP/other"        # 別人的 clone，用來讓遠端往前走
F="$TMP/offline"      # 連不到遠端的 clone
P="$TMP/plain/deep"   # 不是 git 工作樹的普通資料夾（多一層：從這裡算 ../wt 對不到任何工作區）

must() {  # 建沙盒用：這裡失敗就不用往下測了
  "$@" >/dev/null 2>&1 || { echo "[git-sync-gate-test] ✗ 沙盒建不起來：$*" >&2; exit 1; }
}
commit() {  # commit <repo> <訊息>
  echo "$2" >> "$1/f.txt"
  must git -C "$1" add f.txt
  must git -C "$1" commit -m "$2"
}
advance() {  # advance <分支>：別人往遠端的這條分支多推一個 commit
  must git -C "$X" fetch origin
  must git -C "$X" checkout -B "$1" "origin/$1"
  commit "$X" "別人推的 $1"
  must git -C "$X" push origin "$1"
}

must git init --bare "$O"
must git init "$M"
must git -C "$M" checkout -b stage
mkdir -p "$M/scripts" "$P"
cp "$SRC/scripts/git-sync-gate-hook.sh" "$M/scripts/"
HOOK="$M/scripts/git-sync-gate-hook.sh"
commit "$M" "base"
must git -C "$M" remote add origin "$O"
must git -C "$M" push -u origin stage
must git -C "$O" symbolic-ref HEAD refs/heads/stage
for b in feature/TK-1 feature/TK-2; do
  must git -C "$M" branch "$b" stage
  must git -C "$M" push -u origin "$b"
done
must git -C "$M" worktree add "$W" feature/TK-1
must git -C "$M" worktree add "$S" feature/TK-2
must git -C "$M" worktree add -b feature/TK-9 "$N" stage
must git clone "$O" "$X"

payload() {  # payload <指令> [執行目錄] -> 寫進 $TMP/payload.json
  python3 -c 'import json,sys;print(json.dumps({"tool_input":{"command":sys.argv[1]},"cwd":sys.argv[2]}))' \
    "$1" "${2:-}" > "$TMP/payload.json"
}
run() {  # run <指令> [執行目錄] -> echo exit code
  # 從檔案餵 stdin、不接管線：接管線的話這支測試開了 pipefail，拿到的會是前一段的結束碼而不是 hook 的。
  # hook 自己從一個不相干的資料夾起跑：相對路徑要是沒接到執行目錄上，從這裡算一定對不到工作區。
  payload "$1" "${2:-}"
  (cd "$P" && bash "$HOOK" < "$TMP/payload.json" >/dev/null 2>&1)
  echo $?
}
expect() {  # expect <期望 exit> <說明> <指令> [執行目錄]
  local code; code=$(run "$3" "${4:-}")
  [ "$code" = "$1" ] && ok "$2" || err "$2（期望 exit $1，實際 ${code}）"
}

# ── 都沒落後 ───────────────────────────────────────────────
expect 0 "都沒落後：在主目錄推 → 放行"                     'git push' "$M"
expect 0 "都沒落後：在工作區推 → 放行"                     'git push origin feature/TK-1' "$W"
commit "$S" "還沒推的本地 commit"
expect 0 "本地有還沒推的 commit、沒落後 → 放行（這正是要推的時候）" 'git push' "$S"

# ── 主目錄（stage）落後一個 commit，工作區的分支沒落後 ─────
advance stage
expect 2 "主目錄落後：在主目錄推 → 擋"                     'git push' "$M"
expect 2 "主目錄落後：強推也擋（正是會蓋掉別人 commit 的那一種）" 'git push --force origin stage' "$M"
expect 2 "前面先跑別的才推 → 擋"                           'make check && git push' "$M"
expect 2 "多行裡其中一行是推 → 擋"                         $'echo hi\ngit push'  "$M"
expect 2 "括號包起來推 → 擋"                               '(git push)' "$M"
expect 2 "推完後面還接別的 → 擋"                           'git push; echo done' "$M"
expect 2 "git --no-pager push → 擋"                        'git --no-pager push' "$M"
expect 2 "git -c 設定 push → 擋"                           'git -c push.default=current push' "$M"
expect 2 "git --work-tree=<路徑> push → 擋"                "git --work-tree=$M push" "$M"
expect 0 "主目錄落後：不是 push 的 git 指令 → 放行"        'git status' "$M"
expect 0 "主目錄落後：不是 git 指令 → 放行"                'ls -la' "$M"
expect 0 "主目錄落後：只是名字開頭一樣（git pushall）→ 放行" 'git pushall' "$M"
expect 0 "主目錄落後：只是名字結尾一樣（mygit push）→ 放行" 'mygit push' "$M"
expect 0 "主目錄落後：只是印出這幾個字 → 放行"             'echo "git push"' "$M"
expect 0 "主目錄落後、在工作區推 → 放行（量的是執行目錄那一棵，不是腳本所在的主目錄）" 'git push' "$W"
expect 0 "主目錄落後、在還沒推過的新分支上推（沒有上游）→ 放行" 'git push -u origin feature/TK-9' "$N"

# 指令自己講了在哪裡推
expect 0 "人在主目錄、git -C 工作區 push → 放行"           "git -C $W push" "$M"
expect 0 "人在主目錄、cd 工作區 && git push → 放行"        "cd $W && git push" "$M"
expect 0 "人在主目錄、(cd 工作區 && git push) → 放行"      "(cd $W && git push)" "$M"
expect 0 "人在主目錄、cd 工作區之後還跑了別的才推 → 放行"  "cd $W; make check && git push origin feature/TK-1" "$M"
expect 0 "相對路徑：git -C ../wt push → 放行"              'git -C ../wt push' "$M"
expect 0 "相對路徑：cd ../wt && git push → 放行"           'cd ../wt && git push' "$M"
expect 0 "路徑有空白、用雙引號包 → 放行"                   "git -C \"$S\" push" "$M"
expect 0 "路徑有空白、用單引號包 → 放行"                   "cd '$S' && git push" "$M"
expect 0 "git 的其他全域選項夾在中間 → 放行"               "git --no-pager -C $W push" "$M"
expect 0 "連續 cd：照順序接起來 → 放行"                    'cd main && cd ../wt && git push' "$TMP"
expect 2 "連續 cd：最後停在主目錄 → 擋"                    'cd wt && cd ../main && git push' "$TMP"
expect 0 "連續 -C：後面的接在前面的底下 → 放行"           "git -C $TMP -C wt push" "$M"
expect 0 "cd 到主目錄、又 git -C 回工作區 → 放行（-C 接在 cd 後面）" "cd $M && git -C $W push" "$W"
expect 2 "人在工作區、git -C 主目錄 push → 擋"             "git -C $M push" "$W"
expect 2 "人在工作區、cd 主目錄 && git push → 擋"          "cd $M && git push origin stage" "$W"
expect 2 "推完才 cd 到工作區 → 照推的當下，擋"             "git push && cd $W" "$M"

# 包在括號裡的 cd，括號收尾之後就管不到 push 了
expect 2 "(cd 工作區 && 別的事); git push → 人還在主目錄，擋"       "(cd $W && make check); git push" "$M"
expect 0 "(cd 主目錄 && 別的事); git push → 人還在工作區，放行"     "(cd $M && make check); git push" "$W"
expect 2 "外層 cd 主目錄、內層括號 cd 工作區已收尾 → 照外層，擋"    "(cd $M && (cd $W && make check); git push)" "$W"
expect 0 "外層 cd 工作區、內層括號 cd 主目錄已收尾 → 照外層，放行"  "cd $W && (cd $M && make check) && git push" "$M"

# 指令講的地方認不出來 → 退回執行目錄
expect 0 "cd 的路徑是變數（認不出來）、人在工作區 → 照執行目錄，放行" 'cd "$WT_DIR" && git push' "$W"
expect 2 "cd 的路徑是變數（認不出來）、人在主目錄 → 照執行目錄，擋"   'cd "$WT_DIR" && git push' "$M"
expect 2 "git -C 指到不存在的路徑、人在主目錄 → 照執行目錄，擋"       "git -C $TMP/nowhere push" "$M"
expect 0 "git -C 指到不是工作樹的資料夾、人在工作區 → 照執行目錄，放行" "git -C $P push" "$W"
expect 2 "git -C 指到不是工作樹的資料夾、人在主目錄 → 照執行目錄，擋"   "git -C $P push" "$M"

# 執行目錄也不是工作樹 → 退回腳本所在的主目錄
expect 2 "執行目錄不是 git 工作樹 → 退回主目錄，擋"        'git push' "$P"
expect 2 "沒有給執行目錄 → 退回主目錄，擋"                 'git push' ""

# ── 換過來：主目錄跟上了，工作區的分支（feature/TK-1）落後一個 commit ──
must git -C "$M" fetch origin
must git -C "$M" merge --ff-only origin/stage
advance feature/TK-1
expect 0 "工作區落後、在主目錄推 → 放行"                   'git push' "$M"
expect 2 "工作區落後、在工作區推 → 擋"                     'git push' "$W"
expect 2 "工作區落後：人在主目錄、git -C 工作區 push → 擋" "git -C $W push" "$M"
expect 2 "工作區落後：人在主目錄、cd 工作區 && git push → 擋" "cd $W && git push" "$M"
expect 0 "工作區落後：人在工作區、git -C 主目錄 push → 放行" "git -C $M push" "$W"
expect 0 "工作區落後：另一個工作區不受影響 → 放行"          'git push' "$S"

# ── 再換：路徑有空白的那個工作區（feature/TK-2）也落後了 ─────
advance feature/TK-2
expect 2 "路徑有空白的工作區落後：git -C \"路徑\" push → 擋"  "git -C \"$S\" push" "$M"
expect 2 "路徑有空白的工作區落後：cd '路徑' && git push → 擋" "cd '$S' && git push" "$M"
expect 0 "路徑有空白的工作區落後：在主目錄推 → 放行"          'git push' "$M"

# ── 擋下時要講得出落後哪一條、怎麼整合、量的是哪一棵 ───────
payload 'git push' "$W"
msg="$(cd "$P" && bash "$HOOK" 2>&1 >/dev/null < "$TMP/payload.json")"
case "$msg" in *"origin/feature/TK-1 有 1 個"*) ok "擋下訊息：講出落後哪一條、幾個 commit" ;; *) err "擋下訊息沒講落後哪一條、幾個 commit：$msg" ;; esac
case "$msg" in *"git pull --rebase origin feature/TK-1"*) ok "擋下訊息：給得出整合的指令" ;; *) err "擋下訊息沒有整合的指令：$msg" ;; esac
case "$msg" in *"$W"*) ok "擋下訊息：講出量的是哪一棵" ;; *) err "擋下訊息沒講量的是哪一棵：$msg" ;; esac

# ── 連不到遠端：放行（不因網路波動擋工作）─────────────────
must git clone "$O" "$F"
advance stage
must git -C "$F" fetch origin                                # 這一棵已經知道自己落後……
must git -C "$F" remote set-url origin "$TMP/nowhere.git"    # ……但這次連不到遠端
expect 0 "這次連不到遠端 → 放行"                           'git push' "$F"

# ── 讀不懂的輸入：安靜放行，不是報錯 ───────────────────────
# （這時主目錄又落後了一個 commit：hook 要是把讀不懂的輸入當成推送、退回主目錄去量，這幾條會被擋）
raw() {  # raw <說明> <stdin 內容>
  printf '%s' "$2" > "$TMP/payload.json"
  (cd "$P" && bash "$HOOK" < "$TMP/payload.json" >/dev/null 2>&1)
  local code=$?
  [ "$code" = 0 ] && ok "$1 → 安靜放行" || err "$1（期望 exit 0，實際 ${code}）"
}
raw "空的輸入" ''
raw "不是 JSON 的輸入" '這不是 JSON'
raw "沒有 command 的輸入（不是 Bash 工具）" '{"tool_input":{"file_path":"a.py"}}'
raw "command 不是字串" '{"tool_input":{"command":["git","push"]}}'

[ "$fail" = 0 ] && echo "[git-sync-gate-test] 全部通過" || exit 1
