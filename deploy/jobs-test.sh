#!/usr/bin/env bash
# run-job.sh 與 backup-db.sh 的測試（LK-12）。不需要 PostgreSQL、不連外網：
# 通知送到本機假的 Healthchecks，pg_dump／pg_restore／rclone 換成假的指令。
#   bash deploy/jobs-test.sh
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'kill "$srv" 2>/dev/null; rm -rf "$work"' EXIT
pass=0 fail=0
ok() { echo "  ✅ $1"; pass=$((pass + 1)); }
bad() { echo "  ❌ $1"; fail=$((fail + 1)); }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }

PY=$(command -v python3 || command -v python)

# ── 假的 Healthchecks：每個請求記一行「路徑 內容」 ──
port_file="$work/port"
"$PY" - "$work/pings" "$port_file" <<'EOF' &
import http.server, sys
log, port_file = sys.argv[1], sys.argv[2]
class H(http.server.BaseHTTPRequestHandler):
    def _rec(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8", "replace").replace("\n", "|")
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{self.path} {body}\n")
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    do_GET = do_POST = _rec
    def log_message(self, *a): pass
s = http.server.HTTPServer(("127.0.0.1", 0), H)
open(port_file, "w").write(str(s.server_port))
s.serve_forever()
EOF
srv=$!
for _ in $(seq 50); do [ -s "$port_file" ] && break; sleep 0.1; done
export HEALTHCHECKS_BASE="http://127.0.0.1:$(cat "$port_file")"
export LOG_DIR="$work/logs" APP_ENV="$work/.env"
: >"$work/pings"

echo "run-job.sh"
printf 'HEALTHCHECKS_PING_KEY="abc123"\n' >"$APP_ENV"

bash "$here/run-job.sh" demo bash -c 'echo 抓到 5 筆'
code=$?
check "成功：結束碼 0" '[ "$code" -eq 0 ]'
check "成功：先回報開始（並自動建立 check）" 'grep -q "^/abc123/npofile-demo/start?create=1 " "$work/pings"'
check "成功：回報 /0 並附上輸出" 'grep -q "^/abc123/npofile-demo/0 抓到 5 筆" "$work/pings"'
check "成功：輸出寫進紀錄檔" 'grep -q "抓到 5 筆" "$LOG_DIR/demo.log"'

: >"$work/pings"
bash "$here/run-job.sh" demo bash -c 'echo 連線逾時 >&2; exit 3'
code=$?
check "失敗：結束碼照指令的（3）" '[ "$code" -eq 3 ]'
check "失敗：回報 /3，錯誤訊息（stderr）在通知內容裡" 'grep -q "^/abc123/npofile-demo/3 連線逾時" "$work/pings"'
check "失敗：紀錄檔記下結束碼" 'grep -q "結束碼 3" "$LOG_DIR/demo.log"'

: >"$work/pings"
rm -f "$APP_ENV"
bash "$here/run-job.sh" quiet bash -c 'exit 1'
code=$?
check "沒設 key：照樣跑、結束碼照傳" '[ "$code" -eq 1 ]'
check "沒設 key：不送任何通知" '[ ! -s "$work/pings" ]'
check "沒設 key：紀錄檔提醒這次失敗沒人知道" 'grep -q "不會通知任何人" "$LOG_DIR/quiet.log"'

printf 'HEALTHCHECKS_PING_KEY=abc123\n' >"$APP_ENV"
HEALTHCHECKS_BASE="http://127.0.0.1:1" bash "$here/run-job.sh" offline bash -c 'exit 0' 2>/dev/null
code=$?
check "通知送不出去：工作本身不算失敗" '[ "$code" -eq 0 ]'
check "通知送不出去：紀錄檔留一行" 'grep -q "通知送不出去" "$LOG_DIR/offline.log"'

echo "backup-db.sh"
bin="$work/bin"
mkdir -p "$bin"
# 假的 pg_dump：記下收到的參數，寫一個假備份檔；EMPTY_DB=1 時備份裡沒有組織資料
cat >"$bin/pg_dump" <<'EOF'
#!/usr/bin/env bash
echo "$@" >>"$FAKE_LOG"
for a in "$@"; do case $a in --file=*) out=${a#--file=} ;; esac; done
if [ -n "${EMPTY_DB:-}" ]; then echo "x" >"$out"; else echo "TABLE DATA public orgs_organization" >"$out"; fi
EOF
cat >"$bin/pg_restore" <<'EOF'
#!/usr/bin/env bash
cat "$2"; echo "; TABLE DATA public crawling_crawlrun"
EOF
cat >"$bin/rclone" <<'EOF'
#!/usr/bin/env bash
echo "rclone $*" >>"$FAKE_LOG"
EOF
chmod +x "$bin"/*
export PATH="$bin:$PATH" FAKE_LOG="$work/fake.log"
bdir="$work/backups"
printf 'DATABASE_URL=postgres://npofile:p@ss&w0rd@localhost:5432/npofile\nBACKUP_DIR=%s\nBACKUP_KEEP_DAYS=3\n' "$bdir" >"$APP_ENV"
mkdir -p "$bdir"
touch -d "10 days ago" "$bdir/npofile-2000-01-01.dump"
touch -d "1 day ago" "$bdir/npofile-2000-01-09.dump"

out=$(bash "$here/backup-db.sh" 2>&1)
code=$?
today="$bdir/npofile-$(date +%F).dump"
check "備份：成功" '[ "$code" -eq 0 ]'
check "備份：今天的檔案在，沒有殘留 .partial" '[ -s "$today" ] && ! ls "$bdir"/*.partial >/dev/null 2>&1'
check "備份：密碼有特殊字元也原封不動交給 pg_dump" 'grep -q -- "--dbname=postgres://npofile:p@ss&w0rd@localhost:5432/npofile" "$FAKE_LOG"'
check "備份：超過保留天數的舊檔刪掉" '[ ! -e "$bdir/npofile-2000-01-01.dump" ]'
check "備份：保留天數內的舊檔留著" '[ -e "$bdir/npofile-2000-01-09.dump" ]'
check "備份：沒設機器外位置時提醒" 'grep -q "只在這台機器上" <<<"$out"'
check "備份：沒設機器外位置就不呼叫 rclone" '! grep -q rclone "$FAKE_LOG"'

rm -f "$today"
out=$(EMPTY_DB=1 bash "$here/backup-db.sh" 2>&1)
code=$?
check "空資料庫：算失敗" '[ "$code" -ne 0 ]'
check "空資料庫：不留下不算數的備份" '[ ! -e "$today" ] && ! ls "$bdir"/*.partial >/dev/null 2>&1'

printf 'BACKUP_RCLONE_REMOTE=spaces:bk/db\n' >>"$APP_ENV"
: >"$FAKE_LOG"
bash "$here/backup-db.sh" >/dev/null 2>&1
code=$?
check "機器外：成功" '[ "$code" -eq 0 ]'
check "機器外：複製今天的檔案過去" 'grep -q "rclone copy $today spaces:bk/db" "$FAKE_LOG"'
check "機器外：刪掉機器外 60 天以上的" 'grep -q "rclone delete --min-age 60d" "$FAKE_LOG"'

printf 'DATABASE_URL=\n' >"$APP_ENV"
bash "$here/backup-db.sh" >/dev/null 2>&1
check "沒設 DATABASE_URL（還在用 SQLite）：算失敗" '[ $? -ne 0 ]'

echo
echo "通過 ${pass}、失敗 ${fail}"
[ "$fail" -eq 0 ]
