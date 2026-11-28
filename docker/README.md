# NPOFile：Docker Compose 部署（LK-14）

一份 `compose.yaml` 跑全部服務。映像檔支援 **linux/arm64（Apple Silicon）** 與 linux/amd64，
每次推送都會在 GitHub Actions 的 x86 與 ARM64 機器上各自整套建起來測一次（`.github/workflows/docker.yml`）。

```
Cloudflare ──tunnel──▶ cloudflared ──▶ nginx:80
                                         ├─ /          → web（Next.js :3000，/api/* 再轉給 backend）
                                         ├─ /admin/    → backend（Django＋gunicorn :8000）
                                         └─ /static/   → static volume（backend 啟動時 collectstatic）
backend ──▶ db（PostgreSQL 16）
scheduler（同 backend 映像檔＋supercronic）──▶ 每天備份、爬蟲、重算揭露指數
```

| 服務 | 映像檔 | 對外 port |
|---|---|---|
| `db` | `postgres:16-alpine` | 無 |
| `backend` | 本 repo `server/Dockerfile` | 無 |
| `web` | 本 repo `web/Dockerfile` | 無 |
| `nginx` | `nginx:1.28-alpine` | 只綁 `127.0.0.1:8080`（本機測試用，外面連不到） |
| `scheduler` | 同 `backend` | 無 |
| `cloudflared` | `cloudflare/cloudflared:2026.11.0` | 無（主動連出去） |
| `updater` | 本 repo `docker/updater.Dockerfile`（`docker:29.8-cli`＋git） | 無 |

**沒有上傳檔案的功能**，要保存的只有資料庫（`PG_DATA_DIR`）；備份與排程紀錄另外各一個資料夾。

## 第一次啟動

```bash
git clone https://github.com/leekuen/npofile.git && cd npofile
git checkout prod
cp .env.example .env
```

編輯 `.env`：

| 變數 | 說明 |
|---|---|
| `DOMAIN` | 對外網址，例 `npofile.leekuen.com` |
| `DJANGO_SECRET_KEY` | `python3 -c "import secrets;print(secrets.token_urlsafe(50))"` |
| `POSTGRES_PASSWORD` | 只用英數與 `-` `_`（會放進連線網址）：`python3 -c "import secrets;print(secrets.token_urlsafe(24))"` |
| `CLOUDFLARE_TUNNEL_TOKEN` | 見下方〈Cloudflare Tunnel〉 |
| `PG_DATA_DIR` | PostgreSQL 資料夾，例 `/Volumes/外接硬碟/npofile/postgres` |
| `BACKUP_DIR_HOST` | 每天備份放哪，例 `/Volumes/外接硬碟/npofile/backups` |
| `LOG_DIR_HOST` | 排程紀錄放哪，例 `/Volumes/外接硬碟/npofile/logs` |

```bash
docker compose up -d --build
docker compose ps                      # 全部 healthy／running
curl -I http://127.0.0.1:8080/         # 200
docker compose exec -u app backend python manage.py createsuperuser   # 管理後台帳號
```

- `backend` 每次啟動都會 `migrate`＋`collectstatic`，換版不用另外下指令。
- `scheduler` 每次啟動會在背景重算一次組織分類（`/logs/classify.log`）。
- 外接硬碟要在 Docker Desktop → Settings → Resources → File sharing 裡（`/Volumes` 預設就有）。
  硬碟沒掛上時不要啟動 `db`，不然會在空資料夾建一個新的資料庫。

## Cloudflare Tunnel

網域在 Cloudflare（`leekuen.com`）。

1. Cloudflare 後台 → Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared，取名 `npofile`。
2. 安裝步驟那頁會顯示一串 token（`eyJ…`），貼到 `.env` 的 `CLOUDFLARE_TUNNEL_TOKEN`。不用照它的指令裝 cloudflared，compose 裡已經有。
3. Public Hostname：Subdomain `npofile`、Domain `leekuen.com`、Service **HTTP**、URL **`nginx:80`**。
4. `.env` 保留 `COMPOSE_PROFILES=tunnel,autoupdate`，`docker compose up -d`。

主機不用開任何 port。HTTPS 由 Cloudflare 處理；Django 的登入 cookie 只走 HTTPS（`DJANGO_SECURE_COOKIES=true`），
所以**登入、留言只能從 `https://網域` 測**，`http://127.0.0.1:8080` 看得到頁面但登不進去。

## 匯入既有資料（從舊主機的備份）

舊主機每天的備份是 `pg_dump --format=custom` 的檔案（`npofile-日期.dump`）。第一次啟動後：

```bash
docker compose stop backend web scheduler
docker compose exec -T db pg_restore -U npofile -d npofile --clean --if-exists --no-owner < npofile-日期.dump
docker compose start backend web scheduler
```

## 自動更新

`.env` 的 `COMPOSE_PROFILES` 有 `autoupdate` 時，`updater` 每 5 分鐘（`AUTO_UPDATE_INTERVAL`）看一次 GitHub 上的
`prod`（`AUTO_UPDATE_BRANCH`）：有新版就 `git` 快轉、`docker compose up -d --build` 重建並重啟其他服務，再清掉舊映像檔。
沒有新版什麼都不做。

- **一定要在 repo 資料夾裡執行 `docker compose`**：`updater` 把 repo 掛在跟主機一樣的路徑（`${PWD}`），
  compose 裡的相對路徑才對得上；在別的資料夾用 `-f` 啟動會掛錯地方。
- 它掛了 `/var/run/docker.sock`，等於能操作這台的 Docker；只拉公開 repo 的 `prod`，不需要任何帳號或 token。
- **有排程工作在跑就先不更新**（LK-44）：`scheduler` 或 `backend` 裡有 `run-job.sh`（每晚爬蟲、備份、重算）
  或 `manage.py crawl`、`run_crawl_requests` 在跑時，重建會把它砍掉，所以延後到下一輪再看，log 寫
  「有新版，但排程工作還在跑，先不更新」。每晚的爬蟲常跑到早上，這段時間推的 `prod` 會等它跑完才上線。
  最多等 12 小時（`AUTO_UPDATE_MAX_WAIT`，秒），超過就照樣更新。急著上線又不在乎中斷：手動更新（見下）。
- 看它在做什麼：`docker compose logs -f updater`。
- **不要在這台上直接改程式檔**（`.env` 與資料夾不算）：本機有改過的檔案或跟 `prod` 分岔時，它會停下來不更新、在 log 裡說原因。
  要還原成 GitHub 上的版本：`git fetch origin && git reset --hard origin/prod`。
- 不想自動更新：`COMPOSE_PROFILES` 拿掉 `autoupdate`，`docker compose up -d --remove-orphans`。

手動更新（沒開自動更新時）：

```bash
git pull
docker compose up -d --build
```

## 排程

時間表在 `docker/crontab`（時區 Asia/Taipei），每個工作的輸出在 `LOG_DIR_HOST/<名稱>.log`：

| 時間 | 工作 |
|---|---|
| 02:00 | 備份資料庫到 `BACKUP_DIR_HOST`，留 14 天（`BACKUP_KEEP_DAYS`） |
| 02:30 | 爬所有啟用中的來源 |
| 05:30 | 清掉近 5 年以外的資料、重算揭露指數 |
| 每分鐘 | 看有沒有後台按的「排入完整爬取」，有就在背景跑完（紀錄在 `crawl-requests.log`；進度看後台「完整爬取請求」） |

手動跑一次：`docker compose exec -u app scheduler /app/deploy/run-job.sh backup /app/deploy/backup-db.sh`

**不用下指令也能立即完整爬取**：後台 → 爬蟲來源設定 → 勾選來源 → 動作「排入完整爬取」。scheduler 一分鐘內開始，跑完會清舊資料並重算揭露指數；同一時間只跑一個，排隊中的可以在「完整爬取請求」取消。

失敗通知：`.env` 設 `HEALTHCHECKS_PING_KEY`（healthchecks.io），做法見 `deploy/README.md`〈排程失敗通知〉。

環境部裁處（`moenv_penalties`）：`.env` 設 `MOENV_API_KEY`（到 data.moenv.gov.tw 免費申請），改完 `docker compose up -d` 讓容器吃到。

## 看紀錄

```bash
docker compose logs -f backend          # Django／gunicorn
docker compose logs -f web              # Next.js
docker compose logs -f scheduler        # 排程（每個工作的完整輸出在 LOG_DIR_HOST）
docker compose logs -f cloudflared
```

## 從備份還原

```bash
docker compose stop backend web scheduler
docker compose exec -T db pg_restore -U npofile -d npofile --clean --if-exists --no-owner < "$BACKUP_DIR_HOST/npofile-日期.dump"
docker compose start backend web scheduler
```
