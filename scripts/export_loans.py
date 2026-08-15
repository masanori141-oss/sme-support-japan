"""
data/loans.json を、docs/loans/ 配下のサイト表示用データに変換する。

    python scripts/export_loans.py

これを実行すると、以下が作られる（すべて上書き）。

    docs/loans/loan-data.js    … 各ページが読み込む `const LOAN_DATA = [...]`
    docs/loans/loan-data.json  … 同じ内容の素のJSON（LLM・外部ツール向け）

docs/loans/*.html 側は
    <script src="loan-data.js"></script>
を読み込むようになっているので、以降はこのスクリプトを実行するだけで
全ページの表示内容（件数・並び順・絞り込み対象）が最新化される。

さらにこのスクリプトは、docs/loans/*.html 各ページの
    <div id="result-list"><!--SSR_CARDS_START-->...<!--SSR_CARDS_END--></div>
の中身と
    <script type="application/ld+json" id="products-jsonld">...</script>
の中身を、そのページの表示内容（app.js の baseDataset()/sortByRate()/
renderCard() と同じロジック）で直接書き換える。

これにより、JavaScriptを実行しない検索エンジン・AIクローラーが取得する
「生のHTML」の時点で、そのページの主要な商品データがそのまま読める状態
になる（表示上は、ページ読み込み後に app.js がこの内容を同じ結果で
再描画するだけなので、絞り込み・並び替え機能への影響はない）。
"""

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "loans.json"
OUTPUT_DIR = ROOT / "docs" / "loans"

# app.js の LOAN_CATEGORY_LABELS と同じ内容（総合台帳・政府系ページの
# カテゴリバッジ表示、および構造化データの category に使う）。
LOAN_CATEGORY_LABELS = {
    "card-loan": "カードローン",
    "education-loan": "教育ローン",
    "auto-loan": "自動車ローン",
    "reform-loan": "リフォームローン",
    "real-estate-loan": "不動産担保ローン",
    "mortgage": "住宅ローン",
    "investment-property-loan": "投資不動産ローン",
    "securities-loan": "証券担保ローン",
    "purpose-loan": "目的型ローン",
    "government": "政府系補助金・融資",
    "other-loan": "その他ローン",
}

PAGE_CATEGORY_RE = re.compile(r"const PAGE_CATEGORY = '([\w-]+)';")
CANONICAL_RE = re.compile(r'<link rel="canonical" href="([^"]+)">')
SSR_CARDS_RE = re.compile(r"(<!--SSR_CARDS_START-->).*?(<!--SSR_CARDS_END-->)", re.DOTALL)
RESULT_NUM_RE = re.compile(r'(<strong id="result-num">).*?(</strong>)')
PRODUCTS_JSONLD_RE = re.compile(
    r'(<script type="application/ld\+json" id="products-jsonld">).*?(</script>)', re.DOTALL
)


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def js_num(n) -> str:
    """PythonのfloatをJSのtoString()と同じ見た目にする（14.0 -> "14"、3.625 -> "3.625"）。"""
    if n is None:
        return ""
    if float(n).is_integer():
        return str(int(n))
    return str(n)


def format_yen(yen):
    """app.js の formatYen() と同じロジック。"""
    if yen is None:
        return None
    if yen >= 100_000_000:
        oku = yen / 100_000_000
        oku_str = str(int(oku)) if float(oku).is_integer() else f"{oku:.1f}"
        return f"{oku_str}億円"
    man = round(yen / 10_000)
    return f"{man:,}万円"


def rate_text(d) -> str:
    """app.js の renderCard() 内の rateText と同じロジック。"""
    rate_min = d.get("rateMin")
    if rate_min is not None:
        rate_max = d.get("rateMax")
        if rate_min == rate_max:
            return f"年{js_num(rate_min)}%"
        return f"年{js_num(rate_min)}%〜{js_num(rate_max)}%"
    return d.get("rateLabel") or "要確認"


def limit_text(d) -> str:
    return format_yen(d.get("limitMaxYen")) or d.get("limitLabel") or "要確認"


def base_dataset(data: list, page_category: str) -> list:
    """app.js の baseDataset() と同じロジック。"""
    if page_category == "all":
        return [d for d in data if d.get("rateMin") is not None]
    return [d for d in data if d.get("loanCategory") == page_category]


def sort_by_rate(items: list) -> list:
    """app.js の sortByRate() と同じロジック（rateMin不明は末尾）。"""
    return sorted(
        items,
        key=lambda d: d["rateMin"] if d.get("rateMin") is not None else float("inf"),
    )


def render_card_html(d: dict, page_category: str) -> str:
    """app.js の renderCard() が生成するDOMと同じ構造のHTML文字列を返す。"""
    show_cat_badge = page_category in ("all", "government")
    cat_label = LOAN_CATEGORY_LABELS.get(d.get("loanCategory"), d.get("loanCategory"))
    cat_badge_html = f'<span class="cat-badge">{esc(cat_label)}</span>' if show_cat_badge else ""
    features_html = "".join(
        f'<div class="loan-feature"><span class="mark">✓</span>{esc(f)}</div>'
        for f in (d.get("features") or [])[:3]
    )
    url = esc(d.get("url") or "#")
    return (
        '<article class="loan-card">\n'
        '  <div class="loan-body">\n'
        f'    <span class="inst-badge">{esc(d.get("institutionCategory"))}</span>\n'
        f"    {cat_badge_html}\n"
        f'    <div class="loan-inst">{esc(d.get("institution"))}</div>\n'
        f'    <h2 class="loan-title">{esc(d.get("productName"))}</h2>\n'
        f'    <div class="loan-features">\n      {features_html}\n    </div>\n'
        "  </div>\n"
        '  <div class="loan-figures">\n'
        "    <div>\n"
        '      <div class="figure-label">金利（実質年率）</div>\n'
        f'      <div class="figure-value rate">{esc(rate_text(d))}</div>\n'
        "    </div>\n"
        "    <div>\n"
        '      <div class="figure-label">ご利用限度額</div>\n'
        f'      <div class="figure-value">{esc(limit_text(d))}</div>\n'
        "    </div>\n"
        f'    <a class="detail-link" href="{url}" target="_blank" rel="noopener">公式サイトで詳細を見る →</a>\n'
        "  </div>\n"
        "</article>"
    )


def render_cards_block(items: list, page_category: str) -> str:
    if not items:
        return (
            '<div class="empty-state">条件に一致する商品が見つかりませんでした。'
            "絞り込み条件を減らして再度お試しください。</div>"
        )
    return "\n".join(render_card_html(d, page_category) for d in items)


def product_jsonld(d: dict, fallback_url: str) -> dict:
    """1商品ぶんの schema.org Product/Offer 構造化データ。"""
    url = d.get("url") or fallback_url
    entry = {
        "@type": "Product",
        "name": f'{d.get("productName")}（{d.get("institution")}）',
        "category": LOAN_CATEGORY_LABELS.get(d.get("loanCategory"), d.get("loanCategory")),
        "brand": {"@type": "Organization", "name": d.get("institution")},
        "url": url,
    }
    features = d.get("features") or []
    if features:
        entry["description"] = "。".join(features)

    additional_props = []
    if d.get("rateMin") is not None:
        additional_props.append(
            {"@type": "PropertyValue", "name": "実質年率（下限）", "value": d["rateMin"], "unitText": "%"}
        )
    if d.get("rateMax") is not None:
        additional_props.append(
            {"@type": "PropertyValue", "name": "実質年率（上限）", "value": d["rateMax"], "unitText": "%"}
        )
    if d.get("limitMaxYen") is not None:
        additional_props.append(
            {"@type": "PropertyValue", "name": "ご利用限度額", "value": d["limitMaxYen"], "unitText": "円"}
        )
    if additional_props:
        entry["additionalProperty"] = additional_props

    offer = {"@type": "Offer", "url": url, "availability": "https://schema.org/InStock"}
    if d.get("rateMin") is not None:
        offer["priceSpecification"] = {
            "@type": "UnitPriceSpecification",
            "price": d["rateMin"],
            "unitText": "%",
        }
    entry["offers"] = offer
    return entry


def update_loan_pages(data: list) -> None:
    """docs/loans/*.html それぞれの SSR カード領域と Product JSON-LD を更新する。"""
    for path in sorted(OUTPUT_DIR.glob("*.html")):
        content = path.read_text(encoding="utf-8")

        m = PAGE_CATEGORY_RE.search(content)
        if not m:
            # PAGE_CATEGORY が見つからないファイル（このディレクトリに
            # 手作業で追加された想定外のHTML等）は対象外とする。
            continue
        page_category = m.group(1)

        cm = CANONICAL_RE.search(content)
        page_url = cm.group(1) if cm else ""

        items = sort_by_rate(base_dataset(data, page_category))

        cards_html = render_cards_block(items, page_category)
        content, n_cards = SSR_CARDS_RE.subn(
            lambda mo, html_=cards_html: mo.group(1) + html_ + mo.group(2), content
        )

        content, n_num = RESULT_NUM_RE.subn(
            lambda mo, count=len(items): mo.group(1) + str(count) + mo.group(2), content
        )

        jsonld_obj = {
            "@context": "https://schema.org",
            "@graph": [product_jsonld(d, page_url) for d in items],
        }
        jsonld_str = json.dumps(jsonld_obj, ensure_ascii=False, indent=2)
        new_script = (
            f'<script type="application/ld+json" id="products-jsonld">\n{jsonld_str}\n</script>'
        )
        if PRODUCTS_JSONLD_RE.search(content):
            content = PRODUCTS_JSONLD_RE.sub(lambda mo, s=new_script: s, content)
        else:
            content = content.replace("</head>", new_script + "\n</head>")

        if n_cards == 0:
            print(f"警告: {path.name} に SSR_CARDS マーカーが見つかりませんでした（未更新）。")
        if n_num == 0:
            print(f"警告: {path.name} に result-num が見つかりませんでした（未更新）。")

        path.write_text(content, encoding="utf-8")
        print(f"{path.name}: {len(items)} 件をSSR埋め込み（PAGE_CATEGORY={page_category}）")


def run():
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    js_path = OUTPUT_DIR / "loan-data.js"
    js_content = "const LOAN_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n"
    js_path.write_text(js_content, encoding="utf-8")
    print(f"{len(data)} 件を {js_path} に書き出しました。")

    json_path = OUTPUT_DIR / "loan-data.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(data)} 件を {json_path} に書き出しました。")

    update_loan_pages(data)


if __name__ == "__main__":
    run()
