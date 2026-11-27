# CLAUDE.md

**先讀 [AGENTS.md](AGENTS.md)** — 本 repo 唯一工程契約（技術棧、目錄分層、核心原則、
加功能流程、必跑驗證、嚴禁事項）。本檔只放 Claude Code 專屬行為與路由，規則本體不重複寫。

## 首次使用（模板尚未初始化時）

根目錄存在 `.template-uninitialized` → 每個新 session 一律先走**首次使用引導**：
白話介紹框架 → AskUserQuestion 問是否開始初始化 → 讀 `.agents/skills/setup/SKILL.md`
以精靈流程完成專案設定。初始化完成前不進行任何產品開發。
（SessionStart hook 會自動注入此規則；標記檔由 setup 在收尾時刪除。）

## Session 開始（已初始化後）：先當 Team Leader

每個新 session 的第一個回應：team-leader 簡報（hook 已注入狀態就直接沿用、不重跑指令）
→ 從第一句話判斷入口（pm / dev / framework），簡報最後一行用白話講出入口與接下來要做什麼，
接著讀 `.agents/skills/<入口>/SKILL.md` 直接開始。**簡報無例外**；**入口不問**，
只有沒有任務（只打招呼）或分不出要改功能還是改協作規則時才用 AskUserQuestion 問。
判斷順序與例外（上線／部署直接照 AGENTS.md「分支與出貨流程」與「部署」）見 team-leader skill 步驟 3。
**恢復／壓縮後接續的對話不算新 session**：不重做簡報、不重新判斷入口，沿用已在用的入口，
hook 附上的即時狀態只當「這段時間變了什麼」的參考。

## 三入口與鐵則

- **pm** — 給不懂 code 的 PM/案主：討論需求（必問誰用/目的/驗收/邊界/誰看得到誰能改（全新的東西））、開票、
  也能由 agent 主導白話開發出貨。
- **dev** — 給工程師：依票開發，先查架構/功能/資安衝突。
- **framework** — 改協作框架本身：豁免功能票，但必寫 `docs/FRAMEWORK.md` 決策紀錄＋bump 版號。
- **無票不開發**：產品程式碼（`scripts/framework-config.sh` 的 `PRODUCT_DIRS`）的行為變更
  必須有 `tickets/` 的票，PreToolUse 閘門會機制化攔截；被擋時走開票流程，不繞過。
- **一 session 一工作區**：使用者可能同時開多條 session。開發前先 `make worktree n=<票號>`
  進自己的隔離工作區，**主目錄只做合流**（merge／push／盯部署），不在主目錄開發或 `checkout -b`
  ——同一棵工作樹被兩條 session 寫，會互相掃掉未提交的工作。收工 `make worktree-clean n=<票號>`。
  票的 `depends` 有還沒進 stage 的票時，從它的分支開（`base=origin/<那條分支>`），不叫使用者等它上 stage
  （做法與併 stage 前的檢查見 `tickets/README.md`〈相依的票〉）。
- **在別的工作樹做事，就要在那裡重跑一次簡報**：`scripts/agent-status.sh` 會 `cd` 到**自己所屬的 repo**，
  所以開場 hook 報的永遠是 session 根目錄那一棵。拿根目錄的簡報當另一棵樹的現況，會落後整合分支而不自知，
  一路做到合流才炸出票號或版號撞號。**換工作樹＝換現況，簡報要重跑。**
- **動畫面前先套 `ui-design` skill**：寫入畫面檔（`scripts/framework-config.sh` 的 `UI_PATH_GLOBS`）前
  必須先啟動 `ui-design` skill，PreToolUse 閘門會擋（確非設計工作時 `touch cache/ui-design-override` 放行、事後刪）。
  啟動時會印 🎨 banner 留痕。
- **問非工程師取捨題、規則題，用他看得到的情境命名**（哪一筆、會交給誰、對方看到什麼），不用演算法或統計術語，
  有兩種意思的詞先講清楚；做法見 `grilling` skill〈本 repo 補充（非原文）〉。
  （這條放在本檔而不是 AGENTS.md：Claude 每個 session 必載入的只有本檔。）
- 詳細規則：`tickets/README.md`、AGENTS.md「Ticket 工作流」與「git 波及範圍」、`docs/FRAMEWORK.md`。

## 給使用者的流程提醒（省 token；框架 v5.2.0）

使用者希望在這些時機被提醒（回覆最後一句話，只提醒、不替他決定；同一條 session 同一種提醒只說一次）：

- **一張票合進 stage 或上 prod 之後**：建議另開新的 session 做下一張——對話越長，之後每一步都越貴；票、分支、SPEC 都在 repo 裡，換 session 不會丟進度。
- **同一條 session 已做完第二張票，或對話被自動壓縮過**：建議另開，或打 `/compact`。
- **接下來是例行工作**（合流、跑抓取、改文字、照定案的票實作）：可以在模型選單換成 Sonnet 或 Haiku，設計規則、找問題時再換回來。
- **要確認好幾張票的條件時**：一次列完，請他一次回（例：「LK-18 全部同意、LK-21 同意」），不要分好幾輪問。
- **要開新票時**：`make new-ticket` 會列出標題相近的既有票，先看是不是同一件事、或該接在舊票上。

自己也照做：走查確認文字與數字用讀頁面文字，只有版面問題才截圖；長輸出先存檔再挑要看的行。

## 掛載的 hooks（由 harness 強制，非建議）

SessionStart 注入開場規則與即時狀態；PreToolUse 有六道閘門：票務（無票不開發）、畫面（先套 `ui-design`）、示意圖文字、
推送前同步（落後就擋）、git 波及範圍（擋整批提交與 `HEAD~n`）、檢查管線（檢查指令不接管線）。**被擋時照訊息做，不繞過。**
另有版控內的 `.githooks/`（每個 clone 跑一次 `make hooks`）。每一道的細節：`docs/harness/hooks-and-agents.md`。

## Agent 制度檔（docs/harness/）

- 派 subagent 前、卡住、收尾、該不該問人 → `docs/harness/dispatch.md`（單一主檔，附案例來歷）
- 派工 prompt → `docs/harness/templates/`（search/implement/refactor/research/review）填空
- 想改制度檔 → 先讀 `docs/harness/maintenance.md`；可機制化清單 `docs/harness/sensors-backlog.md`；
  完整論述在 `docs/harness/archive/`

30 秒版：大量讀取/掃描/批次改檔派 subagent、派工附三件套（目標動機/驗收/回報格式）、
完成要 fresh-context 驗收＋證據、錯兩輪就升級或問人、對外/不可逆動作先問。

skills 由 harness 自動從 `.claude/skills/` 列出（不在此重複）；canonical 在 `.agents/skills/`，
改 workflow 先改 canonical 再同步 adapter。

## 自訂 subagent（`.claude/agents/`）

subagent 是獨立 context 的全新實例（「fresh eye」只有它做得到），**但每派一次約十幾萬 token**，照各規則的門檻派、不多派。
`spec-adversary`（票寫好、動工前找洞）、`fresh-eye-ux-auditor`（交圖前，預設最多一輪：`ui-design`〈示意圖〉第 13 條）、
`breaker`＋`qa-architect`（測試計畫寫好後）、`skill-change-proofreader`、`adversarial-reviewer`（框架大改才派：framework SKILL〈2. 討論〉）。
用法、迭代方式（「幫我把這個 agent retro 一下」）見 `docs/harness/hooks-and-agents.md`。

## 常用指令

```
make worktree n=TK-12      # 開隔離工作區（開發前必做；主目錄只做合流）
make worktree n=TK-13 base=origin/feature/TK-12   # 票 depends 的票還沒進 stage：從它的分支開（tickets/README〈相依的票〉）
python3 scripts/branch_tickets.py <分支> <票號…>   # 這條分支會帶上 stage 的提交，分屬哪幾張票（併 stage 前看有沒有別張票）
make worktree-list         # 看有幾條 session 在跑、各自什麼狀態
make worktree-clean n=…    # 收掉用完的（n=--merged 先預覽已合流的，照它印的指令加 --yes 才真的收）
make ticket-handoff to=TK-12 t="TK-12 TK-14"   # 把票搬進開發工作區並領票（同一條線的多張票放同一棵）
make new-ticket t="短題" r="角色"   # 開新票（先 fetch 遠端再取號防撞號）
make next-framework-version   # 框架版號取號（先問遠端；level=patch｜major）
make check          # 框架一致性檢查（票務 lint＋框架工具自己的測試；專案檢查由 setup 補上）。輸出不要接管線
make ticket-lint    # 只跑票務 lint 與框架工具測試
make confirm-lint   # 合流前先查：票的〈條件確認〉〈數字口徑〉確認了沒（推 stage 才不會被擋）
make walkthrough-lint   # 合流前先查：票的走查紀錄（W 編號）交代齊了沒
make confirm-lint-prod t="TK-12 TK-13"   # 上 prod 前查：這次上線的票在 origin/stage 上確認了沒
make hooks          # 啟用 .githooks/（每個 clone 一次；之後開發分支 commit 會自動推，stage/prod 不推）
./scripts/agent-status.sh   # 入口簡報用的一次性狀態快照（換工作樹要在那一棵重跑）
```

```
make setup-dev                       # 第一次：後端 venv＋套件＋資料庫、前台套件（之後複製 server/.env.example 成 server/.env）
server/.venv/Scripts/python server/manage.py runserver 127.0.0.1:8000   # 後端＋管理後台 http://127.0.0.1:8000/admin/
npm --prefix web run dev             # 前台 http://localhost:3000（/api/* 轉給後端）
server/.venv/Scripts/python server/manage.py crawl fia               # 匯入財政部非營利名冊（約十萬筆）
server/.venv/Scripts/python server/manage.py crawl mohw --limit 50   # 抓公益勸募團體（每秒一個請求）
server/.venv/Scripts/python server/manage.py crawl mohw_activities --limit 20          # 近 5 年勸募活動＋捐贈人清冊：接著上次進度、只抓新的與有變的（--limit 算活動數；後台「每次最多跑幾分鐘」預設 120）
server/.venv/Scripts/python server/manage.py crawl mohw_activities --group 7210       # 只抓指定團體（網址 fundgroupDetails/ 後的數字）
server/.venv/Scripts/python server/manage.py match_companies --limit 200   # 企業捐款人對商工登記統編（名稱完全相同才連；捐得多的先查）
server/.venv/Scripts/python server/manage.py group_companies --limit 500    # 集團歸戶：查董監事（每家每月一次、捐得多的先查）再依法人董事重新歸戶（--limit 0 只重新歸戶）
server/.venv/Scripts/python server/manage.py reclassify_donors             # 分類規則改了之後重新分類（管理員指定過的不動）
server/.venv/Scripts/python server/manage.py merge_donors                  # 捐款人名稱規則改了之後：同一位的不同寫法（台／臺、空白、(股)）合成一筆（migrate 時也會跑）
server/.venv/Scripts/python server/manage.py classify_orgs                 # 依 orgs/taxonomy.py 重算組織的領域與服務對象（管理員修正的不動）
server/.venv/Scripts/python server/manage.py recompute_scores        # 重算揭露指數（「近五年」隨日期移動，每天跑）
make test-crawler / make test-server / make lint-web / make build-web
```
（macOS／Linux 把 `Scripts/python` 換成 `bin/python`。）
