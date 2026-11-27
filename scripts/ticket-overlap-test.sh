#!/usr/bin/env bash
# 開票相近提醒（similar_tickets.py）與資料庫更新撞號檢查（migration-number-lint.sh）的測試（框架 v5.2.0）。
# 植入錯誤時要真的會紅：撞號那條一定要擋下來。
set -u
here="$(cd "$(dirname "$0")" && pwd)"
fail=0
ok() { echo "[ticket-overlap-test] ✓ $1"; }
bad() { echo "[ticket-overlap-test] ✗ $1" >&2; fail=1; }

names='tickets/LK-19-政府補助：衛福部對民間團體補（捐）助.md
tickets/LK-05-更多爬蟲來源（集資平台、司法院裁判書、組織官網）.md
LK-15-挖貝公益集資專案.md
LK-22-資料說明頁：來源、更新頻率、揭露指數與分類怎麼算.md'

out=$(printf '%s\n' "$names" | python3 "$here/similar_tickets.py" "政府補助：加上勞動部就業安定基金" "LK-24")
case "$out" in *LK-19*) ok "標題相近的會列出來（政府補助）" ;; *) bad "政府補助應該列出 LK-19，實際：$out" ;; esac

out=$(printf '%s\n' "$names" | python3 "$here/similar_tickets.py" "集團歸戶：用法人董事把企業歸成集團" "LK-23")
[ -z "$out" ] && ok "不相關的不列" || bad "集團歸戶不該有相近的票，實際：$out"

out=$(printf '%s\n' "$names" | python3 "$here/similar_tickets.py" "政府補助：衛福部對民間團體補（捐）助" "LK-19")
[ -z "$out" ] && ok "不列自己" || bad "新票自己不該被列出，實際：$out"

out=$(printf '%s\n' "$names" | python3 "$here/similar_tickets.py" "挖貝集資專案改版" "LK-30")
case "$out" in *LK-15*) ok "集資專案列出 LK-15" ;; *) bad "應列出 LK-15，實際：$out" ;; esac

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/scripts" "$tmp/server/orgs/migrations" "$tmp/server/crawling/migrations"
cp "$here/migration-number-lint.sh" "$tmp/scripts/"
printf 'MIGRATION_GLOBS=("server/*/migrations")\n' > "$tmp/scripts/framework-config.sh"
touch "$tmp/server/orgs/migrations/0006_a.py" "$tmp/server/orgs/migrations/0007_b.py" "$tmp/server/crawling/migrations/0007_c.py"
bash "$tmp/scripts/migration-number-lint.sh" "$tmp" 2>/dev/null && ok "不同資料夾同編號不算撞號" || bad "不同資料夾的 0007 不該擋"
touch "$tmp/server/orgs/migrations/0007_d.py"
bash "$tmp/scripts/migration-number-lint.sh" "$tmp" 2>/dev/null
[ $? -eq 1 ] && ok "同一資料夾兩個 0007 擋下" || bad "同一資料夾兩個 0007 應該擋下（結束碼 1）"
printf 'MIGRATION_GLOBS=()\n' > "$tmp/scripts/framework-config.sh"
bash "$tmp/scripts/migration-number-lint.sh" "$tmp" 2>/dev/null && ok "沒設定就不檢查" || bad "MIGRATION_GLOBS 空陣列應該直接通過"

exit $fail
