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

このテンプレートには、scripts/export_loans.py が日次で書き込むための
2つの差し込み先を用意している（このスクリプト自身は中身を書かない）。
  - <div id="result-list"><!--SSR_CARDS_START-->...<!--SSR_CARDS_END--></div>
    JavaScript実行前の生HTMLの時点で商品カードが見えるように
    （検索エンジン・JSを実行しないAIクローラー向け）。
  - <script type="application/ld+json" id="products-jsonld">...</script>
    掲載商品ごとのschema.org Product/Offer構造化データ。
テンプレートの構造を変えた場合は、export_loans.py 側の正規表現が
これらのマーカー・id属性を前提にしている点に注意すること。
"""

import json
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


# 総合台帳ページ（slug == "all"）にのみ表示するFAQ。他の11ページには
# 出さない（同一内容を12ページに複製すると重複コンテンツになるため）。
LOANS_FAQ = [
    ("掲載されている金利は必ず適用されますか？",
     "いいえ。掲載している金利は各金融機関の公式サイトで確認した基準ですが、実際に適用される金利は審査結果により異なります。お申込み前には必ず各金融機関の公式サイトで最新の条件をご確認ください。"),
    ("「下限金利」が低い順に並んでいますが、下限金利だけで選んで良いですか？",
     "下限金利は、その商品で最も優遇された条件が適用された場合の金利です。実際に適用される金利は審査結果によって上限に近づく場合があるため、金利だけでなく限度額や特徴もあわせてご確認ください。"),
    ("カードローンとフリーローン・目的型ローンの違いは何ですか？",
     "カードローンは利用限度額の範囲内で繰り返し借入・返済ができる商品です。フリーローン・目的型ローンは一度にまとまった金額を借り入れる商品で、資金使途が自由なものと、教育・自動車など特定の目的に限定されるものに分かれます。"),
    ("このサイトは特定の金融機関を推奨していますか？",
     "いいえ。本サイトは非公式の比較情報サイトであり、特定の金融機関を推奨するものではありません。掲載順は下限金利が低い順の機械的な並び替えです。"),
    ("政府系の補助金・融資と、民間金融機関の融資はどう違いますか？",
     "「政府系補助金・融資」分類には、中小企業庁・都道府県が実施する制度融資や補助金・共済を掲載しています。返済不要な補助金や、公的機関が関わる分だけ低金利な融資が含まれる一方、審査や手続きに時間がかかる場合があります。"),
]


def faq_html_block(slug: str) -> str:
    if slug != "all":
        return ""
    items = "\n".join(
        f"""    <div class="faq-item">
      <div class="faq-q">Q. {q}</div>
      <div class="faq-a">{a}</div>
    </div>"""
        for q, a in LOANS_FAQ
    )
    return f"""<div class="layout" style="padding-top:0;">
  <div class="faq-block">
    <h2>よくあるご質問</h2>
{items}
  </div>
</div>

"""


def faq_jsonld_block(slug: str) -> str:
    if slug != "all":
        return ""
    entities = ",\n".join(
        f"""    {{
      "@type": "Question",
      "name": {json.dumps(q, ensure_ascii=False)},
      "acceptedAnswer": {{"@type": "Answer", "text": {json.dumps(a, ensure_ascii=False)}}}
    }}"""
        for q, a in LOANS_FAQ
    )
    return f"""<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
{entities}
  ]
}}
</script>

"""


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

<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-N2JHBP892C"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-N2JHBP892C');
</script>

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

{faq_jsonld}<script type="application/ld+json" id="products-jsonld">
{{"@context": "https://schema.org", "@graph": []}}
</script>

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@700;800&family=Zen+Kaku+Gothic+New:wght@400;500;600;700&display=swap" rel="stylesheet">
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
      <a href="../about.html">サイトについて</a>
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
  <div id="result-list"><!--SSR_CARDS_START--><!--SSR_CARDS_END--></div>
</div>

{faq_html}<div class="disclaimer">
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
            faq_jsonld=faq_jsonld_block(slug),
            faq_html=faq_html_block(slug),
            nav=nav_html(slug),
            rate_options=rate_options(),
            limit_options=limit_options(),
        )
        path = OUTPUT_DIR / filename
        path.write_text(html, encoding="utf-8")
        print(f"生成: {path}")


if __name__ == "__main__":
    run()
