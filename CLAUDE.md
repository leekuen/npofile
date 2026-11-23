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

## 掛載的 hooks（由 harness 強制，非建議；設定在 .claude/settings.json）

- SessionStart：`scripts/session-start-hook.sh` 注入開場規則與即時狀態
  （未初始化時改注入首次使用引導；恢復／壓縮後改注入「接續中的 session」提示）。
- PreToolUse 票務閘門：`scripts/ticket-gate-hook.sh`——tickets/ 無「待開發/開發中」
  票時，產品程式碼的檔案修改**直接被擋**（無票不開發）。被擋時不要繞過：
  回報使用者並走開票流程。
- PreToolUse 畫面閘門：`scripts/ui-design-gate-hook.sh`——本 session 還沒啟動過 `ui-design` skill 就寫畫面檔會被擋
  （`scripts/ui-design-mark-hook.sh` 在 skill 啟動時留標記）。
- PreToolUse 示意圖文字閘門：`scripts/mockup-text-gate-hook.sh`——第一次寫 `cache/demos/` 的示意圖時，
  先把「這句話在做什麼工作」分類表推到眼前，看過才放行。
- PreToolUse 遠端同步閘門：`scripts/git-sync-gate-hook.sh`——`git push` 前 fetch，
  本地落後遠端就**擋下**，要求先 `git pull --rebase origin <分支>` 整合再推。
  被擋時照訊息先 pull --rebase、當場解衝突、重跑檢查，再推。
- PreToolUse git 波及範圍閘門：`scripts/git-scope-gate-hook.sh`——擋整批提交（`git add -A`／`.`／資料夾、
  `git commit -a`）與用 `HEAD^`／`HEAD~n` 做的 `reset`／`revert`／`rebase`；擋下時會說怎麼改寫。
- PreToolUse 檢查管線閘門：`scripts/check-pipe-gate-hook.sh`——`NO_PIPE_COMMANDS` 列的檢查指令後面接管線
  （`| tail` 之類）會被擋：結束碼會變成後面那個指令的，失敗被吞掉。

另有版控內的 git hooks（`.githooks/`：commit 前擋衝突標記、推 `stage`／`prod` 前跑通用關卡、
開發分支 commit 後自動推）——**每個 clone 跑一次 `make hooks` 才生效**，沒跑就沒有這幾道。

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

**skill 跟 subagent 不一樣**：skill 跑在主對話的 context 裡（看得見整段對話，好處是知道脈絡、
壞處是被脈絡帶偏）；subagent 是**獨立 context 的全新實例**，可並行、可限制工具、可指定模型。
**「fresh eye」這個性質只有 subagent 做得到**——skill 看得見主對話已經下過的所有結論，包括錯的。

檔案就是全部：`.claude/agents/<name>.md`（專案層，進 git）。**不做 canonical/adapter 兩份**
（理由見 `docs/FRAMEWORK.md` 決策紀錄）。模板附六個：

| 檔名 | 暱稱 | 什麼時候派 |
|---|---|---|
| `spec-adversary` | 規格審查師 | 票寫好、還沒動工時，找票裡沒抓到的洞 |
| `fresh-eye-ux-auditor` | Fresh-eye UX Auditor | 設計圖／UI 使用體驗／文案定案前（交圖前**自己派、照複雜度分級**：`ui-design`〈示意圖〉第 13 條） |
| `breaker` | 測試計畫審查師（破壞法） | 測試計畫寫好後，先攻擊再比對 |
| `qa-architect` | 測試覆蓋審查師（盤點法） | 同上，與 breaker 互補、一起派 |
| `skill-change-proofreader` | Skill 變更校對者 | 沉澱完、一批 skill／agent 改動要出貨前（**校對不是對抗審查**） |
| `adversarial-reviewer` | 提案審查師 | 提案、框架變更、檢討拿給使用者拍板前；落地後併 stage 前對照提案再審（prompt 寫法見 framework SKILL〈怎麼派對抗審查〉） |

**迭代方式**：用完直接說「幫我把這個 agent retro 一下然後優化它」——
改的是那個檔案，並在檔頭的版本註解區塊留下「改了什麼、為什麼」（版本註解就是它的訓練紀錄，不另建 eval）。
每個檔案裡最重要的是**「讓它有效的那一句」**（例如 `breaker` 的「第一階段不准看測試計畫」）
——那是它價值的來源，retro 時主要就是在改那一句。

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

{{專案常用指令（起環境、測試、部署等），setup 初始化時填寫。}}
