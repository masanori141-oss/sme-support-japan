"""
docs/loans/ 配下の12ページ（総合台帳 + 融資分類11ページ）のHTML shellを
生成する。

    python scripts/generate_loan_pages.py

このスクリプトは日次のクローリングパイプラインには含まれない
（ページの「構造」は毎日変わらないため）。一度実行して生成した
HTMLファイルはリポジトリにコミットし、以後は docs/loans/loan-data.js
（scripts/export_loans.py が毎日更新する）だけがページの表示内容を
更新する。ページ構造そのものを変えたい場合だけ、このスクリプトを
直接編集して再実行する。

12ファイルをテンプレートから生成しているのは、ほぼ同一のHTML shell
（ナビ・フィルターUI・スクリプト読み込み）を手作業で12個複製すると、
デザイン修正のたびにファイルごとにズレが生じるのを避けるため。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "docs" / "loans"
SITE_BASE_URL = "https://masanori141-oss.github.io/sme-support-japan/"

# (スラッグ, 表示名, ファイル名, 一言説明, 対象金融機関の目安)
CATEGORIES = [
    ("all", "総合台帳（全分類）", "index.html",
     "全11分類の民間融資・政府系融資を横断し、下限金利が低い順に一覧できる総合台帳です。",
     "メガバンク・信託銀行・新興銀行・政府系金融機関・地方銀行・消費者金融"),
    ("card-loan", "カードローン", "card-loan.html",
     "使いみち自由なカードローン・キャッシングを、金利・限度額で比較できます。",
     "メガバンク・新興銀行・地方銀行・消費者金融 など"),
    ("education-loan", "教育ローン", "education-loan.html",
     "入学金・授業料など教育資金向けローンを、金利・限度額で比較できます。",
     "メガバンク・地方銀行・政府系金融機関（教育一般貸付） など"),
    ("auto-loan", "自動車ローン", "auto-loan.html",
     "新車・中古車の購入資金向けローンを、金利・限度額で比較できます。",
     "メガバンク・新興銀行・地方銀行 など"),
    ("reform-loan", "リフォームローン", "reform-loan.html",
     "住宅の増改築・リフォーム資金向けローンを、金利・限度額で比較できます。",
     "メガバンク・地方銀行 など"),
    ("real-estate-loan", "不動産担保ローン", "real-estate-loan.html",
     "不動産を担保にした多目的ローンを、金利・限度額で比較できます。",
     "メガバンク・信託銀行・新興銀行・地方銀行 など"),
    ("mortgage", "住宅ローン", "mortgage.html",
     "住宅の購入・借換え資金向けローンを、金利・限度額で比較できます。",
     "メガバンク・信託銀行・新興銀行・地方銀行 など"),
    ("investment-property-loan", "投資不動産ローン", "investment-property-loan.html",
     "収益物件（投資用不動産）の購入資金向けローンを、金利・限度額で比較できます。",
     "メガバンク・信託銀行・新興銀行・地方銀行 など"),
    ("securities-loan", "証券担保ローン", "securities-loan.html",
     "保有する株式・投資信託等を担保にしたローンを、金利・限度額で比較できます。",
     "メガバンク・信託銀行・新興銀行 など"),
    ("purpose-loan", "目的型ローン", "purpose-loan.html",
     "冠婚葬祭・医療費など使いみちが決まったローンを、金利・限度額で比較できます。",
     "メガバンク・地方銀行 など"),
    ("government", "政府系補助金・融資", "government.html",
     "中小企業庁・都道府県が実施する制度融資・補助金・共済をまとめて掲載しています（利率のない補助金・共済も含みます）。",
     "中小企業庁・都道府県・日本政策金融公庫 など"),
    ("other-loan", "その他ローン", "other-loan.html",
     "上記のいずれにも当てはまらない融資商品を掲載しています。",
     "各金融機関"),
]


def nav_html(current_slug: str) -> str:
    links = []
    for slug, label, filename, _, _ in CATEGORIES:
        cls = ' class="active"' if slug == current_slug else ""
        links.append(f'<a href="{filename}"{cls}>{label}</a>')
    return "\n    ".join(links)


def rate_options() -> str:
    opts = ['<option value="all">指定しない</option>']
    for v, label in [(1, "年1%以下"), (3, "年3%以下"), (5, "年5%以下"), (8, "年8%以下"), (12, "年12%以下"), (18, "年18%以下")]:
        opts.append(f'<option value="{v}">{label}</option>')
    return "\n          ".join(opts)


def limit_options() -> str:
    opts = ['<option value="all">指定しない</option>']
    for yen, label in [
        (1_000_000, "100万円以上"),
        (3_000_000, "300万円以上"),
        (5_000_000, "500万円以上"),
        (10_000_000, "1,000万円以上"),
        (50_000_000, "5,000万円以上"),
        (100_000_000, "1億円以上"),
    ]:
        opts.append(f'<option value="{yen}">{label}</option>')
    return "\n          ".join(opts)


def jsonld(slug: str, label: str, filename: str, description: str) -> str:
    url = SITE_BASE_URL + "loans/" + filename
    return f"""<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@graph": [
    {{
      "@type": "WebPage",
      "@id": "{url}#webpage",
      "url": "{url}",
      "name": "{label} 比較 ｜ 融資・ローン比較台帳",
      "description": "{description}",
      "inLanguage": "ja",
      "isPartOf": {{"@id": "{SITE_BASE_URL}loans/index.html#website"}}
    }},
    {{
      "@type": "BreadcrumbList",
      "itemListElement": [
        {{"@type": "ListItem", "position": 1, "name": "補助金台帳", "item": "{SITE_BASE_URL}"}},
        {{"@type": "ListItem", "position": 2, "name": "融資・ローン比較", "item": "{SITE_BASE_URL}loans/index.html"}},
        {{"@type": "ListItem", "position": 3, "name": "{label}", "item": "{url}"}}
      ]
    }}
  ]
}}
</script>"""


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{label} 比較 ｜ 融資・ローン比較台帳</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
<meta name="robots" content="index,follow">

<meta property="og:type" content="website">
<meta property="og:site_name" content="融資・ローン比較台帳">
<meta property="og:title" content="{label} 比較 ｜ 融資・ローン比較台帳">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{canonical}">
<meta property="og:locale" content="ja_JP">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{label} 比較 ｜ 融資・ローン比較台帳">
<meta name="twitter:description" content="{description}">

{jsonld_block}

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@400;500;600;700;800&family=Zen+Kaku+Gothic+New:wght@400;500;700;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="loans.css">
</head>
<body>

<div class="topbar">
  <div class="topbar-inner">
    <a href="../index.html" class="brand"><span class="mark">印</span>補助金台帳</a>
    <nav class="topnav">
      <a href="../index.html">一覧（台帳）</a>
      <a href="../search.html">条件で探す</a>
      <a href="index.html" class="active">融資・ローン比較</a>
    </nav>
  </div>
</div>

<div class="page-head">
  <div class="eyebrow">LOAN COMPARISON LEDGER</div>
  <h1>{label}を比較する</h1>
  <p>{description} 金融機関のページに遷移しなくても、金利・限度額・特徴をこの一覧だけで比較できます。下限金利が低い順に並んでいます。</p>
</div>

<nav class="category-nav">
    {nav}
</nav>

<div class="filterbar">
  <div class="filterbar-inner">
    <div class="filter-group" style="flex:1; min-width:260px;">
      <span class="filter-group-label">金融機関分類で絞り込む</span>
      <div class="filter-chips" id="inst-cat-chips"></div>
    </div>
    <div class="filter-group">
      <span class="filter-group-label">金利で絞り込む</span>
      <select id="f-rate">
          {rate_options}
      </select>
    </div>
    <div class="filter-group">
      <span class="filter-group-label">融資希望額で絞り込む</span>
      <select id="f-limit">
          {limit_options}
      </select>
    </div>
    <button class="reset-btn" id="reset-btn" type="button">条件をリセット</button>
  </div>
</div>

<div class="layout">
  <div class="results-bar">
    <div><strong id="result-num">0</strong> 件の商品が見つかりました</div>
    <span>金利（下限）が低い順に表示 ｜ 出典：各金融機関公式サイト・中小企業庁・都道府県公式サイト</span>
  </div>
  <div id="result-list"></div>
</div>

<div class="disclaimer">
  <div class="disclaimer-box">
    <strong>このページについて：</strong>掲載している金利・限度額は各金融機関の公式サイト等で確認した情報をもとにしていますが、実際に適用される金利・限度額は審査結果により異なります。お申込み前には必ず各金融機関の公式サイトで最新の条件をご確認ください。本ページは非公式の比較情報サイトであり、特定の金融機関を推奨するものではありません。
  </div>
</div>

<footer>融資・ローン比較台帳 PROTOTYPE — 補助金台帳と同一プロジェクトの拡張として、Claudeとの協働で作成</footer>

<script>const PAGE_CATEGORY = '{slug}';</script>
<script src="loan-data.js"></script>
<script src="app.js"></script>

</body>
</html>
"""


def run():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for slug, label, filename, description, _ in CATEGORIES:
        html = PAGE_TEMPLATE.format(
            slug=slug,
            label=label,
            description=description,
            canonical=SITE_BASE_URL + "loans/" + filename,
            jsonld_block=jsonld(slug, label, filename, description),
            nav=nav_html(slug),
            rate_options=rate_options(),
            limit_options=limit_options(),
        )
        path = OUTPUT_DIR / filename
        path.write_text(html, encoding="utf-8")
        print(f"生成: {path}")


if __name__ == "__main__":
    run()
