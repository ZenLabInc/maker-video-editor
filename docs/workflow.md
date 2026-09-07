# 実行手順

素材置き場は `/Users/hatadayuuhi/zenlab/maker-video-editor/media/` です。撮影ごとに次のコマンドで専用フォルダーを作成してください。

```sh
maker-video init-session media/2026-09-07-first
```

```text
media/2026-09-07-first/
  hands/          ← microSDの手元動画（名前は自由）
  screen/         ← Mac画面録画（名前は自由）
  settings.json   ← オフセット・解析方式等。素材名の記入は不要
```

`maker-video plan-session media/2026-09-07-first outputs/plan.json` で自動認識して計画を生成します。1候補は自動、複数候補は番号選択、0候補はエラーです。非対話ではエラーに表示される番号を `--hands-index 2` / `--screen-index 1` で指定します。別の撮影フォルダーや入れ子フォルダーは検索しません。複数ファイルの自動連結は行いません。

大文字・小文字を問わずmp4/mov/mkv/webm/m4v/avi/mts/m2tsを候補にします。隠しファイル（AppleDoubleを含む）とシンボリックリンクは除外します。手元と画面に同じ実ファイルのハードリンクを選んだ場合はエラーです。フォルダー内の素材・設定はGit管理から除外されます。

従来の直接指定も利用できます。その場合のみ `examples/config.json` の `../media/hands.mov` 等を実ファイル名へ変更してください。

1. OsmoのmicroSDから撮影ファイルを撮影フォルダーのhands/へコピーしてください。元データは保持してください。Mac画面録画を同じ撮影のscreen/へ保存し、プレーヤーで映像・内部音声の存在を先に確認してください。内部音声の録画方法はこの初版では設定しません。
2. できれば両動画で同じイベントを記録してください。Mac側の画面変化を手元カメラにも映すなど、共通音がなくても視覚マーカーを作れます。末尾にもマーカーを残すとドリフトを確認できます。
3. 同じイベントが手元で10秒、画面で7秒ならscreen_offset=3です。逆なら負数です。推測値の0で始めた場合も、プレビューで同期を必ず確認してください。
4. 撮影フォルダーのsettings.jsonを編集します。区間は完成動画の時刻ではなく手元の元動画の時刻です。例：normal_ranges=[[30,35]]、hands_large_ranges=[[20,50]]。支給されたopening/endingのパスを設定してください。
5. READMEのplan-session、previewを実行します。previewは全区間を最大幅640pxで出力する低解像度版です。部分プレビューや対話GUIはありません。
6. 発話の欠け、無言作業の4倍速、PC音声、音量、レイアウト、冒頭・末尾の同期を確認してください。重要音が速くなっていたら計画を分割してspeed=1にしてください。発話なしの区間は映像を残します。
7. JSON修正後はvalidate、renderを実行してください。解析は再実行しません。素材を移動した場合はsources.pathを更新してください。素材自体を編集・差し替えた場合は計画も作り直してください。
8. 完成動画を通して確認後、upload-manifestで投稿準備ファイルを生成できます。実投稿機能は未実装です。

## エラーと制限への対応

- Silero unavailable：対応Python環境で `pip install -e '.[vad]'` を実行するか、明示的にenergyへ変更してください。今回のPython 3.14環境ではSilero依存導入・推論を検証していません。
- no audio stream：元動画の音声収録を確認してください。音声なしの側からは通常速度候補を作れません。
- no overlap：オフセットの符号と値を確認してください。
- Refusing to overwrite：別の出力ファイル名を指定してください。
- 長時間で同期がずれる：初版はドリフト自動補正非対応です。録画条件を揃えるか、外部で補正した素材を用意してください。
- HDR/D-Log素材の色：初版はSDR向けです。適切なトーンマッピング／LUT適用は未実装です。SDR素材から開始してください。

VFR、異なる解像度／fpsはFFmpegのCFR出力へ変換しますが、実機録画での検証は未了です。元動画のタイムスタンプが不連続、音声が大きく遅延して始まる、複数音声トラックがある素材は事前に正規化してください。数百の短い区間ではフレーム単位の丸めが累積するため、完成尺・同期を点検してください。

## 文字起こしと英語字幕の実行

1. Apple Silicon上のPython 3.11環境で `pip install -e '.[asr]'` を実行してください。既存のSilero依存とは別のオプションです。両方必要なら `pip install -e '.[asr,vad]'` とします。
2. `maker-video prepare-asr-model` でlarge-v3をmodels/whisper-large-v3へ初回取得します。モデルと環境はGit除外です。別配置には--model-dirを指定します。
3. `maker-video transcribe-plan outputs/plan.json outputs/asr` を実行します。計画がなければ `transcribe-session media/撮影01 outputs/asr` を使い、既存と同じ候補選択が可能です。
4. 必要なら--initial-promptで専門用語を渡します。plan生成時にはsettings.jsonのtranscription設定も引き継がれます。
5. `codex login status` でChatGPT認証を確認します。未認証ならcodex loginのブラウザー認証を行ってください。資格情報をJSONや会話へ記載する必要はありません。
6. `maker-video translate outputs/asr/transcript.json outputs/translation --glossary examples/glossary.json` で英訳します。english.jsonで日本語と英語を見比べて修正できます。
7. `maker-video subtitles outputs/translation/english.json outputs/plan.json outputs/subtitles` でenglish.srt／english.vttを生成します。プレーヤーへ読み込み、完成動画の時刻・速度境界・重なりを確認してください。

ASR／翻訳で中断した場合は--resumeを付けて同じ入出力を指定します。入力や用語辞書の変更時は新しい出力先を使います。字幕生成は翻訳を再実行せず繰り返せますが、新しい出力先を指定してください。
