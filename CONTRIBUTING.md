# 貢獻指南

開始前**先讀 [AGENTS.md](AGENTS.md)**（工程契約，唯一事實來源）。本檔補充協作流程：分支模型、commit 規範、PR 流程。

---

## 分支模型 — 「分支即環境」

| 分支 | 對應 | 部署 |
|------|------|------|
| `stage` | 預設整合分支 | {{部署方式（setup / framework 入口填寫；還沒有部署環境就標「無」）}} |
| `prod` | 正式環境 | 一般是把驗過的 `stage` merge 進來 |
| `feature/*`、`fix/*` | 你的工作分支（各自在自己的工作區） | 不部署；合回 `stage` |

流程：

```
make worktree n=<票號>（從最新 origin/stage 開 feature/<票號> 到自己的隔離工作區；
   票有 depends 且那張還沒進 stage 時，從它的分支開，見 tickets/README.md〈相依的票〉）
   → 開發 → make check 綠燈 → 走查 → 問過使用者
   → 合流前跑 make confirm-lint 與 make walkthrough-lint
   → 合回 stage（在主目錄 merge，同一次把變更寫進 docs/SPEC.md；走網頁 PR 合併的專案，
     SPEC 那一筆在要按合併前補進 PR 的最後一個 commit——網頁上合併不會跑本機的 pre-push，兩項檢查要自己先跑）
   → 實機驗收
   → 驗過後把 stage merge 進 prod
```

> ⚠️ 別直接 push 到 `prod`；進 `stage`/`prod` 與部署都是對外動作，先取得使用者確認。
> push 前先 `git pull --rebase origin <分支>`（`scripts/git-sync-gate-hook.sh` 機制化強制）。
> 主目錄固定停在 `stage`、只做合流；不要在主目錄開發或 `checkout -b`（同一棵工作樹被兩條 session 寫會互相掃掉未提交的工作）。

---

## Commit 規範

用 Conventional Commits 前綴，描述可用繁體中文：

```
feat: 後台新增訂單匯出
fix: 修正列表分頁邊界
chore: rename repo
docs: 補工程文件
refactor: 抽出狀態轉換
test: 補並發測試
```

常用前綴：`feat` / `fix` / `chore` / `docs` / `refactor` / `test` / `perf` / `ci`。

**提交一律指名到檔案**（`git add path/to/file`）：不用 `git add -A`／`.`／資料夾、不用 `git commit -a`——
同一台機器上可能有別條 session 的東西，整批加會把不是你改的一起掃進去。要回退先 `git log --oneline -5`，
再指名 commit 雜湊，不用 `HEAD^`／`HEAD~n`。（兩條都由 `scripts/git-scope-gate-hook.sh` 機制化強制；
完整五條見 AGENTS.md「git 波及範圍」。）

---

## PR 前的檢查清單

提 PR（或請人合流）前在本機跑過，避免紅燈：

- [ ] `make check` 綠燈（至少含 ticket-lint 與框架工具測試；專案檢查指令見 AGENTS.md「最小驗證」）。
      輸出不要接管線；`OK (skipped=N)` 要講跳過幾條、為什麼。
- [ ] 對應功能票存在且狀態正確；票的開發備註寫了這次改了什麼（合流 `stage` 時依它寫 `docs/SPEC.md`——
      feature 分支上不改 SPEC）。
- [ ] 改到使用者看得到的東西：已照 `user-walkthrough` 走查並標憑據型態；沒走成的照「沒走的是／為什麼／誰該補走」寫明。
- [ ] 多介面專案：API 契約變動時所有介面都同步更新，除非明確只改單一平台。
- [ ] 對照 [docs/PRINCIPLES.md](docs/PRINCIPLES.md) 的落地清單（並發 / idempotency / N+1 / 權限 / 遷移安全性）。
- [ ] 沒有 commit 任何 env 實檔、祕密或備份檔。
- [ ] 合流前：`make confirm-lint`（票的〈條件確認〉〈數字口徑〉確認了沒）、`make walkthrough-lint`（走查紀錄交代齊了沒）；上 `prod` 前：`make confirm-lint-prod t="<票號…>"`。

PR 說明建議寫清楚：改了什麼、為什麼、各介面處理結果、跑過哪些檢查。

---

## 嚴禁（摘自 AGENTS.md）

- ❌ commit env 實檔、祕密、備份檔（只有 `.example` 進版控）。
- ❌ 無票開發產品程式碼；合流 `stage` 時沒同步 `docs/SPEC.md`（或反過來在 feature 分支上先改 SPEC）。
- ❌ 在主目錄開發；整批提交（`git add -A`／`.`／資料夾）；手寫票檔或自己取號。
- ❌ 閘門失敗硬上（票務 / 畫面 / git 同步 / git 波及範圍 / 部署檢查）。
- ❌ 未經確認執行對外、難復原的動作（部署、merge 整合/正式分支、刪 / 覆蓋資料）。

完整契約見 [AGENTS.md](AGENTS.md)。
