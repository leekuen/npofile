#!/usr/bin/env bash
# 票務一致性 lint：驗證 tickets/<票號>-*.md 的 frontmatter 與基本一致性。
# 掛在 make check（專案有 CI 就一起掛），漂移直接紅燈。規則來源：tickets/README.md。
# 票號舊制前綴（TICKET_PREFIX）與新票規的生效日（TICKET_RULES_SINCE）在 scripts/framework-config.sh 設定。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# 環境變數 TICKET_RULES_SINCE 優先於設定檔（測試與一次性覆寫用）。設定檔是無條件賦值，
# 所以先記下環境裡有沒有給、source 完再放回去。
_since_in_env="${TICKET_RULES_SINCE+set}"
_since_env_value="${TICKET_RULES_SINCE:-}"
. "$ROOT/scripts/framework-config.sh"
[ -n "$_since_in_env" ] && TICKET_RULES_SINCE="$_since_env_value"
TICKETS_DIR="${TICKETS_DIR:-$ROOT/tickets}"

fail=0

#: 整合分支：撞號比對與「本次改動到哪幾張票」共用同一個基準。
INTEGRATION_FOR_DIFF="${TICKET_LINT_BASE:-origin/stage}"

err() { echo "[ticket-lint] $1" >&2; fail=1; }
warn() { echo "[ticket-lint][warn] $1" >&2; }  # 提醒不擋（協作軟規則）

# ── 新票規的生效日（TICKET_RULES_SINCE）──────────────────────────────────
#
# 〈這次可能會弄壞什麼〉〈條件確認〉〈數字口徑〉這三條，只擋 `created` 在這一天（含）之後的票。
# 舊票不溯及——一上線就讓全庫紅，這個檢查會在當天被關掉（同源專案 v4.45.0 對「區塊標題重複」的判斷）。
# 源專案是三條各寫死一個日期（都訂在規則落地的隔天：落地當天已經開好的票不該被新規則追溯），
# 範本收成這一個變數：新專案保持預設＝所有票都套用；留空或沒設也當成全部套用。
#
# ⚠️ 這條讀的是票自己填的 `created:`，**改一個字就繞得過**；它擋的是忘記，
# 不是擋鐵了心要繞的人。
# 不改用 `git log` 取真正的建立時間：每張票各開一次行程，幾百張票就是幾百次 fork，
# 而這支掛在每個 session 的開場簡報上（見下面「一次 awk 取完」與遠端比對那兩段的優化，源專案 v4.19.0／v4.22.1）。
RULES_SINCE="${TICKET_RULES_SINCE:-}"
if [ -n "$RULES_SINCE" ] && ! [[ "$RULES_SINCE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  # 日期是用字串比大小的：格式不對（例 2026/1/5）會讓每張票都排在它前面，三條檢查靜靜全關。寧可紅。
  err "TICKET_RULES_SINCE 格式錯誤（'${RULES_SINCE}'），應為 YYYY-MM-DD 或留空（這次先當成「全部套用」）"
  RULES_SINCE=""
fi

# ── 〈條件確認〉（源專案 v5.5.0）──────────────────────────────────────────
#
# 只擋生效日（含）之後建立、開發中或完成、且本次有改動的票。
#
# ⚠️ **這條擋的是「忘記」，不是「亂填」**（誠實寫在這裡，不要讓人以為它有保證）：
#   ・擋得到：票文字出現「出現條件／可見性／回填／篩選…」卻整節都沒有〈條件確認〉；
#     有這一節但表格壞了（缺欄、狀態不是「已確認／未確認／待 prod 資料」、沒填筆數、範例列沒刪、已確認或待 prod 資料卻沒回答日、待 prod 資料卻不是「查不到：」）。
#   ・擋不到：筆數是不是真的查過正式環境的資料、分母對不對、有沒有漏列條件、整節寫「不適用：隨便一句」、
#     字樣一個都沒出現的票（關鍵字之外的說法）、把 `created:` 改成舊日期。
#   筆數與漏列靠開票的人照 tickets/README.md〈條件確認〉做、以及案主在勾選清單上的眼睛；機器只負責「這一節在」。
#   「未確認」本身**不在這裡擋**（開發中不等案主回答）；由 scripts/unconfirmed-conditions.sh 擋：
#   推 stage 前擋一次、推 prod 前再擋一次（源專案 v5.41.0 起提前到推 stage 前）。
# 這幾個字出現在票裡（不含 HTML 註解）就必須有〈條件確認〉。寧可多抓：多抓的代價只是寫一行「不適用：<理由>」。
# 字樣清單要跟 scripts/unconfirmed-conditions.sh 的 COND_TRIGGER_RE 一模一樣（ticket-tools-test 會比對兩邊）。
COND_TRIGGER_RE='出現條件|可見性|回填|篩選|才會出現|才會顯示|才顯示|才出現|擋下|擋掉'

# ── 〈數字口徑〉（源專案 v5.19.0）──────────────────────────────────────────
#
# 票新增或改變「顯示給人看的數字」，要有〈數字口徑〉一節（寫法見 tickets/README.md〈數字口徑〉）。
# 只擋生效日（含）之後建立、開發中或完成、本次有改動的票。
# 字樣出現在票裡（不含 HTML 註解，標題行也算）就必須有這一節。不放「報表」「匯出」「筆數」「統計」：一般的票也常出現。
# ⚠️ 擋的是「忘記」不是「亂填」：擋不到數字講法不在字樣清單裡的票（例：「X 率」「報表」）、隨手寫「不適用」、口徑填錯。
# 「未確認」不在這裡擋，由 scripts/unconfirmed-conditions.sh 擋（同上）。
# 字樣清單要跟 scripts/unconfirmed-conditions.sh 的 NUM_TRIGGER_RE 一模一樣（ticket-tools-test 會比對兩邊）；
# 專案有自己的數字講法要加，兩支一起改。
NUM_TRIGGER_RE='儀表板|統計卡|成功率|比例|比率|平均|總數|KPI'

shopt -s nullglob
# 新舊兩種票號並存（源專案 v4.11.0）：舊制 ${TICKET_PREFIX}-XXXX 不改號，
# 新票一律作者前綴（git config ticket.prefix，例 AMY-01）。
# 用「排除 README」而不是列舉前綴——新成員加入時不必回來改這裡。
files=()
for f in "$TICKETS_DIR"/*.md; do
  # 內建展開，不開 basename 子行程（幾百張票就是幾百次 fork，源專案 v4.19.0 的教訓）
  [ "${f##*/}" = "README.md" ] && continue
  files+=("$f")
done
if [ ${#files[@]} -eq 0 ]; then
  [ "$fail" -eq 0 ] && echo "[ticket-lint] OK（尚無票）"
  exit "$fail"
fi

# 一次 awk 取完所有票的 frontmatter，取代「每張票開 6 個 sed」（源專案 v4.19.0）。
# 源專案實測：兩百多張票 × 6 ＝一千多次行程啟動、四秒多，而這支掛在每個 session 的開場簡報上。
# 取值語意與逐檔 sed 完全相同：各鍵取第一次出現，status/owner 去掉行尾 # 註解與空白，
# spec 去掉 # 之後的錨點（spec 只用來當檔案路徑檢查）。
meta=$(awk '
  function cut(s){ sub(/ *#.*/,"",s); sub(/ *$/,"",s); return s }
  function cutspec(s){ sub(/ *#.*$/,"",s); return s }
  FNR==1 { order[++n]=FILENAME }
  { f=FILENAME
    if (match($0,/^id: */)     && !(f in ID)) ID[f]=substr($0,RLENGTH+1)
    if (match($0,/^status: */) && !(f in ST)) ST[f]=substr($0,RLENGTH+1)
    if (match($0,/^roles: */)  && !(f in RO)) RO[f]=substr($0,RLENGTH+1)
    if (match($0,/^title: */)  && !(f in TI)) TI[f]=substr($0,RLENGTH+1)
    if (match($0,/^spec: */)   && !(f in SP)) SP[f]=substr($0,RLENGTH+1)
    if (match($0,/^owner: */)  && !(f in OW)) OW[f]=substr($0,RLENGTH+1)
    if (match($0,/^created: */)&& !(f in CR)) CR[f]=substr($0,RLENGTH+1)
    if (match($0,/^depends: */)&& !(f in DP)) { DP[f]=substr($0,RLENGTH+1); HASDP[f]=1 }
  }
  END { for(i=1;i<=n;i++){ f=order[i]
      # 欄位分隔用 US（\x1f）不用 tab（源專案 v4.32.0）：**tab 是 IFS 空白字元，bash 的 read 會把連續的
      # tab 摺疊成一個分隔符**，於是只要有一格是空的（例如 spec 沒填），後面的值就整排
      # 往前挪一格。源專案實際踩到：某張票的 spec 空著、owner 有填，lint 印出
      # 「spec 指向不存在的檔案（<owner 的值>）」——**錯誤訊息在說謊**，真正的問題是
      # 「完成的票沒填 spec」。US 不是空白字元，空欄位就保持空欄位。
      # created 排在前七格之後：前面七格的位置不動，撞號比對那段照舊。
      # depends（源專案 v5.16.0）在 created 之後：沒寫這個鍵的舊票送出 "-"，跟「寫了但留空」分得開。
      printf "%s\037%s\037%s\037%s\037%s\037%s\037%s\037%s\037%s\n", f, ID[f], cut(ST[f]), RO[f], TI[f], cutspec(SP[f]), cut(OW[f]), cut(CR[f]), (f in HASDP) ? cut(DP[f]) : "-" }
  }' "${files[@]}")

risk_candidates=()
cond_candidates=()
num_candidates=()
while IFS=$'\037' read -r f id status roles title spec owner created depends; do
  [ -z "$f" ] && continue
  base="${f##*/}"   # 用內建展開，不開 basename 子行程（每張票一次）

  # 〈這次可能會弄壞什麼〉〈條件確認〉〈數字口徑〉只約束**動工中或已完成**、且在生效日（含）之後才建的票。
  # 待開發不擋：票剛開出來還沒討論完驗收標準，開工當下才有辦法對應
  # （也因此 `scripts/ticket-tools-test.sh` 那條「新開的票要過 lint」仍然綠）。
  # 生效日留空＝全部套用（連沒填 created 的票也算）。
  case "$status" in
    開發中|完成)
      if [ -z "$RULES_SINCE" ] || [[ "$created" > "$RULES_SINCE" || "$created" == "$RULES_SINCE" ]]; then
        risk_candidates+=("$f")
        cond_candidates+=("$f")
        num_candidates+=("$f")
      fi
      ;;
  esac

  # 舊制 ${TICKET_PREFIX}-XXXX（凍結，不再發新號）或作者前綴（PREFIX-NN，源專案 v4.11.0）
  [[ "$id" =~ ^(${TICKET_PREFIX}-[0-9]{4}|[A-Z][A-Z0-9]{1,7}-[0-9]{2,4})$ ]] \
    || err "${base}：id 格式錯誤（'$id'），應為 ${TICKET_PREFIX}-XXXX（舊制）或 前綴-NN（例 AMY-01）"
  [[ "$base" == "$id"-* ]] || err "${base}：檔名須以 id（${id}-）開頭"
  case "$status" in
    待開發|開發中|完成|作廢) ;;
    *) err "${base}：status 不合法（'$status'），只允許 待開發/開發中/完成/作廢" ;;
  esac
  [[ "$roles" =~ ^\[.*[^[:space:]].*\]$ ]] || err "${base}：roles 未填（「誰使用」是開票鐵則）"
  [ -n "$title" ] || err "${base}：title 未填"
  if [ "$status" = "完成" ] && [ -z "$spec" ]; then
    err "${base}：完成的票必須有 spec 欄位（票完成 = SPEC 同步一起完成）"
  fi
  if [ -n "$spec" ] && [ ! -f "$ROOT/${spec%%#*}" ]; then
    err "${base}：spec 指向不存在的檔案（${spec%%#*}）"
  fi
  # depends（源專案 v5.16.0）：選填；寫了就要是 [票號, 票號] 的格式、不能是自己。
  # **只擋格式，不查那張票的檔案存不存在**——只挑部分票上 prod 的專案，prod 的 tickets/ 是 stage 的子集，
  # 存在性檢查會在 prod 那棵樹和開票那棵樹誤紅。找不找得到那張票的分支，由 agent 照 tickets/README〈相依的票〉判斷。
  if [ "$depends" != "-" ]; then
    if [[ ! "$depends" =~ ^\[[[:space:]]*(([A-Z][A-Z0-9]{1,7}-[0-9]{2,4}|${TICKET_PREFIX}-[0-9]{4})([[:space:]]*,[[:space:]]*([A-Z][A-Z0-9]{1,7}-[0-9]{2,4}|${TICKET_PREFIX}-[0-9]{4}))*)?[[:space:]]*\]$ ]]; then
      err "${base}：depends 格式錯誤（'$depends'），應為 [AMY-03, BOB-12]，沒有就寫 []"
    elif [[ "$depends" =~ (^|[^A-Za-z0-9-])"$id"([^0-9]|$) ]]; then
      err "${base}：depends 不能包含自己（${id}）"
    fi
  fi
  # 多 session 領票制（tickets/README）：開發中建議填 owner，缺了提醒不擋
  if [ "$status" = "開發中" ] && [ -z "$owner" ]; then
    warn "${base}：開發中但未填 owner（多 session 協作請領票）"
  fi
done <<< "$meta"

# ── 合併弄壞的痕跡（源專案 v4.45.0）──────────────────────────────────────
#
# 源專案的事故：一次合流用「衝突區塊兩邊都留」的通用規則掃過去，把**別人的**一張票
# 弄成兩行 `title:`、外加一整份過時的區塊。是另一條 session 發現的，不是動手的那一條——
# 而 lint 當時全綠：它只取每個鍵的第一次出現，重複的那一行看不見。
#
# 這兩種痕跡是「合併沒接好」最典型的長相，而且**在畫面上完全看不出來**
# （票是給人讀的，多一段舊規格只會讓人照著做錯的那份）。
#
# 同一支 awk 掃完全部，迴圈裡不開任何行程（沿用源專案 v4.19.0／v4.20.0 的教訓）。
broken=$(awk '
  FNR==1 { f=FILENAME; fm=0; first=1 }
  {
    if (first) { first=0; if ($0=="---") { fm=1; next } }
    if (fm) {
      if ($0=="---") { fm=0; next }
      if (match($0, /^(id|title|status|owner|spec|roles|created|updated|depends): */)) {
        k=substr($0, 1, index($0,":")-1)
        if (++cnt[f,k]==2) dupkey[f]=dupkey[f] " " k
      }
      next
    }
    # 只看區塊標題（## / ###）。同名的小標在同一張票裡就是合併重複的痕跡。
    if (match($0, /^#+ /) && RLENGTH>=3 && RLENGTH<=4) {
      if (++head[f,$0]==2) duphead[f]=duphead[f] "｜" substr($0, RLENGTH+1)
    }
  }
  END {
    for (f in dupkey) print f "\037key\037" dupkey[f]
    for (f in duphead) print f "\037head\037" duphead[f]
  }
' "${files[@]}")
while IFS=$'\037' read -r f kind detail; do
  [ -z "$f" ] && continue
  base="${f##*/}"
  if [ "$kind" = "key" ]; then
    # frontmatter 重複＝**一定**是壞的（每個鍵只該有一行），而且下游都只讀第一行，
    # 所以第二行是靜默的謊。這條擋。
    err "${base}：frontmatter 有重複的欄位（${detail# }）——多半是合併沒接好"
  else
    # 區塊標題重複＝**幾乎一定**是壞的，但源專案這條剛上線時就抓到幾張既有的票
    # （都是先前合併留下的）。**先提醒不擋**（源專案 v4.45.0）：
    # 讓別人的檢查因為新加的規則而紅，等於把清理成本轉嫁給不知情的人。
    # 專案確定沒有存量之後，可以把這行改成 `err`。
    warn "${base}：有重複的區塊標題（${detail#｜}）——多半是合併把同一段留了兩份"
  fi
done <<< "$broken"

# ── 〈這次可能會弄壞什麼〉要有對得上的驗收條件（源專案 v4.52.0 前後加入）──────
#
# 源專案的事故：某張票的〈邊界〉寫了「不動隔壁那個畫面」、〈開發備註〉寫了「不要為了共用把那邊
# 改壞」——**風險當時就被寫成文字了**，但五條驗收標準沒有一條是關於那個畫面的。
# 三天後，那個畫面的五個互動在整合環境壞了一整天。
#
# 所以這裡勾稽的是**編號**，不是中文字串。「原字出現」那種寫法在出事的那張票身上
# 會直接空過：它的驗收標準本來就含有那個畫面的名字（講的是對話框長得一不一樣，
# 跟壞掉的那幾個互動完全無關）。源專案拿全部的票實測：風險行只寫一個常見詞的，有三成五自動過關。
#
# **只檢查本次改動到的票**，不掃全庫：讓別人的檢查因為新加的規則而紅，等於把清理成本
# 轉嫁給不知情的人（本檔「區塊標題重複」那一段已經立過這個判例）。
risk_na=0
changed=""
risk_scope="diff"
# 這張票在不在「本次改動」清單裡。不寫成 `printf … | grep -q`：pipefail 之下 grep 一命中就關管線，
# 寫的那一端收到 SIGPIPE，整條會被當成失敗（＝明明有改動卻被當成沒改、靜靜跳過）。
in_changed() { case $'\n'"$changed"$'\n' in *$'\n'"$1"$'\n'*) return 0 ;; esac; return 1; }
if [ ${#risk_candidates[@]} -gt 0 ] || [ ${#cond_candidates[@]} -gt 0 ] || [ ${#num_candidates[@]} -gt 0 ]; then
  # **`core.quotePath=false` 不能省**：中文檔名預設會被跳脫成 `\346\224...` 並加上引號，
  # 路徑對不起來 → 一張票都比對不到 → 整段靜靜不做事、而且每次都印 OK。
  # 撞號那一段的註解已經寫過這個坑，源專案在這裡照樣踩了一次，是突變測試把它抓出來的
  # （拿掉一條 W 的驗收條件、票卻照樣綠）。
  git_q() { git -C "$ROOT" -c core.quotePath=false "$@" 2>/dev/null; }
  # 拿得到整合分支時只檢查本次改動的票。若離線或在最小 checkout 裡真的拿不到基線，保守退成
  # 「檢查全部符合資格的票」而不是靜靜跳過，避免規則看似執行、其實完全不存在。
  # （專案有 CI 的話，跑這支的那個 job 要完整 checkout 才拿得到 origin/stage。）
  if git_q rev-parse --verify --quiet "$INTEGRATION_FOR_DIFF" >/dev/null; then
    changed=$( { git_q diff --name-only "$INTEGRATION_FOR_DIFF"...HEAD -- 'tickets/*.md';
                 git_q diff --name-only HEAD -- 'tickets/*.md';
                 git_q ls-files --others --exclude-standard -- 'tickets/*.md'; } | sort -u)
    risk_scope="diff"
  else
    changed=""
    risk_scope="all"
    echo "[ticket-lint] 取不到 ${INTEGRATION_FOR_DIFF}，〈這次可能會弄壞什麼〉〈條件確認〉〈數字口徑〉改為檢查全部符合資格的票"
  fi
fi
if [ ${#risk_candidates[@]} -gt 0 ]; then
  for f in "${risk_candidates[@]}"; do
    if [ "$risk_scope" = "diff" ]; then
      rel="${f#$ROOT/}"
      in_changed "$rel" || continue
    fi
    base="${f##*/}"
    out=$(awk '
      function clean(l) { gsub(/^[ \t]*[-*][ \t]*(\[[ xX]\][ \t]*)?/, "", l); gsub(/`/, "", l); gsub(/^[ \t]+|[ \t]+$/, "", l); return l }
      /^#+ / {
        sec = ""
        if ($0 ~ /^#+[ \t]*這次可能會弄壞什麼/) { sec = "risk"; seen_risk = 1 }
        else if ($0 ~ /^#+[ \t]*驗收標準/ || $0 ~ /^#+[ \t]*走查/) sec = "accept"
        next
      }
      sec == "risk" {
        # 多行 HTML 註解（模板那段說明）整段跳過（源專案 v4.83.0）：只擋開頭與結尾兩行的話，中間幾行會被當成
        # 「沒編號的風險行」，新票照範本填了 W1 卻不刪註解就紅。
        if (incomment) { if ($0 ~ /-->/) incomment = 0; next }
        if ($0 ~ /<!--/ && $0 !~ /-->/) { incomment = 1; next }
        l = clean($0)
        if (l == "") next
        if (l ~ /^<!--/ || l ~ /-->$/) next   # 單行註解也不是風險行
        if (l ~ /^不適用/) { na = 1; next }
        if (match(l, /^W[0-9]+/)) { risk[substr(l, 1, RLENGTH)] = 1; nrisk++ }
        else bad = bad "｜" l
      }
      sec == "accept" {
        l = clean($0)
        if (match(l, /^W[0-9]+/)) cov[substr(l, 1, RLENGTH)] = 1
      }
      END {
        if (!seen_risk) { print "ERR\t缺〈這次可能會弄壞什麼〉這一節"; exit }
        if (na) { print "NA"; exit }
        if (nrisk == 0) { print "ERR\t〈這次可能會弄壞什麼〉是空的——至少一行，真的沒有就寫「不適用：<理由>」"; exit }
        if (bad != "") { sub(/^｜/, "", bad); print "ERR\t這幾行沒有編號（要寫成「W1 某個清單頁」這種格式）：" bad }
        miss = ""
        for (k in risk) if (!(k in cov)) miss = miss "、" k
        if (miss != "") { sub(/^、/, "", miss); print "ERR\t" miss " 沒有對應的驗收／走查條件（要有一行以同一個編號開頭）" }
      }
    ' "$f")
    while IFS=$'\t' read -r kind detail; do
      [ -z "$kind" ] && continue
      [ "$kind" = "NA" ] && { risk_na=$((risk_na + 1)); continue; }
      err "${base}：${detail}"
    done <<< "$out"
  done
fi
[ "$risk_na" -gt 0 ] && echo "[ticket-lint] 本次有 ${risk_na} 張票宣告〈這次可能會弄壞什麼〉不適用"

# ── 自己加的條件要有〈條件確認〉表（源專案 v5.5.0）──────────────────────────
#
# 源專案的事故：agent 開票時自己加了條件（「某一區至少有一筆才出現確認勾選」「清單不帶某個欄位」），
# 案主同意了卻沒細看，上線後正式環境大量真實資料被擋（其中一條：三千多筆只有十筆符合）。
# 失靈點是「問案主的當下沒有筆數」，所以票裡要有一張表把每條條件的符合／擋掉筆數與分母擺出來。
#
# 這裡只擋兩種事：①票文字出現 COND_TRIGGER_RE 的字樣卻整節沒有〈條件確認〉；
# ②有這一節，但表格壞了（缺欄、狀態不是「已確認／未確認／待 prod 資料」、沒填筆數、範例列沒刪、已確認或待 prod 資料卻沒回答日、待 prod 資料卻不是「查不到：」）。
# 其餘（筆數真不真、漏列、「不適用」寫得隨便）機器看不出來，見上面〈條件確認〉那段的聲明。
# 同〈這次可能會弄壞什麼〉：只檢查本次改動到的票（risk_scope 共用同一份「改動清單」）。
cond_na=0
if [ ${#cond_candidates[@]} -gt 0 ]; then
  for f in "${cond_candidates[@]}"; do
    if [ "$risk_scope" = "diff" ]; then
      rel="${f#$ROOT/}"
      in_changed "$rel" || continue
    fi
    base="${f##*/}"
    # LC_ALL=C（源專案 v5.9.0）：length() 在 mawk／BWK awk 算位元組、在 UTF-8 的 gawk 算字元，不同機器結果不同
    # （源專案因此多推了一次 stage）；釘成位元組，各處一致。這支 awk 不用 substr 照字數切中文（會切壞字），
    # 要去前綴用 sub(/^、/, "")。
    out=$(LC_ALL=C awk -v trig="$COND_TRIGGER_RE" '
      function trim(x) { gsub(/^[ \t]+|[ \t]+$/, "", x); return x }
      function emit(m) { print "ERR\t" m }
      NR == 1 && $0 == "---" { fm = 1; next }
      fm { if ($0 == "---") fm = 0; next }
      # HTML 註解（範本說明）整段略過：說明文字裡本來就有這些關鍵字，不能算票自己的內容
      incomment { if ($0 ~ /-->/) incomment = 0; next }
      $0 ~ /^[ \t]*<!--/ { if ($0 !~ /-->/) incomment = 1; next }
      /^#+ / {
        sec = "other"
        if ($0 ~ /^#+[ \t]*條件確認/) { sec = "cond"; seen = 1 }
        else if (!trigger && match($0, trig)) { trigger = 1; word = substr($0, RSTART, RLENGTH) }   # 標題也算（unconfirmed-conditions.sh 也算）
        next
      }
      sec != "cond" {
        if (!trigger && match($0, trig)) { trigger = 1; word = substr($0, RSTART, RLENGTH) }
        next
      }
      # ── 條件確認這一節 ──
      {
        l = trim($0)
        if (l == "") next
        if (l ~ /^不適用/) {
          na = 1; r = l; sub(/^不適用/, "", r); sub(/^[ \t]*(:|：)?[ \t]*/, "", r)   # 全形冒號不能放進 [...]
          if (length(r) < 4) emit("〈條件確認〉寫了「不適用」但沒有理由（寫成「不適用：<理由>」）")
          next
        }
        if (l !~ /^\|/) { if (l ~ /\|/) emit("〈條件確認〉有一列沒有開頭的 |（Markdown 會當成表格、這支檢查會看不見它）：「" l "」"); next }
        n = split(l, c, "|")          # c[1] 是第一個 | 之前（空），格子 j 在 c[j+1]
        ncell = n - 2                 # 去掉頭尾兩個空段
        if (!hdr) {
          if (trim(c[2]) ~ /^條件/) {
            hdr = 1
            for (j = 1; j <= ncell; j++) {
              h = trim(c[j + 1])
              if (index(h, "符合") == 1) col_ok = j
              else if (index(h, "擋掉") == 1) col_blk = j
              else if (index(h, "狀態") == 1) col_st = j
              else if (index(h, "回答日") == 1) col_dt = j
            }
            miss = ""
            if (!col_ok)  miss = miss "、符合"
            if (!col_blk) miss = miss "、擋掉"
            if (!col_st)  miss = miss "、狀態"
            if (!col_dt)  miss = miss "、回答日"
            if (miss != "") { sub(/^、/, "", miss); emit("〈條件確認〉表頭缺欄位：" miss "（欄位要有 條件／符合／擋掉／狀態／回答日）") }
          }
          next
        }
        if (l ~ /^\|[ \t:|-]+\|?$/) next   # 分隔列 |---|---|
        rows++
        # 多位元組字元不能放進 [...]（BWK awk 逐位元組處理，括號運算式會把全形字拆壞，測試抓到的），一律用 | 分支
        cond = trim(c[2])
        label = cond
        if (cond == "" ) { emit("〈條件確認〉第 " rows " 列的條件是空的"); next }
        if (cond ~ /^(\(|（)例(\)|）)/) emit("〈條件確認〉還留著範本的範例列（「" label "」）——換成這張票自己的條件，或整節改寫成「不適用：<理由>」")
        if (col_ok  && trim(c[col_ok + 1])  == "") emit("〈條件確認〉「" label "」的〈符合〉沒填筆數（查不到就寫「查不到：<原因>」）")
        if (col_blk && trim(c[col_blk + 1]) == "") emit("〈條件確認〉「" label "」的〈擋掉〉沒填筆數（查不到就寫「查不到：<原因>」）")
        if (col_st) {
          st = trim(c[col_st + 1])
          if (st != "已確認" && st != "未確認" && st != "待 prod 資料") emit("〈條件確認〉「" label "」的〈狀態〉要寫「已確認」、「未確認」或「待 prod 資料」（現在是「" st "」）")
          else if (st == "已確認" && col_dt && trim(c[col_dt + 1]) !~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$/)
            emit("〈條件確認〉「" label "」已確認卻沒有回答日（寫 YYYY-MM-DD）")
          else if (st == "待 prod 資料") {
            # 源專案 v5.41.0：只有「要看到 prod 筆數才答得出來」的列可以延後；案主在推 stage 前那則清單同意延後，回答日填那天
            if (col_ok && col_blk && trim(c[col_ok + 1]) !~ /^查不到：/ && trim(c[col_blk + 1]) !~ /^查不到：/)
              emit("〈條件確認〉「" label "」標了「待 prod 資料」，但〈符合〉或〈擋掉〉不是「查不到：<原因>」開頭（有筆數就現在問案主，不能延後）")
            if (col_dt && trim(c[col_dt + 1]) !~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$/)
              emit("〈條件確認〉「" label "」標了「待 prod 資料」卻沒有回答日（案主同意延後的那天，寫 YYYY-MM-DD；沒問過案主就不能標）")
          }
        }
      }
      END {
        if (!seen) {
          if (trigger) emit("票裡出現「" word "」這類字樣，但沒有〈條件確認〉這一節（自己加的條件要附筆數；真的沒有就加這一節寫「不適用：<理由>」，範本見 tickets/README.md）")
          exit
        }
        if (na && !hdr) { print "NA"; exit }
        if (!hdr) { emit("〈條件確認〉沒有表格（欄位：條件／符合／擋掉／狀態／回答日；沒有條件就寫「不適用：<理由>」）"); exit }
        if (rows == 0) emit("〈條件確認〉表格沒有任何一列（沒有條件就整節改寫成「不適用：<理由>」）")
      }
    ' "$f")
    while IFS=$'\t' read -r kind detail; do
      [ -z "$kind" ] && continue
      [ "$kind" = "NA" ] && { cond_na=$((cond_na + 1)); continue; }
      err "${base}：${detail}"
    done <<< "$out"
  done
fi
[ "$cond_na" -gt 0 ] && echo "[ticket-lint] 本次有 ${cond_na} 張票宣告〈條件確認〉不適用"

# ── 給人看的數字要有〈數字口徑〉表（源專案 v5.19.0）────────────────────────
#
# 源專案的事故：某個成功率的分母是實作時自己定的，票裡只有六個字，案主在畫面上看到說明文字才問
# 「這個公式確定最好嗎」。
# 這裡只擋兩種事：①票文字出現 NUM_TRIGGER_RE 的字樣卻整節沒有〈數字口徑〉；
# ②有這一節，但表格壞了（沒有表頭、沒有任何一列、狀態不是「已確認／未確認」、已確認卻沒回答日、不適用沒理由）。
# 同〈條件確認〉：只檢查本次改動到的票（risk_scope 共用同一份「改動清單」）。
num_na=0
if [ ${#num_candidates[@]} -gt 0 ]; then
  for f in "${num_candidates[@]}"; do
    if [ "$risk_scope" = "diff" ]; then
      rel="${f#$ROOT/}"
      in_changed "$rel" || continue
    fi
    base="${f##*/}"
    out=$(LC_ALL=C awk -v trig="$NUM_TRIGGER_RE" '
      function trim(x) { gsub(/^[ \t]+|[ \t]+$/, "", x); return x }
      function emit(m) { print "ERR\t" m }
      NR == 1 && $0 == "---" { fm = 1; next }
      fm { if ($0 == "---") fm = 0; next }
      incomment { if ($0 ~ /-->/) incomment = 0; next }
      $0 ~ /^[ \t]*<!--/ { if ($0 !~ /-->/) incomment = 1; next }
      /^#+ / {
        sec = "other"
        if ($0 ~ /^#+[ \t]*數字口徑/) { sec = "num"; seen = 1 }
        else if (!trigger && match($0, trig)) { trigger = 1; word = substr($0, RSTART, RLENGTH) }   # 標題也算（unconfirmed-conditions.sh 也算）
        next
      }
      sec != "num" {
        if (!trigger && match($0, trig)) { trigger = 1; word = substr($0, RSTART, RLENGTH) }
        next
      }
      {
        l = trim($0)
        if (l == "") next
        if (l ~ /^不適用/) {
          na = 1; r = l; sub(/^不適用/, "", r); sub(/^[ \t]*(:|：)?[ \t]*/, "", r)
          if (length(r) < 4) emit("〈數字口徑〉寫了「不適用」但沒有理由（寫成「不適用：<理由>」）")
          next
        }
        if (l !~ /^\|/) { if (l ~ /\|/) emit("〈數字口徑〉有一列沒有開頭的 |（Markdown 會當成表格、這支檢查會看不見它）：「" l "」"); next }
        n = split(l, c, "|")
        ncell = n - 2
        if (!hdr) {
          if (trim(c[2]) ~ /^數字/) {
            hdr = 1
            for (j = 1; j <= ncell; j++) {
              h = trim(c[j + 1])
              if (index(h, "狀態") == 1) col_st = j
              else if (index(h, "回答日") == 1) col_dt = j
            }
            miss = ""
            if (!col_st) miss = miss "、狀態"
            if (!col_dt) miss = miss "、回答日"
            if (miss != "") { sub(/^、/, "", miss); emit("〈數字口徑〉表頭缺欄位：" miss "（第一欄「數字」，最後兩欄「狀態」「回答日」）") }
          }
          next
        }
        if (l ~ /^\|[ \t:|-]+\|?$/) next
        rows++
        label = trim(c[2])
        if (label == "") { emit("〈數字口徑〉第 " rows " 列的數字是空的"); next }
        if (label ~ /^(\(|（)例(\)|）)/) emit("〈數字口徑〉還留著範本的範例列（「" label "」）——換成這張票自己的數字，或整節改寫成「不適用：<理由>」")
        if (col_st) {
          st = trim(c[col_st + 1])
          if (st != "已確認" && st != "未確認") emit("〈數字口徑〉「" label "」的〈狀態〉要寫「已確認」或「未確認」（現在是「" st "」）")
          else if (st == "已確認" && col_dt && trim(c[col_dt + 1]) !~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$/)
            emit("〈數字口徑〉「" label "」已確認卻沒有回答日（寫 YYYY-MM-DD）")
        }
      }
      END {
        if (!seen) {
          if (trigger) emit("票裡出現「" word "」這類字樣，但沒有〈數字口徑〉這一節（新增或改變顯示給人看的數字要寫口徑；真的沒有就加這一節寫「不適用：<理由>」，寫法見 tickets/README.md〈數字口徑〉）")
          exit
        }
        if (na && !hdr) { print "NA"; exit }
        if (!hdr) { emit("〈數字口徑〉沒有表格（第一欄「數字」；沒有數字就寫「不適用：<理由>」）"); exit }
        if (rows == 0) emit("〈數字口徑〉表格沒有任何一列（沒有數字就整節改寫成「不適用：<理由>」）")
      }
    ' "$f")
    while IFS=$'\t' read -r kind detail; do
      [ -z "$kind" ] && continue
      [ "$kind" = "NA" ] && { num_na=$((num_na + 1)); continue; }
      err "${base}：${detail}"
    done <<< "$out"
  done
fi
[ "$num_na" -gt 0 ] && echo "[ticket-lint] 本次有 ${num_na} 張票宣告〈數字口徑〉不適用"

dups=$(sed -n 's/^id: *//p' "${files[@]}" | sort | uniq -d)
# 全形括號緊接 $dups 會被 bash 當成變數名的一部分（set -u 下直接炸掉，
# 反而讓「回報撞號」自己先死——源專案 v4.2.1 在 new-ticket.sh 修過同一個坑）。
[ -n "${dups}" ] && err "id 重複：${dups}（號碼不重用；兩個 session 同前綴撞號時，第二個 session 用 TICKET_PREFIX 指定別名）"

# ── 與整合分支比對撞號（源專案 v4.20.0）──────────────────────────────────
#
# 上面那段只看**本地工作樹**，所以「我的 AMY-07」與「stage 上別人的 AMY-07」
# 在本地永遠是綠的，要到合併那一刻才炸。源專案真的發生過：本地兩百多張全過，
# 一 merge 就發現同號不同票（兩張講的是完全不相干的兩件事）。
#
# 作者前綴（源專案 v4.11.0）解決的是**不同人**之間的撞號；**同一個前綴、不同 session／
# 不同分支**照樣會撞——取號與推送之間本來就有競爭條件。
#
# 判準：**同 id 且 title 不同** 才算撞號。同 id 同 title＝同一張票的不同版本，不算。
# 拿不到遠端（離線／淺 clone）就跳過，不讓 lint 失敗。
#
# **比得到不等於比得出東西**（源專案 v4.48.2）。整合分支已經在 HEAD 的歷史裡時，
# 它的每一張票都在我的工作樹裡，「遠端有、我這邊看不到」在定義上不存在——
# 這段跑起來必然零輸出。CI 常見的兩條路徑剛好都長這樣：
#   ・push 到 stage：`origin/stage` 就是 HEAD，拿自己比自己。
#   ・合併請求：checkout 取的是合併後的那個 commit，
#     merge-base 等於整合分支的頂端 → 每個號都算「分歧前就有」→ 被改名豁免整個抵銷。
# 而**真的同號不同票在這兩種情況下都紅得起來**：merge 後的樹裡兩個檔並存，
# 由上面的「id 重複」擋（那條不需要遠端，淺 clone 也跑得動；沙盒實測印的
# 正是「id 重複」而不是「撞號」）。
#
# 這裡刻意**印一行**而不是靜靜跳過：源專案 v4.48.1 的教訓就是「跑了但永遠沒輸出」
# 跟「跑了而且真的比過」在畫面上長得一模一樣。log 要自己說清楚守的人是誰。
INTEGRATION="$INTEGRATION_FOR_DIFF"
if git -C "$ROOT" rev-parse --verify --quiet "$INTEGRATION" >/dev/null 2>&1 \
   && git -C "$ROOT" merge-base --is-ancestor "$INTEGRATION" HEAD 2>/dev/null; then
  echo "[ticket-lint] 撞號比對跳過：${INTEGRATION} 已在 HEAD 的歷史裡（同號不同票改由上面的「id 重複」擋）"
elif git -C "$ROOT" rev-parse --verify --quiet "$INTEGRATION" >/dev/null 2>&1; then
  # 一次 `git grep` 撈回遠端**所有**票的 title，再用一次 awk 在記憶體裡比對，
  # 迴圈裡不開任何行程（源專案 v4.22.1）。v4.20.0 第一版是「每個遠端票檔各開 basename／sed／git show／
  # sed｜head」，兩百多張票＝近兩千次 fork＝五秒多；而這支掛在每個 session 的開場簡報上。
  # 這跟源專案 v4.19.0 把「每張票各開 6 個 sed」改成單次 awk 是同一種修法。
  #
  # **`core.quotePath=false` 不能省**：中文檔名預設會被跳脫成 `\346\224...` 並加上引號，
  # 路徑對不起來，整段會靜靜不做事（源專案開發時就是這樣綠過一次）。
  # **不要用 `printf … | grep -m1`**：`-m1` 一命中就關掉管線 → 每張票噴一行
  # `printf: write error: Broken pipe`，log 被洗到看不見真正的錯誤（源專案 v4.20.0 踩過）。
  #
  # 本地 title 直接沿用上面那次 awk 已經解析好的 `$meta`，不重讀檔案。
  clashes=$(awk -v integ="$INTEGRATION" '
    # **id 是「前綴-數字」兩段**，`${base%%-*}` 只會取到前綴那一段（源專案 v4.20.0 踩過）。
    function idof(b) { if (match(b, /^[A-Z][A-Z0-9]*-[0-9]+-/)) return substr(b, 1, RLENGTH-1); return "" }
    # 第一份輸入：本地 meta。**分隔符必須跟上面產生 $meta 的那個 printf 一致（US＝\037，不是 tab）**：
    # 這裡原本寫 `split($0, a, "\t")`，切 US 分隔的資料只會得到 1 個欄位 → `< 5` → `next`
    # → 本地 title 表 LT 永遠是空的 → 下面的 `!(k in LT)` 一律成立 → 撞號永遠印不出來。
    # 源專案從 v4.20.0 上線到 v4.48.1 修掉之間，這段檢查一次都沒有真的執行過，而 lint 每次都印
    # 「OK（N 張票通過）」——**現役的假保護**。改分隔符前先看產生 $meta 那段
    # 為什麼是 US 不是 tab。回歸測試在 ticket-tools-test.sh「遠端撞號」那幾條。
    NR==FNR {
      if (split($0, a, "\037") < 5) next
      p = a[1]; sub(/^.*\/tickets\//, "tickets/", p)   # repo 相對路徑，用來認「同一個檔」
      b = a[1]; sub(/^.*\//, "", b); k = idof(b)
      if (k == "" || a[5] == "") next
      if (!(k in LT)) { LT[k] = a[5]; LP[k] = p }   # 與原本「取第一個檔名符合的本地票」同語意
      next
    }
    # 第二份輸入：git grep 的 `<integ>:<path>:title: <標題>`；integ 長度已知，直接切掉
    {
      rest = substr($0, length(integ) + 2)
      p = index(rest, ".md:"); if (p == 0) next
      path = substr(rest, 1, p + 2)
      if (path in SEEN) next          # 同一檔多行 title 只取第一行（等同原本的 head -1）
      SEEN[path] = 1
      rt = substr(rest, p + 4); sub(/^title: */, "", rt)
      b = path; sub(/^.*\//, "", b); k = idof(b)
      if (k == "" || rt == "" || !(k in LT)) next
      # **同一個檔案路徑＝同一張票被改標題，不是撞號**（源專案 v4.26.0）。
      # 一個路徑不可能同時是兩張不同的票，所以路徑相同時 title 變動必然是改名。
      # 沒有這條，任何一次正當的改標題都會讓 make check 紅燈紅到推上 stage 為止，
      # 於是大家就把「標題與內容不符」的票留著——正是這條 lint 想防的反面。
      if (path == LP[k]) next
      # **這裡也用 US，不用 tab**：理由同產生 $meta 那段。標題真的含 tab 時，
      # tab 通道會讓撞號訊息自己欄位錯位（本地標題被切成兩半）。
      # 兩邊都去掉尾隨空白再比：只差一個空白的「撞號」訊息看起來一模一樣，沒人查得下去。
      lt = LT[k]; sub(/[ \t]+$/, "", lt); sub(/[ \t]+$/, "", rt)
      if (lt != rt) printf "%s\037%s\037%s\n", k, rt, lt
    }
  ' <(printf '%s\n' "$meta") \
    <(git -C "$ROOT" -c core.quotePath=false grep --color=never -e '^title: ' "$INTEGRATION" -- 'tickets/*.md' 2>/dev/null))
  if [ -n "$clashes" ]; then
    # **改名 ≠ 撞號**（源專案 v4.48.1）。上面只豁免「檔案路徑相同」，但檔名慣例是
    # `<id>-<標題>.md`——改標題時把檔名一起改是常態。路徑因此不同，
    # 於是**正當改名**會被判成撞號，而訊息還叫人「改號」：
    # 完全錯誤的處置，且改名的人從那一刻到合進 stage 為止 `make check` 一路紅。
    # 一條檢查第一次真的活起來的時候，誤報會直接讓人把紅燈當噪音——正是它想防的反面。
    #
    # 真正的分界是**這個號碼在分歧點之前就存在了嗎**：
    #   ・在 → 遠端那張比我的分支還老，我這張同號的就是它（改名／改標題），不是撞號。
    #   ・不在 → 兩邊在分歧之後各自取到同一個號，才是撞號。
    # `new-ticket.sh` 取號時會掃**全部遠端分支**取 max+1，所以「分歧前就存在的號」本來就
    # 取不到——這個判準與取號邏輯是同一套假設，不是另外發明的相似度啟發式。
    # **這樣不會漏**：分歧前就存在的票，我的工作樹本來就有那個檔，真的同號會被上面的
    # 「id 重複」抓到（實測：把兩張同號的票放進同一個 tickets/ → 立刻紅）。
    # 遠端比對要守的本來就是**還沒合進來、我這邊看不到**的那一張。
    #
    # 只在**真的有嫌疑時**才多開這兩個行程（平常 0 次，開場簡報的耗時不受影響）。
    mb_ids=""
    mb=$(git -C "$ROOT" merge-base HEAD "$INTEGRATION" 2>/dev/null)
    if [ -n "$mb" ]; then
      mb_ids=$(git -C "$ROOT" -c core.quotePath=false ls-tree -r --name-only "$mb" -- tickets/ 2>/dev/null \
        | sed -n 's|^tickets/\([A-Z][A-Z0-9]*-[0-9][0-9]*\)-.*|\1|p' | sort -u)
    fi
    reported=0
    while IFS=$'\037' read -r rid rtitle ltitle; do
      [ -z "$rid" ] && continue
      # 分歧前就有這個號 → 同一張票改了名，放行（拿不到 merge-base 時寧可報，維持原行為）
      case $'\n'"$mb_ids"$'\n' in *$'\n'"$rid"$'\n'*) continue ;; esac
      err "撞號：${rid} 在 ${INTEGRATION} 上是「${rtitle}」，本地是「${ltitle}」——兩張不同的票同一個號碼"
      reported=1
    done <<< "$clashes"
    [ "$reported" -eq 1 ] && \
      echo "  先落地的那張保留號碼，後來的改號（檔名、frontmatter 的 id、以及所有引用一起改）。" >&2
  fi
else
  echo "[ticket-lint] 跳過遠端比對（取不到 ${INTEGRATION}）"
fi

if [ "$fail" -eq 0 ]; then
  echo "[ticket-lint] OK（${#files[@]} 張票通過）"
fi
exit "$fail"
