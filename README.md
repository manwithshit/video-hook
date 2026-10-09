<p align="center"><img src="assets/readme/hero.svg" width="100%" alt="video-hook：提炼贴合主旨的连贯钩子；明基案例从22秒精简至14.1秒" /></p>

# video-hook

**从剪好的视频里，挑出让人想继续看正文的那一段。**

给 Agent 一份成片和匹配的 SRT，它理解整片主旨，挑出有结果、有反差或反常识的片段，保持原意做精剪。你认可预览后，再前置到正文。

`Private dogfood` · `本地 FFmpeg` · `一份环境，多个 Agent`

## 两次实际校准

| 案例 | 调整 | 人工反馈 |
|---|---|---|
| 明基 AI 工作台 | 22 秒完整对比 → **14.1 秒**；删去窗口用途说明和铺垫，保留前态、切换、结果与回切 | 用户确认跳剪衔接自然 |
| 徽州鱼灯 | **9.13 秒**；收音避开下一句，渐黑后保留黑屏 | 用户表示效果符合预期 |

这是两例人工校准，**尚无平台留存提升数据**。原始视频、字幕和样片仅留本机。[查看接受与淘汰的具体原因 →](skill/references/cases.md)

## 哪些片段值得前置

- **先过主旨门槛。** 反差必须与产品或正文核心价值直接相连。
- **让对比看得见。** 作者的总结不代替具体结果；保留必要的前态、操作和结果。
- **可以精剪，不能改意。** 删解释、重复和铺垫，保持原声、因果与操作顺序。
- **完整比秒数重要。** 10 秒只是参考，表达自然可以更长。

工作流：`成片 + SRT → 理解整片 → 候选精剪 → 用户确认 → 渐黑钩子 + 正文`

已有片头时，先确认保留还是替换。所有输出写入新目录，源文件不覆盖。

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

输出包括 MP4、重映射 SRT、选段计划、FFmpeg 命令、哈希和技术检查结果。用户明确确认后执行 `approve` 与 `prepend`，详见 [CLI 合约](skill/references/cli.md)。

`--max-side 0` 保持原尺寸；前置成片沿用已批准钩子的尺寸。要交付 4K，就先以原尺寸制作预览。

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

测试覆盖中文字幕解析/时间重映射、真实 FFmpeg 预览及前置、审批缺失/过期、错误切点与源文件变更保护。当前处于私人 dogfood 阶段。[本次实际验证与未验证范围 →](VALIDATION.md)
