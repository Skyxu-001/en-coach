#!/usr/bin/env python3
"""en-coach: practise English while you use Claude Code.

Runs as an async UserPromptSubmit hook. It reads the prompt you just sent,
asks a small, cheap model to correct it or teach the phrases you could not
say in English, and writes the result to two places:

  * a per-session status file that the status line prints (for you to see)
  * an error log, errors.jsonl (for you to review later)

It NEVER writes to stdout. Whatever a hook prints can end up in Claude's
context, so the coaching stays invisible to Claude and its answers are exactly
what they would be without this hook. Every failure exits silently with 0.

Standard library only, Python 3.9+, macOS / Linux / Windows.
"""

import json
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------- settings ----------
MAX_PROMPT_CHARS = 8000       # longer than this is almost always a summary or a huge paste
MAX_PROSE_CHARS = 400         # cap on what is actually sent to the model
MIN_CHARS, MIN_WORDS = 12, 4
MIN_CJK = 6                   # Chinese has no spaces, so count characters instead of words
MAX_ITEMS = 3                 # FIX lines kept (the display width trims again)
MAX_GAPS = 3                  # GAP lines kept
MAX_REWRITES = 2              # rewrite lines kept (the log keeps both; the status line shows 1)
MAX_LINES = 3                 # status line height (the log is not limited)
API_TIMEOUT_SECONDS = 12

# Any OpenAI-compatible chat-completions endpoint works.
# The default is DeepSeek because it is fast and costs about $0.10 a month here.
BASE_URL = os.environ.get("EN_COACH_BASE_URL", "https://api.deepseek.com").rstrip("/")
MODEL = os.environ.get("EN_COACH_MODEL", "deepseek-flash")
ENDPOINT = BASE_URL + "/chat/completions"

DATA_DIR = Path(os.environ.get("EN_COACH_DATA_DIR") or (Path.home() / ".claude" / "english"))
ERRORS_FILE = DATA_DIR / "errors.jsonl"

KINDS = {"verb-form", "countability", "article",
         "preposition", "word-choice", "spelling"}

SYSTEM_PROMPT = """\
You coach a Chinese native-speaker software engineer on English, inside their
terminal. Output at most 3 GAP lines, at most 3 FIX lines, and at most 2 R lines.

=== GAP: teach a phrase they probably cannot produce ===
G|<Chinese fragment>|<English for THAT FRAGMENT ONLY>

Rules, in order of importance:
1. The Chinese fragment MUST be SHORT: 2-8 characters. Quote it verbatim.
2. The English MUST render ONLY that fragment. It is a phrase, not a sentence.
   <example note="format only - NEVER copy these words into your output">
   WRONG: G|<long fragment>|<a whole translated sentence>
   RIGHT: G|<short fragment>|<a short phrase>
   </example>
3. SKIP anything an intermediate learner already says fluently. Never teach:
   帮我 好的 行 我想 我觉得 这个 那个 然后 但是 可以吗 是不是 谢谢
   我尝试 我试了 没反应 你看 问一下
4. Prefer: vivid verbs, technical collocations, idiomatic connectors.
   Good targets: 梳理/复现/兜底/踩坑/落地/闪退/卡住/绕过/收敛/对齐/联调
5. Give 2-3 alternatives separated by " / " whenever they genuinely differ in
   register or nuance: 普及 -> spread / popularize / get across.
   One rendering is fine when only one fits. Do NOT pad with near-duplicates.
6. If nothing in the message clears bar 3, emit NO GAP line at all.
   Emitting nothing is correct and expected for ordinary messages.

=== FIX: correct a real error ===
F|<kind>|<2-5 words copied verbatim>|<those same words, corrected>

1. Quote 2-5 words, enough to see the error in context.
   Not just the single wrong word: give it a neighbour or two.
2. Correct ONLY the error. NEVER change the user's meaning or word choice.
   Changing "run ..." to "test ..." is forbidden - those mean different things.
3. The quoted words MUST be English text from the input. Never quote Chinese
   in a FIX line - Chinese belongs in a GAP line.
4. <kind> must be the MOST SPECIFIC match:
   spelling      misspelled word            similiar -> similar
   verb-form     tense, agreement, modal+base, passive, gerund/infinitive
                 I fix -> I fixed | did it pushed -> was it pushed
                 could works -> could work | who write -> who wrote
                 like use -> likes using
   countability  plural/uncountable         softwares -> software
   article       a / an / the               a error -> an error
   preposition   wrong or missing prep      regarding to -> regarding
                 logging this mac -> logging into this mac
   word-choice   ONLY when none of the above fits
5. STRICTLY IGNORE (normal in a terminal, never report):
   code, file paths, URLs, variable names, tech abbreviations,
   lowercase sentence starts, lowercase "i", missing final punctuation.
6. Never emit a FIX whose correction differs only in letter case.
7. Every line you output must be grounded in the user's actual message.
   Never emit a line about words that are not in it.

=== R: same meaning, more natural English (additive) ===
R|<span copied verbatim, 4-16 words>|<how a native engineer would put it, <=20 words>

Use R when the English is GRAMMATICAL but reads as translated: Chinese word
order, a verb that technically works but no engineer would use, or wording so
vague a colleague would have to ask what you meant.

1. Keep their meaning EXACTLY. Never add information they did not express.
2. Give 2-3 alternatives separated by " / " when they differ in nuance.
3. NEVER emit an R whose only change is something an F line already fixes.
   If fixing the F errors alone would produce your R text, the R is worthless.
4. NEVER emit an R that just repeats a G line's English.
5. Do NOT "upgrade" plain correct English merely to sound fancier.

R is ADDITIVE and OPTIONAL. Decide G and F first, exactly as you would if this
section did not exist, then consider one R. Skipping R is fine; skipping a G or
F you would otherwise emit is NOT. The restraint in rule 5 applies to R alone.

If nothing is worth teaching, output exactly: NONE
Output only G|, F| and R| lines, nothing else."""

# ---------- line filters ----------
# Code keywords are matched CASE-SENSITIVELY and only when real code structure
# follows. An early version used re.I and a bare \b, so "Let me try again" was
# taken for JavaScript's `let` and the whole sentence silently vanished.
# Let / If / For / Try / Return / From are among the most common sentence starts.
CODE_RE = re.compile(r"""(
      ^\s*(def|class|function)\s+\w+\s*[(:]       # def foo( / class Bar:
    | ^\s*import\s+[\w.]+\s*$                     # import os
    | ^\s*from\s+[\w.]+\s+import\b                # from x import y
    | ^\s*(const|let|var)\s+\w+\s*=               # const x =
    | ^\s*(if|while|for|switch|catch)\s*\(        # if (
    | ^\s*(return|await|throw|yield)\s+\w+\s*[({\[]   # return foo(
    | ^\s*(public|private|protected|package|static)\s+\w+\s*[({]
    | ^\s*(else|try|finally|do)\s*[{:]\s*$        # try: / else {
    | ^\s*@\w+                                    # decorators / annotations
    | =>\s*[{(]                                   # arrow functions
)""", re.X)

NOISE_RE = re.compile(r"""(
      ^\s*[\[\{\}\]]                            # JSON / array lines
    | ^\s*[\w.]+\s*[:=]\s*[\[\{"']              # assignments / config
    | \d{4}-\d{2}-\d{2}T\d{2}:\d{2}             # ISO timestamps
    | \b\d{2}:\d{2}:\d{2}[.,]\d+                # log timestamps
    | ^\s*(at|File)\s+["\w./\\-]+[:(]\d+        # stack frames
    | \.(py|js|ts|tsx|go|rs|java|rb|sh|json|ya?ml|toml|log|txt):\d+
    | ^\s*[$%#>]\s                              # shell prompt at line start
    | ^\s*[\w.-]+@[\w.-]+\s*[:~]                # user@host: or user@host ~
    | [~/][\w./-]*\s+[$%#]\s+\S                 # ... ~ % cmd (prompt mid-line)
    | ^\s*[-+]{3}\s | ^\s*@@\s                  # diff header / hunk
    | ^\s*[|+][-=+|\s]{6,}                      # table borders
    | ^\s*[✎↳↻⏵]            # this tool's own output and the CC footer.
                                                # People paste their screen; without this
                                                # the model just repeats last turn's tip.
)""", re.X | re.I)


# ---------- redaction ----------
# Applied to the text BEFORE it is sent to the API, and again to everything
# written to errors.jsonl. Anything you paste into a prompt, including a key,
# would otherwise leave your machine and land in the log. Deliberately narrow:
# over-redacting destroys the context that makes the coaching useful.
_SECRET_SUBS = [
    # scheme://user:password@host
    (re.compile(r"\b([a-z][a-z0-9+.\-]*://[^\s:/@]+):[^\s@/]+@", re.I), r"\1:<REDACTED>@"),
    # "my password is hunter2", "密码是 hunter2"
    # Only when the value looks like a password (has a digit or symbol), so
    # "the password is wrong" / "密码是错的" are still coached normally.
    (re.compile(r"(?i)\b(password|passwd|passcode|pwd)(\s+(?:is|was))\s+"
                r"(?=[^\s]*[0-9!@#$%^&*_+=~-])[^\s,;]{4,}"), r"\1\2 <REDACTED>"),
    (re.compile(r"(密码|口令|密钥)(\s*(?:是|为|[:：]))\s*[\x21-\x7e]{4,}"), r"\1\2<REDACTED>"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "<REDACTED-KEY>"),
    (re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,}"), "<REDACTED-TOKEN>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "<REDACTED-TOKEN>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<REDACTED-AWS>"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"), "<REDACTED-SLACK>"),
    (re.compile(r"\bAIza[A-Za-z0-9_\-]{30,}"), "<REDACTED-GCP>"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
     "<REDACTED-JWT>"),
    (re.compile(r"-----BEGIN[^-\n]*PRIVATE KEY-----"), "<REDACTED-PRIVATE-KEY>"),
    # key = value / "token": "..." style assignments
    (re.compile(r"(?i)\b(api[_\-]?key|access[_\-]?token|auth[_\-]?token|token|secret"
                r"|password|passwd|pwd|bearer)\b(\s*[:=]\s*)"
                r"[\"']?[^\s\"',;]{8,}"), r"\1\2<REDACTED>"),
]
# Bare high-entropy strings: 32+ chars mixing upper, lower and digits.
# Lower-case hex (git hashes) and dashed UUIDs are left alone on purpose.
_HIGH_ENTROPY = re.compile(r"\b(?=[A-Za-z0-9_\-]{32,}\b)"
                           r"(?=[^\s]*[a-z])(?=[^\s]*[A-Z])(?=[^\s]*\d)"
                           r"[A-Za-z0-9_\-]{32,}\b")


def redact(text):
    for pat, repl in _SECRET_SUBS:
        text = pat.sub(repl, text)
    return _HIGH_ENTROPY.sub("<REDACTED-SECRET>", text)


def cjk_count(s):
    return sum(1 for c in s if "一" <= c <= "鿿")


def has_content(s):
    """Is this long enough to be a sentence? Chinese counts characters, English
    counts words. Using split() alone would drop a whole Chinese sentence as
    a single "word"."""
    return cjk_count(s) >= MIN_CJK or len(s.split()) >= MIN_WORDS


# Log levels and command lines: CASE-SENSITIVE, and kept in their own regex.
#
# These used to live in NOISE_RE, which has re.I, so everyday sentences starting
# with error / warning / info / debug / trace / fatal or Go / Git / Node / SSH /
# Curl were silently dropped. Engineers say those words all day.
#
# The costs are asymmetric: wrongly dropping a sentence means you never get
# coached on it (and nothing tells you); letting a noisy line through costs a
# few tokens. So every rule below requires the line to really look like a log
# or a command, even if that lets a bare `git status` through.
#
# No inline `(?-i:...)` flags: they need Python 3.11+, and on an older
# interpreter the hook would die with re.error that main() quietly swallows.
LOG_CMD_RE = re.compile(r"""(
      \b(ERROR|WARN|WARNING|INFO|DEBUG|TRACE|FATAL)\b     # log levels only in capitals
    | [\[\(](error|warn|warning|info|debug|trace|fatal)[\]\)]   # or in brackets
    | ^\s*(npm|pip|uv|kubectl|scp|docker)\s+\w            # not English words: be loose
    | ^\s*(git|go|node|curl|ssh|brew|cargo|python3?)\s+\S*[-/.=]
                                                # English words: need - / . = in the args
    | ^\s*(git|go|node|curl|ssh|brew|cargo|python3?)\s+\w[\w-]*\s+[-/]
                                                # or subcommand + flag (git commit -m ...)
)""", re.X)                                     # note: no re.I


def extract_prose(text):
    """Strip logs / code / stack traces and keep natural language.
    Returns (prose, dropped_line_count)."""
    kept, dropped = [], 0
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if (CODE_RE.search(line) or NOISE_RE.search(line)
                or LOG_CMD_RE.search(line)):
            dropped += 1
            continue
        letters = sum(c.isalpha() for c in s)
        if letters < len(s) * 0.5 or not has_content(s):
            dropped += 1
            continue
        kept.append(s)
    return " ".join(kept)[:MAX_PROSE_CHARS], dropped


def cjk_ratio(text):
    """Share of Chinese, with each character weighted like three Latin letters."""
    cjk = cjk_count(text)
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    if not cjk and not latin:
        return 0.0
    return cjk / (cjk + latin / 3 + 1e-9)


# ---------- was this typed by a human? ----------
def looks_injected(transcript_path, prompt):
    """True when the transcript marks this prompt as injected by the harness
    rather than typed by you. Returns False whenever unsure."""
    if not transcript_path or not isinstance(transcript_path, str):
        return False
    try:
        p = Path(transcript_path)
        size = p.stat().st_size
        with p.open("rb") as f:
            f.seek(max(0, size - 64 * 1024))
            blob = f.read().decode("utf-8", "replace")
    except Exception:
        return False

    target = prompt.strip()
    for line in reversed(blob.split("\n")):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue  # reading from the middle can cut the first line
        if not isinstance(e, dict) or e.get("type") != "user":
            continue
        c = (e.get("message") or {}).get("content")
        if isinstance(c, str):
            text = c.strip()
        elif isinstance(c, list):
            parts = [x.get("text", "") for x in c
                     if isinstance(x, dict) and x.get("type") == "text"]
            text = "".join(parts).strip()
            if any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
                if text == target:
                    return True
        else:
            continue
        if text != target:
            continue
        return bool(e.get("isMeta") or e.get("isSidechain")
                    or (e.get("userType") and e.get("userType") != "external"))
    return False


# ---------- gate ----------
# Messages injected by the harness also fire UserPromptSubmit: background task
# notifications, messages from other sessions, teammates and sub-agents. They
# are not yours, and coaching them floods the log (one real session had ~620 of
# 650 logged items come from other sessions' reports).
# Whole blocks are removed rather than skipping the prompt, so your own words in
# the same message still get coached. Only these tag names, and only properly
# closed pairs: a real message that starts with <div> or merely mentions a tag
# must survive. Replaced by a space, not a newline, because extract_prose judges
# length per line and splitting your sentence in two could drop both halves.
_INJECTED_TAGS = ("task-notification|cross-session-message|teammate-message"
                  "|agent-message|system-reminder")
INJECTED_BLOCK_RE = re.compile(r"<(%s)\b[^>]*>.*?</\1>" % _INJECTED_TAGS, re.S)


def strip_injected(prompt):
    return INJECTED_BLOCK_RE.sub(" ", prompt)


def gate(payload):
    """Return (prose, ratio), or None to skip this prompt."""
    if os.environ.get("EN_COACH_RUNNING"):
        return None
    prompt = payload.get("prompt")
    if not prompt or not isinstance(prompt, str):
        return None
    stripped = prompt.strip()
    if len(prompt) > MAX_PROMPT_CHARS:
        return None
    if stripped.startswith(("/", "!", "#", "<command-message>", "<local-command")):
        return None

    prose, _ = extract_prose(strip_injected(prompt))
    if len(prose) < MIN_CHARS or not has_content(prose):
        return None
    if looks_injected(payload.get("transcript_path"), prompt):
        return None
    return prose, cjk_ratio(prose)


# ---------- model call ----------
def api_key():
    """EN_COACH_API_KEY first. DEEPSEEK_API_KEY only when the endpoint really is
    DeepSeek: never send one provider's key to another host. Values that are
    still encrypted (dotenvx style "encrypted:...") are refused: sending one
    would only get a 401 and leak the ciphertext for nothing."""
    names = ["EN_COACH_API_KEY"]
    if "deepseek.com" in BASE_URL:
        names.append("DEEPSEEK_API_KEY")
    for name in names:
        k = (os.environ.get(name) or "").strip()
        if k and not k.startswith("encrypted:"):
            return k
    return None


def build_request_body(prose):
    body = {
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": prose}],
        "temperature": 0,
        "max_tokens": 320,   # R lines are longer than G/F
    }
    # DeepSeek's flash model thinks by default and would burn every token on
    # reasoning, returning nothing before the timeout. Other providers may reject
    # the unknown field, so only send it to DeepSeek.
    if "deepseek.com" in BASE_URL:
        body["thinking"] = {"type": "disabled"}
    return body


def ask_model(prose):
    key = api_key()
    if not key:
        return ""
    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(build_request_body(prose)).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=API_TIMEOUT_SECONDS) as r:
        d = json.load(r)
    return d["choices"][0]["message"]["content"].strip()


# ---------- parsing ----------
# Model text goes straight to your terminal; strip control characters so a
# stray escape sequence can't redraw or recolour the screen.
_CONTROL_CHARS = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]")


def parse(raw, prose):
    """Turn model output into items and drop hallucinated or empty ones."""
    items = []
    if not raw or raw.strip().upper().startswith("NONE"):
        return items
    raw = _CONTROL_CHARS.sub("", raw)
    low = prose.lower()
    for line in raw.split("\n"):
        line = line.strip().strip("`")
        if not line or "|" not in line:
            continue
        parts = [p.strip().strip('"').strip("'") for p in line.split("|")]
        tag = parts[0].upper()

        if tag == "G" and len(parts) >= 3:
            zh, en = parts[1], parts[2]
            if not zh or not en or zh == en:
                continue
            if zh not in prose:                    # hallucinated: not in what you wrote
                continue
            items.append({"type": "gap", "zh": zh, "en": en})

        elif tag == "F" and len(parts) >= 4:
            kind, orig, fix = parts[1].lower(), parts[2], parts[3]
            if not orig or not fix:
                continue
            if cjk_count(orig):                    # Chinese belongs in GAP, not FIX
                continue
            if orig.lower() == fix.lower():        # case-only change: noise
                continue
            if orig.lower() not in low:            # hallucinated
                continue
            if kind not in KINDS:
                kind = "word-choice"
            items.append({"type": "fix", "kind": kind, "orig": orig, "fix": fix})

        elif tag == "R" and len(parts) >= 3:
            orig, better = parts[1], parts[2]
            if not orig or not better or orig == better:
                continue
            if orig.lower() not in low:            # hallucinated
                continue
            items.append({"type": "rewrite", "orig": orig, "fix": better})

    return _cap(_drop_worthless_rewrites(items))


def _norm(s):
    """Letters and digits only, lower-cased, for comparisons."""
    return "".join(c.lower() for c in s if c.isalnum())


def _cap(items):
    """Apply the per-type quotas AFTER de-duplication.

    The quotas used to be counted while scanning, so a rewrite that
    _drop_worthless_rewrites() later deleted had already used up the only slot,
    and a genuinely useful rewrite after it never got in. Order is preserved:
    filter, then truncate, never re-rank.
    """
    seen = {"gap": 0, "fix": 0, "rewrite": 0}
    quota = {"gap": MAX_GAPS, "fix": MAX_ITEMS, "rewrite": MAX_REWRITES}
    kept = []
    for it in items:
        t = it["type"]
        if seen[t] >= quota[t]:
            continue
        seen[t] += 1
        kept.append(it)
    return kept


def _drop_worthless_rewrites(items):
    """Drop rewrites that teach nothing beyond the FIX lines.

    Models love to copy the whole sentence with only the FIX already applied,
    e.g. `The test is pass, so ...` -> `The test passed, so ...`.
    Test: apply every FIX to the rewrite's original; a suggestion equal to that
    adds nothing. Same for a suggestion that only repeats a GAP's English.
    Checked per " / " alternative: the model often puts the worthless one first
    (`without losing my changes / while keeping my changes`), and since only the
    first alternative is shown, it has to go. The rewrite is dropped only when
    no alternative is left.
    """
    fix_pairs = [(i["orig"], i["fix"]) for i in items if i["type"] == "fix"]
    gap_ens = {_norm(i["en"]) for i in items if i["type"] == "gap"}
    kept = []
    for it in items:
        if it["type"] == "rewrite":
            patched = it["orig"]
            for fo, ff in fix_pairs:
                patched = patched.replace(fo, ff)
            worthless = {_norm(patched)} | gap_ens
            alternatives = [a.strip() for a in it["fix"].split(" / ") if a.strip()]
            useful = [a for a in alternatives if _norm(a) not in worthless]
            if not useful:
                continue
            it = dict(it, fix=" / ".join(useful))
        kept.append(it)
    return kept


# ---------- output ----------
R, G, Y, X = "\033[31m", "\033[32m", "\033[33m", "\033[0m"
# Red marks the side you should LEARN, green is what you wrote. The first version
# had "wrong = red, right = green", and the eye landed on your own mistake while
# the correct phrase faded into the background. Red here means "look here".
# Never use dim (\033[2m): on many terminal themes it is too grey to read.
MINE, LEARN = G, R

# Between items: a heavy vertical bar. Alternatives inside one item use " / ",
# and a slanted slash next to an upright bar reads as a different level, so
# `A -> x / y  ┃  B -> z` is clearly two items, not three.
SEP = f"  {Y}┃{X}  "


def vwidth(s):
    s = re.sub(r"\033\[[0-9;]*m", "", s)
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def term_width(session, default=78):
    """Terminal columns, used to decide how many items fit on one line.

    Claude Code only promises COLUMNS to the status line command, not to hooks.
    So: the environment first, then the width the bundled status line saved
    last time it ran, then a safe 78. Four columns are kept spare because
    Claude Code indents each status line.
    """
    try:
        n = int(os.environ.get("COLUMNS") or 0)
    except ValueError:
        n = 0
    if n < 40:
        try:
            n = int((DATA_DIR / f"width-{session}.txt").read_text(encoding="utf-8").strip() or 0)
        except Exception:
            n = 0
    return n - 4 if n >= 40 else default


def render(items, budget=78):
    """Render 1-N lines. The leading symbol says what kind of line it is:

      ✎  something wrong, or Chinese you could not say in English
      ↳  continuation of the line above
      ↻  nothing wrong, but there is a more natural way to say it

    GAP and FIX items are short and are packed greedily by width: as many per
    line as fit. The rewrite gets its own last line and shows ONE suggestion:
    two sentences side by side means neither gets learned. Everything the model
    returned still goes to the log. When lines run out, GAP/FIX lose space
    first and the rewrite keeps its line.

    A single status line wider than the terminal is cut off, not wrapped, so
    width matters. Continuation lines cannot be indented with spaces because
    Claude Code strips leading whitespace, hence the visible ↳.
    """
    gaps = [i for i in items if i["type"] == "gap"]
    fixes = [i for i in items if i["type"] == "fix"][:MAX_ITEMS]
    rewrites = [i for i in items if i["type"] == "rewrite"][:1]

    # GAP first: "couldn't say it" is worth seeing more than "said it wrong".
    pieces = ([f"{MINE}{g['zh']}{X} → {LEARN}{g['en']}{X}" for g in gaps] +
              [f"{MINE}{f['orig']}{X} → {LEARN}{f['fix']}{X}" for f in fixes])

    packed, cur = [], []
    for piece in pieces:
        trial = cur + [piece]
        # The first item on a line is always accepted: if a single item is too
        # wide, letting Claude Code cut it beats showing an empty line.
        if cur and vwidth("✎ " + SEP.join(trial)) > budget:
            packed.append(cur)
            cur = [piece]
        else:
            cur = trial
    if cur:
        packed.append(cur)

    packed = packed[:max(0, MAX_LINES - len(rewrites))]

    lines = [("s", SEP.join(row)) for row in packed]
    for w in rewrites:
        best = w["fix"].split(" / ")[0]
        lines.append(("r", f"{MINE}{w['orig']}{X} → {LEARN}{best}{X}"))

    if not lines:
        return ""
    out = []
    for i, (kind, text) in enumerate(lines):
        mark = "↻" if kind == "r" else ("✎" if i == 0 else "↳")
        out.append(f"{Y}{mark}{X} {text}")
    return "\n".join(out)


def write_status(session, text):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / f"status-{session}.txt").write_text(text, encoding="utf-8")
        now = datetime.now().timestamp()
        for pattern in ("status-*.txt", "width-*.txt"):
            for f in DATA_DIR.glob(pattern):
                if now - f.stat().st_mtime > 86400:
                    f.unlink(missing_ok=True)
    except Exception:
        pass


def logging_enabled():
    return os.environ.get("EN_COACH_LOG", "1").strip().lower() not in ("0", "false", "no", "off")


def append_errors(items, session, cwd, sentence):
    if not items or not logging_enabled():
        return
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        name = Path(cwd).name if cwd else ""
        with ERRORS_FILE.open("a", encoding="utf-8") as f:
            for it in items:
                fields = {k: redact(v) if isinstance(v, str) else v for k, v in it.items()}
                rec = {"ts": ts, "session": session[:8], "cwd_name": name,
                       "sentence": redact(sentence)[:300], **fields}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------- main ----------
def read_payload():
    """Read the hook's JSON input, pinned to UTF-8.

    On Chinese Windows, Python decodes a pipe with the system code page (GBK).
    Claude Code sends UTF-8, so every Chinese prompt turned into mojibake, the
    model answered NONE, and nothing ever reached the log, with no error at all.
    """
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return json.load(sys.stdin)


def main():
    try:
        payload = read_payload()
    except Exception:
        return
    if not isinstance(payload, dict):
        return

    got = gate(payload)
    # The session id becomes part of a file name: keep it to safe characters.
    session = re.sub(r"[^A-Za-z0-9_-]", "_", str(payload.get("session_id") or "default"))[:64]
    if got is None:
        write_status(session, "")      # clear last turn's tip
        return

    prose, _ratio = got
    prose = redact(prose)              # secrets never leave the machine
    os.environ["EN_COACH_RUNNING"] = "1"
    try:
        raw = ask_model(prose)
    except Exception:
        write_status(session, "")
        return

    items = parse(raw, prose)
    write_status(session, render(items, term_width(session)))
    append_errors(items, session, payload.get("cwd", ""), prose)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass       # never get in the way of your work
    sys.exit(0)
