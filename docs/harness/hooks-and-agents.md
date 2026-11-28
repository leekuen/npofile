# Hooks 與自訂 subagent（從 CLAUDE.md 搬來，框架 v5.2.0）

CLAUDE.md 每條 session 都會載入；這兩段細節平常用不到，搬到這裡減少每次開場讀的量。
CLAUDE.md 留了一段摘要指回本檔。

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
