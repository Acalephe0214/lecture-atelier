# 听课之间 · Lecture Atelier

一个本地录音、文字稿与可追溯笔记工作台。

[English](README.md) · [完整中文手册](FRIEND-GUIDE.html) · [架构说明](docs/ARCHITECTURE.md) · [验证范围](docs/VERIFICATION.md) · [路线图](docs/ROADMAP.md)

![虚构材料演示：原文与结构化笔记](docs/images/workspace.png)

目标不是再做一个“一键摘要”，而是保留录音、回听改字、审核 AI 修改，让笔记能回到原文。适合课程、讲座、讨论和会议；生成结果始终需要人工核查。

## 已有功能

- 上传音视频，或导入 TXT、SRT、VTT、支持的 JSON 转写。安装 Whisper 后可本地识别；原录音保留，支持断点、有限重试与明确的缺口标记。
- 每段都可以“边听边改”，暂停、调速、定位并修改文字。保留最初文字、时间码和修改记录；AI 校对建议可逐项接受或拒绝。
- 用自己配置的兼容 API 生成详细笔记与全局总览，单列重点、明确决策、行动及未决问题，并附原文来源。
- 导出段落阅读版原稿、修订稿、笔记和字幕；可选 Notion 单向导出，每次确认后新建子页面，不是双向同步。

中文／英文界面可切换；录音语言、界面语言和笔记输出语言分别设置。输出可选中文、英文、法语、德语、越南语、日语或跟随原文。

## 先运行基础版本

需要 Python 3.10+，本机开发基线为 Python 3.12。导入、阅读、手工校对等基础功能不需要 npm、Codex、API key 或额外 Python 包。

在完整解压后的项目目录运行：

```sh
python3 app.py --open
```

Windows 已安装 Python 时可用 `py -3 app.py --open` 或双击 `launch-windows.bat`。地址通常是 <http://127.0.0.1:8767/>。保留终端，用 **Control+C** 停止，不是 Command+C。不要直接打开 `static/index.html`。

新环境没有私人课次；“探索虚构示例”只创建一份可选合成演示。

### 本地识别与 PDF

Mac 使用 `setup-mac.command`；Windows 10/11 x64 使用 `setup-windows.bat`。先阅读提示，再确认下载。安装器在项目目录准备依赖和多语言 Whisper small 模型，预留约 2–4 GB；首次需联网，之后本地识别不需要付费 API。它不是已经装好模型的离线安装包。

默认便携方案为 CPU faster-whisper；已有 Apple Silicon MLX Whisper 配置可保留。Windows 脚本尚未经 Windows 真机验收，Windows ARM64 不在打包范围。Mac `.app` 只是未签名启动器，不可单独移出；不要为运行它而关闭系统防护。

详见 [使用手册](FRIEND-GUIDE.html) 和 [交给 Codex 等工具的安装说明](CODEX_SETUP.md)。

## API、隐私和限制

API 留空也能用基础功能。AI 校对和总结需要自己的 API 根地址、精确模型 ID 和密钥；程序追加 `/chat/completions`。保存配置不发送材料，每次外发需要确认，可能收费。Notion 另需 connection token 与授权父页面。

本地识别不上传音频，但文字模型会收到相关原文和背景；资料和密钥存在本地 `.runtime/`。这不是“所有功能永远离线”或“密钥已加密”的承诺。先读 [隐私说明](PRIVACY.md)，确认你有权处理资料。

转写和总结可能有错；缺口检测、来源编号和引用校验都不能证明语义正确。文字校对模型没有听录音。用量预估不是预算上限。目前没有完整的真实语音／总结质量评测集或公开准确率指标。现有功能测试主要使用合成材料和模拟接口，见 [验证范围](docs/VERIFICATION.md)。

**辅助课件和个人笔记上传尚未实现。** 下一步计划把 PDF／PPTX 课件和 TXT／Markdown 笔记独立作为参考材料，保留页码、来源，不混入录音原文。见 [路线图](docs/ROADMAP.md)。

## 开发、分享与许可

[架构说明](docs/ARCHITECTURE.md) 解释各程序的职责；[发布说明](docs/PUBLISHING.md) 说明如何检查和上传干净源码。不要提交 `.runtime/`、真实录音／文字稿、数据库、诊断、API key、模型权重或依赖环境。

项目源码采用 [MIT](LICENSE)。Whisper 等第三方项目和模型保持各自许可，见 [第三方声明](THIRD-PARTY-NOTICES.txt) 与 [许可证副本](licenses/README.md)。源码仓库不含第三方运行环境、权重或字体；本项目接入上游模型，没有训练新的语音模型。代码使用了 AI 编程辅助。
