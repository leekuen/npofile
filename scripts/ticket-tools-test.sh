#!/usr/bin/env bash
# 票務工具自動化測試（源專案 v4.12.1）：new-ticket.sh 的取號、ticket-lint.sh 的守門，
# 以及 unconfirmed-conditions.sh 給票號清單的那條路（推 prod 前的條件確認檢查）。
#
# 為什麼要有：源專案 v4.11.0 把票號改成作者前綴時，取號腳本與 lint 都只靠**手動跑幾次看輸出**
# 驗證——而同一天就實際發生「讓號時檔名改了、frontmatter 的 id 忘了改」與
# 「lint 的錯誤路徑第一次執行就炸」（${base}：黏全形字元）兩件事。守規則的工具自己沒有測試，
# 規則遲早再破一次。
#
# 全程在暫存沙盒跑（TICKETS_DIR 覆寫，或把腳本複製進沙盒 repo 再跑），不碰真的 tickets/；
# 沙盒 repo 不是沒有遠端、就是遠端指到沙盒裡的資料夾，不對外連線。掛在 make ticket-lint 之後。
#
# 新票規的生效日（TICKET_RULES_SINCE）由這支測試自己指定，不吃 scripts/framework-config.sh 的值：
# 專案把生效日改成升級當天之後，這些案例的結果不能跟著變。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

fail=0
err() { echo "[ticket-tools-test] ✗ $1" >&2; fail=1; }
ok() { echo "[ticket-tools-test] ✓ $1"; }

# 從 git hook 裡被叫起來時，環境會帶著 GIT_DIR／GIT_WORK_TREE／GIT_INDEX_FILE，
# 沙盒裡的 git 會全部打到真 repo。先清掉；下面要指到沙盒的地方都是自己明寫 GIT_DIR。
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

SINCE=2025-06-01   # 沙盒用的生效日
NEW=2025-06-10     # 生效日之後建立的票（套新票規）
OLD=2025-05-31     # 生效日前一天建立的票（不套）
export TICKET_RULES_SINCE="$SINCE"

# 舊制前綴讀設定檔的那一個（ticket-lint 也是讀它）：專案改過 TICKET_PREFIX，舊制票的案例跟著走。
LEGACY="$( . "$ROOT/scripts/framework-config.sh" >/dev/null 2>&1; printf '%s' "${TICKET_PREFIX:-}" )"
if [ -z "$LEGACY" ]; then
  err "讀不到 scripts/framework-config.sh 的 TICKET_PREFIX——舊制票的案例先用 TK 代替"
  LEGACY="TK"
fi

SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

# 假 git repo：讓 new-ticket 讀不到**真 repo 的 ticket.prefix**。
# 第一版沒隔離，跑在已設定前綴的 clone 上時「未設前綴要擋」測試就假失敗了——
# 測試自己第一次執行就抓到自己不夠密封，這正是要自動化的原因。
# （GIT_CONFIG_GLOBAL／GIT_CONFIG_NOSYSTEM：前綴設在全域 git 設定的機器上也一樣讀不到。）
git init -q "$SANDBOX/fakegit"
FAKE_GIT_DIR="$SANDBOX/fakegit/.git"

run_new_ticket() {  # $1=prefix（空字串＝不給，測未設定路徑） $2=title
  GIT_DIR="$FAKE_GIT_DIR" GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
  TICKETS_DIR="$SANDBOX" TICKET_PREFIX="${1}" TICKET_REMOTE="__no_such_remote__" \
    bash "$ROOT/scripts/new-ticket.sh" "$2" "管理員" 2>/dev/null
}

run_lint() {
  # `TICKET_LINT_BASE=__no_such_ref__`：這幾條驗的是格式與本地一致性，**不要**去比真的
  # `origin/stage`——沙盒票（TESTA-01、舊制票號…）落在真實號碼空間，遠端哪天出現同號，
  # 這些測試就會莫名轉紅。遠端比對本身由第 9~11 條用自帶的假整合分支驗。
  TICKETS_DIR="$SANDBOX" TICKET_LINT_BASE=__no_such_ref__ \
    bash "$ROOT/scripts/ticket-lint.sh" 2>&1
}

# ── 取號 ────────────────────────────────────────────────────────────────
# 1) 未設前綴要擋下並給指引，不能默默用錯身分
if run_new_ticket "" "無前綴要擋" >/dev/null; then
  err "未設前綴竟然開票成功——會默默用錯身分"
else
  ok "未設前綴被擋下"
fi

# 2) 第一張從 01 開始
run_new_ticket "TESTA" "第一張" >/dev/null
[ -f "$SANDBOX/TESTA-01-第一張.md" ] && ok "TESTA-01 建立" || err "第一張沒有取到 TESTA-01"

# 3) 同前綴遞增
run_new_ticket "TESTA" "第二張" >/dev/null
[ -f "$SANDBOX/TESTA-02-第二張.md" ] && ok "同前綴遞增到 02" || err "同前綴沒有遞增"

# 4) 不同前綴各自獨立（這就是不會撞號的核心保證）
run_new_ticket "TESTB" "別人的第一張" >/dev/null
[ -f "$SANDBOX/TESTB-01-別人的第一張.md" ] \
  && ok "不同前綴各自從 01 起（號碼空間獨立）" \
  || err "前綴的號碼空間沒有隔離——撞號問題沒真的解掉"

# ── lint 守門 ──────────────────────────────────────────────────────────
# 5) 剛開的票要能過 lint（新舊格式相容）
lint_new=$(run_lint); lint_new_rc=$?
if [ "$lint_new_rc" -eq 0 ] && grep -q "OK" <<<"$lint_new"; then
  ok "新格式票通過 lint"
else
  err "新開的票過不了 lint（exit ${lint_new_rc}）：$(head -2 <<<"$lint_new")"
fi

# 6) frontmatter id 與檔名不一致要抓到（讓號時只改了檔名——源專案實際發生過）
sed -i '' 's/^id: TESTA-02$/id: TESTA-99/' "$SANDBOX/TESTA-02-第二張.md" 2>/dev/null \
  || sed -i 's/^id: TESTA-02$/id: TESTA-99/' "$SANDBOX/TESTA-02-第二張.md"
lint_mismatch=$(run_lint)
if grep -q "檔名須以 id" <<<"$lint_mismatch"; then
  ok "id 與檔名不一致被抓到（讓號時只改檔名的守門）"
else
  err "id 與檔名不一致沒被抓到——讓號時只改檔名、忘了改 id 的事會再發生。lint 輸出：$(head -3 <<<"$lint_mismatch")"
fi
sed -i '' 's/^id: TESTA-99$/id: TESTA-02/' "$SANDBOX/TESTA-02-第二張.md" 2>/dev/null \
  || sed -i 's/^id: TESTA-99$/id: TESTA-02/' "$SANDBOX/TESTA-02-第二張.md"

# 7) id 重複要抓到，而且**錯誤路徑本身不能炸**（${base}：黏全形字元那個坑）
cp "$SANDBOX/TESTA-01-第一張.md" "$SANDBOX/TESTA-01-複製撞號.md"
lint_out=$(run_lint)
if grep -q "id 重複" <<<"$lint_out"; then
  ok "id 重複被抓到"
else
  err "id 重複沒被抓到：$lint_out"
fi
if grep -q "unbound variable" <<<"$lint_out"; then
  err "lint 的錯誤路徑自己炸了（unbound variable）——回報撞號的功能在最需要時死掉"
else
  ok "錯誤路徑本身活著（bash 3.2 全形字元坑的回歸）"
fi
rm -f "$SANDBOX/TESTA-01-複製撞號.md"

# 8) 舊制票號（scripts/framework-config.sh 的 TICKET_PREFIX＋四位數）仍然合法：
#    改用作者前綴之前開的票不改號，新舊並存。
cat > "$SANDBOX/${LEGACY}-9999-舊制相容.md" <<EOF
---
id: ${LEGACY}-9999
title: 舊制相容
status: 待開發
roles: [管理員]
spec:
created: $OLD
updated: $OLD
---
EOF
lint_legacy=$(run_lint); lint_legacy_rc=$?
if [ "$lint_legacy_rc" -eq 0 ] && grep -q "OK" <<<"$lint_legacy"; then
  ok "舊制票號（${LEGACY}-XXXX）相容"
else
  err "舊制票被誤擋（exit ${lint_legacy_rc}）：$(head -2 <<<"$lint_legacy")"
fi

# 8b) depends 欄位（源專案 v5.16.0）：只擋格式與「不能是自己」，**不查那張票的檔案存不存在**
#     （只挑部分票上 prod 的專案，prod 的 tickets/ 是 stage 的子集、搬票會刪來源那份，
#     查存在性會在 prod 那棵樹誤紅）。用獨立沙盒，不跟上面的票互相干擾。
DEPS="$SANDBOX/deps"; mkdir -p "$DEPS"
dep_case() {  # $1＝名稱 $2＝pass|fail $3＝depends 那一行（空字串＝不寫這個鍵）
  rm -f "$DEPS"/*.md
  { printf -- '---\nid: TESTD-05\ntitle: 相依測試\nstatus: 待開發\nroles: [管理員]\nspec:\ncreated: %s\nupdated: %s\n' "$NEW" "$NEW"
    [ -n "$3" ] && printf '%s\n' "$3"; printf -- '---\n'; } > "$DEPS/TESTD-05-相依測試.md"
  local out rc; out=$(TICKETS_DIR="$DEPS" TICKET_LINT_BASE=__no_such_ref__ bash "$ROOT/scripts/ticket-lint.sh" 2>&1); rc=$?
  if [ "$2" = pass ] && [ "$rc" -eq 0 ]; then ok "depends：$1"
  elif [ "$2" = fail ] && [ "$rc" -ne 0 ] && grep -q "depends" <<<"$out"; then ok "depends：$1"
  else err "depends：$1（預期 $2，exit ${rc}）：$(head -3 <<<"$out")"; fi
}
dep_case "沒寫這個鍵的舊票照過" pass ""
dep_case "空清單 []" pass "depends: []"
dep_case "兩張票" pass "depends: [AMY-540, BOB-21]"
dep_case "舊制票號" pass "depends: [${LEGACY}-0137]"
dep_case "不存在的票也不擋（不查存在性）" pass "depends: [NOPE-99]"
dep_case "行尾註解" pass "depends: [AMY-540]  # 要用它的資料表"
dep_case "寫了卻留空要紅" fail "depends:"
dep_case "沒有中括號要紅" fail "depends: AMY-540"
dep_case "票號格式錯要紅" fail "depends: [amy-540]"
dep_case "尾逗號要紅" fail "depends: [AMY-540,]"
dep_case "不能依賴自己" fail "depends: [AMY-540, TESTD-05]"
dep_case "票號是自己的前綴一段不算自己" pass "depends: [TESTD-055]"
# 同一個鍵寫兩行 → frontmatter 重複那條要抓到（depends 在鍵清單裡）
rm -f "$DEPS"/*.md
printf -- '---\nid: TESTD-06\ntitle: 重複\nstatus: 待開發\nroles: [管理員]\nspec:\ncreated: %s\nupdated: %s\ndepends: []\ndepends: [AMY-01]\n---\n' "$NEW" "$NEW" > "$DEPS/TESTD-06-重複.md"
dep_dup_out=$(TICKETS_DIR="$DEPS" TICKET_LINT_BASE=__no_such_ref__ bash "$ROOT/scripts/ticket-lint.sh" 2>&1)
if grep -q "重複的欄位（depends）" <<<"$dep_dup_out"; then
  ok "depends 寫兩行被「frontmatter 重複」抓到"
else
  err "depends 寫兩行沒被抓到"
fi
# 新開的票範本要有 depends: []，而且能過 lint
if grep -q '^depends: \[\]' "$SANDBOX/TESTA-01-第一張.md"; then ok "new-ticket 範本有 depends: []"; else err "new-ticket 範本沒有 depends: []"; fi

# ── 與整合分支比對撞號 ────────────────────────────────────────────────
#
# 為什麼補這幾條：源專案 v4.20.0 上線的「同 id 不同 title 就擋」在消費端用 tab 去切
# **US 分隔**的資料（產生端 printf 用 \037），於是本地 title 表永遠是空的、
# 撞號永遠印不出來——而 lint 每次都印「OK（N 張票通過）」。上線之後好一陣子
# 沒有任何跡象：**假保護跟真保護在畫面上長得一模一樣**，只有真的造一次撞號才看得出來。
# 所以這幾條不驗程式碼長什麼樣，驗「造一個撞號，lint 會不會紅」。
#
# 沙盒 repo 刻意做出**分歧**（base → 整合分支多一張票；HEAD 停在 base），
# 因為「改名 ≠ 撞號」的判準就是「這個號在分歧點之前就存在了嗎」。
# 假整合分支自帶（`GIT_DIR` 指沙盒），**不依賴 `origin/stage` 的內容**
# ——依賴真遠端的測試會隨著別人合票而時綠時紅，那種測試沒人會信。
CLASH_REPO="$SANDBOX/clashrepo"
mkdir -p "$CLASH_REPO/tickets" "$SANDBOX/clashlocal/tickets" \
         "$SANDBOX/renamelocal/tickets" "$SANDBOX/renamedfile/tickets"
git init -q "$CLASH_REPO"

write_ticket() {  # $1=檔案路徑 $2=id $3=title
  # created 用生效日之前的日期：這幾張「開發中」的沙盒票只拿來驗撞號，不要被新票規的檢查掃到
  cat > "$1" <<EOF
---
id: $2
title: $3
status: 開發中
roles: [管理員]
owner: tester
spec:
created: $OLD
updated: $OLD
---
EOF
}

# `-c commit.gpgsign=false -c core.hooksPath=/dev/null`：不要吃這台機器的 git 設定。
# 少了它，有簽章或有 global hook 的機器上 commit 會失敗 → 分支建不起來 → lint 印
# 「跳過遠端比對」→ 測試紅在「撞號沒被抓到」，訊息把人指向完全錯的方向。
sandbox_git() { git -C "$CLASH_REPO" -c user.email=t@t -c user.name=t \
  -c commit.gpgsign=false -c core.hooksPath=/dev/null "$@"; }

# base：分歧點。TESTC-02 在這裡就存在（＝之後的改名不算撞號）
write_ticket "$CLASH_REPO/tickets/TESTC-02-同一張票.md" "TESTC-02" "整合分支的標題"
sandbox_git add "tickets/TESTC-02-同一張票.md"
sandbox_git commit -qm "base" >/dev/null
sandbox_git branch -f fakelocal
# 整合分支：分歧之後才多出來的 TESTC-01（＝真撞號的模型）
write_ticket "$CLASH_REPO/tickets/TESTC-01-整合分支上的那張.md" "TESTC-01" "整合分支上的那張"
sandbox_git add "tickets/TESTC-01-整合分支上的那張.md"
sandbox_git commit -qm "integration only" >/dev/null
sandbox_git branch -f fakeintegration
sandbox_git symbolic-ref HEAD refs/heads/fakelocal   # HEAD 停在分歧點
# fixture 沒建起來就直說，不要讓後面三條紅在錯的地方
if sandbox_git rev-parse --verify -q fakeintegration >/dev/null \
   && [ "$(sandbox_git rev-parse fakelocal)" != "$(sandbox_git rev-parse fakeintegration)" ]; then
  ok "撞號測試的假整合分支建立成功（沙盒有分歧）"
else
  err "假整合分支沒建起來——下面三條撞號測試的結果不可信"
fi

run_lint_vs_fake() {  # $1=本地 tickets 目錄（用 .../tickets/ 結尾，路徑正規化才對得上遠端）
  GIT_DIR="$CLASH_REPO/.git" TICKETS_DIR="$1" TICKET_LINT_BASE=fakeintegration \
    bash "$ROOT/scripts/ticket-lint.sh" 2>&1
}

# 9) 同號不同票要擋下來——源專案那場事故（本地每一張都過 lint，一合併就撞）的守門
write_ticket "$SANDBOX/clashlocal/tickets/TESTC-01-本地那張完全不同的票.md" "TESTC-01" "本地那張完全不同的票"
clash_out=$(run_lint_vs_fake "$SANDBOX/clashlocal/tickets"); clash_rc=$?
if grep -q "撞號：TESTC-01" <<<"$clash_out"; then
  ok "同號不同票被抓到（遠端撞號這道防線是活的）"
else
  err "同號不同票沒被抓到——撞號要到合併那一刻才會炸。lint 輸出：$(head -3 <<<"$clash_out")"
fi
if [ "$clash_rc" -ne 0 ]; then
  ok "撞號讓 lint 紅燈（exit≠0，make check 擋得住）"
else
  err "撞號印出來了卻還是綠燈（exit 0）——make check 不會擋，等於沒擋"
fi

# 10) 反向之一：同一張票、同一個檔名，只改 title → 不可報撞號
write_ticket "$SANDBOX/renamelocal/tickets/TESTC-02-同一張票.md" "TESTC-02" "本地改過的標題"
rename_out=$(run_lint_vs_fake "$SANDBOX/renamelocal/tickets"); rename_rc=$?
if [ "$rename_rc" -eq 0 ] && ! grep -q "撞號" <<<"$rename_out"; then
  ok "同一張票改標題不算撞號（同檔名）"
else
  err "改標題被誤判成撞號——正當改名會讓所有人的檢查紅燈。lint 輸出：$(head -3 <<<"$rename_out")"
fi

# 11) 反向之二（源專案實際踩到的）：改 title **並照慣例把檔名一起改**。
# 檔名慣例是 `<id>-<標題>.md`，所以這才是改標題的常態做法；
# 只靠「路徑相同」豁免會把它判成撞號，還叫人改號——完全錯誤的處置。
# 判準改成「這個號在分歧點之前就存在嗎」：TESTC-02 在 base 就有，所以是改名不是撞號。
write_ticket "$SANDBOX/renamedfile/tickets/TESTC-02-改過名的檔.md" "TESTC-02" "本地改過的標題"
renamedfile_out=$(run_lint_vs_fake "$SANDBOX/renamedfile/tickets"); renamedfile_rc=$?
if [ "$renamedfile_rc" -eq 0 ] && ! grep -q "撞號" <<<"$renamedfile_out"; then
  ok "改標題順手改檔名也不算撞號（分歧前就有這個號）"
else
  err "改標題＋改檔名被誤判成撞號——這是改票標題的常態做法。lint 輸出：$(head -3 <<<"$renamedfile_out")"
fi

# ── 整合分支已經在 HEAD 的歷史裡時，守著撞號的是誰（源專案 v4.48.2）──────
#
# 源專案 v4.48.1 修好撞號比對之後留下的問題：它在 CI 上抓不到任何東西。
# 原因不是 ref 取不到，是**整合分支已經在 HEAD 的歷史裡**——
# 推 stage 之後跑的檢查是拿自己比自己；PR 的 checkout 是 merge commit，merge-base 等於
# base tip，於是每個號都算「分歧前就有」，被改名豁免整個抵銷。
# （本機剛把 origin/stage 併進自己的分支之後，也是同一種形狀。）
# 這兩條測試釘住的是**取而代之的保證**，不是那段比對本身：
#   12) 這種形狀下，lint 要**明講**自己跳過了（不准靜靜跑完零輸出——
#       「跑了但永遠沒輸出」正是源專案 v4.48.1 那個假保護的長相）。
#   13) 同一種形狀下，真的同號不同票**仍然要紅**（由「id 重複」擋）。
#       少了這條，第 12 條會變成「合理化跳過」的藉口。
CI_LOCAL="$SANDBOX/cilocal/tickets"
mkdir -p "$CI_LOCAL"

# 讓 HEAD 走到整合分支上（＝那種形狀：INTEGRATION 是 HEAD 的祖先）
sandbox_git symbolic-ref HEAD refs/heads/fakeintegration
sandbox_git read-tree --reset -u HEAD 2>/dev/null

# 12) 這種形狀下要印出「撞號比對跳過」，而且不能因此紅燈
write_ticket "$CI_LOCAL/TESTC-02-同一張票.md" "TESTC-02" "整合分支的標題"
ci_out=$(run_lint_vs_fake "$CI_LOCAL"); ci_rc=$?
if grep -q "撞號比對跳過" <<<"$ci_out"; then
  ok "整合分支已在 HEAD 歷史裡時，lint 明講自己跳過了（不會再是沉默的假保護）"
else
  err "整合分支已在 HEAD 歷史裡時，lint 沒有交代撞號比對的去向——又回到「跑了但永遠沒輸出」。lint 輸出：$(head -3 <<<"$ci_out")"
fi
if [ "$ci_rc" -eq 0 ]; then
  ok "跳過比對本身不讓 lint 紅燈"
else
  err "跳過比對卻紅燈了（exit=${ci_rc}）：$(head -3 <<<"$ci_out")"
fi

# 13) 同一種形狀下，真的撞號仍然要紅——這才是那時候實際在守的那道
write_ticket "$CI_LOCAL/TESTC-02-另一張同號的票.md" "TESTC-02" "另一張完全不同的票"
ci_dup_out=$(run_lint_vs_fake "$CI_LOCAL"); ci_dup_rc=$?
if [ "$ci_dup_rc" -ne 0 ] && grep -q "id 重複：TESTC-02" <<<"$ci_dup_out"; then
  ok "整合分支已在 HEAD 歷史裡時，同號不同票仍然紅燈（「id 重複」接手守住，不需要遠端）"
else
  err "整合分支已在 HEAD 歷史裡時，同號不同票沒被擋——跳過撞號比對就真的沒人守了。lint 輸出：$(head -3 <<<"$ci_dup_out")"
fi
rm -f "$CI_LOCAL/TESTC-02-另一張同號的票.md"

# ── 取號要看得到本機其他工作樹還沒提交的票（源專案 v4.70.0）──────────────
#
# 源專案 v4.55.0 的第 1b 步用 `$ROOT/.claude/worktrees` 找兄弟工作樹，但 ROOT 是**腳本所在的那一棵**：
# 在 worktree 裡跑，那個路徑根本不存在，整步靜靜跳過。源專案因此發出一個重複的號，
# 而另一棵工作樹裡已經有兩張未提交的票用了它。
# 這條照事故的形狀造：主目錄＋.claude/worktrees 下兩棵，腳本**複製進其中一棵**再跑
# （ROOT 就是那棵 worktree），別的兩處各放一張未提交的票，看取號有沒有跳過它們。
WT_MAIN="$SANDBOX/wtmain"
mkdir -p "$WT_MAIN/tickets" "$WT_MAIN/scripts"
git init -q "$WT_MAIN"
wt_git() { git -C "$WT_MAIN" -c user.email=t@t -c user.name=t \
  -c commit.gpgsign=false -c core.hooksPath=/dev/null "$@"; }
touch "$WT_MAIN/tickets/.keep"
wt_git add tickets/.keep && wt_git commit -qm base >/dev/null
wt_git worktree add -q "$WT_MAIN/.claude/worktrees/mine" -b mine 2>/dev/null
wt_git worktree add -q "$WT_MAIN/.claude/worktrees/other" -b other 2>/dev/null
write_ticket "$WT_MAIN/tickets/TESTD-03-主目錄沒提交的.md" "TESTD-03" "主目錄沒提交的"
write_ticket "$WT_MAIN/.claude/worktrees/other/tickets/TESTD-05-別條還沒提交的.md" "TESTD-05" "別條還沒提交的"
MINE="$WT_MAIN/.claude/worktrees/mine"
mkdir -p "$MINE/scripts"
cp "$ROOT/scripts/new-ticket.sh" "$MINE/scripts/new-ticket.sh"
if [ -d "$MINE/tickets" ] && [ -d "$WT_MAIN/.claude/worktrees/other/tickets" ]; then
  ok "工作樹測試的沙盒建立成功（主目錄＋兩棵 worktree）"
else
  err "沙盒 worktree 沒建起來——下一條的結果不可信"
fi
# 14) 在 worktree 裡開票，要跳過主目錄的 03 與另一棵的 05，拿到 06
( unset GIT_DIR; TICKET_PREFIX=TESTD TICKET_REMOTE=__no_such_remote__ \
    bash "$MINE/scripts/new-ticket.sh" "工作樹裡開的" "管理員" >/dev/null 2>&1 )
if [ -f "$MINE/tickets/TESTD-06-工作樹裡開的.md" ]; then
  ok "在 worktree 裡開票看得到主目錄與別棵 worktree 未提交的票（兩個工作區先後取號不重號）"
else
  err "在 worktree 裡開票沒跳過別處未提交的號（期望 TESTD-06，實得：$(ls "$MINE/tickets" | grep TESTD || echo 無)）"
fi

# ── 工作樹的資料夾名不能被當成「這個號碼已被佔用」（源專案 v4.94.1）──────────
#
# 取號用 `grep -oE "PREFIX-[0-9]+"` 掃 `ls` 的輸出，而 `ls` 印的是**完整路徑**。
# `make worktree n=AMY-17` 開出來的工作樹路徑 `.claude/worktrees/AMY-17/tickets/…`
# 自己就含 `AMY-17`，於是剛開的工作樹把自己的號碼佔走，新票被跳號成 18
# （先開工作樹、再在裡面開票是常態，所以每次都會觸發）。
# 這條照事故造：工作樹名是 TESTE-07，沒有任何 07 號的票檔，只有一張已提交的 TESTE-03，
# 正確結果是 TESTE-04（不是 08）。路徑裡的名字會從三條路進來：本機票檔、其他工作樹、
# 工作樹自己的 TICKETS_DIR，所以在 worktree 裡跑才測得到。
WT_E="$SANDBOX/wte"
mkdir -p "$WT_E/tickets"
git init -q "$WT_E"
wte_git() { git -C "$WT_E" -c user.email=t@t -c user.name=t \
  -c commit.gpgsign=false -c core.hooksPath=/dev/null "$@"; }
# 03 號票要**先提交**：真實的工作樹是 checkout，會帶著所有已提交的票檔，
# `ls` 才會印出含工作樹名的完整路徑（沒有票檔的工作樹不會重現）
write_ticket "$WT_E/tickets/TESTE-03-主目錄的票.md" "TESTE-03" "主目錄的票"
wte_git add "tickets/TESTE-03-主目錄的票.md" && wte_git commit -qm base >/dev/null
wte_git worktree add -q "$WT_E/.claude/worktrees/TESTE-07" -b teste07 2>/dev/null
MINE_E="$WT_E/.claude/worktrees/TESTE-07"
mkdir -p "$MINE_E/scripts" "$MINE_E/tickets"
cp "$ROOT/scripts/new-ticket.sh" "$MINE_E/scripts/new-ticket.sh"
( unset GIT_DIR; TICKET_PREFIX=TESTE TICKET_REMOTE=__no_such_remote__ \
    bash "$MINE_E/scripts/new-ticket.sh" "同名工作樹裡開的" "管理員" >/dev/null 2>&1 )
if [ -f "$MINE_E/tickets/TESTE-04-同名工作樹裡開的.md" ]; then
  ok "工作樹資料夾名（TESTE-07）不會佔走自己的號碼"
else
  err "工作樹資料夾名被當成已用號碼（期望 TESTE-04，實得：$(ls "$MINE_E/tickets" | grep TESTE || echo 無)）"
fi

# 15) 遠端分支上的中文檔名票也要算進去，不受使用者 core.quotepath 設定影響（源專案 v4.94.1）
#     git 預設 quotepath=true 時 `ls-tree --name-only` 會把中文檔名輸出成 "tickets/…\351…"，
#     行首錨點 `^tickets/` 就對不上、漏算遠端已有的號碼＝撞號。真實票檔幾乎都是中文標題。
WT_F="$SANDBOX/wtf"
git init -q "$WT_F" && mkdir -p "$WT_F/tickets" "$WT_F/scripts"
git init -q --bare "$SANDBOX/wtf-remote.git"
wtf_git() { git -C "$WT_F" -c user.email=t@t -c user.name=t \
  -c commit.gpgsign=false -c core.hooksPath=/dev/null "$@"; }
write_ticket "$WT_F/tickets/TESTF-05-遠端的中文標題.md" "TESTF-05" "遠端的中文標題"
wtf_git add "tickets/TESTF-05-遠端的中文標題.md" && wtf_git commit -qm base >/dev/null
wtf_git remote add origin "$SANDBOX/wtf-remote.git"
wtf_git push -q origin HEAD:refs/heads/stage 2>/dev/null
wtf_git rm -q "tickets/TESTF-05-遠端的中文標題.md" && wtf_git commit -qm "本機沒有這張" >/dev/null
mkdir -p "$WT_F/tickets"   # git rm 會把空資料夾一起刪掉
git -C "$WT_F" config core.quotepath true
cp "$ROOT/scripts/new-ticket.sh" "$WT_F/scripts/new-ticket.sh"
( unset GIT_DIR; GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 TICKET_PREFIX=TESTF \
    bash "$WT_F/scripts/new-ticket.sh" "遠端取號" "管理員" >/dev/null 2>&1 )
if [ -f "$WT_F/tickets/TESTF-06-遠端取號.md" ]; then
  ok "遠端分支上的中文檔名票有算進去（core.quotepath=true 也一樣）"
else
  err "遠端的中文檔名票被漏算（期望 TESTF-06，實得：$(ls "$WT_F/tickets" | grep TESTF || echo 無)）"
fi

# 15b) 還沒設遠端的全新專案：「取號納入 N 條遠端分支」那一行要是完整的一行（移植時補的回歸）。
#      `grep -c` 在零筆時自己會印 0、結束碼是 1；後面接 `|| echo 0` 會再印一個 0，訊息斷成
#      「…取號納入 0」「0 條遠端分支上的票）」兩行。源專案永遠有遠端，這條路沒被走過。
NOREMOTE="$SANDBOX/noremote"
git init -q "$NOREMOTE" && mkdir -p "$NOREMOTE/tickets" "$NOREMOTE/scripts"
cp "$ROOT/scripts/new-ticket.sh" "$NOREMOTE/scripts/new-ticket.sh"
noremote_out=$( unset GIT_DIR; GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 TICKET_PREFIX=TESTH \
    bash "$NOREMOTE/scripts/new-ticket.sh" "還沒設遠端" "管理員" 2>&1 ); noremote_rc=$?
if [ "$noremote_rc" -eq 0 ] && grep -qF "取號納入 0 條遠端分支上的票" <<<"$noremote_out"; then
  ok "還沒設遠端時，取號訊息是完整的一行（納入 0 條遠端分支）"
else
  err "還沒設遠端時，取號訊息不對（exit ${noremote_rc}）：$(head -3 <<<"$noremote_out")"
fi
if [ -f "$NOREMOTE/tickets/TESTH-01-還沒設遠端.md" ]; then
  ok "還沒設遠端也開得出第一張票（TESTH-01）"
else
  err "還沒設遠端時沒開出 TESTH-01（實得：$(ls "$NOREMOTE/tickets" | grep TESTH || echo 無)）"
fi

# 15c) 遠端連不上（離線）：要印提醒、退回這台機器看得到的最大號，票照樣開得出來（移植時補的）。
#      遠端指到沙盒裡一個不存在的資料夾，fetch 一定失敗，也不會對外連線。
DEADREMOTE="$SANDBOX/offline"
git init -q "$DEADREMOTE" && mkdir -p "$DEADREMOTE/tickets" "$DEADREMOTE/scripts"
git -C "$DEADREMOTE" remote add origin "$SANDBOX/no-such-remote.git"
write_ticket "$DEADREMOTE/tickets/TESTH-04-本機已有的票.md" "TESTH-04" "本機已有的票"
cp "$ROOT/scripts/new-ticket.sh" "$DEADREMOTE/scripts/new-ticket.sh"
offline_out=$( unset GIT_DIR; GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 TICKET_PREFIX=TESTH \
    bash "$DEADREMOTE/scripts/new-ticket.sh" "離線開的" "管理員" 2>&1 ); offline_rc=$?
if [ "$offline_rc" -eq 0 ] && grep -qF "fetch 失敗" <<<"$offline_out" \
   && [ -f "$DEADREMOTE/tickets/TESTH-05-離線開的.md" ]; then
  ok "遠端連不上時印提醒、退回本機最大號照樣開票（TESTH-05）"
else
  err "遠端連不上時的取號不對（exit ${offline_rc}，期望 TESTH-05 與「fetch 失敗」的提醒；實得：$(ls "$DEADREMOTE/tickets" | grep TESTH-05 || echo 無)）：$(head -3 <<<"$offline_out")"
fi

# 15d) 取號的邊角（模板內補的：突變測試抓到這三種寫壞了原本沒有案例會紅）
run_new_ticket_in() {  # $1=tickets 目錄 $2=prefix $3=title（要自己的資料夾、要看得到錯誤訊息時用）
  GIT_DIR="$FAKE_GIT_DIR" GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
  TICKETS_DIR="$1" TICKET_PREFIX="$2" TICKET_REMOTE="__no_such_remote__" \
    bash "$ROOT/scripts/new-ticket.sh" "$3" "管理員" 2>&1
}
EDGE="$SANDBOX/edge-lower"; mkdir -p "$EDGE"
edge_out=$(run_new_ticket_in "$EDGE" amy "小寫前綴"); edge_rc=$?
edge_files=$(ls "$EDGE")
if [ "$edge_rc" -eq 2 ] && grep -qF "前綴格式錯誤" <<<"$edge_out" && [ -z "$edge_files" ]; then
  ok "前綴是小寫（amy）→ 擋、不開檔"
else
  err "小寫前綴應擋（exit 2、「前綴格式錯誤」、不開檔），實得 exit ${edge_rc}、檔案：${edge_files:-無}：$(head -2 <<<"$edge_out")"
fi
EDGE="$SANDBOX/edge-100"; mkdir -p "$EDGE"
write_ticket "$EDGE/TESTM-99-舊.md" "TESTM-99" "舊"
write_ticket "$EDGE/TESTM-100-舊.md" "TESTM-100" "舊"
edge_out=$(run_new_ticket_in "$EDGE" TESTM "破百"); edge_rc=$?
if [ "$edge_rc" -eq 0 ] && [ -f "$EDGE/TESTM-101-破百.md" ]; then
  ok "已有 -99 與 -100：下一張是 -101（照數字比，不是照字串）"
else
  err "已有 -99 與 -100 時下一張應是 TESTM-101，實得 exit ${edge_rc}、檔案：$(ls "$EDGE" | tr '\n' ' ')"
fi
EDGE="$SANDBOX/edge-08"; mkdir -p "$EDGE"
write_ticket "$EDGE/TESTO-08-舊.md" "TESTO-08" "舊"
edge_out=$(run_new_ticket_in "$EDGE" TESTO "零八之後"); edge_rc=$?
if [ "$edge_rc" -eq 0 ] && [ -f "$EDGE/TESTO-09-零八之後.md" ]; then
  ok "已有 -08：下一張是 -09（前導零不被當八進位）"
else
  err "已有 -08 時下一張應是 TESTO-09，實得 exit ${edge_rc}、檔案：$(ls "$EDGE" | tr '\n' ' ')：$(head -2 <<<"$edge_out")"
fi

# ── 〈這次可能會弄壞什麼〉：一行一個 W 編號，每個編號要有對應的驗收／走查行 ──────
#
# 16) 範本的多行 HTML 註解留在這一節裡，不能被當成「沒編號的風險行」（源專案 v4.83.0）
mkdir -p "$SANDBOX/commentlocal/tickets"
COMMENT_T="$SANDBOX/commentlocal/tickets/TESTC-09-留著範本註解的票.md"
write_ticket "$COMMENT_T" "TESTC-09" "留著範本註解的票"
cat >> "$COMMENT_T" <<'TICKETEOF'

## 這次可能會弄壞什麼

<!-- 一行一個編號（W1、W2…）：這次改動有機會波及、但**不打算改**的頁面或功能，
     **以及需求要求其他頁也要檢查或修的（不論寫成一併、同款、也要、一起；一頁一個編號）**。
     推 stage 前每個 W 都要在〈開發備註〉（或〈走查〉節）交代「走查（…）W1 …」，或照 user-walkthrough〈跳過之後怎麼做〉的三行寫「沒走的是：W1 …」，
     推 stage 前的走查紀錄檢查會擋（可先跑 make walkthrough-lint；源專案 v5.30.0）。
     〈驗收標準〉或〈走查〉要有以同一個編號開頭的行。真的沒有就寫「不適用：<理由>」。
     由來（源專案）：某張票的邊界寫了「不動隔壁那個畫面」，五條驗收標準卻沒有一條關於它，
     三天後那個畫面的五個互動在整合環境壞了一整天。 -->

- W1 訂單清單頁

## 驗收標準

- [ ] W1 訂單清單頁開得起來
TICKETEOF
# 〈這次可能會弄壞什麼〉只檢查「符合資格＋有改動」的票；拿不到比對基線時會退成檢查全部符合資格的票，
# 沙盒就走這條路（created 要在規則生效日當天或之後）。
sed -i.bak "s/^created: .*/created: ${NEW}/" "$COMMENT_T" && rm -f "$COMMENT_T.bak"
comment_out=$(TICKETS_DIR="$SANDBOX/commentlocal/tickets" TICKET_LINT_BASE=__no_such_base__ \
  bash "$ROOT/scripts/ticket-lint.sh" 2>&1); comment_rc=$?
if grep -q "TESTC-09.*沒有編號" <<<"$comment_out"; then
  err "多行範本註解被當成沒編號的風險行。lint 輸出：$(grep TESTC-09 <<<"$comment_out" | head -2)"
elif [ "$comment_rc" -ne 0 ]; then
  err "留著範本註解、W1 也有對應驗收行的票卻紅了（exit ${comment_rc}）：$(head -3 <<<"$comment_out")"
else
  ok "多行範本註解不會被當成風險行"
fi

# 17) 這條規則自己「會紅」的案例（源專案只有上面那條反向案例；這一組是移植時補的）：
#     沒有這幾條，規則被改壞成永遠綠，上面那條照樣過。
risk_case() {  # $1=名稱 $2=pass|fail $3=紅燈時要出現的字（pass 時留空） $4=風險節到驗收節的內文（可空＝整節不寫） [$5=status] [$6=created] [$7=生效日，預設 $SINCE]
  local name="$1" expect="$2" want="$3" body="$4" status="${5:-開發中}" created="${6-$NEW}" since="${7-$SINCE}"
  local d="$SANDBOX/risk" out rc
  rm -rf "$d"; mkdir -p "$d"
  cat > "$d/TESTR-01-案例.md" <<TICKETEOF
---
id: TESTR-01
title: 案例
status: $status
roles: [管理員]
owner: tester
spec:
created: $created
updated: $created
---

## 需求細節

純文字調整。

$body
TICKETEOF
  out=$(TICKET_RULES_SINCE="$since" TICKETS_DIR="$d" TICKET_LINT_BASE=__no_such_ref__ bash "$ROOT/scripts/ticket-lint.sh" 2>&1); rc=$?
  if [ "$expect" = pass ]; then
    if [ "$rc" -eq 0 ]; then ok "風險編號：${name}"; else err "風險編號：${name}——不該紅卻紅了：$(head -3 <<<"$out")"; fi
  else
    if [ "$rc" -ne 0 ] && grep -qF -- "$want" <<<"$out"; then ok "風險編號：${name}"
    else err "風險編號：${name}——該紅沒紅，或訊息不對（要有「${want}」，exit ${rc}）：$(head -3 <<<"$out")"; fi
  fi
}
RISK_OK='## 這次可能會弄壞什麼

- W1 訂單清單頁

## 驗收標準

- [ ] W1 訂單清單頁的搜尋、換頁各按一次'
risk_case "W1 有對應的驗收行 → 過" pass "" "$RISK_OK"
risk_case "開發中的新票沒有這一節 → 擋" fail "缺〈這次可能會弄壞什麼〉這一節" '## 驗收標準

- [ ] 改完的文字正確'
risk_case "生效日前一天建立的票不擋" pass "" '## 驗收標準

- [ ] 改完的文字正確' 開發中 "$OLD"
risk_case "生效日當天建立的票要擋（含當天）" fail "缺〈這次可能會弄壞什麼〉這一節" '## 驗收標準

- [ ] 改完的文字正確' 開發中 "$SINCE"
risk_case "待開發的票不擋（還沒動工）" pass "" '## 驗收標準

- [ ] 改完的文字正確' 待開發
risk_case "完成的票也要擋" fail "缺〈這次可能會弄壞什麼〉這一節" '## 驗收標準

- [ ] 改完的文字正確' 完成
risk_case "這一節裡有一行沒編號 → 擋" fail "沒有編號" '## 這次可能會弄壞什麼

- W1 訂單清單頁
- 訂單明細頁

## 驗收標準

- [ ] W1 訂單清單頁的搜尋、換頁各按一次'
risk_case "這一節是空的 → 擋" fail "是空的" '## 這次可能會弄壞什麼

## 驗收標準

- [ ] 改完的文字正確'
risk_case "W2 沒有對應的驗收行 → 擋" fail "W2 沒有對應的驗收／走查條件" '## 這次可能會弄壞什麼

- W1 訂單清單頁
- W2 訂單明細頁

## 驗收標準

- [ ] W1 訂單清單頁的搜尋、換頁各按一次'
risk_case "W10 沒有對應的驗收行（W1 有）→ 擋，點名 W10（模板內補的）" fail "W10 沒有對應的驗收／走查條件" '## 這次可能會弄壞什麼

- W1 訂單清單頁
- W10 會員頁

## 驗收標準

- [ ] W1 訂單清單頁的搜尋、換頁各按一次'
risk_case "完成的票沒填 spec → 擋（模板內補的）" fail "完成的票必須有 spec 欄位" "$RISK_OK" 完成
risk_case "對應行寫在〈走查〉節也算" pass "" '## 這次可能會弄壞什麼

- W1 訂單清單頁

## 驗收標準

- [ ] 改完的文字正確

## 走查

- W1 訂單清單頁：搜尋、換頁各按一次'
risk_case "整節寫「不適用：<理由>」→ 過" pass "" '## 這次可能會弄壞什麼

不適用：只改一句說明文字，不碰任何頁面的互動

## 驗收標準

- [ ] 改完的文字正確'
# 生效日留空＝所有票都套用（連建立日很早的也算）
risk_case "生效日留空 → 很早建立的票也擋" fail "缺〈這次可能會弄壞什麼〉這一節" '## 驗收標準

- [ ] 改完的文字正確' 開發中 "1999-01-01" ""
# 生效日留空時，沒填 created 的票也算；有設生效日時，沒填 created 的票不查
risk_case "生效日留空 → 沒填 created 的票也擋" fail "缺〈這次可能會弄壞什麼〉這一節" '## 驗收標準

- [ ] 改完的文字正確' 開發中 "" ""
risk_case "有設生效日 → 沒填 created 的票不查" pass "" '## 驗收標準

- [ ] 改完的文字正確' 開發中 ""
# 生效日寫錯格式：日期是用字串比大小的，寫成 2025/06/01 會讓每張票都排在它前面、整條規則靜靜關掉
risk_case "生效日格式錯誤 → 明講並紅燈" fail "TICKET_RULES_SINCE 格式錯誤" "$RISK_OK" 開發中 "$NEW" "2025/06/01"

# 18) tickets/ 一張票都沒有（全新專案）：不能紅，要印得出一句話
mkdir -p "$SANDBOX/empty"
empty_out=$(TICKETS_DIR="$SANDBOX/empty" TICKET_LINT_BASE=__no_such_ref__ bash "$ROOT/scripts/ticket-lint.sh" 2>&1); empty_rc=$?
if [ "$empty_rc" -eq 0 ] && grep -q "尚無票" <<<"$empty_out"; then
  ok "tickets/ 零票時 lint 結束碼 0（全新專案不會一開始就紅）"
else
  err "tickets/ 零票時 lint 沒有乾淨結束（exit ${empty_rc}）：$(head -3 <<<"$empty_out")"
fi

# ── 〈條件確認〉：自己加的條件要附筆數（源專案 v5.5.0）──────────────────────
# 由來（源專案）：agent 自己加的出現條件，案主同意了卻沒細看，上線後正式環境大量真實資料被擋。
# 這幾條是「故意種一個該紅的案例，確認真的會紅」——同時各放一條該綠的，防止規則誤傷。
# 沙盒票的風險節一律寫「不適用」，免得被〈這次可能會弄壞什麼〉那條擋走、測不到本條。
cond_case() {  # $1=名稱 $2=pass|fail $3=紅燈時要出現的字（pass 時留空） $4=〈條件確認〉之前的內文 $5=條件確認那一節（含標題，可空） [$6=status] [$7=created]
  local name="$1" expect="$2" want="$3" pre="$4" sec="$5" status="${6:-開發中}" created="${7:-$NEW}"
  local dir="$SANDBOX/cond-$name"
  mkdir -p "$dir"
  cat > "$dir/TESTK-01-條件確認案例.md" <<TICKETEOF
---
id: TESTK-01
title: 條件確認案例
status: $status
roles: [管理員]
owner: tester
spec:
created: $created
updated: $created
---

## 需求細節

$pre

$sec

## 這次可能會弄壞什麼

不適用：沙盒案例

## 驗收標準

- [ ] 略
TICKETEOF
  local out rc
  out=$(TICKETS_DIR="$dir" TICKET_LINT_BASE=__no_such_ref__ bash "$ROOT/scripts/ticket-lint.sh" 2>&1); rc=$?
  if [ "$expect" = "fail" ]; then
    if [ "$rc" -ne 0 ] && grep -qF -- "$want" <<<"$out"; then
      ok "〈條件確認〉${name}：該紅就紅"
    else
      err "〈條件確認〉${name}：應該紅（含「${want}」）卻沒有。rc=$rc 輸出：$(head -3 <<<"$out")"
    fi
  else
    if [ "$rc" -eq 0 ]; then ok "〈條件確認〉${name}：該綠就綠"; else err "〈條件確認〉${name}：不該紅卻紅了：$(head -3 <<<"$out")"; fi
  fi
}
COND_HEAD='| 條件（含分母） | 符合 | 擋掉 | 狀態 | 回答日 |
|---|---|---|---|---|'
cond_case "有字樣沒有這一節" fail "沒有〈條件確認〉這一節" "附件區至少一份附件才出現確認勾選。" ""
cond_case "字樣只出現在標題列也要算" fail "沒有〈條件確認〉這一節" "### 預設篩選
略。" ""
cond_case "沒字樣沒有這一節" pass "" "把按鈕文字改成「送出」。" ""
cond_case "字樣只在範本註解裡" pass "" "把按鈕文字改成「送出」。" "<!-- 範例：回填、篩選、出現條件 -->"
cond_case "待開發的票不擋" pass "" "舊單一次回填。" "" 待開發
cond_case "生效日前一天建立的票不擋" pass "" "舊單一次回填。" "" 開發中 "$OLD"
cond_case "生效日當天建立的票要擋（含當天）" fail "沒有〈條件確認〉這一節" "舊單一次回填。" "" 開發中 "$SINCE"
cond_case "正確的表" pass "" "舊單一次回填。" "## 條件確認

$COND_HEAD
| 已審核的申請單，附件區至少一份附件才出現（分母：prod 已審核的申請單共 3707 筆） | 10 筆 | 3697 筆 | 已確認 | 2025-06-12 |
| 舊單回填（分母：prod 舊申請單共 9 張） | 9 張 | 0 張 | 未確認 | |"
cond_case "不適用附理由" pass "" "舊單一次回填。" "## 條件確認

不適用：這張票只改文案，不新增任何條件"
cond_case "不適用沒理由" fail "沒有理由" "舊單一次回填。" "## 條件確認

不適用"
cond_case "留著範例列" fail "範本的範例列" "舊單一次回填。" "## 條件確認

$COND_HEAD
| （例）已審核的申請單，附件區至少一份附件才出現確認勾選（分母：prod 已審核的申請單共 3707 筆） | 10 筆 | 3697 筆 | 未確認 | |"
cond_case "狀態寫成別的字" fail "要寫「已確認」、「未確認」或「待 prod 資料」" "舊單一次回填。" "## 條件確認

$COND_HEAD
| 舊單回填（分母：9 張） | 9 張 | 0 張 | 先略過 | |"
# 源專案 v5.41.0：「待 prod 資料」只給要看到 prod 筆數才答得出來的列——要「查不到：」開頭＋案主同意延後的回答日
cond_case "待 prod 資料＋查不到＋回答日" pass "" "舊單一次回填。" "## 條件確認

$COND_HEAD
| 舊單回填（分母：不明） | 查不到：prod 沒有這欄資料 | 查不到：同左 | 待 prod 資料 | 2025-06-12 |"
cond_case "待 prod 資料沒有回答日" fail "標了「待 prod 資料」卻沒有回答日" "舊單一次回填。" "## 條件確認

$COND_HEAD
| 舊單回填（分母：不明） | 查不到：prod 沒有這欄資料 | 查不到：同左 | 待 prod 資料 | |"
cond_case "待 prod 資料但兩格都有筆數" fail "不是「查不到：<原因>」開頭" "舊單一次回填。" "## 條件確認

$COND_HEAD
| 舊單回填（分母：9 張） | 9 張 | 0 張 | 待 prod 資料 | 2025-06-12 |"
cond_case "待 prod 資料寫「未查」" fail "不是「查不到：<原因>」開頭" "舊單一次回填。" "## 條件確認

$COND_HEAD
| 舊單回填（分母：不明） | 未查 | 未查 | 待 prod 資料 | 2025-06-12 |"
cond_case "已確認沒有回答日" fail "已確認卻沒有回答日" "舊單一次回填。" "## 條件確認

$COND_HEAD
| 舊單回填（分母：9 張） | 9 張 | 0 張 | 已確認 | |"
cond_case "擋掉沒填筆數" fail "〈擋掉〉沒填筆數" "舊單一次回填。" "## 條件確認

$COND_HEAD
| 舊單回填（分母：9 張） | 9 張 | | 未確認 | |"
cond_case "查不到可以寫原因" pass "" "舊單一次回填。" "## 條件確認

$COND_HEAD
| 舊單回填（分母：不明） | 查不到：prod 唯讀連線被擋 | 查不到：prod 唯讀連線被擋 | 未確認 | |"
cond_case "表頭缺欄位" fail "表頭缺欄位：回答日" "舊單一次回填。" "## 條件確認

| 條件 | 符合 | 擋掉 | 狀態 |
|---|---|---|---|
| 舊單回填 | 9 張 | 0 張 | 未確認 |"
# 多個欄位同時缺：訊息去掉前綴用 sub(/^、/,"")，不用 substr(miss, 4)——後者在 gawk（以字元算）與 macOS 內建的 awk（以位元組算）
# 切出來不一樣：源專案因此在 CI 少印一個欄位名、檢查紅、多推一次（源專案 v5.9.0）。
# 各語系都跑一遍：有的語系在本機不存在會退成 C，無害。
for _loc in C en_US.UTF-8 C.UTF-8; do
  LC_ALL=$_loc cond_case "表頭缺三欄（${_loc}）" fail "表頭缺欄位：擋掉、狀態、回答日（" "舊單一次回填。" "## 條件確認

| 條件 | 符合 |
|---|---|
| 舊單回填 | 9 張 |"
  LC_ALL=$_loc cond_case "不適用只寫一個字（${_loc}）" fail "沒有理由" "舊單一次回填。" "## 條件確認
不適用：無"
  # 「只改」位元組算 6、字元算 2：拿掉 ticket-lint.sh 的 LC_ALL=C，gawk＋UTF-8 這一輪就會紅（少了這條，兩種算法的結果一樣、測不出來）
  LC_ALL=$_loc cond_case "不適用只寫兩個字的理由（${_loc}）" pass "" "舊單一次回填。" "## 條件確認
不適用：只改"
  LC_ALL=$_loc cond_case "不適用寫了完整的理由（${_loc}）" pass "" "舊單一次回填。" "## 條件確認
不適用：只改文案"
done
cond_case "只有標題沒有表" fail "沒有表格" "舊單一次回填。" "## 條件確認

之後再補"

# 新開的票照範本（new-ticket.sh）原樣動工時：範例列沒換掉要紅——範本本身也要能被 lint 讀懂（欄位對得上）
run_new_ticket "TESTK" "範本原樣" >/dev/null
tpl="$SANDBOX/TESTK-01-範本原樣.md"
sed -i.bak -e 's/^status: .*/status: 開發中/' -e "s/^created: .*/created: ${NEW}/" "$tpl" && rm -f "$tpl.bak"
tpl_out=$(run_lint)
tpl_errs=$(grep 'TESTK-01' <<<"$tpl_out" | grep -v '\[ticket-lint\]\[warn\]')
if grep -q "範本的範例列" <<<"$tpl_errs"; then
  ok "範本原樣的〈條件確認〉範例列會被抓到（範本與 lint 欄位對得上）"
else
  err "範本裡的〈條件確認〉範例列沒被抓到。輸出：$(head -3 <<<"$tpl_errs")"
fi
# 範本原樣動工只該紅這一條：W1 與驗收行對得上、沒有會觸發〈數字口徑〉的字樣（票範本、lint、說明三者要對得起來）
tpl_err_count=$(grep -c . <<<"$tpl_errs")
if [ "$tpl_err_count" -eq 1 ]; then
  ok "範本原樣動工只紅「範例列」這一條（範本其餘段落 lint 都讀得懂）"
else
  err "範本原樣動工紅了 ${tpl_err_count} 條（應該只有範例列那一條）：$(head -5 <<<"$tpl_errs")"
fi
rm -f "$tpl"

# 〈條件確認〉補充案例：理由太短、半形冒號、表格壞掉
cond_case "不適用只寫一個字也算沒理由" fail "沒有理由" "舊單一次回填。" "## 條件確認

不適用：無"
cond_case "半形冒號的不適用沒理由" fail "沒有理由" "舊單一次回填。" "## 條件確認

不適用: "
cond_case "某一列沒有開頭的 |" fail "沒有開頭的 |" "舊單一次回填。" "## 條件確認

$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 已確認 | 2025-06-12 |
條件乙（分母：5 張） | 1 張 | 4 張 | 未確認 | |"
cond_case "表前多一行不適用的說明、表是好的" pass "" "舊單一次回填。" "## 條件確認

不適用的部分：下面只列一條會讓資料消失的

$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 未確認 | |"
cond_case "表前有不適用說明、表壞了還是要紅" fail "狀態" "舊單一次回填。" "## 條件確認

不適用的部分：下面只列一條會讓資料消失的

$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 差不多 | |"

# ── 〈數字口徑〉：給人看的數字要寫口徑（源專案 v5.19.0）──────────────────────
# 同上：故意種該紅的、也各放該綠的。沙盒票的風險節一律寫「不適用」。
num_case() {  # $1=名稱 $2=pass|fail $3=紅燈時要出現的字 $4=內文 $5=〈數字口徑〉那一節（含標題，可空） [$6=status] [$7=created]
  local name="$1" expect="$2" want="$3" pre="$4" sec="$5" status="${6:-開發中}" created="${7:-$NEW}"
  local dir="$SANDBOX/num-$name"
  mkdir -p "$dir"
  cat > "$dir/TESTN-01-數字口徑案例.md" <<TICKETEOF
---
id: TESTN-01
title: 數字口徑案例
status: $status
roles: [管理員]
owner: tester
spec:
created: $created
updated: $created
---

## 需求細節

$pre

$sec

## 這次可能會弄壞什麼

不適用：沙盒案例

## 驗收標準

- [ ] 略
TICKETEOF
  local out rc
  out=$(TICKETS_DIR="$dir" TICKET_LINT_BASE=__no_such_ref__ bash "$ROOT/scripts/ticket-lint.sh" 2>&1); rc=$?
  if [ "$expect" = "fail" ]; then
    if [ "$rc" -ne 0 ] && grep -qF -- "$want" <<<"$out"; then ok "〈數字口徑〉${name}：該紅就紅"
    else err "〈數字口徑〉${name}：應該紅（含「${want}」）卻沒有。rc=$rc 輸出：$(head -3 <<<"$out")"; fi
  else
    if [ "$rc" -eq 0 ]; then ok "〈數字口徑〉${name}：該綠就綠"; else err "〈數字口徑〉${name}：不該紅卻紅了：$(head -3 <<<"$out")"; fi
  fi
}
NUM_HEAD='| 數字 | 期間與時間欄位 | 時區 | 算哪些 | 同一筆算幾次 | 加總／平均／比例 | 空值 | 跟站上哪個數字同口徑 | 狀態 | 回答日 |
|---|---|---|---|---|---|---|---|---|---|'
num_case "有字樣沒有這一節" fail "沒有〈數字口徑〉這一節" "首頁加一張準時出貨率的統計卡。" ""
num_case "字樣只出現在標題列也要算" fail "沒有〈數字口徑〉這一節" "### 營運儀表板
略。" ""
num_case "沒字樣沒有這一節" pass "" "把按鈕文字改成「送出」。" ""
num_case "字樣只在範本註解裡" pass "" "把按鈕文字改成「送出」。" "<!-- 範例：成功率、比例、平均 -->"
num_case "待開發的票不擋" pass "" "首頁加一張成功率卡。" "" 待開發
num_case "生效日前一天建立的票不擋" pass "" "首頁加一張成功率卡。" "" 開發中 "$OLD"
num_case "生效日當天建立的票要擋（含當天）" fail "沒有〈數字口徑〉這一節" "首頁加一張成功率卡。" "" 開發中 "$SINCE"
num_case "不適用有理由" pass "" "首頁加一張成功率卡。" "## 數字口徑

不適用：只改卡片顏色，數字不動"
num_case "不適用沒理由" fail "沒有理由" "首頁加一張成功率卡。" "## 數字口徑

不適用：無"
num_case "正確的表" pass "" "首頁加一張成功率卡。" "## 數字口徑

$NUM_HEAD
| 準時出貨率 | 出貨日 | 台北 | 不含取消 | 一筆一次 | 準時出貨數÷出貨數 | 不算 | 同首頁統計卡 | 已確認 | 2025-06-12 |"
num_case "狀態寫成別的字" fail "要寫「已確認」或「未確認」" "首頁加一張成功率卡。" "## 數字口徑

$NUM_HEAD
| 準時出貨率 | 出貨日 | 台北 | 不含取消 | 一筆一次 | 準時出貨數÷出貨數 | 不算 | 同首頁統計卡 | 差不多 | |"
num_case "口徑狀態寫「待 prod 資料」→ 仍紅（口徑沒有延後這個例外）" fail "要寫「已確認」或「未確認」" "首頁加一張成功率卡。" "## 數字口徑

$NUM_HEAD
| 準時出貨率 | 建立時間 | 台北 | 全部 | 一次 | 比例 | 不算 | 同首頁 | 待 prod 資料 | 2025-06-12 |"
num_case "已確認沒有回答日" fail "已確認卻沒有回答日" "首頁加一張成功率卡。" "## 數字口徑

$NUM_HEAD
| 準時出貨率 | 出貨日 | 台北 | 不含取消 | 一筆一次 | 準時出貨數÷出貨數 | 不算 | 同首頁統計卡 | 已確認 | |"
num_case "留著範例列" fail "範本的範例列" "首頁加一張成功率卡。" "## 數字口徑

$NUM_HEAD
| （例）準時出貨率 | 出貨日 | 台北 | 不含取消 | 一筆一次 | 準時出貨數÷出貨數 | 不算 | 同首頁統計卡 | 未確認 | |"
num_case "有標題沒有表格" fail "沒有表格" "首頁加一張成功率卡。" "## 數字口徑

（之後補）"

# ── 推 prod 前的條件確認檢查：scripts/unconfirmed-conditions.sh 給票號清單的那條路（源專案 v5.5.0）──
# 判準是「不是已確認就擋」，而且找不到票檔不能被當成「沒有未確認」（靜靜綠燈的假保護）。
UC="$SANDBOX/uc"
mkdir -p "$UC"
uc_ticket() {  # $1=票號 $2=〈條件確認〉那一節（含標題，可空）
  cat > "$UC/$1-案例.md" <<TICKETEOF
---
id: $1
title: 案例
status: 完成
roles: [管理員]
spec:
created: $NEW
updated: $NEW
---

## 需求細節

略

$2
TICKETEOF
}
uc_run() { TICKETS_DIR="$UC" bash "$ROOT/scripts/unconfirmed-conditions.sh" "$@" 2>&1; }
uc_expect() {  # $1=名稱 $2=預期結束碼 $3=輸出要出現的字（可空） 其餘=票號
  local name="$1" want_rc="$2" want_txt="$3"; shift 3
  local out rc; out=$(uc_run "$@"); rc=$?
  if [ "$rc" -eq "$want_rc" ] && { [ -z "$want_txt" ] || grep -qF -- "$want_txt" <<<"$out"; }; then
    ok "上 prod 的關：$name"
  else
    err "上 prod 的關：${name}——預期 rc=$want_rc 含「${want_txt}」，實得 rc=${rc}：$(head -3 <<<"$out")"
  fi
}
UC_HEAD='| 條件（含分母） | 符合 | 擋掉 | 狀態 | 回答日 |
|---|---|---|---|---|'
uc_ticket TESTU-01 "## 條件確認

$UC_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 已確認 | 2025-06-12 |"
uc_ticket TESTU-02 "## 條件確認

$UC_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 已確認 | 2025-06-12 |
| 條件乙（分母：50 張） | 3 張 | 47 張 | 未確認 | |"
uc_ticket TESTU-03 "## 條件確認

$UC_HEAD
| 條件丙（分母：50 張） | 3 張 | 47 張 | | |"
uc_ticket TESTU-04 "## 條件確認

$UC_HEAD
| 條件丁（分母：50 張） | 3 張 | 47 張 | 差不多確認了 | |"
uc_ticket TESTU-05 ""
uc_ticket TESTU-06 "## 條件確認

不適用：只改文案"
uc_ticket TESTU-07 "## 條件確認

之後再補"
uc_ticket TESTU-010 "## 條件確認

$UC_HEAD
| 條件戊（分母：5 張） | 1 張 | 4 張 | 未確認 | |"
uc_ticket TESTU-08 "" ; sed -i.bak 's/^略$/附件區至少一份附件才出現確認勾選。/' "$UC/TESTU-08-案例.md" && rm -f "$UC/TESTU-08-案例.md.bak"
uc_ticket TESTU-09 "" ; sed -i.bak -e 's/^略$/附件區至少一份附件才出現確認勾選。/' -e "s/^created: .*/created: ${OLD}/" "$UC/TESTU-09-案例.md" && rm -f "$UC/TESTU-09-案例.md.bak"
uc_ticket TESTU-14 "" ; sed -i.bak -e 's/^略$/附件區至少一份附件才出現確認勾選。/' -e "s/^created: .*/created: ${SINCE}/" "$UC/TESTU-14-案例.md" && rm -f "$UC/TESTU-14-案例.md.bak"
uc_ticket TESTU-11 "## 條件確認

$UC_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 已確認 | 2025-06-12 |
條件乙（分母：5 張） | 1 張 | 4 張 | 未確認 | |"
uc_ticket TESTU-12 "## 條件確認

不適用的部分：下面只列一條

$UC_HEAD
| 條件乙（分母：5 張） | 1 張 | 4 張 | 未確認 | |"
uc_expect "全部已確認放行" 0 "沒有未確認" TESTU-01
# 源專案 v5.41.0：「待 prod 資料」只在推 stage 時（--stage-range／--stage-ref，見 stage-confirm-gate-test.sh）放行；推 prod 前照樣算沒確認
uc_ticket TESTU-13 "## 條件確認

$UC_HEAD
| 條件己（分母：不明） | 查不到：prod 沒有這欄資料 | 查不到：同左 | 待 prod 資料 | 2025-06-12 |"
uc_expect "推 prod 前：待 prod 資料（就算格式合格）仍擋，並提示重查 prod 筆數" 1 "推 prod 前要重查 prod 筆數再問案主" TESTU-13
uc_expect "有一條未確認要擋，並印出那一條" 1 "條件乙" TESTU-02
uc_expect "狀態空白也擋（不是已確認就擋）" 1 "空白" TESTU-03
uc_expect "狀態被寫成別的詞也擋" 1 "差不多確認了" TESTU-04
uc_expect "沒有這一節不擋（舊票，或沒有自加條件）" 0 "沒有〈條件確認〉這一節（舊票，或沒有自加條件）" TESTU-05
uc_expect "不適用不擋" 0 "不適用" TESTU-06
uc_expect "有標題沒表格當作未確認" 1 "看不出表格" TESTU-07
uc_expect "找不到票檔不能當成沒有未確認" 2 "找到 0 個票檔" TESTU-99
uc_expect "票號是另一張的前綴時不會撈錯（TESTU-01 不含 TESTU-010）" 0 "沒有未確認" TESTU-01
uc_expect "有字樣、生效日之後建立、卻沒有這一節→擋（漏網的票靠這裡補）" 1 "卻沒有〈條件確認〉這一節" TESTU-08
uc_expect "同樣沒有這一節，但是生效日前一天建立→不擋" 0 "沒有〈條件確認〉這一節（舊票，或沒有自加條件）" TESTU-09
uc_expect "同樣沒有這一節，生效日當天建立→擋（含當天）" 1 "卻沒有〈條件確認〉這一節" TESTU-14
uc_expect "某一列沒有開頭的 | 不能被看漏" 1 "沒有開頭的 |" TESTU-11
uc_expect "表前有「不適用」說明但表裡有未確認→仍然擋" 1 "條件乙" TESTU-12
uc_expect "一批裡只要有一張未確認就擋" 1 "TESTU-02" TESTU-01 TESTU-02
uc_expect "一批裡有一張找不到票檔就擋" 2 "找到 0 個票檔" TESTU-01 TESTU-99

# 上 prod 的關從 origin/stage 讀票檔，不讀目前這棵樹：從 prod 開出來、只挑幾張票上線的分支上也有票檔，
# 但那是舊版，補的〈條件確認〉列只會在 stage。這裡用沙盒 repo 驗：
# 本地票檔寫「已確認」、origin/stage 上是「未確認」→ 必須擋。
# （沙盒裡只複製這一支腳本、沒有 scripts/framework-config.sh：生效日靠檔頭 export 的 TICKET_RULES_SINCE。）
GM="$SANDBOX/gm"
mkdir -p "$GM"
git -C "$GM" init -q --bare origin.git
git clone -q "$GM/origin.git" "$GM/work" 2>/dev/null
mkdir -p "$GM/work/tickets" "$GM/work/scripts"
cp "$ROOT/scripts/unconfirmed-conditions.sh" "$GM/work/scripts/"
GIT_T=(git -C "$GM/work" -c user.name=t -c user.email=t@t.invalid -c commit.gpgsign=false -c core.hooksPath=/dev/null)
"${GIT_T[@]}" checkout -q -b stage
uc_ticket TESTG-01 "## 條件確認

$UC_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 未確認 | |"
cp "$UC/TESTG-01-案例.md" "$GM/work/tickets/"
"${GIT_T[@]}" add tickets scripts >/dev/null && "${GIT_T[@]}" commit -q -m stage && "${GIT_T[@]}" push -q origin stage 2>/dev/null
"${GIT_T[@]}" checkout -q -b prod-TESTG
uc_ticket TESTG-01 "## 條件確認

$UC_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 已確認 | 2025-06-12 |"
cp "$UC/TESTG-01-案例.md" "$GM/work/tickets/"
"${GIT_T[@]}" add tickets scripts >/dev/null && "${GIT_T[@]}" commit -q -m prodcopy
gm_out=$(cd "$GM/work" && bash scripts/unconfirmed-conditions.sh TESTG-01 2>&1); gm_rc=$?
if [ "$gm_rc" -eq 1 ] && grep -qF "條件甲" <<<"$gm_out"; then
  ok "上 prod 的關：從 origin/stage 讀票檔（本地舊版寫已確認也不放行）"
else
  err "上 prod 的關：沒有從 origin/stage 讀——預期 rc=1 含「條件甲」，實得 rc=${gm_rc}：$(head -3 <<<"$gm_out")"
fi
gm_out=$(cd "$GM/work" && bash scripts/unconfirmed-conditions.sh TESTG-02 2>&1); gm_rc=$?
if [ "$gm_rc" -eq 2 ]; then ok "上 prod 的關：origin/stage 上找不到票檔→結束碼 2"; else err "上 prod 的關：origin/stage 找不到票檔應是 rc=2，實得 ${gm_rc}"; fi
# 模板內補的：本機的 stage 被改成跟 origin/stage 不一樣（寫著已確認）→ 仍然以 origin/stage 為準
"${GIT_T[@]}" branch -f stage prod-TESTG
gm_out=$(cd "$GM/work" && bash scripts/unconfirmed-conditions.sh TESTG-01 2>&1); gm_rc=$?
if [ "$gm_rc" -eq 1 ] && grep -qF "條件甲" <<<"$gm_out"; then ok "上 prod 的關：本機的 stage 跟遠端不同時，讀的是 origin/stage（不是本機那一條）"; else err "上 prod 的關：本機 stage 與遠端不同時沒有以 origin/stage 為準——預期 rc=1 含「條件甲」，實得 rc=${gm_rc}：$(head -3 <<<"$gm_out")"; fi

"${GIT_T[@]}" remote set-url origin "$GM/no-such-remote.git"
gm_out=$(cd "$GM/work" && bash scripts/unconfirmed-conditions.sh TESTG-01 2>&1); gm_rc=$?
if [ "$gm_rc" -eq 2 ] && grep -qF "fetch" <<<"$gm_out"; then ok "上 prod 的關：git fetch 失敗→結束碼 2（不用舊的 origin/stage 放行）"; else err "上 prod 的關：fetch 失敗應是 rc=2，實得 ${gm_rc}：$(head -2 <<<"$gm_out")"; fi

# ── 推 prod 前的檢查也讀〈數字口徑〉（源專案 v5.19.0）：另外印、不印符合／擋掉 ──
uc_nticket() {  # $1=票號 $2=created $3=內文 $4=〈數字口徑〉那一節（含標題，可空）
  cat > "$UC/$1-案例.md" <<TICKETEOF
---
id: $1
title: 案例
status: 完成
roles: [管理員]
spec:
created: $2
updated: $2
---

## 需求細節

$3

$4
TICKETEOF
}
UCN_HEAD="$NUM_HEAD"
UCN_BODY="首頁加一張準時出貨率的統計卡。"
uc_nticket TESTN-01 "$NEW" "$UCN_BODY" "## 數字口徑

$UCN_HEAD
| 準時出貨率 | 出貨日 | 台北 | 不含取消 | 一筆一次 | 準時出貨數÷出貨數 | 不算 | 同首頁統計卡 | 已確認 | 2025-06-12 |"
uc_nticket TESTN-02 "$NEW" "$UCN_BODY" "## 數字口徑

$UCN_HEAD
| 準時出貨率 | 出貨日 | 台北 | 不含取消 | 一筆一次 | 準時出貨數÷出貨數 | 不算 | 同首頁統計卡 | 未確認 | |"
uc_nticket TESTN-03 "$NEW" "$UCN_BODY" ""
uc_nticket TESTN-04 "$OLD" "$UCN_BODY" ""
uc_nticket TESTN-05 "$NEW" "$UCN_BODY" "## 數字口徑

不適用：只改卡片顏色，數字不動"
uc_nticket TESTN-06 "$NEW" "$UCN_BODY" "## 數字口徑

$UCN_HEAD
| 準時出貨率 | 出貨日 | 台北 | 不含取消 | 一筆一次 | 準時出貨數÷出貨數 | 不算 | 同首頁統計卡 | | |"
uc_nticket TESTN-07 "$NEW" "$UCN_BODY" "## 數字口徑

$UCN_HEAD
| 準時出貨率 | 出貨日 | 台北 | 不含取消 | 一筆一次 | 準時出貨數÷出貨數 | 不算 | 同首頁統計卡 | 已確認 | 2025-06-12 |
出貨數 | 出貨日 | 台北 | 不含取消 | 一筆一次 | 加總 | 不算 | 同首頁統計卡 | 已確認 | 2025-06-12 |"
uc_nticket TESTN-08 "$SINCE" "$UCN_BODY" ""
uc_expect "數字口徑都已確認→通過" 0 "通過" TESTN-01
uc_expect "數字口徑未確認→擋、印數字與狀態" 1 "數字口徑未確認：準時出貨率" TESTN-02
uc_expect "數字口徑未確認→不印符合／擋掉" 1 "（狀態：未確認）" TESTN-02
uc_expect "有字樣沒有這一節（生效日後）→擋" 1 "卻沒有〈數字口徑〉這一節" TESTN-03
uc_expect "有字樣沒有這一節但生效日前一天建立→不擋" 0 "通過" TESTN-04
uc_expect "有字樣沒有這一節、生效日當天建立→擋（含當天）" 1 "卻沒有〈數字口徑〉這一節" TESTN-08
uc_expect "數字口徑寫不適用→不擋" 0 "通過" TESTN-05
uc_expect "數字口徑狀態空白→擋" 1 "（狀態：空白）" TESTN-06
uc_expect "數字口徑有一列沒有開頭的 |→擋" 1 "〈數字口徑〉看不出表格" TESTN-07
ucn_out=$(uc_run TESTN-02)
if grep -q "符合.*擋掉" <<<"$ucn_out"; then err "上 prod 的關：數字口徑列不該印「符合／擋掉」"; else ok "上 prod 的關：數字口徑列沒有「符合／擋掉」"; fi

# 兩支腳本的字樣清單必須同一份（不然 lint 放行、上 prod 的關卻擋，或反過來）。
# 生效日兩邊都讀 TICKET_RULES_SINCE；讀法一不一致用行為驗（下面的 agree_case），不比對程式字面。
lint_trig=$(grep -o "^COND_TRIGGER_RE='[^']*'" "$ROOT/scripts/ticket-lint.sh")
uc_trig=$(grep -o "^COND_TRIGGER_RE='[^']*'" "$ROOT/scripts/unconfirmed-conditions.sh")
if [ -n "$lint_trig" ] && [ "$lint_trig" = "$uc_trig" ]; then
  ok "〈條件確認〉字樣清單在 ticket-lint 與 unconfirmed-conditions 兩邊一致"
else
  err "〈條件確認〉字樣清單在 ticket-lint.sh 與 unconfirmed-conditions.sh 兩邊不一樣——兩邊要同改"
fi
nlint_trig=$(grep -o "^NUM_TRIGGER_RE='[^']*'" "$ROOT/scripts/ticket-lint.sh")
nuc_trig=$(grep -o "^NUM_TRIGGER_RE='[^']*'" "$ROOT/scripts/unconfirmed-conditions.sh")
if [ -n "$nlint_trig" ] && [ "$nlint_trig" = "$nuc_trig" ]; then
  ok "〈數字口徑〉字樣清單在 ticket-lint 與 unconfirmed-conditions 兩邊一致"
else
  err "〈數字口徑〉字樣清單在 ticket-lint.sh 與 unconfirmed-conditions.sh 兩邊不一樣——兩邊要同改"
fi

# 行為一致：同一張票問兩支腳本，lint 說「缺這一節」時上 prod 的關也要擋，反之亦然。
agree_case() {  # $1=內文 $2=created（可空） $3=生效日（空字串＝全部套用） → 印 blocked｜pass｜DISAGREE(lint=..,gate=..)
  local ad="$SANDBOX/agree" l_rc g_rc
  rm -rf "$ad"; mkdir -p "$ad"
  cat > "$ad/TESTA-01-案例.md" <<TICKETEOF
---
id: TESTA-01
title: 案例
status: 開發中
roles: [管理員]
owner: tester
spec:
created: $2
updated: $2
---

## 需求細節

$1

## 這次可能會弄壞什麼

不適用：沙盒案例

## 驗收標準

- [ ] 略
TICKETEOF
  TICKET_RULES_SINCE="$3" TICKETS_DIR="$ad" TICKET_LINT_BASE=__no_such_ref__ bash "$ROOT/scripts/ticket-lint.sh" >/dev/null 2>&1; l_rc=$?
  TICKET_RULES_SINCE="$3" TICKETS_DIR="$ad" bash "$ROOT/scripts/unconfirmed-conditions.sh" TESTA-01 >/dev/null 2>&1; g_rc=$?
  if [ "$l_rc" -ne 0 ] && [ "$g_rc" -ne 0 ]; then echo blocked
  elif [ "$l_rc" -eq 0 ] && [ "$g_rc" -eq 0 ]; then echo pass
  else echo "DISAGREE(lint=${l_rc},gate=${g_rc})"; fi
}

# 逐個字樣、正文／標題／註解三種位置：字樣只在 HTML 註解裡不算，其餘兩種都要擋
num_agree_fail=""
for w in 儀表板 統計卡 成功率 比例 比率 平均 總數 KPI; do
  for pos in body heading comment; do
    case "$pos" in
      body) pre="這裡講到${w}。"; want=blocked ;;
      heading) pre="### ${w}設定"; want=blocked ;;
      comment) pre="<!-- ${w} -->"; want=pass ;;
    esac
    got=$(agree_case "$pre" "$NEW" "$SINCE")
    [ "$got" = "$want" ] || num_agree_fail="$num_agree_fail ${w}/${pos}（要 ${want}，實得 ${got}）"
  done
done
if [ -z "$num_agree_fail" ]; then ok "〈數字口徑〉lint 與上 prod 的關對 8 個字樣×正文／標題／註解的判斷一致"; else err "〈數字口徑〉lint 與上 prod 的關判斷不一致：${num_agree_fail}"; fi

# 生效日的讀法也要一致（兩支都讀 TICKET_RULES_SINCE）：前一天建立的不查、當天建立的要查（含當天）、
# 留空＝全部套用（連沒填 created 的票也查）、有設生效日時沒填 created 的票不查。
# 〈條件確認〉用「回填」當字樣、〈數字口徑〉用「儀表板」，兩節各驗一輪。
since_agree_fail=""
since_agree() {  # $1=名稱 $2=預期（blocked｜pass） $3=內文 $4=created $5=生效日
  local got; got=$(agree_case "$3" "$4" "$5")
  [ "$got" = "$2" ] || since_agree_fail="$since_agree_fail ${1}（要 ${2}，實得 ${got}）"
}
for since_body in "舊單一次回填。" "這裡講到儀表板。"; do
  since_agree "生效日前一天建立/${since_body}" pass "$since_body" "$OLD" "$SINCE"
  since_agree "生效日當天建立/${since_body}" blocked "$since_body" "$SINCE" "$SINCE"
  since_agree "生效日留空＋很早建立/${since_body}" blocked "$since_body" "1999-01-01" ""
  since_agree "生效日留空＋沒填 created/${since_body}" blocked "$since_body" "" ""
  since_agree "有設生效日＋沒填 created/${since_body}" pass "$since_body" "" "$SINCE"
done
if [ -z "$since_agree_fail" ]; then ok "生效日（TICKET_RULES_SINCE）在 lint 與上 prod 的關兩邊讀法一致（前一天不查、當天要查、留空全部套用）"; else err "生效日在 lint 與上 prod 的關兩邊讀法不一致：${since_agree_fail}"; fi

if [ "$fail" -eq 0 ]; then
  echo "[ticket-tools-test] 全部通過"
fi
exit "$fail"
