#!/usr/bin/env python3
"""Install or remove en-coach for Claude Code.

    python install.py              # install (or update)
    python install.py --uninstall  # remove; your error log is kept
    python install.py --dry-run    # show what would change, touch nothing

What it does:
  1. copies hooks/en-coach.py and hooks/statusline-tip.py to ~/.claude/english-coach/
  2. adds one async UserPromptSubmit hook to ~/.claude/settings.json
  3. points statusLine at statusline-tip.py; a status line you already had is
     kept and still shown above the tip
  4. writes a timestamped backup of settings.json before changing it

It never writes your API key anywhere.
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
HOOK_MARKER = "en-coach.py"
STATUSLINE_MARKER = "statusline-tip.py"
REFRESH_INTERVAL_SECONDS = 5   # see docs/lessons-learned.md: do not go below 5


def posix(p):
    """Forward slashes work in Git Bash (Claude Code's shell on Windows) and everywhere else."""
    return str(p).replace("\\", "/")


def build_command(python_exe, script):
    return f'"{posix(python_exe)}" "{posix(script)}"'


def load_settings(path):
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if text.strip() else {}


def remove_our_hook(settings):
    hooks = settings.get("hooks") or {}
    groups = hooks.get("UserPromptSubmit") or []
    kept_groups = []
    for group in groups:
        entries = [h for h in (group.get("hooks") or [])
                   if HOOK_MARKER not in str(h.get("command", ""))]
        if entries:
            kept_groups.append(dict(group, hooks=entries))
    if kept_groups:
        hooks["UserPromptSubmit"] = kept_groups
    elif "UserPromptSubmit" in hooks:
        del hooks["UserPromptSubmit"]
    if hooks:
        settings["hooks"] = hooks
    elif "hooks" in settings:
        del settings["hooks"]


def add_hook(settings, command):
    remove_our_hook(settings)
    hooks = settings.setdefault("hooks", {})
    hooks.setdefault("UserPromptSubmit", []).append(
        {"hooks": [{"type": "command", "command": command, "async": True}]})


def install_statusline(settings, command):
    """Point statusLine at our script. Returns the command of the status line you
    had before (to be chained), or "" if there was none or it was already ours."""
    current = settings.get("statusLine")
    previous = ""
    if isinstance(current, dict) and STATUSLINE_MARKER in str(current.get("command", "")):
        pass
    elif isinstance(current, dict) and current.get("type") == "command" and current.get("command"):
        previous = current["command"]
    new = dict(current) if isinstance(current, dict) else {}
    new.update({"type": "command", "command": command,
                "refreshInterval": max(int(new.get("refreshInterval") or 0),
                                       REFRESH_INTERVAL_SECONDS)})
    settings["statusLine"] = new
    return previous


def uninstall_statusline(settings, chained_file, notes):
    current = settings.get("statusLine")
    if not (isinstance(current, dict) and STATUSLINE_MARKER in str(current.get("command", ""))):
        return
    previous = ""
    if chained_file.exists():
        previous = chained_file.read_text(encoding="utf-8").strip()
    if previous:
        current["command"] = previous
        notes.append("restored your previous status line")
    else:
        del settings["statusLine"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-statusline", action="store_true",
                    help="only add the hook; wire the tip into your own status line yourself")
    ap.add_argument("--claude-dir", default=str(Path.home() / ".claude"),
                    help="Claude Code config directory (default: ~/.claude)")
    ap.add_argument("--python", default=sys.executable,
                    help="interpreter the hooks should run with (default: this one)")
    args = ap.parse_args(argv)

    claude_dir = Path(args.claude_dir).expanduser()
    settings_path = claude_dir / "settings.json"
    install_dir = claude_dir / "english-coach"
    data_dir = claude_dir / "english"
    chained_file = data_dir / "chained-statusline.txt"
    notes = []

    try:
        settings = load_settings(settings_path)
    except json.JSONDecodeError as e:
        print(f"Cannot parse {settings_path}: {e}\nFix the JSON first; nothing was changed.")
        return 1
    before = json.dumps(settings, indent=2, ensure_ascii=False)

    if args.uninstall:
        remove_our_hook(settings)
        uninstall_statusline(settings, chained_file, notes)
    else:
        hook_cmd = build_command(args.python, install_dir / "en-coach.py")
        add_hook(settings, hook_cmd)
        chained_command = ""
        if not args.no_statusline:
            status_cmd = build_command(args.python, install_dir / "statusline-tip.py")
            chained_command = install_statusline(settings, status_cmd)

    after = json.dumps(settings, indent=2, ensure_ascii=False)

    if args.dry_run:
        print(f"Would write {settings_path}:\n{after}")
        return 0

    if not args.uninstall:
        install_dir.mkdir(parents=True, exist_ok=True)
        for name in ("en-coach.py", "statusline-tip.py"):
            shutil.copy2(REPO_DIR / "hooks" / name, install_dir / name)
        notes.append(f"copied hooks to {install_dir}")
        if chained_command:
            data_dir.mkdir(parents=True, exist_ok=True)
            chained_file.write_text(chained_command, encoding="utf-8")
            notes.append(f"kept your status line; it now runs from {chained_file}")
    else:
        if install_dir.exists():
            shutil.rmtree(install_dir)
            notes.append(f"removed {install_dir}")
        if chained_file.exists():
            chained_file.unlink()

    if after != before:
        claude_dir.mkdir(parents=True, exist_ok=True)
        if settings_path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = settings_path.with_name(f"settings.json.en-coach-backup-{stamp}")
            shutil.copy2(settings_path, backup)
            notes.append(f"backup: {backup}")
        settings_path.write_text(after + "\n", encoding="utf-8")
        notes.append(f"updated {settings_path}")

    for n in notes:
        print("  - " + n)

    if args.uninstall:
        print(f"\nen-coach removed. Your error log is still in {data_dir}.")
        return 0

    print("\nen-coach installed. Start a new Claude Code session to load the hook.")
    if not (os.environ.get("EN_COACH_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")):
        print("\nOne more step: give it an API key. Either export it in your shell profile:\n"
              "    export DEEPSEEK_API_KEY=sk-...\n"
              "or add it to the \"env\" block of settings.json. See README > Configuration.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
