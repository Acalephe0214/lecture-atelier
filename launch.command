#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
lecture_python=""
for lecture_candidate in "$PWD/.portable/python/bin/python3" "$PWD/.venv/bin/python3" "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" python3.12 python3; do
  if command -v "$lecture_candidate" >/dev/null 2>&1 && "$lecture_candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    lecture_python="$lecture_candidate"
    break
  fi
done
if [ -z "$lecture_python" ]; then
  exec /bin/zsh ./bootstrap-mac.command
fi
if [ -d "$PWD/.portable/vendor" ]; then
  export PYTHONPATH="$PWD/.portable/vendor${PYTHONPATH:+:$PYTHONPATH}"
  "$lecture_python" bootstrap.py --configure-bundled
fi
printf '%s\n' '正在启动「听课之间」，请保留此终端窗口。'
printf '%s\n' 'Starting Lecture Atelier. Keep this Terminal open. Choose English / 中文 in the app header.'
printf '%s\n' '停止：先点击此终端，再按 Control+C（⌃C），不是 Command+C（⌘C，复制）。'
printf '%s\n' 'To stop: click this Terminal, then Control+C (⌃C), not Command+C (copy).'
printf '%s\n' '服务运行时可直接打开 http://127.0.0.1:8767，不必重复启动；停止后再次启动会保留数据。'
exec "$lecture_python" app.py --open

