# 部署：DigitalOcean 單機（LK-10）

一台 Ubuntu 24.04 Droplet 裝全部東西。伺服器只拉 `prod` 分支。

```
瀏覽器 ──https──▶ nginx :443
                   ├─ /            → Next.js :3000（/api/* 由它轉給 Django）
                   ├─ /admin/      → Django（gunicorn）:8000
                   └─ /static/     → server/staticfiles/
Django ──▶ PostgreSQL（同一台）
cron   ──▶ 每天爬蟲、清舊資料、重算揭露指數
```

| 檔案 | 放到伺服器哪裡 |
|---|---|
| `npofile-api.service` | `/etc/systemd/system/` |
| `npofile-web.service` | `/etc/systemd/system/` |
| `nginx.conf` | `/etc/nginx/sites-available/npofile`（網域要改） |
| `crontab` | `crontab -u npofile deploy/crontab` |
| `deploy.sh` | 不用搬，在 repo 裡直接跑 |

路徑都寫死成 `/home/npofile/app`（帳號 `npofile`）。要改的話，四個檔案要一起改。

> **目前正式環境（2026-11-27 起）不是上面這種「獨佔一台」的裝法**，而是跟 LINE CRM 共用同一台
> 512MB 的 Droplet（168.144.130.162），做法見下方〈與 LINE CRM 共用主機〉。之後換到自己的主機，就照「第一次安裝」整套做。

---

## 與 LINE CRM 共用主機（目前的做法）

這台主機的 80／443 已經被 LINE CRM 的 Caddy（Docker）佔著，所以 NPOFile 不直接對外：

```
瀏覽器 ──▶ CRM 的 Caddy（Docker，:80/:443）
             ├─ kuen-crm.duckdns.org → CRM
             └─ NPOFILE_ADDRESS     → host.docker.internal:8080
                                        └─ 主機 nginx :8080（deploy/nginx.conf 改 listen 8080）
                                             ├─ /         → Next.js :3000
                                             ├─ /admin/   → gunicorn :8000
                                             └─ /static/  → staticfiles/
```

跟「第一次安裝」不同的地方：

- **不跑 certbot**，HTTPS 由 CRM 的 Caddy 處理（`NPOFILE_ADDRESS` 填網域時自動申請憑證）。
- nginx 改聽 `8080`、`server_name _`、`X-Forwarded-Proto $http_x_forwarded_proto`；防火牆只開給 Docker 網段：
  `ufw allow from 172.16.0.0/12 to any port 8080 proto tcp`。
- 記憶體小：加 2GB swap；gunicorn 改 2 個 worker；`npofile-web.service` 加 `Environment=NODE_OPTIONS=--max-old-space-size=256`；
  PostgreSQL 用 `/etc/postgresql/16/main/conf.d/npofile-small.conf`（`shared_buffers=48MB`、`max_connections=20`）。
- `server/.env` 的 `DJANGO_ALLOWED_HOSTS`、`DJANGO_CSRF_TRUSTED_ORIGINS` 要跟 `NPOFILE_ADDRESS` 一致。

**CRM 那邊加的東西（也要加進 CRM 的 repo）**：CRM 用 GitHub Actions `rsync --delete` 部署，
伺服器上的 `Caddyfile`、`compose.yaml` 每次都會被 repo 的版本蓋掉；沒進 CRM repo，下一次 CRM 部署 NPOFile 就連不到（CRM 本身不受影響）。

`Caddyfile` 最後加：

```
# 非營利檔案 NPOFile（同一台主機上，不在 Docker 裡；主機 nginx 聽 8080）。
# NPOFILE_ADDRESS 來自 .env：還沒有網域時填 http://主機IP；有網域後改成網域，Caddy 會自動上 HTTPS。
{$NPOFILE_ADDRESS} {
	encode gzip
	reverse_proxy host.docker.internal:8080
}
```

`compose.yaml` 的 `caddy` 服務，`STAGING_ADDRESS` 那行下面加：

```yaml
      # 非營利檔案 NPOFile 的網址（見 Caddyfile 最後一段）。沒設就用一個不會有人連的名稱
      NPOFILE_ADDRESS: ${NPOFILE_ADDRESS:-http://npofile.localhost}
    # 讓 caddy 連得到主機上的服務（NPOFile 的 nginx :8080）
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

主機上 `/srv/line-crm/.env` 加 `NPOFILE_ADDRESS=npofile-kuen.duckdns.org`（2026-11-27 起；沒有網域時填 `http://主機IP`）（`.env` 不會被 CRM 部署蓋掉）。
改完 `cd /srv/line-crm && docker compose up -d caddy`。改之前的備份在 `/root/backup-line-crm/`。

**換成網域**（例：`npofile-kuen.duckdns.org`，DNS 指到 168.144.130.162）：

1. `/srv/line-crm/.env`：`NPOFILE_ADDRESS=npofile-kuen.duckdns.org`（不加 `http://`，Caddy 才會上 HTTPS）→ `docker compose up -d caddy`。
2. `/home/npofile/app/server/.env`：`DJANGO_ALLOWED_HOSTS` 加上網域、`DJANGO_CSRF_TRUSTED_ORIGINS=https://網域` → `systemctl restart npofile-api`。

用 `http://IP` 的期間，登入與留言不能用：正式環境的登入 cookie 只走 HTTPS（`DJANGO_SECURE_COOKIES` 預設開），這是刻意的，不要為了 IP 關掉。

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

### 10. 排程（root）

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

## 上線後檢查

- `curl -I https://你的網域/` 回 200。
- `https://你的網域/admin/` 登得進去。
- 前台註冊、登入、留言都要能成功，不能出現 CSRF 錯誤。

## 看紀錄

```bash
journalctl -u npofile-api -n 100 --no-pager     # Django／gunicorn
journalctl -u npofile-web -n 100 --no-pager     # Next.js
tail -n 100 /var/log/nginx/error.log
tail -n 100 /home/npofile/logs/crawl.log
```

## 回滾

在本機對 `prod` 做 `git revert`，推上去後再跑一次 `deploy.sh`。如果某個版本做了不可逆的 migration，要先備份資料庫再更新：

```bash
sudo -u postgres pg_dump npofile > /root/npofile-$(date +%F).sql
```

## 常見問題

- **前台 500，紀錄寫「無法連線到後端」**：`npofile-api` 沒起來，用 `journalctl -u npofile-api` 看原因。最常見的是 `.env` 少了 `DJANGO_SECRET_KEY`，或 `DATABASE_URL` 寫錯。
- **`/api` 回 400 Bad Request**：`DJANGO_ALLOWED_HOSTS` 少了 `127.0.0.1`。
- **登入或留言時 CSRF 失敗**：`DJANGO_CSRF_TRUSTED_ORIGINS` 要完全符合 `https://網域`，不能有結尾斜線。
- **管理後台沒有樣式**：檢查 `collectstatic` 有沒有跑，以及 `/home/npofile` 是不是 `755`。
