#!/usr/bin/env bash
# 排程工作的外殼：跑指令、寫紀錄，並向 Healthchecks.io 回報（失敗或沒準時跑完就會寄信通知）。
#   run-job.sh <工作名稱> <指令…>
#   例：run-job.sh crawl bash -c 'cd ~/app/server && .venv/bin/python manage.py crawl all'
#
# 紀錄：$LOG_DIR/<工作名稱>.log（預設 /home/npofile/logs）
# 通知：server/.env 設 HEALTHCHECKS_PING_KEY 才會送；沒設只寫紀錄（並在紀錄裡提醒）。
#   每個工作在 Healthchecks 上是一個 check，名稱 npofile-<工作名稱>，第一次回報時自動建立。
# 結束碼＝指令的結束碼，cron 照樣看得到。
set -uo pipefail

if [ $# -lt 2 ]; then
  echo "用法：run-job.sh <工作名稱> <指令…>" >&2
  exit 2
fi
name=$1
shift

APP_ENV="${APP_ENV:-/home/npofile/app/server/.env}"
LOG_DIR="${LOG_DIR:-/home/npofile/logs}"
HC_BASE="${HEALTHCHECKS_BASE:-https://hc-ping.com}"

# 從 .env 讀一個值（不用 source：密碼裡的特殊字元會被 shell 解讀）
env_get() {
  [ -f "$APP_ENV" ] || return 0
  sed -n "s/^[[:space:]]*$1[[:space:]]*=//p" "$APP_ENV" | tail -n 1 | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e "s/^[\"']//" -e "s/[\"']\$//"
}

key="${HEALTHCHECKS_PING_KEY:-$(env_get HEALTHCHECKS_PING_KEY)}"
url=""
[ -n "$key" ] && url="$HC_BASE/$key/npofile-$name"

mkdir -p "$LOG_DIR"
log="$LOG_DIR/$name.log"

# 回報失敗不能讓工作本身失敗；只在紀錄裡留一行
ping() {
  [ -n "$url" ] || return 0
  curl -fsS -m 10 --retry 3 -o /dev/null "$@" || echo "!!! 通知送不出去：$1" >>"$log"
}

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

started=$(date +%s)
echo "=== $(date '+%F %T') 開始 $name" >>"$log"
ping "$url/start?create=1"

"$@" 2>&1 | tee "$tmp" >>"$log"
code=${PIPESTATUS[0]}

echo "=== $(date '+%F %T') 結束 ${name}：結束碼 ${code}，用了 $(($(date +%s) - started)) 秒" >>"$log"
if [ "$code" -ne 0 ] && [ -z "$url" ]; then
  echo "!!! 沒設 HEALTHCHECKS_PING_KEY，這次失敗不會通知任何人" >>"$log"
fi

# 0 = 成功，其他 = 失敗；附上輸出的最後 20KB，通知信裡就看得到錯誤
tail -c 20000 "$tmp" | ping --data-binary @- "$url/$code"
exit "$code"
