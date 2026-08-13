# 補助金台帳／融資・ローン比較台帳 自動クローリング一式

補助金・融資・共済、および民間金融機関等の融資商品の情報を毎日自動で
調べ直し、サイトに反映するための一式です。このREADMEの手順通りに
進めれば、GitHubの無料機能だけで動きます（追加のデータベース契約など
は不要です）。

## 全体の仕組み

```
毎日 朝6:00（日本時間）
  → GitHub Actions が起動
  → crawler/main.py が中小企業庁・都道府県のサイトを調べる
  → data/subsidies.json に保存（前回分とマージするので、
    1回の取得失敗で情報が消えることはない）
  → crawler/main_loans.py が data/subsidies.json（政府系補助金・融資・
    共済）を融資比較用の形式に変換しつつ、民間金融機関の融資商品も
    取得して data/loans.json に保存する
  → scripts/export_to_data_js.py が docs/data.js・docs/data.json・
    docs/sitemap.xml・docs/llms.txt を、
    scripts/export_loans.py が docs/loans/loan-data.js・
    docs/loans/loan-data.json を作り直す（件数・最終更新日は
    すべて実データから計算するので、本文中に古い数字が残らない）
  → 変化があれば自動的にリポジトリへコミット
  → サイト（docs/index.html・docs/search.html・docs/loans/*.html）は
    data.js / loan-data.js を読み込んで表示するので、次にサイトを
    開いたときには自動的に最新の内容になっている
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

GitHubの「Actions」タブ →「毎日の補助金・融資・共済・民間ローンクローリング」
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
│   ├── schema.py            # 補助金台帳1件分のデータの形（型）の定義
│   ├── fetch_national.py    # 中小企業庁（全国）の取得ロジック
│   ├── fetch_prefectures.py # 都道府県の取得ロジック・設定
│   ├── main.py               # 補助金台帳をまとめて実行するスクリプト
│   ├── loan_schema.py        # 融資商品1件分のデータの形（型）の定義
│   ├── fetch_private_loans.py # 民間金融機関の取得ロジック・設定
│   └── main_loans.py         # 融資比較台帳をまとめて実行するスクリプト
│                              # （政府系データの変換＋民間データの取得）
├── scripts/
│   ├── export_to_data_js.py  # 補助金台帳: JSON → サイト表示用データ・SEO関連ファイル
│   ├── export_loans.py       # 融資比較台帳: JSON → サイト表示用データ
│   └── generate_loan_pages.py # docs/loans/ 配下12ページのHTML shellを生成
│                               # （構造を変えたい時だけ手動で再実行する。
│                               #   日次パイプラインには含まれない）
├── data/
│   ├── subsidies.json        # 補助金台帳の取得済みデータ本体
│   └── loans.json             # 融資比較台帳の取得済みデータ本体
├── docs/
│   ├── index.html            # 台帳ページ（title/meta description/OGP/JSON-LD対応）
│   ├── search.html           # 検索ページ（同上。?q=クエリで検索キーワードを渡せる）
│   ├── data.js                # サイトが読み込むデータ（自動生成される）
│   ├── data.json              # 同じ内容の素のJSON（外部ツール・LLM向け、自動生成）
│   ├── loans/
│   │   ├── index.html         # 融資・ローン比較 総合台帳（利率のある商品のみ）
│   │   ├── card-loan.html ... government.html ... other-loan.html
│   │   │                      # 融資分類ごとの台帳ページ（計11ページ）
│   │   ├── loans.css           # 融資比較ページ共通スタイル
│   │   ├── app.js              # 融資比較ページ共通ロジック（絞り込み・並び替え・描画）
│   │   ├── loan-data.js        # 全12ページが読み込むデータ（自動生成される）
│   │   └── loan-data.json      # 同じ内容の素のJSON（自動生成）
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
- `crawler/fetch_prefectures.py` の `PREF_PROGRAM_CONFIG` には、
  47都道府県分の制度融資・補助金・共済を登録済みです。
- **`crawler/fetch_private_loans.py` の `LOAN_CONFIG` は、まだ
  「カードローン」を中心に8金融機関分のみ実データを登録した段階です。**
  対象金融機関（メガバンク・信託銀行・新興銀行・政府系金融機関・
  地方銀行・消費者金融あわせて約38社）・対象融資分類（カードローン・
  教育ローン・自動車ローン・リフォームローン・不動産担保ローン・
  住宅ローン・投資不動産ローン・証券担保ローン・目的型ローン・
  その他ローン）はまだ大部分が未調査です。`LOAN_CONFIG` に
  `LoanConfig` を1件ずつ追記していくことで拡充できます
  （Claudeに「◯◯銀行の教育ローンを調べて LOAN_CONFIG に追加して」
  と頼めば対応できます）。
- 民間金融機関のサイトは、みずほ銀行のようにBot対策で自動アクセスを
  拒否するもの、プロミス・千葉銀行のようにJavaScriptで金利・限度額を
  描画していて本文から自動取得できないものが実際に存在します。
  そのため `fetch_private_loans.py` は「取得できなければ登録済みの
  値にフォールバックする」設計にしており、金利・限度額の自動更新は
  一部の金融機関でしか効きません（他は手動で確認して `LOAN_CONFIG`
  を更新する運用になります）。
