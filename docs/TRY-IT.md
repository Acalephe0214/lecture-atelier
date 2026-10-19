# First-use trial / 首次试用

Use a new extracted package, not another person's used app folder. Download versions from [Releases](https://github.com/Acalephe0214/lecture-atelier/releases); version and known limits accompany each release.

## Basic trial — no model or API required

1. Extract the entire ZIP to a writable folder. Open `START-HERE.html` for the complete manual.
2. Mac: open `LectureAtelier.app` or `launch.command`. Windows x64: open `launch-windows.bat`. If Python is missing, basic setup asks to download only the project-local runtime.
3. In the browser, choose English or Chinese. Open **Explore fictional demo**.
4. Edit a sentence, save it, then refresh and check that the change persists.
5. Export the transcript as TXT or a revised Word document. Check that the edited text is present.
6. Stop the service and reopen it. Check that the saved session remains.

Expected: this route does not install Whisper or download model weights. Local imports, edits and non-PDF exports need no API. A working Python is required; OS security controls remain enabled.

## Optional speech trial

Run setup again and select **speech** (PDF is a separate profile). Confirm its download notice. Use a short recording you are allowed to process, select its language, transcribe locally, listen and compare. Record recognition errors separately from installation failures. No cloud API is required.

## Trial record

Copy this into an [installation report](https://github.com/Acalephe0214/lecture-atelier/issues/new/choose) or send it privately after removing sensitive details:

```text
Version:
OS / CPU / browser:
Existing Python, or runtime downloaded:
Selected profile:
Basic startup: pass / fail / not tried
Demo edit and export: pass / fail / not tried
Close and reopen: pass / fail / not tried
Optional speech setup: pass / fail / not tried
Optional speech inference: pass / fail / not tried
First step that needed help:
Elapsed setup time (optional):
Redacted error and reproduction steps:
```

## 中文简版

完整解压后，Windows 双击 `launch-windows.bat`；Mac 打开 `.app` 或 `launch.command`。缺 Python 时仅安装基础运行环境，不下载语音模型。先用虚构示例完成“修改一句 → 保存刷新 → 导出 → 关闭重开”。需要转写时再运行 setup，选择 speech 并确认下载。反馈版本、系统、卡住步骤和脱敏错误即可，不发送 `.runtime`、密钥、私人录音或文字稿。

A trial report is usability evidence, not a speech-quality benchmark. Mark unattempted steps explicitly.
