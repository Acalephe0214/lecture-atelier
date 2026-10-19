#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
printf '%s\n' 'Lecture Atelier · first setup / 首次安装' 'Downloads official Python if needed, local Whisper + PDF tools, and a multilingual model (~0.5–1.5 GB including dependencies).' '首次需要网络和约 2–4 GB 磁盘空间；不会上传录音，不需要 sudo，不改系统 Python。' 'This folder is not a signed native app. Only proceed if you trust its source.'
read -r 'lecture_consent?Download and install into this folder? 输入 y 同意 [y/N]: '
if [[ "$lecture_consent" != [yY] ]]; then exit 0; fi
lecture_python=""
for lecture_candidate in "$PWD/.portable/python/bin/python3" "$PWD/.venv/bin/python3" python3.12 python3; do
  if command -v "$lecture_candidate" >/dev/null 2>&1 && "$lecture_candidate" -c 'import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 1)' >/dev/null 2>&1; then lecture_python="$lecture_candidate"; break; fi
done
if [ -z "$lecture_python" ]; then
  lecture_arch="$(uname -m)"
  case "$lecture_arch" in
    arm64) lecture_hash='9866e11cf2ae9caa1e671383786f248859a52dd8bfb702fb4c0dc2c65f1d36de'; lecture_target='aarch64-apple-darwin';;
    x86_64) lecture_hash='d09998f85752b646873a8a6bc7eea442a0d251b1c8d2413aa8ea06ef131c3335'; lecture_target='x86_64-apple-darwin';;
    *) printf '%s\n' 'Unsupported Mac architecture'; exit 1;;
  esac
  mkdir -p .portable
  lecture_archive="$PWD/.portable/python-download.tar.gz"
  curl --fail --location --proto '=https' --retry 2 --connect-timeout 20 --output "$lecture_archive" "https://github.com/astral-sh/python-build-standalone/releases/download/20261013/cpython-3.12.15%2B20261013-${lecture_target}-install_only_stripped.tar.gz"
  lecture_actual="$(shasum -a 256 "$lecture_archive" | cut -d ' ' -f 1)"
  if [ "$lecture_actual" != "$lecture_hash" ]; then printf '%s\n' 'Python checksum mismatch; stopped.'; exit 1; fi
  tar -xzf "$lecture_archive" -C .portable
  lecture_python="$PWD/.portable/python/bin/python3"
fi
"$lecture_python" bootstrap.py --install
exec /bin/zsh ./launch.command
