#!/usr/bin/env bash
# scripts/unconfirmed-conditions.sh 的 stage 模式（--stage-range／--stage-ref）測試（源專案 v5.41.0）。守門工具自己也要有測試。
# 在暫存 git repo 裡真的 commit 票檔，拿兩個 sha 跑腳本，看結束碼。
# 驗證本身：UC=<別版腳本> 可換成故意弄壞的版本，應該有幾條變紅。
# 沒測的：.githooks/pre-push 怎麼把推送範圍餵給這支腳本、結束碼 2 只警告放行——那是 hook 那邊的接線，測試跟著 hook 走。
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
UC="${UC:-$REPO/scripts/unconfirmed-conditions.sh}"
fail=0
TMP=$(mktemp -d)
CFG=$(mktemp -d)   # 放「腳本＋假設定檔」的另一個暫存夾（測生效日從設定檔讀）
trap 'rm -rf "$TMP" "$CFG"' EXIT
ZERO=0000000000000000000000000000000000000000

# 生效日由測試自己帶：不靠專案 framework-config.sh 現在填的值，也不靠外面剛好設了什麼環境變數
SINCE=2025-06-01
NEW=2025-06-10   # 生效日之後建立的票
OLD=2025-05-31   # 生效日前一天建立的票
export TICKET_RULES_SINCE="$SINCE"

# 從 git hook 或 `git rebase --exec` 裡被叫到時，git 會帶著指向真 repo 的環境變數；
# 不拿掉的話，下面沙盒裡的 git init／commit 會打到真的 repo
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

cd "$TMP"
git init -q . && git config user.email t@t && git config user.name t
git config commit.gpgsign false && git config core.hooksPath /dev/null   # 使用者全域的簽章／hook 設定不要帶進沙盒
git config core.quotePath true   # 故意開著：腳本自己要關掉，中文檔名才對得到
mkdir tickets
echo base > README.md && git add README.md && git commit -qm base
BASE=$(git rev-parse HEAD)

COND_HEAD='| 條件（含分母） | 符合 | 擋掉 | 狀態 | 回答日 |
|---|---|---|---|---|'
NUM_HEAD='| 數字 | 口徑 | 狀態 | 回答日 |
|---|---|---|---|'

# ticket <檔名> <status> <created> <〈條件確認〉內容，空＝不放這一節> <〈數字口徑〉內容，空＝不放> [需求細節的文字]
ticket() {
  {
    printf -- '---\nid: X\nstatus: %s\ncreated: %s\n---\n\n## 需求細節\n\n%s\n\n' "$2" "$3" "${6:-略}"
    [ -n "$4" ] && printf '## 條件確認\n\n%s\n\n' "$4"
    [ -n "$5" ] && printf '## 數字口徑\n\n%s\n\n' "$5"
  } > "tickets/$1"
}

# expect <說明> <預期結束碼> <輸出要出現的字（可空）> <remote> <local>
expect() {
  bash "$UC" --stage-range "$4" "$5" >"$TMP/out" 2>&1
  rc=$?
  if [ "$rc" = "$2" ] && { [ -z "$3" ] || grep -qF -- "$3" "$TMP/out"; }; then echo "  ✅ $1"
  else echo "  ❌ $1（預期 ${2} 含「${3}」，實際 ${rc}）"; sed 's/^/     /' "$TMP/out"; fail=1; fi
}

reset_and() { git rm -rq --cached tickets >/dev/null 2>&1; rm -rf tickets; mkdir tickets; }

# run_case <說明> <預期> <輸出字> <status> <條件節> <口徑節> [created]
run_case() {
  git checkout -q "$BASE" 2>/dev/null
  reset_and
  ticket "AMY-1-中文檔名.md" "$4" "${7:-$NEW}" "$5" "$6"
  git add tickets && git commit -qm "t" && local sha; sha=$(git rev-parse HEAD)
  expect "$1" "$2" "$3" "$BASE" "$sha"
}

echo "── 判準（同推 prod 前那一關）──"
run_case "未確認 → 擋" 1 "未確認" 完成 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 未確認 | |" ""
run_case "已確認＋回答日 → 過" 0 "通過" 完成 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 已確認 | 2025-06-10 |" ""
run_case "狀態空白 → 擋" 1 "空白" 開發中 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | | |" ""
run_case "兩列一已確認一未確認 → 擋" 1 "條件乙" 開發中 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 已確認 | 2025-06-10 |
| 條件乙（分母：50 張） | 3 張 | 47 張 | 未確認 | |" ""
run_case "表格有一列沒有開頭的 | → 擋" 1 "沒有開頭的" 開發中 "$COND_HEAD
條件甲 | 10 張 | 90 張 | 已確認 | 2025-06-10 |" ""
run_case "寫不適用 → 過" 0 "不擋" 開發中 "不適用：只改文案" ""
git checkout -q "$BASE"; reset_and
ticket "AMY-1-中文檔名.md" 開發中 2025-06-10 "" "" "附件區至少一份附件才出現確認勾選。"
git add tickets && git commit -qm t; SM=$(git rev-parse HEAD)
expect "票文字有「才出現」卻沒有〈條件確認〉 → 擋（MISSING）" 1 "沒有〈條件確認〉" "$BASE" "$SM"
ticket "AMY-1-中文檔名.md" 開發中 2025-06-10 "" "" "儀表板顯示平均出貨天數。"
git add tickets && git commit -qm t; SN=$(git rev-parse HEAD)
expect "票文字有「儀表板」卻沒有〈數字口徑〉 → 擋（NMISSING）" 1 "沒有〈數字口徑〉" "$SM" "$SN"

echo "── 〈數字口徑〉──"
run_case "口徑未確認 → 擋" 1 "數字口徑未確認" 開發中 "不適用：沒有條件" "$NUM_HEAD
| 準時出貨率 | 準時出貨數÷出貨數 | 未確認 | |"
run_case "口徑已確認 → 過" 0 "通過" 開發中 "不適用：沒有條件" "$NUM_HEAD
| 準時出貨率 | 準時出貨數÷出貨數 | 已確認 | 2025-06-10 |"
run_case "口徑寫「待 prod 資料」→ 擋（口徑沒有這個例外）" 1 "數字口徑未確認" 開發中 "不適用：沒有條件" "$NUM_HEAD
| 準時出貨率 | 準時出貨數÷出貨數 | 待 prod 資料 | 2025-06-10 |"

echo "── 「待 prod 資料」例外：三個都有才放行 ──"
run_case "待 prod 資料＋〈符合〉查不到＋回答日 → 過，並提醒推 prod 前重查" 0 "待 prod 資料（案主 2025-06-10 同意" 開發中 "$COND_HEAD
| 條件甲（分母：未知） | 查不到：prod 沒有這個欄位的資料 | 查不到：同左 | 待 prod 資料 | 2025-06-10 |" ""
run_case "待 prod 資料＋只有〈擋掉〉查不到＋回答日 → 過" 0 "待 prod 資料" 完成 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 查不到：要看 prod 才知道 | 待 prod 資料 | 2025-06-10 |" ""
run_case "待 prod 資料但沒有回答日 → 擋" 1 "沒有 YYYY-MM-DD 的回答日" 開發中 "$COND_HEAD
| 條件甲（分母：未知） | 查不到：沒資料 | 查不到：同左 | 待 prod 資料 | |" ""
run_case "待 prod 資料但回答日不是日期 → 擋" 1 "回答日" 開發中 "$COND_HEAD
| 條件甲（分母：未知） | 查不到：沒資料 | 查不到：同左 | 待 prod 資料 | 之後 |" ""
run_case "待 prod 資料但兩格都有筆數（有筆數就現在問）→ 擋" 1 "不是「查不到：」開頭" 開發中 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 待 prod 資料 | 2025-06-10 |" ""
run_case "待 prod 資料但寫「未查」不是「查不到：」→ 擋" 1 "不是「查不到：」開頭" 開發中 "$COND_HEAD
| 條件甲（分母：未知） | 未查 | 未查 | 待 prod 資料 | 2025-06-10 |" ""
run_case "同表：一列合格待 prod 資料、一列未確認 → 擋（只放行合格那列）" 1 "條件乙" 開發中 "$COND_HEAD
| 條件甲（分母：未知） | 查不到：沒資料 | 查不到：同左 | 待 prod 資料 | 2025-06-10 |
| 條件乙（分母：50 張） | 3 張 | 47 張 | 未確認 | |" ""
run_case "狀態寫成別的詞（「待prod資料」少一個空格）→ 擋" 1 "待prod資料" 開發中 "$COND_HEAD
| 條件甲（分母：未知） | 查不到：沒資料 | 查不到：同左 | 待prod資料 | 2025-06-10 |" ""

echo "── 查哪幾張票 ──"
run_case "狀態待開發 → 不查" 0 "沒有狀態是開發中／完成" 待開發 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 未確認 | |" ""
run_case "狀態作廢 → 不查" 0 "沒有狀態是開發中／完成" 作廢 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 未確認 | |" ""
run_case "狀態完成 → 查" 1 "未確認" 完成 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 未確認 | |" ""

# 範圍外的票不查：基線已有一張未確認的票，這次只推另一張好的
git checkout -q "$BASE"; reset_and
ticket "AMY-3-舊票.md" 開發中 2025-06-10 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 未確認 | |" ""
git add tickets && git commit -qm t3; S3=$(git rev-parse HEAD)
ticket "AMY-4-新票.md" 開發中 2025-06-10 "$COND_HEAD
| 條件乙（分母：50 張） | 3 張 | 47 張 | 已確認 | 2025-06-10 |" ""
git add tickets && git commit -qm t4; S4=$(git rev-parse HEAD)
expect "範圍外的舊票（票檔這次沒動）不擋這次" 0 "AMY-4：條件與數字口徑都已確認" "$S3" "$S4"
expect "遠端全 0（新分支）→ 全查，抓得到 AMY-3" 1 "AMY-3 未確認" "$ZERO" "$S4"
expect "遠端 sha 本機不認得 → 全查" 1 "AMY-3 未確認" "1111111111111111111111111111111111111111" "$S4"

# 返工：stage 上已經是已確認的票，之後被改回未確認再推 → 要擋（不是「第一次進 stage」才查）
ticket "AMY-3-舊票.md" 開發中 2025-06-10 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 已確認 | 2025-06-10 |" ""
git add tickets && git commit -qm fix3; S5=$(git rev-parse HEAD)
expect "stage 上已確認的票" 0 "" "$S3" "$S5"
ticket "AMY-3-舊票.md" 開發中 2025-06-10 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 已確認 | 2025-06-10 |
| 條件丙（分母：20 張） | 1 張 | 19 張 | 未確認 | |" ""
git add tickets && git commit -qm rework3; S6=$(git rev-parse HEAD)
expect "返工：stage 已有那張票、這次新加一列未確認 → 擋" 1 "條件丙" "$S5" "$S6"

# 範圍內沒有票檔：只改別的檔 → 0
echo x > other.txt && git add other.txt && git commit -qm other; S7=$(git rev-parse HEAD)
expect "範圍內沒有票檔 → 通過（不走「用法」那條回 2）" 0 "範圍內沒有狀態是開發中／完成的票檔——通過" "$S6" "$S7"
expect "遠端＝要推的（空範圍）→ 通過" 0 "通過" "$S7" "$S7"

# 模板內補的：範圍內「刪掉」一張票檔 → 刪掉的檔不拿來讀（不會因為讀不到而回 2）
ticket "AMY-11-會被刪的.md" 開發中 2025-06-10 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 已確認 | 2025-06-10 |" ""
git add tickets && git commit -qm "加一張之後會刪的票"; SD1=$(git rev-parse HEAD)
git rm -q "tickets/AMY-11-會被刪的.md" && git commit -qm "刪掉那張票"; SD2=$(git rev-parse HEAD)
expect "範圍內刪掉一張票檔 → 通過（刪掉的檔不拿來讀，不回 2）" 0 "通過" "$SD1" "$SD2"
mkdir -p tickets

# 讀被推的 commit，不讀工作樹
git checkout -q "$BASE"; reset_and
ticket "AMY-2-工作樹.md" 開發中 2025-06-10 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 未確認 | |" ""
git add tickets && git commit -qm t2; S2=$(git rev-parse HEAD)
ticket "AMY-2-工作樹.md" 開發中 2025-06-10 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 已確認 | 2025-06-10 |" ""   # 只改工作樹、沒 commit
expect "工作樹改成已確認但沒 commit → 照擋" 1 "未確認" "$BASE" "$S2"
git checkout -q -- tickets

# README／子資料夾不當票
git checkout -q "$BASE"; reset_and
printf '## 條件確認\n\n| 條件 | 符合 | 擋掉 | 狀態 | 回答日 |\n|---|---|---|---|---|\n| 範例 | 1 | 1 | 未確認 | |\n' > tickets/README.md
mkdir tickets/archive && printf -- '---\nstatus: 開發中\n---\n## 條件確認\n\n| 條件 | 符合 | 擋掉 | 狀態 | 回答日 |\n|---|---|---|---|---|\n| 範例 | 1 | 1 | 未確認 | |\n' > tickets/archive/AMY-9-x.md
git add tickets && git commit -qm readme; S8=$(git rev-parse HEAD)
expect "tickets/README.md 與子資料夾的檔不當票查" 0 "通過" "$BASE" "$S8"

# 自己跑不起來 → 2
expect "local sha 不存在 → 結束碼 2（pre-push 只警告）" 2 "本機找不到這個 commit" "$BASE" "2222222222222222222222222222222222222222"
bash "$UC" --stage-range onlyone >"$TMP/out" 2>&1; rc=$?
if [ "$rc" = 2 ]; then echo "  ✅ --stage-range 少給參數 → 2"; else echo "  ❌ --stage-range 少給參數（預期 2，實際 ${rc}）"; fail=1; fi

echo "── --stage-ref：合流前先查（每個 ref 自己算 merge-base）──"
expect_ref() {   # expect_ref <說明> <預期> <輸出字> <ref…>
  local name=$1 want=$2 txt=$3; shift 3
  bash "$UC" --stage-ref "$@" >"$TMP/out" 2>&1
  rc=$?
  if [ "$rc" = "$want" ] && { [ -z "$txt" ] || grep -qF -- "$txt" "$TMP/out"; }; then echo "  ✅ $name"
  else echo "  ❌ ${name}（預期 ${want} 含「${txt}」，實際 ${rc}）"; sed 's/^/     /' "$TMP/out"; fail=1; fi
}
git checkout -q "$BASE"; reset_and
ticket "AMY-6-基線.md" 開發中 2025-06-10 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 未確認 | |" ""            # 基線上就未確認的票（之後 stage 補好）
git add tickets/AMY-6-基線.md && git commit -qm t6; B0=$(git rev-parse HEAD)
git checkout -q -b feat-bad "$B0"
ticket "AMY-7-壞.md" 開發中 2025-06-10 "$COND_HEAD
| 條件乙（分母：50 張） | 3 張 | 47 張 | 未確認 | |" ""
git add tickets/AMY-7-壞.md && git commit -qm bad7; FBAD=$(git rev-parse HEAD)
git checkout -q -b feat-good "$B0"
ticket "AMY-8-好.md" 開發中 2025-06-10 "$COND_HEAD
| 條件丙（分母：50 張） | 3 張 | 47 張 | 已確認 | 2025-06-10 |" ""
git add tickets/AMY-8-好.md && git commit -qm good8; FGOOD=$(git rev-parse HEAD)
git checkout -q -b stage-fix "$B0"
ticket "AMY-6-基線.md" 開發中 2025-06-10 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 已確認 | 2025-06-10 |" ""
git add tickets/AMY-6-基線.md && git commit -qm fix6; SFIX=$(git rev-parse HEAD)
git update-ref refs/remotes/origin/stage "$SFIX"
expect_ref "--stage-ref 有未確認的分支 → 擋" 1 "AMY-7 未確認" "$FBAD"
expect_ref "--stage-ref 都已確認的分支 → 過；分支落後 stage、stage 補好的舊票不誤抓（merge-base）" 0 "通過" "$FGOOD"
expect_ref "--stage-ref 多條：一好一壞 → 擋（取最嚴）" 1 "AMY-7 未確認" "$FGOOD" "$FBAD"
if grep -qF "AMY-8：條件與數字口徑都已確認" "$TMP/out" && ! grep -qF "AMY-6" "$TMP/out"; then echo "  ✅ 多條各查各的、不會把基線上的 AMY-6 算進來"
else echo "  ❌ 多條輸出不對"; sed 's/^/     /' "$TMP/out"; fail=1; fi
expect_ref "--stage-ref 找不到的 ref → 2（不當成通過）" 2 "找不到這個 ref" "no-such-branch"

echo "── 生效日（TICKET_RULES_SINCE）：只管「漏了這一節」那一條 ──"
# 環境變數 > 腳本旁的 framework-config.sh；留空＝所有票都套用。
# expect_cmd <說明> <預期結束碼> <輸出要出現的字（可空）> <指令…>
expect_cmd() {
  local name=$1 want=$2 txt=$3; shift 3
  "$@" >"$TMP/out" 2>&1
  rc=$?
  if [ "$rc" = "$want" ] && { [ -z "$txt" ] || grep -qF -- "$txt" "$TMP/out"; }; then echo "  ✅ $name"
  else echo "  ❌ ${name}（預期 ${want} 含「${txt}」，實際 ${rc}）"; sed 's/^/     /' "$TMP/out"; fail=1; fi
}
no_env() { ( unset TICKET_RULES_SINCE; "$@" ); }   # 沒有環境變數（不是設成空的）
git checkout -q "$BASE"; reset_and
ticket "AMY-10-舊票沒有這一節.md" 開發中 "$OLD" "" "" "附件區至少一份附件才出現確認勾選；儀表板顯示平均出貨天數。"
git add tickets/AMY-10-舊票沒有這一節.md && git commit -qm since; SS=$(git rev-parse HEAD)
expect_cmd "生效日前一天建立、字樣對得上但沒有這兩節 → 舊票不擋" 0 "不擋" env TICKET_RULES_SINCE="$SINCE" bash "$UC" --stage-range "$BASE" "$SS"
expect_cmd "生效日往前挪一天（含當天）→ 擋，訊息講出生效日" 1 "生效日（${OLD}）當天或之後，卻沒有〈條件確認〉" env TICKET_RULES_SINCE="$OLD" bash "$UC" --stage-range "$BASE" "$SS"
expect_cmd "同上，〈數字口徑〉那一條也擋" 1 "生效日（${OLD}）當天或之後，卻沒有〈數字口徑〉" env TICKET_RULES_SINCE="$OLD" bash "$UC" --stage-range "$BASE" "$SS"
expect_cmd "環境變數設成空的 → 所有票都套用 → 擋" 1 "新票規沒有設生效日" env TICKET_RULES_SINCE= bash "$UC" --stage-range "$BASE" "$SS"
expect_cmd "生效日格式錯誤 → 講出來，並當成全部套用（不是靜靜整條關掉、也不是結束碼 2）" 1 "格式錯誤" env TICKET_RULES_SINCE=2025/06/01 bash "$UC" --stage-range "$BASE" "$SS"
mkdir -p "$CFG/scripts" && cp "$UC" "$CFG/scripts/unconfirmed-conditions.sh"
printf 'TICKET_RULES_SINCE="%s"\n' "$SINCE" > "$CFG/scripts/framework-config.sh"
expect_cmd "沒有環境變數 → 讀腳本旁的 framework-config.sh（舊票不擋）" 0 "不擋" no_env bash "$CFG/scripts/unconfirmed-conditions.sh" --stage-range "$BASE" "$SS"
expect_cmd "環境變數蓋過設定檔（往前挪一天）→ 擋" 1 "卻沒有〈條件確認〉" env TICKET_RULES_SINCE="$OLD" bash "$CFG/scripts/unconfirmed-conditions.sh" --stage-range "$BASE" "$SS"
printf 'TICKET_RULES_SINCE=""\n' > "$CFG/scripts/framework-config.sh"
expect_cmd "設定檔留空 → 所有票都套用 → 擋" 1 "新票規沒有設生效日" no_env bash "$CFG/scripts/unconfirmed-conditions.sh" --stage-range "$BASE" "$SS"
rm -f "$CFG/scripts/framework-config.sh"
expect_cmd "沒有設定檔 → 所有票都套用 → 擋" 1 "新票規沒有設生效日" no_env bash "$CFG/scripts/unconfirmed-conditions.sh" --stage-range "$BASE" "$SS"
# 表格裡的列不看生效日：舊票只要有這一節、裡面還有未確認，照擋
run_case "生效日之前的舊票、有〈條件確認〉表且未確認 → 照擋" 1 "未確認" 開發中 "$COND_HEAD
| 條件甲（分母：100 張） | 10 張 | 90 張 | 未確認 | |" "" "$OLD"

if [ "$fail" -eq 0 ]; then echo "[stage-confirm-gate-test] ✅ 通過"; else echo "[stage-confirm-gate-test] ❌ 有失敗"; exit 1; fi
