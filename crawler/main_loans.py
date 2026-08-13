"""
融資比較サイト（民間金融機関＋政府系）のデータをまとめて更新する
エントリーポイント。

    python -m crawler.main_loans

を実行すると、
  1. data/subsidies.json（crawler.main の実行結果 = 政府系補助金・融資・
     共済）を LoanProduct 形式に変換し、loan_category="government"
     （政府系補助金・融資）として取り込む
     （※ crawler.main 側で既に安全なマージ・フォールバックが行われた
       "確定版" のデータなので、ここでは単純に全件を新しい値で
       上書きしてよい）
  2. 民間金融機関の融資商品を取得する（fetch_private_loans）
     （※ fetch_private_loans.py 側で「確認済みの値は自動抽出で
       上書きしない」というガードが既にかかっているので、ここでも
       単純に全件を新しい値で上書きしてよい）
  3. 取得元（政府系 / 民間）ごとに、丸ごと失敗した場合だけ
     data/loans.json の前回値を保持する（＝1回の取得失敗でサイトの
     表示が空になる事故を防ぐ）
  4. data/loans.json に書き戻す

GitHub Actions からは、crawler.main の後にこのスクリプトを呼び出す。
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler.fetch_private_loans import fetch_private_loan_products
from crawler.loan_schema import LoanProduct

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SUBSIDIES_PATH = DATA_DIR / "subsidies.json"
LOANS_PATH = DATA_DIR / "loans.json"

# 「年1.8%〜2.2%」「年1.1〜1.5%」「年2.15%以内〜2.85%以内」のような、
# 2つの数値が「〜」で直接つながった範囲表記だけを拾う。1つ目の数値には
# %が付いていないこともあるため任意にしているが、2つ目には必ず%を要求する
# （そうしないと「3年〜10年」のような期間表記まで拾ってしまうため）。
RATE_RANGE_RE = re.compile(
    r"(?<!\d)(\d{1,2}(?:\.\d{1,2})?)\s*[%％]?(?:以内|以下)?\s*[~〜～]\s*"
    r"(\d{1,2}(?:\.\d{1,2})?)\s*[%％](?:以内|以下)?"
)
YEN_RE = re.compile(r"([0-9０-９,，]+)\s*(億円|万円)")


def parse_rate_range(label: str):
    """
    「年1.8%〜2.2%」のような、はっきりした範囲表記だけを (下限, 上限) と
    して取り出す。読み取れなければ (None, None)。

    あえて「単一の数値だけを利率とみなす」フォールバックは実装していない。
    実データで検証したところ、"保証料率はおおむね1％以内"（保証料率を
    利率と誤認）、"経営力向上割引で年0.5%引下げ"（割引幅を利率と誤認）
    のように、範囲を伴わない単発の数値は利率そのものではないケースが
    多く、機械的に「これが利率だ」と決め打ちすると総合台帳の比較結果を
    誤らせてしまうため。範囲として読み取れない場合は None のままにし、
    政府系補助金・融資カテゴリのページでは rateLabel の原文をそのまま
    表示する（総合台帳の利率ソートには乗らない）。

    範囲表記であっても、"保証料率 主に0.45〜1.90%" のように「保証料」の
    直後に出てくる範囲は、融資利率ではなく信用保証協会の保証料率で
    あることが実データで確認できたため、その場合も None にする。
    """
    label = label or ""
    if "要確認" in label:
        return None, None
    m = RATE_RANGE_RE.search(label)
    if not m:
        return None, None
    preceding = label[max(0, m.start() - 15):m.start()]
    if "保証料" in preceding:
        return None, None
    lo, hi = float(m.group(1)), float(m.group(2))
    return min(lo, hi), max(lo, hi)


def parse_yen_amount(label: str) -> Optional[int]:
    """「上限200万円」「2億円」等から、最も大きい金額(円)を取り出す。"""
    best = None
    for m in YEN_RE.finditer(label or ""):
        num = float(m.group(1).replace(",", "").replace("，", ""))
        unit = m.group(2)
        yen = int(num * (100_000_000 if unit == "億円" else 10_000))
        if best is None or yen > best:
            best = yen
    return best


def _pref_name(program: dict) -> str:
    m = re.search(r"（(.+?)）", program.get("scopeLabel", ""))
    return m.group(1) if m else program.get("scopeLabel", "都道府県")


def _institution_for(program: dict) -> str:
    category = program["category"]
    scope = program["scope"]
    pref = program["pref"]
    if category == "共済":
        if pref == "all":
            return "中小企業基盤整備機構"
        return f"{_pref_name(program)}（勤労者福祉共済）"
    if scope == "prefecture":
        return _pref_name(program)
    if scope == "regional":
        return "中小企業庁（能登地域特別枠）"
    return "中小企業庁"


def convert_government_programs(programs: list) -> List[dict]:
    """
    data/subsidies.json の1件（補助金台帳の Program）を LoanProduct に
    変換する。補助金・共済は「利率」という概念を持たないため、
    category が融資のものだけ rate_min/rate_max を実際に読み取り、
    それ以外は None のまま（総合台帳の利率ソートには乗らないが、
    政府系補助金・融資カテゴリのページには rateLabel の原文で表示される）。
    """
    products = []
    for p in programs:
        rate_min = rate_max = None
        if p["category"] == "融資":
            rate_min, rate_max = parse_rate_range(p["rateLabel"])

        confirmed = "要確認" not in p["amountLabel"] and "要確認" not in p["rateLabel"]

        product = LoanProduct(
            institution=_institution_for(p),
            institution_category="政府・地方公共団体",
            loan_category="government",
            product_name=p["title"],
            rate_min=rate_min,
            rate_max=rate_max,
            rate_label=p["rateLabel"],
            limit_label=p["amountLabel"],
            limit_max_yen=parse_yen_amount(p["amountLabel"]),
            features=p["eligibility"][:3],
            url=p["url"],
            source_checked_at=p["sourceCheckedAt"],
            confirmed=confirmed,
        )
        products.append(product.to_dict())
    return products


def load_existing() -> list:
    if LOANS_PATH.exists():
        with open(LOANS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []


def _key(item: dict):
    return (item["institution"], item["loanCategory"], item["productName"])


def run():
    print(f"[{datetime.now().isoformat()}] 融資比較データの更新を開始")

    existing = load_existing()
    fresh_items: List[dict] = []

    try:
        with open(SUBSIDIES_PATH, encoding="utf-8") as f:
            programs = json.load(f)
        gov_products = convert_government_programs(programs)
        fresh_items += gov_products
        print(f"  政府系補助金・融資・共済: {len(gov_products)} 件")
    except Exception as e:
        # 丸ごと失敗した場合のみ、前回のgovernmentカテゴリ分を残す
        print(f"  [警告] 政府系データの変換に失敗: {e}。前回値を保持します。")
        fresh_items += [item for item in existing if item["loanCategory"] == "government"]

    try:
        private_products = [p.to_dict() for p in fetch_private_loan_products()]
        fresh_items += private_products
        print(f"  民間金融機関の融資商品: {len(private_products)} 件")
    except Exception as e:
        print(f"  [警告] 民間金融機関の取得に失敗: {e}。前回値を保持します。")
        fresh_items += [item for item in existing if item["loanCategory"] != "government"]

    merged_by_key = {_key(item): item for item in fresh_items}
    merged = list(merged_by_key.values())

    LOANS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOANS_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"[{datetime.now().isoformat()}] 完了。合計 {len(merged)} 件を保存しました。")


if __name__ == "__main__":
    run()
