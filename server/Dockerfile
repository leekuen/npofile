# NPOFile 後端（Django＋gunicorn），也當排程 container（supercronic）的映像檔。
# build context 是 repo 根目錄（要一起帶 crawler/ 與 deploy/ 的排程腳本）：
#   docker build -f server/Dockerfile .
# 支援 linux/amd64 與 linux/arm64（Apple Silicon）。
FROM python:3.12-slim-trixie

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Taipei

# postgresql-client：備份用的 pg_dump／pg_restore（trixie 是 17 版，可以備份 16 版的資料庫）
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client curl tzdata \
 && rm -rf /var/lib/apt/lists/*

# supercronic：給 container 用的 cron（環境變數照常傳得進去、輸出到 stdout）
ARG TARGETARCH
ARG SUPERCRONIC_VERSION=v0.2.51
RUN set -eu; \
    case "${TARGETARCH:-amd64}" in \
      amd64) sha=1692066e350a88ff4d7d6474fe3c7a6c41ec5e89 ;; \
      arm64) sha=9d4c2000493215a1898502b2fc2dada3e8ea8c7a ;; \
      *) echo "不支援的架構：$TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSLo /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH:-amd64}"; \
    echo "${sha}  /usr/local/bin/supercronic" | sha1sum -c -; \
    chmod +x /usr/local/bin/supercronic

RUN useradd --create-home --uid 1000 app

# 先裝套件（requirements 沒變就用快取）；-e ../crawler 是相對 server/ 的路徑
COPY crawler /app/crawler
COPY server/requirements.txt /app/server/requirements.txt
WORKDIR /app/server
RUN pip install -r requirements.txt

COPY server /app/server
COPY deploy/run-job.sh deploy/backup-db.sh /app/deploy/
COPY docker/crontab docker/entrypoint.sh /app/docker/
RUN chmod +x /app/deploy/*.sh /app/docker/entrypoint.sh \
 && mkdir -p /app/server/staticfiles /backups /logs \
 && chown -R app:app /app /backups /logs

EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "npofile.wsgi", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-"]
