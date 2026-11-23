#!/usr/bin/env bash
# scripts/next-framework-version.sh 的測試：在臨時 git 倉庫裡跑，不碰真的 repo。
# 這支腳本要守的三件事：
#   1. 只認檔頭「框架版本：vX.Y.Z」與決策紀錄表每一列第一格的版號——
#      內文寫到的別的版號（「源專案 v9.9.9」這種來歷）不能被拿來算下一號
#   2. 別條遠端分支上已經寫好、還沒合進來的版號要算進去（防撞號，源專案 v4.45.0）
#   3. --minor（預設）／--patch／--major 三種升法；不認得的參數要擋
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
pass=0; fail=0
ok()  { echo "  ✓ $1"; pass=$((pass+1)); }
bad() { echo "  ✗ $1"; fail=$((fail+1)); }

# mkrepo <目錄>：開一個放了被測腳本的空 repo（分支叫 stage）
mkrepo() {
  git init -q "$1" && git -C "$1" checkout -q -b stage
  git -C "$1" config user.email t@t && git -C "$1" config user.name t
  mkdir -p "$1/scripts" "$1/docs" && cp "$HERE/scripts/next-framework-version.sh" "$1/scripts/"
}
# doc <目錄> <檔頭版號，- 表示不寫檔頭那一行> <表格列…>：寫一份 docs/FRAMEWORK.md
doc() {
  local d="$1" head="$2" row; shift 2
  {
    echo "# FRAMEWORK.md — 協作框架"
    echo
    [ "$head" != "-" ] && echo "> **框架版本：${head}**（此為單一事實來源，簡報會讀這裡）"
    echo
    echo "## 3. 決策紀錄"
    echo
    echo "| 版號 | 日期 | 決策（改了什麼） | 原因（為什麼） |"
    echo "|------|------|------|------|"
    for row in "$@"; do echo "$row"; done
  } > "$d/docs/FRAMEWORK.md"
}
# save <目錄> <訊息>：把 FRAMEWORK.md 提交起來
save() { git -C "$1" add docs/FRAMEWORK.md scripts/next-framework-version.sh && git -C "$1" commit -q -m "$2"; }
# run <目錄> [參數]：版號（標準輸出）放 out、說明（標準錯誤）放 err、結束碼放 rc
run() {
  local d="$1"; shift
  out=$(bash "$d/scripts/next-framework-version.sh" "$@" 2>"$TMP/err"); rc=$?
  err=$(cat "$TMP/err")
}
# want <說明> <期望印出的版號>：結束碼要是 0，標準輸出要「剛好只有」那個版號
want() {
  if [ "$rc" = 0 ] && [ "$out" = "$2" ]; then ok "$1"
  else bad "$1：期望 ${2}，實際「${out}」（結束碼 ${rc}）｜${err}"; fi
}
# push_branch <分支> <訊息>：在主 repo 開一條分支、提交現在的 FRAMEWORK.md、推上遠端，
# 然後把本機分支與遠端追蹤分支都刪掉——這條分支只存在於遠端，要靠被測腳本自己 fetch 才看得到
push_branch() {
  git -C "$R" checkout -q -b "$1" && save "$R" "$2" && git -C "$R" push -q origin "$1"
  git -C "$R" checkout -q stage && git -C "$R" branch -q -D "$1"
  git -C "$R" update-ref -d "refs/remotes/origin/$1"
}

R="$TMP/repo"; mkrepo "$R"
git init -q --bare "$TMP/origin.git" && git -C "$R" remote add origin "$TMP/origin.git"
ROW1="| v4.1.0 | 2026-01-01 | 第一版 | 原因 |"
ROW2="| v4.2.0 | 2026-01-02 | 第二版 | 原因 |"

echo "三種升法（檔頭與表格最大的都是 v4.2.0）"
doc "$R" v4.2.0 "$ROW2" "$ROW1"
save "$R" init && git -C "$R" push -q origin stage
run "$R";         want "不給參數＝下一個 MINOR" v4.3.0
run "$R" --minor; want "--minor" v4.3.0
run "$R" --patch; want "--patch" v4.2.1
run "$R" --major; want "--major" v5.0.0
run "$R" --bogus
if [ "$rc" = 2 ] && [ -z "$out" ]; then ok "不認得的參數會擋（結束碼 2、不印版號）"
else bad "不認得的參數沒擋：結束碼 ${rc}、印出「${out}」"; fi

echo "內文提到別的版號不算"
doc "$R" v4.2.0 \
  "| v4.2.0 | 2026-01-02 | **移植源專案 v4.3.0–v9.9.9 的改進**：來歷見源專案 v9.9.9 | 源專案 v9.9.9 的教訓 |" \
  "$ROW1"
echo "這一段是表格外的內文：源專案 v9.9.9 曾經這樣做。" >> "$R/docs/FRAMEWORK.md"
run "$R"; want "內文的「源專案 v9.9.9」不影響結果" v4.3.0
doc "$R" v4.2.0 "| v4.2.0 | 2026-01-02 | v9.9.9 | 對照：| v9.9.9 | |" "$ROW1"
run "$R"; want "不是第一格的格子剛好是版號也不算" v4.3.0
doc "$R" v4.2.0 "| v4.2.0 | 2026-01-02 | 檔頭原本寫「框架版本：v8.8.8」，這次改掉 | 原因 |" "$ROW1"
run "$R"; want "檔頭以外又出現的「框架版本：v8.8.8」不算" v4.3.0

echo "檔頭與列首都算、照數字比大小"
doc "$R" v4.4.0 "$ROW2" "$ROW1"
run "$R"; want "檔頭 v4.4.0 比表格大（表格還沒補列）→ v4.5.0" v4.5.0
doc "$R" v4.2.0 "| v4.3.0 | 2026-01-03 | 第三版 | 原因 |" "$ROW2"
run "$R"; want "列首 v4.3.0 比檔頭大（檔頭還沒改）→ v4.4.0" v4.4.0
doc "$R" v4.9.0 "| v4.10.0 | 2026-01-04 | 第十版 | 原因 |" "| v4.9.0 | 2026-01-03 | 第九版 | 原因 |"
run "$R"; want "v4.10.0 比 v4.9.0 大（照數字、不是照字串）→ v4.11.0" v4.11.0
# 模板內補的：最大的版號修訂號不是 0 時，--minor／--major 要把後面的歸零
doc "$R" v4.12.1 "| v4.12.1 | 2026-01-05 | 修訂 | 原因 |" "$ROW2"
run "$R";         want "最大的是 v4.12.1：--minor 把修訂號歸零 → v4.13.0" v4.13.0
run "$R" --patch; want "同上，--patch → v4.12.2" v4.12.2
run "$R" --major; want "同上，--major → v5.0.0" v5.0.0

echo "別條遠端分支上的版號"
doc "$R" v4.5.0 "| v4.5.0 | 2026-01-05 | 別條 session 已經寫好、還沒合進來 | 原因 |" "$ROW2"
push_branch feature/other "別條分支佔了 v4.5.0"
doc "$R" v4.2.0 "$ROW2" "$ROW1"   # 本機這一份還停在 v4.2.0
run "$R";         want "遠端分支上更大的列首版號被算進去 → v4.6.0" v4.6.0
run "$R" --patch; want "同上，--patch → v4.5.1" v4.5.1
run "$R" --major; want "同上，--major → v5.0.0" v5.0.0
doc "$R" v4.2.0 "| v4.7.0 | 2026-01-07 | 只補了表格、檔頭還沒改 | 原因 |" "$ROW2"
push_branch feature/row-only "只補表格"
doc "$R" v4.2.0 "$ROW2" "$ROW1"
run "$R"; want "遠端分支只補了表格那一列也算 → v4.8.0" v4.8.0
doc "$R" v4.2.0 "| v4.2.0 | 2026-01-02 | 移植源專案 v9.9.9 的改進 | 源專案 v9.9.9 |" "$ROW1"
push_branch feature/prose "內文提到別的版號"
doc "$R" v4.2.0 "$ROW2" "$ROW1"
run "$R"; want "遠端分支內文的「源專案 v9.9.9」不影響 → 仍是 v4.8.0" v4.8.0

echo "遠端連不上、還沒設遠端"
OFF="$TMP/off"; mkrepo "$OFF"; doc "$OFF" v4.2.0 "$ROW2" "$ROW1"
git -C "$OFF" remote add origin "$TMP/沒有這個遠端.git"
run "$OFF"; want "遠端連不上：照本機算、不中斷" v4.3.0
case "$err" in *"fetch 失敗"*) ok "遠端連不上時有講「只看本機」" ;; *) bad "遠端連不上卻沒有提醒：${err}" ;; esac
SOLO="$TMP/solo"; mkrepo "$SOLO"; doc "$SOLO" v4.2.0 "$ROW2" "$ROW1"
run "$SOLO"; want "還沒設遠端：照本機算" v4.3.0
case "$err" in *"納入 0 條分支"*) ok "還沒設遠端時訊息寫「納入 0 條分支」" ;; *) bad "還沒設遠端時的訊息不對：${err}" ;; esac
doc "$SOLO" - "| — | 2026-01-01 | 前史（v1.0.0–v3.1.0，源專案） | 原因 |"
run "$SOLO"
if [ "$rc" = 1 ] && [ -z "$out" ]; then ok "檔頭與列首都沒有版號 → 結束碼 1、不印版號（不拿內文的湊數）"
else bad "檔頭與列首都沒有版號卻沒擋：結束碼 ${rc}、印出「${out}」"; fi

echo "[next-framework-version-test] 通過 ${pass} 條、失敗 ${fail} 條"
[ "$fail" -eq 0 ]
