#!/usr/bin/env bash
# 「閘門有沒有真的接上」的檢查（模板內補的）。
#
# hook 寫得再對，沒接上就是零。而且下面這幾種接錯法都**不會報錯**，只會安靜地什麼都不擋：
#   ・`.claude/settings.json` 沒掛這支 → harness 根本不會叫它；
#   ・掛了，但檔案不存在或沒有執行權限（用編輯工具新建的檔案預設沒有）→ 每次呼叫都失敗，
#     而 hook 的結束碼不是 2 就不算擋下，工具照常執行；
#   ・掛錯事件或工具（該掛 Bash 的掛到 Edit）→ 永遠等不到它要看的東西；
#   ・指令沒用 "$CLAUDE_PROJECT_DIR" 開頭 → 執行目錄一換（進了子資料夾、別的工作區）就找不到。
# 各支閘門自己的測試是直接用 bash 跑腳本本體，測不到「有沒有接上」，所以另外查。
# 源專案是在個別閘門的測試裡各自斷言一次「必須掛在版控的 settings」；這裡收成一支，
# 並多查執行權限、語法、掛的位置，以及「有沒有哪支 hook 腳本沒人掛」。
#
# 用法：bash scripts/hooks-wiring-lint.sh（由 make ticket-lint 帶著跑）
# 結束碼：0 全部接好｜1 有沒接好的
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
SETTINGS=".claude/settings.json"

# 每支 hook 該掛在哪：<腳本>  <事件>  <matcher 至少要涵蓋的工具或時機，逗號分隔>
# 新增 hook 腳本時在這裡登記一行；沒登記的會被當成「不知道該掛哪」報出來。
# 專案拿掉的 hook（檔案與 settings 都刪了）不用管這張表，檔案不在的那一行不查。
EXPECTED='
session-start-hook.sh     SessionStart  startup,resume,clear,compact
ticket-gate-hook.sh       PreToolUse    Edit,Write
ui-design-gate-hook.sh    PreToolUse    Edit,Write
mockup-text-gate-hook.sh  PreToolUse    Edit,Write
ui-design-mark-hook.sh    PreToolUse    Skill
git-sync-gate-hook.sh     PreToolUse    Bash
git-scope-gate-hook.sh    PreToolUse    Bash
check-pipe-gate-hook.sh   PreToolUse    Bash
'

fail=0
err() { echo "[hooks-wiring-lint] ✗ $1" >&2; fail=1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
WIRED="$TMP/wired.tsv"

# settings 裡每一筆「呼叫 scripts/ 底下腳本」的 hook，一行一筆：事件、matcher、腳本、路徑有沒有錨定。
# 空欄位一律印成 -：用 tab 當分隔讀回來時，連續的 tab 會被當成一個，空欄位會讓後面的欄位全部錯位。
read -r -d '' PY <<'PYEOF' || true
import json, re, sys
rows = []
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    for event, groups in (data.get("hooks") or {}).items():
        for group in groups or []:
            matcher = group.get("matcher") or "-"
            for hook in group.get("hooks") or []:
                cmd = hook.get("command") or ""
                found = re.search(r"scripts/([A-Za-z0-9_.-]+)", cmd)
                if not found:
                    continue  # 不是呼叫 scripts/ 底下的腳本：不歸這支管
                anchored = re.search(r"\$\{?CLAUDE_PROJECT_DIR\}?\"?/scripts/", cmd)
                rows.append("\t".join([event, matcher, found.group(1), "abs" if anchored else "rel"]))
except Exception as exc:
    sys.stderr.write(str(exc))
    sys.exit(1)
print("\n".join(rows))
PYEOF

if [ ! -f "$SETTINGS" ]; then
  err "找不到 ${SETTINGS}——hook 都掛在這個檔，沒有它就一支都不會被呼叫"
  exit 1
fi
if ! python3 -c "$PY" "$SETTINGS" > "$WIRED" 2> "$TMP/py.err"; then
  err "${SETTINGS} 讀不懂（$(cat "$TMP/py.err")）——先修好，裡面掛的 hook 才接得上"
  exit 1
fi

check_exec() {  # check_exec <相對路徑> <沒有執行權限的後果>
  local path="$1" mode
  [ -x "$path" ] || err "${path} 沒有執行權限（chmod +x ${path}）——$2"
  # 版控裡記的模式才是別人 clone 下來會拿到的：這台機器上可執行、版控裡卻不是，問題只會出現在別人那裡
  mode=$(git ls-files -s -- "$path" 2>/dev/null | awk '{ print $1; exit }')
  if [ -n "$mode" ] && [ "$mode" != "100755" ]; then
    err "${path} 在版控裡記的不是可執行（${mode}）——別人 clone 下來沒有執行權限：git update-index --chmod=+x ${path}"
  fi
}

covers() {  # covers <settings 的 matcher> <至少要涵蓋的，逗號分隔> -> 0 表示都涵蓋
  local matcher="$1" need="$2" item
  case "$matcher" in -|'*'|'.*') return 0 ;; esac  # 沒寫 matcher＝全部都會叫
  local IFS=','
  for item in $need; do
    case "|${matcher}|" in *"|${item}|"*) ;; *) return 1 ;; esac
  done
  return 0
}

# ── 1) settings 掛的每一筆：檔案在、能執行、語法過、路徑有錨定 ──
count=0
while IFS=$'\t' read -r w_event w_matcher w_script w_style; do
  [ -n "${w_script:-}" ] || continue
  count=$((count + 1))
  path="scripts/${w_script}"
  if [ ! -f "$path" ]; then
    err "${SETTINGS} 掛了 ${path}（${w_event}），但檔案不存在——呼叫失敗不算擋下，等於沒有這道閘門"
    continue
  fi
  check_exec "$path" "呼叫會失敗，而失敗不算擋下，等於沒有這道閘門"
  case "$path" in
    *.sh) bash -n "$path" 2>/dev/null || err "${path} 語法錯誤（bash -n ${path} 看是哪一行）——每次被呼叫都會出錯" ;;
  esac
  [ "$w_style" = "abs" ] || err "${SETTINGS} 呼叫 ${path} 沒用 \"\$CLAUDE_PROJECT_DIR\" 開頭——執行目錄一換就找不到這支腳本"
done < "$WIRED"

# ── 2) scripts/ 底下每一支 hook 腳本：有人掛、也登記過該掛哪 ──
for f in scripts/*-hook.sh; do
  [ -f "$f" ] || continue
  name="${f##*/}"
  awk -F'\t' -v s="$name" '$3 == s { found = 1 } END { exit !found }' "$WIRED" \
    || err "${f} 沒有掛在 ${SETTINGS}——harness 不會叫它（不用了就把檔案刪掉）"
  printf '%s\n' "$EXPECTED" | awk -v s="$name" '$1 == s { found = 1 } END { exit !found }' \
    || err "${f} 沒登記在 scripts/hooks-wiring-lint.sh 的對照表——補一行寫它該掛在哪個事件、哪些工具"
done

# ── 3) 掛的位置對不對（事件、matcher）──
while read -r e_script e_event e_need; do
  [ -n "${e_script:-}" ] || continue
  [ -f "scripts/${e_script}" ] || continue
  placed=0
  while IFS=$'\t' read -r w_event w_matcher w_script w_style; do
    [ "${w_script:-}" = "$e_script" ] && [ "$w_event" = "$e_event" ] && covers "$w_matcher" "$e_need" && placed=1
  done < "$WIRED"
  [ "$placed" = 1 ] || err "scripts/${e_script} 要掛在 ${e_event}、matcher 至少涵蓋 ${e_need}，${SETTINGS} 裡沒有這樣的掛法——掛錯地方的 hook 永遠等不到它要看的東西"
done <<EOF
$EXPECTED
EOF

# ── 4) 版控裡的 git hooks（make hooks 啟用的那一組）：沒有執行權限的，git 會直接跳過 ──
if [ -d .githooks ]; then
  for f in .githooks/*; do
    [ -f "$f" ] || continue
    check_exec "$f" "git 會直接跳過這支 hook"
    case "$(sed -n '1p' "$f")" in
      '#!'*sh*) bash -n "$f" 2>/dev/null || err "${f} 語法錯誤（bash -n ${f} 看是哪一行）" ;;
    esac
  done
fi

[ "$fail" = 0 ] || exit 1
echo "[hooks-wiring-lint] OK（${SETTINGS} 掛了 ${count} 筆 hook，都接得上）"
