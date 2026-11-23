#!/usr/bin/env bash
# framework-config.sh — 框架的專案層設定（由 setup 入口在初始化時填寫）。
# 所有框架腳本（agent-status / 各閘門 hook / ticket-lint / session-start / worktree 工具）都 source 這份，
# 專案差異只改這裡，不改腳本本體。
#
# 分支模型（`stage` 整合分支、`prod` 正式分支）是框架契約，不在這裡設定——見 AGENTS.md「分支與出貨流程」。

# 專案名稱（顯示於簡報）
PROJECT_NAME="（未初始化——請走 setup 入口）"

# 票號舊制前綴（凍結）：既有 <前綴>-XXXX 票沿用此值過 lint，不再發新號。
# 新票一律「作者前綴」（源專案 v4.11.0）：每個 clone 設一次
#   git config ticket.prefix AMY
# 多人平行開票各有獨立號碼空間，結構上不撞號；詳見 tickets/README.md。
TICKET_PREFIX="TK"

# 票的新規則從哪一天開的票開始套用（比對票 frontmatter 的 created，YYYY-MM-DD）：
# 〈這次可能會弄壞什麼〉W 編號、〈走查〉逐條交代、〈條件確認〉〈數字口徑〉等框架 v5.0.0 起的檢查，
# 只查 created 在這一天（含）之後的票——舊票不回頭補。
# - 新專案：保持預設（＝所有票都套用）。留空也視為全部套用。
# - 從 v4.x 升級的既有專案：改成升級當天的日期（舊票沒有那些段落，不改會整批紅）。
TICKET_RULES_SINCE="2000-01-01"

# 產品程式碼目錄（相對 repo 根目錄）：「無票不開發」閘門的守備範圍。
# 空陣列 = 閘門不擋任何路徑（初始化前的暫時狀態；setup 會要求填寫）。
PRODUCT_DIRS=()

# 畫面層檔案（相對 repo 根目錄的 shell 樣式，`*` 會跨目錄比對整段路徑）：
# 「動 UI 前先套 ui-design skill」閘門的守備範圍（源專案 v4.6.0 的 hook，這裡改成可設定）。
# 例：UI_PATH_GLOBS=("web/*.tsx" "web/*.jsx" "app/*.vue" "server/templates/*.html")
# 空陣列 = 閘門不擋（專案沒有畫面、或還沒決定範圍時）。
UI_PATH_GLOBS=()

# 開新工作區（make worktree）時，要從主目錄原樣複製過去的「不進版控」檔案
# （相對 repo 根目錄的 shell 樣式；例：WORKTREE_COPY_GLOBS=(".env" "config/local.*.json")）。
# 腳本只複製、不打開內容。空陣列 = 不複製。
WORKTREE_COPY_GLOBS=()

# 「檢查指令不准接管線」閘門的守備範圍：這些指令後面接 `| tail` 之類會吞掉失敗的結束碼
# （源專案 v4.90.0）。寫指令開頭即可，比對時以詞為單位。
# 專案自己的檢查指令（例："npm test" "pytest"）由 setup／framework 入口補進來。
NO_PIPE_COMMANDS=("make check" "make ticket-lint")

# 本機健康檢查 URL（agent-status 簡報用；留空 = 跳過健康檢查）
HEALTH_URL=""
