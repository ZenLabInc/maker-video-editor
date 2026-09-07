# 構成

```text
microSD / Mac録画
      ↓ ファイルコピー（手動）
config.json → CLI plan → 発話検出または明示energy → plan.json
                                                   ↓ 修正
                                   validate → preview / render
                                                   ↓
                                               final.mp4
                                                   ↓
                                            upload-manifest
```

- `src/maker_video_editor/cli.py`：CLIとJSON入出力、投稿準備ファイル。
- `session.py`：撮影フォルダー作成、直下動画の発見、候補選択、同一ファイル拒否。
- `engine.py`：ffprobe、音量解析、区間の和集合、計画検証、FFmpegレンダー。
- `vad.py`：オプションのSilero。5分窓を1秒重ねて処理し、長時間音声のメモリ使用を抑えます。
- `tests/test_pipeline.py`：FFmpegで小さな合成映像・音声を作成する統合テスト。

レンダーは区間別に入力をシークし、PTSを0からの共通時間へ正規化して速度を適用します。音声欠落には無音を供給します。映像の配置と音声ミックスを済ませたH.264/AACの一時MP4を同じ解像度・fpsで生成し、concatして最終音量調整をします。中間ファイルは出力先の一時ディレクトリに保存され、成功・例外時に削除します。最後に同じファイルシステムでハードリンクして、完成出力を上書きせず公開します。

Pythonは標準ライブラリだけでもenergy方式で動作します。FFmpegは外部プロセスです。シェル文字列として素材パスを実行しません。通常編集にネットワーク処理はありません。

将来は区間キャッシュ、二回音量測定、VAD品質評価、字幕、任意レイアウト、複数素材、YouTube実行アダプターを追加できます。同期ドリフトはマーカー2点から `master=a*source+b` を推定し、映像と音声の両方へ同一補正を入れる予定です。初版はa=1の固定オフセットのみです。

## ASR／字幕工程

```text
撮影フォルダー または plan.json
  → transcribe-session / transcribe-plan
  → 音源別FFmpeg抽出 → ローカルMLX large-v3
  → ASRチャンクチェックポイント → transcript.json
  → translate → 正規 codex exec（ChatGPT保存認証／構造化出力）
  → 翻訳バッチキャッシュ → english.json（日本語＋英語＋元時刻）
  → subtitles + plan.json → Python時刻変換 → SRT / WebVTT
```

transcription.pyはモデル準備と検査、音声抽出、ASR、チャンク保存／再開を担います。translation.pyは認証方式確認、固定プロンプト、バッチ分割、ID検証、翻訳再開を担います。subtitles.pyは時刻計算、整形、同時字幕の統合、SRT／WebVTT出力を担います。

Codexは独立した一時作業ディレクトリ、read-only、承認never、シェル無効、Web検索無効、ユーザー設定を読み込まないモードで実行します。保存認証の正規利用は維持します。APIキー／アクセストークンの環境注入は引き継がず、API課金へ切り替えません。追加の権限が必要な翻訳は失敗として扱います。CLI実行に600秒の上限を設けます。

ASR・英訳は入力ハッシュと設定が一致するときだけ再開します。成功ファイルは原子的に作成して上書きせず、同時実行を.lockで拒否します。元動画が長くてもASRの音声メモリはチャンク単位です。最終段落一覧とJSONは全体をメモリへ保持するため、無制限サイズは想定しません。


## 非公開投稿工程

SRT + 完成動画 → burn-subtitles（libass）→ 字幕付きMP4＋ハッシュ証跡 → upload-manifest → upload-private → YouTube処理確認、という流れです。youtube.pyに正規OAuth、Keychain、HTTPS要求、サーバーRangeによる再開、非公開検証、台帳を分離しました。実APIと同じHTTP状態遷移をモックで試験します。ブラウザーによるCloud設定は別途必要です。
