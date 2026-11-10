#!/usr/bin/env python3
"""Install or remove en-coach for Claude Code.

    python install.py              # install (or update)
    python install.py --uninstall  # remove; your error log is kept
    python install.py --dry-run    # show what would change, touch nothing

What it does:
  1. copies hooks/en-coach.py and hooks/statusline-tip.py to ~/.claude/english-coach/
  2. adds one async UserPromptSubmit hook to ~/.claude/settings.json
  3. points statusLine at statusline-tip.py; a status line you already had is
     saved and still shown above the tip, and --uninstall puts it back exactly
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
INSTALL_DIR_NAME = "english-coach"
HOOK_SCRIPT = "en-coach.py"
STATUSLINE_SCRIPT = "statusline-tip.py"
CHAINED_FILE_NAME = "chained-statusline.json"
REFRESH_INTERVAL_SECONDS = 5   # see docs/lessons-learned.md: do not go below 5


class SettingsShapeError(Exception):
    pass


def posix(p):
    """Forward slashes work in Git Bash (Claude Code's shell on Windows) and everywhere else."""
    return str(p).replace("\\", "/")


def sh_quote(s):
    """Single quotes: nothing inside is expanded by the shell ($, backticks...)."""
    return "'" + s.replace("'", "'\\''") + "'"


def build_command(python_exe, script):
    return f"{sh_quote(posix(python_exe))} {sh_quote(posix(script))}"


def is_ours(command, script_name):
    """Exact match on our installed script, so a hook that merely contains the
    same file name (say ~/bin/open-coach.py) is never touched."""
    c = str(command or "").strip().strip("'\"")
    return c.endswith(f"{INSTALL_DIR_NAME}/{script_name}")


def load_settings(path):
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8-sig")      # tolerate a BOM from Windows editors
    data = json.loads(text) if text.strip() else {}
    check_shape(data)
    return data


def check_shape(s):
    if not isinstance(s, dict):
        raise SettingsShapeError("the top level is not a JSON object")
    hooks = s.get("hooks")
    if hooks is not None:
        if not isinstance(hooks, dict):
            raise SettingsShapeError('"hooks" is not an object')
        groups = hooks.get("UserPromptSubmit")
        if groups is not None:
            if not isinstance(groups, list) or not all(isinstance(g, dict) for g in groups):
                raise SettingsShapeError('"hooks.UserPromptSubmit" is not a list of objects')
            for g in groups:
                if not isinstance(g.get("hooks", []), list):
                    raise SettingsShapeError('a UserPromptSubmit group has a non-list "hooks"')
    if s.get("statusLine") is not None and not isinstance(s["statusLine"], dict):
        raise SettingsShapeError('"statusLine" is not an object')


def remove_our_hook(settings):
    hooks = settings.get("hooks") or {}
    groups = hooks.get("UserPromptSubmit") or []
    kept_groups = []
    for group in groups:
        entries = group.get("hooks") or []
        kept = [h for h in entries
                if not (isinstance(h, dict) and is_ours(h.get("command"), HOOK_SCRIPT))]
        if kept or not entries:
            kept_groups.append(dict(group, hooks=kept) if entries else group)
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


def refresh_seconds(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def install_statusline(settings, command):
    """Point statusLine at our script. Returns the status line you had before,
    to be saved and restored later, or None if there was none or it was ours."""
    current = settings.get("statusLine")
    previous = None
    if isinstance(current, dict) and not is_ours(current.get("command"), STATUSLINE_SCRIPT):
        previous = dict(current)
    new = dict(current) if isinstance(current, dict) else {}
    new.update({"type": "command", "command": command,
                "refreshInterval": max(refresh_seconds(new.get("refreshInterval")),
                                       REFRESH_INTERVAL_SECONDS)})
    settings["statusLine"] = new
    return previous


def uninstall_statusline(settings, chained_file, notes):
    current = settings.get("statusLine")
    if not (isinstance(current, dict) and is_ours(current.get("command"), STATUSLINE_SCRIPT)):
        return
    previous = None
    try:
        previous = json.loads(chained_file.read_text(encoding="utf-8")).get("statusLine")
    except Exception:
        pass
    if isinstance(previous, dict):
        settings["statusLine"] = previous
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
    install_dir = claude_dir / INSTALL_DIR_NAME
    chained_file = install_dir / CHAINED_FILE_NAME
    data_dir = Path(os.environ.get("EN_COACH_DATA_DIR") or (claude_dir / "english"))
    notes = []

    try:
        settings = load_settings(settings_path)
    except (json.JSONDecodeError, SettingsShapeError) as e:
        print(f"Cannot use {settings_path}: {e}\nNothing was changed. Fix the file, or add the "
              "hook by hand (see README > Install).")
        return 1
    before = json.dumps(settings, indent=2, ensure_ascii=False)

    previous_statusline = None
    if args.uninstall:
        remove_our_hook(settings)
        uninstall_statusline(settings, chained_file, notes)
    else:
        add_hook(settings, build_command(args.python, install_dir / HOOK_SCRIPT))
        if not args.no_statusline:
            previous_statusline = install_statusline(
                settings, build_command(args.python, install_dir / STATUSLINE_SCRIPT))

    after = json.dumps(settings, indent=2, ensure_ascii=False)

    if args.dry_run:
        print(f"Would write {settings_path}:\n{after}")
        return 0

    if not args.uninstall:
        install_dir.mkdir(parents=True, exist_ok=True)
        for name in (HOOK_SCRIPT, STATUSLINE_SCRIPT):
            shutil.copy2(REPO_DIR / "hooks" / name, install_dir / name)
        notes.append(f"copied hooks to {install_dir}")
        if previous_statusline is not None:
            chained_file.write_text(json.dumps({"statusLine": previous_statusline}, indent=2,
                                               ensure_ascii=False), encoding="utf-8")
            notes.append("kept your status line; it is shown above the tip")
    else:
        if install_dir.exists():
            shutil.rmtree(install_dir)
            notes.append(f"removed {install_dir}")
        for pattern in ("status-*.txt", "width-*.txt"):
            for f in data_dir.glob(pattern):
                f.unlink(missing_ok=True)

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
