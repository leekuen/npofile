# sensors-backlog.md — 可機制化的規則（上限 30 行）

> 原則：能用 hook / 測試 / CI 自動擋的，不留文字規則。造好一項就從「待造」移到「現役」。

## 現役（已機制化，文字規則不存在或僅存說明）
> Claude Code hook 全部掛在 repo 內版控的 `.claude/settings.json`（`$CLAUDE_PROJECT_DIR/scripts/*.sh`，隨 repo 走）；git hook 在 `.githooks/`，每個 clone 跑一次 `make hooks` 才生效。
- SessionStart hook（`scripts/session-start-hook.sh`）：開場規則與即時狀態注入。
- PreToolUse ticket-gate（`scripts/ticket-gate-hook.sh`）：無票不開發，直接擋寫入；工作區名稱是票號時只看那張票（源專案 v4.76.0）。
- PreToolUse ui-design-gate＋ui-design-mark（`scripts/ui-design-{gate,mark}-hook.sh`）：動畫面層檔（`UI_PATH_GLOBS`）前未套 ui-design skill 就擋；兩個閘門都認得工作區路徑，回歸測試 `scripts/worktree-gates-test.sh`（源專案 v4.76.0）。
- PreToolUse mockup-text-gate（`scripts/mockup-text-gate-hook.sh`，源專案 v4.47.0）：寫示意圖檔前把 ui-design 的多餘文字分類表推到眼前，自己 touch 標記檔放行。
- PreToolUse git-sync-gate（`scripts/git-sync-gate-hook.sh`）：push 前落後遠端就擋，要求先 pull --rebase。
- PreToolUse git-scope-gate（`scripts/git-scope-gate-hook.sh`，源專案 v4.29.0）：擋 `git add -A`／`.`／資料夾與 `HEAD^`／`HEAD~n`，逼指名到檔案與 commit 雜湊；逃生口 `cache/git-scope-override`。
- PreToolUse check-pipe-gate（`scripts/check-pipe-gate-hook.sh`，源專案 v4.90.0）：擋把檢查指令（`NO_PIPE_COMMANDS`）接進管線的寫法；回歸測試 `scripts/check-pipe-gate-test.sh`。
- ticket-lint（`scripts/ticket-lint.sh`，掛 `make check` 與開場簡報 `agent-status.sh`）：票格式、一致性、與整合分支比對撞號；`TICKET_RULES_SINCE` 之後建的票另擋缺〈條件確認〉〈數字口徑〉（源專案 v5.5.0／v5.19.0，只擋忘記）；回歸測試 `scripts/ticket-tools-test.sh`。
- `.githooks/pre-commit` 擋衝突標記；`.githooks/pre-push` 推 `stage`／`prod` 前跑衝突標記、走查交代、條件確認、bash 3.2 變數寫法（源專案 v5.39.0／v5.30.0／v5.41.0／v5.12.0，細節見該檔檔頭）。

## 待造（每項：擋什麼 → 怎麼造）
1. **push 後驗終態** [C1]：防「push 成功≠部署成功」→ 加 `make push-verify`（push 後
   `gh run watch` 回報 CI/CD 結論）或 git wrapper；造好後 dispatch.md 該句可縮為一行指引。
2. **推 prod 前驗 stage 已部署完成**：防「stage 沒驗完就推 prod」→ 推 prod 前的檢查找 headSha 包含這批 commit（`git merge-base --is-ancestor`）的最新一條 stage run，確認 CI/CD 都成功；不能用 `gh run list --commit <票的 commit>`（`--no-ff` 合流下查不到）。現在只有文字規則。
3. **harness 檔自檢**：防制度膨脹與路由斷鏈 → lint script 進 `make check`：行數上限（dispatch>60 / templates>25 / sensors-backlog>30 / maintenance>25 即紅燈）；兩層 CLAUDE.md 的 `docs/harness/` 引用逐一 `test -e`。
4. **推 prod 前擋未確認條件**：推 `stage` 這一道已由 `.githooks/pre-push` 擋；推 `prod` 前仍是手動 `make confirm-lint-prod t="…"`，要掛進推 prod 前的檢查，需要的是檢查知道「這批是哪幾張票」（源專案 v5.41.0）。
5. **回應欄位清單進版控**（源專案 v5.4.0，防「拿掉欄位卻不知道誰在讀」）→ 把 API schema 的欄位清單產生成進版控的檔、忘了重產 `make check` 紅，diff 看得到被刪的欄位；只抓得到有 schema 描述的端點，手寫回應另想。依技術棧選工具，另開框架票。

> 綁技術棧、這次沒帶的概念（依專案需要再造）：搶桌面焦點的指令閘門（模擬器類）、開場簡報列出主機上誰佔著 dev server、資料庫唯讀查詢的唯一入口、CI runner 卡死的自救、樣板跨行註解寫入當下就擋。

## 兩道確認閘的機制化
規則層現況：pm/dev SKILL + AGENTS.md 嚴禁清單。可機制化：PreToolUse hook 攔 `git push origin stage|prod`，要求本回合確認標記（如 cache/.push-approved，同意後建立、push 後即刪；hook 不能互動，只能以標記檔為證）。先觀察規則層遵循度，重犯再上 hook。
