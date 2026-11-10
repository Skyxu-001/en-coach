---
name: setup
description: Set up the en-coach status line after installing the en-coach plugin (run once, and again after updating the plugin). "/en-coach:setup remove" takes it out again and restores the previous status line.
disable-model-invocation: true
---

# en-coach setup

A plugin can't set Claude Code's status line itself, so this runs en-coach's
installer in status-line-only mode. The plugin already provides the hook.

The plugin root is two folders above this skill's base directory
(`<plugin root>/skills/setup`). Use forward slashes in the path.

1. If the arguments say `remove`, `uninstall` or similar, run:

   ```sh
   bash "<plugin root>/hooks/run-python.sh" "<plugin root>/install.py" --uninstall
   ```

   Otherwise run:

   ```sh
   bash "<plugin root>/hooks/run-python.sh" "<plugin root>/install.py" --statusline-only
   ```

2. Show the installer's output to the user as it is. If it printed nothing at
   all, Python 3.9+ was not found: tell the user to install it.
3. Tell the user to start a new Claude Code session and type a prompt with an
   English mistake in it. The tip shows up under the input box a few seconds later.
4. If the installer said an API key is still needed, point to "Configuration"
   in the README: https://github.com/Skyxu-001/en-coach#configuration
   Never ask the user to paste a key into the chat, and never print one.
5. Mention that if no tip ever appears, this shows what is wrong:
   `python3 ~/.claude/english-coach/en-coach.py --check` (Windows: `py`).
