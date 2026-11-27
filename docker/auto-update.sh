#!/bin/sh
# 自動更新（compose 的 updater 服務）：每隔一段時間看 GitHub 上的分支有沒有新版，
# 有就 git 快轉、重建並重啟其他服務。沒有新版什麼都不做。
#   AUTO_UPDATE_BRANCH   跟哪條分支（預設 prod）
#   AUTO_UPDATE_INTERVAL 幾秒看一次（預設 300）
#   auto-update.sh --once  只檢查一次就結束（測試用）
set -u

BRANCH="${AUTO_UPDATE_BRANCH:-prod}"
INTERVAL="${AUTO_UPDATE_INTERVAL:-300}"

log() { echo "[auto-update $(date '+%F %T')] $*"; }

git config --global --add safe.directory '*'

update_once() {
  if ! git fetch -q origin "$BRANCH"; then
    log "抓不到 origin/${BRANCH}（網路？），下次再試"
    return 0
  fi
  local_sha=$(git rev-parse HEAD)
  remote_sha=$(git rev-parse "origin/$BRANCH")
  [ "$local_sha" = "$remote_sha" ] && return 0

  if ! git merge-base --is-ancestor HEAD "origin/$BRANCH"; then
    log "本機的程式跟 origin/$BRANCH 分岔了（這台上有人改過程式？），不自動更新。處理方式見 docker/README.md〈自動更新〉"
    return 1
  fi
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    log "這台上有改過、還沒提交的檔案，不自動更新：$(git status --porcelain --untracked-files=no | tr '\n' ' ')"
    return 1
  fi

  log "有新版：$(git log -1 --format='%h %s' "origin/$BRANCH")"
  git merge -q --ff-only "origin/$BRANCH" || { log "快轉失敗"; return 1; }

  # 自己（updater）不在這次重啟名單裡，免得重建到一半把自己關掉；config --services 只列啟用中的 profile
  services=$(docker compose config --services | grep -vx updater | tr '\n' ' ')
  log "重建並重啟：$services"
  if docker compose up -d --build --remove-orphans $services; then
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
