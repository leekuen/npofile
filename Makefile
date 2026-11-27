# Makefile — 統一指令入口。
# 模板初始只有框架檢查；setup / framework 入口依技術棧把專案的
# lint / test / build / 起環境指令補進來（並同步 AGENTS.md「最小驗證」與 run-checks skill）。

.PHONY: help check ticket-lint dup-lint new-ticket next-framework-version \
        worktree worktree-list worktree-clean ticket-handoff \
        walkthrough-lint confirm-lint confirm-lint-prod hooks \
        setup-dev test-server test-crawler test-deploy lint-web build-web

# 後端 Python：Windows 的 venv 在 Scripts/，其他平台在 bin/
PY := $(abspath $(firstword $(wildcard server/.venv/Scripts/python.exe server/.venv/bin/python)))
export PYTHONIOENCODING := utf-8

help: ## 列出所有指令
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-24s %s\n", $$1, $$2}'

check: ticket-lint dup-lint test-crawler test-server test-deploy lint-web ## 跑所有檢查（= CI）。輸出不要接管線
	@echo "[check] OK"

# ── 專案（NPOFile）────────────────────────────────────────────────────

setup-dev: ## 第一次開發：建後端 venv、裝套件、建資料庫；裝前台套件
	cd server && python -m venv .venv
	$(MAKE) setup-dev-deps

setup-dev-deps:
	cd server && $(PY) -m pip install -r requirements.txt && $(PY) manage.py migrate
	cd web && npm ci

test-crawler: ## 爬蟲解析測試（用存下來的真實網頁，不連網）
	cd crawler && $(PY) -m unittest discover -s tests

test-server: ## 後端測試（組織、爬蟲匯入與審核、捐款人與留言）
	cd server && $(PY) manage.py test

lint-web: ## 前台型別檢查與 lint
	cd web && npx tsc --noEmit && npm run lint

test-deploy: ## 排程外殼與資料庫備份腳本的測試（假的通知服務與 pg_dump，不連網）
	bash deploy/jobs-test.sh

build-web: ## 前台正式建置（會抓 Next.js 的預先算繪錯誤）
	cd web && npm run build

# ── 票務 ──────────────────────────────────────────────────────────────

new-ticket: ## 開新票（先問遠端、也掃其他工作區再取號，防撞號）：make new-ticket t="短題" r="店員"
	@./scripts/new-ticket.sh "$(t)" "$(r)"

ticket-lint: ## 票務格式與一致性檢查＋框架工具自己的測試
	./scripts/ticket-lint.sh
	@bash scripts/ticket-tools-test.sh  # 守規則的工具自己也要有測試（源專案 v4.12.1）
	@bash scripts/worktree-gates-test.sh  # 票務／畫面／示意圖文字閘門要認得工作區裡的檔案（源專案 v4.76.0）
	@bash scripts/git-sync-gate-test.sh  # 推送前同步閘門：量的是實際推的那一棵（git -C／cd／執行目錄／主目錄），落後才擋（源專案 v4.19.1；測試是模板內補的）
	@bash scripts/hooks-wiring-lint.sh  # 閘門有沒有真的接上：settings 有掛、檔案在、能執行、掛對事件與工具（模板內補的）
	@bash scripts/hooks-wiring-lint-test.sh  # 上面那支平常都是綠的：故意接壞給它看，確認每一種都會被點名（模板內補的）
	@bash scripts/git-scope-gate-test.sh  # git 波及範圍閘門：整批提交與 HEAD^ 要擋、指名檔案不能誤擋（源專案 v4.78.0）
	@bash scripts/check-pipe-gate-test.sh  # 檢查指令接管線要擋、導到檔案再讀不能誤擋（源專案 v4.90.0）
	@bash scripts/walkthrough-record-lint-test.sh  # 推 stage 前每個 W 要交代走過或沒走（源專案 v5.30.0）
	@bash scripts/stage-confirm-gate-test.sh  # 推 stage 前〈條件確認〉〈數字口徑〉要確認過：擋得到、例外只放行合格的（源專案 v5.41.0）
	@bash scripts/conflict-marker-lint-test.sh  # commit／推 stage 前擋沒解掉的衝突標記：擋得到、不誤報 markdown 底線（源專案 v5.39.0）
	@bash scripts/worktree-clean-rescue-test.sh  # 收工作區前先搶救 cache/、搶救不了或期間有動就不收（源專案 v5.21.0）
	@bash scripts/ticket-handoff-test.sh  # 票搬進開發工作區：不能改到內文、也不能留兩份（源專案 v4.81.0）
	@bash scripts/branch-tickets-test.sh  # 分支帶上 stage 的提交分屬哪幾張票（源專案 v5.16.0）
	@bash scripts/next-framework-version-test.sh  # 框架版號取號：只認檔頭與決策紀錄的列首、遠端分支上的號也要算
	@bash scripts/git-hooks-test.sh  # 版控 git hooks：pre-push／post-commit 與 make hooks 在沙盒 repo 裡真的擋得到、放得過（pre-commit 在 conflict-marker-lint-test；模板內補的）
	@bash scripts/repo-lints-test.sh  # bash 3.2 變數、複製檔兩支 lint 自己會紅（模板內補的）
	@bash scripts/bash32-var-lint.sh  # 變數後面直接接全形字，macOS 內建的 bash 3.2 會讀錯變數名（源專案 v4.86.0）

dup-lint: ## 抓版控裡的複製檔（同步工具或檔案總管產生的「檔名 2.副檔名」）
	@bash scripts/dup-file-lint.sh

walkthrough-lint: ## 合流前先查：每張票的走查紀錄（W 編號）交代齊了沒（ref="feature/TK-12 feature/TK-13" 可多條，不給＝目前這條）
	@if git remote get-url origin >/dev/null 2>&1; then \
	  git fetch -q origin stage 2>/dev/null || echo "[walkthrough-lint] ⚠️ git fetch 失敗，對的是本機舊的 origin/stage"; \
	  python3 scripts/walkthrough_record_lint.py --ref $(if $(ref),$(ref),HEAD); \
	else \
	  echo "[walkthrough-lint] 沒有遠端：改跟本機的 stage 比（模板內補的）"; \
	  for r in $(if $(ref),$(ref),HEAD); do \
	    b=$$(git merge-base stage "$$r") || { echo "[walkthrough-lint] ❌ 算不出 $$r 跟本機 stage 的共同祖先——沒有檢查"; exit 2; }; \
	    python3 scripts/walkthrough_record_lint.py "$$b" "$$(git rev-parse "$$r")" || exit $$?; \
	  done; \
	fi

confirm-lint: ## 合流前先查：每張票的〈條件確認〉〈數字口徑〉確認了沒（ref 用法同 walkthrough-lint）
	@if git remote get-url origin >/dev/null 2>&1; then \
	  git fetch -q origin stage 2>/dev/null || echo "[confirm-lint] ⚠️ git fetch 失敗，對的是本機舊的 origin/stage"; \
	  bash scripts/unconfirmed-conditions.sh --stage-ref $(if $(ref),$(ref),HEAD); \
	else \
	  echo "[confirm-lint] 沒有遠端：改跟本機的 stage 比（模板內補的）"; \
	  for r in $(if $(ref),$(ref),HEAD); do \
	    b=$$(git merge-base stage "$$r") || { echo "[confirm-lint] ❌ 算不出 $$r 跟本機 stage 的共同祖先——沒有檢查"; exit 2; }; \
	    bash scripts/unconfirmed-conditions.sh --stage-range "$$b" "$$(git rev-parse "$$r")" || exit $$?; \
	  done; \
	fi

confirm-lint-prod: ## 上 prod 前查：這次要上線的票〈條件確認〉〈數字口徑〉在 origin/stage 上確認了沒：make confirm-lint-prod t="TK-12 TK-13"
	@test -n "$(t)" || { echo "[confirm-lint-prod] 要指名票號：make confirm-lint-prod t=\"TK-12 TK-13\""; exit 2; }
	@git remote get-url origin >/dev/null 2>&1 || { echo "[confirm-lint-prod] 沒有遠端：這項讀的是 origin/stage 上的票，沒有遠端就查不了——上 prod 前先設好遠端（模板內補的）"; exit 2; }
	@bash scripts/unconfirmed-conditions.sh $(t)

# ── 平行多 session：一 session 一工作區 ─────────────────────────────────

worktree: ## 開隔離工作區：make worktree n=TK-12（開發一律在工作區，主目錄只做合流；相依的票還沒進 stage 加 base=origin/feature/TK-11）
	@bash scripts/new-worktree.sh "$(n)" $(if $(base),"$(base)",)

worktree-list: ## 列出目前所有工作區與它們的狀態
	@bash scripts/worktree-clean.sh --list

worktree-clean: ## 收掉用完的工作區：make worktree-clean n=TK-12；整批預覽已合流的：n=--merged（預覽完照它印的指令才真的收）
	@bash scripts/worktree-clean.sh "$(if $(n),$(n),--list)"

ticket-handoff: ## 把票搬進開發工作區並領票：make ticket-handoff to=TK-12 t="TK-12 TK-14"（可加 from=來源工作區、dry=1）
	@bash scripts/ticket-handoff.sh "$(to)" $(t) $(if $(from),--from "$(from)",) $(if $(dry),--dry-run,)

# ── 框架 ──────────────────────────────────────────────────────────────

next-framework-version: ## 框架版號取號（先問遠端所有分支再算，防撞號）：預設下一個 MINOR；level=patch｜major
	@./scripts/next-framework-version.sh $(if $(level),--$(level),)

hooks: ## 啟用版控裡的 git hooks（選用，每個 clone 一次）：commit 前擋衝突標記、推 stage／prod 前跑通用關卡、開發分支 commit 後自動推
	@bash scripts/setup-hooks.sh
