#!/usr/bin/env bash
# 列出票的〈條件確認〉表裡「還沒確認」的條件（源專案 v5.5.0）——推 prod 前用；
# 推 stage 前也用同一套判準（源專案 v5.41.0，stage 模式，見下面）。
#
# 用法：scripts/unconfirmed-conditions.sh AMY-12 [AMY-13 …]
#   結束碼：0＝這幾張票都沒有未確認的條件；1＝有（逐條印出）；2＝找不到其中一張票（不能當成「沒有」）。
#       scripts/unconfirmed-conditions.sh --stage-range <遠端現況 sha> <要推的 sha>   （.githooks/pre-push 用）
#       scripts/unconfirmed-conditions.sh --stage-ref <分支或 commit>…                 （合流前先查：make confirm-lint）
#   stage 模式（源專案 v5.41.0：「推 stage 前就先確認，通過才可推」，起因是一張票自己加的條件還沒確認就進了 stage）：
#     ・查哪幾張票：範圍內有改動的票檔，而且**被推的那一版**狀態是開發中或完成（不比遠端那一版：stage 驗收後返工也要查）；
#       範圍內沒有符合的票＝通過（結束碼 0，不走上面「沒給票號」的用法分支）。
#     ・讀**被推的 commit** 裡的票檔（git show <sha>:<票檔>），不讀工作樹、不讀 origin/stage；不 fetch（hook 不能因網路卡住）。
#       用目前所在的 git repo（pre-push 在 repo 裡跑），不是這支腳本所在的 repo。
#     ・判準同上（不是「已確認」就擋），只多一個例外：〈條件確認〉狀態「待 prod 資料」，而且〈符合〉或〈擋掉〉格開頭是「查不到：」、
#       〈回答日〉是 YYYY-MM-DD（案主同意延後的那天）——三個都有才放行並印一行提醒。〈數字口徑〉沒有這個例外。
#       推 prod 前（不加 --stage-*）「待 prod 資料」照樣算沒確認：重查 prod 筆數再問。
#     ・--stage-ref 每個 ref 自己算 `git merge-base origin/stage <ref>`（同 make walkthrough-lint；先 git fetch）。
#     ・結束碼：0 通過｜1 有未確認（擋）｜2 自己跑不起來（pre-push 只警告放行）。
#
# 為什麼獨立一支、不塞進 ticket-lint：lint 管「格式」（開發中不等案主回答），
# 這支管「能不能推」。要用**票現在的內容**判斷，而且只看這一批的票。
#
# 判準是「不是『已確認』就算沒確認」（fail-safe）：狀態空白、寫錯字、被改成別的詞、某一列沒有開頭的 | 一律擋。
# 沒有〈條件確認〉這一節的票印一行提示、不擋；但 created 在新票規的生效日（TICKET_RULES_SINCE，同 ticket-lint）之後、
# 而且字樣對得上（同 ticket-lint 的 COND_TRIGGER_RE）卻沒有這一節，當作漏了、擋下——
# 規則合流前就開好、之後只進 stage 沒被 lint 掃到的票，靠這一道補。
#
# 〈數字口徑〉（源專案 v5.19.0）也在這裡讀：每個數字一列、狀態不是「已確認」就擋，另外分開印（口徑沒有「符合／擋掉」筆數，
# 問案主時不出筆數勾選清單、改成一個數字問一題）。第一欄叫「數字」（〈條件確認〉的第一欄叫「條件」）。
# 沒有這一節的票不擋；但 created 在生效日之後、字樣對得上（同 ticket-lint 的 NUM_TRIGGER_RE，標題行也算）卻沒有這一節，
# 當作漏了、擋下。
#
# ⚠️ 它看的是票檔本身：票上寫「已確認」是不是真的問過案主，機器看不出來（同 ticket-lint 的聲明）。
# 推 prod 前（預設模式）票檔從 origin/stage 讀（不是目前這棵工作樹）：只挑部分票上 prod 的專案，
# 挑選分支上的票檔是舊版，補的〈條件確認〉列只會在 stage（源專案對抗審查時實測到）。UC_REF 可換成別的 ref；
# 設了 TICKETS_DIR 就改讀那個資料夾（測試用）。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# 新票規的生效日：環境變數 TICKET_RULES_SINCE 優先於 scripts/framework-config.sh（測試與一次性覆寫用）。
# 設定檔是無條件賦值，所以先記下環境裡有沒有給、source 完再放回去（同 scripts/ticket-lint.sh）。
_since_in_env="${TICKET_RULES_SINCE+set}"
_since_env_value="${TICKET_RULES_SINCE:-}"
[ -f "$ROOT/scripts/framework-config.sh" ] && . "$ROOT/scripts/framework-config.sh"
[ -n "$_since_in_env" ] && TICKET_RULES_SINCE="$_since_env_value"
TICKETS_DIR="${TICKETS_DIR:-}"
UC_REF="${UC_REF:-origin/stage}"
ZERO=0000000000000000000000000000000000000000
# 留空或沒設＝所有票都套用（連沒填 created 的票也算）。
RULES_SINCE="${TICKET_RULES_SINCE:-}"
if [ -n "$RULES_SINCE" ] && ! [[ "$RULES_SINCE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  # 日期是用字串比大小的：格式不對會讓每張票都排在它前面，「漏了這一節」那條靜靜全關。
  # 這裡不退出（退出＝這一關整個沒檢查），改成最嚴的那種算；ticket-lint 會因為同一個設定錯誤而紅。
  echo "[unconfirmed-conditions] ⚠️ TICKET_RULES_SINCE 格式錯誤（'${RULES_SINCE}'），應為 YYYY-MM-DD 或留空——這次先當成「全部套用」" >&2
  RULES_SINCE=""
fi
if [ -n "$RULES_SINCE" ]; then
  SINCE_NOTE="建立日在新票規生效日（${RULES_SINCE}）當天或之後"
else
  SINCE_NOTE="新票規沒有設生效日（所有票都套用）"
fi
# 同 scripts/ticket-lint.sh 的 COND_TRIGGER_RE（ticket-tools-test 會比對兩邊一致）
COND_TRIGGER_RE='出現條件|可見性|回填|篩選|才會出現|才會顯示|才顯示|才出現|擋下|擋掉'
# 同 scripts/ticket-lint.sh 的 NUM_TRIGGER_RE（ticket-tools-test 會比對兩邊一致）；專案要加自己的數字講法，兩支一起改
NUM_TRIGGER_RE='儀表板|統計卡|成功率|比例|比率|平均|總數|KPI'
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

MODE=ids
STAGE=0
case "${1:-}" in
  --stage-range)
    if [ "$#" -ne 3 ]; then echo "用法：scripts/unconfirmed-conditions.sh --stage-range <遠端現況 sha> <要推的 sha>" >&2; exit 2; fi
    MODE=range; STAGE=1 ;;
  --stage-ref)
    shift
    MODE=ref; STAGE=1 ;;
esac

if [ "$MODE" = ids ]; then
  if [ -z "$TICKETS_DIR" ]; then
    if ! git -C "$ROOT" fetch -q origin stage 2>/dev/null; then
      echo "[unconfirmed-conditions] ✗ git fetch origin stage 失敗——不能拿舊的 ${UC_REF} 當成「沒有未確認」；網路或憑證恢復後再跑" >&2
      exit 2
    fi
    if ! git -C "$ROOT" rev-parse -q --verify "${UC_REF}^{commit}" >/dev/null; then
      echo "[unconfirmed-conditions] ✗ 找不到 ${UC_REF}——不能當成「沒有未確認」；先 git fetch origin" >&2
      exit 2
    fi
  fi
  if [ "$#" -eq 0 ]; then
    echo "用法：scripts/unconfirmed-conditions.sh <票號> [<票號> …]" >&2
    exit 2
  fi
fi

shopt -s nullglob
blocked=0
missing=0

# check_one <票號> <票檔路徑>：判斷一張票，印結果，必要時把 blocked 設成 1
check_one() {
  local id="$1" f="$2" out nout kind a b c rowcount flagged
  out=$(awk -v since="$RULES_SINCE" -v trigre="$COND_TRIGGER_RE" -v stage="$STAGE" '
    function trim(x) { gsub(/^[ \t]+|[ \t]+$/, "", x); return x }
    NR == 1 && $0 == "---" { fm = 1; next }
    fm { if ($0 ~ /^created:/) { created = $2 }; if ($0 == "---") fm = 0; next }
    incomment { if ($0 ~ /-->/) incomment = 0; next }
    $0 ~ /^[ \t]*<!--/ { if ($0 !~ /-->/) incomment = 1; next }
    /^#+ / { sec = ($0 ~ /^#+[ \t]*條件確認/) ? "cond" : "other"; if (sec == "cond") seen = 1; else if ($0 ~ trigre) trig = 1; next }
    sec != "cond" { if ($0 ~ trigre) trig = 1; next }
    {
      l = trim($0)
      if (l ~ /^不適用/) { na = 1; next }
      if (l !~ /^\|/) { if (l ~ /\|/) bad = 1; next }
      n = split(l, c, "|"); ncell = n - 2
      if (!hdr) {
        if (trim(c[2]) ~ /^條件/) {
          hdr = 1
          for (j = 1; j <= ncell; j++) {
            h = trim(c[j + 1])
            if (index(h, "符合") == 1) col_ok = j
            else if (index(h, "擋掉") == 1) col_blk = j
            else if (index(h, "狀態") == 1) col_st = j
            else if (index(h, "回答日") == 1) col_date = j
          }
        }
        next
      }
      if (l ~ /^\|[ \t:|-]+\|?$/) next
      rows++
      st = col_st ? trim(c[col_st + 1]) : ""
      if (st != "已確認") {
        ok = col_ok ? trim(c[col_ok + 1]) : "?"; blk = col_blk ? trim(c[col_blk + 1]) : "?"
        dt = col_date ? trim(c[col_date + 1]) : ""
        desc = (st == "" ? "空白" : st)
        if (st == "待 prod 資料") {
          # 推 stage 時唯一的例外：「查不到：」開頭＋回答日（案主同意延後的那天）都有才放行；推 prod 前照樣算沒確認
          if (stage && (ok ~ /^查不到：/ || blk ~ /^查不到：/) && dt ~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$/) {
            printf "DEFER\t%s\t%s\n", trim(c[2]), dt
            next
          }
          desc = stage ? "待 prod 資料，但〈符合〉或〈擋掉〉不是「查不到：」開頭、或沒有 YYYY-MM-DD 的回答日" : "待 prod 資料——推 prod 前要重查 prod 筆數再問案主"
        }
        printf "ROW\t%s\t符合 %s／擋掉 %s\t（狀態：%s）\n", trim(c[2]), ok, blk, desc
      }
    }
    END {
      if (!seen) { if (trig && (since == "" || created >= since)) print "MISSING"; else print "NOSEC" }
      else if (bad) print "BROKEN"
      else if (hdr && rows > 0) { }
      else if (na) print "NA"
      else print "BROKEN"
    }
  ' "$f")
  rowcount=0
  while IFS=$'\t' read -r kind a b c; do
    [ -z "$kind" ] && continue
    case "$kind" in
      ROW)
        echo "[unconfirmed-conditions] ✗ ${id} 未確認：${a}　${b}　${c}"
        rowcount=$((rowcount + 1)); blocked=1 ;;
      DEFER)
        echo "[unconfirmed-conditions] ⏳ ${id} 待 prod 資料（案主 ${b} 同意等 prod 筆數再答，放行）：${a}——推 prod 前要重查筆數再問" ;;
      NOSEC) echo "[unconfirmed-conditions] ${id}：沒有〈條件確認〉這一節（舊票，或沒有自加條件）——不擋" ;;
      NA) echo "[unconfirmed-conditions] ${id}：〈條件確認〉寫不適用——不擋" ;;
      BROKEN)
        echo "[unconfirmed-conditions] ✗ ${id}：〈條件確認〉看不出表格、沒有任何一列、或有一列沒有開頭的 |——當作未確認，先補齊（make ticket-lint 會說哪裡壞）" >&2
        blocked=1 ;;
      MISSING)
        echo "[unconfirmed-conditions] ✗ ${id}：票裡有「出現條件／篩選／擋掉」這類字樣、${SINCE_NOTE}，卻沒有〈條件確認〉這一節——補表，或寫「不適用：<理由>」（寫法見 tickets/README.md〈條件確認〉）" >&2
        blocked=1 ;;
    esac
  done <<< "$out"
  flagged=0
  grep -qE '^(NOSEC|NA|BROKEN|MISSING|DEFER)' <<< "$out" && flagged=1
  [ "$rowcount" -gt 0 ] && flagged=1

  # ── 〈數字口徑〉：分開讀、分開印（不印符合／擋掉；沒有「待 prod 資料」例外）──
  nout=$(awk -v since="$RULES_SINCE" -v trigre="$NUM_TRIGGER_RE" '
    function trim(x) { gsub(/^[ \t]+|[ \t]+$/, "", x); return x }
    NR == 1 && $0 == "---" { fm = 1; next }
    fm { if ($0 ~ /^created:/) { created = $2 }; if ($0 == "---") fm = 0; next }
    incomment { if ($0 ~ /-->/) incomment = 0; next }
    $0 ~ /^[ \t]*<!--/ { if ($0 !~ /-->/) incomment = 1; next }
    /^#+ / { sec = ($0 ~ /^#+[ \t]*數字口徑/) ? "num" : "other"; if (sec == "num") seen = 1; else if ($0 ~ trigre) trig = 1; next }
    sec != "num" { if ($0 ~ trigre) trig = 1; next }
    {
      l = trim($0)
      if (l ~ /^不適用/) { na = 1; next }
      if (l !~ /^\|/) { if (l ~ /\|/) bad = 1; next }
      n = split(l, c, "|"); ncell = n - 2
      if (!hdr) {
        if (trim(c[2]) ~ /^數字/) {
          hdr = 1
          for (j = 1; j <= ncell; j++) { h = trim(c[j + 1]); if (index(h, "狀態") == 1) col_st = j }
        }
        next
      }
      if (l ~ /^\|[ \t:|-]+\|?$/) next
      rows++
      st = col_st ? trim(c[col_st + 1]) : ""
      if (st != "已確認") printf "NROW\t%s\t（狀態：%s）\n", trim(c[2]), (st == "" ? "空白" : st)
    }
    END {
      if (!seen) { if (trig && (since == "" || created >= since)) print "NMISSING" }
      else if (bad) print "NBROKEN"
      else if (hdr && rows > 0) { }
      else if (na) { }
      else print "NBROKEN"
    }
  ' "$f")
  while IFS=$'\t' read -r kind a b; do
    [ -z "$kind" ] && continue
    flagged=1
    case "$kind" in
      NROW)
        echo "[unconfirmed-conditions] ✗ ${id} 數字口徑未確認：${a}　${b}"
        blocked=1 ;;
      NBROKEN)
        echo "[unconfirmed-conditions] ✗ ${id}：〈數字口徑〉看不出表格、沒有任何一列、或有一列沒有開頭的 |——當作未確認，先補齊（make ticket-lint 會說哪裡壞）" >&2
        blocked=1 ;;
      NMISSING)
        echo "[unconfirmed-conditions] ✗ ${id}：票裡有「儀表板／成功率／比例／平均／總數」這類字樣、${SINCE_NOTE}，卻沒有〈數字口徑〉這一節——補表，或寫「不適用：<理由>」（寫法見 tickets/README.md〈數字口徑〉）" >&2
        blocked=1 ;;
    esac
  done <<< "$nout"

  if [ "$flagged" -eq 0 ]; then
    echo "[unconfirmed-conditions] ✓ ${id}：條件與數字口徑都已確認"
  fi
}

# stage_range <遠端現況 sha> <要推的 sha> [標籤]：查範圍內改到的票（stage 模式，用目前所在的 git repo）
stage_range() {
  local remote="$1" local_sha="$2" label="${3:-}" paths p tid st checked=0
  if ! git cat-file -e "${local_sha}^{commit}" 2>/dev/null; then
    echo "[unconfirmed-conditions] ✗ ${label:-$local_sha}：本機找不到這個 commit，沒有檢查——不能當成「沒有未確認」" >&2
    missing=1
    return
  fi
  if [ "$remote" != "$ZERO" ] && git cat-file -e "${remote}^{commit}" 2>/dev/null; then
    paths=$(git -c core.quotepath=false diff --name-only --diff-filter=d "$remote" "$local_sha" -- tickets/ 2>/dev/null) || {
      echo "[unconfirmed-conditions] ✗ ${label:-$local_sha}：算不出推送範圍，沒有檢查" >&2; missing=1; return; }
  else
    # 新分支（遠端 sha 全 0）或遠端 sha 本機不認得：無法判斷範圍，保守起見查要推的 commit 裡全部的票
    paths=$(git -c core.quotepath=false ls-tree -r --name-only "$local_sha" -- tickets/ 2>/dev/null) || {
      echo "[unconfirmed-conditions] ✗ ${label:-$local_sha}：讀不到票檔清單，沒有檢查" >&2; missing=1; return; }
  fi
  while IFS= read -r p; do
    case "$p" in
      tickets/README.md) continue ;;
      tickets/*/*) continue ;;
      tickets/*.md) ;;
      *) continue ;;
    esac
    if ! git show "${local_sha}:${p}" > "$tmp" 2>/dev/null; then
      echo "[unconfirmed-conditions] ✗ 讀不到 ${local_sha}:${p}——沒有檢查這張票" >&2
      missing=1
      continue
    fi
    st=$(awk 'NR == 1 && $0 == "---" { fm = 1; next } fm && /^status:/ { print $2; exit } fm && $0 == "---" { exit }' "$tmp")
    case "$st" in 開發中|完成) ;; *) continue ;; esac
    tid="$(basename "$p" .md)"
    # 作者前綴可以帶數字（例 AMY2-01-…，同一人第二條 session 的別名），所以前綴不能只收字母
    tid="$(printf '%s' "$tid" | sed -E 's/^([A-Za-z][A-Za-z0-9]*-[0-9][0-9.]*)-.*$/\1/')"
    check_one "$tid" "$tmp"
    checked=$((checked + 1))
  done <<< "$paths"
  if [ "$checked" -eq 0 ]; then
    echo "[unconfirmed-conditions] ${label:-這次推送}：範圍內沒有狀態是開發中／完成的票檔——通過"
  fi
}

case "$MODE" in
  range)
    stage_range "$2" "$3" ;;
  ref)
    if [ "$#" -eq 0 ]; then set -- HEAD; fi
    for ref in "$@"; do
      if ! sha="$(git rev-parse --verify "${ref}^{commit}" 2>/dev/null)"; then
        echo "[unconfirmed-conditions] ✗ ${ref}：找不到這個 ref，沒有檢查" >&2
        missing=1
        continue
      fi
      if ! base="$(git merge-base origin/stage "$sha" 2>/dev/null)"; then
        echo "[unconfirmed-conditions] ✗ ${ref}：算不出跟 origin/stage 的共同祖先（先 git fetch origin stage），沒有檢查" >&2
        missing=1
        continue
      fi
      echo "[unconfirmed-conditions] ── ${ref} ──"
      stage_range "$base" "$sha" "$ref"
    done ;;
  *)
    for id in "$@"; do
      # 票號後面一定接 -（AMY-5 不能撈到 AMY-54）
      if [ -n "$TICKETS_DIR" ]; then
        matches=("$TICKETS_DIR/${id}"-*.md)
      else
        matches=()
        while IFS= read -r line; do
          case "$line" in tickets/"${id}"-*.md) matches+=("$line") ;; esac
        done < <(git -C "$ROOT" -c core.quotepath=false ls-tree --name-only "$UC_REF" tickets/)
      fi
      if [ ${#matches[@]} -ne 1 ]; then
        echo "[unconfirmed-conditions] ✗ ${id}：在 ${UC_REF:-$TICKETS_DIR} 找到 ${#matches[@]} 個票檔（要剛好 1 個）——不要把「找不到」當成「沒有未確認」" >&2
        missing=1
        continue
      fi
      if [ -n "$TICKETS_DIR" ]; then
        f="${matches[0]}"
      else
        f="$tmp"
        if ! git -C "$ROOT" show "${UC_REF}:${matches[0]}" > "$tmp" 2>/dev/null; then
          echo "[unconfirmed-conditions] ✗ ${id}：讀不到 ${UC_REF}:${matches[0]}——不能當成「沒有未確認」" >&2
          missing=1
          continue
        fi
      fi
      check_one "$id" "$f"
    done ;;
esac

if [ "$missing" -ne 0 ]; then exit 2; fi
if [ "$blocked" -ne 0 ]; then
  if [ "$STAGE" -eq 1 ]; then
    echo "[unconfirmed-conditions] ⛔ 有未確認的條件或數字口徑——推 stage 前要先問完案主：問完把狀態改「已確認」並填回答日再推（怎麼問見 pm skill〈4b〉；表格怎麼填見 tickets/README.md〈條件確認〉〈數字口徑〉）。" >&2
    echo "[unconfirmed-conditions]    要看到 prod 筆數才答得出來的條件：把「為什麼現在答不了」列給案主，對方同意等 prod 筆數，才能標「待 prod 資料」＋回答日，〈符合〉或〈擋掉〉要寫「查不到：<原因>」（pm skill〈4b〉）。" >&2
    echo "[unconfirmed-conditions]    批次合流時是別人的票：請該票負責人補，不要替他改。" >&2
  else
    echo "[unconfirmed-conditions] 有未確認的條件或數字口徑——推 prod 前要先問案主（怎麼問見 pm skill〈4b〉；表格怎麼填見 tickets/README.md〈條件確認〉〈數字口徑〉）" >&2
  fi
  exit 1
fi
if [ "$MODE" = ids ]; then
  echo "[unconfirmed-conditions] 通過：這 $# 張票沒有未確認的條件"
else
  echo "[unconfirmed-conditions] 通過：這次推送範圍內的票沒有未確認的條件"
fi
exit 0
