# 部署：DigitalOcean 單機（LK-10）

一台 Ubuntu 24.04 Droplet 裝全部東西。伺服器只拉 `prod` 分支。

```
瀏覽器 ──https──▶ nginx :443
                   ├─ /            → Next.js :3000（/api/* 由它轉給 Django）
                   ├─ /admin/      → Django（gunicorn）:8000
                   └─ /static/     → server/staticfiles/
Django ──▶ PostgreSQL（同一台）
cron   ──▶ 每天備份資料庫、爬蟲、清舊資料、重算揭露指數
         └─ 失敗或沒準時跑完 → Healthchecks.io 寄信
```

| 檔案 | 放到伺服器哪裡 |
|---|---|
| `npofile-api.service` | `/etc/systemd/system/` |
| `npofile-web.service` | `/etc/systemd/system/` |
| `nginx.conf` | `/etc/nginx/sites-available/npofile`（網域要改） |
| `crontab` | `crontab -u npofile deploy/crontab` |
| `deploy.sh` | 不用搬，在 repo 裡直接跑 |
| `run-job.sh`、`backup-db.sh` | 不用搬，crontab 直接叫 repo 裡的 |

路徑都寫死成 `/home/npofile/app`（帳號 `npofile`）。要改的話，四個檔案要一起改。

---

## 第一次安裝

下面 `example.com` 都換成你的網域。先到 DNS 把網域的 A 記錄指到 Droplet 的 IP。

### 1. 系統套件（root）

```bash
apt update && apt upgrade -y
apt install -y python3-venv python3-dev build-essential git nginx postgresql certbot python3-certbot-nginx
curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt install -y nodejs
timedatectl set-timezone Asia/Taipei
ufw allow OpenSSH && ufw allow 'Nginx Full' && ufw --force enable
```

Ubuntu 24.04 內建 Python 3.12，Django 6 可以用。Next.js 16 要 Node 20.9 以上，這裡裝 22。

### 2. 執行帳號（root）

```bash
adduser --disabled-password --gecos "" npofile
chmod 755 /home/npofile          # nginx 要讀得到 staticfiles
# deploy.sh 要能重啟這兩個服務，只開這兩條，不給完整 sudo
cat > /etc/sudoers.d/npofile <<'EOF'
npofile ALL=(root) NOPASSWD: /usr/bin/systemctl restart npofile-api npofile-web
EOF
chmod 440 /etc/sudoers.d/npofile && visudo -c
```

### 3. 資料庫（root）

```bash
sudo -u postgres psql -c "CREATE USER npofile WITH PASSWORD '換成強密碼';"
sudo -u postgres psql -c "CREATE DATABASE npofile OWNER npofile;"
```

### 4. 拉程式碼（npofile）

repo 是私有的，所以要給伺服器一把**唯讀**的 deploy key：

```bash
sudo -iu npofile
mkdir -p ~/logs
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 && cat ~/.ssh/id_ed25519.pub
```

把印出來的公鑰貼到 GitHub 的 repo → Settings → Deploy keys → Add deploy key（不要勾 Allow write access）。然後：

```bash
git clone -b prod git@github.com:leekuen/npofile.git ~/app
```

### 5. 後端設定（npofile）

建立 `~/app/server/.env`：

```
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=<用 python3 -c "import secrets;print(secrets.token_urlsafe(50))" 產生>
DJANGO_ALLOWED_HOSTS=example.com,127.0.0.1,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=https://example.com
DATABASE_URL=postgres://npofile:換成強密碼@localhost:5432/npofile
CRAWLER_MIN_INTERVAL=1.0
DONOR_INDIVIDUAL_THRESHOLD=100000
```

- `ALLOWED_HOSTS` 一定要包含 `127.0.0.1`。Next.js 把 `/api/*` 轉給 Django 時，Host 標頭是 `127.0.0.1:8000`。
- 如果要用 `www.example.com`，兩行都要加上去。
- `.env` 不進版控，備份放在自己的密碼管理器裡。

```bash
chmod 600 ~/app/server/.env
```

### 6. 裝服務（root）

```bash
cp /home/npofile/app/deploy/npofile-api.service /home/npofile/app/deploy/npofile-web.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable npofile-api npofile-web
```

### 7. 第一次建置（npofile）

```bash
sudo -iu npofile ~/app/deploy/deploy.sh
sudo -iu npofile bash -c 'cd ~/app/server && .venv/bin/python manage.py createsuperuser'
```

`deploy.sh` 跑到最後印出「後端 OK」「前台 OK」，就代表兩個服務都起來了。

### 8. nginx 與 HTTPS（root）

```bash
cp /home/npofile/app/deploy/nginx.conf /etc/nginx/sites-available/npofile
sed -i 's/example.com/你的網域/' /etc/nginx/sites-available/npofile
ln -sf /etc/nginx/sites-available/npofile /etc/nginx/sites-enabled/npofile
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
certbot --nginx -d 你的網域 --redirect
```

certbot 會自動續約，不用另外排程。

### 9. 初次抓資料（npofile）

正式環境的資料庫是空的，要在伺服器上重新爬（不搬本機 SQLite）。這一步要跑很久，用 `tmux` 開著，斷線也不會中斷：

```bash
sudo -iu npofile
tmux
cd ~/app/server
.venv/bin/python manage.py crawl fia                       # 財政部名冊約 10 萬筆
.venv/bin/python manage.py crawl mohw                      # 公益勸募團體
.venv/bin/python manage.py crawl mohw_violations           # 違規公告（全部年度的裁罰）
.venv/bin/python manage.py crawl mohw_activities --limit 50 # 勸募活動＋捐贈人清冊（先抓一部分）
.venv/bin/python manage.py match_companies
.venv/bin/python manage.py recompute_scores
```

### 10. 排程失敗通知（自己的電腦＋npofile）

沒有這一步，爬蟲壞掉只會寫進紀錄檔，沒人看就不會知道資料停更了。

1. 到 <https://healthchecks.io> 註冊（免費方案就夠），建一個專案，例如「npofile」。
2. 專案的 **Settings → Ping key** 按 Create，複製那串 key。
3. **Integrations** 預設會寄信到註冊的信箱；要 LINE、Telegram、Slack 也在這裡加。
4. 把 key 加進伺服器的 `~/app/server/.env`：

   ```
   HEALTHCHECKS_PING_KEY=剛剛複製的 key
   ```

5. 手動跑一次，讓 check 自動建立起來（`npofile-backup` 在第 11 步建立）：

   ```bash
   sudo -iu npofile
   ~/app/deploy/run-job.sh scores bash -c 'cd ~/app/server && .venv/bin/python manage.py recompute_scores'
   ~/app/deploy/run-job.sh crawl  bash -c 'cd ~/app/server && .venv/bin/python manage.py crawl mohw --limit 1'
   ```

6. 回到 Healthchecks，把三個 check 的時間表改成跟 crontab 一樣（不改的話預設是「每天一次、寬限 1 小時」，
   爬蟲跑得久會誤報）：

   | Check | Schedule（Cron，時區選 Asia/Taipei） | Grace time |
   |---|---|---|
   | `npofile-backup` | `0 2 * * *` | 1 小時 |
   | `npofile-crawl` | `30 2 * * *` | 3 小時（爬蟲開始後超過這麼久沒跑完，也會通知） |
   | `npofile-scores` | `30 5 * * *` | 1 小時 |

會收到通知的情況：

- 工作失敗（結束碼不是 0）。信裡附輸出的最後 20KB，通常直接看得到錯誤。
- 爬蟲「成功」但某個來源**一筆都沒抓到**：多半是來源網站改版，`crawl` 會當成失敗。
- 到了時間沒開始跑、或開始了沒在寬限時間內跑完：伺服器關機、cron 沒裝、程式卡住都屬於這種。

### 11. 資料庫每日備份（npofile）

正式資料庫是在伺服器上重新爬出來的，壞了要重爬好幾天。每天 02:00（爬蟲之前）`backup-db.sh` 會：

1. `pg_dump` 成 `~/backups/npofile-日期.dump`（壓縮過的 PostgreSQL 格式，只有 npofile 帳號讀得到）。
2. 檢查檔案讀得回來、裡面真的有組織資料；不合格就算失敗（會通知），不會留下壞檔。
3. 刪掉 14 天前的本機備份。
4. 有設機器外位置的話，複製一份過去，並刪掉那邊 60 天前的。

先手動跑一次，確定成功：

```bash
sudo -iu npofile ~/app/deploy/run-job.sh backup ~/app/deploy/backup-db.sh   # 順便在 Healthchecks 建立 npofile-backup
ls -lh ~npofile/backups
```

**本機備份擋不住整台機器壞掉**（硬碟毀損、Droplet 被誤刪）。強烈建議再放一份到機器外，用 DigitalOcean Spaces：

1. DigitalOcean 後台 → Spaces Object Storage → 建一個 bucket（例 `npofile-backups`，區域選跟 Droplet 一樣，例 `sgp1`）；
   **不要**開 CDN、權限維持 Private。
2. API → Spaces Keys → Generate New Key，記下 Access Key 和 Secret。
3. 伺服器上（root）裝 rclone：`apt install -y rclone`
4. npofile 帳號設定 remote（key 只存在這個帳號的 `~/.config/rclone/rclone.conf`）：

   ```bash
   sudo -iu npofile
   rclone config create spaces s3 provider=DigitalOcean env_auth=false access_key_id=你的AccessKey secret_access_key=你的Secret endpoint=sgp1.digitaloceanspaces.com
   chmod 600 ~/.config/rclone/rclone.conf
   ```

5. `~/app/server/.env` 加上 `BACKUP_RCLONE_REMOTE=spaces:npofile-backups/db`，再手動跑一次 `backup-db.sh`，
   最後一段應該印「複製到機器外」，`rclone ls spaces:npofile-backups/db` 看得到檔案。

保留天數要改的話，在 `.env` 設 `BACKUP_KEEP_DAYS`（本機）、`BACKUP_REMOTE_KEEP_DAYS`（機器外）。

### 12. 排程（root）

```bash
crontab -u npofile /home/npofile/app/deploy/crontab
```

---

## 之後每次更新

1. 本機：`stage` 驗過 → `make confirm-lint-prod t="這次的票號"` → 把 `stage` 合進 `prod`、推上去。
2. 伺服器：

```bash
sudo -iu npofile ~/app/deploy/deploy.sh
```

`deploy.sh` 在服務重啟、印出「後端 OK」「前台 OK」之後，會把所有組織的分類重算一次（`classify_orgs`），
讓分類規則的修改套到舊資料上。十萬筆組織在本機約 11 秒，期間網站照常可用；看到「==> 完成」才算跑完。

## 上線後檢查

- `curl -I https://你的網域/` 回 200。
- `https://你的網域/admin/` 登得進去。
- 前台註冊、登入、留言都要能成功，不能出現 CSRF 錯誤。

## 看紀錄

```bash
journalctl -u npofile-api -n 100 --no-pager     # Django／gunicorn
journalctl -u npofile-web -n 100 --no-pager     # Next.js
tail -n 100 /var/log/nginx/error.log
tail -n 100 /home/npofile/logs/crawl.log      # 爬蟲（backup.log、scores.log 同一個資料夾）
```

排程每一次跑的結果（成功、失敗、花多久）也看得到：Healthchecks 上點 check → Events。

## 回滾

在本機對 `prod` 做 `git revert`，推上去後再跑一次 `deploy.sh`。如果某個版本做了不可逆的 migration，更新前先手動備份一次：

```bash
sudo -iu npofile ~/app/deploy/backup-db.sh
```

（同一天跑第二次會覆蓋當天的檔案；要留住更新前那份，跑完把它改名，例 `mv ~/backups/npofile-$(date +%F).dump ~/backups/before-deploy.dump`。）

## 從備份還原

還原會把資料庫整個換成備份當天的內容，之後抓的資料、新的留言都會不見。先停掉後端，不讓網站在還原中寫入：

```bash
sudo systemctl stop npofile-api                       # root
sudo -iu npofile
ls -lh ~/backups                                      # 挑一份；機器外的用 rclone copy spaces:npofile-backups/db/檔名 ~/backups/ 拿回來
DB=$(sed -n 's/^DATABASE_URL=//p' ~/app/server/.env)
pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$DB" ~/backups/npofile-2026-12-01.dump
exit
sudo systemctl start npofile-api                      # root
```

**每個月演練一次**，確定備份真的能用（還原到另一個空資料庫，不碰正式的）：

```bash
sudo -u postgres createdb -O npofile npofile_restore_test
sudo -iu npofile bash -c 'DB=$(sed -n "s/^DATABASE_URL=//p" ~/app/server/.env); pg_restore --no-owner --no-privileges --dbname="${DB%/*}/npofile_restore_test" ~/backups/$(ls ~/backups | tail -n 1) && echo 還原 OK'
sudo -u postgres psql npofile_restore_test -c "select count(*) from orgs_organization;"   # 應該是十萬上下
sudo -u postgres dropdb npofile_restore_test
```

## 常見問題

- **前台 500，紀錄寫「無法連線到後端」**：`npofile-api` 沒起來，用 `journalctl -u npofile-api` 看原因。最常見的是 `.env` 少了 `DJANGO_SECRET_KEY`，或 `DATABASE_URL` 寫錯。
- **`/api` 回 400 Bad Request**：`DJANGO_ALLOWED_HOSTS` 少了 `127.0.0.1`。
- **登入或留言時 CSRF 失敗**：`DJANGO_CSRF_TRUSTED_ORIGINS` 要完全符合 `https://網域`，不能有結尾斜線。
- **管理後台沒有樣式**：檢查 `collectstatic` 有沒有跑，以及 `/home/npofile` 是不是 `755`。
