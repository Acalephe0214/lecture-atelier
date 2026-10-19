#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
printf '%s\n' 'Lecture Atelier — Quick Start / 听课之间 · 快速开始'
printf '%s\n' 'First setup: confirm one project-local download, then automatic Python / PDF / Whisper setup.'
printf '%s\n' 'Need help or offline speech recognition? Open START-HERE.html or give this folder to Codex and ask it to read CODEX_SETUP.md.'
printf '%s\n' 'Stop the server with Control+C (⌃C), NOT Command+C (⌘C = copy). Keep this Terminal open while using the app.'
exec /bin/zsh ./bootstrap-mac.command
