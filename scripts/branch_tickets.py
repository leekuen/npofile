#!/usr/bin/env python3
"""這條分支會帶上 stage 的提交，分屬哪幾張票（源專案 v5.16.0）。

用法：python3 scripts/branch_tickets.py <ref> [自己的票號 ...]
      printf '<工作區路徑>\\t<分支>\\t<票號/票號>\\n…' | python3 scripts/branch_tickets.py --brief

為什麼有這支（相依的票平行開發）：B 票疊在 A 票的分支上開發時，B 的分支比 stage 多出來的提交
裡有 A 的。只看「B 的票號」會以為都是 B 的；合之前要看得到「這條分支會帶上哪幾張票」，
才知道 A 是同一條線、已上 stage，還是要一起併。

分組規則：
  ・票號前綴從 tickets/ 的檔名推（ticket_re），一筆提交提到好幾張票就全抓。
    另外固定認 FW：框架變更沒有票，提交訊息寫的是工作區名稱（例 FW-5.1，號碼可帶小數點）。
  ・提到「自己的票」就算自己的，否則算第一張；沒有票號 → （沒寫票號）。
  ・--cherry-pick --right-only：內容早已直接進 stage 的提交不算。
  ・排除 tickets/ 底下的檔案——搬票的提交（`tickets: X 移到 …`）全在 tickets/ 裡，不算程式。
  ・不 fetch（簡報要快；要最新自己先 git fetch）。
  ・比的對象：有遠端就是 origin/stage；還沒設遠端的專案退回本機的 stage（環境變數 STAGE_BASE 可指定）。
  ・結束碼：有別張票 → 1，否則 0。「（沒寫票號）」認不出是誰的，只列不算別張票。
--brief 一次處理全部工作區，給 agent-status.sh 的簡報用：stdin 每列「工作區路徑 TAB 分支 TAB 分支名上的票號」
（票號寫法 TK-83/86；沒有票號的列略過、不判別張票）。只印有別張票的工作區：「工作區路徑 TAB 別張票摘要」。
  ・不加 --cherry-pick（源專案實測：二十幾個工作區加了要 3.6 秒，不加 0.4 秒）。
  ・「自己的票」＝分支名上的票號（兩個數字且差 ≤20 就展開成範圍：TK-83/86 → 83～86），再加上
    被列成別張票、而且票檔 owner 是 claude-cc-<工作區名稱或分支名> 的那幾張（同一條線做的票）。
    只讀被列出的那幾張的 owner，不掃全部票檔。
"""
import os
import re
import subprocess
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 票檔名的前綴：大寫字母開頭、共 2~8 個大寫字母／數字（例 TK、AMY2）
TICKET_FILE_RE = re.compile(r"^(?:tickets/)?([A-Z][A-Z0-9]{1,7})-\d+-")
NO_TICKET = "（沒寫票號）"
RANGE_MAX = 20


def git(*args, check=True):
    r = subprocess.run(["git", "-C", ROOT, "-c", "core.quotePath=false", *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"[branch-tickets] git {' '.join(args)} 失敗：{r.stderr.strip()}")
    return r.stdout


def stage_base():
    """整合分支拿誰來比：有遠端就是 origin/stage；還沒設遠端（或還沒推過 stage）的專案退回本機的 stage。"""
    env = os.environ.get("STAGE_BASE")
    if env:
        return env
    for ref, name in (("refs/remotes/origin/stage", "origin/stage"), ("refs/heads/stage", "stage")):
        r = subprocess.run(["git", "-C", ROOT, "rev-parse", "--verify", "-q", ref], capture_output=True, text=True)
        if r.returncode == 0:
            return name
    return "origin/stage"   # 兩個都沒有：照原樣比下去，讓 git 的錯誤訊息講清楚缺哪一個


STAGE = stage_base()


def ticket_prefixes(ref):
    """tickets/ 裡真的有票的前綴（本機工作區＋ref 兩邊都算），另加 FW（框架變更的工作區名稱）。"""
    names = os.listdir(os.path.join(ROOT, "tickets")) if os.path.isdir(os.path.join(ROOT, "tickets")) else []
    names += git("ls-tree", "--name-only", f"{ref}:tickets", check=False).splitlines()
    return {m.group(1) for n in names if (m := TICKET_FILE_RE.match(n))} | {"FW"}


def ticket_re(ref):
    """只認 tickets/ 裡真的有票的前綴，不然 UTF-8、SHA-256 會被當成票號。
    前綴是每個作者自己設的（git config ticket.prefix），寫死清單會漏掉新作者——
    源專案曾經把新作者的票當成「沒寫票號」。"""
    alt = "|".join(sorted(ticket_prefixes(ref), key=lambda p: (-len(p), p)))
    # 號碼可帶小數點（FW-5.1）；只寫 -\d+ 會把 FW-5.1 截成 FW-5（源專案 v5.9.0）
    return re.compile(rf"\b((?:{alt})-\d+(?:\.\d+)*)\b")


def log_lines(base, ref, cherry=True, exclude_tickets=False, git_fn=git):
    """ref 比 base 多的非合併提交，每筆「短 sha 標題」。"""
    args = ["log", "--no-merges", "--right-only"]   # 三個點會連 base 那邊多的提交一起印，只要 ref 這邊的
    if cherry:
        args += ["--cherry-pick"]
    args += ["--format=%h %s", f"{base}...{ref}"]
    if exclude_tickets:
        args += ["--", ".", ":!tickets"]
    return git_fn(*args).splitlines()


def bucket(lines, tre, own):
    """每筆提交歸到一張票：有提到 own 的就算那張（「參考 TK-39 的做法」不算帶上 TK-39），否則第一張。"""
    by_ticket = defaultdict(list)
    for line in lines:
        ids = tre.findall(line) or [NO_TICKET]
        hit = [t for t in ids if t in own]
        by_ticket[(hit or ids)[0]].append(line)
    return by_ticket


def group(base, ref, own=(), cherry=True, exclude_tickets=False, git_fn=git, tre=None):
    """git_fn／tre 可以換掉：別支腳本要拿同一套分組規則去比別的分支時，帶自己的 git 包裝與票號樣式進來。"""
    own = set(own)
    lines = log_lines(base, ref, cherry, exclude_tickets, git_fn)
    return lines, bucket(lines, tre or ticket_re(ref), own)


def others_of(by_ticket, own):
    return sorted(t for t in by_ticket if t != NO_TICKET and t not in own)


def summary(by_ticket, keys):
    return "、".join(f"{t} ×{len(by_ticket[t])}" for t in sorted(keys, key=lambda t: (-len(by_ticket[t]), t)))


def branch_own(label, tre):
    """分支名上的票號（TK-83/86 或 TK-63）→ 票號集合。兩個數字且差 ≤20 展開成範圍。"""
    parts = [p for p in label.split("/") if p]
    if not parts:
        return set()
    m = re.fullmatch(r"(.+)-(\d+)", parts[0])
    if not m:
        return {parts[0]} if tre.fullmatch(parts[0]) else set()
    prefix, first = m.group(1), m.group(2)
    nums = [int(first)] + [int(p) for p in parts[1:] if p.isdigit()]
    if len(nums) == 2 and 0 < nums[1] - nums[0] <= RANGE_MAX:
        nums = list(range(nums[0], nums[1] + 1))
    width = len(first)   # 票號有前導零（TK-04、TK-0145、AMY2-01）：位數照第一個數字補回去，不然自己的票會變成「別張票」
    ids = {f"{prefix}-{str(n).zfill(width)}" for n in nums}
    return {t for t in ids if tre.fullmatch(t)}


def owner_of(ticket, tree_path, ref):
    """只讀那一張票檔的 owner 行：先看該工作區，再看主目錄，最後看 ref 上的版本。"""
    for root in (tree_path, ROOT):
        d = os.path.join(root, "tickets")
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.startswith(ticket + "-") and name.endswith(".md"):
                with open(os.path.join(d, name), encoding="utf-8") as fh:
                    for line in fh:
                        if line.startswith("owner:"):
                            return line.split(":", 1)[1].split("#")[0].strip()
                        if line.startswith("## "):
                            break
    for name in git("ls-tree", "--name-only", f"{ref}:tickets", check=False).splitlines():
        if name.startswith(ticket + "-") and name.endswith(".md"):
            for line in git("show", f"{ref}:tickets/{name}", check=False).splitlines():
                if line.startswith("owner:"):
                    return line.split(":", 1)[1].split("#")[0].strip()
    return ""


def same_line_owner(owner, tree_path, branch):
    names = {os.path.basename(tree_path.rstrip("/")), re.sub(r"^feature/", "", branch)}
    return owner.startswith("claude-cc-") and owner[len("claude-cc-"):] in names


def brief(stdin):
    tre = ticket_re(STAGE)
    for raw in stdin.splitlines():
        cols = raw.split("\t")
        if len(cols) < 3 or not cols[0] or not cols[1] or not cols[2]:
            continue
        path, branch, label = cols[0], cols[1], cols[2]
        own = branch_own(label, tre)
        if not own:
            continue
        lines = log_lines(STAGE, f"refs/heads/{branch}", cherry=False, exclude_tickets=True)
        by_ticket = bucket(lines, tre, own)
        # 被列成別張票、owner 是這個工作區的 → 同一條線做的，算自己的
        for t in others_of(by_ticket, own):
            if same_line_owner(owner_of(t, path, f"refs/heads/{branch}"), path, branch):
                own.add(t)
        by_ticket = bucket(lines, tre, own)
        others = others_of(by_ticket, own)
        if others:
            print(f"{path}\t{summary(by_ticket, others)}")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--brief":
        brief(sys.stdin.read())
        return
    if not args or args[0] in ("-h", "--help"):
        sys.exit(__doc__)
    ref, own = args[0], set(args[1:])
    lines, by_ticket = group(STAGE, ref, own, cherry=True, exclude_tickets=True)
    print(f"[branch-tickets] {ref} 比 {STAGE} 多 {len(lines)} 個 commit（不含 tickets/），分屬 {len(by_ticket)} 張票：")
    others = others_of(by_ticket, own) if own else []
    for t, ls in sorted(by_ticket.items(), key=lambda kv: -len(kv[1])):
        mark = "  ← 別張票" if t in others else ""
        print(f"  {t}：{len(ls)} 個{mark}")
    if not own:
        print("  ⚠ 沒給自己的票號，沒辦法分辨哪些是別張票——請加上這條分支的票號重跑")
    if others:
        print(f"  這條分支會一起帶上 {others}：合之前先確認那幾張是同一條線、已上 stage，還是要一起併。")
    sys.exit(1 if others else 0)


if __name__ == "__main__":
    main()
