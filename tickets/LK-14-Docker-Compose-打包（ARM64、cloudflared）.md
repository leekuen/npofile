---
id: LK-14
title: Docker Compose 打包（ARM64、cloudflared）
status: 開發中
roles: [管理員/維運]
owner: claude-cc-LK-14
depends: []
spec: docs/SPEC.md#3-功能細節
created: 2026-11-27
updated: 2026-11-27
---

## 目的（要解決什麼問題）

使用者 2026-11-27：DigitalOcean 512MB 那台「真的跑太慢」，改放到朋友（書）提供的主機。書要求 Docker Compose，規格（使用者貼上）：
主機 Apple Silicon（linux/arm64）；PostgreSQL 資料與上傳檔案的 volume 路徑用 .env 變數（指到外接 APFS 硬碟）；cron 包成獨立 container 或寫進 backend；對外用 compose 裡的 cloudflared 指向內部 nginx:80（token 放 .env），主機不開 port。

## 使用角色與情境

- 管理員／維運（書）：`cp .env.example .env` 填值 → `docker compose up -d --build`，網站經 Cloudflare Tunnel 對外。
- 公眾／捐款人：網址改成 `npofile.leekuen.com`；行為不變。

## 逼問紀錄

- 問：主機與對外方式？／答（書，使用者轉貼）：Apple Silicon、Docker Compose、cloudflared 指向 nginx:80／因此：映像檔要 arm64、主機不開 port。
- 問（agent 代決）：排程放哪？／答：獨立的 `scheduler` container，跟 backend 同映像檔、用 supercronic／因此：backend 重啟不影響排程，時間表跟 `deploy/crontab` 一致。
- 問（agent 代決）：上傳檔案的 volume？／答：程式沒有上傳功能（沒有 FileField／MEDIA），不做；資料庫、備份、紀錄各一個 .env 路徑。
- 問（agent 代決）：ARM64 怎麼驗？／答：本機沒有 Docker，改用 GitHub Actions 的 `ubuntu-24.04-arm` 原生機器整套建起來測（repo 是公開的，免費）。
- 誰看得到、誰能改：不涉及（沒有新的資料或欄位）。

## 需求細節

- `server/Dockerfile`（context＝repo 根目錄，帶 crawler/ 與 deploy/ 的排程腳本）、`web/Dockerfile`、`compose.yaml`、`.env.example`、`docker/`（nginx、crontab、entrypoint、README）。
- 服務：db（postgres:16-alpine）、backend、web、nginx、scheduler、cloudflared（profile `tunnel`）。
- `.env` 路徑變數：`PG_DATA_DIR`、`BACKUP_DIR_HOST`、`LOG_DIR_HOST`。
- 對外只有 cloudflared；nginx 只綁 `127.0.0.1:8080` 供本機測試。
- `.github/workflows/docker.yml`：x86 與 ARM64 各跑一次整套。
- 自動更新（使用者 2026-11-27 追加：「要自動更新」）：`updater` 服務（profile `autoupdate`）每 5 分鐘看 GitHub 的 `prod`，有新版就 git 快轉並 `docker compose up -d --build` 重建其他服務；本機有改過的檔案或分岔時停下不更新。書那邊不用給任何人主機權限。
- 不改產品程式行為。
- 欄位權限：不涉及。

## 條件確認

不適用：沒有改變資料出現或消失的條件，只是換一種方式把既有程式跑起來。

## 數字口徑

不適用：沒有新的數字。

## 這次可能會弄壞什麼

- W1 既有的主機直裝部署（`deploy/`）：這次只新增檔案、`deploy/run-job.sh`／`backup-db.sh` 照原樣被 container 引用，不能改壞主機版的排程。

## 驗收標準

- [ ] W1 `deploy/` 的檔案沒有改動（diff 只有新增檔案與 `.gitignore`）。
- [ ] GitHub Actions 在 x86 與 ARM64 兩台都綠：全部服務 healthy、經 nginx 打首頁／API／管理後台／靜態檔都 200、登入 CSRF 正確、後端測試在 PostgreSQL 上全過、排程 container 備份成功。
- [ ] CI 的自動更新測試：退回上一個 commit 後 updater 會快轉到最新、重建後首頁與 API 仍 200；已是最新時再跑不做事。
- [ ] 書的主機上 `docker compose up -d --build` 起得來，`https://npofile.leekuen.com` 開得到。

## 邊界（明確不做什麼）

- 不改產品程式；不做上傳檔案的 volume（沒有這功能）。
- 不替書或使用者建立 Cloudflare Tunnel（要在使用者的 Cloudflare 帳號操作）。
- 不搬資料庫（說明寫在 docker/README.md，由有權限的人做）。

## 開發備註（/dev 填寫）

- supercronic v0.2.51（2026-10-21）、cloudflared 2026.11.0（2026-11-12），版本與 supercronic 的 SHA1 寫死在檔案裡。
- 後端映像檔用 `python:3.12-slim-trixie`：Debian trixie 的 postgresql-client 是 17 版，pg_dump 可以備份 16 版的資料庫（bookworm 的 15 版不行）。
- 走查（HTTP 腳本）W1 `git diff origin/stage -- deploy/` 沒有輸出（主機版部署檔沒動，container 只是引用 run-job.sh、backup-db.sh）。
- CI 驗收（2026-11-27，run 45963324143）：`ubuntu-24.04-arm` 與 `ubuntu-24.04` 都綠。ARM64 那台 backend／web container 都是 aarch64；經 nginx 打 `/`、`/login`、`/api/stats`、`/admin/login/`、`/static/admin/css/base.css` 都 200；登入 API 帶 CSRF token 回 invalid_credentials、不帶回 403；`manage.py test` 97 個在 PostgreSQL 上全過；scheduler 跑 backup 產生 88KB、24 張表的 dump。第一次 run 因為沒開 tunnel 也要求 CLOUDFLARE_TUNNEL_TOKEN 而失敗，已改成選填。
- CI 驗收（2026-11-27，run 45964803471，x86 與 ARM64 都綠）自動更新：ARM64 那台退回 127ff94 後 updater 偵測到 31953af、重建並重啟 db／backend／web／nginx／scheduler（19 秒）、HEAD 快轉到最新，之後首頁與 `/api/stats` 200；已是最新時再跑不做事。
