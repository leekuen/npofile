#!/usr/bin/env bash
# 資料庫每日備份：pg_dump 成一個檔 → 檢查讀得回來 → 刪掉太舊的 →（有設的話）複製一份到機器外。
# 由 crontab 透過 run-job.sh 每天跑；手動跑：sudo -iu npofile ~/app/deploy/backup-db.sh
#
# 設定都在 server/.env（只有 DATABASE_URL 是必填）：
#   BACKUP_DIR=/home/npofile/backups      本機備份放哪
#   BACKUP_KEEP_DAYS=14                   本機留幾天
#   BACKUP_RCLONE_REMOTE=spaces:npofile-backups/db   機器外的位置（rclone 的 remote:路徑）；不設就只留本機
#   BACKUP_REMOTE_KEEP_DAYS=60            機器外留幾天
set -euo pipefail
umask 077

APP_ENV="${APP_ENV:-/home/npofile/app/server/.env}"

env_get() {
  [ -f "$APP_ENV" ] || return 0
  sed -n "s/^[[:space:]]*$1[[:space:]]*=//p" "$APP_ENV" | tail -n 1 | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e "s/^[\"']//" -e "s/[\"']\$//"
}
setting() { local v="${!1:-}"; [ -n "$v" ] || v=$(env_get "$1"); echo "${v:-$2}"; }

db_url=$(setting DATABASE_URL "")
dir=$(setting BACKUP_DIR "$HOME/backups")
keep=$(setting BACKUP_KEEP_DAYS 14)
remote=$(setting BACKUP_RCLONE_REMOTE "")
remote_keep=$(setting BACKUP_REMOTE_KEEP_DAYS 60)

case "$db_url" in
  postgres://* | postgresql://*) ;;
  *) echo "DATABASE_URL 沒設或不是 PostgreSQL（$APP_ENV），沒有東西可備份" >&2; exit 1 ;;
esac

mkdir -p "$dir"
file="$dir/npofile-$(date +%F).dump"
partial="$file.partial"
trap 'rm -f "$partial"' EXIT

echo "==> 備份到 $file"
pg_dump --format=custom --no-owner --no-privileges --dbname="$db_url" --file="$partial"

# 檢查：檔案讀得回來，而且真的有組織資料表的內容（避免連到空的資料庫也算成功）
listing=$(pg_restore --list "$partial")
if ! grep -q "TABLE DATA public orgs_organization" <<<"$listing"; then
  echo "備份檔裡找不到 orgs_organization 的資料，可能連錯資料庫，這份不算數" >&2
  exit 1
fi
mv -f "$partial" "$file"
echo "    大小 $(du -h "$file" | cut -f1)，含 $(grep -c 'TABLE DATA' <<<"$listing") 張表的資料"

echo "==> 刪除本機超過 $keep 天的備份"
find "$dir" -maxdepth 1 -name 'npofile-*.dump' -mtime +"$((keep - 1))" -print -delete

if [ -n "$remote" ]; then
  echo "==> 複製到機器外：$remote"
  rclone copy "$file" "$remote"
  rclone delete --min-age "${remote_keep}d" --include 'npofile-*.dump' "$remote"
else
  echo "    沒設 BACKUP_RCLONE_REMOTE：備份只在這台機器上，機器整台壞掉就一起沒了"
fi
echo "==> 完成"
