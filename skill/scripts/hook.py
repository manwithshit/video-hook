#!/usr/bin/env python3
"""Local, non-destructive video-hook rendering. Semantic decisions belong to the agent."""
import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path
from fractions import Fraction

from openshorts_windows import build_transcript_windows


def run(args):
    return subprocess.run([str(x) for x in args], check=True, capture_output=True, text=True).stdout


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def fresh(path):
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=False)
    return p


def probe(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path]))


def media_info(path):
    p = probe(path)
    v = next(s for s in p['streams'] if s['codec_type'] == 'video')
    if not any(s['codec_type'] == 'audio' for s in p['streams']):
        raise ValueError('Input needs an audio stream; silent sources are not supported in v0.1.')
    if v.get('color_transfer') in ('smpte2084', 'arib-std-b67'):
        raise ValueError('HDR needs a separately reviewed color workflow; v0.1 supports SDR only.')
    rotation = sum(float(s.get('rotation', 0)) for s in v.get('side_data_list', []))
    if rotation % 360 or float(v.get('tags', {}).get('rotate', 0)) % 360:
        raise ValueError('Normalize rotation metadata to physical pixels before using this version.')
    return p, v, float(p['format']['duration'])


def parse_srt(path):
    text = Path(path).read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    rows = []
    def sec(t):
        h, m, s, ms = map(int, re.split('[:,.]', t))
        if m >= 60 or s >= 60:
            raise ValueError('Invalid SRT timestamp')
        return h * 3600 + m * 60 + s + ms / 1000
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = block.splitlines()
        i = next((i for i, line in enumerate(lines) if '-->' in line), None)
        if i is None:
            raise ValueError('Invalid SRT block: missing timestamp')
        m = re.fullmatch(r'\s*(\d+:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d{3})\s*', lines[i])
        if not m:
            raise ValueError('Unsupported SRT timestamp: ' + lines[i])
        start, end = map(sec, m.groups())
        caption = '\n'.join(lines[i + 1:]).strip()
        if end <= start or not caption or (rows and start < rows[-1]['start']):
            raise ValueError('SRT must contain nonempty, ordered, positive-duration cues')
        rows.append({'id': len(rows) + 1, 'start': start, 'end': end, 'text': caption})
    if not rows:
        raise ValueError('Empty SRT')
    return rows


def stamp(seconds):
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def mapped_cues(cues, spans):
    out, offset = [], 0.0
    for a, b in spans:
        for c in cues:
            start, end = max(c['start'], a), min(c['end'], b)
            if end > start:
                out.append({'start': offset + start - a, 'end': offset + end - a, 'text': c['text']})
        offset += b - a
    return out


def save_srt(path, cues):
    with Path(path).open('x', encoding='utf-8') as f:
        f.write('\n\n'.join(f"{i}\n{stamp(c['start'])} --> {stamp(c['end'])}\n{c['text']}" for i, c in enumerate(cues, 1)) + '\n')


def prepare(args):
    video, srt = Path(args.video).expanduser().resolve(), Path(args.srt).expanduser().resolve()
    p, v, duration = media_info(video)
    cues = parse_srt(srt)
    if cues[-1]['end'] > duration + 0.15:
        raise ValueError('SRT extends beyond video. Check that both use the same edited timeline.')
    out = fresh(args.out)
    source = {'video': str(video), 'video_sha256': digest(video), 'srt': str(srt), 'srt_sha256': digest(srt)}
    write(out / 'source.json', source)
    write(out / 'probe.json', p)
    write(out / 'transcript.json', cues)
    windows = build_transcript_windows({'segments': cues}, duration, 45, 15)
    write(out / 'windows.json', windows)
    plan = {'version': 1, 'source': source, 'theme': '', 'theme_connection': '', 'surprise': '',
            'preserved_meaning': '', 'segments': [], 'fps': v['avg_frame_rate'],
            'fade_seconds': 0.4, 'black_seconds': 0.2, 'fade_overlap_seconds': 0,
            'audio_tail_fade_seconds': 0.02,
            'existing_opening': {'status': 'unknown', 'body_start': 0}}
    write(out / 'plan.template.json', plan)
    samples = []
    (out / 'frames').mkdir()
    for i in range(args.samples):
        t = i * max(0, duration - 0.1) / max(1, args.samples - 1)
        name = f'{i:03}_{t:09.3f}.jpg'
        run(['ffmpeg', '-nostdin', '-v', 'error', '-n', '-ss', t, '-i', video, '-frames:v', 1,
             '-vf', "scale=640:640:force_original_aspect_ratio=decrease", out / 'frames' / name])
        samples.append({'time': t, 'file': 'frames/' + name})
    write(out / 'frames.json', samples)
    return {'workspace': str(out), 'duration': duration, 'cues': len(cues),
            'note': 'Read all transcript cues and inspect visual samples; windows are not ranked hooks.'}


def number(value, label):
    if isinstance(value, bool):
        raise ValueError(label + ' must be a finite number')
    x = float(value)
    if not math.isfinite(x):
        raise ValueError(label + ' must be finite')
    return x


def validate_plan(path):
    p = read(path)
    if p.get('version') != 1:
        raise ValueError('Unsupported plan version')
    for key in ('theme', 'theme_connection', 'surprise', 'preserved_meaning'):
        if not isinstance(p.get(key), str) or not p[key].strip():
            raise ValueError('Agent must write evidence for ' + key)
    for key in ('video', 'srt'):
        source = Path(p['source'][key])
        if not source.is_absolute() or digest(source) != p['source'][key + '_sha256']:
            raise ValueError('Source missing, not absolute, or hash changed: ' + key)
    _, v, duration = media_info(p['source']['video'])
    fps = float(Fraction(str(p['fps'])))
    if not 1 <= fps <= 120:
        raise ValueError('fps must be 1..120; use a deliberate CFR timeline')
    spans, last = [], -1.0
    for segment in p['segments']:
        if len(segment) != 2:
            raise ValueError('Each segment must be [start_seconds, end_seconds]')
        a, b = [number(x, 'segment') for x in segment]
        if a < 0 or b <= a or b > duration + 0.001 or a < last:
            raise ValueError('Segments must be positive, chronological, nonoverlapping, and in bounds')
        if any(abs(x * fps - round(x * fps)) > 0.001 for x in (a, b)):
            raise ValueError('Cuts must land on output-frame boundaries')
        spans.append([a, b])
        last = b
    if not spans:
        raise ValueError('No segments selected')
    fade = number(p['fade_seconds'], 'fade_seconds')
    black = number(p['black_seconds'], 'black_seconds')
    overlap = number(p.get('fade_overlap_seconds', 0), 'fade_overlap_seconds')
    audio_fade = number(p.get('audio_tail_fade_seconds', .02), 'audio_tail_fade_seconds')
    if not (0 < fade <= 3 and 0 < black <= 3 and 0 <= overlap <= fade and 0 < audio_fade <= spans[-1][1] - spans[-1][0]):
        raise ValueError('Invalid fade / black hold / audio-tail values')
    if overlap > spans[-1][1] - spans[-1][0]:
        raise ValueError('Video fade overlap exceeds final segment')
    for x in (fade, black, overlap):
        if abs(x * fps - round(x * fps)) > .001:
            raise ValueError('Video fade/hold values must be frame-aligned')
    opening = p['existing_opening']
    if opening['status'] not in ('unknown', 'none', 'present'):
        raise ValueError('Invalid existing opening status')
    start = number(opening['body_start'], 'body_start')
    if not 0 <= start < duration or abs(start * fps - round(start * fps)) > .001:
        raise ValueError('Invalid body start')
    if start and opening['status'] != 'present':
        raise ValueError('Trimming body requires existing_opening.status=present')
    p['segments'] = spans
    return p, v, fps, duration


def encode_args(fps):
    return ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-threads', '4', '-pix_fmt', 'yuv420p',
            '-r', str(fps), '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart']


def verify_video(path, expected, width, height, fps):
    p, v, actual = media_info(path)
    if abs(actual - expected) > max(.08, 2 / fps) or (v['width'], v['height']) != (width, height):
        raise ValueError(f'Output mismatch: duration={actual}, expected={expected}')
    run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', path, '-f', 'null', '-'])
    return {'full_decode': 'passed', 'duration': actual, 'expected_duration': expected,
            'width': width, 'height': height, 'sha256': digest(path)}


def render(args):
    p, v, fps, _ = validate_plan(args.plan)
    out = fresh(args.out)
    ratio = min(1, args.max_side / max(v['width'], v['height'])) if args.max_side else 1
    w, h = [max(2, round(v[k] * ratio / 2) * 2) for k in ('width', 'height')]
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-n']
    filters, join, raw = [], [], 0.0
    for i, (a, b) in enumerate(p['segments']):
        length = b - a
        cmd += ['-ss', str(a), '-t', str(length), '-i', p['source']['video']]
        filters.append(f'[{i}:v]setpts=PTS-STARTPTS,fps={fps},scale={w}:{h},setsar=1,trim=duration={length}[v{i}]')
        fadeout = min(length / 2, p.get('audio_tail_fade_seconds', .02) if i == len(p['segments']) - 1 else .02)
        filters.append(f'[{i}:a]asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={length},afade=t=in:d={min(.005,length/2)},afade=t=out:st={length-fadeout}:d={fadeout}[a{i}]')
        join.extend([f'[v{i}]', f'[a{i}]'])
        raw += length
    fade, black, overlap = p['fade_seconds'], p['black_seconds'], p.get('fade_overlap_seconds', 0)
    pad = fade + black - overlap
    total = raw + pad
    filters += [''.join(join) + f'concat=n={len(p["segments"])}:v=1:a=1[v][a]',
                f'[v]tpad=stop_mode=clone:stop_duration={pad},fade=t=out:st={raw-overlap}:d={fade}[vo]',
                f'[a]apad,atrim=duration={total}[ao]']
    target = out / 'hook.mp4'
    cmd += ['-filter_complex_threads', '1', '-filter_complex', ';'.join(filters), '-map', '[vo]', '-map', '[ao]', '-t', str(total)] + encode_args(fps) + [str(target)]
    write(out / 'command.json', cmd)
    run(cmd)
    qa = verify_video(target, total, w, h, fps)
    tail = subprocess.run(['ffmpeg', '-nostdin', '-v', 'info', '-sseof', '-2', '-i', str(target),
                           '-vf', 'blackdetect=d=0.05:pix_th=0.05', '-af', 'silencedetect=n=-50dB:d=0.05', '-f', 'null', '-'], capture_output=True, text=True, check=True).stderr
    (out / 'tail-events.txt').write_text(tail)
    if 'black_start:' not in tail or 'silence_start:' not in tail:
        raise ValueError('Expected black/silent tail was not detected')
    write(out / 'plan.json', p)
    save_srt(out / 'hook.srt', mapped_cues(parse_srt(p['source']['srt']), p['segments']))
    manifest = {'plan_sha256': digest(out / 'plan.json'), 'qa': qa, 'width': w, 'height': h, 'fps': fps,
                'raw_duration': raw, 'hook_duration': total, 'review': 'pending human audio and semantic review'}
    write(out / 'manifest.json', manifest)
    return {'render': str(out), **manifest}


def reviewed_render(directory):
    folder = Path(directory).resolve()
    m = read(folder / 'manifest.json')
    if digest(folder / 'plan.json') != m['plan_sha256'] or digest(folder / 'hook.mp4') != m['qa']['sha256']:
        raise ValueError('Render or plan changed after validation; render again')
    p, _, _, duration = validate_plan(folder / 'plan.json')
    return folder, m, p, duration


def approve(args):
    folder, m, p, _ = reviewed_render(args.render)
    if not args.quote.strip():
        raise ValueError('Record the actual user approval quote')
    if p['existing_opening']['status'] == 'unknown':
        raise ValueError('Inspect the original opening and resolve unknown before approving prepend')
    opening = p['existing_opening']
    if opening['status'] == 'present' and not args.opening_quote:
        raise ValueError('Record explicit user choice to keep or replace the existing opening')
    value = {'render': str(folder), 'plan_sha256': m['plan_sha256'], 'hook_sha256': m['qa']['sha256'],
             'user_quote': args.quote, 'opening_quote': args.opening_quote,
             'scope': 'approve hook audio/meaning and prepend with the body_start in this plan'}
    write(folder / 'approval.json', value)
    return value


def prepend(args):
    folder, m, p, duration = reviewed_render(args.render)
    a = read(folder / 'approval.json')
    if a['plan_sha256'] != m['plan_sha256'] or a['hook_sha256'] != m['qa']['sha256'] or not a['user_quote'].strip():
        raise ValueError('Approval does not match this render')
    if p['existing_opening']['status'] == 'unknown' or (p['existing_opening']['status'] == 'present' and not a.get('opening_quote')):
        raise ValueError('Original opening still requires a user decision')
    out = fresh(args.out)
    start = float(p['existing_opening']['body_start'])
    fps, w, h = m['fps'], m['width'], m['height']
    body_duration = duration - start
    total = m['hook_duration'] + body_duration
    graph = (f'[0:v]fps={fps},setsar=1,setpts=PTS-STARTPTS[v0];'
             '[0:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[a0];'
             f'[1:v]fps={fps},scale={w}:{h},setsar=1,setpts=PTS-STARTPTS[v1];'
             f'[1:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={body_duration},asetpts=PTS-STARTPTS[a1];'
             '[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]')
    target = out / 'final.mp4'
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-n', '-i', folder / 'hook.mp4', '-ss', start, '-i', p['source']['video'],
           '-filter_complex_threads', '1', '-filter_complex', graph, '-map', '[v]', '-map', '[a]', '-t', total] + encode_args(fps) + [target]
    cmd = [str(x) for x in cmd]
    write(out / 'command.json', cmd)
    run(cmd)
    qa = verify_video(target, total, w, h, fps)
    cues = parse_srt(p['source']['srt'])
    mapped = mapped_cues(cues, p['segments'])
    for c in mapped_cues(cues, [[start, duration]]):
        mapped.append({**c, 'start': c['start'] + m['hook_duration'], 'end': c['end'] + m['hook_duration']})
    save_srt(out / 'final.srt', mapped)
    write(out / 'manifest.json', {'qa': qa, 'approval': a, 'source': p['source'], 'body_start': start,
                                'note': 'Body re-encoded to the approved hook resolution; original source unchanged.'})
    return {'output': str(target), 'qa': qa}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('doctor')
    p.set_defaults(func=lambda _: {'python': sys.executable, 'script': str(Path(__file__).resolve()),
                                  'ffmpeg': shutil.which('ffmpeg'), 'ffprobe': shutil.which('ffprobe')})
    p = sub.add_parser('prepare')
    for flag in ('video', 'srt', 'out'):
        p.add_argument('--' + flag, required=True)
    p.add_argument('--samples', type=int, choices=range(2, 61), default=16)
    p.set_defaults(func=prepare)
    p = sub.add_parser('validate')
    p.add_argument('--plan', required=True)
    p.set_defaults(func=lambda a: {'valid': True, 'segments': validate_plan(a.plan)[0]['segments']})
    p = sub.add_parser('render')
    p.add_argument('--plan', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--max-side', type=int, default=1920, help='0 = original size; final prepend uses this same resolution')
    p.set_defaults(func=render)
    p = sub.add_parser('approve')
    p.add_argument('--render', required=True)
    p.add_argument('--quote', required=True, help='Actual user approval of this hook and prepend')
    p.add_argument('--opening-quote', default='', help='Explicit user decision for an existing original teaser')
    p.set_defaults(func=approve)
    p = sub.add_parser('prepend')
    p.add_argument('--render', required=True)
    p.add_argument('--out', required=True)
    p.set_defaults(func=prepend)
    args = parser.parse_args()
    if getattr(args, 'max_side', 0) < 0:
        parser.error('--max-side must be nonnegative')
    try:
        print(json.dumps(args.func(args), ensure_ascii=False, indent=2))
    except (ValueError, KeyError, OSError, StopIteration, subprocess.CalledProcessError) as e:
        print(f'ERROR: {e}', file=sys.stderr)
        if isinstance(e, subprocess.CalledProcessError):
            print(e.stderr[-5000:] if e.stderr else '', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
