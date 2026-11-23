#!/usr/bin/env bash
# 啟用版控裡的 git hooks：把 core.hooksPath 指到 .githooks/（源專案 v4.8.0）。
#
# `.git/hooks/` 不進版控，所以每個 clone 要自己跑一次這支（`make hooks`）。選用——不跑就沒有下面三件事。
# 可以重複跑。
#
# 啟用後多三件事：
#   1. commit 前擋沒解乾淨的合併衝突標記（.githooks/pre-commit）。
#   2. 推 stage／prod 前先跑通用關卡（衝突標記、票的走查交代、條件確認、bash 3.2 變數寫法），沒過會擋（.githooks/pre-push）。
#   3. 開發分支每次 commit 後自動推到 origin；stage／prod／main／master 永遠不自動推（.githooks/post-commit）。
#
# 設成**相對路徑** `.githooks`：git 在哪一棵工作樹跑 hook，就用那一棵自己的 .githooks/。
# 設定寫在整個版本庫共用的 .git/config，所以跑一次，主目錄與所有工作區（.claude/worktrees/…）都生效，
# 各用各自那一棵的版本。
#
# 模板內補的（源專案是直接蓋掉）——core.hooksPath 已經是別的值時，不安靜蓋掉：
#   ・指到的資料夾不存在（例：指進一個已經收掉的工作區，hooks 整組安靜失效）→ 改成 .githooks 並說明原本的值；
#   ・就是這一棵的 .githooks，只是寫法不同（寫成固定路徑的話，別的工作區會全部跑這一棵的版本）→ 統一改成 .githooks 並說明；
#   ・指到別的、存在的資料夾（你自己的 hooks，或別的工具裝的）→ 不動，印出現值與要換的那條指令，結束碼 1。
# 也是模板內補的：這個資料夾不是 git 版本庫的最上層（例：範本解壓縮在另一個版本庫底下、自己還沒 git init）→
# 不動外面那個版本庫的設定，結束碼 1；找不到 .githooks/ → 不設定（設了等於把所有 hook 關掉），結束碼 1。
#
# 結束碼：0 已啟用（或不是 git 版本庫，略過）｜1 沒有啟用，原因印在訊息裡。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "${ROOT}" || exit 1
WANT=".githooks"

if [ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" != "true" ]; then
  echo "[hooks] 這個資料夾不是 git 版本庫，略過（git init 或 clone 之後再跑一次 make hooks）"
  exit 0
fi

top="$(git rev-parse --show-toplevel 2>/dev/null)"
top="$(cd "${top}" 2>/dev/null && pwd -P)"
if [ "${top}" != "${ROOT}" ]; then
  echo "[hooks] ⚠️ 沒有啟用：這個資料夾（${ROOT}）不是 git 版本庫的最上層，它在另一個版本庫（${top}）裡面。" >&2
  echo "[hooks]    hooks 是整個版本庫共用的設定，所以沒有更動那個版本庫。這個資料夾要自己當一個版本庫，先在這裡 git init 再跑一次。" >&2
  exit 1
fi

if [ ! -d "${WANT}" ]; then
  echo "[hooks] ⚠️ 沒有啟用：找不到 ${WANT}/ 資料夾，沒有 hook 可以啟用。" >&2
  exit 1
fi

enable() {
  git config core.hooksPath "${WANT}" && return 0
  echo "[hooks] ⚠️ 沒有啟用：寫不進 git 設定（git config core.hooksPath ${WANT} 沒有成功）。" >&2
  exit 1
}

current="$(git config --get core.hooksPath 2>/dev/null || true)"

if [ -z "${current}" ]; then
  enable
elif [ "${current}" = "${WANT}" ]; then
  chmod +x "${WANT}"/* 2>/dev/null || true
  echo "[hooks] 已經啟用了（core.hooksPath = ${WANT}），不用再設定。"
  exit 0
else
  # 相對路徑是相對於工作樹最上層；--type=path 會把開頭的 ~ 展開
  expanded="$(git config --type=path --get core.hooksPath 2>/dev/null || true)"
  [ -n "${expanded}" ] || expanded="${current}"
  case "${expanded}" in
    /*) target="${expanded}" ;;
    *) target="${ROOT}/${expanded}" ;;
  esac
  if [ ! -d "${target}" ]; then
    enable
    echo "[hooks] core.hooksPath 原本是「${current}」，但那個資料夾不存在（等於所有 hook 都沒在跑）——已改成 ${WANT}。"
  elif [ "$(cd "${target}" 2>/dev/null && pwd -P)" = "${ROOT}/${WANT}" ]; then
    enable
    case "${expanded}" in
      /*) echo "[hooks] core.hooksPath 原本是「${current}」——就是這一棵的 ${WANT}，但寫成固定路徑，別的工作區會全部跑這一棵的版本；已改成相對路徑 ${WANT}。" ;;
      *) echo "[hooks] core.hooksPath 原本是「${current}」——跟 ${WANT} 是同一個資料夾，已統一寫成 ${WANT}。" ;;
    esac
  else
    origin="$(git config --show-origin --get core.hooksPath 2>/dev/null | cut -f1)"
    echo "[hooks] ⚠️ 沒有啟用：core.hooksPath 已經指到別的地方，沒有更動。" >&2
    echo "[hooks]    目前的值：${current}（設定來源：${origin:-不明}）" >&2
    echo "[hooks]    那裡可能是你自己的 hooks，或別的工具裝的；換過來之後它們就不會再跑。" >&2
    echo "[hooks]    確定要換成這個專案的 hooks，自己下這一條（只影響這個版本庫），再跑一次 make hooks：" >&2
    echo "[hooks]      git config core.hooksPath ${WANT}" >&2
    exit 1
  fi
fi

chmod +x "${WANT}"/* 2>/dev/null || true
echo "[hooks] 已啟用 ${WANT}/（這個 clone 的主目錄與所有工作區都生效）。之後多三件事："
echo "[hooks]   1. commit 前擋沒解乾淨的合併衝突標記。"
echo "[hooks]   2. 推 stage／prod 前先跑通用關卡（衝突標記、票的走查交代、條件確認、bash 3.2 變數寫法），沒過會擋。"
echo "[hooks]   3. 開發分支每次 commit 後自動推到 origin——stage／prod／main／master 永遠不自動推；沒有 origin 就不推；推不上去只提示、不擋 commit。"
echo "[hooks] 之後不想要：git config --unset core.hooksPath"
