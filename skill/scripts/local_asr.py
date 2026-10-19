"""Optional offline whisper.cpp adapter; never installs or downloads anything."""
import os
import shutil
import subprocess
import time
from pathlib import Path


def setup_guidance():
    return (
        '\n首次使用指引：有匹配字幕可传 --srt，免装模型。没有字幕时：\n'
        '1. 缺识别引擎：macOS 已有 Homebrew 可执行 brew install whisper.cpp。\n'
        '2. 缺模型：建议先下载多语种 ggml-small.bin（约 488 MB / 466 MiB）：\n'
        '   https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin\n'
        '   放到 ~/.cache/video-hook/models/ggml-small.bin，或用 --asr-model 指定位置。\n'
        '3. 下载完成并校验后，重试原来的 prepare 命令。\n'
        '下载/校验步骤：' + str(Path(__file__).resolve().parents[1] / 'references/asr-setup.md') + '\n'
        '本命令不会自动安装或下载；已有可复用模型时无需重复下载。')


def discover_srt(video, explicit=None):
    if explicit is not None:
        return Path(explicit).expanduser().resolve(), 'explicit'
    direct = video.with_suffix('.srt')
    if direct.is_file():
        return direct.resolve(), 'sidecar'
    # Do not recursively pick a raw-timeline or previous hook subtitle.
    matches = sorted({(video.parent / folder / direct.name).resolve()
                      for folder in ('asr', 'edit', 'edit/asr')
                      if (video.parent / folder / direct.name).is_file()})
    if len(matches) > 1:
        raise ValueError('Multiple same-name SRT files; choose one with --srt: '
                         + ', '.join(map(str, matches)))
    return (matches[0], 'sidecar') if matches else (None, 'local_asr')


def resolve_backend(model=None):
    binary = shutil.which('whisper-cli')
    if not binary:
        raise ValueError('No SRT found and whisper-cli is missing. Install whisper.cpp '
                         'and a local GGML model, or supply --srt. No media was uploaded.'
                         + setup_guidance())
    configured = model or os.environ.get('VIDEO_HOOK_ASR_MODEL')
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError('Local ASR model missing or empty: ' + str(path) + setup_guidance())
    else:
        roots = [Path.home() / '.cache/video-hook/models',
                 Path.home() / '.cache/whisper',
                 Path.home() / '.cache/hyperframes/whisper/models']
        # Prefer multilingual small/base models; reuse a larger cached model if needed.
        names = ('small', 'base', 'tiny', 'medium', 'large-v3', 'large-v3-turbo', 'large-v2')
        path = next((root / ('ggml-' + name + '.bin') for name in names for root in roots
                     if (root / ('ggml-' + name + '.bin')).is_file()
                     and (root / ('ggml-' + name + '.bin')).stat().st_size > 0), None)
        if path is None:
            raise ValueError('No local GGML ASR model found. Use --asr-model /path/model.bin '
                             'or VIDEO_HOOK_ASR_MODEL, or supply --srt. No automatic download.'
                             + setup_guidance())
        path = path.resolve()
    return str(Path(binary).resolve()), path


def doctor():
    try:
        binary, model = resolve_backend()
        return {'available': True, 'engine': 'whisper-cli', 'binary': binary,
                'model': str(model), 'note': 'Discovery only; model load/inference not checked.'}
    except ValueError as e:
        return {'available': False, 'reason': str(e)}


def transcribe(video, out, duration, backend, language='auto'):
    binary, model = backend
    folder = out / 'asr'
    folder.mkdir()
    audio, prefix = folder / 'audio.wav', folder / 'raw'
    # Keep delayed audio on the edited timeline; pad missing audio to the video end.
    extract = ['ffmpeg', '-nostdin', '-v', 'error', '-n', '-i', str(video),
               '-map', '0:a:0', '-vn', '-af',
               f'aresample=16000:async=1:first_pts=0,apad,atrim=duration={duration}',
               '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(audio)]
    command = [binary, '-m', str(model), '-f', str(audio), '-l', language,
               '-osrt', '-oj', '-of', str(prefix)]
    # Save commands before execution so failed runs remain diagnosable.
    import json
    (folder / 'commands.json').write_text(json.dumps(
        {'extract': extract, 'transcribe': command}, ensure_ascii=False, indent=2) + '\n')
    started = time.monotonic()
    for name, cmd in [('extract', extract), ('whisper', command)]:
        with (folder / (name + '.stdout.log')).open('w') as stdout, \
                (folder / (name + '.stderr.log')).open('w') as stderr:
            result = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
        if result.returncode:
            raise ValueError(f'Local ASR {name} failed ({result.returncode}); '
                             f'see {folder / (name + ".stderr.log")}. No silent fallback.')
    return prefix.with_suffix('.srt'), {
        'kind': 'local_asr', 'engine': 'whisper-cli', 'binary': binary,
        'model': str(model), 'model_bytes': model.stat().st_size,
        'language_requested': language, 'elapsed_seconds': round(time.monotonic() - started, 3),
        'audio': str(audio), 'raw_srt': str(prefix.with_suffix('.srt')),
        'review': 'unreviewed ASR; verify words and timestamps against the original audio',
    }
