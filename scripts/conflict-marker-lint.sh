#!/usr/bin/env bash
# 擋「git 衝突標記被 commit 進去」（源專案 v5.39.0）。
#
# 為什麼：源專案合流時解一份文件的衝突，替換指令沒生效（macOS 的 `sed -i` 少了 `''`），接著照常 commit，
# `<<<<<<<`／`=======`／`>>>>>>>` 三行標記進了整合分支。程式檔有標記時，格式檢查或編譯多半會紅；
# 文件與設定檔（.md、.json、.yml）沒人管。
#
# 只認「行首的 <<<<<<< 或 >>>>>>>（後面接空格或行尾）」，不看 =======：
#   ・真的衝突一定同時有 <<<<<<< 與 >>>>>>>；
#   ・markdown 的 7 個等號標題底線剛好是 =======，看它會誤報（git diff --check 就是這樣，不能直接用）。
#
# 用法：
#   conflict-marker-lint.sh --staged               看這次要 commit 的新增行（.githooks/pre-commit 用）
#   conflict-marker-lint.sh --range <遠端> <本地>   看這次要推的範圍的新增行（.githooks/pre-push 用）
#   conflict-marker-lint.sh                        掃整棵追蹤中的檔案（手動補查用；從子資料夾跑也是掃整棵）
# --range 的 <遠端> 全是 0（遠端還沒有這條分支）時：
#   ・有 origin/stage → 對它與 <本地> 的共同祖先比（源專案的做法）；
#   ・連 origin/stage 都沒有（新專案第一次推）→ 把要推的那個 commit 整棵當成新增來查
#     （模板內補的；源專案這種情況回 2＝沒有檢查，而範本的新專案第一次推一定會遇到）。
# 結束碼：0 沒有；1 有標記（印出檔案:行號）；2 自己跑不起來（呼叫端只警告「這次沒有檢查」後放行）。
#
# 另外兩處模板內補的：
#   ・git diff 指定 a/、b/ 前綴——使用者的 git 設了 diff.noprefix 時，回報的檔名才不會被切掉開頭兩個字；
#   ・不帶參數時先切到版本庫最上層——git grep 預設只看目前資料夾以下，從子資料夾跑會漏掉其他地方卻照樣回 0。
set -uo pipefail

ZERO=0000000000000000000000000000000000000000
PAT='^(<{7}|>{7})( |$)'

report() {  # 讀 "檔案:行號: 內容" 行；有內容就印提示並回 1
  local hits
  hits="$(cat)"
  [ -z "$hits" ] && return 0
  echo "[conflict-marker-lint] ⛔ 發現沒解掉的 git 衝突標記（<<<<<<<／>>>>>>>）：" >&2
  printf '%s\n' "$hits" | head -20 | sed 's/^/    /' >&2
  echo "[conflict-marker-lint]    處理：打開上面的檔案，把 <<<<<<<、=======、>>>>>>> 三種行連同不要的那一邊刪掉；" >&2
  echo "[conflict-marker-lint]    文件裡真的要放衝突範例，縮排或放進行內程式碼（只擋行首）。" >&2
  return 1
}

added_lines() {  # stdin: git diff -U0 輸出 → "檔案:行號: 內容"（只含符合標記的新增行）
  awk '
    /^diff --git /      { hdr = 1; next }
    hdr && /^\+\+\+ /   { f = substr($0, 7); next }
    /^@@/               { hdr = 0; match($0, /\+[0-9]+/); n = substr($0, RSTART + 1, RLENGTH - 1) - 1; next }
    !hdr && /^\+/       { n++; line = substr($0, 2); if (line ~ /^(<<<<<<<|>>>>>>>)( |$)/) print f ":" n ": " line; next }
  '
}

case "${1:-}" in
  --staged)
    out="$(git -c core.quotepath=off diff --cached -U0 --no-color --no-ext-diff --src-prefix=a/ --dst-prefix=b/ 2>/dev/null)" || {
      echo "[conflict-marker-lint] ⚠️ 讀不到暫存區的差異，這次沒有檢查。" >&2
      exit 2
    }
    printf '%s\n' "$out" | added_lines | report
    exit $?
    ;;
  --range)
    remote="${2:-}"; local_sha="${3:-}"
    [ -n "$remote" ] && [ -n "$local_sha" ] || { echo "用法：$0 --range <遠端 sha> <本地 sha>" >&2; exit 2; }
    base_kind=commit
    if [ "$remote" = "$ZERO" ]; then
      if git rev-parse -q --verify "origin/stage^{commit}" >/dev/null 2>&1; then
        remote="$(git merge-base origin/stage "$local_sha" 2>/dev/null)" || {
          echo "[conflict-marker-lint] ⚠️ 算不出 ${local_sha:0:8} 與 origin/stage 的共同祖先，這次沒有檢查。" >&2
          exit 2
        }
      else
        # 沒有 origin/stage 可以比：對「空的樹」比，要推的 commit 裡每一行都算新增
        remote="$(git hash-object -t tree /dev/null 2>/dev/null)" || {
          echo "[conflict-marker-lint] ⚠️ 沒有 origin/stage 可以比，也算不出空樹，這次沒有檢查。" >&2
          exit 2
        }
        base_kind=tree
      fi
    fi
    git cat-file -e "${remote}^{${base_kind}}" 2>/dev/null && git cat-file -e "${local_sha}^{commit}" 2>/dev/null || {
      echo "[conflict-marker-lint] ⚠️ 遠端現況本機不認得（先 git fetch），這次沒有檢查。" >&2
      exit 2
    }
    out="$(git -c core.quotepath=off diff -U0 --no-color --no-ext-diff --src-prefix=a/ --dst-prefix=b/ "$remote" "$local_sha" 2>/dev/null)" || {
      echo "[conflict-marker-lint] ⚠️ 讀不到 ${remote:0:8}..${local_sha:0:8} 的差異，這次沒有檢查。" >&2
      exit 2
    }
    printf '%s\n' "$out" | added_lines | report
    exit $?
    ;;
  "")
    top="$(git rev-parse --show-toplevel 2>/dev/null)" && [ -n "$top" ] && cd "$top" 2>/dev/null || {
      echo "[conflict-marker-lint] ⚠️ 這裡不是 git 版本庫的工作樹（或 git 跑不起來），這次沒有檢查。" >&2
      exit 2
    }
    out="$(git grep -nIE -e "$PAT" 2>/dev/null)"
    rc=$?
    case "$rc" in
      0) printf '%s\n' "$out" | sed 's/^\([^:]*:[0-9]*\):/\1: /' | report; exit $? ;;
      1) echo "[conflict-marker-lint] OK（追蹤中的檔案沒有沒解掉的衝突標記）"; exit 0 ;;
      *) echo "[conflict-marker-lint] ⚠️ git grep 跑不起來（結束碼 ${rc}），這次沒有檢查。" >&2; exit 2 ;;
    esac
    ;;
  *)
    echo "用法：$0 [--staged | --range <遠端 sha> <本地 sha>]" >&2
    exit 2
    ;;
esac
