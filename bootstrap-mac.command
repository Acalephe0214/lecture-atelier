#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
lecture_profile=""
lecture_yes=0
lecture_no_launch=0
while (( $# )); do
  case "$1" in
    --profile) (( $# >= 2 )) || exit 2; lecture_profile="$2"; shift 2;;
    --yes) lecture_yes=1; shift;;
    --no-launch) lecture_no_launch=1; shift;;
    *) printf '%s\n' "Unknown setup option: $1"; exit 2;;
  esac
done
printf '%s\n' 'Lecture Atelier · Setup / 安装'
if [ -z "$lecture_profile" ]; then
  if (( lecture_yes )); then
    lecture_profile=basic
  else
    printf '%s\n' '1 · Basic / 基础体验（不下载模型） [default]' '2 · PDF export / 仅 PDF' '3 · Local Whisper / 仅本地语音' '4 · PDF + Whisper / 全部可选功能'
    read -r 'lecture_selection?Choose / 选择 [1]: '
    case "${lecture_selection:-1}" in
      1) lecture_profile=basic;; 2) lecture_profile=pdf;; 3) lecture_profile=speech;; 4) lecture_profile=full;;
      *) printf '%s\n' 'Invalid selection.'; exit 2;;
    esac
  fi
fi
case "$lecture_profile" in basic|pdf|speech|full) ;; *) printf '%s\n' 'Invalid setup profile.'; exit 2;; esac
lecture_python=""
lecture_version_check='import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] else 1)'
if [ "$lecture_profile" != basic ]; then
  lecture_version_check='import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 1)'
fi
for lecture_candidate in "$PWD/.portable/python/bin/python3" "$PWD/.venv/bin/python3" python3.12 python3; do
  if command -v "$lecture_candidate" >/dev/null 2>&1 && "$lecture_candidate" -c "$lecture_version_check" >/dev/null 2>&1; then lecture_python="$lecture_candidate"; break; fi
done
if [ -z "$lecture_python" ] || [ "$lecture_profile" != basic ]; then
  printf '%s\n' "Selected profile: $lecture_profile" 'Downloads stay in this project. No audio upload, administrator rights or system-Python changes.'
  if [ "$lecture_profile" = basic ]; then
    printf '%s\n' 'Only the pinned Python runtime will be downloaded; no speech model.'
  elif [ "$lecture_profile" = pdf ]; then
    printf '%s\n' 'PDF dependencies only; no speech model. Python is downloaded only if needed.'
  else
    printf '%s\n' 'Speech dependencies and Whisper small may require 0.5–1.5 GB download and 2–4 GB disk; an existing speech configuration is retained.'
  fi
  if (( ! lecture_yes )); then
    read -r 'lecture_consent?Download into this folder? 输入 y 同意 [y/N]: '
    [[ "$lecture_consent" == [yY] ]] || exit 0
  fi
fi
if [ -z "$lecture_python" ]; then
  if [ -e .portable/python ] || [ -L .portable ] || [ -L .portable/python ]; then
    printf '%s\n' 'Existing runtime path is incompatible or unsafe; nothing was overwritten.'; exit 1
  fi
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
"$lecture_python" bootstrap.py --install --profile "$lecture_profile"
if (( ! lecture_no_launch )); then exec /bin/zsh ./launch.command; fi
