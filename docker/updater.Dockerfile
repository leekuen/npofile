# 自動更新服務：docker CLI（含 compose plugin）＋ git。支援 linux/amd64 與 linux/arm64。
FROM docker:29.8-cli
RUN apk add --no-cache git tzdata
ENV TZ=Asia/Taipei
