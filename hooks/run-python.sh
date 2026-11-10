#!/usr/bin/env bash
# Run a Python script with this machine's Python 3, for the plugin's hook.
# (install.py writes an absolute interpreter path instead; a plugin can't know it.)
#
# On Windows, python3.exe / python.exe in ...\WindowsApps are often only the
# Microsoft Store stubs that open the Store, so real interpreters are tried
# first and a WindowsApps one is used only if it actually runs.
store=""
for name in python3 python py; do
  path=$(command -v "$name" 2>/dev/null) || continue
  case "$path" in
    *WindowsApps*) [ -z "$store" ] && store=$path ;;
    *) exec "$path" "$@" ;;
  esac
done
if [ -n "$store" ] && "$store" -c "" >/dev/null 2>&1; then
  exec "$store" "$@"
fi
exit 0   # no Python: stay silent like the hook itself
