"""Japanese ASR with an explicitly installed, local MLX Whisper large-v3 model."""
from __future__ import annotations

import array
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile

from .engine import number, probe, run

MODEL_REPO = 'mlx-community/whisper-large-v3-mlx'
DEFAULT_ASR = {'chunk_seconds': 300, 'initial_prompt': ''}


def check_model(directory):
    root = Path(directory).resolve()
    if not (root / 'config.json').is_file():
        raise ValueError(f'Local large-v3 model missing: {root}. Run prepare-asr-model first.')
    config = json.loads((root / 'config.json').read_text())
    expected = {'n_mels': 128, 'n_audio_layer': 32, 'n_text_layer': 32,
                'n_audio_state': 1280, 'n_text_state': 1280}
    if any(config.get(k) != v for k, v in expected.items()) or config.get('quantization'):
        raise ValueError('Expected non-quantized Whisper large-v3; tiny/turbo/other models are not accepted.')
    if not any((root / name).is_file() for name in ('weights.npz', 'weights.safetensors', 'model.safetensors')):
        raise ValueError('large-v3 model weights are missing; finish prepare-asr-model.')
    return root


def prepare_model(directory):
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise ValueError('ASR dependencies missing. Install .[asr].') from exc
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    snapshot_download(MODEL_REPO, local_dir=root,
                      allow_patterns=['config.json', 'weights.npz', 'weights.safetensors', 'model.safetensors'])
    return check_model(root)


def local_backend(model_dir):
    model = check_model(model_dir)
    try:
        import mlx_whisper
    except ImportError as exc:
        raise ValueError('MLX Whisper unavailable. Use Apple Silicon and install .[asr].') from exc

    def transcribe(audio, prompt):
        import numpy as np
        return mlx_whisper.transcribe(np.asarray(audio, dtype=np.float32), path_or_hf_repo=str(model), language='ja',
                                      task='transcribe', word_timestamps=True,
                                      initial_prompt=prompt or None, verbose=None,
                                      condition_on_previous_text=False)
    return transcribe


def atomic_json(path, data):
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as file:
        temp = Path(file.name)
        try:
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        os.link(temp, path)  # Never overwrite a prior checkpoint/result.
    finally:
        temp.unlink(missing_ok=True)


def extract_audio(path, start, duration):
    raw = run(['ffmpeg', '-v', 'error', '-ss', str(start), '-i', path, '-t', str(duration),
               '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '16000', '-f', 'f32le', '-']).stdout
    samples = array.array('f', raw)
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples


def timed_item(item, source, chunk_start, offset, duration, text_key):
    start, end = number(item['start'], 'ASR start'), number(item['end'], 'ASR end')
    if not 0 <= start <= end <= duration + 0.1:
        raise ValueError('ASR returned invalid chunk timestamps')
    start, end = min(start, duration) + chunk_start, min(end, duration) + chunk_start
    return {'source': source, 'source_start': start, 'source_end': end,
            'master_start': start + offset, 'master_end': end + offset,
            'text': str(item[text_key])}


def transcribe_sources(sources, output, model_dir, settings=None, resume=False, backend=None):
    settings = {**DEFAULT_ASR, **(settings or {})}
    seconds = number(settings['chunk_seconds'], 'chunk_seconds')
    if not 10 <= seconds <= 1800:
        raise ValueError('chunk_seconds must be 10..1800')
    if not isinstance(settings['initial_prompt'], str):
        raise ValueError('initial_prompt must be text')
    output = Path(output).resolve()
    if output.exists() and not resume:
        raise ValueError(f'Refusing to overwrite: {output}. Use --resume or a new directory.')
    if sources['hands']['path'] == sources['screen']['path'] or Path(sources['hands']['path']).samefile(sources['screen']['path']):
        raise ValueError('Hands and screen must be different source files')
    identities = {}
    infos = {}
    for role in ('hands', 'screen'):
        source = sources[role]
        number(source['offset'], 'offset')
        path = Path(source['path']).resolve()
        with path.open('rb') as file:
            digest = hashlib.file_digest(file, 'sha256').hexdigest()
        infos[role] = probe(path)
        identities[role] = {'path': str(path), 'sha256': digest, 'offset': source['offset'], **infos[role]}
    # Checking model also makes accidental tiny/default use impossible even for a silent input.
    model = check_model(model_dir)
    identity = {'version': 1, 'model': 'large-v3', 'model_repo': MODEL_REPO,
                'model_path': str(model), 'language': 'ja', 'settings': settings, 'sources': identities}
    if output.exists():
        manifest = output/'manifest.json'
        if not manifest.is_file() or json.loads(manifest.read_text()) != identity:
            raise ValueError('Resume identity differs (sources/settings/offset/model). Use a new output directory.')
    else:
        output.mkdir(parents=True)
        atomic_json(output/'manifest.json', identity)
    if (output/'transcript.json').exists():
        return output/'transcript.json'
    # Exclude concurrent writers. A killed process may leave the lock: inspect before deleting it.
    lock = output/'.lock'
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(f'Another run or stale lock exists: {lock}. Stop/verify the other run before removing it.') from exc
    os.close(descriptor)
    try:
        segments, status = [], {}
        for role in ('hands', 'screen'):
            info = infos[role]
            if not info['audio']:
                status[role] = 'no_audio'
                continue
            count = 0
            for index in range(math.ceil(info['duration']/seconds)):
                start = index*seconds
                duration = min(seconds, info['duration']-start)
                checkpoint = output/f'{role}-{index:06}.json'
                if checkpoint.exists():
                    chunk = json.loads(checkpoint.read_text())
                else:
                    print(f'ASR {role}: {start:.1f}..{start+duration:.1f}s (large-v3)', file=sys.stderr)
                    audio = extract_audio(identities[role]['path'], start, duration)
                    if not audio or max(abs(x) for x in audio) < 1e-5:
                        chunk = {'status': 'digital_silence', 'segments': []}
                    else:
                        if backend is None:
                            backend = local_backend(model)
                        result = backend(audio, settings['initial_prompt'])
                        converted = []
                        for item_index, item in enumerate(result.get('segments', [])):
                            segment = timed_item(item, role, start, identities[role]['offset'], duration, 'text')
                            segment['id'] = f'{role}-{index:06}-{item_index:04}'
                            segment['words'] = [timed_item(word, role, start, identities[role]['offset'], duration, 'word')
                                                for word in item.get('words', [])]
                            converted.append(segment)
                        chunk = {'status': 'transcribed' if converted else 'no_speech_detected', 'segments': converted}
                    atomic_json(checkpoint, chunk)
                segments.extend(chunk['segments'])
                count += len(chunk['segments'])
            status[role] = 'transcribed' if count else 'no_text'
        result = {**identity, 'status': status, 'segments': sorted(segments, key=lambda x: (x['master_start'], x['source'])),
                  'timeline': 'source/master seconds; no speed or opening transformation applied',
                  'warnings': ['Source labels are not speaker diarization.',
                               'Mic bleed and simultaneous speech are not deduplicated.',
                               'Chunk boundaries and word timestamps require review; no English subtitles generated.']}
        atomic_json(output/'transcript.json', result)
        return output/'transcript.json'
    finally:
        lock.unlink(missing_ok=True)
