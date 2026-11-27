---
id: LK-10
title: 正式環境部署（DigitalOcean 單機）
status: 開發中
roles: [管理員/維運]
owner: claude-cc-LK-10
depends: []
spec: docs/SPEC.md#3-功能細節
created: 2026-11-27
updated: 2026-11-27
---

## 目的（要解決什麼問題）

使用者 2026-11-27：「我要如何正式串上公開頁面，我有在 DigitalOcean 開了一個伺服器」→ 同意「把部署檔加進 repo」。
目前沒有任何部署設定（AGENTS.md〈部署〉是「未定」），每次要上線都得重想一次怎麼裝。把一台 Droplet 從零裝好、之後一行指令更新的做法寫進版控。

## 使用角色與情境

- 管理員／維運：第一次照 `deploy/README.md` 把一台 Ubuntu 24.04 Droplet 裝好；之後每次 `prod` 有新東西，SSH 進去跑 `deploy/deploy.sh`。
- 公眾／捐款人：透過網域（HTTPS）看到前台；行為不變。

## 逼問紀錄

- 問（agent 代決）：一台機器還是拆服務（App Platform、Managed DB）？／答：一台 Droplet 全裝（nginx＋Next.js＋gunicorn＋PostgreSQL＋cron）／因此：使用者已經開好一台伺服器，現階段流量小，單機最省錢也最好懂；之後要拆再開票。
- 問（agent 代決）：用 Docker 還是直接裝？／答：直接裝＋systemd／因此：少一層要學的東西，出錯時 `journalctl` 就看得到。
- 問（agent 代決）：伺服器拉哪條分支？／答：`prod`／因此：照 AGENTS.md 分支模型，`stage` 驗過才進 `prod`。
- 問（agent 代決）：資料怎麼上去？／答：在伺服器上重新爬（fia、mohw、mohw_activities、violations），不搬本機 SQLite／因此：本機資料只是開發樣本。
- 誰看得到、誰能改：不涉及（沒有新的資料或欄位）。

## 需求細節

- `server/requirements.txt` 加 `gunicorn`（正式環境的 WSGI 伺服器）。
- `deploy/`：
  - `README.md`：第一次安裝步驟（套件、帳號、資料庫、deploy key、`.env`、systemd、nginx、HTTPS、cron、初次爬資料）、更新、看紀錄、回滾。
  - `npofile-api.service`（gunicorn 綁 127.0.0.1:8000）、`npofile-web.service`（`next start` 綁 127.0.0.1:3000）。
  - `nginx.conf`：`/` → Next.js；`/admin/` → Django；`/static/` → `staticfiles/`。
  - `deploy.sh`：拉 `prod` → 裝套件 → migrate → collectstatic → 建前台 → 重啟兩個服務。
  - `crontab`：每天凌晨爬蟲、`prune_old_records`、`recompute_scores`。
- `server/.env` 正式環境：`DJANGO_ALLOWED_HOSTS` 要含 `127.0.0.1`（Next.js 轉 `/api` 時 Host 是 `127.0.0.1:8000`），`DJANGO_CSRF_TRUSTED_ORIGINS` 填 `https://網域`。
- AGENTS.md〈部署〉與〈分支與出貨流程〉第 6 點的「未定」改指向 `deploy/README.md`。
- 欄位權限：不涉及。

## 條件確認

不適用：沒有改變資料出現或消失的條件，只是把既有程式裝到伺服器上。

## 數字口徑

不適用：沒有新的數字。

## 這次可能會弄壞什麼

- W1 本機開發：`requirements.txt` 多了 gunicorn，`make setup-dev` 照樣要裝得起來、後端測試照樣過。

## 驗收標準

- [ ] W1 `make test-server` 綠、`pip install -r server/requirements.txt` 在本機裝得起來。
- [ ] `deploy.sh` 通過 `bash -n` 語法檢查；systemd 檔與 nginx 設定照 README 放到伺服器後，`nginx -t` 通過、兩個服務起得來。
- [ ] 伺服器上 `https://網域/` 開得到首頁、`/admin/` 登得進去、前台登入留言不被 CSRF 擋。

## 邊界（明確不做什麼）

- 不做 CI/CD 自動部署（GitHub Actions）、不做 Docker、不做多台機器或 Managed Database。
- 不搬本機資料庫。
- 不替使用者 SSH 進伺服器操作（要做需使用者另外同意並提供連線方式）。

## 開發備註（/dev 填寫）

- 部署檔只放 `deploy/`，不動產品程式行為；唯一的產品目錄變更是 `server/requirements.txt` 多一行 gunicorn。
- 伺服器上的路徑寫死為 `/home/npofile/app`（使用者帳號 `npofile`），四個檔案一致。
- 走查（本機，2026-11-27）W1 新建的 venv 跑 `pip install -r server/requirements.txt` 成功（gunicorn 27.0.1、Django 6.1.3），`manage.py test` 64 個全過；`DJANGO_DEBUG=false` 下 `check --deploy --fail-level ERROR` 通過（只剩 HSTS、SSL redirect 兩個警告，由 nginx＋certbot `--redirect` 處理）；`bash -n deploy/deploy.sh` 通過。伺服器上的兩條驗收還沒做（要等使用者的 Droplet）。
