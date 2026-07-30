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
- 初回取得時のRSS項目を `data/feed_state.json` に保存
- 同じ投稿の本文・画像URL・日時表現が変化しても、既存RSS項目は書き換えない
- 新着がない場合は `index.xml` の内容を変化させない
- `vk.ru`、`vk.com`、各モバイル版を順番に試す
- VKのJavaScript検証へ対応するためPlaywrightのChromiumを使用

## RSSリーダーでの重複取得を防ぐ仕組み

VKのHTMLを毎回スクレイピングすると、同じ投稿でも次の情報が変化することがあります。

- 一時的な画像URL
- 抽出される本文の範囲
- 投稿日時を取得できるかどうか
- 添付リンクの表示順

RSSリーダーの中には、`guid` が同じでも項目内容が大きく変わると、
再取得または更新記事として扱うものがあります。

この版では、投稿を初めて検出したときの `title`、`link`、`guid`、
`pubDate`、`description` を `data/feed_state.json` に保存します。
同じ投稿を再び取得した場合は、スクレイピング結果で上書きせず、
保存済みのRSS項目をそのまま出力します。

また、状態ファイルがまだない最初の実行では、次の公開中RSSを読み込み、
既存項目を引き継ぎます。

`https://suteakadechi.github.io/vk-doujinmusic-rss/index.xml`

これにより、修正版へ移行するときも既存項目の `guid` を変更しません。
状態ファイルは新着があったときだけGitHub Actionsからリポジトリへコミットされます。

公開URLを変更した場合は、ワークフロー内の次の値も変更してください。

```yaml
RSS_PREVIOUS_FEED_URL: "https://example.github.io/repository/index.xml"
```

`data/feed_state.json` は削除しないでください。削除すると、公開中RSSからの
再取り込みを試みますが、取得できない場合は現在のスクレイピング結果から
状態を作り直すため、RSSリーダーによっては既存項目を再評価する可能性があります。

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
