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
import struct
import os
from pathlib import Path
from fractions import Fraction

from openshorts_windows import build_transcript_windows
import local_asr


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
    video = Path(args.video).expanduser().resolve()
    p, v, duration = media_info(video)
    srt, kind = local_asr.discover_srt(video, getattr(args, 'srt', None))
    if srt is not None:
        cues = parse_srt(srt)
        if cues[-1]['end'] > duration + 0.15:
            raise ValueError('SRT extends beyond video. Check that both use the same edited timeline.')
        out = fresh(args.out)
        provenance = {'kind': kind, 'review': 'Verify subtitle alignment against this edited video.'}
    else:
        backend = local_asr.resolve_backend(getattr(args, 'asr_model', None))
        out = fresh(args.out)
        raw_srt, provenance = local_asr.transcribe(
            video, out, duration, backend, getattr(args, 'asr_language', 'auto'))
        try:
            cues = parse_srt(raw_srt)
        except ValueError as e:
            raise ValueError('ASR produced no usable ordered speech cues; inspect asr/ logs '
                             'or supply a matched --srt. ' + str(e)) from e
        # Never silently accept hallucinated timestamps outside the video timeline.
        if max(c['end'] for c in cues) > duration + 0.15:
            raise ValueError('ASR timestamps extend beyond video; inspect asr/raw.srt.')
        adjusted = 0
        for cue in cues:
            if cue['end'] > duration:
                cue['end'] = round(duration, 3)
                adjusted += 1
            if cue['start'] >= cue['end']:
                raise ValueError('ASR cue has no duration within the video timeline.')
        provenance['tail_cues_clipped'] = adjusted
        srt = out / 'transcript.srt'
        save_srt(srt, cues)
        cues = parse_srt(srt)
        provenance['raw_srt_sha256'] = digest(raw_srt)
    provenance['srt'] = str(srt)
    provenance['srt_sha256'] = digest(srt)
    write(out / 'subtitle-source.json', provenance)
    source = {'video': str(video), 'video_sha256': digest(video), 'srt': str(srt), 'srt_sha256': digest(srt)}
    write(out / 'source.json', source)
    write(out / 'probe.json', p)
    write(out / 'transcript.json', cues)
    windows = build_transcript_windows({'segments': cues}, duration, 45, 15)
    write(out / 'windows.json', windows)
    plan = {'version': 1, 'source': source, 'theme': '', 'theme_connection': '', 'surprise': '',
            'preserved_meaning': '', 'segments': [], 'fps': v['avg_frame_rate'],
            'fade_seconds': round(.4 * float(Fraction(v['avg_frame_rate']))) / float(Fraction(v['avg_frame_rate'])),
            'black_seconds': round(.2 * float(Fraction(v['avg_frame_rate']))) / float(Fraction(v['avg_frame_rate'])), 'fade_overlap_seconds': 0,
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
    return {'workspace': str(out), 'duration': duration, 'cues': len(cues), 'subtitle_source': kind,
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
    _, v, actual = media_info(path)
    expected_frames = round(expected * fps)
    frames = int(v.get('nb_frames', 0))
    if (abs(actual - expected) > max(.08, 2 / fps)
            or (v['width'], v['height']) != (width, height)
            or abs(float(Fraction(v['avg_frame_rate'])) - fps) > .0001
            or frames != expected_frames):
        raise ValueError(f'Output mismatch: duration={actual}, frames={frames}, expected={expected}/{expected_frames}')
    run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', path, '-f', 'null', '-'])
    return {'full_decode': 'passed', 'duration': actual, 'expected_duration': expected,
            'frames': frames, 'expected_frames': expected_frames, 'fps': fps,
            'width': width, 'height': height, 'sha256': digest(path)}


def frame_duration(seconds, fps):
    # Round up only the container's fractional last frame; never lose the tail audio.
    return math.ceil(seconds * fps - .00001) / fps


def hook_duration(p):
    raw = sum(b - a for a, b in p['segments'])
    return raw + p['fade_seconds'] + p['black_seconds'] - p.get('fade_overlap_seconds', 0)


def preview_length(p, duration, fps, requested=None):
    start = float(p['existing_opening']['body_start'])
    available = duration - start
    if requested is not None:
        requested = number(requested, 'body_seconds')
        if requested <= 0:
            raise ValueError('body_seconds must be positive')
        return frame_duration(min(available, requested), fps)
    ends = [c['end'] - start for c in parse_srt(p['source']['srt'])
            if 10 <= c['end'] - start <= min(20, available)]
    # Cue ends are a review aid, not proof of sentence/audio boundaries.
    chosen = min(ends, key=lambda x: abs(x - 15)) if ends else min(15, available)
    return frame_duration(chosen, fps)


def output_cues(p, body_duration=None):
    cues = parse_srt(p['source']['srt'])
    mapped = mapped_cues(cues, p['segments'])
    if body_duration is not None:
        start = float(p['existing_opening']['body_start'])
        for c in mapped_cues(cues, [[start, start + body_duration]]):
            mapped.append({**c, 'start': c['start'] + hook_duration(p),
                           'end': c['end'] + hook_duration(p)})
    return mapped


def render_source(p, target, w, h, body_duration=None):
    """Encode from the canonical source once, including both hook and body."""
    fps = float(Fraction(str(p['fps'])))
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-n']
    filters, join, raw = [], [], 0.0
    for i, (a, b) in enumerate(p['segments']):
        length = b - a
        cmd += ['-ss', str(a), '-t', str(length), '-i', p['source']['video']]
        filters.append(f'[{i}:v:0]setpts=PTS-STARTPTS,fps={p["fps"]},scale={w}:{h},setsar=1,trim=duration={length}[v{i}]')
        fadeout = min(length / 2, p.get('audio_tail_fade_seconds', .02) if i == len(p['segments']) - 1 else .02)
        filters.append(f'[{i}:a:0]asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={length},afade=t=in:d={min(.005,length/2)},afade=t=out:st={length-fadeout}:d={fadeout}[a{i}]')
        join.extend([f'[v{i}]', f'[a{i}]'])
        raw += length
    fade, black, overlap = p['fade_seconds'], p['black_seconds'], p.get('fade_overlap_seconds', 0)
    pad, total = fade + black - overlap, hook_duration(p)
    filters += [''.join(join) + f'concat=n={len(p["segments"])}:v=1:a=1[v][a]',
                f'[v]tpad=stop_mode=clone:stop_duration={pad},fade=t=out:st={raw-overlap}:d={fade}[hv]',
                f'[a]apad,atrim=duration={total}[ha]']
    if body_duration is not None:
        i = len(p['segments'])
        cmd += ['-ss', str(p['existing_opening']['body_start']), '-t', str(body_duration), '-i', p['source']['video']]
        filters += [f'[{i}:v:0]setpts=PTS-STARTPTS,fps={p["fps"]},scale={w}:{h},setsar=1,tpad=stop_mode=clone:stop_duration={1/fps},trim=duration={body_duration}[bv]',
                    f'[{i}:a:0]asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={body_duration}[ba]',
                    '[hv][ha][bv][ba]concat=n=2:v=1:a=1[vo][ao]']
        total += body_duration
    else:
        filters += ['[hv]null[vo]', '[ha]anull[ao]']
    cmd += ['-filter_complex_threads', '1', '-filter_complex', ';'.join(filters),
            '-map', '[vo]', '-map', '[ao]', '-t', str(total)] + encode_args(p['fps']) + [str(target)]
    return cmd, total


def join_evidence(target, out, p, total):
    """Check the intentional separator and expose body frames for human review."""
    seam = hook_duration(p)
    t = seam - p['black_seconds'] / 2
    rgb = subprocess.check_output(['ffmpeg', '-nostdin', '-v', 'error', '-ss', str(t), '-i', str(target),
                                   '-frames:v', '1', '-vf', 'scale=32:18', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
    if not rgb or max(rgb) > 8:
        raise ValueError('Expected black separator missing')
    length = min(.05, p['black_seconds'] / 4)
    pcm = subprocess.check_output(['ffmpeg', '-nostdin', '-v', 'error', '-ss', str(t), '-i', str(target),
                                   '-t', str(length), '-vn', '-ac', '1', '-ar', '48000', '-f', 'f32le', '-'])
    samples = [x[0] for x in struct.iter_unpack('<f', pcm)]
    if not samples:
        raise ValueError('Separator audio could not be checked')
    rms = math.sqrt(sum(x*x for x in samples) / len(samples))
    if rms > .006:
        raise ValueError('Unexpected audio in black separator')
    fps = float(Fraction(str(p['fps'])))
    frames = {}
    for label, time in [('separator', t), ('body_first', seam),
                        ('body_middle', (seam + total) / 2), ('body_last', total - 1/fps)]:
        path = out / (target.stem + '_' + label + '.jpg')
        run(['ffmpeg', '-nostdin', '-v', 'error', '-n', '-ss', time, '-i', target,
             '-frames:v', 1, '-vf', 'scale=640:640:force_original_aspect_ratio=decrease', path])
        if not path.is_file():
            raise ValueError('Missing review frame: ' + label)
        frames[label] = str(path)
    return {'body_output_start': seam, 'black_pixel_max': max(rgb), 'separator_audio_rms': rms,
            'frames': frames, 'human_listening': 'pending', 'human_visual_review': 'pending'}


def render(args):
    p, v, fps, duration = validate_plan(args.plan)
    body = preview_length(p, duration, fps, getattr(args, 'body_seconds', None))
    out = fresh(args.out)
    ratio = min(1, args.max_side / max(v['width'], v['height'])) if args.max_side else 1
    w, h = [max(2, round(v[k] * ratio / 2) * 2) for k in ('width', 'height')]
    target = out / 'hook.mp4'
    cmd, total = render_source(p, target, w, h)
    write(out / 'command.json', list(map(str, cmd)))
    run(cmd)
    qa = verify_video(target, total, w, h, fps)
    save_srt(out / 'hook.srt', output_cues(p))
    preview = out / 'preview.mp4'
    cmd, preview_total = render_source(p, preview, w, h, body)
    write(out / 'preview-command.json', list(map(str, cmd)))
    run(cmd)
    preview_qa = verify_video(preview, preview_total, w, h, fps)
    seam_qa = join_evidence(preview, out, p, preview_total)
    save_srt(out / 'preview.srt', output_cues(p, body))
    write(out / 'plan.json', p)
    manifest = {'schema_version': 2, 'plan_sha256': digest(out / 'plan.json'), 'qa': qa,
                'width': w, 'height': h, 'fps': fps, 'hook_duration': total,
                'raw_duration': sum(b-a for a,b in p['segments']),
                'hook_srt_sha256': digest(out / 'hook.srt'),
                'preview': {'qa': preview_qa, 'srt_sha256': digest(out / 'preview.srt'),
                            'body_start': p['existing_opening']['body_start'], 'body_duration': body,
                            'join': seam_qa}, 'review': 'pending human audio and semantic review'}
    write(out / 'manifest.json', manifest)
    return {'render': str(out), 'preview': str(preview), **manifest}


def reviewed_render(directory):
    folder = Path(directory).resolve()
    m = read(folder / 'manifest.json')
    if m.get('schema_version') != 2:
        raise ValueError('Render a joined preview with this version before approval/delivery')
    checks = {'plan.json': m['plan_sha256'], 'hook.mp4': m['qa']['sha256'],
              'hook.srt': m['hook_srt_sha256'], 'preview.mp4': m['preview']['qa']['sha256'],
              'preview.srt': m['preview']['srt_sha256']}
    if any(digest(folder / name) != sha for name, sha in checks.items()):
        raise ValueError('Render, subtitles or plan changed after validation; render again')
    p, _, _, duration = validate_plan(folder / 'plan.json')
    return folder, m, p, duration


def approve(args):
    folder, m, p, _ = reviewed_render(args.render)
    if not args.quote.strip():
        raise ValueError('Record the actual user approval quote')
    if p['existing_opening']['status'] == 'unknown':
        raise ValueError('Inspect the original opening and resolve unknown before approving prepend')
    opening = p['existing_opening']
    if opening['status'] == 'present' and not args.opening_quote.strip():
        raise ValueError('Record explicit user choice to keep or replace the existing opening')
    value = {'render': str(folder), 'manifest_sha256': digest(folder / 'manifest.json'),
             'plan_sha256': m['plan_sha256'], 'hook_sha256': m['qa']['sha256'],
             'preview_sha256': m['preview']['qa']['sha256'],
             'user_quote': args.quote, 'opening_quote': args.opening_quote,
             'scope': 'approve editorial plan and joined preview; deliver full body at source size beside source'}
    write(folder / 'approval.json', value)
    return value


def reserve_delivery(source):
    # Reserve a common basename, including a sidecar-only collision and concurrent runs.
    for version in range(1, 100000):
        stem = source.stem + f'_hook_v{version}'
        target = source.parent / (stem + '.mp4')
        sidecar = source.parent / (stem + '.srt')
        receipt = source.parent / (stem + '.json')
        lock = source.parent / ('.' + stem + '.lock')
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except FileExistsError:
            continue
        if any(x.exists() or x.is_symlink() for x in (target, sidecar, receipt,
                *(x.with_name('.' + x.name + '.partial') for x in (target, sidecar, receipt)))):
            lock.unlink()
            continue
        return target, sidecar, receipt, lock
    raise ValueError('No free output version')


def prepend(args):
    folder, m, p, duration = reviewed_render(args.render)
    a = read(folder / 'approval.json')
    if (a.get('manifest_sha256') != digest(folder / 'manifest.json')
            or a['plan_sha256'] != m['plan_sha256'] or a['hook_sha256'] != m['qa']['sha256']
            or a.get('preview_sha256') != m['preview']['qa']['sha256'] or not a['user_quote'].strip()):
        raise ValueError('Approval does not match this render')
    if p['existing_opening']['status'] == 'unknown' or (p['existing_opening']['status'] == 'present' and not a.get('opening_quote', '').strip()):
        raise ValueError('Original opening still requires a user decision')
    source = Path(p['source']['video'])
    _, v, _ = media_info(source)
    w, h, fps = v['width'], v['height'], float(Fraction(str(p['fps'])))
    if w % 2 or h % 2:
        raise ValueError('Source dimensions must be even for H.264 yuv420p delivery')
    if abs(fps - float(Fraction(v['avg_frame_rate']))) > .0001:
        raise ValueError('Full delivery must use source frame rate; prepare/review a matching plan')
    body = frame_duration(duration - p['existing_opening']['body_start'], fps)
    out = fresh(args.out)
    target, sidecar, receipt, lock = reserve_delivery(source)
    try:
        staged = out / 'final.mp4'
        cmd, total = render_source(p, staged, w, h, body)
        write(out / 'command.json', list(map(str, cmd)))
        run(cmd)
        qa = verify_video(staged, total, w, h, fps)
        seam_qa = join_evidence(staged, out, p, total)
        save_srt(out / 'final.srt', output_cues(p, body))
        # Recheck inputs after a long render before publishing a final filename.
        validate_plan(folder / 'plan.json')
        result = {'output': str(target), 'srt': str(sidecar), 'qa': qa, 'join': seam_qa,
                  'approval': a, 'source': p['source'], 'body_start': p['existing_opening']['body_start'],
                  'body_duration': body, 'hook_duration': hook_duration(p),
                  'source_unchanged': True, 'srt_sha256': digest(out / 'final.srt'),
                  'work_directory': str(out), 'note': 'One encode from original source at source size/fps; original body retained.'}
        write(out / 'manifest.json', result)
        # Copy to hidden files on the destination volume, then expose complete files
        # exclusively. The receipt is published last and is the completion marker.
        hidden, published = [], []
        try:
            for src, dst, sha in [(staged, target, qa['sha256']),
                                  (out / 'final.srt', sidecar, result['srt_sha256']),
                                  (out / 'manifest.json', receipt, digest(out / 'manifest.json'))]:
                partial = dst.with_name('.' + dst.name + '.partial')
                with src.open('rb') as reader, partial.open('xb') as writer:
                    hidden.append(partial)
                    shutil.copyfileobj(reader, writer)
                if digest(partial) != sha:
                    raise ValueError('Delivery copy hash mismatch')
            for partial, dst in zip(hidden, (target, sidecar, receipt)):
                os.link(partial, dst)  # Atomic, fails if another writer created dst.
                published.append(dst)
            return result
        except Exception:
            for path in published:
                path.unlink()
            raise
        finally:
            for path in hidden:
                path.unlink()
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('doctor')
    p.set_defaults(func=lambda _: {'python': sys.executable, 'script': str(Path(__file__).resolve()),
                                  'ffmpeg': shutil.which('ffmpeg'), 'ffprobe': shutil.which('ffprobe'),
                                  'local_asr': local_asr.doctor()})
    p = sub.add_parser('prepare')
    for flag in ('video', 'out'):
        p.add_argument('--' + flag, required=True)
    p.add_argument('--srt', help='Matched subtitles; omitted: same-name sidecar, then offline ASR')
    p.add_argument('--asr-model', help='Existing whisper.cpp GGML model path; no download')
    p.add_argument('--asr-language', default='auto', help='whisper-cli language code (default: auto)')
    p.add_argument('--samples', type=int, choices=range(2, 61), default=16)
    p.set_defaults(func=prepare)
    p = sub.add_parser('validate')
    p.add_argument('--plan', required=True)
    p.set_defaults(func=lambda a: {'valid': True, 'segments': validate_plan(a.plan)[0]['segments']})
    p = sub.add_parser('render')
    p.add_argument('--plan', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--max-side', type=int, default=1920, help='Preview only: 0 = original size; final delivery always uses source size')
    p.add_argument('--body-seconds', type=float, help='Body excerpt after hook; default near a cue end at 10-20 seconds')
    p.set_defaults(func=render)
    p = sub.add_parser('approve')
    p.add_argument('--render', required=True)
    p.add_argument('--quote', required=True, help='Actual user approval of this hook and prepend')
    p.add_argument('--opening-quote', default='', help='Explicit user decision for an existing original teaser')
    p.set_defaults(func=approve)
    p = sub.add_parser('prepend')
    p.add_argument('--render', required=True)
    p.add_argument('--out', required=True, help='New audit/work directory; delivery files are versioned beside source')
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
