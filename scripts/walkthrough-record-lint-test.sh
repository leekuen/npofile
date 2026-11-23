#!/usr/bin/env bash
# scripts/walkthrough_record_lint.py 的測試（源專案 v5.30.0）。守門工具自己也要有測試。
# 在暫存 git repo 裡真的 commit 票檔，拿兩個 sha 跑腳本，看結束碼。
# 驗證本身：LINT=<別版腳本> 可換成故意弄壞的版本，應該有幾條變紅。
set -uo pipefail
cd "$(dirname "$0")/.."
LINT="${LINT:-$PWD/scripts/walkthrough_record_lint.py}"
fail=0
TMP=$(mktemp -d)
CFG=$(mktemp -d)   # 放「腳本＋假設定檔」的另一個暫存夾（測生效日從設定檔讀）
trap 'rm -rf "$TMP" "$CFG"' EXIT
ZERO=0000000000000000000000000000000000000000

# 生效日由測試自己帶：不靠專案 framework-config.sh 現在填的值，也不靠外面剛好設了什麼環境變數
SINCE=2025-06-01
NEW=2025-06-01   # 生效日當天建立 → 要查（含當天）
OLD=2025-05-31   # 前一天建立 → 不查
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

# ticket <檔名> <created> <status> <風險節內容> <開發備註內容> [額外節]
ticket() {
  cat > "tickets/$1" <<EOF
---
id: X
status: $3
created: $2
---

## 這次可能會弄壞什麼

<!-- 一行一個編號（W1、W2…）：範本說明，不是風險行。
     W9 也不是 -->
$4

## 驗收標準

- [x] W1 驗收行不算走查交代
- [x] W2 同上

## 開發備註（/dev 填寫）

$5
${6:-}
EOF
}

# expect <說明> <預期結束碼> <remote> <local>
# python3 -I：不讓使用者的 PYTHONPATH、使用者層套件影響結果（腳本只用標準函式庫）
expect() {
  python3 -I "$LINT" "$3" "$4" >"$TMP/out" 2>&1
  rc=$?
  if [ "$rc" = "$2" ]; then echo "  ✅ $1"; else echo "  ❌ $1（預期 ${2}，實際 ${rc}）"; sed 's/^/     /' "$TMP/out"; fail=1; fi
}

# commit_one <檔名> ... ：只放這次的票，回傳 sha
reset_and() { git rm -rq --cached tickets >/dev/null 2>&1; rm -rf tickets; mkdir tickets; }

run_case() {   # run_case <說明> <預期> <created> <status> <風險> <備註> [額外節]
  git checkout -q "$BASE" 2>/dev/null
  reset_and
  ticket "AMY-01-中文檔名.md" "$3" "$4" "$5" "$6" "${7:-}"
  git add tickets && git commit -qm "t" && local sha; sha=$(git rev-parse HEAD)
  expect "$1" "$2" "$BASE" "$sha"
}

run_case "W1 沒交代 → 擋" 1 $NEW 開發中 "- W1 訂單清單頁" "- 根因：…"
run_case "W1 有真人眼看 → 過" 0 $NEW 開發中 "- W1 訂單清單頁" "- 走查（真人眼看）W1 訂單清單頁：清單完整"
run_case "W1 寫在沒走的是 → 過" 0 $NEW 開發中 "- W1 訂單清單頁" "⚠️ 走查未完成
· 沒走的是：W1 訂單清單頁
· 為什麼：環境
· 誰該補走：下一位接手的人"
run_case "一行兩個 W → 過" 0 $NEW 完成 "- W1 訂單清單頁
- W2 訂單明細頁" "- 走查（HTTP 腳本）W1 訂單清單頁、W2 訂單明細頁：…"
run_case "只交代 W10、沒交代 W1 → 擋" 1 $NEW 開發中 "- W1 訂單清單頁
- W10 會員頁" "- 走查（真人眼看）W10 會員頁"
run_case "兩個 W 只交代一個 → 擋" 1 $NEW 開發中 "- W1 訂單清單頁
- W2 訂單明細頁" "- 走查（HTML 檢查）W1 訂單清單頁"
run_case "風險節不適用 → 過" 0 $NEW 開發中 "不適用：只改 CI" "- 根因"
run_case "舊票（生效日前一天建立）→ 不查" 0 $OLD 開發中 "- W1 訂單清單頁" "- 根因"
run_case "待開發 → 不查" 0 $NEW 待開發 "- W1 訂單清單頁" ""
run_case "只有驗收行打勾、沒有走查行 → 擋" 1 $NEW 開發中 "- W1 訂單清單頁" "- 驗證：W1 看過了"
run_case "寫在〈走查〉節 → 過" 0 $NEW 開發中 "- W1 訂單清單頁" "- 根因" "## 走查

- 走查（真人眼看）W1 訂單清單頁"
run_case "開發備註下的 ### 小標裡 → 過" 0 $NEW 開發中 "- W1 訂單清單頁" "### 驗證

- 走查（真人眼看）W1 訂單清單頁"
run_case "交代寫在〈邊界〉之類別節 → 擋" 1 $NEW 開發中 "- W1 訂單清單頁" "- 根因" "## 邊界

- 走查（真人眼看）W1 訂單清單頁"
# ── 以下四條是模板內補的（突變測試抓到原本沒有案例守住的判斷）──
run_case "W1 有 HTML 檢查 → 過（三種走查寫法都收）" 0 $NEW 開發中 "- W1 訂單清單頁" "- 走查（HTML 檢查）W1 訂單清單頁：欄位都在"
run_case "只交代 W1、沒交代 W10 → 擋（W10 不會被當成 W1）" 1 $NEW 開發中 "- W1 訂單清單頁
- W10 會員頁" "- 走查（真人眼看）W1 訂單清單頁"
run_case "交代行寫的是 ABW2（英數後面的 W 不算編號）→ 擋" 1 $NEW 開發中 "- W2 訂單明細頁" "- 走查（真人眼看）ABW2 訂單明細頁"
run_case "風險節寫了不適用、底下還留著 W 行 → 不查（不適用優先，同 ticket-lint）" 0 $NEW 開發中 "不適用：只改 CI
- W1 訂單清單頁" "- 根因"

# 讀被推的 commit，不讀工作樹
git checkout -q "$BASE"; reset_and
ticket "AMY-2.md" $NEW 開發中 "- W1 訂單清單頁" "- 根因"
git add tickets && git commit -qm t2; S2=$(git rev-parse HEAD)
ticket "AMY-2.md" $NEW 開發中 "- W1 訂單清單頁" "- 走查（真人眼看）W1 訂單清單頁"   # 只改工作樹、沒 commit
expect "工作樹補了但沒 commit → 照擋" 1 "$BASE" "$S2"
git checkout -q -- tickets

# 範圍外的票不查：基線已有一張缺交代的票，這次只推另一張好的
git checkout -q "$BASE"; reset_and
ticket "AMY-3.md" $NEW 開發中 "- W1 訂單清單頁" "- 根因"
git add tickets && git commit -qm t3; S3=$(git rev-parse HEAD)
ticket "AMY-4.md" $NEW 開發中 "- W1 訂單清單頁" "- 走查（真人眼看）W1 訂單清單頁"
git add tickets && git commit -qm t4; S4=$(git rev-parse HEAD)
expect "範圍外的舊缺漏不擋這次" 0 "$S3" "$S4"
expect "遠端全 0（新分支）→ 全查，抓得到 AMY-3" 1 "$ZERO" "$S4"
expect "遠端 sha 本機不認得 → 全查" 1 "1111111111111111111111111111111111111111" "$S4"

# 自己跑不起來 → 2
expect "local sha 不存在 → 結束碼 2（只警告）" 2 "$BASE" "2222222222222222222222222222222222222222"

# --ref：合流前先查（源專案 v5.39.0）。每個 ref 自己算 merge-base origin/stage，不是直接拿 origin/stage 當基準
expect_ref() {   # expect_ref <說明> <預期> <ref…>
  local name=$1 want=$2; shift 2
  python3 -I "$LINT" --ref "$@" >"$TMP/out" 2>&1
  rc=$?
  if [ "$rc" = "$want" ]; then echo "  ✅ $name"; else echo "  ❌ ${name}（預期 ${want}，實際 ${rc}）"; sed 's/^/     /' "$TMP/out"; fail=1; fi
}
git checkout -q "$BASE"; reset_and
ticket "AMY-6.md" $NEW 開發中 "- W1 訂單清單頁" "- 根因"                       # 基線上就缺交代的票（之後 stage 補好）
git add tickets/AMY-6.md && git commit -qm t6; B0=$(git rev-parse HEAD)
git checkout -q -b feat-bad "$B0"
ticket "AMY-7.md" $NEW 開發中 "- W1 訂單清單頁" "- 根因"
git add tickets/AMY-7.md && git commit -qm bad7; FBAD=$(git rev-parse HEAD)
git checkout -q -b feat-good "$B0"
ticket "AMY-8.md" $NEW 開發中 "- W1 訂單清單頁" "- 走查（真人眼看）W1 訂單清單頁"
git add tickets/AMY-8.md && git commit -qm good8; FGOOD=$(git rev-parse HEAD)
# stage 在這之後把 AMY-6 補好（分支落後 stage）
git checkout -q -b stage-fix "$B0"
ticket "AMY-6.md" $NEW 開發中 "- W1 訂單清單頁" "- 走查（真人眼看）W1 訂單清單頁"
git add tickets/AMY-6.md && git commit -qm fix6; SFIX=$(git rev-parse HEAD)
git update-ref refs/remotes/origin/stage "$SFIX"
expect_ref "--ref 沒交代的分支 → 擋" 1 "$FBAD"
expect_ref "--ref 有交代的分支 → 過；分支落後 stage、stage 補好的舊缺漏不誤抓（merge-base）" 0 "$FGOOD"
expect_ref "--ref 多條：一好一壞 → 擋（取最嚴）" 1 "$FGOOD" "$FBAD"
if grep -q "${FGOOD}：通過" "$TMP/out" && grep -q "${FBAD}：這幾張票" "$TMP/out" && grep -q 'AMY-7' "$TMP/out"; then
  echo "  ✅ 多條各印各的，壞的列出票名"
else
  echo "  ❌ 多條沒有各印各的"; sed 's/^/     /' "$TMP/out"; fail=1
fi
expect_ref "--ref 不認得的分支 → 結束碼 2（不當成通過）" 2 "no-such-branch"
git checkout -q feat-bad
expect_ref "--ref 不給參數 → 用目前 HEAD（壞的）→ 擋" 1
git checkout -q feat-good
expect_ref "--ref 不給參數 → 用目前 HEAD（好的）→ 過" 0
git checkout -q "$B0"

# 生效日從哪裡讀：--since 參數 > 環境變數 TICKET_RULES_SINCE > 腳本旁的 framework-config.sh；留空＝所有票都套用。
# 同一張「沒交代、生效日前一天建立」的票，生效日不同、結果就不同。
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
ticket "AMY-09-生效日.md" $OLD 開發中 "- W1 訂單清單頁" "- 根因"
git add tickets/AMY-09-生效日.md && git commit -qm since; SS=$(git rev-parse HEAD)
expect_cmd "環境變數的生效日比票晚一天 → 不查" 0 "" env TICKET_RULES_SINCE="$SINCE" python3 -I "$LINT" "$BASE" "$SS"
expect_cmd "環境變數設成空的 → 所有票都套用 → 擋" 1 "W1" env TICKET_RULES_SINCE= python3 -I "$LINT" "$BASE" "$SS"
expect_cmd "--since 蓋過環境變數（往前挪一天）→ 擋" 1 "W1" env TICKET_RULES_SINCE="$SINCE" python3 -I "$LINT" --since "$OLD" "$BASE" "$SS"
expect_cmd "--since=<日期> 的寫法、接在 --ref 前面 → 擋" 1 "W1" python3 -I "$LINT" --since="$OLD" --ref "$SS"
expect_cmd "--since 給空字串 → 所有票都套用 → 擋" 1 "W1" python3 -I "$LINT" --since "" "$BASE" "$SS"
expect_cmd "生效日格式錯誤 → 講出來，並當成全部套用（不是靜靜整條關掉）" 1 "格式錯誤" env TICKET_RULES_SINCE=2025/06/01 python3 -I "$LINT" "$BASE" "$SS"
expect_cmd "--since 後面沒接日期 → 結束碼 2" 2 "--since" python3 -I "$LINT" "$BASE" "$SS" --since
mkdir -p "$CFG/scripts" && cp "$LINT" "$CFG/scripts/walkthrough_record_lint.py"
printf '# 設定檔\nTICKET_RULES_SINCE="%s"   # 行尾註解\n' "$SINCE" > "$CFG/scripts/framework-config.sh"
expect_cmd "沒給參數、沒有環境變數 → 讀腳本旁的 framework-config.sh（票早一天 → 不查）" 0 "" no_env python3 -I "$CFG/scripts/walkthrough_record_lint.py" "$BASE" "$SS"
printf 'TICKET_RULES_SINCE=%s\n' "$OLD" > "$CFG/scripts/framework-config.sh"
expect_cmd "設定檔的生效日往前挪一天（沒加引號的寫法）→ 擋" 1 "W1" no_env python3 -I "$CFG/scripts/walkthrough_record_lint.py" "$BASE" "$SS"
expect_cmd "環境變數蓋過設定檔 → 不查" 0 "" env TICKET_RULES_SINCE="$SINCE" python3 -I "$CFG/scripts/walkthrough_record_lint.py" "$BASE" "$SS"
printf 'TICKET_RULES_SINCE=""\n' > "$CFG/scripts/framework-config.sh"
expect_cmd "設定檔留空 → 所有票都套用 → 擋" 1 "W1" no_env python3 -I "$CFG/scripts/walkthrough_record_lint.py" "$BASE" "$SS"
rm -f "$CFG/scripts/framework-config.sh"
expect_cmd "沒有設定檔 → 所有票都套用 → 擋" 1 "W1" no_env python3 -I "$CFG/scripts/walkthrough_record_lint.py" "$BASE" "$SS"

if [ "$fail" -eq 0 ]; then echo "[walkthrough-record-lint-test] ✅ 通過"; else echo "[walkthrough-record-lint-test] ❌ 有失敗"; exit 1; fi
