import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from .engine import create_plan, render, validate


def write_json(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write('\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline dual-source maker video editor')
    sub = parser.add_subparsers(dest='command', required=True)
    plan = sub.add_parser('plan', help='Analyze sources and create an editable JSON plan')
    plan.add_argument('config'); plan.add_argument('output')
    check = sub.add_parser('validate'); check.add_argument('plan')
    for name in ('preview', 'render'):
        command = sub.add_parser(name)
        command.add_argument('plan'); command.add_argument('output')
    upload = sub.add_parser('upload-manifest', help='Prepare metadata only; never uploads')
    upload.add_argument('video'); upload.add_argument('output')
    upload.add_argument('--title', required=True)
    upload.add_argument('--description', default='')
    args = parser.parse_args(argv)
    try:
        if args.command == 'plan':
            source = Path(args.config).resolve()
            result = create_plan(json.loads(source.read_text()), source.parent)
            write_json(args.output, result)
            for warning in result['warnings']:
                print('WARNING:', warning, file=sys.stderr)
        elif args.command == 'upload-manifest':
            path = Path(args.video).resolve()
            with path.open('rb') as file:
                hasher = hashlib.sha256()
                while chunk := file.read(1024 * 1024):
                    hasher.update(chunk)
                digest = hasher.hexdigest()
            write_json(args.output, {'version': 1, 'video': str(path), 'sha256': digest,
                'bytes': path.stat().st_size, 'body': {'snippet': {'title': args.title,
                'description': args.description}, 'status': {'privacyStatus': 'private'}},
                'state': 'prepared', 'network_request_sent': False})
        else:
            result = json.loads(Path(args.plan).read_text())
            validate(result)
            if args.command != 'validate':
                print(json.dumps(render(result, args.output, args.command == 'preview')))
            else:
                print('Plan valid')
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        message = exc.stderr.decode(errors='replace') if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(f'ERROR: {message}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
