"""
補助金台帳サイトが扱う1件分のデータ構造の定義。

この形は search.html の `const DATA = [...]` の中身と1対1で対応している。
クローリングで取得した情報は、最終的にすべてこの形に変換してから
data/subsidies.json に保存する。
"""

from dataclasses import dataclass, field, asdict
from typing import List


@dataclass
class Program:
    title: str                 # 制度の正式名称
    category: str              # "補助金" / "融資" / "共済"
    kicker: str                # 一覧に出す一言説明（対象・目的）
    scale: List[str]           # 事業規模タグ。例: ["小規模5","小規模20","中小企業100","中小企業300"]
    purpose: List[str]         # 目的タグ。例: ["DX・AI","設備投資","事業承継", ...]
    scope: str                 # "nationwide" / "regional" / "prefecture"
    scope_label: str           # 表示用ラベル。例: "都道府県独自（大阪府）"
    pref: str                  # 都道府県コード（小文字ローマ字）。全国対象は "all"
    amount_label: str          # 上限額・掛金など、金額に関する表示
    rate_label: str            # 補助率・利率など
    deadline: str              # ISO日付 (YYYY-MM-DD)。随時受付は "2099-01-01" を仮の遠い未来日として使う
    deadline_label: str        # 表示用の締切・受付状況の文言
    eligibility: List[str]     # 「こんな会社が対象です」のチェックリスト（3項目程度、短文）
    url: str                   # 公式ページのURL
    source_checked_at: str = ""  # このデータを確認した日付 (YYYY-MM-DD)。クローラーが自動で入れる

    def to_dict(self) -> dict:
        d = asdict(self)
        # JS側のキー名（キャメルケース）に変換
        return {
            "title": d["title"],
            "category": d["category"],
            "kicker": d["kicker"],
            "scale": d["scale"],
            "purpose": d["purpose"],
            "scope": d["scope"],
            "scopeLabel": d["scope_label"],
            "pref": d["pref"],
            "amountLabel": d["amount_label"],
            "rateLabel": d["rate_label"],
            "deadline": d["deadline"],
            "deadlineLabel": d["deadline_label"],
            "eligibility": d["eligibility"],
            "url": d["url"],
            "sourceCheckedAt": d["source_checked_at"],
        }
