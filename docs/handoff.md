# 作業引き継ぎ（2026-09-07）

## 現在地

独立した動画編集プロジェクト。ローカルは `/Users/hatadayuuhi/zenlab/maker-video-editor`、ブランチはmain。会社コンテキストのcompanyリポジトリとは別です。GitHubの保存先はZenLabInc/maker-video-editor（private）。

手元映像と画面収録の合成、非発話区間の倍速、MLX Whisper large-v3によるローカル日本語文字起こし、ログイン済みCodexによる英訳、SRT/VTT生成、英語字幕焼き込み、YouTube非公開アップロードを実装済みです。合成素材で文字起こしから字幕付き動画出力まで実行済みです。27件の単体テストが成功しています。実素材の品質評価と実投稿は未実施です。

## 外部設定

CloudプロジェクトZenLabYoutube（ID zenlabyoutube）でYouTube Data API v3を有効化済み。OAuthは外部・テスト中、テストユーザーはzenlab.jp@gmail.com。Desktopクライアント作成とGmail認証が完了しています。APIでZenLabチャンネル `UCT3Y4S8vM74xzNL6wQR1Zmg` を確認済みです。組織アカウントhatada.yuhi@zenlab.co.jpにはYouTubeチャンネルがありません。

クライアントJSONはローカルのcredentials/youtube-client.json、ユーザートークンはmacOS Keychainにあります。Gitには含めません。モデル、録画、生成動画、キャッシュもローカルのみです。別端末では依存環境・モデル・認証を準備してください。

旧Cloudプロジェクトzenorgとzenmedia-498310のみ承認に基づきシャットダウン済み（2026/10/07以降削除予定）。他プロジェクト・組織・チャンネルは維持しています。

## 次に必要な情報・作業

ユーザーから実動画または撮影フォルダの保存場所を受け取る必要があります。実素材で編集・英訳・字幕タイミングを確認し、タイトルと子ども向け指定を確定して非公開投稿します。投稿先ID、private状態、YouTube側の処理成功まで確認して完了とします。work/full-smokeの合成検証動画は投稿しません。

## 操作上の希望

常に敬語。Chrome操作は拡張経由の既存hatada.yuhi@zenlab.co.jpプロファイルを使います。そのプロファイル内でYouTubeはzenlab.jp@gmail.comを選びます。別プロファイルへ切り替えません。新たなログインが必要な場合はユーザーへ依頼します。

## 再開時の入口

README.md、docs/workflow.md、docs/youtube.mdを参照してください。Python3.11.9と.venv-asrを使用します。
