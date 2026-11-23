#!/usr/bin/env bash
# 開票助手：取「作者前綴 + 流水號」（例：AMY-01），照 tickets/README.md 模板建檔。
#
# 為什麼是作者前綴（源專案 v4.11.0，取代全域流水號）：
# 全域流水號的撞號是**取號與推送之間的競爭條件**——兩個人在對方 push 之前取號，
# fetch 再勤也看不到彼此（源專案四度因此撞號）。
# 作者前綴給每個人**獨立的號碼空間**，不需要與任何人協調，結構上不會撞。
# 專案若有舊制流水號的票（前綴見 scripts/framework-config.sh）**不改號**，新舊並存。
#
# 前綴規則：
#   ・前綴 = 每個 clone 顯式設定一次（git config ticket.prefix），代表「這台 clone 的作者」，
#     **不是「誰想到需求」**——使用者叫 agent 開票，commit 掛誰名下就用誰的前綴，規則明確不用判斷。
#   ・同一人平行開兩個 session 都在開票時，第二個 session 用 TICKET_PREFIX 環境變數
#     指定別名（例：AMY2），否則 namespace 塌回去照樣撞。
#   ・這裡的環境變數 TICKET_PREFIX 是「這次開票用的作者前綴」。本腳本刻意**不** source
#     scripts/framework-config.sh：那裡的同名設定是凍結的舊制前綴，讀進來會把每張新票都開成舊制號。
#
# 用法：scripts/new-ticket.sh "短題（kebab 或中文）" ["角色，可多個、用逗號分隔"]
#   也可： make new-ticket t="匯出對帳單" r="管理員"
#   前綴覆寫：TICKET_PREFIX=AMY2 scripts/new-ticket.sh "..."
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TICKETS_DIR="${TICKETS_DIR:-$ROOT/tickets}"  # 測試用沙盒入口（ticket-tools-test.sh）
REMOTE="${TICKET_REMOTE:-origin}"
BASE_BRANCH="${TICKET_BASE_BRANCH:-stage}"

title="${1:-}"
roles="${2:-}"

# 0) 決定作者前綴：TICKET_PREFIX 環境變數 > git config ticket.prefix（每個 clone 設一次）。
#
# **不用 git user.name 判**：源專案實測有機器根本沒設 user.name，commit 作者是
# 系統帳號 fallback（<使用者>@<機器名>.local）——拿一個本來就
# 沒人維護的欄位當身分依據，判出來的前綴是假的。改成顯式設定，一次就好：
#
#   git config ticket.prefix AMY    # 存在這個 clone 的 .git/config，不會 commit
#
prefix="${TICKET_PREFIX:-}"
if [ -z "$prefix" ]; then
  prefix="$(git -C "$ROOT" config ticket.prefix 2>/dev/null || echo "")"
fi
if [ -z "$prefix" ]; then
  echo "[new-ticket] 尚未設定票號前綴。每個 clone 設一次即可：" >&2
  echo "    git config ticket.prefix AMY   ← 換成你的（2~8 個大寫字母/數字、字母開頭）" >&2
  echo "  臨時覆寫（同一人第二個平行 session 用）：TICKET_PREFIX=AMY2 make new-ticket …" >&2
  exit 2
fi
if ! [[ "$prefix" =~ ^[A-Z][A-Z0-9]{1,7}$ ]]; then
  echo "[new-ticket] 前綴格式錯誤（'$prefix'）：2~8 個大寫字母/數字、字母開頭" >&2
  exit 2
fi
if [ -z "$title" ]; then
  echo "用法：scripts/new-ticket.sh \"短題\" [\"角色\"]" >&2
  echo "  例：scripts/new-ticket.sh \"匯出對帳單\" \"管理員\"" >&2
  exit 2
fi

# 1) 先 fetch 遠端——取號的重點：讓本地看到別人剛開的票號
#
# **掃全部遠端分支，不只 stage**（源專案 v4.8.0）：只掃 stage 會看不到「已經開好、
# 但還在別人 feature 分支上」的票，那正是源專案一次撞號的成因
# ——對方的票躺在未合併的分支上，取號時完全看不見。
if git -C "$ROOT" fetch --all --prune >/dev/null 2>&1; then
  branches=$(git -C "$ROOT" for-each-ref --format='%(refname)' refs/remotes/ 2>/dev/null | grep -v '/HEAD$')
  # 計數後面接 `|| true`，不接 `|| echo 0`：一條遠端分支都沒有時（全新專案還沒設遠端），
  # `grep -c` 自己會印 0、結束碼是 1；再 `echo 0` 就多印一個 0，這一行訊息會斷成兩行。
  echo "[new-ticket] 已 fetch 全部遠端（取號納入 $(printf '%s\n' "$branches" | grep -c . || true) 條遠端分支上的票）"
  remote_nums=$(
    for ref in $branches; do
      git -C "$ROOT" -c core.quotepath=false ls-tree -r --name-only "$ref" -- tickets/ 2>/dev/null
    done | grep -oE "^tickets/${prefix}-[0-9]+" | grep -oE "${prefix}-[0-9]+"
  )
else
  echo "[new-ticket][warn] fetch 失敗（離線或無此遠端）——改用本地最大號，撞號風險較高；push 前務必先 pull --rebase" >&2
  remote_nums=""
fi

# 1b) 掃**本機其他工作樹**裡的票（源專案 v4.55.0）
#
# fetch 看得到「已經 push 的」，看不到**別條 session 剛開在自己 worktree 裡、還沒提交**的票
# ——而那正是最容易撞的那一批：開票到推送之間有好幾分鐘的空窗。
# 源專案曾一天撞三次（要用的號都被別條 session 先用掉了），
# 三次都是「取號時看不見、事後才發現」。這一步把那個空窗關掉。
#
# **只讀檔名，不讀內容**：別人的工作樹可能正在被寫，碰它的內容沒有好處。
#
# **用 `git worktree list` 列，不用 `$ROOT/.claude/worktrees`**（源專案 v4.70.0）：
# ROOT 是「這支腳本所在的那一棵」，在 worktree 裡跑時 `$ROOT/.claude/worktrees` 不存在，
# 整步靜靜跳過——而「一 session 一 worktree」之後，開票幾乎都在 worktree 裡。
# 源專案因此發出過一個別棵工作樹裡已經有、只是還沒提交的號。
# git 的清單從任何一棵問都一樣，還包含主目錄自己（主目錄也可能有未提交的票）。
worktree_nums=""
wt_paths=$(git -C "$ROOT" worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p')
if [ -n "$wt_paths" ]; then
  worktree_nums=$(
    printf '%s\n' "$wt_paths" | while IFS= read -r wt; do
      ( cd "$wt/tickets" 2>/dev/null && ls "${prefix}"-*.md 2>/dev/null )
    done | grep -oE "^${prefix}-[0-9]+"
  )
  wt_count=$(printf '%s\n' "$wt_paths" | grep -c .)
  echo "[new-ticket] 已掃本機 $wt_count 棵工作樹（含主目錄與還沒提交的票）"
else
  echo "[new-ticket][warn] 列不出本機工作樹——別條 session 還沒提交的票看不到，撞號風險較高" >&2
fi

# **只看檔名，不看路徑**（源專案 v4.94.1）：本機與工作樹兩處 cd 進 tickets/ 再 `ls`，讓 grep 只看得到檔名；
# 遠端那處 `ls-tree` 吐的是 repo 相對路徑，改錨在 `^tickets/` 開頭，並強制 `core.quotepath=false`
# ——預設值遇到中文檔名會輸出 `"tickets/…\351…"`（行首是引號），錨點會全數落空而漏算遠端的號碼。
# 以前 `ls` 印完整路徑，工作樹資料夾名（`.claude/worktrees/AMY-17/…`）會被 grep 當成
# 「17 已被佔用」——先 `make worktree n=AMY-17` 再在裡面開票，就被跳號成 18。
# 檔名一律錨在開頭（`^PREFIX-N`），標題裡剛好寫到別張票號（例「接 AMY-03」）也不會算進去。
#
# 2) 本地 + 遠端 + 其他工作樹合併，取**這個前綴自己的**最大號 +1（10# 強制十進位，防前導零變八進位）。
# 只在自己的 namespace 裡取號——這正是不會撞的原因。
local_nums=$( cd "$TICKETS_DIR" 2>/dev/null && ls "${prefix}"-*.md 2>/dev/null | grep -oE "^${prefix}-[0-9]+" )
max=$(printf '%s\n%s\n%s\n' "$local_nums" "$remote_nums" "$worktree_nums" | grep -oE '[0-9]+$' | sort -n | tail -1)
max=${max:-00}
next=$(printf '%s-%02d' "$prefix" "$((10#$max + 1))")

# 3) 短題正規化到檔名（空白、斜線→ -）
slug=$(printf '%s' "$title" | tr ' /' '--')
file="$TICKETS_DIR/$next-$slug.md"
today=$(date +%Y-%m-%d)
if [ -n "$roles" ]; then roles_field="[$roles]"; else roles_field="[]"; fi

if [ -e "$file" ]; then
  echo "[new-ticket] 檔案已存在，未覆寫：$file" >&2
  exit 1
fi

cat > "$file" <<EOF
---
id: $next
title: $title
status: 待開發        # 待開發 | 開發中 | 完成 | 作廢
roles: $roles_field
owner:
depends: []
spec: docs/SPEC.md#3-功能細節
created: $today
updated: $today
---

<!-- roles 誰使用：填這個產品的角色，例 顧客 / 店員 / 管理員（清單見 docs/SPEC.md〈產品概述〉；可多個，未填 ticket-lint 會擋）；owner 動工時填；depends 填要用到哪幾張票的程式才做得出來／測得了（例：[AMY-03]，不是「主題相關」；做法見 tickets/README.md〈相依的票〉）；spec 換成這個功能在 SPEC 的章節錨點（SPEC 本身等合流 stage 那一次才寫，開票時不動它） -->

## 目的（要解決什麼問題）

一句話說明為什麼要做。

## 使用角色與情境

- 誰、在什麼場景、用什麼裝置操作。

## 逼問紀錄

<!-- 開票前 grill 問過什麼。一題一行：問了什麼／對方怎麼答／因此推翻或確認了哪個假設。
     看票的人不用翻對話，就知道開工前確認過哪些事。
     框架票、只修錯字這類沒有要問的，寫「不適用：<理由>」。（源專案 v4.76.0） -->

- 問：……／答：……／因此：……

## 需求細節

- 與案主確認過的具體行為（含欄位、流程、規則）。
- 欄位權限：……（照 AGENTS.md〈沒權限的欄位，哪裡都不出現〉：哪些欄位出現在新地方或開給新角色，各寫原本誰看得到 → 做完誰看得到；不改程式、不改開放對象寫「不涉及」）

## 條件確認

<!-- 你（agent）自己加的、案主沒講過，而且會讓資料「出現／消失／被一次改掉／被擋掉」的條件，一條一列（源專案 v5.5.0）。
     例：某區塊至少要有一份附件才出現、舊資料一次回填、預設篩選掉某些資料、驗證擋送出。
     純文字、版面、顏色這類沒有筆數的，照預設做、寫在〈需求細節〉，不進這張表。
     符合／擋掉：開票時唯讀查 prod（正式環境）的筆數，寫「N 筆」；〈條件〉格要講清楚分母（哪一群資料、共幾筆）。
       查不到就寫「查不到：<原因>」，不要用估的。
     狀態有三種：已確認｜未確認｜待 prod 資料。只有案主在勾選清單裡回「同意」才是已確認（回答日填當天）；
       「不同意」（照對方的改法改票、重查筆數再給對方看新筆數）、「先略過」「我看不懂」或還沒問，都是未確認——
       開發中不等清單的回答，但**推 stage 前一定要問完**（推 stage／prod 前的條件確認檢查會擋，可先跑 make confirm-lint；源專案 v5.41.0）。
       「待 prod 資料」只給「要看到 prod 筆數才答得出來」的列：〈符合〉或〈擋掉〉寫「查不到：<原因>」，
       案主在推 stage 前那則清單選「等 prod 筆數再答」才能標，回答日填那天；推 prod 前還是要重查筆數再問。
     這節沒有條件可列就整節改寫成「不適用：<理由>」。清單怎麼產生見 pm skill〈4b〉；表格怎麼填見 tickets/README.md〈條件確認〉。 -->

| 條件（含分母） | 符合 | 擋掉 | 狀態 | 回答日 |
|---|---|---|---|---|
| （例）已審核的申請單，附件區至少一份附件才出現確認勾選（分母：prod 已審核的申請單共 3707 筆） | 10 筆 | 3697 筆 | 未確認 | |

## 這次可能會弄壞什麼

<!-- 一行一個編號（W1、W2…）：這次改動有機會波及、但**不打算改**的頁面或功能，
     **以及需求要求其他頁也要檢查或修的（不論寫成一併、同款、也要、一起；一頁一個編號）**。
     推 stage 前每個 W 都要在〈開發備註〉（或〈走查〉節）交代「走查（…）W1 …」，或照 user-walkthrough〈跳過之後怎麼做〉的三行寫「沒走的是：W1 …」，
     推 stage 前的走查紀錄檢查會擋（可先跑 make walkthrough-lint；源專案 v5.30.0）。
     〈驗收標準〉或〈走查〉要有以同一個編號開頭的行。真的沒有就寫「不適用：<理由>」。
     由來（源專案）：某張票的邊界寫了「不動隔壁那個畫面」，五條驗收標準卻沒有一條關於它，
     三天後那個畫面的五個互動在整合環境壞了一整天。 -->

- W1 例：某個清單頁

## 驗收標準

- [ ] W1 那一頁的哪幾個互動要各按一次（風險編號要對得上）
- [ ] 可驗證的條件一
- [ ] 可驗證的條件二

## 邊界（明確不做什麼）

- 這張票不包含的範圍，避免無限延伸。

## 開發備註（/dev 填寫）

- 實作決策、風險、對應 commit / PR。
EOF

echo "[new-ticket] 已建立 $next → $file"
echo "[new-ticket] 記得補：roles（誰用）、目的、驗收；動工時標「開發中」+ 填 owner。"
