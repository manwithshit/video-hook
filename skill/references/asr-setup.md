# 首次使用：没有字幕时，先准备本地识别引擎和模型

如果已有同一成片时间线的 SRT，可直接传 `--srt`，无需安装模型。否则 `prepare` 需要两个条件：`whisper-cli` 可运行，以及本地存在可加载的 GGML 模型。

Agent 先运行 `doctor`，复用已有模型；发现缺项时给用户明确指引，不只返回“缺少模型”。在用户尚未授权安装/下载时，提供以下步骤与下载量；已有该授权则可直接执行并核验。不要为了省略字幕输入而偷偷上传媒体到云端。

## 1. 安装识别引擎（仅缺少时）

macOS 已安装 Homebrew 的用户：

```bash
brew install whisper.cpp
```

没有 Homebrew 或在其他平台时，按 [whisper.cpp 官方构建说明](https://github.com/ggml-org/whisper.cpp#quick-start) 安装，使 `whisper-cli` 出现在 PATH。安装引擎不会附带下载模型。

## 2. 下载多语种 small 模型（仅没有可复用模型时）

推荐起步使用 `ggml-small.bin`，约 **488 MB（466 MiB）**，支持多语种；中文不要误选 `small.en`。这是资源占用与中文任务需求之间的默认选择，不是精度或速度保证。本轮真实转写验证使用的是已缓存的 large-v3；未将 small 的质量或性能标为已实测。

- [官方托管模型页面](https://huggingface.co/ggerganov/whisper.cpp/blob/main/ggml-small.bin)
- [直接下载 ggml-small.bin](https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin)

浏览器下载后，将完整文件放到 `~/.cache/video-hook/models/ggml-small.bin`，或保留原位置，在 prepare 中用 `--asr-model /实际路径/ggml-small.bin`。

也可在 macOS 终端执行以下步骤；先下载到 `.part`，校验成功再改名，不覆盖已有模型：

```bash
mkdir -p "$HOME/.cache/video-hook/models"
if [ -e "$HOME/.cache/video-hook/models/ggml-small.bin" ]; then
  echo '模型已存在；先核验或复用，不重复下载。'
else
  curl --fail --location --retry 3 \
    --output "$HOME/.cache/video-hook/models/ggml-small.bin.part" \
    'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin' &&
  printf '%s  %s\n' \
    '1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b' \
    "$HOME/.cache/video-hook/models/ggml-small.bin.part" | shasum -a 256 -c - &&
  mv -n "$HOME/.cache/video-hook/models/ggml-small.bin.part" \
    "$HOME/.cache/video-hook/models/ggml-small.bin"
fi
```

校验失败不要改名使用；检查网络或模型来源。已有模型可用 `shasum -a 256 /实际路径/ggml-small.bin` 对照上面的 SHA-256。指引中的模型大小、下载链接与校验值来自官方托管页，核对日期 2026-10-19。

## 3. 再检查并重跑

```bash
python3 "$SKILL_DIR/scripts/run.py" doctor
python3 "$SKILL_DIR/scripts/run.py" prepare \
  --video /absolute/final.mp4 --out /absolute/new-hook-work
```

`SKILL_DIR` 替换为本次实际加载的 Skill 目录。doctor 显示可发现依赖不等于识别已经通过；实际 prepare 加载模型、产生字幕并通过校验后才算成功。若先前已创建失败目录，重试时换一个全新的 `--out`。

ASR 在本机运行。首次下载模型需要网络，之后可复用本地文件，不需要每条视频重新下载。抽样核对人名、数字与声音边界；不要把自动字幕直接当成已校对字幕。

来源：[whisper.cpp 模型说明](https://github.com/ggml-org/whisper.cpp/blob/master/models/README.md)、[Homebrew 安装说明](https://formulae.brew.sh/formula/whisper.cpp)。
