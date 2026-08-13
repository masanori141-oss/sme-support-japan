"""
民間金融機関等の融資商品（カードローン・教育ローン等）1件分のデータ構造。

補助金台帳（schema.py の Program）とは別に定義している。融資商品は
「下限利率〜上限利率」「上限融資額」で横断比較・絞り込みをする、という
補助金とは異なる使われ方をするため、専用の形を持たせている。

政府系の補助金・融資・共済（Program）も、この LoanProduct 形式に変換して
loan_category="government"（政府系補助金・融資）として統合する
（crawler/main_loans.py の convert_government_programs を参照）。
"""

from dataclasses import asdict, dataclass, field
from typing import List, Optional

# 融資分類（英語スラッグ: 表示ラベル）。URL・ファイル名にもこのスラッグを使う。
LOAN_CATEGORIES = {
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

# 金融機関分類。政府系補助金・融資カテゴリの中でのみ使う特殊値も含む。
INSTITUTION_CATEGORIES = [
    "メガバンク",
    "信託銀行",
    "新興銀行",
    "政府系金融機関",
    "地方銀行",
    "消費者金融",
    "政府・地方公共団体",  # 中小企業庁・都道府県（政府系補助金・融資カテゴリ専用）
]


@dataclass
class LoanProduct:
    institution: str                   # 金融機関名（例: "三菱UFJ銀行"）
    institution_category: str          # INSTITUTION_CATEGORIES のいずれか
    loan_category: str                 # LOAN_CATEGORIES のキー（英語スラッグ）
    product_name: str                  # 商品名（例: "バンクイック"）
    rate_min: Optional[float] = None   # 下限金利(%)。読み取れない場合は None
    rate_max: Optional[float] = None   # 上限金利(%)。読み取れない場合は None
    rate_label: str = "要確認（公式サイトで最終確認）"  # 表示用の金利文言
    limit_label: str = "要確認（公式サイトで最終確認）"  # 表示用の上限額文言
    limit_max_yen: Optional[int] = None  # 上限額(円)。ソート・絞り込み用。不明なら None
    features: List[str] = field(default_factory=list)  # 特徴（3項目程度の短文）
    url: str = ""
    source_checked_at: str = ""
    confirmed: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        return {
            "institution": d["institution"],
            "institutionCategory": d["institution_category"],
            "loanCategory": d["loan_category"],
            "productName": d["product_name"],
            "rateMin": d["rate_min"],
            "rateMax": d["rate_max"],
            "rateLabel": d["rate_label"],
            "limitLabel": d["limit_label"],
            "limitMaxYen": d["limit_max_yen"],
            "features": d["features"],
            "url": d["url"],
            "sourceCheckedAt": d["source_checked_at"],
        }
