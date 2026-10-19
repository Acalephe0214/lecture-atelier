# 听课之间 · Lecture Atelier

一个本地录音、文字稿与可追溯笔记工作台。

[English](README.md) · [下载版本](https://github.com/Acalephe0214/lecture-atelier/releases) · [完整中文手册](FRIEND-GUIDE.html) · [架构说明](docs/ARCHITECTURE.md) · [验证范围](docs/VERIFICATION.md) · [路线图](docs/ROADMAP.md)

![虚构材料演示：原文与结构化笔记](docs/images/workspace.png)

面向课程、讲座、讨论和会议，将录音转为可编辑文字稿与结构化笔记，保留回听定位、修订记录和原文引用。

## 已有功能

- 上传音视频，或导入 TXT、SRT、VTT、支持的 JSON 转写。安装 Whisper 后可本地识别；原录音保留，支持断点、有限重试与明确的缺口标记。
- 每段都可以“边听边改”，暂停、调速、定位并修改文字。保留最初文字、时间码和修改记录；AI 校对建议可逐项接受或拒绝。
- 用自己配置的兼容 API 生成详细笔记与全局总览，单列重点、明确决策、行动及未决问题，并附原文来源。
- 导出段落阅读版原稿、修订稿、笔记和字幕；可选 Notion 单向导出，每次确认后新建子页面，不是双向同步。

中文／英文界面可切换；录音语言、界面语言和笔记输出语言分别设置。输出可选中文、英文、法语、德语、越南语、日语或跟随原文。

## 快速开始

需要 Python 3.10+。导入、阅读、手工校对等基础功能仅使用 Python 标准库。

在完整解压后的项目目录运行：

```sh
python3 app.py --open
```

浏览器地址为 <http://127.0.0.1:8767/>。Windows 可用 `py -3 app.py --open` 或 `launch-windows.bat`。应用内提供虚构示例。

### 按需安装

Mac 使用 `setup-mac.command`；Windows 10/11 x64 使用 `setup-windows.bat`。菜单默认选择基础模式，下载前确认。

| 模式 | 安装内容 |
| --- | --- |
| `basic` | 仅在缺少 Python 时下载运行环境，不下载依赖包或语音模型 |
| `pdf` | PDF 导出依赖，不下载语音模型 |
| `speech` | CPU Whisper 与音频工具；未配置语音后端时才下载模型 |
| `full` | PDF 与语音组件 |

语音安装可能需下载约 0.5–1.5 GB、预留 2–4 GB 磁盘。已有语音配置（包括 Apple Silicon MLX 路径）会保留；Mac 启动器不再以模型安装完成作为打开应用的前提。

详细步骤见 [中文手册](FRIEND-GUIDE.html)、[English guide](FRIEND-GUIDE-EN.html) 或 [首次试用](docs/TRY-IT.md)。

## API、隐私和限制

AI 校对和总结需在设置中填写兼容 Chat Completions 的 API 根地址、模型 ID 和密钥；程序追加 `/chat/completions`，发送文字前需确认。Notion 另需 connection token 与授权父页面，每次导出新建子页面。

录音和应用数据保存在本地；选择外部功能时，相应文字或录音会发送到指定服务。API 密钥保存在本地配置中，未做应用层加密。详见 [隐私说明](PRIVACY.md)。

转写与总结需人工核查。文字校对依赖文字上下文而非录音，原文引用也不保证语义准确；token 和价格为近似预估。现有软件测试主要使用合成材料和模拟接口，尚无公开的转写／总结质量基准。Linux、macOS、Windows 托管 CI 已通过，包括已有 Python 的基础安装；全新 Windows 用户安装及语音依赖安装仍待验证，不支持 Windows ARM64。见 [验证范围](docs/VERIFICATION.md)。

辅助课件和个人笔记上传列入后续计划，见 [路线图](docs/ROADMAP.md)。

## 开发与许可

[架构说明](docs/ARCHITECTURE.md) 介绍模块分工；[验证说明](docs/VERIFICATION.md) 提供测试命令；[源码打包](docs/PUBLISHING.md) 介绍发行工具。

项目源码采用 [MIT](LICENSE)。Whisper 等第三方项目和模型保持各自许可，见 [第三方声明](THIRD-PARTY-NOTICES.txt) 与 [许可证副本](licenses/README.md)。源码仓库不含第三方运行环境、模型权重或字体。项目使用 AI 辅助开发，本地识别接入上游 Whisper 实现。
