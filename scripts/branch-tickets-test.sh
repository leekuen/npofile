#!/usr/bin/env bash
# branch_tickets.py 的測試（源專案 v5.16.0，相依的票平行開發）：這條分支會帶上 stage 的提交，分屬哪幾張票。
# 沙盒 git repo，不碰真的 origin。最後做變異確認：把規則弄壞，對應的案例一定要紅（測試自己要有牙）。
# 來歷：B 票疊在 A 票的分支上開發時，簡報只看「ahead N」，看不出 N 個提交裡有 A 的；
# 合之前要看得到，才知道 A 是同一條線、已上 stage，還是要一起併。
set -u
cd "$(dirname "$0")/.."
SRC="$PWD/scripts/branch_tickets.py"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
# 沙盒不吃外面的 git 環境：從 git hook 裡跑時 GIT_DIR 會指向真的 repo；使用者自己的 git 設定也不帶進來
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
pass=0; fail=0; mut_fail=0; MUT=""
ok() { [ -n "$MUT" ] || pass=$((pass+1)); }
ng() { if [ -n "$MUT" ]; then mut_fail=$((mut_fail+1)); else fail=$((fail+1)); echo "  ✗ $1"; fi; }

R="$TMP/repo"; mkdir -p "$R/scripts" "$R/tickets"; cp "$SRC" "$R/scripts/"
g() { git -C "$R" -c user.name=t -c user.email=t@t -c commit.gpgsign=false "$@" >/dev/null; }
commit() {  # $1＝訊息 $2＝檔名（預設 code.txt）
  echo "$1" >> "$R/${2:-code.txt}"; g add "${2:-code.txt}"; g commit -q -m "$1"
}
g init -q -b stage
for t in TK-540 TK-541 TK-542 TK-543 TK-544 TK-545 TK-546 TK-483 TK-484 TK-486 \
         TK-487 TK-488 TK-391 TK-550 AMY-22 AMY-229 AMY-232 AMY-233 AMY2-04 TK-0145 AMY-09 AMY-10; do
  printf -- "---\nid: %s\nowner: claude-cc\n---\n" "$t" > "$R/tickets/$t-票.md"
done
g add tickets scripts; g commit -q -m "init"

# A（TK-540）有程式；B（TK-541）從 A 開
g checkout -q -b feature/TK-540 stage; commit "feat(api): TK-540 資料表"
g checkout -q -b feature/TK-541 feature/TK-540; commit "feat: TK-541 畫面"
# B 從 stage 開
g checkout -q -b feature/TK-542 stage; commit "feat: TK-542 單獨一條"
# 搬票提交只動 tickets/，不算程式
g checkout -q -b feature/TK-543 stage
echo more >> "$R/tickets/TK-550-票.md"; g add tickets; g commit -q -m "tickets: TK-550 移到別的分支"
commit "feat: TK-543 本體"
# 提到自己的票就算自己的（tickets(AMY-232,AMY-233) 在 AMY-233 上、開 TK-391）
g checkout -q -b feature/AMY-233 stage; commit "tickets(AMY-232,AMY-233): 補票與程式"
g checkout -q -b feature/TK-391 stage; commit "feat: 開 TK-391 並參考 TK-540 的做法"
# 內容已直接進 stage 的提交不算（cherry）
g checkout -q -b feature/TK-544 stage; commit "feat: TK-544 先做"
g checkout -q -b feature/TK-545 feature/TK-544; commit "feat: TK-545 疊上去"
# stage 先往前一步再挑：不然挑出來的提交會和原本的同雜湊（同父、同秒），就不是在測 cherry 了
g checkout -q stage; commit "chore: stage 先往前一步" pre.txt; g cherry-pick feature/TK-544
# merge commit 不算
g checkout -q -b feature/TK-546 stage; commit "feat: TK-546 本體"
g checkout -q stage; commit "chore: 無關的 stage 新提交" other.txt
g checkout -q feature/TK-546; g merge -q --no-ff stage -m "Merge TK-541 into feature/TK-546"
# 模板內補的：合併提交的訊息「只」寫了別張票（上面那一筆同時寫了自己的票，就算被算進來也會歸給自己，守不住「合併提交不算」）
g checkout -q -b feature/TK-551 stage; commit "feat: TK-551 本體"
g checkout -q stage; commit "chore: 又一筆無關的 stage 提交" other2.txt
g checkout -q feature/TK-551; g merge -q --no-ff stage -m "Merge TK-541 的修正"
# 字界：AMY-22 與 AMY-229；XTK-9 不是票號（前綴前面還黏著字母）
g checkout -q -b feature/TK-548 stage; commit "chore: XTK-9 不是票"
g checkout -q -b feature/AMY-229 stage; commit "feat: AMY-229 本體"
# 範圍分支 TK-483-486：中間的 484 也是自己的
g checkout -q -b feature/TK-483-486 stage
commit "feat: TK-483 第一張"; commit "feat: TK-484 中間那張"; commit "feat: TK-486 最後一張"
# 同一條線：TK-488 寫在 feature/TK-487 上，票檔 owner 是 claude-cc-TK-487
g checkout -q -b feature/TK-487 stage; commit "feat: TK-487 本體"; commit "feat: TK-488 同一條線"
# 沒寫票號的提交：認不出是誰的，只列不算別張票
g checkout -q -b feature/TK-547 stage; commit "chore: 沒寫票號的小改"
# 票號有前導零（AMY2-04、TK-0145）：分支名上的號碼不能被吃掉前導零，不然自己的提交會被當成別張票
g checkout -q -b feature/AMY2-04 stage; commit "feat: AMY2-04 自己的程式"
g checkout -q -b feature/TK-0145 stage; commit "feat: TK-0145 自己的程式"
g checkout -q -b feature/AMY-09-10 stage; commit "feat: AMY-09 第一張"; commit "feat: AMY-10 第二張"
# 框架變更沒有票：提交訊息寫的是工作區名稱（FW-5.1，號碼帶小數點），疊在它上面開發時要看得到
g checkout -q -b feature/TK-549 stage; commit "FW-5.1: 補一條框架規則"; commit "feat: TK-549 本體"
g checkout -q stage

mkdir -p "$TMP/trees/TK-487/tickets" "$TMP/trees/other/tickets"
printf -- "---\nid: TK-488\nowner: claude-cc-TK-487\n---\n" > "$TMP/trees/TK-487/tickets/TK-488-票.md"
printf -- "---\nid: TK-488\nowner: claude-cc\n---\n" > "$TMP/trees/other/tickets/TK-488-票.md"

cli() { (cd "$R" && STAGE_BASE=stage python3 scripts/branch_tickets.py "$@" 2>&1); }
cli_nobase() { (cd "$R" && unset STAGE_BASE && python3 scripts/branch_tickets.py "$@" 2>&1); }   # 不指定比誰，讓它自己找
brief() { printf '%b' "$1" | (cd "$R" && STAGE_BASE=stage python3 scripts/branch_tickets.py --brief 2>&1); }

cases() {
  local out rc
  # 1. B 從 A 開 → 列出 A，標成別張票、結束碼 1；B 自己那行不標
  out=$(cli feature/TK-541 TK-541); rc=$?
  [ $rc -eq 1 ] && ok || ng "1 B 疊在 A 上應 exit 1，得 ${rc}：$out"
  grep -q "TK-540：1 個  ← 別張票" <<<"$out" && ok || ng "1 應列出 TK-540 並標別張票：$out"
  grep -q "TK-541：1 個$" <<<"$out" && ok || ng "1 TK-541 是自己的，不該標別張票：$out"
  # 2. B 從 stage 開 → 沒有別張
  out=$(cli feature/TK-542 TK-542); rc=$?
  [ $rc -eq 0 ] && ok || ng "2 從 stage 開應 exit 0，得 ${rc}：$out"
  grep -q "別張票" <<<"$out" && ng "2 不該有別張票：$out" || ok
  # 3. 搬票提交（只動 tickets/）不算
  out=$(cli feature/TK-543 TK-543); rc=$?
  [ $rc -eq 0 ] && ok || ng "3 搬票提交不該算別張票，得 ${rc}：$out"
  grep -q "TK-550" <<<"$out" && ng "3 TK-550 的搬票提交不該出現：$out" || ok
  # 4. 提到自己的票就算自己的
  out=$(cli feature/AMY-233 AMY-233); rc=$?
  [ $rc -eq 0 ] && ok || ng "4 tickets(AMY-232,AMY-233) 在 AMY-233 上應 exit 0，得 ${rc}：$out"
  out=$(cli feature/TK-391 TK-391); rc=$?
  [ $rc -eq 0 ] && ok || ng "4 「開 TK-391 並參考 TK-540」在 TK-391 上應 exit 0，得 ${rc}：$out"
  # 5. 內容已直接進 stage 的提交不算（cherry）
  out=$(cli feature/TK-545 TK-545); rc=$?
  [ $rc -eq 0 ] && ok || ng "5 TK-544 的內容已在 stage，不該算別張票，得 ${rc}：$out"
  # 6. merge commit 不算
  out=$(cli feature/TK-546 TK-546); rc=$?
  [ $rc -eq 0 ] && ok || ng "6 merge commit 的訊息不該算別張票，得 ${rc}：$out"
  # 6b.（模板內補的）合併提交的訊息只寫了別張票，也不算
  out=$(cli feature/TK-551 TK-551); rc=$?
  [ $rc -eq 0 ] && ok || ng "6b 合併提交只寫了別張票也不該算，得 ${rc}：$out"
  grep -q "TK-541" <<<"$out" && ng "6b 合併提交裡的 TK-541 不該出現：$out" || ok
  # 7. 字界：AMY-22 不是 AMY-229
  out=$(cli feature/AMY-229 AMY-22); rc=$?
  [ $rc -eq 1 ] && ok || ng "7 自己是 AMY-22 時，AMY-229 是別張票，得 ${rc}：$out"
  out=$(cli feature/AMY-229 AMY-229); rc=$?
  [ $rc -eq 0 ] && ok || ng "7 自己是 AMY-229 應 exit 0，得 ${rc}：$out"
  out=$(cli feature/TK-548 TK-548); rc=$?
  [ $rc -eq 0 ] && ok || ng "7 XTK-9 前綴前面黏著字母，不是票號，得 ${rc}：$out"
  # 8. 沒給自己的票號 → 不判別張，印警告
  out=$(cli feature/TK-541); rc=$?
  [ $rc -eq 0 ] && ok || ng "8 沒給票號不判別張，應 exit 0，得 ${rc}：$out"
  grep -q "沒給自己的票號" <<<"$out" && ok || ng "8 應提醒沒給票號：$out"

  # 14. 沒寫票號的提交只列不算別張票
  out=$(cli feature/TK-547 TK-547); rc=$?
  [ $rc -eq 0 ] && ok || ng "14 沒寫票號不該算別張票，得 ${rc}：$out"
  grep -q "沒寫票號）：1 個" <<<"$out" && ok || ng "14 應列出沒寫票號 1 個：$out"
  # 16. 沒指定比誰、專案也還沒設遠端 → 退回本機的 stage（不是拿不存在的 origin/stage 去比、整支失敗）
  out=$(cli_nobase feature/TK-541 TK-541); rc=$?
  grep -qF "feature/TK-541 比 stage 多 2 個 commit" <<<"$out" && ok || ng "16 沒有遠端時應該跟本機的 stage 比：$out"
  [ $rc -eq 1 ] && grep -qF "TK-540：1 個  ← 別張票" <<<"$out" && ok || ng "16 跟本機的 stage 比也要列出 TK-540（得 ${rc}）：$out"
  # 17. 框架變更的提交（FW-5.1）認得出來、算別張票；小數點不能被截掉變成 FW-5
  out=$(cli feature/TK-549 TK-549); rc=$?
  [ $rc -eq 1 ] && ok || ng "17 疊在框架變更上應 exit 1，得 ${rc}：$out"
  grep -qF "FW-5.1：1 個  ← 別張票" <<<"$out" && ok || ng "17 應列出 FW-5.1 並標別張票：$out"

  # 9. --brief：B 疊在 A 上 → 印出「樹路徑 TAB 別張票摘要」
  out=$(brief "/x/b\tfeature/TK-541\tTK-541\n")
  [ "$out" = "$(printf '/x/b\tTK-540 ×1')" ] && ok || ng "9 brief 應印出 TK-540 ×1：[$out]"
  # 10. --brief：從 stage 開的不印；分支名沒票號（label 空）不判別張
  out=$(brief "/x/c\tfeature/TK-542\tTK-542\n/x/d\tclaude/foo\t\n")
  [ -z "$out" ] && ok || ng "10 沒有別張票、或分支名沒票號時不該印：[$out]"
  # 11. --brief：範圍分支 TK-483-486，中間的 484 是自己的
  out=$(brief "/x/e\tfeature/TK-483-486\tTK-483/486\n")
  [ -z "$out" ] && ok || ng "11 範圍分支中間的票是自己的，不該印：[$out]"
  # 12. --brief：同一條線（別張票的 owner 是 claude-cc-<樹名>）算自己；owner 只寫 claude-cc 就列出來
  out=$(brief "$TMP/trees/TK-487\tfeature/TK-487\tTK-487\n")
  [ -z "$out" ] && ok || ng "12 owner 是 claude-cc-TK-487 的 TK-488 是同一條線，不該印：[$out]"
  out=$(brief "$TMP/trees/other\tfeature/TK-487\tTK-487\n")
  [ "$out" = "$(printf '%s\tTK-488 ×1' "$TMP/trees/other")" ] && ok || ng "12 owner 只寫 claude-cc 時 TK-488 要列出來：[$out]"
  # 15. --brief：前導零（AMY2-04、TK-0145、範圍 AMY-09/10）不能被吃掉
  out=$(brief "/x/g\tfeature/AMY2-04\tAMY2-04\n/x/h\tfeature/TK-0145\tTK-0145\n/x/i\tfeature/AMY-09-10\tAMY-09/10\n")
  [ -z "$out" ] && ok || ng "15 有前導零的票號是自己的，不該印：[$out]"
  # 13. --brief：搬票提交不算
  out=$(brief "/x/f\tfeature/TK-543\tTK-543\n")
  [ -z "$out" ] && ok || ng "13 brief 也要排除 tickets/：[$out]"
}

cases

# 變異確認：把規則弄壞，對應案例一定要紅
mutate() {  # $1＝名稱 $2＝原文 $3＝改成
  cp "$SRC" "$R/scripts/branch_tickets.py"
  python3 - "$R/scripts/branch_tickets.py" "$2" "$3" <<'PY' || { ng "變異「$1」：原文找不到，測試要跟著改"; return; }
import sys
p, old, new = sys.argv[1:]
s = open(p, encoding="utf-8").read()
if old not in s:
    sys.exit(1)
open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
PY
  MUT=1; mut_fail=0; cases; local n=$mut_fail; MUT=""
  [ "$n" -gt 0 ] && ok || ng "變異「$1」沒讓任何案例變紅——測試沒牙"
}
mutate "不排除 tickets/" 'args += ["--", ".", ":!tickets"]' 'pass'
mutate "不做 cherry-pick" 'args += ["--cherry-pick"]' 'pass'
mutate "不認 own" 'hit = [t for t in ids if t in own]' 'hit = []'
mutate "不展開範圍" 'nums = list(range(nums[0], nums[1] + 1))' 'pass'
mutate "前導零被吃掉" 'width = len(first)' 'width = 0'
mutate "不看 owner" 'return owner.startswith("claude-cc-") and' 'return False and'
mutate "字界拿掉" 'rf"\b((?:{alt})-\d+(?:\.\d+)*)\b"' 'rf"((?:{alt})-\d+(?:\.\d+)*)"'
mutate "把沒寫票號算成別張" 'if t != NO_TICKET and t not in own' 'if t not in own'
mutate "不退回本機的 stage" 'return name' 'return "origin/stage"'
mutate "小數點被截掉" '-\d+(?:\.\d+)*)' '-\d+)'
mutate "不認框架變更" ' | {"FW"}' ''
mutate "合併提交也算" '"--no-merges", ' ''   # 模板內補的

# 簡報（agent-status.sh）接線：有別張票時改寫那一行、沒有就維持原句（沙盒 repo 帶自己的 origin）
S2="$TMP/status"; mkdir -p "$S2/scripts" "$S2/tickets" "$S2/docs"
cp "$PWD/scripts/agent-status.sh" "$PWD/scripts/framework-config.sh" "$SRC" "$S2/scripts/"
echo 'HEALTH_URL=""' >> "$S2/scripts/framework-config.sh"   # 測試不連專案設定的健康檢查網址
g2() { git -C "$S2" -c user.name=t -c user.email=t@t -c commit.gpgsign=false "$@" >/dev/null; }
git init -q --bare "$TMP/origin.git"
g2 init -q -b stage; g2 remote add origin "$TMP/origin.git"
for t in TK-540 TK-541; do printf -- "---\nid: %s\nowner: claude-cc\n---\n" "$t" > "$S2/tickets/$t-票.md"; done
echo "框架版本：v0.0.0" > "$S2/docs/FRAMEWORK.md"
g2 add scripts tickets docs; g2 commit -q -m init; g2 push -q origin stage; g2 fetch -q origin
g2 checkout -q -b feature/TK-540; echo a >> "$S2/code.txt"; g2 add code.txt; g2 commit -q -m "feat(api): TK-540 資料表"
g2 checkout -q -b feature/TK-541; echo b >> "$S2/code.txt"; g2 add code.txt; g2 commit -q -m "feat: TK-541 畫面"
status_out() { (cd "$S2" && bash scripts/agent-status.sh 2>&1); }
out=$(status_out)
grep -q "2 個 commit 還沒進 stage，含別張票的提交（TK-540 ×1）→ 合之前先確認" <<<"$out" && ok || ng "簡報 B 疊在 A 上應改寫成「含別張票」：$(grep -n 'commit 還沒進' <<<"$out")"
grep -q "要我合就說" <<<"$out" && ng "簡報有別張票時不該還寫「要我合就說」：$(grep -n '要我合' <<<"$out")" || ok
# 有遠端、沒指定比誰 → 跟 origin/stage 比（不是本機那條可能沒跟上的 stage）
out=$( (cd "$S2" && unset STAGE_BASE && python3 scripts/branch_tickets.py feature/TK-541 TK-541 2>&1) )
grep -qF "feature/TK-541 比 origin/stage 多 2 個 commit" <<<"$out" && ok || ng "有遠端時應該跟 origin/stage 比：$out"
g2 checkout -q -b feature/TK-542 stage; echo c >> "$S2/code.txt"; g2 add code.txt; g2 commit -q -m "feat: TK-542 單獨一條"
out=$(status_out)
grep -q "1 個 commit 還沒進 stage → 要我合就說「合 TK-542」" <<<"$out" && ok || ng "簡報沒有別張票時要維持原句：$(grep -n 'commit 還沒進' <<<"$out")"
rm -f "$S2/scripts/branch_tickets.py"   # 簡報在 python 缺檔時不能擋、要退回原句
out=$(status_out)
grep -q "1 個 commit 還沒進 stage → 要我合就說" <<<"$out" && ok || ng "branch_tickets.py 不在時簡報要退回原句：$(grep -n 'commit 還沒進' <<<"$out")"

echo "[branch-tickets-test] 通過 $pass 條、失敗 $fail 條"
[ $fail -eq 0 ]
