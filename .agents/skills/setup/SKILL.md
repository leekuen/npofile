---
name: setup
description: 模板初始化精靈（首次使用引導）：把框架模板變成使用者自己的專案——設定專案名稱、技術棧、票號前綴、產品目錄、檢查指令，代填 AGENTS.md / SPEC / framework-config，最後移除未初始化標記。當專案根目錄還有 .template-uninitialized、或使用者說「初始化模板 / 開始設定 / setup」時使用。
---

# setup 入口（模板初始化精靈）

你的對象是**第一次拿到這個框架模板的人**，可能不懂 code。目標：15 分鐘內把模板變成
他的專案。全程白話、一次只問一組問題（用 AskUserQuestion）、每步做完就回報做了什麼。

## 0. 檢查狀態與預告

- 根目錄**沒有** `.template-uninitialized` → 已初始化過，告知並改走 team-leader 開場。
- 有 → 先預告流程：「我會問你 5 組問題，然後代你填好所有設定檔；之後每個新對話
  都會自動看到專案簡報。答不出來的都可以先跳過。」

## 1. 逐組提問（AskUserQuestion，一組一問，都可跳過）

1. **專案名稱與一句話定位**：叫什麼？給誰用、解決什麼問題？
   （→ AGENTS.md「這是什麼」、docs/SPEC.md「產品概述」、README.md 標題）
2. **技術棧**：後端 / 前端 / Mobile 各用什麼？還沒定就標「未定」
   （之後走 framework 入口補；→ AGENTS.md「技術棧」「目錄分層」）。
3. **產品程式碼放哪裡**（一組三小題，後兩題你先照技術棧擬好答案、請使用者點頭即可）：
   - 程式碼會放在哪些資料夾（例：server、web、src）？
     （→ framework-config `PRODUCT_DIRS`，這是「無票不開發」閘門的守備範圍——
     沒填閘門不會擋任何檔案，務必說明這個影響）
   - 哪些檔案是「使用者看得到的畫面」（例：`web/` 底下的 `.tsx`、`server/templates/` 底下的 `.html`）？
     （→ `UI_PATH_GLOBS`，「動畫面前先套 ui-design」閘門的守備範圍；沒有畫面或還沒定就留空，閘門不擋）
   - 有沒有「不進版控、但少了它程式跑不起來」的本機檔案（例：`.env`）？
     （→ `WORKTREE_COPY_GLOBS`：開新工作區時自動從主目錄複製過去；腳本只複製、不打開內容。
     **你也不要打開這些檔案讀**——只記檔名樣式）
4. **票號前綴與使用者角色**：
   - 你自己的票號前綴：2～8 個大寫字母或數字、字母開頭（例：AMY）。每個人各用各的，
     多人同時開票不會撞號（→ 對使用者說明後執行 `git config ticket.prefix <前綴>`，只存在這份 clone、不進版控；
     其他協作者各自在自己的 clone 設一次）。
   - 產品有哪些使用者角色（例：顧客 / 店員 / 管理員）？（→ tickets/README.md 範例、docs/SPEC.md「主要角色」）
   - `TICKET_PREFIX` 是舊制全域前綴（凍結，只為了讓既有的舊票過 lint）；新專案保持預設即可，不用問。
5. **檢查指令**：lint / test / build 怎麼跑？有健康檢查 URL 嗎？沒有就跳過
   （→ `.agents/skills/run-checks/SKILL.md`、Makefile `check`、`HEALTH_URL`；
   同一批指令也寫進 `NO_PIPE_COMMANDS`——這些指令後面接 `| tail` 之類會把失敗吞掉，閘門會擋）。

## 2. 代填（逐檔落地，白話回報每一項）

- `scripts/framework-config.sh`：PROJECT_NAME / PRODUCT_DIRS / UI_PATH_GLOBS / WORKTREE_COPY_GLOBS /
  NO_PIPE_COMMANDS / HEALTH_URL。`TICKET_RULES_SINCE` 新專案保持預設（所有票都套用新規則）；
  **從舊版框架升級的既有專案**才改成升級當天的日期（舊票沒有新段落，不改會整批紅）。
- `AGENTS.md`：把所有 `{{…}}` 佔位區塊換成使用者的答案；答不出的留
  `{{TODO：…}}` 並在回報中列出。
- `docs/harness/templates/implement.md`：〈共通規則〉最後那個 `{{…}}`（專案的測試與環境指令）照同樣方式填。
- `docs/SPEC.md`：產品概述（一句話定位、主要角色）；功能總覽表保持空白（開發時再長）。
- `README.md`：把「（未初始化）」的專案段換成專案名稱與定位。
- `.agents/skills/run-checks/SKILL.md` 與 `Makefile`：填實際檢查指令；沒有就留 TODO。
- 檢查 `.gitignore` 是否涵蓋使用者技術棧的常見產物（node_modules、venv、.env 實檔等），
  缺就補。`.claude/worktrees/`（平行工作區）與 `cache/` 已經在裡面，不要拿掉。
  順口問一句：這個資料夾有沒有放在雲端同步（iCloud／Dropbox／OneDrive）裡？有 → 把 `.gitignore`
  最後那段「同步工具產生的重複檔」四行取消註解，並說明代價（「步驟 1.png」這種檔名會進不了版控）。

## 3. git（對外動作，先確認再做）

- 沒有 `.git` → 問是否 `git init`（建議做，框架的票務與留痕都靠版控）。
- 問是否要設 remote；使用者沒有就跳過，不要催。
- 分支：框架約定 `stage` 是整合分支、`prod` 是正式分支（`AGENTS.md`「分支與出貨流程」）。
  新 repo 沒有 `stage` 就問是否把目前分支改名或另開一條；不要自己決定。
- **問是否啟用 git hooks**（`make hooks`，每個 clone 跑一次）。用白話講清楚啟用後會多三件事，再讓使用者選：
  1. commit 前擋掉沒解乾淨的合併衝突標記；
  2. 推 `stage`／`prod` 前先跑一輪本機檢查（票的走查交代、條件確認、衝突標記等），沒過會擋；
  3. **開發分支每次 commit 後自動推到遠端**（`stage`、`prod` 永遠不會自動推）——
     好處是別條 session、別的協作者取票號與版號時看得到你正在做的東西，不會撞號；
     代價是還沒做完的東西也會出現在遠端。沒有 remote 時這一項自動不做。
  使用者不想自動推 → 不跑 `make hooks`，並說明：這樣前兩項也不會有，推之前要自己跑 `make check`，
  推 `stage` 前另外跑 `make confirm-lint` 與 `make walkthrough-lint`（`make check` 不查這兩項）。

## 4. 收尾（缺一不算完成）

1. 刪除 `.template-uninitialized`。
2. `docs/FRAMEWORK.md` §3 決策紀錄補一列「專案初始化（setup）」——**不 bump 版號**
   （填佔位符屬專案設定，不是框架變更）。
3. 跑 `make check`（**輸出不要接管線**），紅燈就照訊息修到綠燈；修不了的列進第 6 點。
4. 建議 commit：`chore: 初始化專案（from agent framework template）`（先問再 commit）。
5. 收尾引導（白話）：「設定完成。之後每個新對話會自動出現專案簡報，並從你的第一句話判斷要走哪個入口
   （討論需求、開票、做功能走 pm；改協作規則走 framework）。現在可以直接跟我說你要做的第一個功能，
   我會幫你確認需求、開票、開發。」
6. 有跳過的項目 → 明列清單與補法（framework 入口 / 直接改 framework-config）。

## 紀律

- 答不出的一律可跳過、標 TODO，不擋初始化完成；但要講清楚跳過的影響
  （尤其 PRODUCT_DIRS 沒填 = 票務閘門不設防）。
- 只填佔位符與專案設定，**不趁機改框架規則**；使用者想改規則 → 引導 framework 入口。
- 每一步用「發生什麼事、對你有什麼影響」的白話回報，不丟術語。
- 初始化是在主目錄直接做的（這時還沒有票、也還沒有工作區）；**初始化完成後**的開發才走
  「一 session 一工作區」（`make worktree n=<票號>`）。
