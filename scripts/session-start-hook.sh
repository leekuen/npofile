#!/usr/bin/env bash
# SessionStart hook：每個 session 開始（新開、/clear、恢復、壓縮後接續）由 harness 強制執行。
# 三種模式：
# 1. 恢復／壓縮後接續（stdin 的 source 是 resume 或 compact）→ 只注入「這不是新 session」與即時狀態，
#    不重做簡報、不重新判斷入口（源專案 v4.78.0：長對話每壓縮一次就重問一次入口）。
# 2. 模板尚未初始化（存在 .template-uninitialized）→ 注入「首次使用引導」規則，
#    帶新使用者走 setup 入口完成專案設定。
# 3. 已初始化的新 session → 注入「開場規則 + 專案即時狀態」：第一個回應一定是 team-leader 簡報，
#    入口從第一句話判斷、不問（源專案 v4.98.0）。
# 由 .claude/settings.json 的 hooks.SessionStart 呼叫（不設 matcher，四種來源都要跑）。
set -uo pipefail
cd "$(dirname "$0")/.."

# 這棵工作樹的 agent 記憶接回主目錄那一份（有接或失敗才出聲；腳本不在就跳過）
[ -x ./scripts/ensure-agent-memory.sh ] && { ./scripts/ensure-agent-memory.sh 2>&1 || true; }

SOURCE=""
# 手動在終端機跑時 stdin 是 tty，不讀（不然會卡著等輸入）
[ -t 0 ] || SOURCE=$(python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("source",""))
except Exception: print("")' 2>/dev/null || true)

if [ "$SOURCE" = "resume" ] || [ "$SOURCE" = "compact" ]; then
  cat <<'EOF'
=== 接續中的 session（恢復／壓縮後）===
這不是新 session：**不要**重做 team-leader 簡報、**不要**再問要進哪個入口，
沿用本 session 已經在用的入口與任務，直接接著做。
下方即時狀態只當「這段時間有什麼變了」的參考——有別條 session 動到你正在做的東西
（例：同一個檔案、同一張票、已經先併進整合分支），先講一句再繼續。
EOF
  if [ -f .template-uninitialized ]; then
    echo "（模板尚未初始化：setup 精靈做到一半就接著做完，不要重頭歡迎一次。）"
  fi
  echo "=== 專案即時狀態 ==="
  ./scripts/agent-status.sh
  exit 0
fi

if [ -f .template-uninitialized ]; then
  cat <<'EOF'
=== 首次使用引導（強制，無例外） ===
這是尚未初始化的「Agent 協作開發框架模板」。本 session 的第一個回應，
不論使用者打了什麼，一律：
1. 歡迎使用者，用 5 行內白話介紹這個框架是什麼：
   角色入口（pm / dev / framework）＋ 功能票驅動開發（無票不開發，hook 強制）
   ＋ SPEC 單一事實來源 ＋ 每次變更留痕。
2. 用 AskUserQuestion 問「要現在開始初始化嗎？」（開始初始化 / 先了解框架再說）。
3. 選「開始初始化」→ 讀 .agents/skills/setup/SKILL.md，照精靈流程逐步引導；
   選「先了解」→ 白話導覽 README.md 與 docs/FRAMEWORK.md 的重點，隨時可回到初始化。
初始化完成前不進行任何產品開發；不要跳過引導直接執行使用者的其他任務
（可先記下任務，初始化完成後再處理）。
EOF
  exit 0
fi

cat <<'EOF'
=== Session 開場規則（強制） ===
本 session 的第一個回應，不論使用者打了什麼（打招呼、提問、甚至明確指定任務），一律：
1. 以 team-leader 身分產出「專案現況簡報」（直接用下方即時狀態，不要重跑 agent-status.sh）。
2. 從第一句話判斷入口，不用 AskUserQuestion 問，照順序：
   ① 指定了入口（「dev 入口」「/pm」「（入口：pm）」）就照寫的；單獨的 dev、pm 字樣不算
   ② 上線／部署類任務（只限把做好的東西送上去）→ 不進入口，直接照 AGENTS.md「分支與出貨流程」「部署」做
      （專案有部署 skill 就讀它）；夾著要新做或要改的功能，照 ③～⑤
   ③ 跟本 repo 無關、或改個人設定（~/.claude/、CLAUDE.local.md、.claude/settings.local.json）→ 不進入口，直接做
   ④ 要改本 repo 的協作方式（.agents/skills/、.claude/agents/、.claude/settings.json、scripts/*-hook.sh、.githooks/、開場、票的流程、AGENTS.md／CLAUDE.md 規則）→ framework
   ⑤ 其他 → pm；沒寫入口的「開發 <票號>」也進 pm，票是待開發／開發中就從 pm〈5.〉開始、不重新 grill，
      動工前照常問「現在開發？還是先留著？」
   同一句話有兩段 → 依序走，最後一行講清楚哪段走哪個入口。
   只有沒有任務（只打招呼）、或分不出要改功能還是改協作規則時，才用 AskUserQuestion 問。
3. 簡報最後一行寫「用〈入口〉入口：接下來〈白話寫要做什麼〉。不對請直接說。」
   （不進入口的寫「照部署流程：…」「不進入口：…」），接著讀該入口的 SKILL.md、帶著任務直接開始，不等回覆。
   使用者說判斷錯了 → 換讀那個入口的 SKILL.md 接著做，不重做簡報。
詳細流程見 .agents/skills/team-leader/SKILL.md。
=== 專案即時狀態 ===
EOF
./scripts/agent-status.sh
