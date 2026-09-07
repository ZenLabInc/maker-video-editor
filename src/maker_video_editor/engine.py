"""All times are seconds on the hands-camera timeline; no network calls."""
from __future__ import annotations

import array
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile


def run(args):
    return subprocess.run([str(x) for x in args], check=True, capture_output=True)


def probe(path):
    data = json.loads(run(['ffprobe', '-v', 'error', '-show_streams',
                           '-show_format', '-of', 'json', path]).stdout)
    videos = [s for s in data['streams'] if s['codec_type'] == 'video']
    if not videos:
        raise ValueError(f'Video stream required: {path}')
    duration = float(videos[0].get('duration', data['format'].get('duration', 0)))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f'Invalid video duration: {path}')
    return {'duration': duration, 'audio': any(s['codec_type'] == 'audio' for s in data['streams'])}


def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    return value


def merge(ranges, gap=0):
    result = []
    for start, end in sorted(ranges):
        if end <= start:
            continue
        if result and start <= result[-1][1] + gap:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def activity(path, info, threshold_db=-38, window=0.1):
    """Streaming energy gate, NOT a speech classifier. Keep any audible activity."""
    if not info['audio']:
        return []
    args = ['ffmpeg', '-v', 'error', '-i', str(path), '-vn', '-ac', '1', '-ar',
            '16000', '-f', 's16le', '-']
    ranges = []
    # stderr file prevents pipe deadlocks on decoding errors.
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errors)
        index = 0
        try:
            while raw := proc.stdout.read(round(16000 * window) * 2):
                samples = array.array('h', raw)
                if sys.byteorder != 'little':
                    samples.byteswap()
                rms = math.sqrt(sum(x*x for x in samples) / max(1, len(samples))) / 32768
                if rms >= 10 ** (threshold_db / 20):
                    ranges.append([index * window, index * window + len(samples)/16000])
                index += 1
            if proc.wait() != 0:
                errors.seek(0)
                raise ValueError(errors.read().decode(errors='replace'))
        finally:
            proc.stdout.close()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    return merge(ranges)


def create_plan(config, base):
    def resolve(p):
        return str((base / p).resolve())
    sources = {name: {'path': resolve(config[name])} for name in ('hands', 'screen')}
    offset = number(config.get('screen_offset', 0), 'screen_offset')
    # A screen frame at source time s occurs at master time s + offset.
    sources['hands']['offset'] = 0
    sources['screen']['offset'] = offset
    infos = {name: probe(item['path']) for name, item in sources.items()}
    start = max(0, offset)
    end = min(infos['hands']['duration'], offset + infos['screen']['duration'])
    if end <= start:
        raise ValueError('Sources have no overlap at this offset')
    analysis = config.get('analysis', {})
    threshold = number(analysis.get('threshold_db', -38), 'threshold_db')
    padding = number(analysis.get('padding', 0.3), 'padding')
    gap = number(analysis.get('bridge_gap', 0.6), 'bridge_gap')
    if padding < 0 or gap < 0:
        raise ValueError('padding and bridge_gap must be nonnegative')
    method = analysis.get('method', 'silero')
    if method == 'silero':
        from .vad import silero_detector
        detector = silero_detector()
    elif method == 'energy':
        detector = activity
    else:
        raise ValueError('analysis.method must be silero or energy')
    keep = []
    for name, item in sources.items():
        for a, b in detector(item['path'], infos[name], threshold):
            keep.append([max(start, a+item['offset']-padding), min(end, b+item['offset']+padding)])
    manual = config.get('normal_ranges', [])
    layouts = config.get('hands_large_ranges', [])
    for ranges in (manual, layouts):
        for pair in ranges:
            if len(pair) != 2 or number(pair[0], 'range start') >= number(pair[1], 'range end'):
                raise ValueError('Ranges must be [start, end] with start < end')
    keep += [[max(start, a), min(end, b)] for a, b in manual]
    keep = merge(keep, gap)
    cuts = {start, end}
    for a, b in keep + layouts:
        cuts.update([max(start, min(end, a)), max(start, min(end, b))])
    cuts = sorted(cuts)
    segments = []
    for a, b in zip(cuts, cuts[1:]):
        middle = (a+b)/2
        segments.append({'start': a, 'end': b,
                         'speed': 1 if any(x <= middle < y for x, y in keep) else config.get('silent_speed', 4),
                         'layout': 'hands' if any(x <= middle < y for x, y in layouts) else 'screen',
                         'gains': config.get('gains', {'hands': 1.0, 'screen': 1.0})})
    warnings = ['Review speech boundaries and sync in preview.']
    if method == 'energy':
        warnings.append('Energy gate is NOT speech recognition; noise also stays at normal speed.')
    for name, item in sources.items():
        if not infos[name]['audio']:
            warnings.append(f'{name}: no audio stream; treated as silence.')
        excluded = infos[name]['duration'] - (end-start)
        if excluded > 0.05:
            warnings.append(f'{name}: {excluded:.3f}s outside shared overlap excluded; inspect sync.')
    plan = {'transcription': config.get('transcription', {}), 'version': 1, 'sources': sources, 'range': [start, end],
            'segments': segments, 'output': config.get('output', {'width': 1920, 'height': 1080, 'fps': 30}),
            'opening': resolve(config['opening']) if config.get('opening') else None,
            'ending': resolve(config['ending']) if config.get('ending') else None,
            'warnings': warnings, 'analysis': {'method': method, 'threshold_db': threshold,
                                             'padding': padding, 'bridge_gap': gap}}
    validate(plan)
    return plan


def validate(plan):
    if plan['version'] != 1:
        raise ValueError('Unsupported plan version')
    start, end = plan['range']
    number(start, 'range start'); number(end, 'range end')
    if end <= start:
        raise ValueError('Empty range')
    for name in ('hands', 'screen'):
        source = plan['sources'][name]
        number(source['offset'], 'offset')
        info = probe(source['path'])
        if start-source['offset'] < -0.001 or end-source['offset'] > info['duration']+0.001:
            raise ValueError(f'{name}: range outside source')
    if not plan['segments']:
        raise ValueError('No segments')
    cursor = start
    for segment in plan['segments']:
        a, b = number(segment['start'], 'start'), number(segment['end'], 'end')
        if abs(a-cursor) > 1e-6 or b <= a:
            raise ValueError('Segments must cover range continuously, without gaps or overlaps')
        if number(segment['speed'], 'speed') not in (1, 2, 4, 8):
            raise ValueError('Supported speeds: 1, 2, 4, 8')
        if segment['layout'] not in ('hands', 'screen'):
            raise ValueError('Layout must be hands or screen')
        for name in ('hands', 'screen'):
            if not 0 <= number(segment['gains'][name], 'gain') <= 8:
                raise ValueError('Gains must be between 0 and 8')
        cursor = b
    if abs(cursor-end) > 1e-6:
        raise ValueError('Segments must reach range end')
    for key in ('width', 'height'):
        v = plan['output'][key]
        if isinstance(v, bool) or not isinstance(v, int) or v < 64 or v % 2:
            raise ValueError('Output dimensions must be positive even integers >= 64')
    if not 1 <= number(plan['output']['fps'], 'fps') <= 120:
        raise ValueError('fps must be 1..120')
    for key in ('opening', 'ending'):
        if plan.get(key):
            probe(plan[key])


def fit(label, width, height, output):
    return (f'{label}scale={width}:{height}:force_original_aspect_ratio=decrease,'
            f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1{output}')


def encode(args, graph, output, fps, duration):
    run(['ffmpeg', '-v', 'error', '-y', *args, '-filter_complex', graph,
         '-map', '[v]', '-map', '[a]', '-t', f'{duration:.9f}', '-r', str(fps),
         '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
         '-c:a', 'aac', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', output])


def render(plan, output, preview=False):
    validate(plan)
    output = Path(output).resolve()
    if output.exists():
        raise ValueError(f'Refusing to overwrite: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    width, height, fps = (plan['output'][k] for k in ('width', 'height', 'fps'))
    if preview:
        ratio = min(1, 640/width)
        width, height = max(64, round(width*ratio/2)*2), max(64, round(height*ratio/2)*2)
    infos = {n: probe(s['path']) for n, s in plan['sources'].items()}
    # Temporary chunks bound graph size for long recordings. Per-cut frame rounding is unavoidable.
    with tempfile.TemporaryDirectory(prefix='.render-', dir=output.parent) as temp:
        temp = Path(temp)
        chunks = []
        def bumper(path):
            info = probe(path)
            filters = [fit('[0:v:0]setpts=PTS-STARTPTS,', width, height, '[v]')]
            filters.append('[0:a:0]asetpts=PTS-STARTPTS,aresample=48000,apad[a]' if info['audio']
                           else 'anullsrc=r=48000:cl=stereo[a]')
            dest = temp / f'{len(chunks):06}.mp4'
            encode(['-i', path], ';'.join(filters), dest, fps, info['duration'])
            chunks.append(dest)
        if plan.get('opening'):
            bumper(plan['opening'])
        for segment in plan['segments']:
            args, filters = [], []
            length = segment['end']-segment['start']
            duration = length/segment['speed']
            for i, name in enumerate(('hands', 'screen')):
                source = plan['sources'][name]
                args += ['-ss', f"{segment['start']-source['offset']:.9f}", '-t', f'{length:.9f}', '-i', source['path']]
                filters.append(f'[{i}:v:0]setpts=(PTS-STARTPTS)/{segment["speed"]}[{name}]')
            main = segment['layout']
            small = 'hands' if main == 'screen' else 'screen'
            filters += [fit(f'[{main}]', width, height, '[bg]'),
                        fit(f'[{small}]', max(2, width//6*2), max(2, height//6*2), '[pip]'),
                        '[bg][pip]overlay=W-w-12:H-h-12:eof_action=repeat[v]']
            audio = []
            if segment['speed'] == 1:
                for i, name in enumerate(('hands', 'screen')):
                    if infos[name]['audio']:
                        filters.append(f'[{i}:a:0]asetpts=PTS-STARTPTS,aresample=48000,'
                                       f'volume={segment["gains"][name]},apad[au{i}]')
                        audio.append(f'[au{i}]')
            if audio:
                filters.append(''.join(audio)+f'amix=inputs={len(audio)}:normalize=0,alimiter=limit=0.95:level=0:latency=1[a]')
            else:
                filters.append('anullsrc=r=48000:cl=stereo[a]')
            dest = temp / f'{len(chunks):06}.mp4'
            encode(args, ';'.join(filters), dest, fps, duration)
            chunks.append(dest)
        if plan.get('ending'):
            bumper(plan['ending'])
        # Relative generated filenames make concat safe even if parent paths contain quotes.
        manifest = temp / 'concat.txt'
        manifest.write_text(''.join(f"file '{p.name}'\n" for p in chunks))
        assembled = temp / 'assembled.mp4'
        run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '1', '-i', manifest,
             '-c:v', 'copy', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-c:a', 'aac',
             '-ar', '48000', '-movflags', '+faststart', assembled])
        # Link publishes atomically and refuses a concurrent overwrite.
        import os
        os.link(assembled, output)
    return probe(output)
