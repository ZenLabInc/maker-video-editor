# YouTube非公開連携

## 実装済みと外部準備

正規Desktop OAuth、macOS Keychainへのトークン保存、YouTube Data APIの再開アップロード、重複防止、投稿先とprivate状態の確認を実装しました。API連携はprivateのみ扱います。実動画の投稿は未実施です。

2026-09-07: ユーザーが専用プロジェクト ZenLabYoutube (`zenlabyoutube`、番号86544629335) を作成し、YouTube Data API v3の有効化とOAuth同意画面の初期構成を完了しました。承認を受けてDesktopクライアント ZenLab YouTube Desktopを作成し、クライアントJSONをGit除外のcredentials/へ権限0600で保存しました。hatada.yuhi@zenlab.co.jpで正規OAuth認証が成功し、トークンはmacOS Keychainへ保存済みです。ただし、このアカウントのchannels.list(mine=true)は空でした。

同日のYouTube Studioアカウント一覧で、ZenLab (@ZenLabInc、チャンネルID `UCT3Y4S8vM74xzNL6wQR1Zmg`) は zenlab.jp@gmail.com に紐づき、hatada.yuhi@zenlab.co.jpは「チャンネルがありません」と確認しました。ユーザー承認後、OAuthを外部・テスト中へ変更し、zenlab.jp@gmail.comのみをテストユーザーとして追加しました。同Gmailで再認証し、Keychainの既定資格情報を更新済みです。channels.list(mine=true)からZenLabと上記チャンネルIDが返り、投稿先の一致を確認しました。実動画素材の保存場所が未提供のため、投稿は未実施です。

承認された旧プロジェクトZenOrg (`zenorg`) とZenMedia (`zenmedia-498310`) のみシャットダウン済みです。Cloud画面で2026/10/07以降の削除予定を確認しました。同名の別プロジェクトZenMedia (`gen-lang-client-0695258215`)、その他プロジェクト、組織、YouTubeチャンネルは変更していません。

## 認証の準備

1. Cloudで専用プロジェクトを選び、YouTube Data API v3を有効にしてください。不要な課金設定は不要です。
2. OAuth同意画面を構成し、Desktop appのOAuthクライアントを作成してください。取得JSONは `credentials/youtube-client.json` などGit除外領域へ保存し、秘密を会話やログに貼り付けないでください。
3. `pip install -e '.[youtube]'` を実行してください。
4. `maker-video youtube-auth credentials/youtube-client.json` を実行し、表示される正規Google認証URLを指定の既存Chromeプロファイルで開いて同意してください。アプリはブラウザーを自動で別プロファイルに開きません。ローカルループバックコールバックを使い、待機上限は600秒です。
5. `maker-video youtube-channels` で認証されたチャンネルを確認してください。

トークンはmacOS Keychainのmaker-video-editor.youtubeへ保存します。平文トークンファイルへ自動フォールバックしません。スコープはyoutube.uploadとyoutube.readonlyです。後者はチャンネル照合と非公開・処理状態確認に使います。OAuthクライアントとユーザートークンをプログラムが会話へ出力することはありません。

## 字幕を確実に付ける方式

初版の投稿経路は英語SRTを映像へ焼き込む方式です。字幕トラック追加APIは使いません。プレーヤーによる表示設定に依存せず英語字幕が表示されますが、視聴者は字幕をオフにできず、訂正には再レンダーが必要です。字幕なしの元動画とSRT／WebVTTは保持できます。

```sh
maker-video burn-subtitles outputs/final.mp4 outputs/subtitles/english.srt outputs/final-en.mp4
maker-video upload-manifest outputs/final-en.mp4 outputs/upload.json --title '制作記録'
maker-video upload-private outputs/upload.json \
  --channel-id UCT3Y4S8vM74xzNL6wQR1Zmg --made-for-kids no
```

子ども向け指定は動画の実内容に合わせてyes/noを明示してください。上記noは構文例であり、ユーザーの動画に対する判定ではありません。対象実動画、タイトル等が未確定なら投稿は実行しません。work/full-smokeの合成動画は検証専用で投稿しません。

burn-subtitlesはlibassで字幕を焼き込み、動画と字幕のハッシュ証跡を `動画名.subtitles.json` に保存します。upload-privateは証跡と動画ハッシュが一致する場合だけ送信します。証跡は品質保証や改ざん耐性署名ではなく、ローカル工程の取り違え防止です。

## 状態・再開・重複防止

既定台帳は `.cache/youtube-uploads/`、ディレクトリ0700／ファイル0600です。セッションURLも機密として扱い、画面やエラーへ出しません。台帳は削除しないでください。別の台帳を指定した場合や台帳紛失時には、過去の重複を防ぐことはできません。

チャンネルIDと完成動画SHA-256をキーに、prepared→initializing→uploading→uploaded→processing→completeを保存します。メタデータ変更による同一動画の再投稿は拒否します。初期化応答が不明な場合は自動で新規セッションを作らず停止します。再開時はサーバーの受信済み位置を毎回問い合わせ、Rangeに従って未受信バイトを送ります。通常は8MiB単位です。

429／500／502／503／504は上限付き指数バックオフで再試行します。通信例外では状態を保持して停止し、同じコマンドで再開します。期限切れ404などは新規投稿に切り替えません。セッション完了応答が不明な場合も、まず既存セッションへ問い合わせます。台帳に動画IDがあれば新規POSTせず、既存動画の状態を確認します。

APIでチャンネルIDとprivateを再確認し、処理成功を確認したときだけcompleteです。processingは処理待ちで、同じコマンドを後で実行して確認してください。processing_failedは処理失敗でCLI終了コード3です。アップロード完了だけで投稿工程全体が成功とは報告しません。公開や公開予約への変更機能はありません。

2020年7月28日以降に作成された未監査APIプロジェクトからの投稿は非公開に制限され、解除には監査が必要です。本ツールはprivate固定のため、解除を試みません。

公式資料：

- [Videos API／非公開制限](https://developers.google.com/youtube/v3/docs/videos)
- [再開可能アップロード](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol)
- [Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app)
