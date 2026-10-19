# Publishing this source / 上传说明

This document prepares a source repository; it does not authorize an automatic push or public upload.

## Safe starting point

Use the fresh `lecture-atelier` source folder produced by `prepare_github.py`. Do not upload your used installation directory, copy an old `.git`, or add your `.runtime/`. The generated archive has an explicit file list and checksums; the scanner is a guardrail, not a complete secret audit.

```sh
python3 prepare_github.py --output ../output/github/lecture-atelier --zip ../output/github/lecture-atelier-source.zip
```

Both targets must be new. Inspect the directory, `SOURCE-MANIFEST.json`, the screenshot, and all text before uploading. The example materials and screenshot must remain fictional. The MIT license covers project source only; keep third-party notices and `licenses/`.

## GitHub website route

1. Create a repository named `lecture-atelier` in your own GitHub account. Visibility is your decision. If uploading this prepared tree, do not create a different README/license in the website wizard.
2. Use the repository's file-upload option and include the contents of the prepared folder, including the required dotfiles. Do not upload the whole parent workspace or `.git`.
3. Check the English README, Chinese README and image render correctly. The suggested description is: “Local-first recording-to-notes workspace with transcript review, source-linked summaries and optional Whisper.”
4. Do not add API keys for a demonstration. The built-in fictional demo and local basic app need no paid API. A workflow file can run only after publication/configuration; do not add a green CI badge before observing a real successful run.

## Git route

Use Git only in the prepared source folder, not in its parent personal workspace. Inspect `git status --short` and the staged diff before committing. Choose the author identity/email that you want in public commits. No commit identity, remote, credentials or public upload is configured by the preparation script.

```sh
git init
git add .
git diff --cached --stat
git diff --cached
# Commit only after reviewing the staged material and your public author identity.
```

Then follow the new repository's own remote/push instructions. Never force-push or rewrite an existing remote just to upload this project. The clean ZIP contains no old Git history.

## Before every later release

- Rebuild with the allowlisted source exporter; do not recursively ZIP a working folder.
- Check new examples, filenames, screenshots and logs for privacy leaks.
- Exclude installed runtimes, weights and FFmpeg binaries. A future offline binary release needs its own dependency/build/license review; adding license links alone is not enough.
- Keep claims proportional to evidence: distinguish software checks, model-quality evaluation and actual hardware tests.

中文：本轮只准备可上传文件，不会替你登录、创建远端或推送。上传前再次确认可见性；检查文件和 Git 历史，勿把自己的运行目录、密钥、录音或真实课件混进去。
