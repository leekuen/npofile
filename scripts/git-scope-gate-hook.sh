#!/usr/bin/env bash
# PreToolUse hook（matcher: Bash）：「git 指令的波及範圍」閘門（源專案 v4.29.0）。
#
# 來歷：源專案一天內連續出了三次事。看起來是三個不同的失誤，其實是同一個——
# **對「這個目錄現在是什麼狀態」的認知是舊的，卻直接下了會改動它的指令。**
# 框架的核心約定是平行多 session，主目錄隨時可能被別條 session 動過。
#
#   事故一：想提交一張票，用了 `git add tickets/`，把使用者明講「還不想提交」的另外兩張票
#           一起掃進 commit、推上了整合分支。
#           （「絕不盲目 git add -A」本來就背得出來，但被背成字面：以為指定資料夾就安全——
#             對「不是我改的東西」而言，兩者一視同仁。）
#   事故三：想退掉那個誤提交，用了 `git reset --mixed HEAD^`，但主目錄的 HEAD
#           早已被另一條 session 推進，退掉的是**別人的 commit**。
#
# 所以擋兩類指令：
#   1) `git add` 用 `-A`／`-u`／`.`／`*`／資料夾，以及 `git commit -a` → 要求指名到檔案。
#   2) `git reset`／`revert`／`rebase` 用 `HEAD^`／`HEAD~n` 這種相對指法
#      → 要求指名 commit 雜湊（相對指法在別人也在寫的分支上等於盲射）。
#
# 邊界（誠實聲明）：
#   ・只看指令字串，不解析 git 語意；寧可誤擋也不放行（擋下時會告訴你怎麼改寫）。
#   ・`git add -p`（互動挑 hunk）與指名檔案一律放行。
#   ・`git -C <路徑> add …` 這種把全域選項夾在中間的寫法會先拿掉選項再判斷（模板內補的：
#     「跨工作樹用絕對路徑」正是叫人這樣寫，不處理的話這一整類都看不到）；
#     選項的值裡有空白又沒加引號之類的少見寫法認不出來，會漏擋。
#   ・「是不是資料夾」對照的是 hook 所在的這一棵與指令實際執行的目錄；`-C` 指到的那個目錄不看。
#   ・確有必要時 `touch cache/git-scope-override` 放行一次，事後刪（比照 ui-design 閘門）。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

read -r -d '' PY <<'PYEOF' || true
import json, re, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
cmd = (d.get("tool_input") or {}).get("command") or ""
# git 與子指令中間的全域選項先拿掉：git -C <路徑> add -A → git add -A
VAL = r'''(?:"[^"]*"|'[^']*'|[^\s;&|]+)'''
OPT = (r'(?:\s+(?:-C|-c|--git-dir|--work-tree|--namespace)\s+' + VAL
       + r'|\s+--(?:git-dir|work-tree|namespace)=' + VAL
       + r'|\s+(?:--no-pager|--paginate|--bare|--no-replace-objects|--literal-pathspecs|--no-optional-locks))+')
cmd = re.sub(r'(^|[;&|\s])git' + OPT + r'(?=\s)', r'\1git', cmd)
# 第一行給執行目錄，其餘是指令（指令本身可能有很多行）
print((d.get("cwd") or "").replace("\n", " "))
print(cmd)
PYEOF

# 先把 stdin 讀完再做任何判斷：還沒讀就結束，送資料進來的那一端會收到 broken pipe
PAYLOAD=$(cat)
OUT=$(printf '%s' "$PAYLOAD" | python3 -c "$PY" 2>/dev/null || true)
CWD=$(printf '%s\n' "$OUT" | sed -n '1p')
CMD=$(printf '%s\n' "$OUT" | sed '1d')

[ -n "${CMD:-}" ] || exit 0

# 明確放行的逃生口（事後要刪）
[ -f "$ROOT/cache/git-scope-override" ] && exit 0

is_dir() {  # 這個參數實際上是不是資料夾（`git add tickets` 少打一個 / 也一樣是整包）
  case "$1" in /*) [ -d "$1" ]; return ;; esac
  [ -d "$ROOT/$1" ] && return 0
  [ -n "$CWD" ] && [ -d "$CWD/$1" ]
}

# ── 1) git add 的範圍 ─────────────────────────────────────
if printf '%s' "$CMD" | grep -Eq '(^|[;&|[:space:]])git[[:space:]]+add([[:space:]]|$)'; then
  # 取出每一個 `git add` 之後那一段（同一行、到下一個 ; && || 之前），**逐段判斷**。
  # **只取那一段、不取整條指令**：源專案原本用 sed 逐行改寫，沒有 `git add` 的其他行會原封不動
  # 留下來——一段 Python 的 `from . import x` 就被當成 `git add .` 擋下，
  # 而那條指令裡真正的 `git add` 全是指名檔案（源專案 v4.78.0）。
  # 反斜線換行先接回同一行，不然續行上的 `.`、`tickets/` 會漏掉。
  # -p / --patch 是互動挑 hunk，只放行**那一段**（`git add -p a; git add .` 的後半照擋）。
  BAD=""
  while IFS= read -r SEG; do
    SEG=$(printf '%s' "$SEG" | sed -E 's/^.*git[[:space:]]+add[[:space:]]*//' | tr -d "\"'")
    printf ' %s ' "$SEG" | grep -Eq ' (-p|--patch) ' && continue
    printf ' %s ' "$SEG" | grep -Eq ' (-[a-zA-Z]*[Au][a-zA-Z]*|--all|--update|\.|\.\.|:/|\*) ' && BAD="${BAD:-範圍旗標（-A / -u / . / *）}"
    # 資料夾：結尾是 /，或實際上是資料夾
    set -f  # 參數裡的 * 不要展開成檔名
    for a in $SEG; do
      case "$a" in -*) continue ;; esac
      if [ "${a%/}" != "$a" ] || is_dir "$a"; then
        case "$BAD" in *資料夾*) ;; *) BAD="${BAD:+${BAD}、}資料夾" ;; esac
      fi
    done
    set +f
  done < <(printf '%s\n' "$CMD" | sed -e ':a' -e '/\\$/N; s/\\\n/ /; ta' \
    | grep -Eo '(^|[;&|[:space:]])git[[:space:]]+add([[:space:]][^;&|]*)?')
  if [ -n "$BAD" ]; then
    cat >&2 <<EOF
[git-scope-gate] 擋下：\`git add\` 用了${BAD}。

這個 repo 的約定是**平行多 session**，同一個目錄隨時可能有別人還沒提交的工作。
\`git add -A\` 與 \`git add <資料夾>\` 對「不是我改的東西」一視同仁——
源專案就是這樣把使用者明講「還不想提交」的票掃進 commit、推上了整合分支。

請**指名到檔案**：
  git add path/to/file1 path/to/file2
若真的要挑局部：git add -p
（確有必要整批加：touch cache/git-scope-override 放行一次，事後刪）
EOF
    exit 2
  fi
fi

# ── 1b) git commit -a（等於先 `git add -u` 再提交，一樣擋）──
# 引號裡的字先拿掉，commit 訊息寫到「-a」不算
if printf '%s\n' "$CMD" | sed -E "s/\"[^\"]*\"//g; s/'[^']*'//g" \
  | grep -Eo '(^|[;&|[:space:]])git[[:space:]]+commit([[:space:]][^;&|]*)?' \
  | grep -Eq '[[:space:]](-[a-zA-Z]*a[a-zA-Z]*|--all)([[:space:]]|$)'; then
  cat >&2 <<'EOF'
[git-scope-gate] 擋下：`git commit -a` 會把所有已追蹤檔案的修改一起提交，包括別條 session 改到一半的。

請先指名檔案 `git add path/to/file`，再 `git commit`（不加 -a）。
（確有必要：touch cache/git-scope-override 放行一次，事後刪）
EOF
  exit 2
fi

# ── 2) 相對 commit 指法 ───────────────────────────────────
if printf '%s' "$CMD" | grep -Eq '(^|[;&|[:space:]])git[[:space:]]+(reset|revert|rebase)([[:space:]]|$)'; then
  if printf '%s' "$CMD" | grep -Eq 'HEAD(\^|~[0-9]*)'; then
    cat >&2 <<'EOF'
[git-scope-gate] 擋下：`git reset/revert/rebase` 用了 HEAD^ / HEAD~n。

平行多 session 下，HEAD 可能在你上次看之後就前進了——相對指法等於盲射。
源專案就是這樣用 `git reset --mixed HEAD^` 退掉了**別條 session 剛推的 commit**。

請先看清楚再指名 commit 雜湊：
  git log --oneline -5
  git reset --mixed <你確認過的雜湊>
（確有必要用相對指法：touch cache/git-scope-override 放行一次，事後刪）
EOF
    exit 2
  fi
fi

exit 0
