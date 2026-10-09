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
- `fade_seconds`, `black_seconds`: 默认 `.4` 和 `.2`；必须帧对齐。
- `fade_overlap_seconds`: 默认 0，即原片结束后定格渐黑。可设置让渐黑覆盖原片尾部，不能超过渐黑时长。鱼灯基准为 `4/30`。
- `audio_tail_fade_seconds`: 末段音轨渐隐，默认 `.02`；鱼灯基准 `4/30`。中间接缝采用 5ms/20ms 短淡化。
- `existing_opening`: `status=unknown|none|present`, `body_start=秒`。none 必须从0开始；present 可保留0或经用户明确同意后指定替换起点。

`validate --plan PLAN` 检查哈希、边界与字段，**不会**判断文字证据真假。

## render

`render --plan PLAN --out NEW_DIR [--max-side 1920]`

默认不放大，最长边1920；0为原始尺寸。输出 `hook.mp4`, `hook.srt`, `plan.json`, `manifest.json`, `command.json`, `tail-events.txt`。所有目录必须全新；失败目录保留排错，下次换新目录。成片 H.264 yuv420p、AAC stereo 48kHz；多音轨仅取第一条。只支持常规 SDR、有音轨且无旋转元数据的视频；HDR/多声道保真不在 v0.1 范围。

技术检查包括全解码、时长/尺寸、黑屏及静音尾部事件。不能代替人工试听、字幕语义与吸引力审核。

## approve / prepend

```bash
python3 "$SKILL_DIR/scripts/run.py" approve --render ABS_PREVIEW_DIR --quote '用户对这个预览及前置的实际确认原话'
python3 "$SKILL_DIR/scripts/run.py" prepend --render ABS_PREVIEW_DIR --out ABS_NEW_FINAL_DIR
```

原片已有钩子时，额外 `--opening-quote '用户明确选择保留/替换原钩子的原话'`，计划中的 `body_start` 必须对应这次选择。不能编造引文代替用户确认。修改计划或视频后必须重新预览审批。

前置输出重编码为已批准钩子的尺寸和帧率，正文按计划起点完整接入，字幕整体延后；源文件不改。程序记录审批与哈希以避免版本串用，这是协作检查机制，不是防恶意篡改系统。
