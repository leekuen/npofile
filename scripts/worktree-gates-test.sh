#!/usr/bin/env bash
# 三個寫檔閘門（ticket-gate／ui-design-gate／mockup-text-gate）的自動化測試（源專案 v4.76.0）。
#
# 為什麼要有：閘門原本都用主目錄算相對路徑，工作區（.claude/worktrees/<名稱>/）裡的檔案
# 對不上任何規則就一律放行——而規定的開發方式正是在工作區裡做。這種洞不會報錯，
# 只會安靜地什麼都不擋，所以要有會紅的測試釘住。
#
# 全部在沙盒 repo 裡跑：把 hook 複製進 $TMP/repo/scripts/，hook 算出來的 ROOT 就是沙盒，
# 設定（framework-config.sh）、票、cache、override 檔都是沙盒自己的——
# 不讀這個專案真的設定、不碰真的工作樹，正在跑的別條 session 不會被這支測試影響。
set -uo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"

fail=0
err() { echo "[worktree-gates-test] ✗ $1" >&2; fail=1; }
ok() { echo "[worktree-gates-test] ✓ $1"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
R="$TMP/repo"
mkdir -p "$R/scripts" "$R/tickets" "$R/cache"
cp "$SRC/scripts/ticket-gate-hook.sh" "$SRC/scripts/ui-design-gate-hook.sh" \
  "$SRC/scripts/ui-design-mark-hook.sh" "$SRC/scripts/mockup-text-gate-hook.sh" "$R/scripts/"

config() {  # config <PRODUCT_DIRS 內容> <UI_PATH_GLOBS 內容>
  printf 'PRODUCT_DIRS=(%s)\nUI_PATH_GLOBS=(%s)\n' "$1" "$2" > "$R/scripts/framework-config.sh"
}
config '"server" "web/"' '"web/*.tsx" "web/*.jsx" "server/*admin*.py" "server/templates/*.html"'

ticket() {  # ticket <目錄> <票號> <狀態>
  mkdir -p "$1"
  printf -- '---\nid: %s\nstatus: %s        # 待開發 | 開發中 | 完成 | 作廢\n---\n' "$2" "$3" > "$1/$2-測試.md"
}
payload() {  # payload <file_path> [session_id] -> 寫進 $TMP/payload.json
  python3 -c 'import json,sys;print(json.dumps({"tool_input":{"file_path":sys.argv[1]},"session_id":sys.argv[2]}))' \
    "$1" "${2:-gate-test}" > "$TMP/payload.json"
}
run() {  # run <hook> <file_path> [session_id] -> echo exit code
  # 從檔案餵 stdin、不接管線：接管線的話這支測試開了 pipefail，拿到的會是前一段的結束碼而不是 hook 的
  payload "$2" "${3:-gate-test}"
  bash "$R/scripts/$1" < "$TMP/payload.json" >/dev/null 2>&1
  echo $?
}
expect() {  # expect <期望 exit> <hook> <file_path> <說明> [session_id]
  local code; code=$(run "$2" "$3" "${5:-gate-test}")
  [ "$code" = "$1" ] && ok "$4" || err "$4（期望 exit $1，實際 ${code}）"
}

WT="$R/.claude/worktrees"
mkdir -p "$WT/ZZ-1" "$WT/ZZ-2" "$WT/ZZ-3" "$WT/ZZ2-4" "$WT/elegant-test-1234"
ticket "$WT/ZZ-1/tickets" ZZ-1 開發中
ticket "$WT/ZZ-2/tickets" ZZ-2 完成

# ── 無票閘門 ────────────────────────────────────────────────
G=ticket-gate-hook.sh
# 主目錄沒有任何開著的票時，舊規則會擋——先確認沙盒的起點
expect 2 $G "$R/server/a.py" "主目錄：全站沒有開著的票 → 擋"
expect 2 $G "$R/web/src/a.ts" "主目錄：設定寫成「web/」（帶斜線）也認得 → 擋"
expect 0 $G "$R/docs/a.md" "主目錄：docs 不在閘門範圍 → 放行"
expect 0 $G "$R/webhooks/a.py" "主目錄：名字只是開頭相同的目錄（webhooks）不算產品目錄 → 放行"
expect 0 $G "$TMP/elsewhere/server/a.py" "repo 外的檔案 → 放行"
expect 0 $G "$WT/ZZ-1/server/a.py" "工作區 ZZ-1：票開發中 → 放行"
expect 2 $G "$WT/ZZ-2/server/a.py" "工作區 ZZ-2：票已完成 → 擋"
expect 2 $G "$WT/ZZ-3/web/a.tsx" "工作區 ZZ-3：找不到票 → 擋"
expect 2 $G "$WT/elegant-test-1234/server/a.py" "名稱不是票號的工作區、全站沒票 → 擋（舊規則）"
ticket "$R/tickets" ZZ2-4 待開發        # 票只在主目錄、還沒進工作區的分支
expect 0 $G "$WT/ZZ2-4/web/a.ts" "工作區 ZZ2-4：票只在主目錄、待開發 → 放行"
expect 0 $G "$WT/ZZ-2/docs/a.md" "工作區 ZZ-2：docs 不在閘門範圍 → 放行"
expect 0 $G "$WT/elegant-test-1234/server/a.py" "名稱不是票號的工作區、全站有票 → 放行（舊規則）"
mkdir -p "$WT/ZZ-2/cache"
touch "$WT/ZZ-2/cache/hotfix-override"
expect 0 $G "$WT/ZZ-2/server/a.py" "工作區裡的 hotfix-override → 放行"
rm -f "$WT/ZZ-2/cache/hotfix-override"
touch "$R/cache/hotfix-override"
expect 0 $G "$WT/ZZ-2/server/a.py" "主目錄的 hotfix-override → 放行"
rm -f "$R/cache/hotfix-override"
payload "$WT/ZZ-2/server/a.py"
msg="$(bash "$R/scripts/$G" 2>&1 >/dev/null < "$TMP/payload.json")"
case "$msg" in *ZZ-2*完成*) ok "擋下訊息講出票號與狀態" ;; *) err "擋下訊息缺票號或狀態：$msg" ;; esac

# ── 畫面閘門 ───────────────────────────────────────────────
U=ui-design-gate-hook.sh
expect 2 $U "$R/server/shop/admin.py" "主目錄畫面檔、沒套 ui-design → 擋"
expect 2 $U "$WT/ZZ-1/server/shop/admin.py" "工作區畫面檔、沒套 ui-design → 擋"
expect 2 $U "$WT/ZZ-1/web/app/x.tsx" "工作區深層的 tsx、沒套 ui-design → 擋"
expect 2 $U "$WT/ZZ-1/server/templates/shop/list.html" "工作區樣板 html、沒套 ui-design → 擋"
expect 0 $U "$WT/ZZ-1/server/shop/models.py" "工作區非畫面檔 → 放行"
expect 0 $U "$TMP/elsewhere/web/x.tsx" "repo 外的檔案 → 放行"
touch "$R/cache/.ui-design-ok.sid-ok"
expect 0 $U "$WT/ZZ-1/server/shop/admin.py" "工作區畫面檔、已套 ui-design → 放行" sid-ok
expect 0 $U "$R/server/shop/admin.py" "主目錄畫面檔、已套 ui-design → 放行" sid-ok
expect 2 $U "$R/server/shop/admin.py" "別條 session 套過不算數 → 擋" sid-other
touch "$R/cache/ui-design-override"
expect 0 $U "$WT/ZZ-1/server/shop/admin.py" "主目錄的 ui-design-override → 放行"
rm -f "$R/cache/ui-design-override"
mkdir -p "$WT/ZZ-1/cache"
touch "$WT/ZZ-1/cache/ui-design-override"
expect 0 $U "$WT/ZZ-1/server/shop/admin.py" "工作區裡的 ui-design-override → 放行"
expect 2 $U "$WT/ZZ-2/server/shop/admin.py" "別的工作區的 override 不算數 → 擋"
rm -f "$WT/ZZ-1/cache/ui-design-override"

# 啟動 skill 留下的標記，閘門要認得（兩支 hook 的 session key 算法必須一致）
mark() {  # mark <skill> <session_id>：模擬「透過 Skill 工具啟動某個 skill」
  python3 -c 'import json,sys;print(json.dumps({"tool_input":{"skill":sys.argv[1]},"session_id":sys.argv[2]}))' \
    "$1" "$2" > "$TMP/skill.json"
  bash "$R/scripts/ui-design-mark-hook.sh" < "$TMP/skill.json" >/dev/null 2>&1
}
mark ui-design sid-mark
expect 0 $U "$R/server/shop/admin.py" "透過 Skill 工具啟動 ui-design 之後 → 放行" sid-mark
mark ux-writing sid-other-skill
expect 2 $U "$R/server/shop/admin.py" "啟動的是別的 skill → 照擋" sid-other-skill

# ── 示意圖文字閘門 ────────────────────────────────────────────
M=mockup-text-gate-hook.sh
expect 2 $M "$R/cache/demos/a.html" "主目錄的示意圖、還沒看過分類表 → 擋"
expect 2 $M "$WT/ZZ-1/cache/demos/sub/a.html" "工作區的示意圖、還沒看過分類表 → 擋"
expect 0 $M "$R/cache/demos/a.png" "示意圖資料夾裡的非 html → 放行"
expect 0 $M "$R/docs/a.html" "別處的 html → 放行"
touch "$R/cache/.mockup-text-ok.sid-m"
expect 0 $M "$R/cache/demos/a.html" "主目錄的示意圖、看過了 → 放行" sid-m
expect 0 $M "$WT/ZZ-1/cache/demos/a.html" "工作區的示意圖、標記在主目錄 → 放行" sid-m
touch "$WT/ZZ-1/cache/.mockup-text-ok.sid-w"
expect 0 $M "$WT/ZZ-1/cache/demos/a.html" "工作區的示意圖、標記在工作區 → 放行" sid-w
expect 2 $M "$R/cache/demos/a.html" "別條 session 看過不算數 → 擋" sid-none

# ── 還沒設定的專案：兩個可設定的閘門都不擋（初始化前不能把人卡死）────────
config '' ''
expect 0 $G "$R/server/a.py" "PRODUCT_DIRS 是空的 → 無票閘門不擋"
expect 0 $U "$R/server/shop/admin.py" "UI_PATH_GLOBS 是空的 → 畫面閘門不擋" sid-empty
# 設定檔裡根本沒有這兩個變數（從舊版升級、還沒補）：要安靜放行，不是報錯——
# hook 以 1 結束時工具照樣會跑，但每次寫檔都會噴一行錯誤
printf 'PROJECT_NAME="舊設定檔"\n' > "$R/scripts/framework-config.sh"
expect 0 $G "$R/server/a.py" "設定檔沒有 PRODUCT_DIRS → 無票閘門安靜放行"
expect 0 $U "$R/server/shop/admin.py" "設定檔沒有 UI_PATH_GLOBS → 畫面閘門安靜放行" sid-empty
rm -f "$R/scripts/framework-config.sh"
expect 0 $G "$R/server/a.py" "連設定檔都沒有 → 無票閘門安靜放行"
expect 0 $U "$R/server/shop/admin.py" "連設定檔都沒有 → 畫面閘門安靜放行" sid-empty

[ "$fail" = 0 ] && echo "[worktree-gates-test] 全部通過" || exit 1
