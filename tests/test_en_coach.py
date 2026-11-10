#!/usr/bin/env python3
"""Regression tests for en-coach. Offline: no API calls, no key needed.

    python -B tests/test_en_coach.py

Almost every test here pins down a bug that actually happened, and almost all
of them were SILENT: no error, the coaching just quietly got worse or stopped.
You cannot catch those by eye, so run this before and after changing the hook.

Use -B. Without it Python writes __pycache__ next to the hook, and a stale .pyc
with the same mtime as the source can make you test old code.
"""

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "en-coach.py"
STATUSLINE = ROOT / "hooks" / "statusline-tip.py"
INSTALLER = ROOT / "install.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m = load(HOOK, "en_coach")


class ExtractProse(unittest.TestCase):
    """Line filter: drop the noise, never lose a word of real prose."""

    def keep(self, text):
        return m.extract_prose(text)[0]

    def test_english_sentence_starting_with_code_keyword(self):
        """re.I once made `Let me` look like JavaScript's `let`: whole sentence gone."""
        for line in [
            "Let me try again, and chech the latency.",
            "If you have time, please take a look at this.",
            "For now, we do not need to do the write part.",
            "Try to make it faster if you can.",
            "Return the money to me as soon as possible.",
            "From my side everything looks fine.",
            "Class was cancelled so I stayed home.",
            "Import duties went up again this year.",
            # The real test: a ( really follows the keyword. Only case
            # sensitivity keeps these two alive.
            "For (whatever reason) it broke again this morning.",
            "If (and only if) you have time, take a look.",
        ]:
            self.assertEqual(self.keep(line), line, f"wrongly dropped: {line!r}")

    def test_real_code_is_dropped(self):
        for line in [
            "def main():",
            "import os",
            "from pathlib import Path",
            "const foo = bar()",
            "if (x > 1) {",
            "return foo(bar)",
            "@decorator",
            "items.map(x => ({...x}))",
        ]:
            self.assertEqual(self.keep(line), "", f"code not dropped: {line!r}")

    def test_noise_is_dropped(self):
        for line in [
            "2026-08-20T05:45:29 INFO starting up",
            "  at Object.<anonymous> (/app/index.js:42)",
            "$ npm install --save-dev",
            "dev@laptop ~ % ls -la",
            "+++ b/src/main.py",
            "@@ -1,7 +1,9 @@",
        ]:
            self.assertEqual(self.keep(line), "", f"noise not dropped: {line!r}")

    def test_everyday_english_containing_log_words(self):
        """With re.I, log levels and command names swallowed everyday sentences."""
        for line in [
            "there was an error in my code",
            "I got a warning from the compiler",
            "just for your info the meeting moved",
            "let me trace the problem back",
            "this bug is fatal to our release",
            "can you debug this for me please",
            "Go ahead and try it yourself",
            "go to the store and buy some milk",
            "Git is hard to learn at the beginning",
            "git is hard to learn honestly",
            "Node is fine for this workload",
            "Curl up on the sofa and rest",
            "ssh keys are confusing to me",
            "brew a cup of tea for me please",
            "the cargo ship arrived late last night",
            "这个 bug 我 debug 了半天，还是没找到 root cause，你能帮我看看吗",
        ]:
            self.assertTrue(self.keep(line), f"everyday English dropped: {line!r}")

    def test_real_logs_and_commands_dropped(self):
        """...while real logs and command lines still go. The trade-off is
        deliberately lopsided: a bare `git status` may slip through, but
        "Git is hard to learn" must never be dropped."""
        for line in [
            "2026-08-20 06:10:45 ERROR failed to connect",
            "[error] connection refused",
            "  WARN  deprecated option ignored",
            "git commit -m 'fix the thing'",
            "git push --force-with-lease origin main",
            "go build ./cmd/server",
            "go run main.go",
            "npm install --save-dev typescript",
            "python3 scripts/validate.py --dir status",
            "docker compose up -d",
            "ssh -i ~/.ssh/id_rsa user@host",
            "curl -fsSL https://example.com/x.sh",
            "brew install poppler",
            "cargo build --release",
            "pip install uv",
            "kubectl get pods -n default",
        ]:
            self.assertEqual(self.keep(line), "", f"log/command not dropped: {line!r}")

    def test_log_cmd_rule_is_case_sensitive(self):
        """No re.I, and no inline (?-i:) either: that needs Python 3.11+ and an
        older interpreter would raise re.error that main() silently swallows."""
        import re
        self.assertFalse(m.LOG_CMD_RE.flags & re.I)
        self.assertNotIn("(?-i:", m.LOG_CMD_RE.pattern)

    def test_self_contamination(self):
        """Paste your screen and last turn's tip goes back to the model, which
        then just repeats it and skips the new mistakes in the same message."""
        pasted = "\n".join([
            "Is it normal? Can it show more than 1 line? check here:",
            "  ✎ we can fix it latter → we can fix it later",
            "  ↳ miniutes → minutes  ┃  massages → messages",
            "  ↻ I need to do a small report → I need to give a quick update",
            "  ⏵⏵ bypass permissions on (shift+tab to cycle)",
        ])
        prose = self.keep(pasted)
        for ch in "✎↳↻⏵":
            self.assertNotIn(ch, prose)
        self.assertEqual(prose, "Is it normal? Can it show more than 1 line? check here:")


class ContentGate(unittest.TestCase):
    def test_chinese_has_no_spaces(self):
        """len(split()) < 4 used to drop every Chinese sentence."""
        zh = "帮我梳理一下这几个服务之间的依赖关系"
        self.assertEqual(len(zh.split()), 1)
        self.assertTrue(m.has_content(zh))

    def test_too_short_is_rejected(self):
        for s in ["好的", "ok", "继续"]:
            self.assertFalse(m.has_content(s), s)

    def test_mode_boundaries(self):
        self.assertLessEqual(m.cjk_ratio("Let me check the latency first"), 0.15)
        self.assertGreater(m.cjk_ratio("我们今天把这个功能上线吧"), 0.75)

    def test_slash_commands_and_shell_escapes_skipped(self):
        for p in ("/compact keep the last task", "!git status --short",
                  "# remember that I prefer tabs over spaces"):
            self.assertIsNone(m.gate({"prompt": p}), p)


class InjectedMessages(unittest.TestCase):
    """Messages from background tasks, other sessions, teammates and sub-agents
    also fire the hook. They are not yours and must not be coached. The samples
    use the formats seen in real transcripts."""

    TASK = ("<task-notification>\n<task-id>b4cv0ingz</task-id>\n"
            "<output-file>/tmp/tasks/b4cv0ingz.output</output-file>\n"
            "<status>completed</status>\n"
            "<summary>Dynamic workflow \"verify the fallback reviewer is appended\" "
            "completed</summary>\n</task-notification>")
    PEER = ('<cross-session-message from="uds:/tmp/socks/7707.sock" from-name="api-8c">\n'
            "已停手,没有后台任务在跑,也没有定时唤醒。恢复通知我转给另一个会话了。\n"
            "</cross-session-message>")
    TEAMMATE = ('<teammate-message teammate_id="team-lead">\n'
                "Please send your concise report if your run is complete; "
                "do not make edits.\n</teammate-message>")
    AGENT = ('<agent-message from="code-review">\nAlso flag a lower-priority '
             "test-standard violation candidate in the functional tests.\n"
             "</agent-message>")

    def gate(self, prompt):
        return m.gate({"prompt": prompt})

    def test_injected_messages_are_skipped(self):
        for p in (self.TASK, self.PEER, self.TEAMMATE, self.AGENT,
                  self.TASK + "\n" + self.TASK):
            self.assertIsNone(self.gate(p), p[:60])

    def test_user_words_next_to_injected_block_survive(self):
        mine = "帮我看看这个后台任务为什么又失败了，是不是网络的问题"
        for p in (mine + "\n" + self.TASK, self.PEER + "\n" + mine):
            got = self.gate(p)
            self.assertIsNotNone(got)
            self.assertIn(mine, got[0])
            for leaked in ("Dynamic workflow", "已停手", "b4cv0ingz"):
                self.assertNotIn(leaked, got[0])

    def test_block_in_the_middle_of_a_line_does_not_split_it(self):
        """Replaced by a newline, each half would be too short and both dropped."""
        got = self.gate("帮我看一下 " + self.TASK.replace("\n", " ") + " 错在哪儿了呢")
        self.assertIsNotNone(got)
        self.assertIn("帮我看一下", got[0])
        self.assertIn("错在哪儿了呢", got[0])

    def test_user_text_that_merely_mentions_tags_is_kept(self):
        for p in ("为什么 <task-notification> 会被当成我写的话去纠错呢",
                  "<div> 这个元素为什么在手机上不显示出来，帮我查一下样式",
                  "<agent-message> 这个标签是干嘛的？为什么会出现在我的输入里",
                  "I think the <agent-message> block should not be coached at all"):
            self.assertIsNotNone(self.gate(p), p)


class StdinEncoding(unittest.TestCase):
    """On Chinese Windows, Python decoded the UTF-8 payload as GBK; every Chinese
    prompt became mojibake and the model answered NONE, with no error at all.
    PYTHONIOENCODING reproduces that machine's decoding on any platform."""

    def test_utf8_payload_survives_a_gbk_console(self):
        prompt = "帮我看看这个 feature 为什么不 work 了"
        probe = ("import importlib.util,sys;"
                 "s=importlib.util.spec_from_file_location('c',sys.argv[1]);"
                 "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
                 "sys.stdout.write(ascii(m.read_payload().get('prompt')))")
        r = subprocess.run(
            [sys.executable, "-B", "-c", probe, str(HOOK)],
            input=json.dumps({"prompt": prompt}, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
            env=dict(os.environ, PYTHONIOENCODING="gbk:surrogateescape"))
        self.assertEqual(r.stdout.decode("ascii", "replace"), ascii(prompt),
                         r.stderr.decode("utf-8", "replace")[-300:])


class Render(unittest.TestCase):
    F = staticmethod(lambda o, f: {"type": "fix", "kind": "spelling", "orig": o, "fix": f})
    G = staticmethod(lambda z, e: {"type": "gap", "zh": z, "en": e})
    R = staticmethod(lambda o, f: {"type": "rewrite", "orig": o, "fix": f})

    def lines(self, items, budget=174):
        out = m.render(items, budget)
        return out.split("\n") if out else []

    def test_short_items_share_a_line(self):
        """One item per line left huge empty gaps; pack by width instead."""
        got = self.lines([self.G("传入", "feed in / pass in"),
                          self.G("麻不麻烦", "how much of a hassle it is")])
        self.assertEqual(len(got), 1)
        self.assertIn("\u2503", got[0])

    def test_long_items_wrap_to_next_line(self):
        got = self.lines([self.G("传入", "feed in / pass in"),
                          self.G("麻不麻烦", "how much of a hassle it is")], budget=60)
        self.assertEqual(len(got), 2)
        self.assertIn("↳", got[1])

    def test_fixes_share_one_line(self):
        got = self.lines([self.F("latter", "later"), self.F("miniutes", "minutes")])
        self.assertEqual(len(got), 1)

    def test_gap_comes_before_fix(self):
        got = self.lines([self.F("latter", "later"), self.G("自我污染", "self-contamination")])
        self.assertLess(got[0].index("自我污染"), got[0].index("latter"))

    def test_max_lines_cap(self):
        long_gap = lambda i: self.G(f"很长的中文片段第{i}个",
                                    f"a deliberately long english rendering number {i}")
        got = self.lines([long_gap(i) for i in range(9)], budget=100)
        self.assertEqual(len(got), m.MAX_LINES)

    def test_rewrite_gets_own_line_and_marker(self):
        got = self.lines([self.F("what task I did", "what tasks I did"),
                          self.R("I need to do a small report", "I need to give a quick update")])
        self.assertEqual(len(got), 2)
        self.assertIn("↻", got[1])
        self.assertNotIn("\033[2m", got[1], "no dim: too grey to read on many themes")

    def test_learn_side_is_red_mine_is_green(self):
        got = self.lines([self.G("配色", "colour scheme"),
                          self.F("latter", "later"),
                          self.R("the colour set is not very good",
                                 "the colour scheme isn't great")])
        self.assertIn("\033[32m配色\033[0m → \033[31mcolour scheme\033[0m", got[0])
        self.assertIn("\033[32mlatter\033[0m → \033[31mlater\033[0m", got[0])
        self.assertIn("\033[32mthe colour set is not very good\033[0m → "
                      "\033[31mthe colour scheme isn't great\033[0m", got[1])

    def test_rewrite_shows_one_sentence_only(self):
        """Two suggestions side by side: neither gets learned."""
        got = self.lines([
            self.R("the colour set is not very good",
                   "the colour scheme isn't great / the colour choices don't work well"),
            self.R("it should be red to attract my attention",
                   "it should be red so it catches my eye")])
        self.assertEqual(len(got), 1)
        self.assertIn("the colour scheme isn't great", got[0])
        self.assertNotIn(" / ", got[0])
        self.assertNotIn("catches my eye", got[0])

    def test_rewrite_always_gets_its_line(self):
        long_gap = lambda i: self.G(f"很长的中文片段第{i}个",
                                    f"a deliberately long english rendering number {i}")
        got = self.lines([long_gap(i) for i in range(9)] + [self.R("xx yy zz", "aa bb cc")],
                         budget=100)
        self.assertEqual(len(got), m.MAX_LINES)
        self.assertIn("↻", got[-1])

    def test_narrow_terminal_wraps_instead_of_dropping(self):
        got = self.lines([self.F("we can fix it latter", "we can fix it later"),
                          self.F("miniutes", "minutes")], budget=40)
        self.assertEqual(len(got), 2)
        self.assertIn("latter", got[0])
        self.assertIn("miniutes", got[1])

    def test_empty(self):
        self.assertEqual(m.render([], 174), "")

    def test_cjk_counted_as_two_columns(self):
        self.assertEqual(m.vwidth("中文"), 4)
        self.assertEqual(m.vwidth("\033[31mab\033[0m"), 2)


class TermWidth(unittest.TestCase):
    def setUp(self):
        self.saved_cols = os.environ.pop("COLUMNS", None)
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.saved_dir = m.DATA_DIR
        m.DATA_DIR = self.tmp

    def tearDown(self):
        m.DATA_DIR = self.saved_dir
        os.environ.pop("COLUMNS", None)
        if self.saved_cols is not None:
            os.environ["COLUMNS"] = self.saved_cols
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fallback(self):
        self.assertEqual(m.term_width("no-such-session"), 78)

    def test_from_env(self):
        os.environ["COLUMNS"] = "200"
        self.assertEqual(m.term_width("no-such-session"), 196)

    def test_from_statusline_width_file(self):
        """Claude Code gives COLUMNS to the status line, not to hooks."""
        (self.tmp / "width-probe.txt").write_text("178")
        self.assertEqual(m.term_width("probe"), 174)

    def test_absurd_width_ignored(self):
        os.environ["COLUMNS"] = "3"
        self.assertEqual(m.term_width("no-such-session"), 78)


class ApiKeyAndProvider(unittest.TestCase):
    NAMES = ("EN_COACH_API_KEY", "DEEPSEEK_API_KEY")

    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in self.NAMES}

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def test_no_key_means_no_call(self):
        self.assertIsNone(m.api_key())
        self.assertEqual(m.ask_model("anything at all here"), "")

    def test_en_coach_key_wins(self):
        os.environ["EN_COACH_API_KEY"] = "a"
        os.environ["DEEPSEEK_API_KEY"] = "b"
        self.assertEqual(m.api_key(), "a")

    def test_deepseek_key_used(self):
        os.environ["DEEPSEEK_API_KEY"] = "b"
        self.assertEqual(m.api_key(), "b")

    def test_deepseek_key_never_sent_to_another_provider(self):
        os.environ["DEEPSEEK_API_KEY"] = "b"
        saved = m.BASE_URL
        try:
            m.BASE_URL = "http://localhost:11434/v1"
            self.assertIsNone(m.api_key())
            os.environ["EN_COACH_API_KEY"] = "local"
            self.assertEqual(m.api_key(), "local")
        finally:
            m.BASE_URL = saved

    def test_ciphertext_is_refused(self):
        os.environ["EN_COACH_API_KEY"] = "encrypted:BAD"
        self.assertIsNone(m.api_key())

    def test_thinking_switch_only_sent_to_deepseek(self):
        """DeepSeek flash must have thinking off or it returns nothing in time;
        other OpenAI-compatible APIs may reject the unknown field."""
        saved = m.BASE_URL
        try:
            m.BASE_URL = "https://api.deepseek.com"
            self.assertIn("thinking", m.build_request_body("x"))
            m.BASE_URL = "https://api.openai.com/v1"
            self.assertNotIn("thinking", m.build_request_body("x"))
        finally:
            m.BASE_URL = saved


class Parse(unittest.TestCase):
    """Models copy examples from the prompt and invent text that isn't there."""

    def test_hallucinated_gap_rejected(self):
        self.assertEqual(m.parse("G|梳理|walk me through", "Let me check the latency first."), [])

    def test_fix_must_appear_verbatim(self):
        prose = "we can fix it latter"
        self.assertEqual(m.parse("F|spelling|nonexistent phrase|whatever", prose), [])
        self.assertEqual(len(m.parse("F|spelling|latter|later", prose)), 1)

    def test_case_only_change_rejected(self):
        self.assertEqual(m.parse("F|spelling|github|GitHub", "i think github is down"), [])

    def test_none(self):
        self.assertEqual(m.parse("NONE", "whatever text here"), [])

    def test_control_characters_from_the_model_are_stripped(self):
        """Model text is printed to your terminal; an escape sequence must not get through."""
        items = m.parse("F|spelling|latter|lat\x1b[2Jer", "we can fix it latter")
        self.assertEqual(items[0]["fix"], "lat[2Jer")

    def test_rewrite_parsed(self):
        prose = "I need to do a small report on our team's standup meeting"
        items = m.parse("R|do a small report on our team's standup"
                        "|give a quick update at our team's standup", prose)
        self.assertEqual([i["type"] for i in items], ["rewrite"])

    def test_rewrite_must_be_grounded(self):
        self.assertEqual(m.parse("R|something never said|a nicer version of it",
                                 "I need to do a small report"), [])

    def test_rewrite_that_only_fixes_the_error_is_dropped(self):
        prose = "The test is pass, so I think we can merge this PR now"
        raw = ("F|verb-form|The test is pass|The test passed\n"
               "R|The test is pass, so I think we can merge this PR now"
               "|The test passed, so I think we can merge this PR now")
        self.assertEqual([i["type"] for i in m.parse(raw, prose)], ["fix"])

    def test_rewrite_that_repeats_a_gap_is_dropped(self):
        raw = ("G|换一种方式|take a different approach\n"
               "R|换一种方式|take a different approach!")
        self.assertEqual([i["type"] for i in m.parse(raw, "我们应该换一种方式来做这件事情吧")],
                         ["gap"])

    def test_quota_is_applied_after_dedup_not_during_scan(self):
        """Worthless rewrites must fill the quota for this test to mean anything:
        with spare slots, truncate-then-dedup and dedup-then-truncate agree."""
        prose = "We has a error and it work good in production today"
        raw = ("F|verb-form|We has|We have\n"
               "F|article|a error|an error\n"
               "F|verb-form|it work good|it works well\n"
               "R|We has a error|We have an error\n"
               "R|it work good|it works well\n"
               "R|in production today|in prod today")
        rewrites = [i for i in m.parse(raw, prose) if i["type"] == "rewrite"]
        self.assertEqual(len(rewrites), 1)
        self.assertEqual(rewrites[0]["orig"], "in production today")

    def test_worthless_first_alternative_is_removed(self):
        """Real output: the first alternative only repeated the FIX, and since the
        status line shows the first one, the same correction appeared twice."""
        prose = "how do I 撤销 the last commit without lose my changes?"
        raw = ("F|verb-form|without lose my changes|without losing my changes\n"
               "R|without lose my changes|without losing my changes / while keeping my changes")
        rewrites = [i for i in m.parse(raw, prose) if i["type"] == "rewrite"]
        self.assertEqual(len(rewrites), 1)
        self.assertEqual(rewrites[0]["fix"], "while keeping my changes")

    def test_rewrite_with_real_value_survives(self):
        prose = "can we buid our program as a repo and share it on github"
        raw = ("F|spelling|buid our|build our\n"
               "R|can we buid our program as a repo|can we turn our program into a repo")
        self.assertEqual([i["type"] for i in m.parse(raw, prose)], ["fix", "rewrite"])


class Redact(unittest.TestCase):
    def test_secrets_are_redacted(self):
        for raw in [
            "my key is sk-abcdefghijklmnopqrstuvwxyz123456",
            "token ghp_abcdefghijklmnopqrstuvwxyz1234567890",
            "AKIAIOSFODNN7EXAMPLE",
            "api_key = supersecretvalue123",
            "password: hunter2hunter2",
            "my password is hunter2xyz99",
            "connect to postgres://admin:S3cretPass@db.internal:5432/app",
            "数据库密码是 Abc12345 你帮我连一下",
        ]:
            out = m.redact(raw)
            self.assertIn("REDACTED", out, raw)
            for leaked in ("hunter2", "S3cretPass", "Abc12345", "supersecret"):
                self.assertNotIn(leaked, out, raw)

    def test_secrets_are_redacted_before_the_api_call(self):
        """The model must never receive a pasted secret, not just the log."""
        sent = []
        saved_ask, saved_dir = m.ask_model, m.DATA_DIR
        payload = {"prompt": "can you check why login fails? my password is hunter2xyz99 btw",
                   "session_id": "redact-probe"}
        try:
            m.ask_model = lambda prose: sent.append(prose) or "NONE"
            m.DATA_DIR = pathlib.Path(tempfile.mkdtemp())
            import io
            saved_stdin = sys.stdin
            sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()), encoding="utf-8")
            try:
                m.main()
            finally:
                sys.stdin = saved_stdin
        finally:
            m.ask_model, m.DATA_DIR = saved_ask, saved_dir
            os.environ.pop("EN_COACH_RUNNING", None)
        self.assertEqual(len(sent), 1)
        self.assertNotIn("hunter2", sent[0])

    def test_harmless_things_survive(self):
        """git hashes and UUIDs are kept: they are context, not secrets."""
        for raw in [
            "look at commit 8b9e34d1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7",
            "session 33c4830c-2060-4d61-b444-56db48d9a43a crashed",
            "we can fix it latter",
            "the password is wrong again, can you check",
            "数据库密码是错的，帮我看看",
        ]:
            self.assertEqual(m.redact(raw), raw)


class ErrorLog(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.saved = (m.DATA_DIR, m.ERRORS_FILE, os.environ.get("EN_COACH_LOG"))
        m.DATA_DIR, m.ERRORS_FILE = self.tmp, self.tmp / "errors.jsonl"

    def tearDown(self):
        m.DATA_DIR, m.ERRORS_FILE = self.saved[0], self.saved[1]
        os.environ.pop("EN_COACH_LOG", None)
        if self.saved[2] is not None:
            os.environ["EN_COACH_LOG"] = self.saved[2]
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_log_is_redacted(self):
        items = [{"type": "fix", "kind": "spelling", "orig": "latter", "fix": "later"}]
        m.append_errors(items, "abcdef123456", "/work/project",
                        "we fix it latter, key sk-abcdefghijklmnopqrstuvwxyz123456")
        rec = json.loads(m.ERRORS_FILE.read_text(encoding="utf-8"))
        self.assertNotIn("sk-abc", rec["sentence"])
        self.assertEqual(rec["cwd_name"], "project")
        self.assertEqual(rec["session"], "abcdef12")

    def test_every_logged_field_is_redacted(self):
        items = [{"type": "fix", "kind": "word-choice",
                  "orig": "token ghp_abcdefghijklmnopqrstuvwxyz1234567890", "fix": "x"}]
        m.append_errors(items, "s", "", "short")
        self.assertNotIn("ghp_abc", m.ERRORS_FILE.read_text(encoding="utf-8"))

    def test_log_can_be_turned_off(self):
        os.environ["EN_COACH_LOG"] = "0"
        m.append_errors([{"type": "gap", "zh": "兜底", "en": "fallback"}], "s", "", "x")
        self.assertFalse(m.ERRORS_FILE.exists())


class Contract(unittest.TestCase):
    """Invariants whose breakage would quietly change Claude's answers or the workflow."""

    def test_hook_never_writes_stdout(self):
        self.assertNotIn("print(", HOOK.read_text(encoding="utf-8"),
                         "a hook's stdout can reach Claude's context")

    def test_hook_prints_nothing_end_to_end(self):
        """Run the real script with no key: it must exit 0 and print nothing."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("EN_COACH_API_KEY", "DEEPSEEK_API_KEY")}
        with tempfile.TemporaryDirectory() as d:
            env["EN_COACH_DATA_DIR"] = d
            r = subprocess.run([sys.executable, "-B", str(HOOK)],
                               input=json.dumps({"prompt": "can you check why the build is failling",
                                                 "session_id": "t"}).encode(),
                               capture_output=True, env=env)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))

    def test_stdlib_only(self):
        """No third-party or same-directory imports. Decided by where each module
        is actually loaded from, so a local file shadowing a stdlib name is
        caught too. (Not sys.stdlib_module_names: that is Python 3.10+.)"""
        import ast
        import importlib.util as iu
        import sysconfig
        for path in (HOOK, STATUSLINE, INSTALLER):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imported.add(node.module.split(".")[0])
                elif isinstance(node, ast.ImportFrom) and node.level:
                    self.fail(f"relative import in {path.name}")
            paths = sysconfig.get_paths()
            roots = {os.path.realpath(paths["stdlib"]), os.path.realpath(paths["platstdlib"])}
            # Windows keeps C extensions in sys.base_prefix\DLLs, next to Lib\, not inside it.
            win_dlls = os.path.join(sys.base_prefix, "DLLs")
            if os.path.isdir(win_dlls):
                roots.add(os.path.realpath(win_dlls))
            offenders = {}
            for name in sorted(imported):
                if name in sys.builtin_module_names:
                    continue
                spec = iu.find_spec(name)
                if spec is None:
                    offenders[name] = "not found"
                    continue
                origin = spec.origin or ""
                if origin in ("frozen", "built-in"):
                    continue
                if not any(os.path.realpath(origin).startswith(r + os.sep) for r in roots):
                    offenders[name] = origin
            self.assertEqual(offenders, {}, path.name)


class StatusLine(unittest.TestCase):
    """The installed script lives in its own folder with chained-statusline.json
    next to it; each test builds that layout in a temp dir."""

    def run_statusline(self, data_dir, session="s1", columns=None, chained=None):
        import shutil
        script_dir = pathlib.Path(data_dir) / "install"
        script_dir.mkdir(exist_ok=True)
        shutil.copy2(STATUSLINE, script_dir / STATUSLINE.name)
        if chained:
            (script_dir / "chained-statusline.json").write_text(
                json.dumps({"statusLine": {"type": "command", "command": chained}}))
        env = dict(os.environ, EN_COACH_DATA_DIR=str(data_dir))
        env.pop("COLUMNS", None)
        if columns:
            env["COLUMNS"] = str(columns)
        r = subprocess.run([sys.executable, "-B", str(script_dir / STATUSLINE.name)],
                           input=json.dumps({"session_id": session}).encode(),
                           capture_output=True, env=env, timeout=30)
        return r.stdout.decode("utf-8")

    def test_prints_tip_and_saves_width(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            (d / "status-s1.txt").write_text("✎ latter → later", encoding="utf-8")
            self.assertEqual(self.run_statusline(d, columns=150), "✎ latter → later\n")
            self.assertEqual((d / "width-s1.txt").read_text(), "150")

    def test_silent_without_tip(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_statusline(pathlib.Path(d)), "")

    def test_chained_statusline_comes_first(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            (d / "status-s1.txt").write_text("tip line", encoding="utf-8")
            self.assertEqual(self.run_statusline(d, chained="echo my-old-statusline"),
                             "my-old-statusline\ntip line\n")

    def test_slow_chained_statusline_is_cut_off(self):
        """A slow old status line must not hang ours (a hung status line piles up
        processes). On Windows, killing only bash left a child holding the pipe."""
        import time
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            (d / "status-s1.txt").write_text("tip line", encoding="utf-8")
            t0 = time.monotonic()
            out = self.run_statusline(d, chained="echo early; sleep 15; echo late")
            self.assertLess(time.monotonic() - t0, 10)
            self.assertTrue(out.endswith("tip line\n"), out)
            self.assertNotIn("late", out)


class Installer(unittest.TestCase):
    def setUp(self):
        self.inst = load(INSTALLER, "en_coach_install")
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.settings = self.tmp / "settings.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_installer(self, *extra):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            return self.inst.main(["--claude-dir", str(self.tmp), "--python", "/usr/bin/python3",
                                   *extra])

    def read(self):
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def test_fresh_install_and_uninstall(self):
        self.assertEqual(self.run_installer(), 0)
        s = self.read()
        hook = s["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        self.assertIn("en-coach.py", hook["command"])
        self.assertTrue(hook["async"], "a sync hook would delay every prompt")
        self.assertIn("statusline-tip.py", s["statusLine"]["command"])
        self.assertGreaterEqual(s["statusLine"]["refreshInterval"], 5)
        self.assertTrue((self.tmp / "english-coach" / "en-coach.py").exists())

        self.assertEqual(self.run_installer("--uninstall"), 0)
        s = self.read()
        self.assertNotIn("hooks", s)
        self.assertNotIn("statusLine", s)
        self.assertFalse((self.tmp / "english-coach").exists())

    def test_existing_settings_survive_and_statusline_is_chained(self):
        original = {
            "model": "opus",
            "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "echo hi"}]}]},
            "statusLine": {"type": "command", "command": "my-statusline --fancy", "padding": 1},
        }
        self.settings.write_text(json.dumps(original), encoding="utf-8")
        self.run_installer()
        s = self.read()
        self.assertEqual(s["model"], "opus")
        cmds = [h["command"] for g in s["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
        self.assertIn("echo hi", cmds)
        self.assertEqual(s["statusLine"]["padding"], 1)
        chained = self.tmp / "english-coach" / "chained-statusline.json"
        self.assertEqual(json.loads(chained.read_text())["statusLine"], original["statusLine"])
        self.assertTrue(list(self.tmp.glob("settings.json.en-coach-backup-*")))

        self.run_installer()          # running twice must not duplicate anything
        s = self.read()
        cmds = [h["command"] for g in s["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
        self.assertEqual(sum("en-coach.py" in c for c in cmds), 1)
        self.assertEqual(json.loads(chained.read_text())["statusLine"], original["statusLine"],
                         "second run must not chain our own status line")

        self.run_installer("--uninstall")
        self.assertEqual(self.read(), original, "uninstall must restore settings exactly")

    def test_hooks_with_a_similar_name_are_left_alone(self):
        theirs = {"hooks": {"UserPromptSubmit": [
            {"matcher": "", "hooks": [{"type": "command", "command": "python ~/bin/open-coach.py"}]}]}}
        self.settings.write_text(json.dumps(theirs), encoding="utf-8")
        self.run_installer()
        self.run_installer("--uninstall")
        self.assertEqual(self.read(), theirs)

    def test_settings_with_bom_are_read(self):
        self.settings.write_bytes(b"\xef\xbb\xbf" + json.dumps({"model": "opus"}).encode())
        self.assertEqual(self.run_installer(), 0)
        self.assertEqual(self.read()["model"], "opus")

    def test_odd_settings_shape_is_refused_cleanly(self):
        for bad in ([1, 2], {"hooks": []}, {"hooks": {"UserPromptSubmit": ["x"]}},
                    {"statusLine": "fancy"}):
            raw = json.dumps(bad)
            self.settings.write_text(raw, encoding="utf-8")
            self.assertEqual(self.run_installer(), 1, raw)
            self.assertEqual(self.settings.read_text(encoding="utf-8"), raw, "must not write")

    def test_non_numeric_refresh_interval(self):
        self.settings.write_text(json.dumps(
            {"statusLine": {"type": "command", "command": "x", "refreshInterval": "fast"}}))
        self.assertEqual(self.run_installer(), 0)
        self.assertEqual(self.read()["statusLine"]["refreshInterval"], 5)

    def test_dry_run_writes_nothing(self):
        self.run_installer("--dry-run")
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_commands_use_forward_slashes(self):
        """Claude Code runs hooks through Git Bash on Windows; backslashes break there."""
        cmd = self.inst.build_command(r"C:\Python\python.exe", pathlib.PureWindowsPath(r"C:\Users\a\x.py"))
        self.assertNotIn("\\", cmd)

    def test_paths_are_not_expanded_by_the_shell(self):
        """Single-quoted, so a $ or backtick in a path stays literal."""
        cmd = self.inst.build_command("/opt/py$HOME/python", "/tmp/it's `here`/x.py")
        r = subprocess.run(["bash", "-c", f"printf '%s|' {cmd}"], capture_output=True, text=True)
        if r.returncode == 0:
            self.assertEqual(r.stdout, "/opt/py$HOME/python|/tmp/it's `here`/x.py|")


if __name__ == "__main__":
    unittest.main(verbosity=2)
