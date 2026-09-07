"""Optional packaged Silero model; no torch.hub or remote model download."""
import array
import sys
from .engine import run


def silero_detector():
    try:
        import torch
        from silero_vad import load_silero_vad, get_speech_timestamps
    except ImportError as exc:
        raise ValueError('Silero unavailable. Install .[vad], or explicitly choose analysis.method=energy.') from exc
    torch.set_num_threads(1)
    model = load_silero_vad()

    def detect(path, info, _threshold):
        if not info['audio']:
            return []
        # Bounded 5-minute windows with 1s overlap; merge happens in planner.
        ranges = []
        for start in range(0, int(info['duration'])+1, 299):
            samples = array.array('f', run(['ffmpeg', '-v', 'error', '-ss', str(start),
                '-i', path, '-t', '300', '-vn', '-ac', '1', '-ar', '16000', '-f', 'f32le', '-']).stdout)
            if sys.byteorder != 'little':
                samples.byteswap()
            if not samples:
                continue
            wav = torch.tensor(samples, dtype=torch.float32)
            for item in get_speech_timestamps(wav, model, sampling_rate=16000, return_seconds=True):
                ranges.append([start+item['start'], start+item['end']])
        return ranges
    return detect
