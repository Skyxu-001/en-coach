# Lessons learned

Notes from building and running en-coach every day for a few months.
Most of the bugs below were **silent**: nothing crashed, the coaching just got
quietly worse or stopped. That is why the test suite exists, and why each test
names the bug it guards against.

## Decisions

### Keep the lessons out of Claude's context

This was the one hard rule from day one. Some similar tools add the coaching to
Claude's reply, or ask Claude to do it. Then every lesson costs context, and
Claude's behaviour changes. en-coach writes to a status file and the status line
reads it. The status line is shown to you and never sent to the model. A contract
test runs the real hook and checks that it prints nothing.

### Call an API directly, not `claude -p`

The first idea was to let Claude Code itself do the checking with `claude -p`.
Measured on my machine:

| How | Wall time | Cost |
|---|---|---|
| `claude -p --model haiku`, just saying "OK" | 40-41 s | |
| `claude -p`, actually correcting one sentence | 48-54 s | ~31k cache-creation tokens, about $0.076 per call, ~$45/month |
| a direct call to DeepSeek | **~1.2 s** | **about $0.10/month** |

`claude -p` boots the whole Claude Code system prompt and tool definitions every
time; turning off MCP doesn't fix that. A direct call is about 400 times cheaper
and 40 times faster.

### Teach Chinese too, not only English mistakes

Version one only corrected messages written in English. Looking at my own
history changed that: most of my messages were Chinese or mixed, and those were
exactly the moments I *didn't know* how to say something in English. Coaching
only the English half meant missing the most useful material. Hence GAP
(mixed messages) and SAY (all Chinese).

### Mixed Chinese and English is a feature

If you have to write perfect English for the tool to work, you write less English.
Letting `how do I 撤销 the last commit` through, and teaching `撤销`, keeps the bar
low enough that you actually use it.

### Correcting "only one or two error types" is not better

It feels obvious that focusing on a couple of error types should work better.
The meta-analysis I could find does not support it: focused feedback g = 0.628
vs unfocused g = 0.445, difference not significant (Qb = 1.050, p = .305;
Chen & Renandya 2020, *TESL-EJ* 24(3)). The display limit in en-coach is about
screen width, not teaching method, and the log keeps everything.

## Things that did not work

### Making the model teach more

The status line looked empty, so I tried to get more items per message:

| Attempt | Result |
|---|---|
| raise the GAP limit from 2 to 4 | still 2 |
| tell it "a sparse line is wasted screen; if there are four, emit four" | no change |
| allow word-level rewrites | **fewer** items: it used them instead of sentence rewrites |
| say explicitly "both, not either" | total output dropped about 10% |
| temperature 0 to 0.4 / 0.8 / 1.2 | random noise, no trend |
| ask twice and merge | twice the latency, no more items |
| switch to a reasoning model | 7.8 s, all 800 tokens spent thinking, **zero** items |

The model has its own sense of "enough" and prompting doesn't move it. What did
work was putting more into each item instead of asking for more items: it gives
2-3 alternatives per item happily (`普及 → spread / popularize / get across`).

In the end the status line is a glance-at-it surface. Wanting to learn more is a
real need, but the place for it is a review screen built on the log, not a fuller
status line.

### Giving the model Claude's previous reply as context

Easy to build (the transcript path is in the hook payload), but it made things
worse. When you talk to Claude in Chinese, Claude answers in Chinese, so the
"context" is Chinese too. The model started teaching words from *Claude's* reply
that I never used. Stripping the Chinese left only numbers and identifiers. With
no context, quality was the same or better.

## Silent failures (most now have a test)

1. **`Let me try again` was dropped as JavaScript.** The code filter used `re.I`, so
   `Let`, `If`, `For`, `Try`, `Return`, `From` at the start of a sentence looked like
   code. The status line was just empty, for no visible reason.
2. **Every Chinese sentence was dropped.** The "long enough?" check counted words
   with `split()`. Chinese has no spaces, so a whole sentence was one word.
3. **Everyday English with "error", "Git", "Go" disappeared.** The log and command
   filters were case-insensitive. Engineers say these words constantly.
4. **The model copies examples from the prompt and invents text.** Every quoted
   fragment must appear literally in what you wrote, or the item is dropped.
5. **Your pasted screen fed last turn's tip back in.** Paste your terminal to ask a
   question and the model saw `✎ latter → later`, repeated it, and skipped the new
   mistakes. Lines starting with the tool's own symbols are filtered.
6. **Secrets in prompts landed in the log, and went to the API.** The log keeps
   300 characters of context, and masking was first applied only there. Known
   key formats, `user:pass@` URLs and "password is ..." are now masked before the
   text is sent and again before anything is written.
7. **A useless rewrite took the only slot.** Quotas were counted before
   de-duplication, so a rewrite that was later deleted blocked a good one behind it.
8. **The same correction showed twice.** The model put a rewrite that only
   repeated the fix as its *first* alternative, and the first alternative is the
   one shown. Alternatives are now checked one by one.
9. **Other sessions' messages were coached as mine.** Background task notices and
   messages from other agents also fire `UserPromptSubmit`. In one session about
   620 of 650 logged items came from them. Those tagged blocks are removed; your
   own words in the same message are kept.
10. **Nothing worked on Chinese Windows.** Python read the UTF-8 payload as GBK,
    every Chinese prompt became mojibake, the model answered NONE. stdin is now
    pinned to UTF-8, and the test reproduces the GBK console on any OS.
11. **A stale `.pyc` made me debug the wrong code.** `py_compile` left bytecode with
    the same mtime as the source. Run tests with `python -B`.
12. **A test used a Python 3.10 API** while the hook ran on the system Python 3.9.
    The test that guards imports crashed instead of checking. CI now runs 3.9.
13. **"Any OpenAI-compatible API works" was only half true.** Trying 14 models
    with the plain request, about half gave nothing. Several think before
    answering and spent all 320 tokens on it, returning `content: null`, which
    also crashed the hook. GPT-5 models reject `max_tokens`. Kimi only accepts
    temperature 1. GPT-5 nano, Gemini Flash-Lite and Qwen Flash write
    `F|orig|fix` without the error type, and every one of their corrections was
    dropped. And because the hook fails silently, each of these looked exactly
    like "you made no mistakes". Now: `EN_COACH_EXTRA_BODY` for per-model
    switches, an empty reply is just "no tips", the three-field form is
    accepted, and `--check` shows the real error.

## The status line refresh trap

The hook finishes in about 1.1 s, but the tip showed up 8 to 70 seconds later.
Claude Code redraws the status line when a new assistant message arrives, not when
you submit a prompt, so it stays frozen while Claude is thinking.

The fix is `statusLine.refreshInterval`. The installer sets it to **5**, not 1:

- every session reruns the status line script on that timer, all day;
- with 24 sessions open, 1 second meant about 0.43 of a CPU core just for that;
- worse, on a slow machine the script took longer than 1 s, Claude Code killed and
  restarted it every tick, and the leftover processes piled up (one machine reached
  2,100 `ps` processes and a load of 288).

5 seconds means the tip can be up to 5 seconds late, and the problem goes away.

## Cost

Replaying about 5,600 of my real messages: 59% pass the filters and get coached,
about 38 a day. With DeepSeek's flash model at off-peak prices that's roughly
$0.10 a month.
