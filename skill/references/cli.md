# CLI 合约

所有命令通过 `python3 <skill>/scripts/run.py` 调用。Python 3.9+ 标准库，FFmpeg / ffprobe；外部字幕路径不需要模型；无字幕回退额外需要本地 `whisper-cli` 与 GGML 模型，不需要 Python 模型 SDK。CLI 不会自行语义选段。

## prepare

`prepare --video ABS_MP4 --out NEW_DIR [--srt ABS_SRT] [--samples 16] [--asr-model LOCAL_GGML] [--asr-language auto]`

创建整片字幕、45 秒左右的重叠阅读窗口、全片均匀抽样帧、视频参数和 SHA-256，以及待填写计划。2–60 张抽样仅作导航，不能替代审片。已有 SRT 沿用旧校验：末条不得超出视频时长 0.15 秒以上；同步仍需 Agent 人工核对。

### 字幕来源优先级

1. 显式 `--srt`：直接读取、校验、绑定原文件哈希，不调用 ASR；路径错误或字幕无效就报错。
2. 视频同目录 `<视频文件名去扩展名>.srt`：优先复用，不改变文件。
3. `asr/`、`edit/`、`edit/asr/` 中同名 `.srt`：仅当唯一时复用；多个不同路径匹配时要求显式 `--srt`。不递归扫描、不猜测“原始ASR”或历史版本文件。
4. 均不存在：提取第一条音轨为 16 kHz 单声道 PCM WAV，调用离线 `whisper-cli`，转成标准 SRT 后复用原流水线。保留音轨起始延迟与末尾静音；不做 VAD 删停顿或改变时间线。

同名字幕仍可能属于错误剪辑版本，必须审查同步。自动找到的字幕有错误时不跳过、不悄悄重新转写。

首次缺依赖时，CLI 会返回安装命令、模型直链和缓存路径；Agent 应按 [首次使用指引](asr-setup.md) 引导用户补齐，而不是仅说任务无法进行。

### 本地 ASR 配置

- `whisper-cli` 从 PATH 查找，使用其默认硬件后端；支持的语言值以本机 `whisper-cli --help` 为准，默认 `auto`，中文可显式 `--asr-language zh`。
- 模型优先级：`--asr-model` → `VIDEO_HOOK_ASR_MODEL` → 本地缓存。显式配置无效直接报错，不偷换模型。
- 缓存目录：`~/.cache/video-hook/models`、`~/.cache/whisper`、`~/.cache/hyperframes/whisper/models`。
- 精确匹配模型文件 `ggml-{small,base,tiny,medium,large-v3,large-v3-turbo,large-v2}.bin`，按此顺序查找；每个模型按上述目录顺序查找。优先复用较小多语种模型，不默认选英文专用模型。量化模型等其他文件名可通过参数显式指定。
- 本实现只接入 whisper.cpp；不宣称支持尚未实现的 mlx-whisper/faster-whisper 适配。不会自动下载模型、安装依赖、调用云端 ASR 或退回无字幕视觉模式。
- `doctor` 中 `local_asr.available` 仅表示发现了可执行文件和非空模型，不保证模型可加载或转写成功。

### 新增证据文件

- 所有路径新增 `subtitle-source.json`，注明 `explicit` / `sidecar` / `local_asr`、实际字幕路径及哈希；原有 `source.json`、计划 source 字段与下游 schema 不变。
- 仅 ASR 路径生成 `transcript.srt`（标准定位字幕），以及 `asr/audio.wav`、`raw.srt`、引擎 JSON、调用参数与 stdout/stderr 日志。记录模型路径/大小、语言请求与耗时，识别结果标为未人工审核。
- 自动转写必须产生可解析、非空、有序、正时长的 cues。超出视频结束超过 0.15 秒时报错；容差内尾端按视频时长裁齐并记录。失败保留工作目录排错，不生成可用计划。
- 不修正识别文字、不烧录新字幕；自动 SRT 可能与已烘焙文字不同。生成 SRT 被后续计划按路径和 SHA-256 绑定，必须保留，修改后须重建计划/预览。

## 计划

`plan.template.json` 提供字段：

- `source`: 视频/SRT 的绝对路径及 SHA-256，来自 prepare，不手工猜。
- `theme`, `theme_connection`, `surprise`, `preserved_meaning`: 必填文字证据。
- `segments`: `[[start_seconds,end_seconds],...]`，半开区间，按原片顺序、不可重叠、按输出帧率对齐。
- `fps`: 固定输出帧率，例如 `30` 或 `30000/1001`；VFR 以时间选取后重采样成 CFR。
- `fade_seconds`, `black_seconds`: 默认约 `.4` 和 `.2`，prepare 按源帧率取整到最近帧；必须帧对齐。
- `fade_overlap_seconds`: 默认 0，即原片结束后定格渐黑。可设置让渐黑覆盖原片尾部，不能超过渐黑时长。灯笼案例基准为 `4/30`。
- `audio_tail_fade_seconds`: 末段音轨渐隐，默认 `.02`；灯笼案例基准 `4/30`。中间接缝采用 5ms/20ms 短淡化。
- `existing_opening`: `status=unknown|none|present`, `body_start=秒`。none 必须从0开始；present 可保留0或经用户明确同意后指定替换起点。

`validate --plan PLAN` 检查哈希、边界与字段，**不会**判断文字证据真假。

## render

`render --plan PLAN --out NEW_DIR [--max-side 1920] [--body-seconds SECONDS]`

默认不放大，最长边 1920；0 为原始尺寸。`--max-side` 仅控制预览尺寸。

- 主要审核对象：`preview.mp4`、`preview.srt`，含钩子、A 版渐黑及正文开头。默认在正文 10–20 秒内选择最接近 15 秒的字幕结束点；没有合适字幕时取 15 秒，短视频最多接全片。可通过 `--body-seconds` 覆盖。时长向上对齐帧，声音边界仍需试听。
- 中间产物：`hook.mp4`、`hook.srt`。
- 复核记录：`plan.json`、`manifest.json`（schema 2）、`command.json`、`preview-command.json` 和接缝/正文首中尾抽帧。

所有工作目录必须全新；失败目录保留排错，下次换新目录。成片 H.264 yuv420p、AAC stereo 48kHz；多音轨仅取第一条。只支持常规 SDR、有音轨且无旋转元数据的视频；HDR/多声道保真不在 v0.1 范围。

技术检查包括全解码、精确帧数、时长/尺寸/帧率，以及黑场中心的像素与音频 RMS。不能代替人工试听、字幕语义与吸引力审核。

## approve / prepend

```bash
python3 "$SKILL_DIR/scripts/run.py" approve --render ABS_PREVIEW_DIR --quote '用户对这个预览及前置的实际确认原话'
python3 "$SKILL_DIR/scripts/run.py" prepend --render ABS_PREVIEW_DIR --out ABS_NEW_WORK_DIR
```

原片已有钩子时，额外 `--opening-quote '用户明确选择保留/替换原钩子的原话'`，计划中的 `body_start` 必须对应这次选择。不能编造引文代替用户确认。审批绑定计划、Hook、拼接预览、两份字幕及 manifest 的哈希；任一变化须重新渲染并确认。

旧 schema 1 仅钩子预览不能直接交付，需用新版本生成带正文的预览。若沿用用户已明确认可的同一选段与衔接方案，记录该实际反馈及本次完整拼接授权；不能把复用旧方案写成新样片已试听。

最终从原片重新读取选段与完整正文，按**原尺寸、原帧率一次编码**，不读取低清预览作为素材。计划帧率若与原片不一致会拒绝交付。保留正文中的钩子选段，原有烘焙字幕随画面保留，独立 SRT 中的正文时间整体后移。为保留容器尾部音频，必要时补不足一帧的定格尾帧。

`--out` 是全新的暂存/审计目录，保存 `final.mp4`、`final.srt`、命令、manifest 和检查抽帧。最终交付自动放到**原视频所在目录**：

- `原文件名_hook_v1.mp4`
- `原文件名_hook_v1.srt`
- `原文件名_hook_v1.json`（完成记录）

遇到任一同名文件，编号递增；不覆盖原片、源 SRT 或已有版本。先在工作目录编码、检查并复核源哈希，再向原片目录写入，JSON 完成记录最后出现。普通编码/复制异常会清理本轮未完成的交付文件，工作目录保留排错；进程被强制终止可能留下隐藏临时文件/锁，下次跳过该编号。程序记录审批与哈希以避免版本串用，这是协作检查机制，不是防恶意篡改系统。
