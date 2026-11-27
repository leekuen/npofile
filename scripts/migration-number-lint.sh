#!/usr/bin/env bash
# 資料庫更新（migration）撞號檢查（框架 v5.2.0）。
#
# 多條 session 平行開發時，兩條分支各自新增資料表，常拿到同一個編號（例：兩個 0007_*.py）。
# 各自分支上都沒事，合進整合分支後才變成「同一層有兩個」——Django 這類工具會拒絕執行資料庫更新，
# 部署當下才炸。源專案（NPOFile）2026-11-27 一天撞了兩次（0006、0007），都是合流前人工發現。
#
# 檢查：`scripts/framework-config.sh` 的 MIGRATION_GLOBS 列出的每個資料夾裡，
# 檔名開頭的編號（數字＋底線，例 0007_）不能重複。空陣列＝專案沒有這種東西，直接通過。
#
# 用法：bash scripts/migration-number-lint.sh [repo 根目錄]
# 結束碼：0 沒撞號（或沒設定）；1 撞號（印出哪個資料夾、哪幾個檔、怎麼改）；2 用法錯誤。
set -u

root="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
# 沒有設定檔＝沒有設定（不當成跑不起來）
# shellcheck source=/dev/null
[ -f "$root/scripts/framework-config.sh" ] && . "$root/scripts/framework-config.sh"

if [ -z "${MIGRATION_GLOBS+x}" ] || [ "${#MIGRATION_GLOBS[@]}" -eq 0 ]; then
  exit 0
fi

bad=0
for pattern in "${MIGRATION_GLOBS[@]}"; do
  for dir in $root/$pattern; do
    [ -d "$dir" ] || continue
    dups=$(cd "$dir" && ls 2>/dev/null | grep -oE '^[0-9]+_' | sort | uniq -d)
    [ -z "$dups" ] && continue
    bad=1
    rel=${dir#"$root"/}
    for n in $dups; do
      echo "[migration-number-lint] ⛔ ${rel} 有兩個以上編號 ${n%_} 的資料庫更新：" >&2
      (cd "$dir" && ls "${n}"* | sed 's/^/    /') >&2
    done
  done
done

if [ "$bad" -eq 1 ]; then
  echo "[migration-number-lint] 怎麼改：還沒合進整合分支的那一個改成下一個編號，" >&2
  echo "    並把它的相依改成接在另一個後面（Django：檔名改號、dependencies 改成另一個檔名），再跑 makemigrations --check。" >&2
  exit 1
fi
exit 0
