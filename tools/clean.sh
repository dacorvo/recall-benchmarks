#!/bin/sh
# clean.sh HOME [VAR=value ...] CMD ...: run CMD with HOME, a system PATH, LANG and TERM and nothing else
# from the calling environment, so a tool reads only the home it is given.
h=$1; shift
exec env -i HOME="$h" PATH="${CLEAN_PATH:-/usr/local/bin:/usr/bin:/bin}" LANG=C.UTF-8 TERM=dumb "$@"
