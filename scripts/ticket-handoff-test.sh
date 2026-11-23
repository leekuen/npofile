#!/usr/bin/env bash
# scripts/ticket-handoff.sh 的測試（源專案 v4.81.0）：在臨時 git 倉庫裡跑，不碰真的 repo。
# 驗：票搬得過去、status／owner 只改檔頭、內文不動、來源（追蹤與未追蹤兩種）被清掉、
# 找不到／多個來源會擋、已在目標的票只更新狀態、--dry-run 不動任何檔案。
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail=0
ok()  { echo "  ✓ $1"; }
bad() { echo "  ✗ $1"; fail=1; }

cd "$TMP" && git init -q main && cd main
git config user.email t@t && git config user.name t
mkdir -p tickets scripts .claude/worktrees
cp "$HERE/scripts/ticket-handoff.sh" scripts/
touch tickets/.keep
git add scripts/ticket-handoff.sh tickets/.keep && git commit -q -m init
git worktree add -q .claude/worktrees/src -b feature/src
git worktree add -q .claude/worktrees/dst -b feature/dst
S=.claude/worktrees/src; D=.claude/worktrees/dst

mk() { # $1=dir $2=檔名 $3=status $4=owner
  printf -- '---\nid: %s\ntitle: 測試票\nstatus: %s\nroles: [使用者]\nowner:%s\n---\n\n## 目的\n\nowner: 這行在內文不能被改\nstatus: 待開發\n' "${2%%-*}" "$3" "${4:+ $4}" > "$1/tickets/$2"
}
mk "$S" "TK-901-測試一.md" 待開發 ""
mk "$S" "TK-902-測試二.md" 待開發 "someone"
git -C "$S" add -- tickets/TK-901-測試一.md tickets/TK-902-測試二.md && git -C "$S" commit -q -m t1   # 901、902 被追蹤
mk "$S" "TK-903-未追蹤.md" 待開發 ""                                                                    # 903 沒追蹤

echo "dry-run"
bash scripts/ticket-handoff.sh dst TK-901 --dry-run >/dev/null
[ ! -e "$D/tickets/TK-901-測試一.md" ] && [ -e "$S/tickets/TK-901-測試一.md" ] && ok "dry-run 不動任何檔案" || bad "dry-run 動了檔案"

echo "搬 901（追蹤）＋902（owner 已有）＋903（未追蹤）"
bash scripts/ticket-handoff.sh dst TK-901 TK-902 TK-903 >/dev/null 2>"$TMP/err" || bad "指令失敗：$(cat "$TMP/err")"
f1="$D/tickets/TK-901-測試一.md"
grep -q '^status: 開發中' "$f1" && ok "901 status→開發中" || bad "901 status 沒改"
grep -q '^owner: claude-cc-dst' "$f1" && ok "901 owner 已填" || bad "901 owner 沒填"
grep -q '^owner: someone' "$D/tickets/TK-902-測試二.md" && ok "902 既有 owner 不被覆蓋" || bad "902 owner 被蓋掉"
[ "$(grep -c '^status: 待開發' "$f1")" = 1 ] && grep -q '^owner: 這行在內文不能被改' "$f1" && ok "內文裡長得像檔頭的行沒被改" || bad "內文被改到"
[ -z "$(git -C "$D" status --short)" ] && ok "目標工作區乾淨（已提交）" || bad "目標有未提交：$(git -C "$D" status --short)"
[ ! -e "$S/tickets/TK-901-測試一.md" ] && [ ! -e "$S/tickets/TK-902-測試二.md" ] && [ ! -e "$S/tickets/TK-903-未追蹤.md" ] && ok "來源三份都清掉（追蹤＋未追蹤）" || bad "來源還有殘留"
[ -z "$(git -C "$S" status --short)" ] && ok "來源工作區乾淨" || bad "來源有未提交：$(git -C "$S" status --short)"

echo "找不到"
bash scripts/ticket-handoff.sh dst TK-999 >/dev/null 2>&1 && bad "找不到卻成功" || ok "找不到票會擋"

echo "多個來源要擋"
git worktree add -q .claude/worktrees/src2 -b feature/src2
mk "$S" "TK-904-重複.md" 待開發 ""; mk .claude/worktrees/src2 "TK-904-重複.md" 待開發 ""
bash scripts/ticket-handoff.sh dst TK-904 >/dev/null 2>&1 && bad "多來源卻成功" || ok "多個來源會擋"
# 模板內補的：擋下來的理由要是「多個來源」（不是後面複製失敗剛好也回非 0），而且兩邊的票都沒被動到
out=$(bash scripts/ticket-handoff.sh dst TK-904 2>&1); rc=$?
case "$out" in *"同時出現在多個工作區"*"--from"*) ok "多個來源：有講清楚要用 --from 指名" ;; *) bad "多個來源卻沒講要用 --from 指名（結束碼 ${rc}）：$out" ;; esac
[ -e "$S/tickets/TK-904-重複.md" ] && [ -e ".claude/worktrees/src2/tickets/TK-904-重複.md" ] && [ ! -e "$D/tickets/TK-904-重複.md" ] && ok "多個來源被擋時，兩邊的票都還在、目標沒有多出檔案" || bad "多個來源被擋時有檔案被動到"
bash scripts/ticket-handoff.sh dst TK-904 --from src >/dev/null 2>&1 && ok "--from 指名可以" || bad "--from 指名失敗"

echo "已在目標的票只更新狀態"
mk "$D" "TK-905-已在.md" 待開發 ""; git -C "$D" add -- tickets/TK-905-已在.md && git -C "$D" commit -q -m t5
bash scripts/ticket-handoff.sh dst TK-905 >/dev/null 2>&1
grep -q '^status: 開發中' "$D/tickets/TK-905-已在.md" && ok "905 只改狀態" || bad "905 沒更新"

[ "$fail" = 0 ] && echo "ticket-handoff 測試：全部通過" || { echo "ticket-handoff 測試：有失敗"; exit 1; }
