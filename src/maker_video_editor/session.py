"""Explicit recording sessions; never infer a recording from timestamps."""
import json
from pathlib import Path
import sys

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm', '.m4v', '.avi', '.mts', '.m2ts'}
DEFAULT_SETTINGS = {
    'screen_offset': 0,
    'analysis': {'method': 'silero', 'threshold_db': -38, 'padding': 0.3, 'bridge_gap': 0.6},
    'silent_speed': 4, 'normal_ranges': [], 'hands_large_ranges': [],
    'gains': {'hands': 1.0, 'screen': 0.8}, 'opening': None, 'ending': None,
    'output': {'width': 1920, 'height': 1080, 'fps': 30},
}


def init_session(directory):
    root = Path(directory).absolute()
    # Refuse existing directories, including empty ones, to prevent mixing shoots.
    root.mkdir(parents=True, exist_ok=False)
    for name in ('hands', 'screen'):
        (root / name).mkdir()
    (root / 'settings.json').write_text(json.dumps(DEFAULT_SETTINGS, indent=2) + '\n')
    return root


def candidates(root, role):
    directory = root / role
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f'Expected a real directory: {directory}')
    return sorted((p for p in directory.iterdir()
                   if not p.name.startswith('.') and not p.is_symlink()
                   and p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS),
                  key=lambda p: (p.name.casefold(), p.name))


def select(files, role, index=None):
    if not files:
        raise ValueError(f'No video in {role}/. Add a supported video directly to that folder.')
    listing = '\n'.join(f'  {i}: {p.name}' for i, p in enumerate(files, 1))
    if index is None and len(files) == 1:
        return files[0]
    if index is None:
        if not sys.stdin.isatty():
            raise ValueError(f'Multiple videos in {role}/:\n{listing}\n'
                             f'Rerun with --{role}-index NUMBER (1..{len(files)}).')
        print(f'{role}/ videos:\n{listing}', file=sys.stderr)
        try:
            index = int(input(f'Select {role} number (1..{len(files)}): '))
        except (ValueError, EOFError) as exc:
            raise ValueError('Selection cancelled or invalid; no plan created.') from exc
    if not 1 <= index <= len(files):
        raise ValueError(f'--{role}-index must be 1..{len(files)}:\n{listing}')
    return files[index - 1]


def session_config(directory, config=None, hands_index=None, screen_index=None):
    root = Path(directory).resolve(strict=True)
    source = Path(config).resolve(strict=True) if config else root / 'settings.json'
    settings = json.loads(source.read_text())
    chosen = {role: select(candidates(root, role), role, index)
              for role, index in [('hands', hands_index), ('screen', screen_index)]}
    if chosen['hands'].samefile(chosen['screen']):
        raise ValueError('Hands and screen are the same file (including hard links).')
    settings.update({role: str(path) for role, path in chosen.items()})
    for role, path in chosen.items():
        print(f'{role}: {path}', file=sys.stderr)
    return settings, source.parent
