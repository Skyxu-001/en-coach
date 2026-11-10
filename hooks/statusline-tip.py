#!/usr/bin/env python3
"""Status line for en-coach: prints the latest English tip for this session.

Claude Code runs the status line command and shows whatever it prints, so the
tip appears under your prompt without ever entering Claude's context.

If you already had a status line, the installer saves its command to
~/.claude/english/chained-statusline.txt. This script runs that command first
(with the same input) and prints the tip on the line below, so you keep
everything you had.

Standard library only, Python 3.9+.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DATA_DIR = Path(os.environ.get("EN_COACH_DATA_DIR") or (Path.home() / ".claude" / "english"))
CHAINED_COMMAND_FILE = DATA_DIR / "chained-statusline.txt"
CHAINED_TIMEOUT_SECONDS = 4


def run_chained(raw_input):
    """Run the status line you had before installing, if any."""
    try:
        command = CHAINED_COMMAND_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    if not command:
        return ""
    # Claude Code runs status line commands through a POSIX shell (Git Bash on
    # Windows), so do the same; fall back to the platform shell.
    bash = shutil.which("bash")
    argv = [bash, "-c", command] if bash else command
    try:
        r = subprocess.run(argv, input=raw_input, capture_output=True,
                           shell=not bash, timeout=CHAINED_TIMEOUT_SECONDS)
        return r.stdout.decode("utf-8", "replace").rstrip("\n")
    except Exception:
        return ""


def main():
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except Exception:
        payload = {}
    session = str(payload.get("session_id") or "default")

    # The hook is not told the terminal width; leave it here for the hook to read.
    try:
        cols = int(os.environ.get("COLUMNS") or 0)
        if cols >= 40:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            (DATA_DIR / f"width-{session}.txt").write_text(str(cols), encoding="utf-8")
    except Exception:
        pass

    lines = []
    chained = run_chained(raw.encode("utf-8"))
    if chained:
        lines.append(chained)
    try:
        tip = (DATA_DIR / f"status-{session}.txt").read_text(encoding="utf-8").strip()
    except Exception:
        tip = ""
    if tip:
        lines.append(tip)
    if lines:
        out = "\n".join(lines) + "\n"
        try:
            sys.stdout.buffer.write(out.encode("utf-8"))
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
