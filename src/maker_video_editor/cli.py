import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from .engine import create_plan, render, validate
from .session import init_session, session_config


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
    init = sub.add_parser('init-session', help='Create a recording folder with hands/ and screen/')
    init.add_argument('directory')
    session = sub.add_parser('plan-session', help='Discover videos in one recording folder')
    session.add_argument('directory')
    session.add_argument('output', help='New plan JSON path')
    session.add_argument('--config', help='Editing settings JSON (default: session/settings.json)')
    session.add_argument('--hands-index', type=int)
    session.add_argument('--screen-index', type=int)
    prepare = sub.add_parser('prepare-asr-model', help='Download the explicit MLX large-v3 model once')
    prepare.add_argument('--model-dir', default='models/whisper-large-v3')
    for name in ('transcribe-session', 'transcribe-plan'):
        asr = sub.add_parser(name, help='Japanese large-v3 ASR; sources are transcribed separately')
        asr.add_argument('input')
        asr.add_argument('output', help='New transcript/checkpoint directory')
        asr.add_argument('--model-dir', default='models/whisper-large-v3')
        asr.add_argument('--resume', action='store_true')
        asr.add_argument('--initial-prompt', help='Japanese technical vocabulary hint')
        asr.add_argument('--chunk-seconds', type=float)
        if name == 'transcribe-session':
            asr.add_argument('--config')
            asr.add_argument('--hands-index', type=int)
            asr.add_argument('--screen-index', type=int)
    translation = sub.add_parser('translate', help='English translation through saved ChatGPT Codex CLI auth')
    translation.add_argument('transcript'); translation.add_argument('output')
    translation.add_argument('--glossary', help='Japanese-to-English JSON dictionary')
    translation.add_argument('--resume', action='store_true')
    subtitles = sub.add_parser('subtitles', help='Map translations to edited SRT and WebVTT')
    subtitles.add_argument('english'); subtitles.add_argument('plan'); subtitles.add_argument('output')
    burn = sub.add_parser('burn-subtitles', help='Burn English SRT into a video for reliable YouTube delivery')
    burn.add_argument('video'); burn.add_argument('subtitles'); burn.add_argument('output')
    auth = sub.add_parser('youtube-auth', help='Desktop OAuth; stores credentials in macOS Keychain')
    auth.add_argument('client_json'); auth.add_argument('--account',default='default')
    channels = sub.add_parser('youtube-channels'); channels.add_argument('--account',default='default')
    upload_private = sub.add_parser('upload-private', help='Explicitly upload a prepared video as private only')
    upload_private.add_argument('manifest'); upload_private.add_argument('--channel-id',required=True)
    upload_private.add_argument('--made-for-kids',choices=['yes','no'],required=True)
    upload_private.add_argument('--account',default='default')
    upload_private.add_argument('--ledger',default='.cache/youtube-uploads')
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
        if args.command == 'burn-subtitles':
            from .subtitles import burn_subtitles
            print(burn_subtitles(args.video,args.subtitles,args.output))
        elif args.command == 'youtube-auth':
            from .youtube import authorize
            print(authorize(args.client_json,args.account))
        elif args.command in ('youtube-channels','upload-private'):
            from .youtube import authorized_session,get_channels,upload_private
            session=authorized_session(args.account)
            try:
                result = get_channels(session) if args.command == 'youtube-channels' else upload_private(
                    json.loads(Path(args.manifest).read_text()),args.channel_id,args.made_for_kids=='yes',args.ledger,session)
                print(json.dumps(result,ensure_ascii=False))
                if isinstance(result,dict) and result.get('state') == 'processing_failed':
                    return 3
            finally:
                session.close()
        elif args.command == 'translate':
            from .translation import translate
            glossary = json.loads(Path(args.glossary).read_text()) if args.glossary else None
            print(translate(json.loads(Path(args.transcript).read_text()), args.output, glossary, args.resume))
        elif args.command == 'subtitles':
            from .subtitles import write_subtitles
            print(write_subtitles(json.loads(Path(args.english).read_text()), json.loads(Path(args.plan).read_text()), args.output))
        elif args.command == 'prepare-asr-model':
            from .transcription import prepare_model
            print(prepare_model(args.model_dir))
        elif args.command in ('transcribe-session', 'transcribe-plan'):
            from .transcription import transcribe_sources
            if args.command == 'transcribe-session':
                config, _ = session_config(args.input, args.config, args.hands_index, args.screen_index)
                sources = {'hands': {'path': config['hands'], 'offset': 0},
                           'screen': {'path': config['screen'], 'offset': config.get('screen_offset', 0)}}
                settings = config.get('transcription', {})
            else:
                plan = json.loads(Path(args.input).read_text())
                sources, settings = plan['sources'], plan.get('transcription', {})
            if args.initial_prompt is not None:
                settings = {**settings, 'initial_prompt': args.initial_prompt}
            if args.chunk_seconds is not None:
                settings = {**settings, 'chunk_seconds': args.chunk_seconds}
            print(transcribe_sources(sources, args.output, args.model_dir, settings, args.resume))
        elif args.command == 'init-session':
            print(init_session(args.directory))
        elif args.command in ('plan', 'plan-session'):
            if Path(args.output).exists():
                raise ValueError(f'Refusing to overwrite: {args.output}')
            if args.command == 'plan':
                source = Path(args.config).resolve()
                config, base = json.loads(source.read_text()), source.parent
            else:
                config, base = session_config(args.directory, args.config,
                                              args.hands_index, args.screen_index)
            result = create_plan(config, base)
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
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        message = exc.stderr.decode(errors='replace') if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(f'ERROR: {message}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
