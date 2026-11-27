#!/usr/bin/env bash
# 更新正式環境：在伺服器上用 npofile 帳號執行
#   sudo -iu npofile ~/app/deploy/deploy.sh
# 拉 prod → 裝套件 → migrate → collectstatic → 建前台 → 重啟服務 → 重算組織分類 → 重算揭露指數與公開募款
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

# 分類規則寫在程式裡（server/orgs/taxonomy.py），改規則一定要部署；每天的爬蟲只重分「資料有變」的組織，
# 所以部署完把全部重算一次，舊組織才會換上新標籤。放在重啟之後：服務先起來，重算期間網站照常可用。
echo "==> 重算組織分類"
cd "$APP/server"
.venv/bin/python manage.py classify_orgs
# 揭露指數與近 5 年公開募款（LK-20）存在組織上、每天 05:30 重算；新欄位或算法換版後先算一次，首頁排序不用等到隔天
echo "==> 重算揭露指數與近 5 年公開募款"
.venv/bin/python manage.py recompute_scores
echo "==> 完成"
