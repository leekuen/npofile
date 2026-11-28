#!/bin/sh
# 自動更新（compose 的 updater 服務）：每隔一段時間看 GitHub 上的分支有沒有新版，
# 有就 git 快轉、重建並重啟其他服務。沒有新版什麼都不做。
#   AUTO_UPDATE_BRANCH   跟哪條分支（預設 prod）
#   AUTO_UPDATE_INTERVAL 幾秒看一次（預設 300）
#   AUTO_UPDATE_MAX_WAIT 有排程工作在跑時最多延後幾秒（預設 43200＝12 小時；超過就照樣更新）
#   AUTO_UPDATE_BUSY_RECHECK 看到工作在跑後隔幾秒再看一次，兩次都在跑才算（預設 10；
#                            排除每分鐘跑一下就結束的 run_crawl_requests）
#   auto-update.sh --once  只檢查一次就結束（測試用）
#
# 重建會重啟 scheduler，正在跑的夜間爬蟲會被砍掉、後面的來源整晚沒跑到（LK-44），
# 所以 scheduler 或 backend 裡有排程工作或爬蟲在跑時先不更新，下一輪再看。
set -u

BRANCH="${AUTO_UPDATE_BRANCH:-prod}"
INTERVAL="${AUTO_UPDATE_INTERVAL:-300}"
MAX_WAIT="${AUTO_UPDATE_MAX_WAIT:-43200}"
RECHECK="${AUTO_UPDATE_BUSY_RECHECK:-10}"
# 記「從什麼時候開始因為有工作在跑而延後」；--once 連跑多次也接得上
STATE="${AUTO_UPDATE_STATE:-/tmp/npofile-auto-update-busy-since}"
# 算「在跑」的程式：排程外殼 run-job.sh（每晚爬蟲、備份、重算）、手動或後台排入的爬取
BUSY_PATTERN='run-job\.sh|manage\.py (crawl|run_crawl_requests)'

log() { echo "[auto-update $(date '+%F %T')] $*"; }

git config --global --add safe.directory '*'

# 印出 scheduler、backend 裡符合 BUSY_PATTERN 的程式（沒有就不印）
busy_jobs() {
  docker compose top scheduler backend 2>/dev/null | grep -E "$BUSY_PATTERN" || true
}

# 隔 RECHECK 秒看兩次都有工作在跑才算忙；忙就印出工作名稱並回 0
busy_now() {
  [ -n "$(busy_jobs)" ] || return 1
  sleep "$RECHECK"
  jobs=$(busy_jobs)
  [ -n "$jobs" ] || return 1
  echo "$jobs" | grep -oE 'run-job\.sh [A-Za-z0-9_-]+|manage\.py (crawl|run_crawl_requests)( [A-Za-z0-9_-]+)*' | sort -u | tr '\n' ' '
  return 0
}

update_once() {
  if ! git fetch -q origin "$BRANCH"; then
    log "抓不到 origin/${BRANCH}（網路？），下次再試"
    return 0
  fi
  local_sha=$(git rev-parse HEAD)
  remote_sha=$(git rev-parse "origin/$BRANCH")
  if [ "$local_sha" = "$remote_sha" ]; then
    rm -f "$STATE"
    return 0
  fi

  if ! git merge-base --is-ancestor HEAD "origin/$BRANCH"; then
    log "本機的程式跟 origin/$BRANCH 分岔了（這台上有人改過程式？），不自動更新。處理方式見 docker/README.md〈自動更新〉"
    return 1
  fi
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    log "這台上有改過、還沒提交的檔案，不自動更新：$(git status --porcelain --untracked-files=no | tr '\n' ' ')"
    return 1
  fi

  if names=$(busy_now); then
    now=$(date +%s)
    since=$(cat "$STATE" 2>/dev/null || true)
    case "$since" in
      ''|*[!0-9]*) since=$now; echo "$now" >"$STATE" ;;
    esac
    waited=$((now - since))
    if [ "$waited" -lt "$MAX_WAIT" ]; then
      log "有新版，但排程工作還在跑，先不更新（已等 $((waited / 60)) 分鐘，最多等 $((MAX_WAIT / 60)) 分鐘）：$names"
      return 0
    fi
    log "已經等了 $((waited / 60)) 分鐘工作還沒跑完，照樣更新（正在跑的會被中斷，下次排程再跑）：$names"
  fi
  rm -f "$STATE"

  log "有新版：$(git log -1 --format='%h %s' "origin/$BRANCH")"
  git merge -q --ff-only "origin/$BRANCH" || { log "快轉失敗"; return 1; }

  # 自己（updater）不在這次重啟名單裡，免得重建到一半把自己關掉；config --services 只列啟用中的 profile
  services=$(docker compose config --services | grep -vx updater | tr '\n' ' ')
  log "重建並重啟：$services"
  if docker compose up -d --build --remove-orphans $services; then
    # 保險：nginx.conf 已改成每次請求重新解析，但舊版設定或手動改壞時，重啟 nginx 也能接上新容器的 IP
    docker compose restart nginx >/dev/null 2>&1 || log "重啟 nginx 失敗"
    docker image prune -f >/dev/null 2>&1 || true
    log "更新完成，現在版本：$(git log -1 --format='%h %s')"
  else
    log "重建失敗，網站還是舊版在跑；看上面的錯誤訊息"
    return 1
  fi
}

if [ "${1:-}" = "--once" ]; then
  update_once
  exit $?
fi

log "開始：每 ${INTERVAL} 秒檢查 origin/${BRANCH}（目前 $(git log -1 --format='%h %s')）"
while true; do
  update_once || true
  sleep "$INTERVAL"
done
