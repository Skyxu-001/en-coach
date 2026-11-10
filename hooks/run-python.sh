#!/usr/bin/env bash
# Run a Python script with this machine's Python 3, for the plugin's hook.
# (install.py writes an absolute interpreter path instead; a plugin can't know it.)
#
# Each candidate must really run and be 3.9 or newer. Things that are found on
# PATH but don't work: the Microsoft Store stubs in ...\WindowsApps (they open
# the Store), a stale pyenv / asdf shim, an old python, and on a Mac without the
# Command Line Tools /usr/bin/python3, which pops up an install dialog. Real
# interpreters are tried before a WindowsApps one.
works() {
  case "$1" in
    /usr/bin/python3)
      if [ "$(uname -s 2>/dev/null)" = Darwin ]; then
        xcode-select -p >/dev/null 2>&1 || return 1
      fi ;;
  esac
  "$1" -c "import sys; sys.exit(sys.version_info < (3, 9))" </dev/null >/dev/null 2>&1
}

# The hook's JSON arrives on stdin. Keep it on fd 3: inside the read loop below
# stdin is the here-doc, and exec'ing Python there handed it the here-doc instead.
exec 3<&0

store=""
for name in python3 python py; do
  # every match on PATH, not just the first: a broken shim may shadow a good one
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    case "$path" in
      *WindowsApps*) [ -z "$store" ] && store=$path ;;
      *) works "$path" && exec "$path" "$@" <&3 3<&- ;;
    esac
  done <<EOF
$(type -ap "$name" 2>/dev/null)
EOF
done
if [ -n "$store" ] && works "$store"; then
  exec "$store" "$@" <&3 3<&-
fi
exit 0   # no usable Python: stay silent like the hook itself
