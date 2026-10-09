# CLI 合约

所有命令通过 `python3 <skill>/scripts/run.py` 调用。Python 3.9+ 标准库，FFmpeg / ffprobe；不需要模型 SDK。CLI 不会自行语义选段。

## prepare

`prepare --video ABS_MP4 --srt ABS_SRT --out NEW_DIR [--samples 16]`

创建整片字幕、45 秒左右的重叠阅读窗口、全片均匀抽样帧、视频参数和 SHA-256，以及待填写计划。2–60 张抽样仅作导航，不能替代审片。拒绝 SRT 超出视频时长；同步仍需 Agent 人工核对。

## 计划

`plan.template.json` 提供字段：

- `source`: 视频/SRT 的绝对路径及 SHA-256，来自 prepare，不手工猜。
- `theme`, `theme_connection`, `surprise`, `preserved_meaning`: 必填文字证据。
- `segments`: `[[start_seconds,end_seconds],...]`，半开区间，按原片顺序、不可重叠、按输出帧率对齐。
- `fps`: 固定输出帧率，例如 `30` 或 `30000/1001`；VFR 以时间选取后重采样成 CFR。
- `fade_seconds`, `black_seconds`: 默认约 `.4` 和 `.2`，prepare 按源帧率取整到最近帧；必须帧对齐。
- `fade_overlap_seconds`: 默认 0，即原片结束后定格渐黑。可设置让渐黑覆盖原片尾部，不能超过渐黑时长。鱼灯基准为 `4/30`。
- `audio_tail_fade_seconds`: 末段音轨渐隐，默认 `.02`；鱼灯基准 `4/30`。中间接缝采用 5ms/20ms 短淡化。
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
