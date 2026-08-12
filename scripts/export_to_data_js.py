"""
data/subsidies.json を、サイトが読み込める形式に変換して docs/ に書き出す。

    python scripts/export_to_data_js.py

これを実行すると、以下が作られる（すべて上書き）。

    docs/data.js     … search.html / index.html が読み込む `const DATA = [...]`
    docs/data.json    … 同じ内容の素のJSON（LLM・外部ツールが直接fetchしやすいように）
    docs/sitemap.xml  … 検索エンジン向けのサイトマップ（lastmodはデータの最新確認日）
    docs/llms.txt     … LLM向けのサイト概要（llms.txt規格）。件数・最終更新日を都度更新する

search.html / index.html 側は、
    <script src="data.js"></script>
を読み込むようになっているので、以降は data.js を差し替えるだけで
サイトの表示内容が自動的に更新される（HTML自体を毎回書き換える必要がない）。

sitemap.xml・llms.txt は「本文中に数字を書くと古くなる」問題（実際に
index.html/search.htmlで起きた）を避けるため、ページ本文と同じ考え方で
このスクリプトが実行されるたびに実際の件数・最新確認日から再生成する。

（出力先が docs/ なのは、GitHub Pages の公開フォルダとして
  リポジトリ直下では /(root) か /docs しか選べないため。）
"""

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "subsidies.json"
DOCS_DIR = ROOT / "docs"

SITE_BASE_URL = "https://masanori141-oss.github.io/sme-support-japan/"


def load_data() -> list:
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def write_data_js(data: list) -> None:
    path = DOCS_DIR / "data.js"
    content = "const DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n"
    path.write_text(content, encoding="utf-8")
    print(f"{len(data)} 件を {path} に書き出しました。")


def write_data_json(data: list) -> None:
    path = DOCS_DIR / "data.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(data)} 件を {path} に書き出しました。")


def latest_checked_at(data: list) -> str:
    dates = sorted({d["sourceCheckedAt"] for d in data if d.get("sourceCheckedAt")})
    return dates[-1] if dates else datetime.now().strftime("%Y-%m-%d")


def write_sitemap(data: list) -> None:
    lastmod = latest_checked_at(data)
    urls = [
        (SITE_BASE_URL, "1.0"),
        (SITE_BASE_URL + "search.html", "0.9"),
    ]
    entries = "\n".join(
        f"  <url>\n"
        f"    <loc>{loc}</loc>\n"
        f"    <lastmod>{lastmod}</lastmod>\n"
        f"    <changefreq>daily</changefreq>\n"
        f"    <priority>{priority}</priority>\n"
        f"  </url>"
        for loc, priority in urls
    )
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>\n"
    )
    path = DOCS_DIR / "sitemap.xml"
    path.write_text(content, encoding="utf-8")
    print(f"sitemap.xml を {path} に書き出しました。")


def write_llms_txt(data: list) -> None:
    total = len(data)
    loan = sum(1 for d in data if d["category"] == "融資")
    subsidy = sum(1 for d in data if d["category"] == "補助金")
    kyosai = sum(1 for d in data if d["category"] == "共済")
    updated = latest_checked_at(data)

    content = f"""# 補助金台帳 (Subsidy Ledger) — 日本の中小企業向け補助金・制度融資・共済データベース

> 日本の中小企業・小規模事業者向けに、中小企業庁（全国）および47都道府県が実施する補助金・制度融資・共済制度を横断的にまとめた非公式データベースです。中小企業庁および各都道府県の公式サイトの情報をもとに収集・統合しています。現在{total}件の制度を掲載（内訳: 補助金{subsidy}件・融資{loan}件・共済{kyosai}件、最終更新: {updated}）。本サイトは非公式の情報整理ツールであり、公式情報ではありません。申請・加入前には必ず各制度の公式サイト・パンフレットで最新の状況をご確認ください。

## サイト

- [台帳ページ]({SITE_BASE_URL}index.html): 代表的な制度を詳細カード形式で紹介
- [検索ページ]({SITE_BASE_URL}search.html): 区分（補助金・融資・共済）・都道府県・事業規模・目的で絞り込み検索できる全件一覧

## データ

- [data.json]({SITE_BASE_URL}data.json): 掲載している全{total}件の構造化データ（JSON配列）。1件ごとに制度名（title）・区分（category: 補助金/融資/共済）・対象都道府県（pref）・上限額（amountLabel）・補助率/利率（rateLabel）・締切（deadline, deadlineLabel）・対象要件（eligibility）・公式URL（url）・確認日（sourceCheckedAt）などを含みます。

## 更新方法

data.json / data.js は GitHub Actions により毎日自動で再取得・更新されます（1回の取得に失敗した項目は前回値を保持するため、情報が急に消えることはありません）。
"""
    path = DOCS_DIR / "llms.txt"
    path.write_text(content, encoding="utf-8")
    print(f"llms.txt を {path} に書き出しました。")


def run():
    data = load_data()
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    write_data_js(data)
    write_data_json(data)
    write_sitemap(data)
    write_llms_txt(data)


if __name__ == "__main__":
    run()
