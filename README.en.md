# maker-video-editor

[日本語](README.md)

A local, plan-driven editor for maker videos recorded with a hand camera and a Mac screen capture. It aligns the two recordings, preserves speech at normal speed, accelerates quiet sections, switches the main and picture-in-picture views, creates English captions, and renders the result with FFmpeg.

Normal editing runs locally and does not require a generative-AI API. Optional English translation uses an authenticated Codex CLI, and optional private YouTube upload uses Google OAuth.

## Requirements

- Python 3.11 or later
- `ffmpeg` and `ffprobe` on `PATH`, with H.264 and AAC support
- Optional: Apple Silicon for the MLX Whisper transcription path

## Quick start

```sh
git clone https://github.com/ZenLabInc/maker-video-editor.git
cd maker-video-editor
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[vad]'
maker-video init-session media/first-session
# Put one hand-camera file in media/first-session/hands/
# and one screen recording in media/first-session/screen/.
maker-video plan-session media/first-session outputs/plan.json
maker-video validate outputs/plan.json
maker-video preview outputs/plan.json outputs/preview.mp4
maker-video render outputs/plan.json outputs/final.mp4
```

Edit the generated plan before the final render when timing or layout needs manual correction. Existing output files are not overwritten.

## Optional transcription and captions

```sh
pip install -e '.[asr]'
maker-video prepare-asr-model
maker-video transcribe-plan outputs/plan.json outputs/asr
maker-video translate outputs/asr/transcript.json outputs/translation --glossary examples/glossary.json
maker-video subtitles outputs/translation/english.json outputs/plan.json outputs/subtitles
```

Audio remains local during MLX Whisper transcription. Japanese text and surrounding context are sent to Codex for translation; audio and video are not sent.

## Tests

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The automated suite uses synthetic media. Real-camera synchronization, Silero inference, YouTube authorization, and a real upload require separate environment-specific checks.

## Documentation

- [Specification](docs/specification.md)
- [Architecture](docs/architecture.md)
- [Recording and editing workflow](docs/workflow.md)
- [YouTube integration](docs/youtube.md)
- [Validation notes](docs/validation.md)

## Private data

Do not commit media, transcripts, OAuth client files, access tokens, upload-resume ledgers, or generated videos. Start YouTube uploads as private and verify both the destination channel and visibility after upload.
