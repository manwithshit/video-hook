<p align="center"><img src="assets/readme/hero.svg" width="100%" alt="video-hook：提炼贴合主旨的连贯钩子；明基案例从22秒精简至14.1秒" /></p>

# video-hook

**从剪好的视频里，挑出让人想继续看正文的那一段。**

给 Agent 一份成片和匹配的 SRT，它理解整片主旨，挑出有结果、有反差或反常识的片段，保持原意做精剪。预览包含钩子与正文开头；你认可后，交付钩子与完整原片拼接的新成片。

`Private dogfood` · `本地 FFmpeg` · `一份环境，多个 Agent`

## 已认可的效果

| 案例 | 调整 | 人工反馈 |
|---|---|---|
| 明基 AI 工作台 | 22 秒完整对比 → **14.1 秒**；删去窗口用途说明和铺垫，保留前态、切换、结果与回切 | 用户确认跳剪衔接自然；五版转场对照后选择保留 A 版 |
| 徽州鱼灯 | **9.13 秒**；收音避开下一句，渐黑后保留黑屏 | 用户表示效果符合预期 |

这是两例人工校准，**尚无平台留存提升数据**。原始视频、字幕和样片仅留本机。[查看接受与淘汰的具体原因 →](skill/references/cases.md)

## 当前保留：A 版渐黑

**高亮结束 → 0.4 秒渐黑 → 0.2 秒纯黑 → 正文从 0 秒开始。**

明基对照预览在钩子后接了原片前 16.63 秒，用户选择保留 A 版。直接切黑、无黑场和深灰场暂不采用；这是当前个人偏好基准，不是平台效果结论。已有片头的原片仍须先确认正文起点。

## 哪些片段值得前置

- **先过主旨门槛。** 反差必须与产品或正文核心价值直接相连。
- **让对比看得见。** 作者的总结不代替具体结果；保留必要的前态、操作和结果。
- **可以精剪，不能改意。** 删解释、重复和铺垫，保持原声、因果与操作顺序。
- **完整比秒数重要。** 10 秒只是参考，表达自然可以更长。

工作流：`成片 + SRT → 理解整片 → 钩子及正文开头预览 → 用户确认 → 钩子 + 完整原片`

最终文件与原视频放在**同一文件夹**，另存为 `final_hook_v1.mp4`、`final_hook_v1.srt` 和 `final_hook_v1.json`；重名自动递增。正文默认从 0 秒完整接入，抽出的片段仍保留在正文。已有钩子时，先确认保留还是替换。源文件不覆盖。

## 安装一次

需要 Python 3.9+、FFmpeg 和 ffprobe。Python 运行时只用标准库，没有单独的模型 SDK。

```bash
gh repo clone manwithshit/video-hook
cd video-hook
python3 scripts/install.py
```

使用 Obsidian 统一管理 Skill 时：

```bash
python3 scripts/install.py --vault '/absolute/path/to/ObsidianMac'
```

安装器创建唯一 `.venv`，将 Claude Code、Codex、Antigravity 的 Skill 入口链接到同一源码。已有同名入口指向别处时会停止，不覆盖。每台 Mac 单独安装；iCloud 的目录同步不等于机器环境已安装。

## 直接开始

在 Agent 的新会话中输入：

> 使用 video-hook，分析这个成片和 SRT。先给我贴合主旨、连贯自然的钩子预览；允许不改变原意的精剪，不必限制在 10 秒，确认后再前置。

然后提供两个文件的绝对路径。Codex 可显式写 `$video-hook`；Claude Code 可使用 `/video-hook`。

<details>
<summary>脚本入口与可复查输出</summary>

```bash
python3 skill/scripts/run.py doctor
python3 skill/scripts/run.py prepare \
  --video '/absolute/final.mp4' \
  --srt '/absolute/final.srt' \
  --out '/absolute/hook-work-v1'
```

Agent 读取完整字幕和抽样画面，填写生成的计划，再执行：

```bash
python3 skill/scripts/run.py render \
  --plan '/absolute/plan.json' \
  --out '/absolute/hook-preview-v1' \
  --max-side 1920
```

复核 `preview.mp4`：钩子、A 版转场和约 10–20 秒正文；`hook.mp4` 仅为中间产物。用 `--body-seconds` 可指定正文预览时长。用户确认后：

```bash
python3 skill/scripts/run.py approve \
  --render '/absolute/hook-preview-v1' \
  --quote '用户对选段、衔接与完整前置的实际确认原话'
python3 skill/scripts/run.py prepend \
  --render '/absolute/hook-preview-v1' \
  --out '/absolute/hook-delivery-work-v1'
```

`--out` 保存命令、检查记录和暂存文件；最终成片自动另存在原视频同一文件夹。完整约定见 [CLI 合约](skill/references/cli.md)。

`--max-side` 只影响预览；最终从原片按原尺寸、原帧率一次编码。4K 原片可以用 1080p 预览，不会因此交付低清成片。

</details>

## 当前边界

- Agent 负责语义判断；脚本没有“爆款评分”，也不会独立决定最佳钩子。
- v0.1 面向 SDR 成片，输出 H.264/AAC；正文前置时重新编码。原画面中的烘焙字幕保留，不重复叠字幕。
- SRT 只作定位依据，不能代替听音。全解码、时长、黑屏/静音检测不等于人工听感验收。
- 暂不自动配音或追加音效；不裁画幅、不做 HDR 色彩转换。保留原视频第一音轨，输出 stereo 48kHz。
- Skill 会把字幕/抽样图片交给当前 Agent 理解；渲染脚本本身不联网、不上传媒体。

## 开源基础与验证

复用 [OpenShorts](https://github.com/mutonby/openshorts/tree/1ceb57d77d0429a8f526797287b3529757b31055) 的 MIT 字幕分窗函数，使用本机 [FFmpeg](https://ffmpeg.org/) 处理媒体。主旨筛选、精剪审批、渲染与共享安装是本项目的适配层。[来源与许可 →](THIRD_PARTY.md)

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖完整正文的画面、声音和字幕，低清预览后的原尺寸输出，分数帧率与竖屏，同目录版本命名，审批失效，已有片头处理及编码/写入失败保护。当前处于 Private Dogfood 阶段。[本次实际验证与未验证范围 →](VALIDATION.md)

## Dogfood 时看什么

1. **想继续看吗？** 钩子提出的疑问，要由正文主旨或产品价值兑现。
2. **对比完整吗？** 删除解释后，必要的前态、操作与结果仍然看得懂。
3. **接得自然吗？** 连看高亮、渐黑和正文开头，检查截字、带入下一句及重复开场。

每次记录通过或淘汰的具体原因，再调整选段；不以渲染成功代替人工判断。
