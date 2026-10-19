<p align="center"><img src="assets/readme/hero.svg" width="100%" alt="video-hook：只提供成片，复用字幕或本地转写，先看预览再确认前置" /></p>

# video-hook

**从已剪好的视频里，提炼一段预告式开头。**

把成片交给 Agent，说清楚视频主题。它结合字幕和画面，寻找有具体结果、反差或前后变化的片段，剪出带正文开头的预览；你选定并确认后，再接到完整原片前面。

**SRT 可选。** 有匹配字幕就复用，没有则调用本地语音识别。首次没有识别引擎或模型时，需要先按提示补齐，不能跳过这一步直接剪辑。

## 你会得到什么

- 通常 1–3 个有意义的候选；素材只适合一条就只做一条，没有合适片段也会说明。
- 每条预览包含候选片段、渐黑转场与正文开头，供你连着看、连着听。
- 确认后的新成片、调整时间后的独立 SRT 和处理记录，另存在原片同目录：`final_hook_v1.mp4`、`final_hook_v1.srt`、`final_hook_v1.json`。重名递增，不覆盖原文件。

正文默认从 0 秒完整保留，抽出的片段仍留在正文里；已有片头是否替换由你决定。默认不生成 HTML 候选页，也不输出可编辑的剪映工程。

## 安装

当前验证环境为 **macOS / Apple Silicon**。需要可访问本仓库的 GitHub 账号、Python 3.9+、FFmpeg 和 ffprobe。仓库目前为私有开发验证项目，不代表已公开开源；[许可与依赖说明](THIRD_PARTY.md)。

**请克隆完整仓库，再运行安装器。不要只复制 `skill/` 文件夹。** 启动器依赖仓库里的共享运行环境和安装脚本。

macOS 已有 Homebrew、但还没有 FFmpeg 时：

```bash
brew install ffmpeg
```

安装 Skill（克隆的是默认分支）：

```bash
gh repo clone manwithshit/video-hook
cd video-hook
python3 scripts/install.py
```

安装器创建仓库内唯一的 `.venv`，将 Claude Code、Codex、通用 Agents 与 Antigravity 的入口链接到同一份源码。已有同名入口指向别处时会停止，不覆盖。它**不自动安装 ASR 引擎或下载模型**；安装成功也不等于视频转写环境已就绪。

更新已有安装时，在完整仓库目录执行 `git pull --ff-only`，再运行 `python3 scripts/install.py`。旧的功能分支安装不会因此自动切到默认分支；先核对当前分支。

<details>
<summary>可选：将 Obsidian Vault 作为统一 Skill 入口</summary>

```bash
python3 scripts/install.py --vault '/absolute/path/to/ObsidianMac'
```

每台电脑单独准备运行环境；同步 Skill 文件不等于另一台机器已安装依赖。

</details>

## 第一次只给视频，会发生什么？

Agent 先检查运行环境，并查找字幕。你不需要自己先导出 SRT。

| 当前条件 | 下一步 |
|---|---|
| 提供了匹配 SRT，或找到同名 SRT | 直接使用，不调用语音模型；仍需确认字幕与成片同步 |
| 没有字幕，但已有 `whisper-cli` 与本地模型 | 提取音频，本地转写，再进入选段流程 |
| 缺 `whisper-cli` | 停止转写，提示安装引擎 |
| 有引擎，但没有本地模型 | 停止转写，提供模型下载地址、存放位置及重试说明 |
| 模型加载失败、转写为空或字幕有歧义 | 返回错误与诊断信息，不用视觉猜段代替成功结果 |

首次建议使用多语种 `small` 模型；**安装引擎不会附带模型**。完整步骤、下载量、校验与失败处理见 [首次使用指引](skill/references/asr-setup.md)。这里需要的是语音识别模型，不需要另装聊天大模型。

当前脚本只检查并给出指引，不会自动下载或补齐后自动续跑。Agent 在获得安装/下载授权后可按指引操作，再重新运行。`doctor` 只能确认文件和程序被发现，不保证模型加载或识别质量。

## 使用

对 Agent 说：

> 使用 video-hook，给这条已剪好的视频做预告式开头。主题是……。有匹配字幕就复用，没有就本地转写；首次缺依赖时先说明需要安装什么。先剪出候选预览给我看，等我选定并确认后再接到完整原片前面。

提供视频文件或实际本地路径即可。有匹配字幕也可以一起提供。Codex 可使用 `$video-hook`，Claude Code 可使用 `/video-hook`。

流程：**成片 → 复用字幕或本地转写 → 理解主题与画面 → 候选预览 → 本人确认 → 完整前置**。

Agent 判断哪些片段值得选；脚本执行具体的剪辑计划。10 秒只是参考，不为压时长删掉必要条件，也不把多步操作剪成“一步完成”。

<details>
<summary>CLI 与输出记录</summary>

```bash
python3 skill/scripts/run.py doctor
python3 skill/scripts/run.py prepare \
  --video '/absolute/final.mp4' \
  --out '/absolute/new-hook-work'
```

已有字幕可加 `--srt /absolute/final.srt`；本地模型可用 `--asr-model /absolute/ggml-small.bin` 指定。无参数时只查找约定的本地缓存，不全盘搜索、不自动下载。输入优先级、缓存目录与日志见 [CLI 合约](skill/references/cli.md)。

Agent 阅读整份字幕和画面抽样，填写计划，再执行：

```bash
python3 skill/scripts/run.py render \
  --plan '/absolute/plan.json' \
  --out '/absolute/new-hook-preview' \
  --max-side 1920
```

审核 `preview.mp4`，其中包含钩子、转场及约 10–20 秒正文；`hook.mp4` 是中间产物。只有取得真实确认后才执行：

```bash
python3 skill/scripts/run.py approve \
  --render '/absolute/new-hook-preview' \
  --quote '用户对选段、衔接与完整前置的实际确认原话'
python3 skill/scripts/run.py prepend \
  --render '/absolute/new-hook-preview' \
  --out '/absolute/new-delivery-work'
```

已有片头时，另记录用户保留/替换的决定。所有工作目录必须全新；失败目录保留用于诊断。自动转写的 SRT 是后续计划的哈希绑定输入，需要保留。

`--max-side` 只控制预览。最终从原素材按原尺寸与帧率重新编码，不用低清预览作为成片输入；不是无损流复制。

</details>

## 能力边界与隐私

- 支持有音轨的常规 SDR 视频；输出 H.264/AAC。暂不支持无音轨素材、纯视觉降级、HDR 色彩处理或单独音频文件输入。
- 原画面中的烘焙字幕保留；ASR 根据声音生成独立字幕，不读取、修复或重新烧录画面文字。识别人名、数字和时间边界仍需核对。
- 不保证找到“最佳片段”，不保证每次有多个候选，不自动追加配音、音乐或卡点特效。
- 默认尾部约 0.4 秒渐黑加 0.2 秒黑场；是否顺畅仍需试听。技术检查不代替听感与内容判断，也没有平台完播率提升承诺。
- ASR 和视频处理在本机进行，不上传媒体到转写服务；首次下载模型需要网络。字幕和抽样图片交给当前 Agent 理解，其数据处理方式由你使用的 Agent 决定，不能因此宣称整套工作流完全离线。

## 验证与来源

- 22 项自动测试通过，覆盖显式字幕回归、查找歧义、ASR 失败、音轨延迟、哈希与确认绑定、完整正文保留及版本化输出。
- M5 上用已缓存 large-v3 对 205.4 秒成片进行了无 SRT 转写，并用独立 30 秒副本完成真实 ASR → 预览 → 完整前置验证。推荐的 small 模型性能和精度未在本轮实测。
- 首次使用隔离审查覆盖缺引擎、缺模型、损坏模型及安装布局；尚未在另一台空白电脑完成从下载到推理的整套验收。
- 历史人工校准案例与技术验证范围分开记录：[案例说明](skill/references/cases.md) · [验证记录](VALIDATION.md)。原始媒体、个人运行日志与测试输出不进入仓库。

```bash
python3 -m unittest discover -s tests -v
```

使用 [FFmpeg](https://ffmpeg.org/) 处理媒体、[whisper.cpp](https://github.com/ggml-org/whisper.cpp) 进行本地转写，并复用 [OpenShorts](https://github.com/mutonby/openshorts/tree/1ceb57d77d0429a8f526797287b3529757b31055) 的字幕分窗函数。仓库不分发引擎或模型权重。[第三方来源与许可](THIRD_PARTY.md)。
