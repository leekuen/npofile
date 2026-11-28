#!/usr/bin/env bash
# docker/auto-update.sh 的測試（LK-44）：有排程工作在跑時延後更新、等太久照樣更新、
# 每分鐘一下就結束的工作不算忙。不需要 Docker、不連網：docker 換成假的指令，origin 是本機的 bare repo。
#   bash docker/auto-update-test.sh
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
pass=0 fail=0
ok() { echo "  ✅ $1"; pass=$((pass + 1)); }
bad() { echo "  ❌ $1"; fail=$((fail + 1)); }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }

# auto-update.sh 會改 git 全域設定：指到暫存檔，不動到跑測試的人的設定
export HOME="$work/home" GIT_CONFIG_GLOBAL="$work/gitconfig"
mkdir -p "$HOME"
git config --global user.email test@example.invalid
git config --global user.name test
git config --global init.defaultBranch prod
git config --global core.autocrlf false

# ── 假的 docker：compose top 依序吐 top.1、top.2…（沒有就吐 top）；up 記到 docker.log ──
mkdir -p "$work/bin"
cat >"$work/bin/docker" <<'EOF'
#!/usr/bin/env bash
w=$FAKE_WORK
if [ "$1 $2" = "compose top" ]; then
  n=$(( $(cat "$w/top.count" 2>/dev/null || echo 0) + 1 )); echo "$n" >"$w/top.count"
  if [ -f "$w/top.$n" ]; then cat "$w/top.$n"; elif [ -f "$w/top" ]; then cat "$w/top"; fi
  exit 0
fi
if [ "$1 $2" = "compose config" ]; then printf 'backend\nweb\nscheduler\nupdater\n'; exit 0; fi
echo "$*" >>"$w/docker.log"
exit 0
EOF
chmod +x "$work/bin/docker"
export PATH="$work/bin:$PATH" FAKE_WORK="$work"
export AUTO_UPDATE_BUSY_RECHECK=0 AUTO_UPDATE_STATE="$work/busy-since" AUTO_UPDATE_BRANCH=prod

# ── origin（bare）有兩個提交；app 停在第一個 ──
setup() {
  rm -rf "$work/origin.git" "$work/seed" "$work/app" "$work"/top* "$work/docker.log" "$AUTO_UPDATE_STATE"
  git init -q --bare "$work/origin.git"
  git init -q "$work/seed"
  (cd "$work/seed" && echo 1 >f && git add f && git commit -qm one && echo 2 >f && git commit -qam two \
    && git remote add origin "$work/origin.git" && git push -q origin prod)
  git clone -q "$work/origin.git" "$work/app"
  (cd "$work/app" && git reset -q --hard HEAD~1)
}
run() { (cd "$work/app" && sh "$here/auto-update.sh" --once) >"$work/out" 2>&1; echo $? >"$work/code"; }
head_msg() { git -C "$work/app" log -1 --format=%s; }
RUNNING_CRAWL='leekuen 123 1 0 02:30 ? 00:10:00 /bin/sh -c /app/deploy/run-job.sh crawl python manage.py crawl all'

echo "auto-update.sh"

setup; echo "$RUNNING_CRAWL" >"$work/top"; run
check "夜間爬蟲在跑：不更新、結束碼 0" '[ "$(cat "$work/code")" = 0 ] && [ "$(head_msg)" = one ]'
check "夜間爬蟲在跑：沒有重建" '[ ! -s "$work/docker.log" ]'
check "夜間爬蟲在跑：紀錄寫明延後與哪個工作" 'grep -q "先不更新" "$work/out" && grep -q "run-job.sh crawl" "$work/out"'
check "夜間爬蟲在跑：記下開始等的時間" '[ -s "$AUTO_UPDATE_STATE" ]'

rm -f "$work/top.count"; run
check "還在跑：再看一次照樣延後、開始等的時間不變" '[ "$(head_msg)" = one ] && grep -q "已等 0 分鐘" "$work/out"'

echo $(( $(date +%s) - 13 * 3600 )) >"$AUTO_UPDATE_STATE"; rm -f "$work/top.count"; run
check "等超過 12 小時：照樣更新" '[ "$(head_msg)" = two ] && grep -q "照樣更新" "$work/out"'
check "等超過 12 小時：有重建、清掉等待紀錄" 'grep -q "compose up" "$work/docker.log" && [ ! -e "$AUTO_UPDATE_STATE" ]'

setup; run
check "沒有工作在跑：直接更新並重建" '[ "$(head_msg)" = two ] && grep -q "compose up" "$work/docker.log"'
check "重建名單不含 updater 自己" '! grep -q "updater" "$work/docker.log"'

setup; echo 'leekuen 9 1 0 13:00 ? 00:00:01 python manage.py run_crawl_requests' >"$work/top.1"; : >"$work/top"; run
check "每分鐘一下就結束的工作（第二次看已經沒了）：照樣更新" '[ "$(head_msg)" = two ]'

setup; echo 'leekuen 9 1 0 13:00 ? 00:30:00 python manage.py crawl swft' >"$work/top"; run
check "手動跑的單一來源爬蟲也算在跑" '[ "$(head_msg)" = one ] && grep -q "manage.py crawl swft" "$work/out"'

setup; echo 'leekuen 1 0 0 02:00 ? 00:00:03 supercronic -passthrough-logs /app/docker/crontab' >"$work/top"; run
check "只有 supercronic 本身：不算忙" '[ "$(head_msg)" = two ]'

setup; (cd "$work/app" && git pull -q --ff-only); echo 123 >"$AUTO_UPDATE_STATE"; echo "$RUNNING_CRAWL" >"$work/top"; run
check "已是最新：什麼都不做、清掉等待紀錄" '[ ! -s "$work/docker.log" ] && [ ! -e "$AUTO_UPDATE_STATE" ]'

echo
echo "auto-update-test：通過 ${pass}、失敗 ${fail}"
[ "$fail" -eq 0 ]
