#!/usr/bin/env bash
# PreToolUse hook（matcher: Bash）：「檢查指令不准接管線」閘門（源專案 v4.90.0）。
#
# 擋的是這種寫法：
#     make check | tail -3
#     npm test 2>&1 | grep -E "FAIL|passed"
#     docker compose exec web sh -c "pytest -q" | tail -5
# 管線的結束碼是**最後一段**的（tail／head／grep 幾乎永遠成功），檢查失敗時整行仍然回報成功，
# 畫面上又只剩最後幾行，看起來像過了。源專案一個月內兩次因此把沒過的東西推上去、到 CI 才紅；
# 「檢查要看到通過才算過」這條文字規則早就有，仍然再犯，所以改用機器擋。
#
# 哪些算「檢查指令」：`scripts/framework-config.sh` 的 NO_PIPE_COMMANDS
# （源專案把自己的格式檢查工具寫死在腳本裡，這裡改成可設定）。一筆寫指令開頭的幾個詞即可：
#     "npm test"   → `npm test`、`npm test -- --ci` 都算；`npm run build` 不算
#     "make check" → make 的目標不看順序：`make -C sub check`、`make check fix=1` 都算
#     "pytest"     → `pytest -q`、`/usr/local/bin/pytest`、`python3 -m pytest` 都算
# 空陣列（或設定檔裡沒有這個變數）＝這道閘門不擋任何指令。
#
# 判斷方式（只看指令字串）：
#   把指令切成一段一段的簡單指令，凡是「檢查指令」那一段的輸出**進了管線**就擋：
#   自己後面接 |，或包在括號、大括號、迴圈、if 裡而整組收尾之後接 |
#   （`(cd sub && make check) 2>&1 | tail`、`{ make check; } | tail`）。
#   包在 docker／sh -c／env／timeout 這類包裝裡跑的也算。
#   只是**提到**這些字的指令不擋（`grep "make check" Makefile | head`、commit 訊息、註解、
#   heredoc 的內文）。`||`（失敗時接著做）不是管線，不擋；輸出導到檔案（`> out.txt 2>&1`）不擋。
#
# 跟源專案不同的地方（模板內補的；每一條都拿源專案的 hook 實際餵過指令確認）：
#   ・註解先拿掉再解析。源專案的寫法遇到引號外的 `#`（連沒加引號的 `${#arr[@]}`、網址裡的 `#` 也算）
#     會把後面每一行都當成註解，「註解一行、下一行檢查接管線」整條看不到。
#   ・heredoc 的內文先拿掉：內文裡的撇號會讓整條指令解析不了，退回逐行比對之後，
#     只剩「檢查指令寫在行首」的那一種擋得到。
#   ・整組（括號、大括號、迴圈、if、case）收尾之後才接管線也算。
#   ・包裝後面先出現 pip／install／grep 這類詞就不當成在跑檢查（源專案會把
#     `uv pip install <工具名> | tail` 擋下來）。
#
# 邊界（誠實聲明）：
#   ・`set -o pipefail` 之下接管線其實不會吞掉失敗，這裡照樣擋——規則只有一條比較不會記錯。
#   ・指令解析不了（引號不成對）時退回逐行比對，可能漏擋，不會誤擋到無法工作。
#   ・先存成變數或函式再接管線、用反引號或雙引號裡的 $( ) 包起來、交給 eval／ssh 的寫法認不出來，會漏擋。
#   ・比對只看指令名稱的最後一段：別的資料夾裡同名的腳本也會被當成同一支。
#   ・包裝（docker／env／xargs／uv…）後面的詞只要對得上就算在跑檢查。前面先出現 pip／install／grep
#     這類詞就不算（`uv pip install pytest | tail`、`… | xargs grep -l pytest | head` 放行，
#     清單見下面的 NOT_RUNNING）；清單以外、把檢查指令的名字當參數傳的寫法仍會被誤擋。
#   ・沒有逃生口：被擋到（含誤擋）時照訊息改成「導到檔案再讀」，能做到一樣的事。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 先把 stdin 讀完再做任何判斷：還沒讀就結束，送資料進來的那一端會收到 broken pipe
PAYLOAD=$(cat)

# 陣列先給預設值再讀設定檔：設定檔沒有這個變數時，bash 3.2 在 set -u 下連 ${#NAME[@]} 都會報錯
NO_PIPE_COMMANDS=()
# shellcheck disable=SC1091
[ -f "$ROOT/scripts/framework-config.sh" ] && . "$ROOT/scripts/framework-config.sh"
[ "${#NO_PIPE_COMMANDS[@]}" -gt 0 ] || exit 0
LIST=$(printf '%s\n' "${NO_PIPE_COMMANDS[@]}")

read -r -d '' PY <<'PYEOF' || true
import json, os, re, shlex, sys

try:
    cmd = (json.load(sys.stdin).get("tool_input") or {}).get("command") or ""
except Exception:
    sys.exit(0)
if not isinstance(cmd, str) or not cmd.strip():
    sys.exit(0)

# NO_PIPE_COMMANDS：[(原文, 拆好的詞)]
ENTRIES = []
for line in os.environ.get("NO_PIPE_LIST", "").splitlines():
    try:
        toks = shlex.split(line)
    except ValueError:
        toks = line.split()
    if toks:
        ENTRIES.append((line.strip(), toks))
if not ENTRIES:
    sys.exit(0)

# 連在一起的標點要拆回一個一個運算子；長的排前面（`>|` 是覆寫導向，不是 `>` 加 `|`）
OPS = ["&&", "||", ";;", "|&", ">|", ">>", "<<", ">&", "<&", "&>", "<>",
       "(", ")", ";", "|", "&", ">", "<"]
SEPS = {";", "&&", "||", "&", "(", ")", ";;", "|", "|&"}  # 一段指令到這裡結束
PIPES = {"|", "|&"}
REDIRECTS = {">", ">>", "<", ">&", "<&", "&>", ">|", "<>"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
# 後面才接真正指令的包裝（`command` 不列：`command -v pytest | head` 是在問路徑，不是在跑）
WRAPPERS = SHELLS | {"docker", "docker-compose", "podman", "env", "timeout", "sudo", "xargs", "nice",
                     "nohup", "uv", "uvx", "poetry", "pipx", "pipenv", "npx"}
# 包裝後面先遇到這些詞，就知道再後面的名字只是參數（裝套件、找字、印字），不是在跑檢查：
# `uv pip install pytest | tail`、`git ls-files | xargs grep -l pytest | head`
NOT_RUNNING = {"pip", "pip3", "install", "uninstall", "add", "remove", "show", "list", "search", "info",
               "grep", "egrep", "fgrep", "rg", "ag", "echo", "printf", "cat", "ls", "find", "which", "type",
               "man", "head", "tail", "wc", "sed", "awk", "apt", "apt-get", "brew", "apk", "yum", "dnf"}
LEAD = {"then", "else", "elif", "do", "!", "time"}  # 後面才是指令的關鍵字
OPENERS = {"{", "if", "while", "until", "for", "case", "select"}  # 開一組
CLOSERS = {"}", "fi", "done", "esac"}  # 收一組
KEYWORDS = LEAD | {"{", "if", "while", "until"}  # 判斷「這一段是不是檢查指令」前先拿掉


def drop_heredocs(text):
    """heredoc 的內文是資料不是指令：整段拿掉（找得到結尾那一行才拿，找不到就當作不是 heredoc）。"""
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        out.append(lines[i])
        m = re.search(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", lines[i])
        if m:
            for j in range(i + 1, len(lines)):
                if lines[j].strip() == m.group(2):
                    i = j
                    break
        i += 1
    return "\n".join(out)


def strip_comments(text):
    """拿掉 shell 註解（引號外、一個詞開頭的 # 到行尾）；引號裡的 # 不動。"""
    out, quote, i, n = [], "", 0, len(text)
    while i < n:
        c = text[i]
        if quote == "'":
            if c == "'":
                quote = ""
        elif c == "\\" and i + 1 < n:
            out.append(c)
            out.append(text[i + 1])
            i += 2
            continue
        elif quote == '"':
            if c == '"':
                quote = ""
        elif c in "'\"":
            quote = c
        elif c == "#" and (i == 0 or text[i - 1] in " \t\n;&|("):
            while i < n and text[i] != "\n":
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def split_ops(tok):
    """shlex 會把連在一起的標點當成一個 token（`)|`、`;(`）：拆回一個一個運算子。"""
    out = []
    while tok:
        for op in OPS:
            if tok.startswith(op):
                out.append(op)
                tok = tok[len(op):]
                break
        else:
            out.append(tok)
            break
    return out


def split(text):
    """切成 [(這一段的詞, 後面接的運算子)]；解析不了回傳 None。"""
    text = drop_heredocs(text)
    text = strip_comments(text)
    text = re.sub(r"\\\n", " ", text).replace("\n", " ; ")
    lex = shlex.shlex(text, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""  # 註解上面已經拿掉；留著預設值的話，`${#arr[@]}` 之後整行都會被當成註解吃掉
    try:
        toks = list(lex)
    except ValueError:
        return None
    segs, cur = [], []
    for tok in toks:
        parts = split_ops(tok) if tok and all(c in "();<>|&" for c in tok) else [tok]
        for t in parts:
            if t in SEPS:
                segs.append((cur, t))
                cur = []
            else:
                cur.append(t)
    segs.append((cur, ""))
    return segs


def norm(word):
    """指令名稱只看最後一段；python3／python3.12 都算 python，gmake 算 make。"""
    name = word.rsplit("/", 1)[-1]
    if re.match(r"^python[0-9.]*$", name):
        return "python"
    return "make" if name == "gmake" else name


def direct(words):
    """words[0] 就是指令本身：對得上 NO_PIPE_COMMANDS 的哪一筆，就回傳那一筆的原文。"""
    if not words:
        return None
    head = norm(words[0])
    for text, ent in ENTRIES:
        if norm(ent[0]) != head:
            continue
        if head == "make":
            if all(t in words[1:] for t in ent[1:]):
                return text
        elif words[1:len(ent)] == ent[1:]:
            return text
    if head == "python" and "-m" in words[1:]:
        return direct(words[words.index("-m", 1) + 1:])
    return None


def strip_prefix(words):
    """拿掉開頭的 shell 關鍵字與 VAR=值。"""
    words = list(words)
    while words and (words[0] in KEYWORDS or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0])):
        words.pop(0)
    return words


def cmd_strings(words):
    """交給 shell 跑的整串指令：sh -c "…"、bash -lc "…"、docker exec web sh -c "…"。
    只認 shell 後面的 -c；別的工具的 -c（grep -c、head -c）後面不是指令。"""
    out = []
    for i, w in enumerate(words):
        if norm(w) not in SHELLS:
            continue
        j = i + 1
        while j < len(words) and words[j][:1] in "-+":
            if words[j] in ("-o", "+o", "-O", "+O"):  # 這幾個選項後面還帶一個值
                j += 2
                continue
            if re.match(r"^-[A-Za-z]*c$", words[j]):
                if j + 1 < len(words):
                    out.append(words[j + 1])
                break
            j += 1
    return out


def is_check(words, depth=0):
    """這一段簡單指令本身是不是在跑檢查；是就回傳對到的那一筆。"""
    words = strip_prefix(words)
    hit = direct(words)
    if hit or not words or norm(words[0]) not in WRAPPERS:
        return hit
    # 包裝後面直接接指令（docker compose exec web pytest -q）
    for i in range(1, len(words)):
        if words[i] in NOT_RUNNING:
            break
        hit = direct(words[i:])
        if hit:
            return hit
    # 包裝後面是一整串指令字串（sh -c "pytest -q && echo ok"）
    if depth < 2:
        for w in cmd_strings(words):
            for seg, _ in split(w) or []:
                hit = is_check(seg, depth + 1)
                if hit:
                    return hit
    return None


def only_redirects(words):
    """這一段只有轉向（2>&1、> 檔案），沒有指令。空的也算。"""
    i = 0
    while i < len(words):
        if words[i].isdigit() and i + 1 < len(words) and words[i + 1] in REDIRECTS:
            i += 1
        elif words[i] in REDIRECTS and i + 1 < len(words):
            i += 2
        else:
            return False
    return True


def first_word(words):
    for w in words:
        if w not in LEAD:
            return w
    return ""


def piped_segments(segs):
    """哪幾段的輸出進了管線：自己後面接 |，或整組（括號、大括號、迴圈、if、case）收尾之後接 |。"""
    flags = [op in PIPES for _, op in segs]
    stack = []  # 還沒收尾的組：(種類, 組裡第一段的編號)
    for i, (words, op) in enumerate(segs):
        head = first_word(words)
        if head in CLOSERS:
            start = None
            while stack and start is None:
                kind, s = stack.pop()
                if kind != "(":
                    start = s
            if start is not None and op in PIPES:  # `} 2>&1 | tail`、`done | tail`
                for k in range(start, i):
                    flags[k] = True
        elif head in OPENERS:
            stack.append(("{", i))
        if op == "(":
            stack.append(("(", i + 1))
        elif op == ")" and stack and stack[-1][0] == "(":  # case 的 `a)` 不是括號收尾，不算
            _, s = stack.pop()
            nxt = segs[i + 1] if i + 1 < len(segs) else ([], "")
            if only_redirects(nxt[0]) and nxt[1] in PIPES:  # `) | tail`、`) 2>&1 | tail`
                for k in range(s, i + 1):
                    flags[k] = True
    return flags


def piped(text, depth=0):
    """回傳被接了管線的那一筆檢查指令；沒有就回傳空字串；解析不了回傳 None。"""
    segs = split(text)
    if segs is None:
        return None
    for (words, _), flagged in zip(segs, piped_segments(segs)):
        if flagged:
            hit = is_check(words)
            if hit:
                return hit
        # 引號裡自己又接了管線：sh -c "make check | tail -1"
        inner = strip_prefix(words)
        if depth < 2 and inner and norm(inner[0]) in WRAPPERS:
            for w in cmd_strings(inner):
                hit = piped(w, depth + 1)
                if hit:
                    return hit
    return ""


hit = piped(cmd)
if hit is None:
    # 解析不了：逐行看「行首就是檢查指令，後面接單獨一個 |」
    hit = ""
    lines = drop_heredocs(cmd).splitlines()
    for text, ent in ENTRIES:
        words = [ent[0].rsplit("/", 1)[-1]] + ent[1:]
        pat = re.compile(r"^\s*(?:\S*/)?" + r"\s+".join(re.escape(w) for w in words)
                         + r"(?:\s(?:[^|;&\n]|>&|&>)*)?\|(?!\|)")
        if any(pat.search(line) for line in lines):
            hit = text
            break
if hit:
    print("BLOCK")
    print(hit)
PYEOF

VERDICT=$(printf '%s' "$PAYLOAD" | NO_PIPE_LIST="$LIST" python3 -c "$PY" 2>/dev/null || true)
[ "$(printf '%s\n' "$VERDICT" | sed -n '1p')" = "BLOCK" ] || exit 0
HIT=$(printf '%s\n' "$VERDICT" | sed -n '2p')

cat >&2 <<EOF
[check-pipe-gate] 擋下：檢查指令（${HIT}）的輸出接了管線。

管線的結束碼是最後一段的（tail／head／grep 幾乎永遠成功），檢查失敗時整行仍然回報成功，
畫面上也只剩最後幾行——看起來像過了，其實沒過。

請直接跑、不接管線。要留完整輸出，或只想看尾段，就先導到檔案再讀：
  ${HIT} > /tmp/check.txt 2>&1; echo "exit=\$?"
  tail -40 /tmp/check.txt
（哪些指令算檢查指令：scripts/framework-config.sh 的 NO_PIPE_COMMANDS）
EOF
exit 2
