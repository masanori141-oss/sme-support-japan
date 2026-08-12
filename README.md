# 補助金台帳 自動クローリング一式

補助金・融資・共済の情報を毎日自動で調べ直し、サイトに反映するための一式です。
このREADMEの手順通りに進めれば、GitHubの無料機能だけで動きます
（追加のデータベース契約などは不要です）。

## 全体の仕組み

```
毎日 朝6:00（日本時間）
  → GitHub Actions が起動
  → crawler/main.py が中小企業庁・都道府県のサイトを調べる
  → data/subsidies.json に保存（前回分とマージするので、
    1回の取得失敗で情報が消えることはない）
  → scripts/export_to_data_js.py が docs/data.js・docs/data.json・
    docs/sitemap.xml・docs/llms.txt を作り直す（件数・最終更新日は
    すべて実データから計算するので、本文中に古い数字が残らない）
  → 変化があれば自動的にリポジトリへコミット
  → サイト（docs/search.html, docs/index.html）は data.js を
    読み込んで表示するので、次にサイトを開いたときには
    自動的に最新の内容になっている
```

## 必要なアカウント

- **GitHubアカウント**（無料）。これだけです。
- サイトを実際にインターネット上に公開したい場合は、GitHub Pages
  （GitHubに無料で付いている機能）を使うのがもっとも簡単です。

## セットアップ手順

### 1. GitHubにリポジトリを作る

GitHubで新しいリポジトリを作成し（例: `subsidy-database`）、この
フォルダの中身をすべてアップロードしてください。

やり方が分からない場合は、Claude（Claude Code）に
「このフォルダをGitHubの新しいリポジトリにアップロードして」と
頼めば、コマンドを実行して代わりに進めることができます
（ただしGitHubアカウントへのログイン・認証だけはご自身の操作が必要です）。

### 2. GitHub Actionsを有効にする

特別な操作は不要です。`.github/workflows/daily-crawl.yml` が
入った状態でリポジトリにアップロードするだけで、GitHub側が
自動的に「毎日この時間に実行する」設定を認識します。

リポジトリの「Actions」タブを開くと、実行結果（成功・失敗）を
確認できます。

### 3. （任意）今すぐ1回試してみる

GitHubの「Actions」タブ →「毎日の補助金・融資・共済クローリング」
→「Run workflow」ボタンで、スケジュールを待たずに今すぐ
1回実行できます。

### 4. （任意）サイトを公開する

GitHubリポジトリの Settings → Pages で「docs」フォルダを
公開対象に設定すると、`https://（あなたのアカウント名）.github.io/（リポジトリ名）/`
のようなURLでサイトが誰でも見られるようになります
（GitHub Pagesは /(root) か /docs しか公開フォルダに選べないため、
このリポジトリではサイト一式を docs/ に置いています）。

## ファイル構成

```
subsidy-crawler/
├── crawler/
│   ├── schema.py            # 1件分のデータの形（型）の定義
│   ├── fetch_national.py    # 中小企業庁（全国）の取得ロジック
│   ├── fetch_prefectures.py # 都道府県の取得ロジック・設定
│   └── main.py               # 全体をまとめて実行するスクリプト
├── scripts/
│   └── export_to_data_js.py # JSON → サイト表示用データ・SEO関連ファイルへの変換
├── data/
│   └── subsidies.json        # 取得済みデータ本体
├── docs/
│   ├── index.html            # 台帳ページ（title/meta description/OGP/JSON-LD対応）
│   ├── search.html           # 検索ページ（同上。?q=クエリで検索キーワードを渡せる）
│   ├── data.js                # サイトが読み込むデータ（自動生成される）
│   ├── data.json              # 同じ内容の素のJSON（外部ツール・LLM向け、自動生成）
│   ├── sitemap.xml            # 検索エンジン向けサイトマップ（自動生成）
│   ├── robots.txt             # クローラー向け設定（sitemap.xmlの場所を案内）
│   ├── llms.txt                # LLM向けサイト概要（llms.txt規格、自動生成）
│   └── .nojekyll               # GitHub PagesのJekyllビルドを無効化
├── .github/workflows/
│   └── daily-crawl.yml       # 「毎日自動実行して」という設定ファイル
└── requirements.txt           # 必要なPythonライブラリの一覧
```

## 今後、詰めていく必要がある部分（正直な注意点）

- **`crawler/fetch_national.py` と `crawler/fetch_prefectures.py` は
  「動く出発点」です。** このコードを書いた環境はインターネットに
  接続できなかったため、実際に中小企業庁や都道府県のサイトに
  アクセスして中身を確認する検証はできていません。
  初回実行後、GitHub Actionsの実行ログ・取得結果
  （data/subsidies.json の中身）を見て、正しく取れているかを
  確認してください。
- 取れていない・崩れている場合は、該当箇所のHTML構造を確認し、
  抽出ロジック（`BeautifulSoup` の `select(...)` 部分）を
  調整する必要があります。ここはClaude（Claude Code）に
  「このページの構造に合わせて fetch_national.py を直して」と
  頼めば、対応できます。
- `crawler/fetch_prefectures.py` の `PREF_LOAN_CONFIG` には、
  今回のResearchで判明した数県分のみサンプルとして入れています。
  残りの都道府県も、既存の `data/subsidies.json` に入っている
  84件の値を見ながら追記していくのが最短ルートです。
