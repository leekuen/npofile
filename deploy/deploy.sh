#!/usr/bin/env bash
# 更新正式環境：在伺服器上用 npofile 帳號執行
#   sudo -iu npofile ~/app/deploy/deploy.sh
# 拉 prod → 裝套件 → migrate → collectstatic → 建前台 → 重啟服務
set -euo pipefail

APP="${APP:-$HOME/app}"
BRANCH="${BRANCH:-prod}"
export API_BASE="${API_BASE:-http://127.0.0.1:8000}"

cd "$APP"
echo "==> 拉 $BRANCH"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git merge --ff-only "origin/$BRANCH"
echo "    現在版本：$(git log -1 --format='%h %s')"

echo "==> 後端"
cd "$APP/server"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput -v 0
.venv/bin/python manage.py check --deploy --fail-level ERROR

echo "==> 前台"
cd "$APP/web"
npm ci --no-audit --no-fund
npm run build

echo "==> 重啟服務"
sudo systemctl restart npofile-api npofile-web
sleep 3
systemctl is-active --quiet npofile-api && systemctl is-active --quiet npofile-web
curl -fsS -o /dev/null "$API_BASE/api/stats" && echo "    後端 OK"
curl -fsS -o /dev/null http://127.0.0.1:3000/ && echo "    前台 OK"
echo "==> 完成"
