# FRAMEWORK.md — Agent 協作框架（總覽 + 決策紀錄）

> **框架版本：v5.0.1**（版號規則見 §2.9；此為單一事實來源，`scripts/agent-status.sh` 簡報會讀這裡）
>
> 本檔記錄**協作框架本身**：角色入口怎麼設計、為什麼這樣設計、歷次變更。
> 框架的變更由 `framework` 入口討論與落地（豁免功能票）；每次變更**必須**同時
> (1) bump 上面的版號、(2) 在 §3 決策紀錄補一列（版號 / 日期 / 改了什麼 / 為什麼）。
> 產品功能的規格請看 `docs/SPEC.md`；工程規範請看 `AGENTS.md`。

## 1. 框架總覽

```
新對話開始
   │（模板未初始化 → 先進 [setup] 初始化精靈，完成後才有下面的流程）
   ▼
[team-leader] 專案現況簡報（SPEC 狀態 / ticket 看板 / 分支環境 / 平行現場）
   │            └─ 從第一句話判斷入口，簡報最後一行講出入口與接下來要做什麼（不問；判斷不出來才問）
   │
   ├─→ [pm]        非工程師入口（不懂 code 的 PM/案主）：先 grill，再確認五件事
   │                （誰用/目的/驗收/邊界/誰看得到誰能改）→ 開票 tickets/（規劃只住在票裡，不動 SPEC）；
   │                使用者要的話 agent 主導、白話幫他開發並上實機
   │                討論過程與 demo 素材 → cache/（不進 git）
   │
   ├─→ [dev]       工程師入口：無票不開發 → 衝突/資安檢查 → 實作 → 驗證與走查 → 推進票況
   │
   │   ↑ pm 與 dev 能力相同（都先開票、共用「分支與出貨流程」）；差在使用者是誰與呈現方式。
   │   共用出貨流程：make worktree n=<票號>（自己的隔離工作區，從最新 origin/stage 開 feature/<票號>）
   │     → 依票實作 → 檢查綠燈 → 走查 → 問使用者 → 在主目錄 merge 回 stage（同一次寫 SPEC）
   │     → 實機測試 → 驗收 → make worktree-clean
   │
   └─→ [framework] 框架入口：討論與修改框架本身（入口、規則、資料夾約定）
                    → 提案拍板前先派對抗審查 → 落地後在本檔決策紀錄補一列（豁免票）
                    → 併 stage 前對照提案再審一次；動到 skill／agent 檔的另派校對者
```

### 資料夾與規則檔的分工

| 位置 | 進 git | 角色 |
|------|:------:|------|
| `AGENTS.md` | ✅ | 唯一工程契約（規範「必須怎麼做」；`{{…}}` 佔位符由 setup 填寫） |
| `CLAUDE.md` | ✅ | Claude Code 入口行為（session 開始先 team-leader）與 adapter 說明 |
| `.agents/skills/` | ✅ | 所有角色入口與工作流的 canonical（單一來源） |
| `.claude/skills/` | ✅ | Claude Code adapter，只指回 canonical，不放第二套邏輯 |
| `.claude/agents/` | ✅ | 自訂審查 subagent（規格、測試計畫、畫面與文案、框架提案、skill 校對）；一個檔就是全部，不分 canonical／adapter |
| `.claude/settings.json` | ✅ | Claude Code hooks（開場簡報與六道閘門）與權限 |
| `.githooks/` | ✅ | 版控內的 git hooks；每個 clone 跑一次 `make hooks` 才生效（選用） |
| `scripts/framework-config.sh` | ✅ | 專案層設定（專案名、舊制票號前綴、產品目錄、畫面檔樣式、開工作區要複製的本機檔案、不准接管線的檢查指令、健康檢查 URL） |
| `.template-uninitialized` | ✅ | 模板未初始化標記；存在時 SessionStart 導向 setup，由 setup 刪除 |
| `tickets/` | ✅ | 功能票（產品開發唯一依據；還沒上 `stage` 的規劃只住在這裡） |
| `docs/SPEC.md` | ✅ | 產品「目前實際行為」單一事實來源（寫點在合流 `stage`） |
| `docs/FRAMEWORK.md` | ✅ | 框架設計與決策紀錄（本檔） |
| `docs/harness/` | ✅ | agent 派工制度（門檻、模板、判準、可機制化清單） |
| `.claude/worktrees/` | ❌ | 各條 session 的隔離工作區（`make worktree` 開、`make worktree-clean` 收） |
| `cache/` | ❌ | 戰情資料（PM 討論過程、demo 素材、示意圖 `cache/demos/`），可隨時丟棄——所以收工作區前要先搶救（`worktree-clean` 會做） |

### Harness 原語對照（為什麼入口用 skill 做）

| 原語 | 特性 | 本框架的用法 |
|------|------|--------------|
| Skill（slash command） | 載入主對話、可互動提問；**看得見整段對話** | 角色入口（pm/dev/framework/team-leader）＋ setup 精靈（都需要來回討論）；`ui-design`／`ux-writing`／`user-walkthrough`／`grilling` 等工作流 |
| Subagent（Agent 工具，背景執行） | 獨立 context、跑完自動通知、不可互動 | 長任務背景執行——唯讀調查、demo 素材（pm）、依票實作於隔離 worktree（dev）；進行中每回合回報一行狀態 |
| 自訂 subagent（`.claude/agents/`） | 獨立 context 的**全新實例**，看不到主對話已經下過的結論（包括錯的） | 審查與校對——「fresh eye」這個性質只有它做得到。每個檔裡最重要的是「讓它有效的那一句」 |
| CLAUDE.md 指令 | 每 session 自動載入 | 觸發「開場先 team-leader / 未初始化先 setup」；只有 Claude 每次必讀的規則才放這裡 |
| Hook（Claude Code） | 工具呼叫前後的攔截 | SessionStart（開場規則與即時狀態；恢復／壓縮後改注入「接續中的 session」；未初始化改注入 setup 引導）＋ PreToolUse 六道閘門（票務、畫面、示意圖文字、git 同步、git 波及範圍、檢查管線） |
| git hook（`.githooks/`） | 跟用哪個 agent 無關；每個 clone 要自己啟用 | commit 前擋衝突標記、推 `stage`／`prod` 前跑通用關卡、開發分支 commit 後自動推（選用，`make hooks`） |

## 2. 框架規則摘要

1. **入口紀律**：新 session 先 team-leader 簡報，**無例外**（SessionStart hook 會注入開場規則與即時狀態，
   簡報直接沿用、不重跑指令）。接著**從第一句話判斷入口**（pm / dev / framework），簡報最後一行用白話講出
   入口與接下來要做什麼，然後直接開始——**不問**。只有沒有任務（只打招呼）、或分不出要改功能還是改協作規則時，
   才用 AskUserQuestion 問。上線／部署的請求不算入口，直接照 AGENTS.md「分支與出貨流程」與「部署」。
   - **恢復／壓縮後接續的對話不算新 session**：不重做簡報、不重新判斷入口，沿用已在用的入口。
   - **換工作樹＝換現況**：開場 hook 報的是 session 根目錄那一棵；到別棵工作樹做事，
     就在那裡重跑一次 `scripts/agent-status.sh`。
   - **任何入口（pm / dev / framework）被進入時，都要先回報專案現況**（壓縮版 ≤10 行，帶角色視角）；
     本對話已簡報過則改 3 行內差異更新。
2. **無票不開發**（產品程式碼）：新功能 / 行為修改必須有 `tickets/` 的票；純問答、調查、不改行為的救火豁免。
   由 PreToolUse hook（`scripts/ticket-gate-hook.sh`）**機制化強制**：無「待開發/開發中」票時，
   `PRODUCT_DIRS` 內的檔案寫入直接被擋；救火經使用者同意後以 `cache/hotfix-override` 暫時放行，事後補票。
   **閘門認得工作區**：工作區的名稱是票號時，只看**那一張票**是不是待開發／開發中
   （別張票在開發中不算數）；主目錄與不是用票號命名的工作區維持「有任何一張就放行」。
   票的格式與一致性由 `scripts/ticket-lint.sh` 檢查（`make ticket-lint`，含在 `make check`）。
3. **PM 必問五件事**：誰使用、目的、驗收標準、邊界、誰看得到／誰能改（最後一件在全新的頁面、區塊或欄位時問）
   ——沒確認不開票。需求一進來先 grill；問取捨題、規則題時用對方看得到的情境命名，不用演算法或統計術語。
   **PM 入口也能實際開發**（給不懂 code 的人用，agent 主導、白話回報），但**開發前一樣先開票**，
   無票不開發不豁免；pm 與 dev 差在使用者是誰與呈現方式，不在能力。
4. **票三態**：待開發 → 開發中 → 完成（作廢標記不刪檔）。開票一律用 `make new-ticket`
   （`scripts/new-ticket.sh`：先問遠端、也掃這台機器上其他工作區再取號，防撞號；不手寫票檔、不自己取號）；
   多 session 平行以**領票制**協作（標「開發中」同時填 `owner`，他人票不碰，見 `tickets/README.md`）。
   票之間有先後就寫 `depends`：那張還沒進 `stage` 時，從它的分支開工作區，不叫使用者等
   （`tickets/README.md`〈相依的票〉）；同一條線的幾張票放同一個工作區（`make ticket-handoff`）。
5. **兩道確認閘**：開票後→問「現在開發嗎？」同意才動工；檢查綠燈後→問「上實機嗎？」
   同意才 merge/push/部署。授權單次有效，不跨票、不跨回合延續。
   （開發分支的自動推送不在這道閘內：它只在啟用 `make hooks` 後才有，而且永遠不碰 `stage`／`prod`，見第 19 點。）
6. **框架變更豁免票**：走 framework 入口討論確認後直接改，但**必須**在本檔決策紀錄留痕。
   框架變更也在自己的工作區做（`make worktree n=FW-<短名>`）。審查有固定的三個點，都是流程文字、沒有 hook 發動：
   提案拿給使用者拍板前派 `adversarial-reviewer` 審提案；落地後、併 `stage` 前拿已審的提案與 diff 再審一次；
   這一批動到 skill 或 subagent 檔時，另派 `skill-change-proofreader` 校對（校對不是對抗審查，兩者不互相取代）。
   純錯字、只動決策紀錄那一列不必派。
7. **canonical/adapter 一致**：改工作流先改 `.agents/skills/`，再確認 `.claude/skills/` adapter 與
   CLAUDE.md / README / team-leader 入口清單同步。**自訂 subagent（`.claude/agents/`）不分兩份**：
   一個檔就是全部。skill 的 adapter 可以只寫「去讀 canonical」，因為那段字載進主對話、再由主對話去讀；
   subagent 的檔案內文就是它的系統提示，做成指標會讓它第一件事變成「去讀另一個檔」，多一步而且會失敗。
   其他工具把那個檔的內文貼進派工 prompt 即可。
8. **長任務走背景 subagent**：大範圍調查、demo 素材、已開票的長實作（限隔離 worktree）
   派背景 subagent 執行，主對話不中斷。任務描述必須自包含（subagent 中途不能提問）；
   進行中每回合開頭回報一行狀態，完成/失敗自動彙報；「無票不開發」同樣約束 subagent，
   實作結果由主對話驗證（run-checks）與驗收後才合回，票況與 SPEC 由主對話推進。
   背景任務同時 ≤3 個；subagent 的回報是主張不是證據，結論要自己重新驗過。
   派工門檻、模型調度、驗證判準見 `docs/harness/dispatch.md`。
9. **框架版號（semver）**：每次框架變更**必須** bump 檔頭「框架版本」並於 §3 補一列（含版號欄）。
   - **MAJOR**：不相容變更——移除/改寫入口、推翻既有規則、改變資料夾契約。
   - **MINOR**：新增能力——新入口、新機制/腳本、新規則（不破壞既有）。
   - **PATCH**：修 bug、文字、微調（不改行為契約）。
   一次涵蓋多項變更時，取最高等級 bump 一次；各項在 §3 分列、共用該版號。
   **取號用 `make next-framework-version`**（先問遠端所有分支再給下一號；預設 MINOR，`level=patch`／`level=major`）
   ——不讀本機檔頭自己加一，別條 session 可能已經佔走那個號、只是還沒合進來。
   （**專案初始化（setup 填佔位符）不 bump**：屬專案設定，非框架變更，但在 §3 留一列。）
10. **分支與出貨流程**（pm/dev 共用，細節見 AGENTS.md「分支與出貨流程」、權威分支定義見 CONTRIBUTING.md
    「分支即環境」）：開發一律在自己的工作區——`make worktree n=<票號>` 從最新 `origin/stage` 開
    `feature/<票號>` 到 `.claude/worktrees/<票號>/`；判斷可實機測試時**先問使用者**，
    同意後**在主目錄** merge 回 `stage`（同一次把變更寫進 `docs/SPEC.md`），在實機環境驗收，驗收後收掉工作區。
    分支模型：`stage` 整合分支、`prod` production。進 stage/prod 與部署都是對外動作，先確認。
11. **模板初始化（setup）**：`.template-uninitialized` 存在時，SessionStart hook 導向 setup 精靈；
    setup 只填佔位符與 `framework-config.sh`，不改框架規則；收尾刪除標記、在 §3 留痕（不 bump）。
12. **一 session 一工作區**：同一台機器同時開幾條 session 是常態，而同一棵工作樹被兩條 session 寫，
    會互相掃掉未提交的工作。所以**開發一律在自己的工作區，主目錄固定停在 `stage`、只做合流**
    （merge／push／盯部署），不在主目錄開發或 `checkout -b`；工作區裡也不要 checkout `stage`（會把它佔住）。
    開場簡報的「平行現場」列出每個工作區的狀態，並直接寫出使用者可以說的話。
    收工 `make worktree-clean n=<票號>`（整批收已合流的：`n=--merged` 先預覽，確定再照它印的指令加 `--yes`）；
    刪之前腳本會先把那個工作區 `cache/` 裡不進版控的東西搶救回主目錄。
    宣告收尾時要列出查了哪幾項、各是誰的——不是自己起的不要關，先問。
13. **git 波及範圍**（平行多 session 的鐵則，全文見 AGENTS.md 同名一節）：(1) 提交指名到檔案，
    不用 `git add -A`／`.`／資料夾、不用 `git commit -a`；(2) 跨工作樹用絕對路徑；
    (3) `reset`／`revert`／`rebase` 指名 commit 雜湊，不用 `HEAD^`／`HEAD~n`；
    (4) 解衝突時自己沒改過的檔案一律取對方的；(5) 取號（票號、框架版號）先問遠端。
    1 與 3 由 PreToolUse hook（`scripts/git-scope-gate-hook.sh`）機制化強制，
    確有必要時 `touch cache/git-scope-override` 放行一次、事後刪；2、4 擋不住，只能靠規則本身。
14. **SPEC 的寫點在合流 `stage`**：`docs/SPEC.md` 只記使用者現在真的看得到的行為，
    在合流 `stage` 的那一次依票的開發備註寫進去；開票階段與 feature 分支都不動它，規劃只住在票裡。
    理由：它是多條 session 最大的衝突熱點，合流時才寫，天然只有一個寫入者。動工前先讀 SPEC 對焦既有行為，這一點不變。
15. **使用者看得到的東西有三道關**：
    - 寫入畫面檔（`framework-config.sh` 的 `UI_PATH_GLOBS`）前先啟動 `ui-design` skill，
      由 PreToolUse hook（`scripts/ui-design-gate-hook.sh`）擋；確非設計工作時 `touch cache/ui-design-override` 放行、事後刪。
    - 示意圖（`cache/demos/`）上的說明文字另有一道閘門（`scripts/mockup-text-gate-hook.sh`）：
      先逐句分類「這句話在做什麼工作」再寫。
    - 檢查綠燈後、回報使用者前照 `user-walkthrough` 走查：開工就宣告走哪一級，回報標憑據型態
      （真人眼看／腳本／HTML 檢查）；沒走成的固定寫三行——沒走的是／為什麼／誰該補走。判準以該 skill 為準。
16. **票的結構與合流前檢查**：票除了必問的五件事，還有幾個固定段落各管一種會漏的東西——
    〈逼問紀錄〉（grill 的結論）、「欄位權限：」一行（AGENTS.md〈沒權限的欄位，哪裡都不出現〉）、
    〈條件確認〉（篩選與可見性的條件，逐條有人確認過才算數）、〈數字口徑〉、
    〈這次可能會弄壞什麼〉的 W 編號（每一條在走查紀錄裡都要被點名）。格式見 `tickets/README.md`。
    推 `stage` 前跑 `make confirm-lint`（條件確認了沒）與 `make walkthrough-lint`（走查紀錄交代齊了沒），
    上 `prod` 前跑 `make confirm-lint-prod t="<票號…>"`（讀 `origin/stage` 上的票）；
    啟用 `make hooks` 後，推 `stage` 由 pre-push 自動跑前兩項（推 `prod` 只自動擋衝突標記與 bash 3.2 寫法）。
17. **審查用自訂 subagent**（`.claude/agents/`，清單與派工時機見 CLAUDE.md）：票寫好未動工派 `spec-adversary`；
    畫面與文案定案前派 `fresh-eye-ux-auditor`；測試計畫寫好後 `breaker` 與 `qa-architect` 一起派；
    框架這邊見第 6 點。它們都只讀不改、產出是清單——逐條複驗成立才改。
    迭代方式是用完就在同一個對話請 agent 回顧並改那個檔，檔頭版本註解留下改了什麼、為什麼；不另建 eval。
    skill 與 subagent 檔跟 AGENTS.md 牴觸時停下來回報，不自己選一邊。
18. **檢查輸出不接管線**：`framework-config.sh` 的 `NO_PIPE_COMMANDS` 列的檢查指令後面接 `| tail`／`| head`／`| grep`
    時，結束碼會變成後面那個指令的、失敗被吞掉，由 PreToolUse hook（`scripts/check-pipe-gate-hook.sh`）擋；
    要看尾段就先導到檔案再讀。`OK (skipped=N)` 不等於全過，回報要講跳過幾條、為什麼。
    合流後的檢查由做合流的那條 session 跑。新加的檢查要植入一個錯誤證明它真的會紅——只會綠的檢查比沒有更糟。
19. **git hooks 是選用的**（`.githooks/`，每個 clone 跑一次 `make hooks` 才生效）：
    commit 前擋沒解乾淨的合併衝突標記；推 `stage`／`prod` 前跑通用關卡（第 16 點的兩支檢查等）；
    開發分支每次 commit 後自動推到遠端——別條 session、別的協作者取票號與版號時才看得到正在做的東西
    （永遠不推 `stage`／`prod`／`main`／`master`；沒有 remote 就不做）。
    不啟用時這三件事都沒有：推之前自己跑 `make check`，推 `stage` 前另外跑 `make confirm-lint` 與 `make walkthrough-lint`
    （`make check` 不查推送範圍內的條件確認與走查紀錄）；走網頁 PR 合併時 pre-push 也不會跑，同樣要先手動跑。

## 3. 決策紀錄（changelog）

> 新版在上。每列：版號 / 日期 / 改了什麼 / 為什麼。版號規則見 §2.9。

| 版號 | 日期 | 決策（改了什麼） | 原因（為什麼） |
|------|------|------|------|
| v5.0.1 | 2026-11-27 | **修正三個寫檔閘門在 Windows（Git Bash/MSYS）上完全不擋的 bug**：`ticket-gate-hook.sh`／`ui-design-gate-hook.sh`／`mockup-text-gate-hook.sh` 都用 `ROOT="$(cd .. && pwd)"` 算主目錄、再跟 harness 傳進來的 `file_path` 做字首比對；但 Git Bash 的 `pwd` 回傳 posix 式路徑（`/c/...`），harness 寫入的 `file_path` 是 Windows 式（`C:\...`），兩邊字串對不上，`case "$FILE_PATH" in "$ROOT"/*)` 恆假，三個閘門因而對任何檔案都放行。修法：ROOT 改用 `pwd -W`（Git Bash 專有，印 Windows 式路徑；非 Windows 平台這個選項不存在、指令失敗會自動退回原本的 `pwd`，不影響 macOS/Linux），FILE_PATH 讀出來後把反斜線正規化成正斜線（三支腳本原本的 case 樣式與字首比對都假設正斜線）。同一次順手修好「框架的 `python3` 呼叫在 Windows 上解析到 Windows Store 的別名樁、叫不到真正 Python」——這是本機層級的問題（建議每個 Windows clone 各自在 `~/bin/python3` 建一個轉給 `python` 的 shim，不改框架腳本）。驗證：`scripts/worktree-gates-test.sh` 原本 20/43 條假綠（該擋的全部沒擋），修完 43/43 全線；用「故意改壞看會不會紅」驗證過修法本身有在起作用。**已知但這次沒修**：同樣在這台機器上，`git-sync-gate-test.sh` 17 條新冒出來的失敗（python3 真的能跑之後才浮現），初步追查像是測試腳本自己組 payload 時（`command` 字串內嵌路徑 vs 純路徑的 `cwd`）被 MSYS 的 argv 路徑轉換不一致地改寫，比較像測試腳本的假象、還不確定是真的機制 bug；留給下一次 framework 入口專門查。 | 這個專案的使用者在 Windows + Git Bash 上做 setup 時，`make check` 紅燈牽出來的；三個閘門「看起來裝好了、其實什麼都不擋」是會讓人誤以為有保護、實際上無票也能改產品程式碼的真實風險，優先度高於照表操課留到別次 framework 入口才修 |
| v5.0.0 | 2026-11-27 | **專案初始化（setup）**：模板走過 setup 入口的初始化精靈，變成「非營利檔案 NPOFile」——讓大眾查得到非營利組織的受捐紀錄、資金來源（財閥／金主）與受裁罰紀錄的公開透明平台。代填：`AGENTS.md`／`docs/SPEC.md`／`README.md`／`docs/harness/templates/implement.md` 的佔位符（技術棧：前端 Next.js、後端 Python FastAPI/Django 待定、PostgreSQL、Python 爬蟲模組；目錄分層 `web/`／`server/`／`crawler/`）；`scripts/framework-config.sh`（`PROJECT_NAME`／`PRODUCT_DIRS`／`UI_PATH_GLOBS`／`WORKTREE_COPY_GLOBS`）；`.gitignore` 補 Next.js 產物；git remote（`origin` 改名 `template` 保留拉框架更新的能力，新增使用者自己的 `origin`）、票號前綴（`git config ticket.prefix`，只存在這份 clone）、啟用 `make hooks`；刪除 `.template-uninitialized`。不 bump 版號——這是專案設定，不是框架變更。 | setup 入口的收尾規則：填佔位符與專案層設定屬於「把模板變成使用者的專案」，不算框架規則變更，所以照 `.agents/skills/setup/SKILL.md` 第 4 節的要求補一列紀錄但不動版號 |
| v5.0.0 | 2026-11-23 | **回港源專案（baojay）v4.13.0–v5.46.0 的通用框架改進**（去產品化後移植；逐條對照源專案 146 列決策紀錄，分可帶／概念可帶機制綁專案／不帶三類）：(1) **開場與入口**——入口不問、從第一句話判斷（v4.98.0）；恢復／壓縮後接續不算新 session（v4.78.0）；換工作樹要重跑簡報（v4.20.0）；部署任務不算入口（v4.90.0）。(2) **平行多 session**——一 session 一工作區、主目錄只做合流（v4.14.0／v4.19.0）：`make worktree`／`worktree-list`／`worktree-clean`（收之前先搶救 `cache/` 到 `cache/rescued/`，v5.21.0）、`make ticket-handoff`（v4.81.0／v5.25.0）、相依的票 `depends`＋`scripts/branch_tickets.py`（v5.16.0）、agent 記憶接回主目錄（v4.51.0）、開場簡報的平行現場與落後警示（v4.17.0／v4.20.0／v4.22.0）、ticket gate 認得工作區（v4.76.0）、git 波及範圍五條＋`git-scope-gate-hook.sh`（v4.29.0／v4.45.0／v4.78.0）、git 同步閘門量實際推的那一棵（v4.19.1）、取號先問遠端並掃其他工作區（v4.45.0／v4.55.0／v4.70.0／v4.94.1）、`make next-framework-version`（v4.45.0）。(3) **票的結構與票務 lint**——〈逼問紀錄〉（v4.76.0）、「欄位權限：」一行與必問第五件事「誰看得到、誰能改」（v5.37.0／v5.42.0）、〈條件確認〉（v5.5.0／v5.27.0／v5.41.0，附 `.agents/skills/pm/condition-checklist.html`）、〈數字口徑〉（v5.19.0）、〈這次可能會弄壞什麼〉W 編號（v4.74.0 起、v5.30.0 每個 W 都要點名）；新規則只套用 `TICKET_RULES_SINCE` 當天及之後建立的票。(4) **SPEC 改在合流整合分支那一次寫**（v4.27.0）。(5) **走查制度**——三級＋四題、動工前宣告讀取方與級別、走不了就跳過＋〈跳過之後怎麼做〉固定格式、三種紀錄寫法、憑據型態、三型環境、收尾盤點、「不能按」用計算後樣式量外觀、設計圖交圖前真點走過、卡登入先請人代登（v4.15.0–v5.35.0）。(6) **自訂 subagent**——`.claude/agents/` 六個通用審查 agent 單檔（v4.39.0；校對者 v4.48.0、fresh-eye 鐵律 7 v4.72.0、先聲明看得到的範圍 v4.54.0、對抗審查兩個時間點與派法 v5.17.0／v5.22.0）。(7) **ui-design 拆成核心＋`references/`**（v4.97.0）與示意圖規則、「做在真頁面還是先出圖」等通則；ux-writing 心法 8–13（v4.13.0 起）。(8) **run-checks**——檢查輸出不接管線＋`check-pipe-gate-hook.sh`（v4.90.0）、`skipped=N` 要回報（v4.85.0／v5.39.0）、三層測試與合流後由合流那條 session 跑（v5.20.0）、假綠比假紅嚴重（v4.32.0）。(9) `docs/harness/` 派工、審查型 agent 行數例外、案例與 `templates/implement.md`〈共通規則〉（v4.21.0–v5.25.0）。(10) grilling〈本 repo 補充（非原文）〉（v5.36.1）。(11) pm 文件類需求多問讀者、批次回饋仍須問在哪頁給誰、一次開發兩張以上（v4.78.0／v4.90.0／v5.25.0）。(12) **版控 git hooks（選用，`make hooks` 啟用）**——pre-commit 擋衝突標記、pre-push 推 `stage` 時跑衝突標記／走查交代／條件確認／bash 3.2 寫法四道關卡（推 `prod` 跑衝突標記與 bash 3.2），post-commit 自動推開發分支（`stage`／`prod`／`main`／`master` 不推）；`make dup-lint`（v4.8.0／v4.14.0／v4.86.0／v5.12.0／v5.30.0／v5.39.0／v5.41.0）。**推翻 v4.2.0 的兩項「不帶入」**：v4.6.0 的 ui-design 閘門本體改帶入（畫面層路徑改由 `UI_PATH_GLOBS` 設定，空的就不擋）；v4.8.0 的自動推送改帶入但**選用**（沒跑 `make hooks` 就沒有）。**模板內補的**（源專案沒有）：git 同步閘門認得 `git -C`／`cd <路徑>` 與它的測試、閘門接線檢查 `hooks-wiring-lint.sh`＋測試、管線閘門與波及範圍閘門的邊角、`new-worktree.sh --no-track` 與 `WORKTREE_COPY_GLOBS`（只複製檔案、不收絕對路徑與 ..）、`next-framework-version.sh` 不認得的參數回 2、記憶資料夾名英數以外全換成 -（實測底線也會被換）、三個生效日併成 `TICKET_RULES_SINCE`＋格式檢查、`make confirm-lint-prod`（上 prod 前讀 `origin/stage` 的票）、沒有遠端的專案 `make confirm-lint`／`make walkthrough-lint` 改跟本機 `stage` 比、`setup-hooks.sh` 不蓋掉既有的 `core.hooksPath`、bash 3.2／複製檔兩支 lint 的測試、git hooks 沙盒測試，以及突變測試找出來後補的 20 條案例（含源專案一條永遠紅不了的合併提交案例）。**不帶入**：deploy-safely 與所有綁技術棧的 skill、測試環境槽位與 `make env*`、唯讀資料庫通道、CI runner 工具、測試資料庫範本、模擬器焦點閘門、env／ERD／後端格式的 pre-push 關卡、migration lint、挑票上 prod 與上線紀錄制度、AI 小幫手審查 agent 與知識庫、報表匯出決定表、App 版號／熱更新、各外部服務整合，以及綁後台框架的 ui-design 段落（v5.6.0、v5.10.0 其餘、v5.24.0、v5.26.0、v5.28.0、v5.31.0、v5.32.0、v5.43.0）。`.claude/settings.json` 允許清單新增 `make confirm-lint`、`make walkthrough-lint`、`make dup-lint`、`make next-framework-version`、`make worktree-list`；`.gitignore` 的複製檔樣式維持註解（選用）。**模板內驗證**：`make check` 綠（ticket-tools 150、worktree-gates 43、git-sync 63、hooks-wiring 21、git-scope 59、check-pipe 119、walkthrough-record 41、stage-confirm 49、conflict-marker 47、worktree-clean 70、ticket-handoff 14、branch-tickets 48、next-framework-version 24、git-hooks 210、repo-lints 66），全部在 macOS 內建 bash 3.2、只有系統 PATH 下跑；突變測試（故意改壞被測程式看測試會不會紅）共 303 條，抓到 300 條，沒抓到的 3 條是改了行為不變（ticket-lint 遠端比對欄位數門檻、ticket-handoff 找來源時跳過目標）或走不到的防呆（new-ticket 檔案已存在）；開工作區、記憶接回、開場簡報、新分支第一次推不被同步閘門擋另在沙盒 repo 實跑 16 項，沒有遠端時兩項合流前檢查擋得到、補好會過另實跑 5 項；交付前派兩批 skill 校對與一次對抗審查，必改的都已修。MAJOR：入口規則、SPEC 寫點與開發流程（一 session 一工作區）改變 | 使用者要求把源專案演進出的框架更新蒸餾回模板；照 v4.1.0 起的移植方法論——逐條對照決策紀錄，只移植通用能力、產品內容一律不帶，來歷標「源專案」；這一段源專案最大的教訓是「同時開很多條 session」與「看起來綠但其實沒在檢查」，所以除了搬規則，每一道閘門與工具都補上會紅的測試，並用突變測試驗證測試本身 |
| v4.2.0 | 2026-08-14 | **回港源專案（baojay）v4.3.0–v4.12.1 的通用框架改進**（去產品化後移植）：(1) **四個通用 skill**——`ui-design`（v4.3.0 通用 UI/UX 檢查清單＋v4.10.0 輸入元件一致性四規則；來源專案的 PreToolUse 閘門因畫面層路徑依專案而異，模板不帶 hook、SKILL 內留機制化備忘）、`ux-writing`（v4.4.0 繁中 UX Writing：心法／標點／盤古之白／範例庫＋v4.5.0「套用即揭露」；術語表去產品化為「由專案自己累積」的空表＋示範列）、`grilling`（v4.7.0 vendored，MIT © Matt Pocock；pm 開票前必跑）、`user-walkthrough`（v4.12.0 真人操作走查；接進 dev 出貨流程「綠燈後、回報前必過」）；(2) **pm 開票前先 grill**（v4.7.0）——需求一進來先用 Skill 工具啟動 grilling 逼問一輪，共識再收斂到四件事；(3) **票號改作者前綴**（v4.11.0）——`git config ticket.prefix` 每 clone 一次、流水號只在自己前綴裡遞增（撞號是取號與推送間的競爭條件，fetch 再勤也看不到彼此；作者前綴讓取號不需要與任何人協調）；舊制 `TICKET_PREFIX`-XXXX 凍結、lint 兩制並收；`new-ticket.sh` 同步帶入 **fetch 全部遠端分支**（v4.8.0，只掃整合分支會看不到別人 feature 分支上的票）；agent-status／ticket-gate 的票 glob 改前綴無關；(4) **票務工具自動化測試**（v4.12.1）——`scripts/ticket-tools-test.sh` 九測項（未設前綴要擋／同前綴遞增／號碼空間獨立／id×檔名不一致／id 重複且錯誤路徑不炸／舊制相容…）掛進 `make ticket-lint`，「守規則的工具自己也要有測試」。**不帶入**：v4.9.0（Django migration lint 與 line-messaging，stack/產品綁定）、v4.6.0 的 hook 本體（畫面層路徑產品綁定，降級為 SKILL 內備忘）、v4.8.0 的 commit 自動推送 hook（部署拓樸綁定）。模板內驗證：ticket-lint OK、ticket-tools-test 9/9 過。MINOR：新增能力，不破壞既有 | 使用者要求把源專案演進出的框架更新與 skills 同步上模板 repo；照 v4.1.0 建立的移植方法論——逐條對照決策紀錄，只移植通用能力、產品內容一律不帶，來歷保留標「源專案」 |
| v4.1.0 | 2026-07-17 | **回港源專案（baojay）v3.2.0–v4.2.1 的通用框架改進**（去產品化後移植）：(1) **領票制**（源 v3.2.0）——票 frontmatter 加 `owner`、他人開發中票不碰、ticket-lint 對「開發中缺 owner」warn 不擋、agent-status 簡報顯示 owner、tickets/README 補「多 session 平行協作」；(2) **兩道確認閘**（源 v3.3.0）——開票後必問「現在開發嗎？」、綠燈後必問「上實機嗎？」，授權單次有效不跨票；入 pm/dev SKILL、AGENTS.md 嚴禁清單、§2 規則 5、sensors-backlog 機制化備忘；(3) **開票先 fetch 再取號**（源 v4.2.0+v4.2.1）——新增 `scripts/new-ticket.sh`（改讀 framework-config 的 `TICKET_PREFIX`，含 v4.2.1 的 `${VAR}` 大括號修正）＋ `make new-ticket`；(4) tickets/README 補「有 CI 就把 `make check` 掛進 CI」通用建議（源 v4.1.0 的 CI 強制在模板無 CI 可掛，降級為建議、由 setup/framework 入口落地）。**不帶入**源專案 v4.0.0「App-only/Web-admin 平台範圍」（產品決策）與所有 stack 綁定內容。連動同步：README「30 秒版」補領票制與兩道確認閘、`.claude/settings.json` 允許清單加 `make new-ticket`、§2.8→§2.9 引用更新。MINOR：新增機制與規則，不破壞既有 | 使用者要求把源專案演進出的新版框架同步回模板；逐條對照兩邊 FRAMEWORK.md 決策紀錄，只移植通用框架能力、產品內容一律不帶 |
| v4.0.0 | 2026-07-07 | **模板化（template 化）**：(1) 剝離源專案（baojay）的全部業務程式碼、票、stack 綁定文件與 git 歷史，框架改為 stack 無關；(2) 目錄壓平成單一 repo（原「工作區＋專案子目錄」兩層併一層，hooks 路徑改 `$CLAUDE_PROJECT_DIR/scripts/`）；(3) 專案差異外部化到 `scripts/framework-config.sh`（專案名/票號前綴/產品目錄/健康檢查 URL），四支框架腳本改讀設定不寫死；(4) 新增 **setup 入口**（初始化精靈）＋ `.template-uninitialized` 標記：未初始化時 SessionStart hook 改注入首次使用引導，setup 問 5 組問題代填 AGENTS.md 佔位符與設定，收尾刪標記；(5) AGENTS.md 改為含 `{{…}}` 佔位符的骨架，stack 綁定 skills（add-*/deploy-safely/troubleshoot）移除、run-checks 改為由 setup 填寫的佔位版。MAJOR：移除入口、改變資料夾契約 | 使用者要把源專案的協作框架做成可發布的 template：業務程式碼是客戶 IP 不能散布；stack 綁定會限縮適用面；新使用者需要被引導而不是自己讀文件——用既有原語（skill + SessionStart hook + 標記檔）實作首次使用引導，不發明新機制 |
| — | 2026-07-02 ~ 07-04 | **前史（v1.0.0–v3.1.0，源專案 baojay）**：三角色入口以 skill 實作、每 session 開場簡報（SessionStart hook 強制）、無票不開發（PreToolUse hook 機制化）＋ ticket-lint、PM 升級為非工程師開發代理（能力=dev、差在呈現）、分支即環境出貨流程、框架版號制度、背景 subagent、harness 制度檔（dispatch/templates/sensors/maintenance）、git 同步閘門。完整決策表見 `docs/harness/archive/FRAMEWORK-history.md` | 每條規則的「為什麼」都來自源專案的真實踩坑（假設角色致重構、push 成功但 CD 失敗、平行開發互相覆蓋等）；歷史保留供翻舊帳，本表只留摘要 |
