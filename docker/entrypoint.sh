#!/usr/bin/env bash
# 後端／排程 container 的進入點：以 root 啟動，把掛進來的資料夾交給 app 帳號，再降權執行。
# RUN_MIGRATIONS=1（backend）：啟動前 migrate＋collectstatic。
# RUN_CLASSIFY=1（scheduler）：啟動後在背景重算一次組織分類（規則寫在程式裡，換版要重算）。
set -euo pipefail

mkdir -p "${BACKUP_DIR:-/backups}" "${LOG_DIR:-/logs}"
chown app:app "${BACKUP_DIR:-/backups}" "${LOG_DIR:-/logs}" /app/server/staticfiles 2>/dev/null || true

as_app() { setpriv --reuid=app --regid=app --init-groups "$@"; }

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  as_app python manage.py migrate --noinput
  as_app python manage.py collectstatic --noinput -v 0
  as_app python manage.py check --deploy --fail-level ERROR
fi

if [ "${RUN_CLASSIFY:-0}" = "1" ]; then
  as_app /app/deploy/run-job.sh classify python manage.py classify_orgs &
  # 揭露指數與近 5 年公開募款（LK-20）換版後先算一次，首頁排序不用等每天 05:30 的排程
  as_app /app/deploy/run-job.sh scores python manage.py recompute_scores &
  # 上市櫃公司 ESG（LK-39）：資料表還是空的就先抓一次，不用等週日的排程；有資料就馬上結束
  as_app /app/deploy/run-job.sh esg python manage.py sync_esg --if-empty &
fi

exec setpriv --reuid=app --regid=app --init-groups "$@"
