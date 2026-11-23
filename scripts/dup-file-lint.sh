#!/usr/bin/env bash
# 抓版控裡的「複製檔」（「foo 2.py」「foo copy.py」）——源專案 v4.14.0。
#
# 為什麼要這支：源專案曾在版控裡一次發現幾十個這種重複檔，其中一半落在「整個資料夾會被自動載入」的地方，
# 多一份副本就讓程式跑起來不一樣；而這種檔案用肉眼掃 diff 很容易放過去。
# 成因：repo 放在雲端同步資料夾時的同步衝突、在工作區之間用檔案總管拖拉或 cp 搬檔——
# 系統遇到同名檔會自動在檔名後面加「 2」「 copy」另存一份。
#
# 只看「git 追蹤中的檔案」：不進版控的本機產物（裝進來的套件、.claude/worktrees）不算數，
# 也因此不受工作區巢狀在 repo 內的影響。還沒進版控的複製檔由 .gitignore 擋在外面。
#
# 結束碼：0 沒有（或這裡不是 git 版本庫，略過）｜1 有複製檔｜2 自己跑不起來。
# 模板內補的：檔名有中文時也抓得到（源專案沒關 git 的檔名跳脫，中文檔名的複製檔會漏掉）；
# 不是 git 版本庫時明講「略過」，不印成檢查通過。
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

# 「名稱 <空白> 數字.副檔名」或「名稱 copy.副檔名」；副檔名限制在會被執行／載入的類型，
# 避免誤傷正常帶空白數字的檔名（例："報價 2024.pdf" 這種文件不該紅燈）。
# 專案用到別種語言，把副檔名加在最後一組括號裡。
pattern='(^|/)[^/]+ (2|3|4|5|6|7|8|9|copy)\.(py|tsx|ts|jsx|js|json|yml|yaml|sh|sql|html|css)$'

if [ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" != "true" ]; then
  echo "[dup-file-lint] 略過：這個資料夾不是 git 版本庫，沒有「版控內的檔案」可以看（**這次沒有檢查**）。"
  exit 0
fi

# core.quotepath=off：不關的話，中文檔名會被印成 "\346\226\207…" 這種跳脫字串，下面的樣式對不到
files="$(git -c core.quotepath=off ls-files 2>/dev/null)" || {
  echo "[dup-file-lint] ⚠️ 列不出版控內的檔案（git ls-files 沒有成功），這次沒有檢查。" >&2
  exit 2
}
hits="$(printf '%s\n' "$files" | grep -E "$pattern" || true)"

if [ -n "$hits" ]; then
  n=$(printf '%s\n' "$hits" | wc -l | tr -d ' ')
  echo "[dup-file-lint] ❌ 版控內有 ${n} 個疑似複製檔（檔名結尾是「 2」～「 9」或「 copy」）：" >&2
  printf '%s\n' "$hits" | sed 's/^/  /' >&2
  cat >&2 <<'HINT'

  這種檔案多半是系統自動另存的副本：repo 放在雲端同步資料夾時的同步衝突，
  或在工作區之間用檔案總管拖拉、cp 搬檔。
  處理：確認內容確實是副本後 git rm 掉；真的要留，改一個不會被當成副本的檔名。
  避免：在工作區之間搬檔案用 git（cherry-pick／merge），不要用檔案總管拖拉。
HINT
  exit 1
fi

echo "[dup-file-lint] OK（版控內沒有疑似複製檔）"
