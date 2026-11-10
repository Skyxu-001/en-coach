#!/usr/bin/env python3
"""Status line for en-coach: prints the latest English tip for this session.

Claude Code runs the status line command and shows whatever it prints, so the
tip appears under your prompt without ever entering Claude's context.

If you already had a status line, the installer saves it next to this script as
chained-statusline.json. This script runs that command first (with the same
input) and prints the tip on the line below, so you keep everything you had.

Standard library only, Python 3.9+.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

# Same default as install.py and en-coach.py: follow CLAUDE_CONFIG_DIR.
DATA_DIR = Path(os.environ.get("EN_COACH_DATA_DIR")
                or Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser() / "english")
CHAINED_FILE = Path(__file__).resolve().parent / "chained-statusline.json"
CHAINED_TIMEOUT_SECONDS = 4


def chained_command():
    try:
        saved = json.loads(CHAINED_FILE.read_text(encoding="utf-8"))
        return str((saved.get("statusLine") or {}).get("command") or "").strip()
    except Exception:
        return ""


def kill_tree(proc):
    """Kill the command and everything it started. Killing only the shell can
    leave a child holding the output open, and the status line would hang."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, timeout=5)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_chained(raw_input):
    """Run the status line you had before installing, if any."""
    command = chained_command()
    if not command:
        return ""
    # Claude Code runs status line commands through a POSIX shell (Git Bash on
    # Windows), so do the same; fall back to the platform shell.
    bash = shutil.which("bash")
    argv = [bash, "-c", command] if bash else command
    extra = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    # Output goes to a temp file, not a pipe: a pipe can keep us waiting on a
    # grandchild process even after the timeout fired.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as stdin_file:
        stdin_file.write(raw_input)
        stdin_file.seek(0)
        try:
            proc = subprocess.Popen(argv, stdin=stdin_file, stdout=out,
                                    stderr=subprocess.DEVNULL, shell=not bash, **extra)
        except Exception:
            return ""
        try:
            proc.wait(timeout=CHAINED_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        out.seek(0)
        return out.read().decode("utf-8", "replace").rstrip("\n")


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
    session = re.sub(r"[^A-Za-z0-9_-]", "_", str(payload.get("session_id") or "default"))[:64]

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
