# Optional: tech-word dictionary for spell-check

Claude Code's `spellcheck` setting underlines typos in the input box using
hunspell. It runs locally, costs nothing, and is independent of the coaching hook.
Out of the box it flags words like `yaml`, `kubectl` or `webhook`. `tech.dic` is a
small list of those so they aren't marked.

1. Install hunspell and an `en_US` dictionary (macOS: `brew install hunspell`, then put
   `en_US.aff` / `en_US.dic` from
   [LibreOffice/dictionaries](https://github.com/LibreOffice/dictionaries/tree/master/en)
   in `~/Library/Spelling/`).
2. Copy `tech.dic` and `tech.aff` into the same folder. Keep the names `tech.*`.
3. In `~/.claude/settings.json`:

   ```json
   "spellcheck": { "enabled": true, "language": "en_US,tech" }
   ```

4. Check: `hunspell -D </dev/null` should list both `en_US` and `tech`.

To add words, edit `tech.dic`. **The number on the first line is the word count;
update it when you add words.** Wherever hunspell is missing, spell-check just
stays off; the coaching hook is not affected.
