# NPOFile 前台（Next.js）。支援 linux/amd64 與 linux/arm64（Apple Silicon）。
#   docker build web/
# API_BASE 在建置時寫進 /api/* 的轉址設定，執行時給伺服器端取資料用；compose 裡是 http://backend:8000。
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG API_BASE=http://backend:8000
ENV API_BASE=$API_BASE NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 TZ=Asia/Taipei
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund && npm cache clean --force
COPY --from=build /app/.next ./.next
COPY --from=build /app/next.config.ts ./next.config.ts
ARG API_BASE=http://backend:8000
ENV API_BASE=$API_BASE
USER node
EXPOSE 3000
CMD ["npx", "next", "start", "-H", "0.0.0.0", "-p", "3000"]
