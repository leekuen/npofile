# Agent 協作開發框架模板

> 給「用 AI Agent 開發軟體」的個人與小團隊：一套**角色入口 + 功能票 + 機制化閘門**的
> 協作框架，讓不懂 code 的案主/PM 和工程師共用同一個 repo、同一套規則，
> 而且規則靠 hook 強制執行，不靠自律。

**目前專案**：（未初始化——第一次用 Claude Code 開啟本資料夾時，會自動進入初始化引導。）

**框架版本**：見 [docs/FRAMEWORK.md](docs/FRAMEWORK.md) 檔頭（版號只記在那裡）；每一版改了什麼、為什麼改，見同檔 §3 決策紀錄。

---

## 這個框架解決什麼問題

VibeCoding 常見的坑：agent 假設需求就動工、改 A 壞 B 沒人發現、「能跑」就當「能上線」、
討論結論散落對話裡下次全忘、同時開幾個對話互相蓋掉對方的東西。本框架的對策：

| 機制 | 對策 |
|------|------|
| **無票不開發**（hook 強制） | 沒有確認過「誰用/目的/驗收/邊界/誰看得到誰能改」的功能票，產品程式碼直接改不動 |
| **SPEC 單一事實來源** | 系統現在做什麼全記在 `docs/SPEC.md`，動工前先讀、合流整合分支時同步 |
| **角色入口** | 案主走 pm（全程白話）、工程師走 dev（工程語言），能力相同、守門相同；入口從第一句話判斷，不用選 |
| **一 session 一工作區**（腳本＋hook） | 同時開幾個對話也不互踩：各自在隔離工作區開發，主目錄只做合流；整批提交、相對指法的回退會被擋 |
| **真人操作走查** | 檢查綠燈之後再照使用者的過程走一遍；走多深依風險分級，沒走成要照固定格式講清楚 |
| **fresh-eye 審查** | 規格、測試計畫、畫面與文案、框架提案，各有一個獨立 context 的審查 subagent（`.claude/agents/`） |
| **每次變更留痕** | 框架規則變更記 `docs/FRAMEWORK.md`（帶版號），功能變更記票與 SPEC |
| **開場簡報**（hook 強制） | 每個新對話自動報告專案現況與平行現場，不用問「上次做到哪」 |
| **票先問清楚再動工** | 票裡有〈逼問紀錄〉、〈條件確認〉（每條篩選條件符合幾筆、擋掉幾筆，要使用者點頭）、〈數字口徑〉（報表的數字怎麼算）、〈這次可能會弄壞什麼〉（W 編號，每一條都要交代驗過沒） |
| **合流前、上線前的檢查** | `make confirm-lint`／`make walkthrough-lint` 查條件確認了沒、W 編號交代了沒；`make confirm-lint-prod` 上 prod 前再查一次 |
| **檢查不會假綠** | 檢查輸出接 `\| tail` 這類管線會把失敗吞掉，hook 直接擋；框架自己的每一道閘門都有測試，且用突變測試（故意改壞看測試會不會紅）驗過 |
| **選用的 git hooks** | `make hooks` 啟用：commit 前擋衝突標記、推 `stage`／`prod` 前跑本機關卡、開發分支 commit 後自動推（讓別條 session 取號時看得到） |

## 內建的審查 agent（`.claude/agents/`）

skill 跑在主對話裡，看得見整段對話，也就會被前面下過的結論帶偏；subagent 是**獨立 context 的全新實例**，
「用沒看過的眼睛審」只有它做得到。模板附六個，一個檔就是全部，都是只讀不改：

| agent | 暱稱 | 什麼時候派 | 讓它有效的那一句 |
|---|---|---|---|
| `spec-adversary` | 規格審查師 | 票寫好、還沒動工 | 實地讀程式碼驗證票的每一句；分清「讀程式碼確認過」與「推測」，不重複票裡已知的 |
| `breaker` | 測試計畫審查師（破壞法） | 測試計畫或驗收標準寫好後 | 第一階段**不准看測試計畫**，先自己想怎麼弄壞它，再回頭比對漏了哪些 |
| `qa-architect` | 測試覆蓋審查師（盤點法） | 同上，與 `breaker` 一起派 | 先回答「哪些 bug 類別完全沒被任何一層測試覆蓋」 |
| `fresh-eye-ux-auditor` | Fresh-eye UX Auditor | 設計圖、畫面、文案定案前 | 用「第一次看到的人」的口吻寫一句他會怎麼想；只答好不好懂、會不會誤會 |
| `skill-change-proofreader` | Skill 變更校對者 | 一批 skill／agent 改動要出貨前 | **整份**讀完、不准只看改的那幾行；只找矛盾、重複、可刪的，不提新規則 |
| `adversarial-reviewer` | 提案審查師 | 提案、框架變更拿給使用者拍板前；落地後併 stage 前再審一次 | 拿每條結論去試著推翻，第 1 輪先看方向再逐條，每點都要指到檔案:行號或指令輸出 |

用完覺得不夠好，直接說「幫我把這個 agent retro 一下然後優化它」：改的是那個檔案，並在檔頭留下改了什麼、為什麼。
沒有 Claude Code 時，把檔案內文貼進派工 prompt 即可。

## 內建的 skill（`.agents/skills/`）

| skill | 做什麼 |
|---|---|
| `team-leader` | 每個新對話的開場簡報（SPEC、票、分支、平行現場），並從第一句話判斷入口 |
| `pm` | 給不懂 code 的案主：討論需求（必問五件事）、開票，要的話由 agent 用白話幫他開發到驗收 |
| `dev` | 給工程師：依票開發，動工前先查架構、既有功能、其他票與資安的衝突 |
| `framework` | 改協作框架本身：豁免功能票，但必寫決策紀錄並升版號 |
| `setup` | 第一次拿到模板時的初始化精靈，代填所有設定 |
| `grilling` | 把一個計畫或決定逼問到底；問非工程師時用他看得到的情境，不用術語 |
| `ui-design` | 動任何畫面前套用的 UI/UX 檢查清單（核心＋12 份 references），含示意圖規則 |
| `ux-writing` | 介面上的文字：把技術術語換成好懂、中性的繁體中文，全站用語一致 |
| `user-walkthrough` | 檢查綠燈後，用真人操作的視角走完整條路徑；分三級，走不了要照固定格式交代 |
| `run-checks` | 改完程式後必跑的最小驗證；輸出不接管線、有跳過的測試要回報 |

`.claude/skills/` 只是給 Claude Code 找得到的轉接檔，內容一律改 `.agents/skills/`。

## 機制化的閘門（`.claude/settings.json` hooks）

| 閘門 | 擋什麼 |
|---|---|
| 票務閘門 | 沒有待開發／開發中的票就改產品程式碼（`PRODUCT_DIRS`；在工作區裡看的是那一張票） |
| ui-design 閘門 | 沒先套 `ui-design` 就改畫面檔（`UI_PATH_GLOBS`，空的就不擋） |
| 示意圖文字閘門 | 寫示意圖（`cache/demos/`）前先擋一次，把「這句話在做什麼工作」那張表推到眼前；這是提醒，不是檢查 |
| git 同步閘門 | 落後遠端還要推（量的是實際要推的那一棵工作樹） |
| git 波及範圍閘門 | `git add -A`／`.` 整批提交、`HEAD^` 這類相對指法的回退 |
| 檢查管線閘門 | 檢查指令接 `\| tail`、`\| head` 等會吞掉失敗的管線（`NO_PIPE_COMMANDS`） |

閘門有沒有正確接上，`make check` 會用 `hooks-wiring-lint` 檢查。

## 常用指令

```
make new-ticket t="短題" r="角色"   # 開票（先問遠端、掃其他工作區再取號，防撞號）
make worktree n=TK-12               # 開隔離工作區（開發前必做）
make worktree-list                  # 看現在有幾條 session、各自什麼狀態
make worktree-clean n=TK-12         # 收工作區（先把 cache/ 搶救到 cache/rescued/）
make ticket-handoff to=TK-12 t="TK-12 TK-14"   # 把票搬進開發工作區並領票
python3 scripts/branch_tickets.py <分支> <票號…>  # 這條分支會帶上哪幾張別人的票
make check                          # 跑所有檢查（= CI），輸出不要接管線
make confirm-lint / walkthrough-lint   # 合流 stage 前
make confirm-lint-prod t="TK-12"    # 上 prod 前
make next-framework-version         # 框架版號取號（level=patch｜major）
make hooks                          # 啟用選用的 git hooks（每個 clone 一次）
make help                           # 列出所有指令
```

## 快速開始

1. **取得模板**：clone 或複製本資料夾，作為你的專案根目錄。
2. **用 [Claude Code](https://claude.com/claude-code) 開啟**（桌面 app 或 CLI 皆可）。
3. **打任何字**——第一個對話會自動進入**初始化引導**：回答 5 組問題
   （專案名稱、技術棧、程式碼目錄、票號前綴、檢查指令），agent 會代你填好所有設定。
   答不出來的都可以跳過，之後再補。
4. 初始化完成後，每個新對話自動出現**專案現況簡報**，並從你的第一句話判斷要走哪個入口（不用選）；
   直接說你要做的第一個功能即可。

> 不用 Claude Code 的 agent（Codex / Cursor）也能用：規則都在 `AGENTS.md` 與
> `.agents/skills/`，但 hooks（開場簡報與各道閘門）僅在 Claude Code 生效，其他 agent 靠紀律遵守；
> `.claude/agents/` 的審查 subagent 沒有 Claude Code 時，把那個檔的內文貼進派工 prompt 即可。
> `.githooks/`（`make hooks` 啟用）是一般的 git hooks，跟用哪個 agent 無關。

## 開發協作流程

```
新對話開始
   │
   ▼
[team-leader] 專案現況簡報（SPEC 狀態 / ticket 看板 / 分支環境 / 平行現場）
   │            └─ 從第一句話判斷入口（判斷不出來才問）
   │
   ├─→ [pm]        非工程師入口：討論需求（必問誰用/目的/驗收/邊界/誰看得到誰能改）→ 開票 →
   │                （要的話）agent 主導白話開發 → 實機測試 → 驗收
   │
   ├─→ [dev]       工程師入口：無票不開發 → 衝突/資安檢查 → 實作 → 驗證 → 推進票況
   │
   └─→ [framework] 框架入口：改協作框架本身（豁免票，必留決策紀錄）

開發一律：make worktree n=<票號>（自己的隔離工作區）→ 實作 → make check → 走查
          → 問過使用者 → 在主目錄合流 stage（同一次寫 SPEC）→ 實機驗收 → make worktree-clean
```

pm 與 dev **能力相同**（都先開票、共用「分支與出貨流程」），差在使用者是誰與呈現方式。
完整規則與設計理由見 [docs/FRAMEWORK.md](docs/FRAMEWORK.md)。

## 目錄結構

| 位置 | 進 git | 角色 |
|------|:------:|------|
| `AGENTS.md` | ✅ | 唯一工程契約（所有 agent 動工前先讀） |
| `CLAUDE.md` | ✅ | Claude Code 入口行為與路由 |
| `.agents/skills/` | ✅ | 角色入口與工作流的 canonical（單一來源） |
| `.claude/skills/` | ✅ | Claude Code adapter，只指回 canonical |
| `.claude/agents/` | ✅ | 自訂審查 subagent（一個檔就是全部，不分 canonical／adapter） |
| `.claude/settings.json` | ✅ | hooks（開場簡報、票務／畫面／示意圖文字／git 同步／git 波及範圍／檢查管線閘門）與權限 |
| `.githooks/` | ✅ | 版控內的 git hooks（每個 clone 跑一次 `make hooks` 才生效） |
| `tickets/` | ✅ | 功能票（產品開發唯一依據） |
| `docs/SPEC.md` | ✅ | 產品「目前實際行為」單一事實來源 |
| `docs/FRAMEWORK.md` | ✅ | 框架設計與決策紀錄（帶版號） |
| `docs/harness/` | ✅ | agent 派工制度（門檻、模板、判準） |
| `scripts/` | ✅ | 框架腳本（簡報、閘門、lint、工作區；專案設定在 `framework-config.sh`） |
| `.claude/worktrees/` | ❌ | 各條 session 的隔離工作區（`make worktree` 開、`make worktree-clean` 收） |
| `cache/` | ❌ | 戰情資料（討論過程、demo 素材），可隨時丟棄 |

## 框架規則 30 秒版

1. 新 session 先 team-leader 簡報（無例外）→ 從第一句話判斷入口，判斷不出來才問；
   恢復／壓縮後接續的對話不算新 session。
2. 無票不開發（hook 強制）；PM 開票必問「誰用 / 目的 / 驗收 / 邊界 / 誰看得到誰能改（全新的東西）」；
   開票用 `make new-ticket`（先問遠端再取號，防撞號）。
3. 票三態：待開發 → 開發中 → 完成（作廢不刪檔）；動工＝領票（標「開發中」＋填 `owner`，
   他人開發中的票不碰）。
4. 一 session 一工作區：開發前 `make worktree n=<票號>`，主目錄只做合流；
   提交指名到檔案、回退指名 commit（hook 強制）。
5. 兩道確認閘：開票後問「現在開發嗎？」、綠燈後問「上實機嗎？」——授權單次有效，不跨票延續。
6. 功能改了，`docs/SPEC.md` 在合流 `stage` 的同一次寫，否則合流不算完成；feature 分支與開票階段不動它。
7. 改到使用者看得到的東西：動畫面前先套 `ui-design`（hook 強制），檢查綠燈後照 `user-walkthrough` 走查；
   沒走成要講清楚「沒走的是／為什麼／誰該補走」。
8. 框架變更豁免票，但必 bump 版號＋寫 `docs/FRAMEWORK.md` 決策紀錄。
9. 對外/不可逆動作（merge 整合分支、部署、刪資料）一律先問使用者。
10. push 前先 `git pull --rebase`（hook 強制），避免平行開發互相覆蓋。

## 來歷

本框架萃取自一個真實外包專案的協作制度（框架版本演進與每條規則的「為什麼」
完整保留在 [docs/FRAMEWORK.md](docs/FRAMEWORK.md) 決策紀錄與 [docs/harness/](docs/harness/) 案例）。
