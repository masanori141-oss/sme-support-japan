"""
都道府県ごとの制度融資・独自補助金を取得する。

47都道府県は、それぞれ公式サイトの構造が違う（今回のResearchでも
そうだった）。そのため「1本のコードで全部読める」ようにはできず、
県ごとに「どのURLを見るか」「どうやって数値を読み取るか」を
少しずつ登録していく形にしている。

【使い方】
1. PREF_CONFIG に、対応したい県の設定を追加する
2. まずは url だけ登録しておけば、クローラーは「このURLを見て」と
   記録するところまではやってくれる（詳細の自動抽出は県ごとに実装）
3. 自動抽出が難しい県は、amount_label 等を手入力のまま固定しておき、
   「confirmed: False」のフラグだけ立てておく運用でもよい
   （＝完全自動でなくてもよい。まずは仕組みを回すことを優先する）
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from .schema import Program

PREFECTURES_JA = {
    "hokkaido": "北海道", "aomori": "青森県", "iwate": "岩手県", "miyagi": "宮城県",
    "akita": "秋田県", "yamagata": "山形県", "fukushima": "福島県", "ibaraki": "茨城県",
    "tochigi": "栃木県", "gunma": "群馬県", "saitama": "埼玉県", "chiba": "千葉県",
    "tokyo": "東京都", "kanagawa": "神奈川県", "niigata": "新潟県", "toyama": "富山県",
    "ishikawa": "石川県", "fukui": "福井県", "yamanashi": "山梨県", "nagano": "長野県",
    "gifu": "岐阜県", "shizuoka": "静岡県", "aichi": "愛知県", "mie": "三重県",
    "shiga": "滋賀県", "kyoto": "京都府", "osaka": "大阪府", "hyogo": "兵庫県",
    "nara": "奈良県", "wakayama": "和歌山県", "tottori": "鳥取県", "shimane": "島根県",
    "okayama": "岡山県", "hiroshima": "広島県", "yamaguchi": "山口県", "tokushima": "徳島県",
    "kagawa": "香川県", "ehime": "愛媛県", "kochi": "高知県", "fukuoka": "福岡県",
    "saga": "佐賀県", "nagasaki": "長崎県", "kumamoto": "熊本県", "oita": "大分県",
    "miyazaki": "宮崎県", "kagoshima": "鹿児島県", "okinawa": "沖縄県",
}


@dataclass
class PrefLoanConfig:
    """1都道府県・1制度融資ぶんの設定。まずはURLと既知の数値を登録するだけでよい。"""
    pref: str                      # 例: "osaka"
    program_name: str              # 制度融資の正式名称
    url: str                       # 公式ページのURL
    amount_label: str = "要確認（公式サイトで最終確認）"
    rate_label: str = "要確認（公式サイトで最終確認）"
    confirmed: bool = False        # True なら「確定値」として扱う


# 今回のResearchで判明した47都道府県分の制度融資を、そのまま設定として登録。
# ここに無い県・新しい制度が出てきた場合は、この辞書に1行追加するだけでよい。
PREF_LOAN_CONFIG: List[PrefLoanConfig] = [
    PrefLoanConfig("hokkaido", "北海道中小企業総合振興資金",
                    "https://www.pref.hokkaido.lg.jp/kz/csk/kny/yuushi/"),
    PrefLoanConfig("saitama", "埼玉県中小企業制度融資（経営安定資金）",
                    "https://www.pref.saitama.lg.jp/a0805/seidoyushi/",
                    rate_label="年1.8%〜2.2%（上限利率、利子補給後・固定）", confirmed=True),
    PrefLoanConfig("kanagawa", "神奈川県中小企業制度融資（事業振興融資）",
                    "https://www.pref.kanagawa.jp/docs/m6c/cnt/f5782/",
                    amount_label="2億円", confirmed=True),
    PrefLoanConfig("osaka", "大阪府制度融資",
                    "https://www.pref.osaka.lg.jp/o110080/kinyushien/seido001/index.html"),
    # ... 残り43都道府県も同じ形式で追加していく。
    # search.html の DATA に既に入っている47件分の値を、
    # そのまま初期値としてこのリストに移すのが最短ルート。
]


def build_programs_from_config() -> List[Program]:
    """設定済みの都道府県融資情報を Program 形式に変換する。"""
    today = datetime.now().strftime("%Y-%m-%d")
    programs = []
    for cfg in PREF_LOAN_CONFIG:
        pref_ja = PREFECTURES_JA[cfg.pref]
        programs.append(
            Program(
                title=cfg.program_name,
                category="融資",
                kicker=f"制度融資 ｜ {pref_ja}内の中小企業向け",
                scale=["小規模5", "小規模20", "中小企業100", "中小企業300"],
                purpose=["設備投資"],
                scope="prefecture",
                scope_label=f"都道府県独自（{pref_ja}）",
                pref=cfg.pref,
                amount_label=cfg.amount_label,
                rate_label=cfg.rate_label,
                deadline="2099-01-01",
                deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
                eligibility=[
                    f"{pref_ja}内で事業を営む中小企業者",
                    "県・金融機関・信用保証協会の三者協調融資",
                    "資金使途:運転資金・設備資金",
                ],
                url=cfg.url,
                source_checked_at=today,
            )
        )
    return programs


def fetch_prefecture_programs() -> List[Program]:
    """
    将来的には、ここで各県ページに実際にアクセスして
    最新の利率・限度額を自動取得する処理を足していく。
    現時点では PREF_LOAN_CONFIG の設定値をそのまま使う「半自動」の状態。
    """
    return build_programs_from_config()


if __name__ == "__main__":
    for p in fetch_prefecture_programs():
        mark = "確定" if any(c.confirmed for c in PREF_LOAN_CONFIG if c.pref == p.pref) else "要確認"
        print(f"[{mark}] {p.title}")
