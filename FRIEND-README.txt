Lecture Atelier / 听课之间
分享包使用说明 · Detailed instructions · 2026-10-18

第一次使用请从这里开始：
1. 完整解压 ZIP，将 LectureAtelier 文件夹放在固定位置，例如“文稿”。
   不在 ZIP 中运行，不单独复制 HTML / .app，不覆盖旧使用目录。
2. 双击 START-HERE.html，用浏览器阅读入口。
   完整中文手册：FRIEND-GUIDE.html
   Complete English manual: FRIEND-GUIDE-EN.html
3. Mac 首次双击 setup-mac.command；Windows 10/11 x64 双击 setup-windows.bat。
   出现 [y/N] 后，确认信任来源、愿意下载，再输入 y 并按回车。
   首次约下载 0.5–1.5 GB，预留 2–4 GB；需 GitHub / PyPI / Hugging Face 可达。
   安装器在项目内准备 Python、PDF/音频依赖和多语言 Whisper small 模型。
   无需管理员权限，本地处理不需要 API key，也不上传录音。
4. 成功后打开 http://127.0.0.1:8767/，保留服务终端；没自动打开就手动访问。
5. 先用“探索虚构示例”，再用 30–60 秒的授权录音测试。
   新建课次 → 添加录音 → 选择录音语言 → 无稿时本地转写；有稿时直接导入。
   识别完成不等于识别准确；长课、专名和混合语言仍需回听。

以后怎么打开：
Mac 双击 launch.command；Windows 双击 launch-windows.bat。
服务还在、只关了网页：重新打开本地地址，不重复启动。
停止：点击服务终端，按 Control+C。
重启电脑或停止服务后，再运行 launch，不必重新安装。

输出语言与视频处理：
右侧“笔记输出语言”独立于界面/录音语言，可选中英法德越日或跟随原文；
“语言设置”窗口显示对应默认提示词。只影响下次生成，不自动改旧笔记。
MP4 / MOV / WEBM 本地转写先提取并缓存 16 kHz 单声道 WAV，之后再跑 Whisper；
原视频不覆盖，缓存约 110 MiB/小时，后续可复用；没有音轨会报错。

哪些功能需要联网 / 密钥：
导入、阅读、手工校对、已装好的本地 Whisper、降噪和本地导出不需模型 API。
首次下载依赖和权重需联网；PDF 需相应依赖，Word 不额外依赖 PDF 工具。
AI 校对 / 总结需要自己的兼容 Chat Completions API，可能收费、逐次确认。
Notion 需要自己的 connection token 和有权限的父页面，不是 LLM API key。
详见手册“API 三个字段”“校对与总结”“导出与 Notion”“故障排查”。

English quick path:
Unzip → START-HERE.html → FRIEND-GUIDE-EN.html.
First run: setup-mac.command (Mac) or setup-windows.bat (Windows x64).
Approve project-local downloads with y + Return only after reviewing the source.
Later: launch.command / launch-windows.bat. Keep Terminal open; stop with Control+C.
Installed local transcription needs no paid API. AI proofreading and summaries
require your own provider endpoint, model ID and API key.

回听编辑与阅读版导出 / Listening, editing and readable transcript export:
阅读视图每段都有“边听边改”：正常段落也能修改，播放器可暂停、调速、定位。
每句保留原编号和真实时间；只保存修改的句子，最初转写及修改历史仍保留。
修改后的句子重新标为未核查，关联的已核查笔记需要复核；不调用 AI。
中间“导出校对稿”选择版本与格式，默认“阅读版 · 合并成段落”。
可勾选每段起始时间，或切回逐句时间线。TXT 快捷导出也按阅读段落合并。
合并是机械排版，不是 AI 改写；SRT 保留逐句时间码，JSON 保留原句与段落映射。
Every reading paragraph has Listen and edit, including unflagged passages.
Save only changed sentences; original text, edit history and true timestamps remain.
Changed sentences become unreviewed and linked verified notes need review. No AI call.
Export transcript editions defaults to Reading: merged paragraphs. Optional paragraph
start times and the old Timeline layout are available. Quick TXT is readable too.
SRT keeps sentence timing; JSON retains source rows and paragraph mappings.

用量估算 / Usage planning:
用量预估分为详细笔记与总览阶段。仅总览保留现有笔记；未经人工编辑、仍待核查的
原句复制卡片只转成原文索引，避免重复发送正文。人工笔记与已核查笔记不这样处理。
总览也会读取笔记未引用到的原文。首轮分组复用实际执行计划；后续综合依赖模型返回，
因此用量仍只是区间，不是预算上限。全流程会重做详细笔记；预估不能预知其长度。
缺少笔记、来源无效或已知会超限时，先提示问题，不把它显示为“零费用任务”。
Stage estimates separate detail extraction from overview synthesis. Overview-only
keeps existing notes; untouched unreviewed source-copy cards become reference indexes
without duplicate source text. Human-edited or verified notes remain verbatim.
Uncited source passages are included too. First-pass grouping matches execution;
later levels depend on model responses. Full runs regenerate details, whose future
length is unknown. Estimates are not caps; blocked tasks are not zero-cost quotes.

如果请 Codex 协助 / If using Codex:
完整解压，把文件夹作为 Codex 项目打开，再复制 START-HERE.html 中的指令。
要求先读 AGENTS.md 和 CODEX_SETUP.md，先做只读检查，再验证基础服务。
下载前询问；不调用付费 API、上传录音、修改系统安全设置、覆盖 .runtime
或批量结束 Python。没有 Codex 也可以直接按上面的脚本路线使用。

数据与安全：
资料和密钥存在隐藏的 .runtime；不要删除或转发。
外部索引文件仍在原路径，也要单独备份；停止服务后再备份使用目录。
转发请用干净发行 ZIP，不是自己整个工作目录。
发行包仅含源码、说明和示例；模型与运行环境由安装器另行下载。
诊断下载可能含你的文本，分享前检查并脱敏。

已知限制：
这是首次联网安装包，不是预装模型的离线 .app/.exe。
Mac .app 只是未签名启动器，不可单独移出；不关闭防护或移除隔离。
Windows x64 脚本已提供，但未经 Windows 真机验证；Windows ARM64 不在范围。
默认跨平台 CPU faster-whisper；已有 Apple Silicon MLX 配置保留，不强制改装。
许可证与来源：THIRD-PARTY-NOTICES.txt。校验清单不是数字签名或安全审计。
