# vk-doujinmusic-rss — scraping版

VK APIを使用せず、公開されているVKウォールのHTMLをPlaywrightで取得し、
RSS 2.0へ変換してGitHub Pagesから公開します。

## 対象

- `https://vk.ru/wall-60027733`
- コミュニティ短縮名: `doujinmusic`

## API版からの変更点

- VKアプリ不要
- VKアクセストークン不要
- GitHub Actions Secret不要
- Telegramを経由しない
- VKの1ウォール投稿をRSSの1項目として出力
- 最新200投稿を10分ごとに再取得
- `vk.ru`、`vk.com`、各モバイル版を順番に試す
- VKのJavaScript検証へ対応するためPlaywrightのChromiumを使用

## 既存リポジトリへ導入する方法

リポジトリ直下へ次を置きます。

- `scrape_vk.py`

次のワークフローを作成します。

- `.github/workflows/update-rss-scrape.yml`

API版の `.github/workflows/update-rss.yml` が残っている場合は、
無効化または削除してください。API版とスクレイピング版を同時に動かすと、
同じGitHub Pages環境へ同時にデプロイして競合します。

GitHub Pagesは次の設定にします。

- `Settings`
- `Pages`
- `Build and deployment`
- `Source: GitHub Actions`

その後、次を開いて手動実行します。

- `Actions`
- `Update VK RSS by scraping`
- `Run workflow`

成功時のRSS URL:

`https://suteakadechi.github.io/vk-doujinmusic-rss/index.xml`

## 取得件数

初期設定は200件です。

```yaml
VK_POST_LIMIT: "200"
```

5分に1投稿なら、200投稿は約16時間40分分です。
GitHub Actionsが一時的に遅延しても、次の正常実行で直近200投稿を再取得します。

300件に増やす場合:

```yaml
VK_POST_LIMIT: "300"
```

ページ読み込み回数が増えるため、まず200件で動作を確認してください。

## 失敗時の確認

スクレイピングに失敗すると、Actionsの実行画面に
`vk-scraping-debug` というアーティファクトが作成されます。

中には次が入ります。

- VKから返されたHTML
- ページのスクリーンショット
- HTTPステータス、最終URL、抽出件数などのJSON

VK側のHTML変更、ログイン要求、地域制限、429制限などを切り分けるために使います。

## 制約

この方法はAPIより不安定です。次の場合は停止する可能性があります。

- VKがGitHub ActionsのIPアドレスを制限した
- 公開ページでもログインが必須になった
- VKのHTML構造が大きく変更された
- CAPTCHAや高度なbot判定が表示された
- `offset` によるページ分割が廃止された

その場合は、debugアーティファクトに合わせて抽出処理を調整します。
