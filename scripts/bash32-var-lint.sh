#!/usr/bin/env bash
# 擋「$變數 後面直接接中文／全形字」（源專案 v4.86.0）。一律寫成 ${變數}。
# 來歷：源專案有一支腳本在 macOS 上整支中斷（訊息像「num�: unbound variable」）——
# macOS 內建的 bash 3.2 在中文語系下，會把 "$num：" 全形冒號的第一個位元組當成變數名的一部分；
# 有 set -u 就當場中斷，沒有就默默印成空白。Linux 多半是 bash 5 不會出事，所以只有在 macOS 本機才看得到。
#
# 判準（照源專案）：不是註解的行裡，「$ 加英文變數名」後面直接接非 ASCII 字元。
# 用 perl（macOS 與 Linux 都有），不用 grep -P（macOS 的 grep 沒有）。
#
# 掃哪些檔：
#   ・git 追蹤中的 *.sh；
#   ・還沒進版控、但沒被 .gitignore 忽略的 *.sh（模板內補的：剛寫好還沒 commit 的腳本最容易中）；
#   ・.githooks/ 底下的檔（模板內補的：hook 沒有 .sh 副檔名，只看 *.sh 會漏掉）。
#   這裡不是 git 版本庫（或 git 列不出檔案）時，改用 find 掃整個資料夾（跳過 .git 與 .claude/worktrees），
#   並在結果裡講明（模板內補的：源專案這種情況是一個檔都沒掃就印 OK）。
#
# 結束碼：0 沒有｜1 有這種寫法（印出 檔案:行號）｜2 自己跑不起來（沒有檢查）。
set -u
cd "$(dirname "$0")/.." || exit 2

command -v perl >/dev/null 2>&1 || {
  echo "[bash32-var-lint] ⚠️ 找不到 perl，這次沒有檢查。" >&2
  exit 2
}

work="$(mktemp -d "${TMPDIR:-/tmp}/bash32-var-lint.XXXXXX")" || {
  echo "[bash32-var-lint] ⚠️ 建不出暫存資料夾，這次沒有檢查。" >&2
  exit 2
}
trap 'rm -rf "${work}"' EXIT

# 檔名清單用 NUL 分隔（檔名可以有空白、中文），所以放檔案裡、不放變數
mode=git
if [ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" != "true" ] \
  || ! git ls-files -z --cached --others --exclude-standard -- '*.sh' '.githooks/*' >"${work}/all" 2>/dev/null; then
  mode=find
  find . \( -path ./.git -o -path ./.claude/worktrees \) -prune -o \
    -type f \( -name '*.sh' -o -path './.githooks/*' \) -print0 >"${work}/all" 2>/dev/null || {
    echo "[bash32-var-lint] ⚠️ 列不出要掃的檔案（git 與 find 都沒有成功），這次沒有檢查。" >&2
    exit 2
  }
fi

# 只留真的還在的檔（git 的清單裡會有「已經刪掉、還沒 commit」的檔）
n=0
: >"${work}/list"
while IFS= read -r -d '' f; do
  [ -f "${f}" ] || continue
  printf '%s\0' "${f}" >>"${work}/list"
  n=$((n + 1))
done <"${work}/all"

hits=""
if [ "${n}" -gt 0 ]; then
  hits="$(xargs -0 perl -ne 'print "$ARGV:$.: $_" if !/^\s*#/ && /\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7F]/; close ARGV if eof' <"${work}/list")" || {
    echo "[bash32-var-lint] ⚠️ perl 掃到一半出錯，這次沒有檢查完。" >&2
    exit 2
  }
fi

if [ -n "${hits}" ]; then
  echo "[bash32-var-lint] ✗ 這幾行的 \$變數 後面直接接了中文或全形字，macOS 的 bash 3.2 會讀錯變數名，改成 \${變數}："
  printf '%s\n' "${hits}" | sed 's/^/  /'
  exit 1
fi

if [ "${mode}" = find ]; then
  echo "[bash32-var-lint] OK（git 列不出檔案——這裡不是 git 版本庫，或 git 出了狀況——改用 find 掃了 ${n} 個檔；沒有照 .gitignore 過濾，本機產物也一起掃了）"
else
  echo "[bash32-var-lint] OK（掃了 ${n} 個檔）"
fi
