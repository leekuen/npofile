#!/usr/bin/env bash
# PreToolUse hook（matcher: Bash）：「推分支前先同步遠端」的機制化閘門。
# 當 agent 要跑 `git push` 時，先 fetch 對應遠端分支；若本地落後遠端（會產生衝突或
# 覆蓋他人 commit）就擋下（exit 2），要求先 `git pull --rebase` 整合再推。
#
# 量的是哪一棵（源專案 v4.19.1）：
#   框架規定開發一律在自己的工作區（源專案 v4.14.0），而這支腳本永遠位在主目錄底下。
#   固定 `cd` 到主目錄的話，量到的是「主目錄那條分支落後多少」——跟要推的東西無關，
#   主目錄一落後，任何工作區的推送都會被誤擋。所以照這個順序找「這條 push 實際在哪裡跑」：
#     1) 指令自己講了：`git -C <路徑> push`，或前面先 `cd <路徑>`
#     2) 這條指令的執行目錄（hook 收到的 cwd）
#     3) 主目錄（最後的退路）
#   找到的地方不是 git 工作樹（路徑裡有變數或 ~、打錯）就往下一個退。
#   第 1 項是模板內補的，源專案只看執行目錄：人在主目錄下 `cd 工作區 && git push`，執行目錄還是主目錄，
#   主目錄落後就誤擋；`git -C 工作區 push` 則是整條認不出來、不檢查。
#   `cd` 只算還管得到 push 的：包在括號裡、括號已經收尾的不算（`(cd 別處 && make check); git push`）。
#
# 邊界（誠實聲明）：
#   ・只擋「落後遠端」的 push；不自動 rebase（避免在 hook 內卡在 rebase 中途），解衝突交給 agent／使用者明確執行。
#   ・只比「那一棵目前的分支」對它的上游；`git push origin HEAD:別的分支` 這種另外指定目的地的推法不會多比。
#   ・沒有上游（全新分支第一次推）、fetch 失敗（連不到遠端）一律放行，不因網路波動擋工作。
#   ・只看指令字串，不真的解析：
#       - 一條指令有好幾個 push，只看第一個。
#       - commit 訊息或 echo 的字串裡剛好有一段前後都是空白的 git push，也會被當成推送
#         （那一棵落後時會被擋；照訊息整合完再做，或把那幾個字換個寫法）。
#       - `--git-dir`／`--work-tree` 指的地方不看，照上面的順序量。
#       - 引號裡的括號、`case` 分支的右括號也會被當成括號，可能少算一個 `cd`。
#   ・沒有逃生口：被擋到時訊息會講量的是哪一棵，量錯了就把 `cd` 跟 push 拆成兩條指令。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

read -r -d '' PY <<'PYEOF' || true
import json, os, re, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
cmd = (d.get("tool_input") or {}).get("command") or ""
cwd = d.get("cwd") or ""
if not isinstance(cmd, str) or not isinstance(cwd, str):
    sys.exit(0)
VAL = r'''(?:"[^"]*"|'[^']*'|[^\s;&|()]+)'''
# git 與 push 中間可以夾全域選項：git -C <路徑> push、git --no-pager push
OPT = (r'(?:\s+(?:-C|-c|--git-dir|--work-tree|--namespace)\s+' + VAL
       + r'|\s+--(?:git-dir|work-tree|namespace)=' + VAL
       + r'|\s+(?:--no-pager|--paginate|--bare|--no-replace-objects|--literal-pathspecs|--no-optional-locks))*')
# 前後都要是詞的邊界：`git pushall`、`mygit push`、`echo "git push"` 不算
m = re.search(r'(?:^|[;&|(\s])git(' + OPT + r')\s+push(?=[\s;&|)]|$)', cmd)
if not m:
    sys.exit(0)

def unquote(s):
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'" else s

# 指令自己講的地方：push 前面的 cd 一個一個接下去，最後才是 git -C。
# 括號（子 shell）收尾時，裡面的 cd 就不算了——它管不到括號外面的 push。
steps, opened = [], []
for t in re.finditer(r'(\()|(\))|(?:^|(?<=[;&|(\s]))cd\s+(' + VAL + r')', cmd[:m.start(1)]):
    if t.group(1):
        opened.append(len(steps))
    elif t.group(2):
        if opened:
            del steps[opened.pop():]
    else:
        steps.append(t.group(3))
steps += re.findall(r'\s-C\s+(' + VAL + r')', m.group(1))
where = None
for p in steps:
    p = unquote(p)
    where = p if os.path.isabs(p) else os.path.join(where or cwd, p)
print("PUSH")
print((where or "").replace("\n", " "))
print(cwd.replace("\n", " "))
PYEOF

# 先把 stdin 讀完再做任何判斷：還沒讀就結束，送資料進來的那一端會收到 broken pipe
PAYLOAD=$(cat)
OUT=$(printf '%s' "$PAYLOAD" | python3 -c "$PY" 2>/dev/null || true)

# 不是 git push（或讀不懂的輸入）→ 放行
case "$OUT" in PUSH*) ;; *) exit 0 ;; esac
WANT=$(printf '%s\n' "$OUT" | sed -n '2p')   # 指令自己講的地方；沒講就是空的
CWD=$(printf '%s\n' "$OUT" | sed -n '3p')    # 這條指令的執行目錄

in_tree() { [ -n "$1" ] && [ -d "$1" ] && git -C "$1" rev-parse --is-inside-work-tree >/dev/null 2>&1; }
if in_tree "$WANT"; then
  cd "$WANT" || exit 0
elif in_tree "$CWD"; then
  cd "$CWD" || exit 0
else
  cd "$ROOT" || exit 0
fi

# 這一棵目前分支的上游；沒有上游（全新分支第一次推）→ 沒有東西可比，放行
UPSTREAM=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null) || exit 0
REMOTE=${UPSTREAM%%/*}
BRANCH=${UPSTREAM#*/}

# 先抓最新遠端狀態；抓不到就放行（不因網路波動擋工作）。
# 這裡沒有另外設逾時：.claude/settings.json 給這支 hook 的 timeout 就是上限。
git fetch "$REMOTE" "$BRANCH" >/dev/null 2>&1 || exit 0

BEHIND=$(git rev-list --count "HEAD..$UPSTREAM" 2>/dev/null || echo 0)
[ "${BEHIND:-0}" -eq 0 ] && exit 0

cat >&2 <<EOF
[git-sync-gate] 本地落後遠端：${UPSTREAM} 有 ${BEHIND} 個你還沒有的 commit
（量的是 ${PWD} 目前的分支）。直接 push 會衝突或無法推，請先整合再推：

  git pull --rebase ${REMOTE} ${BRANCH}
  # 若有衝突：解完 → git add <檔> → git rebase --continue → 重跑檢查 → 再 push

（此閘門只擋下、不自動 rebase；解衝突請當場處理。規則見 AGENTS.md「分支與出貨流程」。）
EOF
exit 2
