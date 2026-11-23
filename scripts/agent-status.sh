#!/usr/bin/env bash
# Agent 入口簡報用的一次性狀態快照（設計目標 <1 秒；有設遠端時另加一次 git fetch 的時間）。
# 供 team-leader / pm / dev / framework 入口共用：一個指令拿到簡報所需的全部資訊。
# 專案差異（專案名、票號前綴、健康檢查 URL）在 scripts/framework-config.sh，不改本檔。
#
# 這支會先 cd 到「自己所屬的那一份 repo」再看現況——開場 hook 報的是 session 根目錄那一份。
# 在別的工作區做事，要到那個工作區裡重跑一次：換工作區＝換現況（源專案 v4.20.0）。
set -uo pipefail
cd "$(dirname "$0")/.."
. scripts/framework-config.sh

if [ -f .template-uninitialized ]; then
  echo "⚠️ 模板尚未初始化：請走 setup 入口（.agents/skills/setup/SKILL.md）完成專案設定"
fi

echo "== framework =="
fw_ver=$(grep -m1 -oE '框架版本：v[0-9]+\.[0-9]+\.[0-9]+' docs/FRAMEWORK.md 2>/dev/null | sed 's/框架版本：//')
echo "  ${PROJECT_NAME}｜框架 ${fw_ver:-未知}（規則與決策紀錄見 docs/FRAMEWORK.md）"

echo "== git =="
echo "branch: $(git branch --show-current 2>/dev/null || echo '?')"
echo "last:   $(git log --oneline -1 2>/dev/null || echo '?')"

# 落後多少（源專案 v4.17.0）。只讀本機 git、從不比對遠端的簡報，報的可能是早就過期的狀態，
# 而 agent 會拿它當現況用——源專案曾有一條 session 在落後幾十個 commit 的分支上討論規格，
# 整場把「已經做完並上線的功能」講成「還沒做」，還用「我查證過」的語氣講出來。
# 查得到不等於查的是現在的東西。fetch 失敗（離線）不擋簡報，只講「現況可能過期」。
#
# 一定要連整合分支 stage 一起比，不能只看自己的 upstream（源專案 v4.20.0）：
# feature 分支推過之後，upstream 就是它自己在遠端的那一條——兩邊永遠同步、落後數永遠是 0，
# 而真正會撞車的是「別人已經合進 stage 的東西」。源專案實測：一條 feature 分支落後整合分支
# 11 個 commit，只看 upstream 的版本回報「同步」，下游是一整晚的收拾（票號撞號、
# 兩邊各寫一份的程式差點無聲蓋掉功能）。
is_repo=0; git rev-parse --is-inside-work-tree >/dev/null 2>&1 && is_repo=1
cur_branch=$(git branch --show-current 2>/dev/null || echo "")
upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null) || upstream=""
has_origin=0; git remote get-url origin >/dev/null 2>&1 && has_origin=1
fetch_ok=1
if [ "$has_origin" = 1 ]; then git fetch --quiet origin 2>/dev/null || fetch_ok=0; fi
# 整合分支拿誰來比（要等 fetch 完才看得準）：有遠端就是 origin/stage；
# 還沒設遠端、或還沒推過 stage 的專案退回本機的 stage；兩個都沒有就不比（下面〈平行現場〉會講）。
stage_ref=""
if git rev-parse --verify --quiet refs/remotes/origin/stage >/dev/null 2>&1; then stage_ref="origin/stage"
elif git rev-parse --verify --quiet refs/heads/stage >/dev/null 2>&1; then stage_ref="stage"
fi
integration="$stage_ref"
# 自己就是本機的 stage、比的又是本機的 stage 時，不要跟自己比
[ "$cur_branch" = "stage" ] && [ "$stage_ref" = "stage" ] && integration=""

compared=""
report_behind() {  # $1=比對基準 $2=追上它的做法
  local base="$1" how="$2" behind
  [ -z "$base" ] && return 0
  git rev-parse --verify --quiet "$base" >/dev/null 2>&1 || return 0
  compared="${compared:+${compared} 及 }${base}"
  behind=$(git rev-list --count "HEAD..$base" 2>/dev/null || echo 0)
  if [ "${behind:-0}" -gt 0 ]; then
    # 這一行的開頭「⚠️ 落後 」是 team-leader skill 逐字引用的字樣，改之前先 grep 引用的地方
    echo "⚠️ 落後 $base $behind 個 commit——**先 ${how} 再判斷任何現況**"
    echo "    落後期間的變更（最新 5 筆）："
    git log --oneline "HEAD..$base" 2>/dev/null | head -5 | sed 's/^/      /'
    return 1
  fi
  return 0
}

if [ "$is_repo" = 0 ]; then
  echo "remote: （這裡還不是 git repo）"
elif [ "$has_origin" = 1 ] && [ "$fetch_ok" = 0 ]; then
  echo "remote: 取不到（離線），現況可能過期"
else
  [ "$has_origin" = 0 ] && echo "remote: 還沒設遠端（只有本機）"
  warned=0
  report_behind "$upstream" "git pull --rebase" || warned=1
  # upstream 與整合分支是同一條時不重複報
  if [ "$upstream" != "$integration" ]; then
    report_behind "$integration" "git merge ${integration}" || warned=1
  fi
  if [ "$warned" = 0 ]; then
    if [ -n "$compared" ] && [ "$has_origin" = 1 ]; then echo "remote: 與 ${compared} 同步"
    elif [ -n "$compared" ]; then echo "        與本機的 ${compared} 同步"
    elif [ "$has_origin" = 1 ]; then echo "remote: 沒有可以比的對象（這條分支沒有 upstream，也還沒有 stage 分支）"
    fi
  fi
fi
dirty_n=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
echo "dirty:  $dirty_n 個未提交檔案"
if [ "$dirty_n" -gt 0 ]; then
  git status --porcelain 2>/dev/null | head -5 | sed 's/^/  /'
  [ "$dirty_n" -gt 5 ] && echo "  … 還有 $((dirty_n - 5)) 個"
fi

# 平行現場：這台機器上還有誰在做事（源專案 v4.14.0）。
# 開場簡報原本只看得到「當前工作區」，對平行 session 完全沉默——而歷次撞車的第一因
# 就是雙方不知道對方存在。
echo "== 平行現場 =="
main_root="$(git worktree list --porcelain 2>/dev/null | head -1 | sed 's/^worktree //')"
here="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$main_root" ]; then
  echo "  （這裡還不是 git repo，沒有工作區可列）"
else
  if [ "$here" = "$main_root" ]; then
    echo "  你在：主目錄（合流用；開發請開工作區 → scripts/new-worktree.sh <票號>）"
  else
    echo "  你在：工作區 ${here#$main_root/} ✅"
  fi
  # 主目錄固定停在整合分支（源專案 v4.19.0）：主目錄只做合流，停在別條分支＝有人在主目錄開發、
  # 或合流做到一半。同一份檔案被兩條 session 寫，會互相掃掉未提交的工作。
  main_br="$(git -C "$main_root" branch --show-current 2>/dev/null || echo "")"
  if [ "$main_br" != "stage" ]; then
    echo "  ⚠️ 主目錄目前在 ${main_br:-(detached)}，不是 stage——主目錄只做合流，開發請開工作區"
  fi
  if [ -z "$stage_ref" ]; then
    echo "  ⚠️ 還沒有 stage 分支（遠端、本機都沒有）：分不出哪些工作區已經合流——整合分支固定叫 stage"
  fi
  # 只逐條列「還有事要處理的」（有未提交 或 有 commit 沒進 stage）；已合流又乾淨的收斂成一行。
  # 十幾個工作區全列出來是一面牆，看的人會直接略過——簡報要給訊號，不是給清單（源專案 v4.19.0）。
  # 每條都要帶「票號」與「使用者可以做什麼、放行什麼」（源專案 v4.22.0）——目標是多 session 平行也能保持乾淨。
  # 票號取法：先從分支名撈（feature/TK-63-64-… → TK-63/64），撈不到再從那個工作區動過的票檔名撈
  # （自動命名的分支，票號只存在於它還沒提交的 tickets/*.md）。
  # 票號前綴從 tickets/ 的檔名推（源專案 v4.78.2）：前綴是每個 clone 自己設的，寫死清單會漏掉新作者。
  # 只認真的有票的前綴，分支名裡的 UTF-8 之類不會被當成票號。
  tkt_re="($(ls tickets 2>/dev/null | sed -nE 's/^([A-Z][A-Z0-9]{1,7})-[0-9]+-.*/\1/p' | sort -u | paste -sd'|' -))-[0-9]+"
  if [ "$tkt_re" = "()-[0-9]+" ]; then
    # 一張票都還沒有：退回設定檔的前綴，加上這個 clone 自己的作者前綴（git config ticket.prefix，有設才加）
    tkt_pfx="$(printf '%s\n%s\n' "${TICKET_PREFIX:-}" "$(git config ticket.prefix 2>/dev/null || true)" \
      | grep -E '^[A-Z][A-Z0-9]{1,7}$' | sort -u | paste -sd'|' -)"
    tkt_re="(${tkt_pfx:-TK})-[0-9]+"
  fi
  # 「還沒進 stage 的提交裡，有別張票的」（源專案 v5.16.0）：B 票疊在 A 票的分支上開發時，領先的 N 個提交裡有 A 的。
  # 一次呼叫處理全部工作區（不加 --cherry-pick：加了會慢一個數量級，簡報不值得）。
  # 輸入每列「工作區路徑 TAB 分支 TAB 分支名上的票號（TK-83/86）」；分支名撈不到票號的不送。
  # 輸出只有「有別張票」的工作區：「工作區路徑 TAB 別張票摘要」。python3 缺或失敗就當沒有，不擋簡報。
  brief_out=""
  if [ -n "$stage_ref" ] && command -v python3 >/dev/null 2>&1; then
    brief_out=$(git worktree list --porcelain 2>/dev/null | awk -v tre="$tkt_re" '
      /^worktree / { path=substr($0,10) }
      /^branch /   { br=substr($0,8); sub("refs/heads/","",br)
        if (match(br, tre "(-[0-9]+)*")) {
          n=split(substr(br, RSTART, RLENGTH), a, "-"); t=a[1] "-" a[2]
          for (i=3; i<=n; i++) t=t "/" a[i]
          print path "\t" br "\t" t } }' \
      | STAGE_BASE="$stage_ref" python3 scripts/branch_tickets.py --brief 2>/dev/null) || brief_out=""
  fi
  wt_n=0; wt_stale=0; wt_stage_holder=""; wt_todo=0; stale_names=""; now_s=$(date +%s)
  while IFS=$'\t' read -r wpath wbr; do
    [ -z "$wpath" ] && continue
    wt_n=$((wt_n+1))
    wdirty=$(git -C "$wpath" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    if [ "$wpath" = "$main_root" ]; then wlabel="(主目錄)"
    else
      wlabel="${wpath#$main_root/.claude/worktrees/}"
      [ "$wlabel" = "$wpath" ] && wlabel="↗ $(basename "$wpath")"
    fi
    case "$wbr" in stage|prod|main|master) [ "$wpath" != "$main_root" ] && wt_stage_holder="${wlabel}（${wbr}）";; esac
    # refs/heads：同名 tag 不能頂替分支（git 會先把名字解析成 tag）
    merged=0
    [ -n "$stage_ref" ] && git merge-base --is-ancestor "refs/heads/$wbr" "$stage_ref" 2>/dev/null && merged=1
    wshort=$(printf '%s' "$wbr" | grep -oE "$tkt_re" | head -1)
    [ -z "$wshort" ] && wshort="${wlabel#↗ }"
    # 可收＝已合流、無未提交、不是主目錄、不是你自己——**但剛動過的不算**（源專案 v4.22.0）。
    # 源專案實例：一個工作區已合流又乾淨，舊版直接列進「可以收」，但那條 session 兩分鐘前才 commit、
    # 人還在裡面——收掉它，那條 session 的所在目錄會當場消失。
    # 「已合流又乾淨」是 git 的狀態，不等於「沒人在用」；用最後一次 commit 的時間當活躍度的代理。
    if [ "$merged" = "1" ] && [ "$wdirty" = "0" ] && [ "$wpath" != "$main_root" ] && [ "$wpath" != "$here" ]; then
      wlast=$(git -C "$wpath" log -1 --format=%ct 2>/dev/null || echo "")
      if [ -n "$wlast" ] && [ $(( now_s - wlast )) -lt 3600 ]; then
        printf "    %-14s %s・剛動過（%s 分鐘前 commit）\n" "$wshort" "$wbr" "$(( ( now_s - wlast ) / 60 ))"
        echo "        ⏳ 已合流又乾淨，但可能還有 session 在裡面 → 確認沒人用再收，別直接 --merged --yes"
      else
        wt_stale=$((wt_stale+1)); stale_names="$stale_names $wshort"
      fi
      continue
    fi
    # 票號：分支名 → 該工作區動過的票檔名 → 都撈不到就用工作區名當識別
    # 一條分支可能掛兩張票（feature/TK-63-64-… ＝ TK-63 與 TK-64），所以連號也要抓出來
    tkt=$(printf '%s' "$wbr" | grep -oE "${tkt_re}(-[0-9]+)*" | head -1 \
      | awk -F- '{p=$1"-"$2; for(i=3;i<=NF;i++) p=p"/"$i; print p}')
    [ -z "$tkt" ] && tkt=$(git -C "$wpath" status --porcelain -- tickets/ 2>/dev/null \
      | grep -oE "$tkt_re" | sort -u | paste -sd/ - 2>/dev/null)
    [ -n "$tkt" ] && idlabel="$tkt" || idlabel="$wlabel"
    # 一次 rev-list 同時拿到落後／領先，省一半行程
    behind=""; ahead=0; wbehind=""
    if [ -n "$stage_ref" ]; then
      read -r behind ahead <<<"$(git -C "$wpath" rev-list --left-right --count "$stage_ref...HEAD" 2>/dev/null)"
      wbehind="・落後 ${behind:-?}"
    fi
    if [ "$wpath" = "$here" ]; then
      printf "  → %-14s %s（你在這）・%s 未提交%s\n" "$idlabel" "$wbr" "$wdirty" "$wbehind"
    else
      printf "    %-14s %s・%s 未提交%s\n" "$idlabel" "$wbr" "$wdirty" "$wbehind"
    fi
    # 待辦與可放行的動作：說「你能做什麼」，不只是報數字
    if [ "${ahead:-0}" -gt 0 ] 2>/dev/null && [ "$wbr" = "stage" ]; then
      # 整合分支自己領先遠端＝合好了還沒推。不是「要我合」——推 stage 是對外動作
      wt_todo=$((wt_todo+1))
      echo "        ⚠️ $ahead 個 commit 還沒推上 ${stage_ref}（推 stage 是對外動作，先確認再推）"
    elif [ "${ahead:-0}" -gt 0 ] 2>/dev/null; then
      wt_todo=$((wt_todo+1))
      wother=""
      while IFS=$'\t' read -r bp bo; do [ "$bp" = "$wpath" ] && wother="$bo"; done <<<"$brief_out"
      if [ -n "$wother" ]; then
        # 不寫「它先合」：那張可能就是同一條線做的，或早就上 stage 了——先確認，不是下指令
        echo "        ⚠️ $ahead 個 commit 還沒進 stage，含別張票的提交（${wother}）→ 合之前先確認那張是同一條線、已上 stage，還是要一起併"
      else
        echo "        ⚠️ $ahead 個 commit 還沒進 stage → 要我合就說「合 ${idlabel}」；還沒做完就留著"
      fi
    fi
    if [ "$wdirty" -gt 0 ] 2>/dev/null && [ "$wpath" != "$here" ]; then
      wt_todo=$((wt_todo+1))
      echo "        ⚠️ 有未提交的東西 → 要我接手就說「處理 ${idlabel}」；確定不要就說「丟掉」"
    fi
  done < <(git worktree list --porcelain 2>/dev/null | awk '
    /^worktree /  { path=substr($0,10) }
    /^branch /    { br=substr($0,8); sub("refs/heads/","",br); print path "\t" br }
    /^detached$/  { print path "\t(detached)" }
  ')
  [ "$wt_stale" -gt 0 ] && echo "  ✅ 可以直接收（已合流又乾淨）：$(echo $stale_names) → bash scripts/worktree-clean.sh --merged（先預覽，加 --yes 才真的收）"
  [ "$wt_stale" = "0" ] && [ "$wt_todo" = "0" ] && [ "$wt_n" -gt 1 ] && echo "  ✅ 沒有待收的工作區，現場是乾淨的"
  [ -n "$wt_stage_holder" ] && echo "  ⚠️ $wt_stage_holder 佔著保護分支，主目錄無法 checkout 它（請該 session 換分支或收掉）"
  [ "$wt_n" -le 1 ] && echo "  （目前只有主目錄，沒有其他工作區）"
fi

echo "== tickets =="
# 一次 awk 讀完全部票檔（源專案 v4.19.0、v4.22.1）：迴圈裡對每張票各開幾個行程，票一多簡報就慢到沒人等。
# 同時修掉一個 bug：status 值後面帶著範本註解（`status: 待開發        # 待開發 | 開發中 | 完成 | 作廢`）時，
# 整行比對吃不到，工作佇列會靜靜漏掉大半的票——比對前先把註解去掉。
if ls tickets/*-*.md >/dev/null 2>&1; then
  awk '
    function cut(s){ sub(/ *#.*/,"",s); sub(/ *$/,"",s); return s }
    FNR==1 { order[++n]=FILENAME }
    { f=FILENAME
      if (match($0,/^id: */)     && !(f in ID)) ID[f]=cut(substr($0,RLENGTH+1))
      if (match($0,/^status: */) && !(f in ST)) ST[f]=cut(substr($0,RLENGTH+1))
      if (match($0,/^title: */)  && !(f in TI)) TI[f]=substr($0,RLENGTH+1)
      if (match($0,/^owner: */)  && !(f in OW)) OW[f]=cut(substr($0,RLENGTH+1))
    }
    END {
      split("待開發 開發中 完成 作廢", st4, " ")
      for(i=1;i<=n;i++){ cnt[ST[order[i]]]++ }
      for(k=1;k<=4;k++) printf "  %s: %d\n", st4[k], cnt[st4[k]]+0
      # 工作佇列：開發中優先（領票制要看得到誰佔著），其次待開發；各自設上限避免淹沒簡報
      doing=0; todo=0
      for(i=1;i<=n;i++){ f=order[i]; if(ST[f]!="開發中") continue; doing++
        if(doing<=8) printf "  → %s [開發中]%s %s\n", ID[f], (OW[f]!=""?"["OW[f]"]":"[未領票]"), TI[f] }
      for(i=1;i<=n;i++){ f=order[i]; if(ST[f]!="待開發") continue; todo++
        if(todo<=4) printf "  → %s [待開發] %s\n", ID[f], TI[f] }
      rest=(doing>8?doing-8:0)+(todo>4?todo-4:0)
      if(rest>0) printf "  … 還有 %d 張未列出（開發中 %d／待開發 %d）\n", rest, doing, todo
    }' tickets/*-*.md
else
  echo "  (尚無票)"
fi

echo "== spec =="
# 只掃「## 2. 功能狀態總覽」到下一個「## 」之間的表格列，避開圖例表與變更歷史的符號
awk '
  /^## 2\. 功能狀態總覽/ {inseg=1; next}
  inseg && /^## / {inseg=0}
  inseg {print}
' docs/SPEC.md 2>/dev/null \
  | grep -o "✅ 已完成\|🚧 進行中\|⏳ 未開始" | sort | uniq -c | sed 's/^/  /'
# ⏳ 未開始項目的標題（總覽表首欄），讓簡報零額外讀檔就能點出待啟動的事
awk -F'|' '
  /^## 2\. 功能狀態總覽/ {inseg=1; next}
  inseg && /^## / {inseg=0}
  inseg && /⏳ 未開始/ {gsub(/^ *| *$/,"",$2); print "  ⏳ " $2}
' docs/SPEC.md 2>/dev/null
# 最近一筆變更歷史（changelog 第一列資料 = 最新）
latest=$(awk -F'|' '
  /^## 5\. 變更歷史/ {inseg=1; next}
  inseg && /^\| *[0-9]{4}-/ {gsub(/^ *| *$/,"",$2); gsub(/^ *| *$/,"",$3); print $2 "：" $3; exit}
' docs/SPEC.md 2>/dev/null)
[ -n "$latest" ] && echo "  最近變更 $latest"

echo "== lint =="
# 這條管線把 lint 的結束碼吃掉了（簡報不該因為票有錯就中斷），但「吃掉」不等於「可以不講」——
# 紅燈跟一堆 warn 混在一起長得一樣，而全綠時才會印的「OK（N 張票通過）」沒出現，很容易被略過。
# 所以用 PIPESTATUS 把結束碼撈回來，不是 0 就補一行醒目的（仍然不中斷簡報）。
./scripts/ticket-lint.sh 2>&1 | sed 's/^\[ticket-lint\] /  /'
if [ "${PIPESTATUS[0]}" -ne 0 ]; then
  echo "  ⛔ ticket-lint 紅燈：上面的錯誤會讓 make check 擋下來，先修再開工"
fi

echo "== 閘門 =="
if [ -f cache/hotfix-override ]; then
  # 「⚠️ hotfix-override 存在」是 team-leader skill 逐字引用的字樣，改之前先 grep 引用的地方
  echo "  ⚠️ hotfix-override 存在（cache/hotfix-override）：無票不開發閘門目前被放行！救火完成請刪除此檔並補票"
else
  echo "  票務閘門正常（無 hotfix-override）"
fi

echo "== health =="
if [ -n "$HEALTH_URL" ]; then
  curl -m 2 -fsS "$HEALTH_URL" 2>/dev/null || echo "  dev 環境未啟動或未就緒"
else
  echo "  （未設定健康檢查；要啟用請在 scripts/framework-config.sh 填 HEALTH_URL）"
fi
