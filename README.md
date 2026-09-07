# maker-video-editor

Osmo Pocketの手元映像とMac画面録画を、PythonとFFmpegでローカル編集する初版です。独立したGitリポジトリで、companyリポジトリには属しません。通常の編集に生成AI API、APIトークン、編集ソフト操作は不要です。

## クイックスタート

Python 3.11以上（この環境では `.python-version` で3.11.9を選択）、PATH上の `ffmpeg` / `ffprobe`（libx264、AAC対応）が必要です。

```sh
cd /Users/hatadayuuhi/zenlab/maker-video-editor
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[vad]'
maker-video init-session media/2026-09-07-first
# 手元動画を media/2026-09-07-first/hands/ へ、画面録画を screen/ へ置きます。
# ファイル名は自由です。それぞれ1本なら自動認識します。
# 撮影フォルダーの settings.json でオフセット等を調整します（素材名は不要）。
maker-video plan-session media/2026-09-07-first outputs/plan.json
maker-video validate outputs/plan.json
maker-video preview outputs/plan.json outputs/preview.mp4
# プレビュー確認後、plan.jsonのsegmentsを直接修正できます。
maker-video render outputs/plan.json outputs/final.mp4
maker-video upload-manifest outputs/final.mp4 outputs/upload.json --title '制作記録'
```

Sileroを導入しない場合は `pip install -e .` とし、撮影フォルダーの `settings.json` にある `analysis.method` を明示的に `energy` に変更してください。energyは発話検出ではなく音量検出です。工具音や音楽も通常速度になり得ます。Silero未導入でsileroを指定した場合はエラーになり、代替解析へ自動変更しません。Sileroの実モデル推論は今回の検証環境では未検証です。

依存導入なしでenergy方式のCLIを使う場合は `PYTHONPATH=src python3 -m maker_video_editor.cli ...` でも実行できます。初回インストールにはネットワークが必要ですが、編集処理はローカルで実行します。

## 撮影単位の素材選択

`init-session` は新しい撮影フォルダーに `hands/`、`screen/`、`settings.json` を作成します。撮影ごとに別のフォルダーを指定してください。既存フォルダーへの作成は拒否します。

`plan-session` は指定した撮影の各サブフォルダー直下だけを探します。候補が複数なら端末上で番号を選びます。非対話実行では候補一覧とエラーが表示されますので、明示指定で再実行できます。

```sh
maker-video plan-session media/2026-09-07-first outputs/plan.json --hands-index 2 --screen-index 1
```

番号は名前順で、その実行時の一覧に対応します。最新版・撮影日時から推測しません。選択した絶対パスは計画へ保存するため、再レンダー時の再選択は不要です。

編集設定を共用する場合は `--config examples/session-settings.json` を使えます。OP／EDの相対パスは設定ファイル基準です。従来の `maker-video plan examples/config.json outputs/plan.json` もそのまま使えます。

## 編集内容

- 手元映像を基準に手動オフセットで同期します。初版の対象は両素材の共通区間です。重ならない冒頭・末尾は計画の警告に表示されます。
- 両音声の発話区間の和集合を通常速度、前後0.3秒と0.6秒以内の間も保護します。それ以外の映像は削除せず4倍速、倍速中の両音声はミュートします。
- 初期配置は画面を大きく、手元を右下小窓にします。指定区間で主副を入れ替えられます。
- オープニング／エンディング、素材別音量、最終音量調整に対応します。
- 計画JSONを修正して再レンダーする際は解析不要です。既存の出力ファイルは上書きしません。

## 検証と資料

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

素材検出・CLI・合成素材による27件のテストを通過しました。同期オフセット、欠落音声、通常／倍速、画面配置の画素検証、音声の時間位置とミュート、前後素材の挿入、出力尺、入力検証を確認しています。実Osmo／Mac素材、実Silero推論、YouTube認証・投稿は未検証です。

- [仕様と編集計画](docs/specification.md)
- [構成と処理方式](docs/architecture.md)
- [撮影・同期・実行手順](docs/workflow.md)
- [YouTubeアップロード設計](docs/youtube.md)
- [検証結果と制限](docs/validation.md)

YouTube非公開アップロードのコードを実装しました。正規OAuthと実動画の指定が必要です。現在はCloud準備が未完了で、実投稿していません。[YouTube連携手順](docs/youtube.md)をご覧ください。

## 日本語文字起こし → 英語字幕

Apple Silicon向けMLX Whisperの **large-v3** を明示使用します。tiny／turboへの自動変更はしません。初回のみ依存と約3GBのモデルをダウンロードします。以後の文字起こしはローカルで実行します。

```sh
pip install -e '.[asr]'
maker-video prepare-asr-model
maker-video transcribe-plan outputs/plan.json outputs/asr
# 計画作成前なら transcribe-session media/撮影01 outputs/asr も利用できます。
maker-video translate outputs/asr/transcript.json outputs/translation --glossary examples/glossary.json
maker-video subtitles outputs/translation/english.json outputs/plan.json outputs/subtitles
```

文字起こしの `transcript.json` は手元・PCを混ぜずに音源別の日本語、区間／単語の元時刻、共通時刻を保存します。これは話者分離ではありません。無音の幻覚、マイクへの回り込み、同時発話の自動解決は保証しません。

英訳にはPATH上の正規 `codex` CLIと保存済みChatGPTログインを使います。`codex login status` で確認し、未認証なら `codex login` のブラウザー操作を行ってください。CLI未導入の場合は[公式手順](https://learn.chatgpt.com/docs/cli)をご覧ください。ChatGPTの契約枠・利用制限に従い、APIキー課金へは切り替えません。日本語テキストと周辺文脈がCodexへ送られます。動画や音声は送信しません。

中断後は同じコマンドに `--resume` を付けます。入力／設定が変わった場合は別の出力先を指定してください。成功済みのASRチャンク・翻訳バッチは再処理しません。ASRは既定5分単位で処理し、字幕用時刻はPythonが速度変更・対象範囲・OP尺を反映して算出します。英訳モデルには時刻を決めさせません。

出力は `english.srt`、`english.vtt` と確認用JSONです。burn-subtitlesで字幕の焼き込みにも対応しています。字幕なしのrenderも従来どおり使えます。日本語原文と英訳は `english.json` で並べて確認できます。実素材での字幕品質は未評価です。


非公開投稿は `burn-subtitles → upload-manifest → upload-private` の明示実行です。英語字幕を焼き込み、チャンネルとprivate状態を検証します。認証情報と再開台帳はGitへ含めません。実動画が未指定のため、検証用合成動画は投稿していません。
