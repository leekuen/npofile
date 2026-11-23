#!/usr/bin/env bash
# hooks-wiring-lint.sh 的自動化測試（模板內補的）。守門工具自己也要有測試：
# 那支檢查平常都是綠的，要證明它**真的會紅**，只能故意把東西接壞給它看。
#
# 做法：把真的 settings、真的 hook 腳本複製進沙盒（所以第一條也順便確認現在的接法是好的），
# 再一次弄壞一個地方——沒掛、沒有執行權限、檔案不見、掛錯工具、路徑沒錨定……每一種都要被點名。
set -uo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
# 從 git hook 裡被叫起來時，環境會帶著 GIT_DIR／GIT_WORK_TREE／GIT_INDEX_FILE，
# 沙盒裡的 git（下面會在沙盒 init、改檔案模式）會全部打到真的 repo。先清掉。
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

fail=0
err() { echo "[hooks-wiring-lint-test] ✗ $1" >&2; fail=1; }
ok() { echo "[hooks-wiring-lint-test] ✓ $1"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
R="$TMP/repo"

build() {  # 重建一個照現況接好的沙盒（-p：執行權限要跟著複製過來）
  rm -rf "$R"
  mkdir -p "$R/scripts" "$R/.claude"
  cp -p "$SRC/scripts/hooks-wiring-lint.sh" "$SRC"/scripts/*-hook.sh "$R/scripts/"
  cp -p "$SRC/.claude/settings.json" "$R/.claude/"
  [ -d "$SRC/.githooks" ] && cp -Rp "$SRC/.githooks" "$R/"
  return 0
}

edit_settings() {  # edit_settings <python 片段：改變數 d（整份 settings）>
  python3 -c '
import json, sys
path, code = sys.argv[1], sys.argv[2]
d = json.load(open(path, encoding="utf-8"))
exec(code)
json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
' "$R/.claude/settings.json" "$1"
}

check() {  # check <期望 exit> <說明> [訊息裡要有的字]
  local out code
  out="$(bash "$R/scripts/hooks-wiring-lint.sh" 2>&1)"
  code=$?
  if [ "$code" != "$1" ]; then
    err "$2（期望 exit $1，實際 ${code}）：${out}"
    return
  fi
  if [ -n "${3:-}" ]; then
    case "$out" in *"$3"*) ;; *) err "$2（訊息裡沒有「$3」）：${out}"; return ;; esac
  fi
  ok "$2"
}

# ── 現況 ───────────────────────────────────────────────────
build
check 0 "照現況複製進沙盒 → 通過" "OK"

# ── 沒掛 ───────────────────────────────────────────────────
build
edit_settings 'for g in d["hooks"]["PreToolUse"]:
    g["hooks"] = [h for h in g["hooks"] if "git-scope-gate-hook.sh" not in h["command"]]'
check 1 "腳本在、settings 沒掛 → 點名沒掛的那一支" "scripts/git-scope-gate-hook.sh 沒有掛在"

build
printf '#!/usr/bin/env bash\nexit 0\n' > "$R/scripts/brand-new-hook.sh"
chmod +x "$R/scripts/brand-new-hook.sh"
check 1 "多了一支沒人掛的 hook 腳本 → 點名" "scripts/brand-new-hook.sh 沒有掛在"
edit_settings 'd["hooks"]["PreToolUse"][0]["hooks"].append(
    {"type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/scripts/brand-new-hook.sh"})'
check 1 "新 hook 掛了、但沒登記該掛哪 → 點名" "scripts/brand-new-hook.sh 沒登記"

# ── 掛了但叫不動 ───────────────────────────────────────────
build
chmod -x "$R/scripts/ticket-gate-hook.sh"
check 1 "hook 沒有執行權限 → 點名" "scripts/ticket-gate-hook.sh 沒有執行權限"

build
rm -f "$R/scripts/ticket-gate-hook.sh"
check 1 "settings 掛了、檔案不存在 → 點名" "掛了 scripts/ticket-gate-hook.sh"

build
printf '#!/usr/bin/env bash\nif then\n' > "$R/scripts/ticket-gate-hook.sh"
check 1 "hook 語法錯誤 → 點名" "scripts/ticket-gate-hook.sh 語法錯誤"

build
edit_settings 'for g in d["hooks"]["PreToolUse"]:
    for h in g["hooks"]:
        if "git-sync-gate-hook.sh" in h["command"]:
            h["command"] = "scripts/git-sync-gate-hook.sh"'
check 1 "指令用相對路徑（沒有 \${CLAUDE_PROJECT_DIR}）→ 點名" "呼叫 scripts/git-sync-gate-hook.sh 沒用"

# ── 掛錯地方 ───────────────────────────────────────────────
build
edit_settings 'moved = None
for g in d["hooks"]["PreToolUse"]:
    keep = []
    for h in g["hooks"]:
        if "check-pipe-gate-hook.sh" in h["command"]:
            moved = h
        else:
            keep.append(h)
    g["hooks"] = keep
[g for g in d["hooks"]["PreToolUse"] if "Edit" in (g.get("matcher") or "")][0]["hooks"].append(moved)'
check 1 "該掛 Bash 的掛到 Edit → 點名" "scripts/check-pipe-gate-hook.sh 要掛在 PreToolUse"

build
edit_settings 'moved = None
for g in d["hooks"]["PreToolUse"]:
    keep = []
    for h in g["hooks"]:
        if "git-scope-gate-hook.sh" in h["command"]:
            moved = h
        else:
            keep.append(h)
    g["hooks"] = keep
d["hooks"]["PostToolUse"] = [{"matcher": "Bash", "hooks": [moved]}]'
check 1 "掛錯事件（該在執行前擋的掛到執行後）→ 點名" "scripts/git-scope-gate-hook.sh 要掛在 PreToolUse"

build
edit_settings 'for g in d["hooks"]["PreToolUse"]:
    if "Write" in (g.get("matcher") or ""):
        g["matcher"] = "Edit"'
check 1 "matcher 少了 Write（新建檔案不會被擋）→ 點名" "scripts/ticket-gate-hook.sh 要掛在 PreToolUse"

build
edit_settings 'for g in d["hooks"]["SessionStart"]:
    g["matcher"] = "startup"'
check 1 "開場 hook 只掛新開（恢復、壓縮後不會跑）→ 點名" "scripts/session-start-hook.sh 要掛在 SessionStart"

build
edit_settings 'for g in d["hooks"]["PreToolUse"]:
    if (g.get("matcher") or "") == "Bash":
        g["matcher"] = "Bash|Read"'
check 0 "matcher 多涵蓋別的工具 → 通過"

build
edit_settings 'd["hooks"].setdefault("PostToolUse", []).append(
    {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo done"}]})'
check 0 "專案自己加的 hook 不是呼叫 scripts/ 底下的腳本 → 不歸這支管、通過"

# ── settings 本身 ──────────────────────────────────────────
build
printf '{ 這不是 JSON' > "$R/.claude/settings.json"
check 1 "settings 不是合法 JSON → 講出讀不懂" "讀不懂"

build
rm -f "$R/.claude/settings.json"
check 1 "沒有 settings → 講出找不到" "找不到"

# ── 版控裡記的模式（這台機器上可執行，不代表別人 clone 下來也是）──
build
git -C "$R" init -q > /dev/null 2>&1
git -C "$R" add scripts/ticket-gate-hook.sh > /dev/null 2>&1
check 0 "版控裡記的是可執行 → 通過"
git -C "$R" update-index --chmod=-x scripts/ticket-gate-hook.sh > /dev/null 2>&1
check 1 "這台機器上可執行、版控裡記的卻不是 → 點名" "scripts/ticket-gate-hook.sh 在版控裡記的不是可執行"

# ── 版控裡的 git hooks ─────────────────────────────────────
build
mkdir -p "$R/.githooks"
printf '#!/usr/bin/env bash\nexit 0\n' > "$R/.githooks/sample-hook"
check 1 "git hook 沒有執行權限 → 點名" ".githooks/sample-hook 沒有執行權限"
chmod +x "$R/.githooks/sample-hook"
check 0 "git hook 補上執行權限 → 通過"
printf '#!/usr/bin/env bash\nif then\n' > "$R/.githooks/sample-hook"
check 1 "git hook 語法錯誤 → 點名" ".githooks/sample-hook 語法錯誤"

[ "$fail" = 0 ] && echo "[hooks-wiring-lint-test] 全部通過" || exit 1
