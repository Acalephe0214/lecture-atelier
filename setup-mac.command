#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
exec /bin/zsh ./bootstrap-mac.command "$@"
