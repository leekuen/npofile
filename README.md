# Agent 協作開發框架模板

> 給「用 AI Agent 開發軟體」的個人與小團隊：一套**角色入口 + 功能票 + 機制化閘門**的
> 協作框架，讓不懂 code 的案主/PM 和工程師共用同一個 repo、同一套規則，
> 而且規則靠 hook 強制執行，不靠自律。

**目前專案**：（未初始化——第一次用 Claude Code 開啟本資料夾時，會自動進入初始化引導。）

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
