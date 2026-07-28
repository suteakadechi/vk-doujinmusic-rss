# vk-doujinmusic-rss

VKコミュニティ `doujinmusic` のウォール投稿を、GitHub Actionsで定期取得し、
GitHub PagesからRSS 2.0として公開するためのひな形です。

## 特徴

- VK APIの `wall.get` を直接使用
- Telegramを経由しない
- VKの1投稿をRSSの1項目として出力
- 写真・動画・文書・外部リンクなどを同じRSS項目の本文へまとめる
- 10分間隔で最新300投稿を再取得
- ローカルサーバー不要
- パブリックリポジトリならGitHub ActionsとPagesを無料で利用可能

## 1. VKのサービスアクセストークンを用意

VK Developersでアプリケーションを作成し、アプリ設定に表示される
サービスアクセストークン／Service access keyを取得してください。

`wall.get` はVK APIスキーマ上、ユーザートークンとサービストークンの
両方に対応しています。トークンはリポジトリ内のファイルへ書かず、
GitHub Actions Secretへ保存します。

VKの管理画面は変更されることがあります。サービスキーで
`wall.get` が拒否される場合は、同じアプリで取得したユーザーアクセストークンを
代わりに使用してください。

## 2. GitHubにパブリックリポジトリを作成

例:

- リポジトリ名: `vk-doujinmusic-rss`
- Visibility: Public

このひな形の内容を、リポジトリのルートへアップロードします。

## 3. Secretを登録

リポジトリで次を開きます。

`Settings` → `Secrets and variables` → `Actions`
→ `New repository secret`

- Name: `VK_ACCESS_TOKEN`
- Secret: VKで取得したトークン

トークンをREADME、YAML、Pythonファイルへ直接書かないでください。

## 4. GitHub Pagesを有効にする

`Settings` → `Pages` → `Build and deployment`

- Source: `GitHub Actions`

## 5. 初回実行

`Actions` → `Update VK RSS` → `Run workflow`

成功後、PagesのURLは通常、次の形式です。

`https://GITHUBユーザー名.github.io/vk-doujinmusic-rss/index.xml`

このURLをFeedbroなどへ登録します。

## 取得漏れへの耐性

現在の設定では、10分ごとに最新300投稿を取り直します。
仮に5分に1投稿でも、300投稿の範囲は約25時間分に相当します。

GitHub Actionsの実行が数回遅延・欠落しても、次の正常実行が
最新300投稿を再取得するため、短時間の障害で投稿が抜けにくい構成です。

項目数を増やす場合は、ワークフロー内の次の値を変更します。

`VK_POST_LIMIT: "300"`

上限はこのスクリプトでは1000です。VK APIは1回につき最大100投稿なので、
300なら3回、500なら5回APIを呼び出します。

## 更新間隔

現在は10分間隔です。

```yaml
- cron: "7,17,27,37,47,57 * * * *"
```

5分間隔にする場合:

```yaml
- cron: "2,7,12,17,22,27,32,37,42,47,52,57 * * * *"
```

毎時0分付近はGitHub Actionsが混雑しやすいため避けています。

## 注意事項

- Pagesに公開されるRSS自体は誰でも閲覧できます。
- VKアクセストークンはGitHub Secretに保存され、Pagesには含まれません。
- VK APIの仕様変更、トークン失効、対象ページの公開範囲変更により停止する場合があります。
- Actions画面で失敗した実行を開くと、`VK API error 番号`を確認できます。
- パブリックリポジトリの定期ワークフローは、長期間活動がないと無効化されるため、
  月1回だけ自動コミットするkeepalive処理を含めています。
