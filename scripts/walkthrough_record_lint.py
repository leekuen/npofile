#!/usr/bin/env python3
"""推 stage 前：票上每個 W 編號都要交代「走過」或「沒走」（源專案 v5.30.0）。

用法：python3 scripts/walkthrough_record_lint.py <遠端現況 sha> <要推的 sha>
      python3 scripts/walkthrough_record_lint.py --ref <分支或 commit>…   （源專案 v5.39.0）合流前先查：
        每個 ref 自己算 `git merge-base origin/stage <ref>`，範圍就是 merge-base..ref，判斷規則與推 stage 時完全相同；
        多個 ref 取最嚴的結束碼、各印各的。用 merge-base 而不是 origin/stage：分支落後 stage 時，stage 上別張票
        改過的票檔會出現在 origin/stage..分支 的差異裡，被當成這條分支要推的、讀的卻是分支上的舊版本。
        用法：`make walkthrough-lint ref="feature/AMY-12 feature/AMY-13"`（先 git fetch）。
      遠端 sha 全 0 或本機不認得 → 無法判斷範圍，檢查要推的 commit 裡全部符合資格的票（保守，同 ticket-lint）。
      兩種用法前面都可以加 `--since <YYYY-MM-DD>`（測試與一次性覆寫用，見下面「生效日」）。
結束碼：0 通過｜1 有 W 沒交代（擋）｜2 自己跑不起來（pre-push 只警告放行）。

為什麼（源專案的教訓）：一張票寫了「另外兩頁的同款元件一併檢查」，W1 只是為了過 ticket-lint 補的一行，
一頁都沒走就合進 stage。ticket-lint 只管「計畫」（W 有對應的驗收行），不管「結果」（走過沒有）。

規則：
  ・查哪幾張票：推送範圍裡**有改動到的票檔**（不從提交訊息抓票號：一個提交訊息寫好幾張票時，
    常常只抓得到第一張）；只留 created 在生效日（含）之後、狀態開發中或完成、
    〈這次可能會弄壞什麼〉有 W 編號的票（寫「不適用」的不查）。
  ・生效日：`--since` 參數 > 環境變數 TICKET_RULES_SINCE > scripts/framework-config.sh 裡的 TICKET_RULES_SINCE。
    留空或都沒設＝所有票都套用；有設的時候，沒填 created 的票不查（同 ticket-lint）。
  ・讀**被推的 commit** 裡的票檔，不讀工作樹（工作樹可能還有沒提交的改動，推出去的不是那一版）。
  ・每個 W，在〈開發備註〉或〈走查〉開頭的節裡要有其中一種：
      走過：行首「走查（真人眼看）／走查（HTTP 腳本）／走查（HTML 檢查）」，同一行寫出該 W；
      沒走：含「沒走的是」的那一行寫出該 W（user-walkthrough〈跳過之後怎麼做〉的三行格式）。
  ・W 編號整段比對：W1 不會被 W10 算成已交代；一行寫好幾個 W 逐個抽出。
"""
import os
import re
import subprocess
import sys

ZERO = "0" * 40
W_TOKEN = re.compile(r"(?<![A-Za-z0-9])W\d+(?!\d)")
EVIDENCE = re.compile(r"^走查（(?:真人眼看|HTTP ?腳本|HTML ?檢查)）")
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "framework-config.sh")


def since_from_config():
    """從 scripts/framework-config.sh 撈 TICKET_RULES_SINCE（Python 讀不了 bash 設定，用正則）。撈不到＝空字串。"""
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return ""
    # 同一個變數寫了兩次時 bash 以後面那次為準，這裡也取最後一筆
    found = re.findall(r"""^[ \t]*TICKET_RULES_SINCE=["']?([^"'#\s]*)""", text, re.M)
    return found[-1] if found else ""


def rules_since(cli_value):
    """回傳生效日（YYYY-MM-DD）；空字串＝所有票都套用。"""
    if cli_value is not None:
        value = cli_value
    elif "TICKET_RULES_SINCE" in os.environ:
        value = os.environ["TICKET_RULES_SINCE"]
    else:
        value = since_from_config()
    value = value.strip()
    if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        # 日期是用字串比大小的：格式不對會讓每張票都排在它前面、整條檢查靜靜關掉。
        # 不回結束碼 2（pre-push 遇到 2 只警告放行＝沒檢查），改用最嚴的那種算；ticket-lint 會因為同一個設定錯誤而紅。
        print(f"[walkthrough-record] ⚠️ TICKET_RULES_SINCE 格式錯誤（'{value}'），應為 YYYY-MM-DD 或留空"
              "——這次先當成「全部套用」", file=sys.stderr)
        return ""
    return value


def pop_since(args):
    """把 `--since <日期>`／`--since=<日期>` 從參數裡拿掉（只認 --ref 之前的），回傳 (日期或 None, 剩下的參數)。"""
    rest, since, i = [], None, 0
    while i < len(args):
        a = args[i]
        if a == "--ref":
            rest.extend(args[i:])
            break
        if a == "--since":
            if i + 1 >= len(args):
                raise ValueError("--since 後面要接日期（YYYY-MM-DD）")
            since = args[i + 1]
            i += 2
            continue
        if a.startswith("--since="):
            since = a[len("--since="):]
            i += 1
            continue
        rest.append(a)
        i += 1
    return since, rest


def git(*args):
    # core.quotePath=false 不能省：預設會把中文檔名跳脫成 \346… 加引號，一張票都對不到、整條靜靜放行
    r = subprocess.run(["git", "-c", "core.quotePath=false", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"git {' '.join(args)} 失敗")
    return r.stdout


def known(sha):
    return sha != ZERO and subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True).returncode == 0


def ticket_paths(remote, local):
    if known(remote):
        out = git("diff", "--name-only", "--diff-filter=d", remote, local, "--", "tickets/")
    else:
        out = git("ls-tree", "-r", "--name-only", local, "--", "tickets/")
    return [p for p in out.splitlines()
            if p.endswith(".md") and "/" not in p[len("tickets/"):] and not p.endswith("README.md")]


def clean(line):
    line = re.sub(r"^[ \t]*(?:[-*·][ \t]*)?(?:\[[ xX]\][ \t]*)?", "", line)
    return line.replace("`", "").strip()


def check(text, since=""):
    """回傳 (要查嗎, 沒交代的 W 清單)。since 空字串＝所有票都套用。"""
    fm = re.match(r"^---\n(.*?)\n---", text, re.S)
    meta = fm.group(1) if fm else ""
    created = (re.search(r"^created:\s*(\S+)", meta, re.M) or [None, ""])[1]
    status = (re.search(r"^status:\s*(\S+)", meta, re.M) or [None, ""])[1]
    if (since and created < since) or status not in ("開發中", "完成"):
        return False, []

    risk, covered, na = [], set(), False
    sec, in_comment = "", False
    for raw in text.splitlines():
        h = re.match(r"^(#+)[ \t]+(.*)", raw)
        if h:
            in_comment = False
            name = h.group(2)
            if name.startswith("這次可能會弄壞什麼"):
                sec = "risk"
            elif name.startswith(("開發備註", "走查")):
                sec = "record"
            elif len(h.group(1)) <= 2:
                sec = ""   # 〈開發備註〉底下的 ### 小標（根因、驗證…）仍算開發備註
            continue
        # HTML 註解整段跳過（範本說明裡就有「W1、W2…」）
        if in_comment:
            if "-->" in raw:
                in_comment = False
            continue
        if "<!--" in raw:
            if "-->" not in raw:
                in_comment = True
            continue
        line = clean(raw)
        if not line:
            continue
        if sec == "risk":
            if line.startswith("不適用"):
                na = True
            m = re.match(r"^W\d+(?!\d)", line)
            if m and m.group(0) not in risk:
                risk.append(m.group(0))
        elif sec == "record":
            if EVIDENCE.match(line) or "沒走的是" in line:
                covered.update(W_TOKEN.findall(line))
    if na or not risk:
        return False, []
    return True, [w for w in risk if w not in covered]


HELP = """[walkthrough-record] 在票的〈開發備註〉（或〈走查〉節）每個 W 補一種交代，commit 後再推：
    走過：走查（真人眼看）W1 訂單清單頁、W2 訂單明細頁：下拉選單打字選一次，選項完整
          （也可寫 走查（HTTP 腳本）／走查（HTML 檢查）；版面類的 W 用真人眼看，HTML 檢查看不到版面）
    沒走：⚠️ 走查未完成
          · 沒走的是：W2 訂單明細頁
          · 為什麼：…
          · 誰該補走：…
    寫了「沒走」的，要在問「上實機嗎？」的那一則開頭講出來（user-walkthrough〈跳過之後怎麼做〉）。
    批次合流時是別人的票：請那張票的負責人補，不要替他寫「沒走」。"""


def lint_range(remote, local, since=""):
    """回傳沒交代的 [(票檔, [W…])]；自己壞掉就丟例外。"""
    bad = []
    for p in ticket_paths(remote, local):
        ok, missing = check(git("show", f"{local}:{p}"), since)
        if ok and missing:
            bad.append((p, missing))
    return bad


def print_bad(bad):
    for p, missing in bad:
        print(f"  · {p[len('tickets/'):]}：{'、'.join(missing)}", file=sys.stderr)


def main_refs(refs, since=""):
    """合流前先查：每個 ref 自己算 merge-base（見檔頭）。"""
    worst = 0
    for ref in refs or ["HEAD"]:
        try:
            sha = git("rev-parse", "--verify", f"{ref}^{{commit}}").strip()
            base = git("merge-base", "origin/stage", sha).strip()
            bad = lint_range(base, sha, since)
        except Exception as e:  # noqa: BLE001 — 自己壞掉：這個 ref 沒有檢查，不當成通過
            print(f"[walkthrough-record] {ref}：跑不起來，沒有檢查（{e}）", file=sys.stderr)
            worst = max(worst, 2)
            continue
        if not bad:
            print(f"[walkthrough-record] {ref}：通過", file=sys.stderr)
            continue
        print(f"[walkthrough-record] ⛔ {ref}：這幾張票有 W 編號沒交代走過或沒走：", file=sys.stderr)
        print_bad(bad)
        worst = 1 if worst == 0 else worst
    if worst == 1:
        print(HELP, file=sys.stderr)
    return worst


def main(argv):
    try:
        cli_since, args = pop_since(argv[1:])
    except ValueError as e:
        print(f"[walkthrough-record] {e}", file=sys.stderr)
        return 2
    since = rules_since(cli_since)
    if args and args[0] == "--ref":
        return main_refs(args[1:], since)
    if len(args) != 2:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    remote, local = args[0], args[1]
    try:
        bad = lint_range(remote, local, since)
    except Exception as e:  # noqa: BLE001 — 自己壞掉不擋推送，交給 pre-push 印警告
        print(f"[walkthrough-record] 跑不起來：{e}", file=sys.stderr)
        return 2
    if not bad:
        return 0
    print("[walkthrough-record] ⛔ 這幾張票有 W 編號沒交代走過或沒走：", file=sys.stderr)
    print_bad(bad)
    print(HELP, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
