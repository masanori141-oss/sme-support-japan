"""
民間金融機関等（メガバンク・信託銀行・新興銀行・政府系金融機関・地方銀行・
消費者金融）の融資商品を取得する。

【設計方針】
都道府県の制度融資（fetch_prefectures.py）と同じ考え方を踏襲している。
金融機関ごとにサイト構造がまったく違い、しかも銀行・消費者金融のサイトは
Bot対策（古いTLS設定、JavaScriptレンダリング、Akamai等の防御）で
自動取得できないことが実際に多い（例: みずほ銀行は自動アクセスを403で
拒否、プロミス・千葉銀行の商品ページはJSレンダリングで本文が取得できない
等、実装時に確認済み）。

そのため「個別サイト専用パーサー」ではなく、LOAN_CONFIG に金融機関ごとの
初期値（Researchで確認した金利・上限額）を登録しておき、実行時に実際の
URLへアクセスして汎用キーワードで自動更新を試みる、失敗したら初期値に
フォールバックする、という半自動の構成にしている。

【新しい金融機関・商品を追加する場合】
LOAN_CONFIG に LoanConfig を1件追加するだけでよい。まずは url と
product_name だけ登録し、rate_label 等は「要確認」のままにしておいても
仕組みは正しく動く（confirmed=False の「要確認」枠として扱われる）。
"""

import re
import ssl
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

from .loan_schema import LoanProduct

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
REQUEST_TIMEOUT = 20


@dataclass
class LoanConfig:
    """1金融機関・1商品ぶんの設定。url と初期値（フォールバック値）を持つ。"""
    institution: str
    institution_category: str
    loan_category: str             # loan_schema.LOAN_CATEGORIES のキー
    product_name: str
    url: str
    rate_min: Optional[float] = None
    rate_max: Optional[float] = None
    rate_label: str = "要確認（公式サイトで最終確認）"
    limit_label: str = "要確認（公式サイトで最終確認）"
    limit_max_yen: Optional[int] = None
    features: List[str] = field(default_factory=list)
    confirmed: bool = False


# 代表的な金融機関・カードローンをResearchで確認した初期値として登録。
# 他の融資分類・金融機関は今後この一覧に追記していく
# （まずは枠組みを構築し、代表データで動作確認するという方針のため、
#  現時点ではカードローンを中心に少数の金融機関のみ登録している）。
LOAN_CONFIG: List[LoanConfig] = [
    LoanConfig(
        institution="三菱UFJ銀行", institution_category="メガバンク",
        loan_category="card-loan", product_name="バンクイック",
        url="https://www.bk.mufg.jp/kariru/banquic/index.html",
        rate_min=1.4, rate_max=14.6, rate_label="年1.4%〜14.6%（変動）",
        limit_label="10万円〜800万円", limit_max_yen=8_000_000,
        features=["三菱UFJ銀行ATM・提携コンビニATM手数料がほぼ24時間無料", "WEB完結で申込可能", "最低返済額は毎月1,000円から"],
        confirmed=True,
    ),
    LoanConfig(
        institution="みずほ銀行", institution_category="メガバンク",
        loan_category="card-loan", product_name="みずほ銀行カードローン",
        url="https://www.mizuhobank.co.jp/loan_card/kinri/index.html",
        rate_min=2.0, rate_max=14.0, rate_label="年2.0%〜14.0%（変動、住宅ローン利用者は1.5%〜13.5%）",
        limit_label="10万円〜800万円（10万円単位）", limit_max_yen=8_000_000,
        features=["みずほ銀行で住宅ローン利用中なら金利が年0.5%優遇", "利用限度額に応じて金利が決定", "WEB完結で申込可能"],
        confirmed=True,
    ),
    LoanConfig(
        institution="楽天銀行", institution_category="新興銀行",
        loan_category="card-loan", product_name="楽天銀行スーパーローン",
        url="https://www.rakuten-bank.co.jp/loan/cardloan/",
        rate_min=1.9, rate_max=14.5, rate_label="年1.9%〜14.5%（変動）",
        limit_label="10万円〜800万円", limit_max_yen=8_000_000,
        features=["楽天銀行口座があれば即時キャッシング可能", "月々2,000円から返済可能", "楽天会員ランクに応じて審査優遇"],
        confirmed=True,
    ),
    LoanConfig(
        institution="住信SBIネット銀行（ドコモSMTBネット銀行）", institution_category="新興銀行",
        loan_category="card-loan", product_name="Mr.カードローン",
        url="https://www.netbk.co.jp/contents/lineup/card-loan/",
        rate_min=2.04, rate_max=14.94, rate_label="年2.04%〜14.94%（変動、コースにより異なる）",
        limit_label="コースにより300万円〜1,000万円", limit_max_yen=10_000_000,
        features=["SBI証券口座保有登録で金利年0.5%優遇", "プレミアムコースは銀行カードローン最高クラスの限度額", "2025年に住信SBIネット銀行からドコモSMTBネット銀行へ名称変更"],
        confirmed=True,
    ),
    LoanConfig(
        institution="千葉銀行", institution_category="地方銀行",
        loan_category="card-loan", product_name="ちばぎんカードローン（クイックパワー＜アドバンス＞）",
        url="https://www.chibabank.co.jp/kojin/services/loan/cardloan/cardloan_new",
        rate_min=1.7, rate_max=14.8, rate_label="年1.7%〜14.8%（変動）",
        limit_label="10万円〜800万円", limit_max_yen=8_000_000,
        features=["千葉銀行本支店・提携ATMで借入・返済可能", "ちばぎんアプリで残高確認・返済ができる", "限度額100万円未満は上限金利14.8%が適用されやすい"],
        confirmed=True,
    ),
    LoanConfig(
        institution="横浜銀行", institution_category="地方銀行",
        loan_category="card-loan", product_name="横浜銀行カードローン",
        url="https://www.boy.co.jp/kojin/card-loan/yokohama/index.html",
        rate_min=1.5, rate_max=14.6, rate_label="年1.5%〜14.6%（変動）",
        limit_label="10万円〜1,000万円（10万円単位）", limit_max_yen=10_000_000,
        features=["限度額100万円超で金利が年11.8%以下に低下", "24時間WEB受付、最短当日利用も可能", "銀行カードローンの中でも上限額が高め"],
        confirmed=True,
    ),
    LoanConfig(
        institution="アコム", institution_category="消費者金融",
        loan_category="card-loan", product_name="アコムカードローン",
        url="https://www.acom.co.jp/lineup/cardloan/",
        rate_min=2.4, rate_max=17.9, rate_label="実質年率2.4%〜17.9%",
        limit_label="1万円〜800万円", limit_max_yen=8_000_000,
        features=["初めての利用は30日間金利0円サービス対象", "最短20分審査・即日融資も可能", "契約極度額100万円超で金利が下がりやすい"],
        confirmed=True,
    ),
    LoanConfig(
        institution="プロミス", institution_category="消費者金融",
        loan_category="card-loan", product_name="プロミス フリーキャッシング",
        url="https://cyber.promise.co.jp/",
        rate_min=4.5, rate_max=17.8, rate_label="実質年率4.5%〜17.8%",
        limit_label="1万円〜500万円", limit_max_yen=5_000_000,
        features=["初回利用から30日間無利息", "WEB完結・最短即日融資に対応", "三井住友銀行グループのSMBCコンシューマーファイナンスが運営"],
        confirmed=True,
    ),
    LoanConfig(
        institution="りそな銀行", institution_category="メガバンク",
        loan_category="card-loan", product_name="りそなプレミアムカードローン",
        url="https://www.resonabank.co.jp/kojin/cardloan/cardloan.html",
        rate_min=1.45, rate_max=13.9, rate_label="年1.45%〜13.9%（変動、住宅ローン利用者は上限13.5%）",
        limit_label="10万円〜800万円", limit_max_yen=8_000_000,
        features=["りそな銀行・埼玉りそな銀行で住宅ローン利用中なら金利年0.5%優遇", "限度額が大きいほど金利が低くなる", "WEB完結で申込可能"],
        confirmed=True,
    ),
    LoanConfig(
        institution="ソニー銀行", institution_category="新興銀行",
        loan_category="card-loan", product_name="ソニー銀行カードローン",
        url="https://sonybank.jp/rate/cl.html",
        rate_min=2.5, rate_max=13.8, rate_label="年2.5%〜13.8%（変動）",
        limit_label="10万円〜800万円", limit_max_yen=8_000_000,
        features=["申込・借入・返済がPC/スマホで完結", "月々2,000円から返済可能", "金利は原則毎月1日に見直し"],
        confirmed=True,
    ),
    LoanConfig(
        institution="イオン銀行", institution_category="新興銀行",
        loan_category="card-loan", product_name="イオン銀行カードローン",
        url="https://www.aeonbank.co.jp/interest/card-loan/",
        rate_min=3.8, rate_max=13.8, rate_label="年3.8%〜13.8%（変動、住宅ローン利用者は上限13.5%）",
        limit_label="10万円〜800万円", limit_max_yen=8_000_000,
        features=["イオン銀行で住宅ローン利用中なら金利年0.5%優遇", "口座があれば新規申込時に振込融資も利用可", "審査完了後、最短5日程度でカード到着"],
        confirmed=True,
    ),
    LoanConfig(
        institution="セブン銀行", institution_category="新興銀行",
        loan_category="card-loan", product_name="セブン銀行カードローン",
        url="https://www.sevenbank.co.jp/personal/netbank/deposit_loan/loan/beginner.html",
        rate_min=12.0, rate_max=15.0, rate_label="年12.0%〜15.0%（限度額10万円/30万円は15.0%、50万円は12.0%）",
        limit_label="10万円・30万円・50万円の3種類", limit_max_yen=500_000,
        features=["キャッシュカード・デビットカード・カードローンが1枚に集約", "全国のセブン銀行ATMで借入・返済とも手数料0円", "限度額は3種類から審査で決定"],
        confirmed=True,
    ),
    LoanConfig(
        institution="PayPay銀行", institution_category="新興銀行",
        loan_category="card-loan", product_name="PayPay銀行カードローン",
        url="https://www.paypay-bank.co.jp/cardloan/index.html",
        rate_min=1.59, rate_max=18.0, rate_label="年1.59%〜18.0%（13段階の変動金利）",
        limit_label="最大1,000万円", limit_max_yen=10_000_000,
        features=["初回借入日から30日間利息0円", "利用にはPayPay銀行の普通預金口座が必要", "最高限度額1,000万円枠は年1.59%と業界最低水準"],
        confirmed=True,
    ),
    LoanConfig(
        institution="アイフル", institution_category="消費者金融",
        loan_category="card-loan", product_name="アイフルカードローン",
        url="https://www.aiful.co.jp/starter/cardloan/",
        rate_min=3.0, rate_max=18.0, rate_label="実質年率3.0%〜18.0%",
        limit_label="1万円〜800万円（1,000円単位）", limit_max_yen=8_000_000,
        features=["はじめての契約は最大30日間利息0円", "限度額50万円超・他社含め借入100万円超は収入証明書が必要", "WEB完結・最短即日融資に対応"],
        confirmed=True,
    ),
    LoanConfig(
        institution="レイク", institution_category="消費者金融",
        loan_category="card-loan", product_name="レイク",
        url="https://lakealsa.com/cashing/interest/",
        rate_min=4.5, rate_max=18.0, rate_label="実質年率4.5%〜18.0%",
        limit_label="1万円〜500万円", limit_max_yen=5_000_000,
        features=["Web申込の初回契約者は最大365日間無利息", "満20歳以上70歳以下、パート・アルバイトも申込可", "最短即日融資に対応"],
        confirmed=True,
    ),
    LoanConfig(
        institution="SMBCモビット", institution_category="消費者金融",
        loan_category="card-loan", product_name="SMBCモビット カードローン",
        url="https://www.mobit.ne.jp/index.html",
        rate_min=3.0, rate_max=18.0, rate_label="実質年率3.0%〜18.0%",
        limit_label="最大800万円", limit_max_yen=8_000_000,
        features=["WEB完結申込なら電話・郵送物なしで契約可能", "全国約12万台の提携ATMで借入・返済可能", "スマホATM取引にも対応"],
        confirmed=True,
    ),
    LoanConfig(
        institution="京葉銀行", institution_category="地方銀行",
        loan_category="card-loan", product_name="京葉銀行カードローン",
        url="https://www.keiyobank.co.jp/individual/loan/card/card_loan/",
        rate_min=4.5, rate_max=13.0, rate_label="年4.5%〜13.0%（住宅ローン利用者・給与振込利用者は0.5%優遇）",
        limit_label="30万円〜300万円", limit_max_yen=3_000_000,
        features=["住宅ローン利用中または給与振込利用中は金利0.5%優遇", "カードローンⅡ型（住宅ローン利用者向け）は年4.5%", "WEBで申込可能"],
        confirmed=True,
    ),
    LoanConfig(
        institution="福岡銀行", institution_category="地方銀行",
        loan_category="card-loan", product_name="福岡銀行カードローン",
        url="https://www.fukuokabank.co.jp/personal/service/mokuteki/cardloan/",
        rate_min=3.0, rate_max=14.5, rate_label="実質年率3.0%〜14.5%（固定）",
        limit_label="10万円〜1,000万円", limit_max_yen=10_000_000,
        features=["限度額が大きいほど金利が低い", "審査結果通知まで5〜7日程度", "初回契約時は上限金利14.5%が適用されやすい"],
        confirmed=True,
    ),
    LoanConfig(
        institution="京都銀行", institution_category="地方銀行",
        loan_category="card-loan", product_name="京都銀行カードローン＜ダイレクト＞",
        url="https://www.kyotobank.co.jp/kojin/loan/card/",
        rate_min=1.9, rate_max=14.5, rate_label="年1.9%〜14.5%（固定）",
        limit_label="10万円〜1,000万円", limit_max_yen=10_000_000,
        features=["京都・大阪・滋賀・兵庫・奈良・愛知在住/勤務の方が対象", "WEB完結、原則来店不要", "月々2,000円からの返済に対応"],
        confirmed=True,
    ),
    LoanConfig(
        institution="北海道銀行", institution_category="地方銀行",
        loan_category="card-loan", product_name="北海道銀行カードローン「ラピッド」",
        url="https://www.hokkaidobank.co.jp/loan/lineup/rapid.html",
        rate_min=1.9, rate_max=14.95, rate_label="年1.9%〜14.95%（審査により決定）",
        limit_label="1万円〜800万円", limit_max_yen=8_000_000,
        features=["北海道銀行に口座がなくても利用可能", "全国の提携コンビニATMで返済可能", "限度額400万円超は最小返済額1,000円から"],
        confirmed=True,
    ),
    LoanConfig(
        institution="常陽銀行", institution_category="地方銀行",
        loan_category="card-loan", product_name="常陽銀行カードローン「キャッシュピット」",
        url="https://www.joyobank.co.jp/personal/loan/cashpit/",
        rate_min=1.5, rate_max=14.8, rate_label="年1.5%〜14.8%",
        limit_label="上限300万円", limit_max_yen=3_000_000,
        features=["常陽銀行ATM・提携コンビニATMとも手数料0円", "入会金・年会費0円", "パート・アルバイトの方も申込可能"],
        confirmed=True,
    ),
    LoanConfig(
        institution="東邦銀行", institution_category="地方銀行",
        loan_category="card-loan", product_name="東邦銀行カードローン「TOHOスマートネクスト」",
        url="https://www.tohobank.co.jp/kinri/loan.html",
        rate_min=1.4, rate_max=14.6, rate_label="年1.4%〜14.6%（固定、極度額により12段階）",
        limit_label="10万円〜800万円", limit_max_yen=8_000_000,
        features=["極度額は12種類（30万〜500万円等）から審査で決定", "極度額に応じて金利が適用される", "利用限度額は返済状況等により増減"],
        confirmed=True,
    ),
    LoanConfig(
        institution="滋賀銀行", institution_category="地方銀行",
        loan_category="card-loan", product_name="滋賀銀行カードローン「サットキャッシュ」",
        url="https://mcl.sbk.jp/lp/satto/",
        rate_min=4.8, rate_max=14.9, rate_label="実質年率4.8%〜14.9%",
        limit_label="上限500万円", limit_max_yen=5_000_000,
        features=["利用日数分だけ利息がかかる日割計算", "パート・アルバイトは限度額50万円まで申込可", "他社ローンの借換えにも利用可"],
        confirmed=True,
    ),
    LoanConfig(
        institution="伊予銀行", institution_category="地方銀行",
        loan_category="card-loan", product_name="伊予銀行カードローン「SAFETY」",
        url="https://www.iyobank.co.jp/kariru/safety.html",
        rate_min=1.9, rate_max=14.5, rate_label="実質年率1.9%〜14.5%",
        limit_label="上限1,000万円", limit_max_yen=10_000_000,
        features=["24時間365日アプリで申込〜借入〜返済が完結", "対応14都府県在住/勤務の方が対象", "カード到着前でも返済用口座への振込融資が可能"],
        confirmed=True,
    ),
    LoanConfig(
        institution="静岡銀行", institution_category="地方銀行",
        loan_category="card-loan", product_name="静岡銀行カードローン「セレカ」",
        url="https://www.shizuokabank.co.jp/interest/loan.html",
        rate_min=1.5, rate_max=14.5, rate_label="年1.5%〜14.5%",
        limit_label="上限1,000万円", limit_max_yen=10_000_000,
        features=["新規契約は契約から60日間無利息", "全国対応・口座開設不要で申込可能", "限度額が大きいほど金利が低い"],
        confirmed=True,
    ),
    LoanConfig(
        institution="山陰合同銀行", institution_category="地方銀行",
        loan_category="card-loan", product_name="ごうぎんカードローン「キャッシュバンクネオ」",
        url="https://www.gogin.co.jp/personal/loan/mypace/",
        rate_min=1.95, rate_max=14.5, rate_label="実質年率1.95%〜14.5%",
        limit_label="10万円〜800万円", limit_max_yen=8_000_000,
        features=["残高不足時に限度額内で自動融資", "スマホ・PCから必要書類をWEB提出可能", "コンビニATMでの繰上返済にも対応"],
        confirmed=True,
    ),
    LoanConfig(
        institution="三井住友銀行", institution_category="メガバンク",
        loan_category="card-loan", product_name="三井住友銀行カードローン",
        url="https://www.smbc.co.jp/kojin/cardloan/details/kinri/",
        rate_min=1.5, rate_max=14.5, rate_label="年1.5%〜14.5%（限度額に応じた8段階、変動）",
        limit_label="10万円〜800万円（1万円単位）", limit_max_yen=8_000_000,
        features=["住宅ローン利用中は金利0.5%優遇", "限度額700万円超〜800万円以下は年1.5%〜4.5%", "50万円超の借入は収入証明書類が必要"],
        confirmed=True,
    ),
    LoanConfig(
        institution="三井住友信託銀行", institution_category="信託銀行",
        loan_category="card-loan", product_name="ハウジングカードローン（無担保型）「暮らしの味方」",
        url="https://www.smtb.jp/personal/loan/housing-card",
        rate_min=5.05, rate_max=5.05, rate_label="変動年5.05%（短期プライムレート+年2.925%）",
        limit_label="50万円〜500万円（50万円単位から選択）", limit_max_yen=5_000_000,
        features=["三井住友信託銀行で住宅ローンを利用中の方限定のカードローン", "資金使途は自由（事業性資金は除く）", "全国の提携ATMで借入・返済可能"],
        confirmed=True,
    ),

    # --- 教育ローン ---
    LoanConfig(
        institution="日本政策金融公庫", institution_category="政府系金融機関",
        loan_category="education-loan", product_name="教育一般貸付（国の教育ローン）",
        url="https://www.jfc.go.jp/n/finance/search/ippan.html",
        rate_min=4.05, rate_max=4.05, rate_label="年4.05%（固定、2026年7月時点）",
        limit_label="上限350万円（要件により子1人450万円、海外留学450万円）", limit_max_yen=4_500_000,
        features=["世帯年収の上限あり（子の人数に応じて基準が変動）", "在学中は利息のみの返済に据置可能", "日本政策金融公庫・沖縄振興開発金融公庫が実施する公的融資"],
        confirmed=True,
    ),
    LoanConfig(
        institution="三菱UFJ銀行", institution_category="メガバンク",
        loan_category="education-loan", product_name="ネットDE教育ローン",
        url="https://www.bk.mufg.jp/kariru/kyouiku/index.html",
        rate_min=4.475, rate_max=4.475, rate_label="年4.475%（固定）",
        limit_label="上限500万円（医学部等6年制大学は上限1,000万円）", limit_max_yen=10_000_000,
        features=["WEB完結で来店不要", "医学部等6年制大学は融資期間最長16年", "入学金・授業料のほか下宿費用等にも利用可"],
        confirmed=True,
    ),
    LoanConfig(
        institution="みずほ銀行", institution_category="メガバンク",
        loan_category="education-loan", product_name="みずほ銀行教育ローン（無担保）",
        url="https://www.mizuhobank.co.jp/loan_education/detail.html",
        rate_min=3.875, rate_max=5.5, rate_label="変動年3.875%・固定年5.5%（選択制）",
        limit_label="10万円〜300万円（1万円単位）", limit_max_yen=3_000_000,
        features=["保証人不要・保証料もかからない", "みずほの証書貸付ローン利用者は金利0.1%優遇", "在学期間中・卒業後1年は元金返済据置が可能"],
        confirmed=True,
    ),
    LoanConfig(
        institution="三井住友銀行", institution_category="メガバンク",
        loan_category="education-loan", product_name="三井住友銀行教育ローン（無担保型）",
        url="https://www.smbc.co.jp/kojin/mokuteki_loan/kyouiku_m/",
        rate_min=3.625, rate_max=3.625, rate_label="年3.625%（変動）",
        limit_label="10万円〜300万円（1万円単位）", limit_max_yen=3_000_000,
        features=["最短即日融資に対応", "原則、担保・保証人とも不要（保証会社が保証）", "300万円超の借入は郵送契約"],
        confirmed=True,
    ),
    LoanConfig(
        institution="りそな銀行", institution_category="メガバンク",
        loan_category="education-loan", product_name="りそな教育ローン",
        url="https://www.resonabank.co.jp/kojin/edu/detail.html",
        rate_min=2.2, rate_max=3.2, rate_label="年2.2%〜3.2%（住宅ローン利用者は年1.55%〜）",
        limit_label="10万円〜1,000万円", limit_max_yen=10_000_000,
        features=["証書貸付タイプ・当座貸越タイプから選択可", "りそなで住宅ローン利用中なら金利優遇", "WEB申込に対応"],
        confirmed=True,
    ),

    # --- 自動車ローン ---
    LoanConfig(
        institution="三菱UFJ銀行", institution_category="メガバンク",
        loan_category="auto-loan", product_name="ネットDEマイカーローン",
        url="https://www.bk.mufg.jp/kariru/mycar/index.html",
        rate_min=2.125, rate_max=3.25, rate_label="実質年率2.125%〜3.25%",
        limit_label="50万円〜3,000万円", limit_max_yen=30_000_000,
        features=["WEB完結・来店不要、事前審査は最短即日回答", "住宅ローン利用中は金利年0.2%優遇", "新車・中古車・バイク購入や他社借換にも対応"],
        confirmed=True,
    ),
    LoanConfig(
        institution="みずほ銀行", institution_category="メガバンク",
        loan_category="auto-loan", product_name="みずほ銀行マイカーローン（多目的ローン）",
        url="https://www.mizuhobank.co.jp/loan_multi/multi_j/detail.html",
        rate_min=6.525, rate_max=8.3, rate_label="変動年6.525%・固定年8.3%（選択制）",
        limit_label="上限300万円", limit_max_yen=3_000_000,
        features=["新車購入または新車ローンの借換えが対象", "融資期間は最長7年", "固定・変動の金利タイプを選択可能"],
        confirmed=True,
    ),
    LoanConfig(
        institution="三井住友銀行", institution_category="メガバンク",
        loan_category="auto-loan", product_name="三井住友銀行マイカーローン",
        url="https://www.smbc.co.jp/kojin/mokuteki_loan/car/",
        rate_min=3.2, rate_max=3.2, rate_label="年3.2%（固定）",
        limit_label="上限300万円", limit_max_yen=3_000_000,
        features=["原則、担保・保証人とも不要（保証会社が保証）", "自動車購入資金のほか車検・修理・免許取得費用にも利用可", "融資期間1年〜10年以内"],
        confirmed=True,
    ),
    LoanConfig(
        institution="りそな銀行", institution_category="メガバンク",
        loan_category="auto-loan", product_name="りそなマイカーローン",
        url="https://www.resonabank.co.jp/kojin/mycar/",
        rate_min=1.55, rate_max=4.45, rate_label="年1.55%〜4.45%（住宅ローン利用者は年1.55%〜、EV/FCVは0.3%優遇）",
        limit_label="要確認（公式サイトで最終確認）",
        features=["EV・FCV購入は金利年0.3%優遇", "住宅ローン利用中は金利優遇", "他社自動車ローンの借換えにも対応"],
        confirmed=True,
    ),
    LoanConfig(
        institution="横浜銀行", institution_category="地方銀行",
        loan_category="auto-loan", product_name="横浜銀行マイカーローン",
        url="https://www.boy.co.jp/kojin/mycar-loan/index.html",
        rate_min=0.9, rate_max=3.3, rate_label="年0.9%〜3.3%（審査により決定）",
        limit_label="上限1,000万円（車検・修理等は500万円）", limit_max_yen=10_000_000,
        features=["神奈川県・東京都全域等が対象エリア", "WEB完結で申込〜契約が可能", "車検・修理・保険料等にも利用可"],
        confirmed=True,
    ),

    # --- リフォームローン ---
    LoanConfig(
        institution="三菱UFJ銀行", institution_category="メガバンク",
        loan_category="reform-loan", product_name="ネットDEリフォームローン",
        url="https://www.bk.mufg.jp/kariru/reform/index.html",
        rate_min=2.74, rate_max=3.625, rate_label="年2.74%〜3.625%（住宅ローン利用者・バリアフリー工事は優遇あり）",
        limit_label="50万円〜1,000万円（1万円単位）", limit_max_yen=10_000_000,
        features=["住宅ローン利用中は金利年0.5%優遇", "バリアフリー工事は金利年0.385%優遇（併用可）", "WEB完結・来店不要"],
        confirmed=True,
    ),
    LoanConfig(
        institution="三井住友銀行", institution_category="メガバンク",
        loan_category="reform-loan", product_name="フリーローン［リフォーム］",
        url="https://www.smbc.co.jp/kojin/mokuteki_loan/free_m/reform/",
        rate_min=2.375, rate_max=2.375, rate_label="年2.375%（店頭金利年6.625%から年4.25%引下げ後）",
        limit_label="10万円〜800万円（1万円単位）", limit_max_yen=8_000_000,
        features=["原則、担保・保証人とも不要（保証会社が保証）", "短期プライムレート連動で年2回金利見直し", "リフォーム内容が未確定でも申込可"],
        confirmed=True,
    ),
    LoanConfig(
        institution="りそな銀行", institution_category="メガバンク",
        loan_category="reform-loan", product_name="りそなリフォームローン",
        url="https://www.resonabank.co.jp/kojin/reform/",
        rate_min=3.175, rate_max=10.3, rate_label="年3.175%〜10.3%",
        limit_label="100万円〜1億円（大型リフォームローン含む）", limit_max_yen=100_000_000,
        features=["解体費・借換え資金・太陽光パネル設置費用にも利用可", "リフォーム内容が決まる前でも仮審査可能", "大型リフォームは上限1億円まで対応"],
        confirmed=True,
    ),
    LoanConfig(
        institution="横浜銀行", institution_category="地方銀行",
        loan_category="reform-loan", product_name="横浜銀行リフォームローン",
        url="https://www.boy.co.jp/kojin/reform-loan/index.html",
        rate_min=1.5, rate_max=14.6, rate_label="年1.5%〜14.6%（審査により決定）",
        limit_label="上限1,000万円（最長15年）", limit_max_yen=10_000_000,
        features=["リフォーム内容が決まる前でも申込可能", "担保・保証人不要", "太陽光発電・エコキュート設置費用にも利用可"],
        confirmed=True,
    ),

    # --- 住宅ローン（変動金利・最優遇後の代表値。実際の適用金利は審査結果による） ---
    LoanConfig(
        institution="三菱UFJ銀行", institution_category="メガバンク",
        loan_category="mortgage", product_name="三菱UFJ銀行住宅ローン（変動金利）",
        url="https://www.bk.mufg.jp/kariru/jutaku/index.html",
        rate_min=0.945, rate_max=0.945, rate_label="年0.945%（変動、最優遇後の目安）",
        limit_label="要確認（融資金額は物件価格・年収等により決定）",
        features=["変動金利は基準金利を年2回見直し", "5年ルール・125%ルールで返済額急増を抑制", "団体信用生命保険料は金利に含む"],
        confirmed=True,
    ),
    LoanConfig(
        institution="みずほ銀行", institution_category="メガバンク",
        loan_category="mortgage", product_name="みずほ銀行住宅ローン（変動金利）",
        url="https://www.mizuhobank.co.jp/loan_housing/housingloancost/index.html",
        rate_min=1.025, rate_max=1.025, rate_label="年1.025%（変動、2026年8月時点・最優遇後の目安）",
        limit_label="要確認（融資金額は物件価格・年収等により決定）",
        features=["変動金利は年2回見直し", "2027年1月返済分からは年1.275%への改定が予定されている", "ネット専用住宅ローンあり"],
        confirmed=True,
    ),
    LoanConfig(
        institution="三井住友銀行", institution_category="メガバンク",
        loan_category="mortgage", product_name="三井住友銀行住宅ローン（変動金利）",
        url="https://www.smbc.co.jp/kojin/jutaku_loan/kinri/",
        rate_min=1.275, rate_max=1.275, rate_label="年1.275%（変動、最優遇後の目安）",
        limit_label="要確認（融資金額は物件価格・年収等により決定）",
        features=["変動金利型のほか固定金利特約型（5年・10年）等も選択可", "WEB申込専用住宅ローンあり", "がん団信等の団体信用生命保険が充実"],
        confirmed=True,
    ),
    LoanConfig(
        institution="りそな銀行", institution_category="メガバンク",
        loan_category="mortgage", product_name="りそな住宅ローン（変動金利）",
        url="https://www.resonabank.co.jp/kojin/jutaku/",
        rate_min=0.95, rate_max=0.95, rate_label="年0.95%（変動、最優遇後の目安）",
        limit_label="要確認（融資金額は物件価格・年収等により決定）",
        features=["新規・借換えとも取扱いあり", "リフォーム資金セット型など目的別プランが豊富", "全期間固定金利プランも選択可"],
        confirmed=True,
    ),
    LoanConfig(
        institution="横浜銀行", institution_category="地方銀行",
        loan_category="mortgage", product_name="横浜銀行住宅ローン（変動金利）",
        url="https://www.boy.co.jp/kojin/jutaku-loan/shinchiku/index.html",
        rate_min=0.945, rate_max=0.945, rate_label="年0.945%（融資手数料型、2026年8月時点・変動）",
        limit_label="要確認（融資金額は物件価格・年収等により決定）",
        features=["住宅ローン基準レートを年2回（4月・10月）見直し", "融資手数料型・保証料型から選択可", "返済額は約5年間一定（5年ルール適用）"],
        confirmed=True,
    ),

    # --- 地方銀行の対象拡充（住宅ローン: 北海道銀行・福岡銀行・常陽銀行） ---
    LoanConfig(
        institution="北海道銀行", institution_category="地方銀行",
        loan_category="mortgage", product_name="道銀住宅ローン変動金利型",
        url="https://www.hokkaidobank.co.jp/kinri/new_loan.html",
        rate_min=1.825, rate_max=1.825, rate_label="年1.825%（変動、2026年8月時点・新規受付金利）",
        limit_label="要確認（融資金額は物件価格・年収等により決定）",
        features=["基準金利からの引下げ利率は年1.500%", "固定金利選択型（3〜10年）も選択可", "カーボンニュートラル住宅ローンなど目的別プランもあり"],
        confirmed=True,
    ),
    LoanConfig(
        institution="福岡銀行", institution_category="地方銀行",
        loan_category="mortgage", product_name="福岡銀行住宅ローン優遇金利（保証料一括型・変動金利）",
        url="https://www.fukuokabank.co.jp/price/loaninterest/",
        rate_min=1.525, rate_max=1.525, rate_label="年1.525%（変動、2026年8月時点・優遇金利）",
        limit_label="要確認（融資金額は物件価格・年収等により決定）",
        features=["優遇金利の適用には一定の条件あり（窓口で要確認）", "固定金利型（2〜10年、全期間固定20〜35年）も選択可", "フラット35の取扱いもあり"],
        confirmed=True,
    ),
    LoanConfig(
        institution="常陽銀行", institution_category="地方銀行",
        loan_category="mortgage", product_name="常陽銀行住宅ローン（変動金利型・全期間重視プラン）",
        url="https://www.joyobank.co.jp/personal/loan/jutaku/kinri/",
        rate_min=1.325, rate_max=1.525, rate_label="年1.325%〜1.525%（変動、店頭金利年3.125%より最大1.8%割引、2026年8月時点）",
        limit_label="要確認（融資金額は物件価格・年収等により決定）",
        features=["給与振込等の条件を満たすと全期間最大年1.8%引下げ", "3年固定特別金利プランは年0.795%〜", "固定3〜15年・全期間完全固定も選択可"],
        confirmed=True,
    ),

    # --- 新興銀行の対象拡充（住宅ローン: ネット銀行が実は主流） ---
    LoanConfig(
        institution="住信SBIネット銀行（ドコモSMTBネット銀行）", institution_category="新興銀行",
        loan_category="mortgage", product_name="住宅ローン（WEB申込コース・通期引下げプラン変動金利）",
        url="https://www.netbk.co.jp/contents/lineup/home-loan/web/kinri/",
        rate_min=1.20, rate_max=1.55, rate_label="変動年1.20%（環境配慮型住宅または物件価格80%以下）〜1.55%（80%超）、2026年8月時点",
        limit_label="要確認（融資金額は物件価格・年収等により決定）",
        features=["ネット銀行住宅ローンの代表格で借入件数が多い", "当初引下げプラン（当初期間のみ大幅引下げ）も選択可", "がん団信等の各種団信プランが充実"],
        confirmed=True,
    ),
    LoanConfig(
        institution="ソニー銀行", institution_category="新興銀行",
        loan_category="mortgage", product_name="変動セレクト住宅ローン（環境配慮型住宅）",
        url="https://sonybank.jp/products/hl/",
        rate_min=1.247, rate_max=1.247, rate_label="年1.247%（変動、環境配慮型住宅、2026年8月時点）",
        limit_label="要確認（融資金額は物件価格・年収等により決定、上限3億円）",
        features=["借入期間最長50年・融資金額最大3億円", "がん団信100は金利上乗せ年0.1%", "環境配慮型住宅以外は別途住宅ローン金利を適用"],
        confirmed=True,
    ),
    LoanConfig(
        institution="楽天銀行", institution_category="新興銀行",
        loan_category="mortgage", product_name="楽天銀行住宅ローン（金利選択型・変動金利）",
        url="https://www.rakuten-bank.co.jp/home-loan/rate/",
        rate_min=1.543, rate_max=1.543, rate_label="年1.543%（変動、2026年8月時点）",
        limit_label="要確認（融資金額は物件価格・年収等により決定）",
        features=["保証料・繰上返済手数料が無料", "楽天銀行口座を返済口座に指定するとさらに年0.3%優遇", "つなぎ融資にも対応"],
        confirmed=True,
    ),
    LoanConfig(
        institution="PayPay銀行", institution_category="新興銀行",
        loan_category="mortgage", product_name="PayPay銀行住宅ローン（全期間引下型・変動金利）",
        url="https://www.paypay-bank.co.jp/mortgage/interest/index.html",
        rate_min=1.330, rate_max=1.330, rate_label="年1.330%（変動、2026年8月時点）",
        limit_label="要確認（融資金額は物件価格・年収等により決定）",
        features=["ソフトバンクスマホユーザー等は「スマホ／ネット／でんき優遇割」でさらに金利優遇", "保証料・保証会社手数料は不要", "手続きはオンラインで完結（司法書士面談は別途）"],
        confirmed=True,
    ),
    LoanConfig(
        institution="イオン銀行", institution_category="新興銀行",
        loan_category="mortgage", product_name="イオン銀行住宅ローン（全期間優遇金利プラン・変動金利）",
        url="https://www.aeonbank.co.jp/interest/housing-loan/",
        rate_min=0.990, rate_max=1.070, rate_label="年0.990%〜1.070%（変動、イオン銀行カードローン利用で年0.05%優遇、2026年8月時点）",
        limit_label="要確認（融資金額は物件価格・年収等により決定）",
        features=["イオングループでの買い物が完済まで毎日5%OFF", "保証料・一部繰上返済手数料が無料", "8疾病保障付団信など保障が充実"],
        confirmed=True,
    ),
    LoanConfig(
        institution="SBI新生銀行（新生インベストメント&ファイナンス）", institution_category="新興銀行",
        loan_category="mortgage", product_name="パワースマート住宅ローン（変動・半年型）",
        url="https://www.sbishinseibank.co.jp/retail/housing/",
        rate_min=1.060, rate_max=1.060, rate_label="年1.060%（変動・半年型、2026年8月時点）",
        limit_label="要確認（融資金額は物件価格・年収等により決定）",
        features=["保証料・団体信用生命保険料・一部繰上返済手数料が無料", "5年ルール・125%ルールは適用されない", "全疾病保障付団信も金利上乗せなしで選択可"],
        confirmed=True,
    ),

    # --- 不動産担保ローン ---
    LoanConfig(
        institution="オリックス銀行", institution_category="新興銀行",
        loan_category="real-estate-loan", product_name="オリックス銀行 不動産担保ローン",
        url="https://www.orixbank.co.jp/personal/mortgage/",
        rate_min=2.425, rate_max=4.425, rate_label="変動金利型（短期プライムレート基準）年2.425%〜4.425%",
        limit_label="2,000万円〜2億円", limit_max_yen=200_000_000,
        features=["海外不動産・別荘・賃貸用不動産の購入資金にも利用可", "資金使途は原則自由", "投資用不動産ローン・住宅ローンは新規取扱を中止中（本商品は継続提供）"],
        confirmed=True,
    ),
    LoanConfig(
        institution="楽天銀行", institution_category="新興銀行",
        loan_category="real-estate-loan", product_name="楽天銀行 不動産担保ローン",
        url="https://www.rakuten-bank.co.jp/loan/mortgage-collateral/detail/",
        rate_min=3.02, rate_max=11.78, rate_label="年3.02%〜11.78%（2026年7月1日時点適用金利、固定金利・5年毎見直し）",
        limit_label="最大1億円未満", limit_max_yen=100_000_000,
        features=["住宅ローン返済中でも利用可能", "複数の借入のおまとめにも利用可", "資金使途は原則自由"],
        confirmed=True,
    ),
    LoanConfig(
        institution="SBI新生銀行（新生インベストメント&ファイナンス）", institution_category="新興銀行",
        loan_category="real-estate-loan", product_name="不動産担保ローン",
        url="https://www.shinsei-if.com/loan/",
        rate_min=3.2, rate_max=4.45, rate_label="変動年3.2%〜4.45%（団体信用生命保険なし、2026年4月時点）",
        limit_label="担保不動産評価額の80%以内", limit_max_yen=None,
        features=["SBI新生銀行グループの新生インベストメント&ファイナンスが提供", "融資期間は最長35年", "団信加入の有無で金利が異なる"],
        confirmed=True,
    ),

    # --- 投資不動産ローン ---
    LoanConfig(
        institution="みずほ信託銀行", institution_category="信託銀行",
        loan_category="investment-property-loan", product_name="賃貸マンション・アパートローン「プロデュース II」",
        url="https://www.mizuho-tb.co.jp/kinri/loan.html",
        rate_min=3.375, rate_max=3.375, rate_label="短期プライムレート連動型 年3.375%（団信不加入、2026年8月12日時点、最良条件）",
        limit_label="要確認（公式サイトで最終確認）",
        features=["長期プライムレート連動型・固定金利選択型など金利タイプが豊富", "団体信用生命保険の加入有無を選択可", "長期プライムレート連動型は新規取扱を停止中"],
        confirmed=True,
    ),
    LoanConfig(
        institution="三井住友信託銀行", institution_category="信託銀行",
        loan_category="investment-property-loan", product_name="アパートローン",
        url="https://www.smtb.jp/personal/loan/apartment",
        limit_label="3億円以内（100万円以上、10万円単位）", limit_max_yen=300_000_000,
        features=["賃貸マンション・アパートの建築・購入資金に利用可", "融資期間は物件の耐用年数等に応じて設定", "金利は個別審査により決定"],
        confirmed=False,
    ),
    LoanConfig(
        institution="三井住友銀行", institution_category="メガバンク",
        loan_category="investment-property-loan", product_name="アパートローン",
        url="https://www.smbc.co.jp/kojin/apartment/",
        rate_label="非公開（担保評価・借入属性等により個別に決定）",
        limit_label="200万円以上（上限は物件の建築・購入価格等による）",
        features=["団体信用生命保険は加入金額1億円が上限", "既存ローンの借換えには利用不可", "融資利率は個別審査により決定（団信加入で年0.3%上乗せ）"],
        confirmed=False,
    ),

    # --- 証券担保ローン ---
    LoanConfig(
        institution="楽天銀行", institution_category="新興銀行",
        loan_category="securities-loan", product_name="楽天銀行 証券担保ローン",
        url="https://www.rakuten-bank.co.jp/loan/securities-collateral/borrowing-ratio/",
        rate_min=2.125, rate_max=4.125, rate_label="年2.125%〜4.125%（お借入残高に応じた3段階、2026年8月時点）",
        limit_label="担保有価証券（楽天証券口座内）の評価額に応じて決定", limit_max_yen=None,
        features=["楽天証券に預けている株式・投資信託等を担保に借入可能", "残高1,000万円超は年2.125%と最も低い", "基準金利（短期プライムレート）に連動し見直しあり"],
        confirmed=True,
    ),

    # --- 目的型ローン ---
    LoanConfig(
        institution="りそな銀行", institution_category="メガバンク",
        loan_category="purpose-loan", product_name="りそなフリーローン（無担保型）",
        url="https://www.resonabank.co.jp/kojin/freeloan/",
        rate_min=1.7, rate_max=14.0, rate_label="年1.7%〜14.0%（固定、住宅ローン利用者は▲0.5%優遇）",
        limit_label="上限1,000万円（最長10年）", limit_max_yen=10_000_000,
        features=["結婚式・旅行・医療費など資金使途は原則自由", "りそなで住宅ローン利用中は金利優遇", "固定金利で返済計画が立てやすい"],
        confirmed=True,
    ),
    LoanConfig(
        institution="横浜銀行", institution_category="地方銀行",
        loan_category="purpose-loan", product_name="横浜銀行ライフサポートローン（多目的ローン）",
        url="https://www.boy.co.jp/kojin/lifesupport-loan/index.html",
        rate_min=3.85, rate_max=4.85, rate_label="年3.85%〜4.85%（審査により決定）",
        limit_label="10万円〜500万円", limit_max_yen=5_000_000,
        features=["結婚式・旅行・医療費など生活の様々なシーンで利用可", "他の目的別ローンとの合計残高1,000万円以内", "審査回答は最短即日"],
        confirmed=True,
    ),

    # --- 地方銀行の対象拡充（教育ローン・住宅ローン） ---
    LoanConfig(
        institution="千葉銀行", institution_category="地方銀行",
        loan_category="education-loan", product_name="ちばぎんスーパー教育ローン",
        url="https://www.chibabank.co.jp/kojin/loan/education/",
        rate_min=2.4, rate_max=3.25, rate_label="年2.4%〜3.25%（変動、WEB契約は年2.8%）",
        limit_label="10万円〜3,000万円", limit_max_yen=30_000_000,
        features=["保証料は千葉銀行負担", "マイナンバーカード等提示で金利優遇あり", "千葉・東京・茨城・埼玉・神奈川在住/勤務が対象"],
        confirmed=True,
    ),
    LoanConfig(
        institution="福岡銀行", institution_category="地方銀行",
        loan_category="education-loan", product_name="学資ローンDX",
        url="https://www.fukuokabank.co.jp/personal/service/mokuteki/gakushiloan/",
        rate_min=3.1, rate_max=3.7, rate_label="年3.1%〜3.7%（変動）",
        limit_label="10万円〜2,000万円", limit_max_yen=20_000_000,
        features=["借入期間は最長17年", "入学金・授業料のほか、下宿費用等にも利用可", "同行には限度額の低い「教育カードローン」も別途あり"],
        confirmed=True,
    ),
    LoanConfig(
        institution="常陽銀行", institution_category="地方銀行",
        loan_category="education-loan", product_name="常陽教育ローン（学援生活）",
        url="https://www.joyobank.co.jp/personal/loan/education/lp/",
        rate_min=2.6, rate_max=3.2, rate_label="年2.6%〜3.2%（変動）",
        limit_label="10万円〜3,000万円", limit_max_yen=30_000_000,
        features=["入学金・授業料のほか仕送り・生活費・家賃にも利用可", "担保・保証人不要", "全国対応・来店不要でスマホ/PCから申込可"],
        confirmed=True,
    ),
    LoanConfig(
        institution="千葉銀行", institution_category="地方銀行",
        loan_category="mortgage", product_name="ちばぎん住宅ローン「ベストチョイス21」（変動金利）",
        url="https://www.chibabank.co.jp/kojin/loan/housing/plan/select/plan02.html",
        rate_min=1.225, rate_max=1.225, rate_label="年1.225%（変動、2026年8月時点・店頭金利年3.125%より1.9%割引後）",
        limit_label="要確認（融資金額は物件価格・年収等により決定）",
        features=["店頭表示金利からの割引幅を公式サイトで明示（透明性が高い）", "変動・固定とも同じ仕組みで金利を割引", "借入後は年2回金利を見直し"],
        confirmed=True,
    ),
    LoanConfig(
        institution="静岡銀行", institution_category="地方銀行",
        loan_category="mortgage", product_name="静岡銀行住宅ローン（変動金利）",
        url="https://www.shizuokabank.co.jp/personal/loan/jyutaku/index.html",
        rate_min=1.15, rate_max=1.15, rate_label="年1.15%（変動、2026年8月時点・最優遇後の目安）",
        limit_label="要確認（融資金額は物件価格・年収等により決定）",
        features=["au回線等とのセット利用でさらに最大年0.15%優遇", "新規契約は契約から一定期間無利息の特典がある商品も併設", "静岡県内を中心に幅広いエリアで取扱い"],
        confirmed=True,
    ),

    # --- 新興銀行の対象拡充（カードローン・投資不動産ローン） ---
    LoanConfig(
        institution="東京スター銀行", institution_category="新興銀行",
        loan_category="card-loan", product_name="スターカードローンα",
        url="https://www.tokyostarbank.co.jp/products/loan/cardloan/",
        rate_min=1.5, rate_max=14.6, rate_label="年1.5%〜14.6%",
        limit_label="最大1,000万円（10万円単位）", limit_max_yen=10_000_000,
        features=["契約日から30日間利息0円", "来店不要・インターネットで完結", "口座なしタイプも選択可（返済は普段使いの口座でOK）"],
        confirmed=True,
    ),
    LoanConfig(
        institution="みんなの銀行", institution_category="新興銀行",
        loan_category="card-loan", product_name="みんなの銀行カードローン",
        url="https://www.minna-no-ginko.com/service/loan/column/cardloan/",
        rate_min=1.5, rate_max=14.5, rate_label="年1.5%〜14.5%",
        limit_label="10万円〜1,000万円（10万円単位）", limit_max_yen=10_000_000,
        features=["審査はアプリ完結、勤務先への在籍確認なし", "1次審査は最短2分で結果表示", "借入・返済ともアプリ内で操作"],
        confirmed=True,
    ),
    LoanConfig(
        institution="大和ネクスト銀行", institution_category="新興銀行",
        loan_category="investment-property-loan", product_name="不動産投資ローン",
        url="https://www.bank-daiwa.co.jp/saving/loan/investment_loan/",
        rate_label="非公開（変動型、個別審査により決定）",
        limit_label="最大30億円（大和証券の不動産仲介物件が対象）", limit_max_yen=3_000_000_000,
        features=["大和証券の紹介を受けた「ダイワ・コンサルティングコース」の富裕層向け", "対象は東京・大阪・名古屋等の賃貸需要が見込まれるエリア", "他行からの借換え・建築資金は対象外"],
        confirmed=False,
    ),

    # --- 地方銀行の対象拡充（教育ローン・自動車ローン） ---
    LoanConfig(
        institution="横浜銀行", institution_category="地方銀行",
        loan_category="education-loan", product_name="横浜銀行教育ローン",
        url="https://www.boy.co.jp/kojin/education-loan/index.html",
        rate_min=0.9, rate_max=3.55, rate_label="年0.9%〜3.55%",
        limit_label="10万円〜1,000万円", limit_max_yen=10_000_000,
        features=["カードローン型・一括借入型から選択可", "保証料不要、担保・保証人も不要", "WEB完結で来店不要"],
        confirmed=True,
    ),
    LoanConfig(
        institution="千葉銀行", institution_category="地方銀行",
        loan_category="auto-loan", product_name="ちばぎんマイカーローン",
        url="https://www.chibabank.co.jp/kojin/services/loan/mycar/kinri_mycar",
        rate_min=2.1, rate_max=3.4, rate_label="年2.1%〜3.4%（変動、保証料は千葉銀行負担）",
        limit_label="最大3,000万円", limit_max_yen=30_000_000,
        features=["WEB完結・アプリ口座登録・200万円以上の借入で金利優遇", "新車・中古車のほか維持費・借換えにも利用可", "千葉・東京・茨城・埼玉・神奈川在住/勤務が対象"],
        confirmed=True,
    ),
    LoanConfig(
        institution="京葉銀行", institution_category="地方銀行",
        loan_category="auto-loan", product_name="京葉銀行マイカーローン",
        url="https://www.keiyobank.co.jp/individual/loan/my_car/",
        rate_min=1.4, rate_max=4.2, rate_label="年1.4%〜4.2%（変動、Web完結でさらに金利優遇）",
        limit_label="最大1,000万円", limit_max_yen=10_000_000,
        features=["車検・修理費用・水上バイク購入等にも利用可", "Web申込で来店不要の完結契約が可能", "営業用車両は対象外"],
        confirmed=True,
    ),
    LoanConfig(
        institution="福岡銀行", institution_category="地方銀行",
        loan_category="auto-loan", product_name="ニューオートローンDX",
        url="https://www.fukuokabank.co.jp/personal/service/mokuteki/autoloan/",
        rate_min=2.15, rate_max=3.95, rate_label="年2.15%〜3.95%（固定）",
        limit_label="10万円〜1,500万円", limit_max_yen=15_000_000,
        features=["固定金利型（ニューオートローンDX）と変動金利型（らくらくマイカーローン）を選択可", "住宅ローン利用中はさらに金利優遇", "1万円単位で融資額を調整可能"],
        confirmed=True,
    ),

    # --- 地方銀行の対象拡充（リフォームローン） ---
    LoanConfig(
        institution="千葉銀行", institution_category="地方銀行",
        loan_category="reform-loan", product_name="ちばぎん住まいのリフォームローン",
        url="https://www.chibabank.co.jp/kojin/loan/reform/",
        rate_min=2.9, rate_max=3.3, rate_label="年2.9%〜3.3%（通常金利。WEB契約・住宅ローン利用者は優遇あり）",
        limit_label="最大1,500万円", limit_max_yen=15_000_000,
        features=["保証人・担保とも不要", "千葉銀行で住宅ローン利用中はさらに金利優遇", "千葉・東京・茨城・埼玉・神奈川在住/勤務が対象"],
        confirmed=True,
    ),
    LoanConfig(
        institution="京葉銀行", institution_category="地方銀行",
        loan_category="reform-loan", product_name="京葉銀行リフォームローン",
        url="https://www.keiyobank.co.jp/individual/loan/reform/",
        rate_min=1.9, rate_max=4.9, rate_label="年1.9%〜4.9%（固定）",
        limit_label="最大2,000万円", limit_max_yen=20_000_000,
        features=["空き家取壊し資金など使いみちの幅が広い", "住宅ローン・給与振込利用者向けの金利優遇プランもあり", "大規模改修にも対応"],
        confirmed=True,
    ),

    # --- 不動産担保ローン・目的型ローンの対象拡充 ---
    LoanConfig(
        institution="りそな銀行", institution_category="メガバンク",
        loan_category="real-estate-loan", product_name="りそなフリーローン（有担保型）",
        url="https://www.resonabank.co.jp/kojin/freeloan/secured/",
        rate_min=3.175, rate_max=10.3, rate_label="年3.175%〜10.3%（変動）",
        limit_label="100万円〜1億円（最長30年）", limit_max_yen=100_000_000,
        features=["団体信用生命保険は金利上乗せなしで無料付帯", "無担保型より高額・長期の返済計画が可能", "土地・居宅等の購入資金や借換えにも利用可"],
        confirmed=True,
    ),
    LoanConfig(
        institution="福岡銀行", institution_category="地方銀行",
        loan_category="purpose-loan", product_name="ふくぎんフリーローン（ナイスカバー）",
        url="https://www.fukuokabank.co.jp/personal/service/mokuteki/freeloan/",
        rate_min=5.2, rate_max=14.0, rate_label="年5.2%〜14.0%（変動・固定選択制、事業資金以外は使途自由）",
        limit_label="10万円〜500万円", limit_max_yen=5_000_000,
        features=["他社ローンのおまとめにも利用可", "家具・家電・レジャー資金など使いみち自由（事業資金は除く）", "Web申込は店頭申込より金利優遇"],
        confirmed=True,
    ),

    # --- 地方銀行の対象拡充（京都銀行・北海道銀行・東邦銀行: 教育ローン・自動車ローン・リフォームローン） ---
    LoanConfig(
        institution="京都銀行", institution_category="地方銀行",
        loan_category="education-loan", product_name="京銀教育ローン",
        url="https://www.kyotobank.co.jp/kojin/loan/kyouiku/",
        rate_min=2.425, rate_max=4.325, rate_label="年2.425%〜4.325%（変動、子育て応援金利プラン等の引下げ後、2026年4月時点）",
        limit_label="最大1,000万円", limit_max_yen=10_000_000,
        features=["固定金利も選択可", "入学前・納付済でも申込可能", "最長5年間は利息のみの返済に据置可能"],
        confirmed=True,
    ),
    LoanConfig(
        institution="京都銀行", institution_category="地方銀行",
        loan_category="auto-loan", product_name="京銀マイカーローン（自動車ローン）",
        url="https://www.kyotobank.co.jp/kojin/loan/car/",
        rate_min=1.825, rate_max=3.025, rate_label="年1.825%〜3.025%（変動、借入金額に応じた引下げ後、2026年4月時点）",
        limit_label="最大1,000万円", limit_max_yen=10_000_000,
        features=["新車・中古車とも同一金利", "固定金利も選択可", "借入金額が大きいほど金利が低い"],
        confirmed=True,
    ),
    LoanConfig(
        institution="京都銀行", institution_category="地方銀行",
        loan_category="reform-loan", product_name="京銀住宅リフォームローン",
        url="https://www.kyotobank.co.jp/kojin/loan/reform/",
        rate_min=2.325, rate_max=3.325, rate_label="年2.325%〜3.325%（変動、2026年4月時点）",
        limit_label="最大1,500万円（最長20年）", limit_max_yen=15_000_000,
        features=["エコ金利プラン・京町家金利プランで追加引下げあり", "借入金額100万円以上でさらに金利優遇", "担保・保証人とも不要"],
        confirmed=True,
    ),
    LoanConfig(
        institution="北海道銀行", institution_category="地方銀行",
        loan_category="education-loan", product_name="道銀教育ローン（証書貸付型）",
        url="https://www.hokkaidobank.co.jp/loan/kyoiku/",
        rate_min=2.825, rate_max=4.125, rate_label="変動年2.825%〜4.125%（保証会社・団信付帯の有無による）",
        limit_label="10万円〜1,000万円", limit_max_yen=10_000_000,
        features=["カード型（在学中利息のみ）も選択可", "50万円までは使途確認資料が不要", "団体信用生命保険の付帯も可能"],
        confirmed=True,
    ),
    LoanConfig(
        institution="北海道銀行", institution_category="地方銀行",
        loan_category="auto-loan", product_name="道銀マイカーローン",
        url="https://www.hokkaidobank.co.jp/loan/mycar/",
        rate_min=3.075, rate_max=4.375, rate_label="変動年3.075%〜4.375%（WEB申込による金利引下げ後）",
        limit_label="10万円〜1,000万円", limit_max_yen=10_000_000,
        features=["WEB申込で店頭申込より金利優遇", "車検・修理・カー用品購入等にも利用可", "取扱手数料・保証料とも無料"],
        confirmed=True,
    ),
    LoanConfig(
        institution="北海道銀行", institution_category="地方銀行",
        loan_category="reform-loan", product_name="道銀リフォームローン",
        url="https://www.hokkaidobank.co.jp/loan/reform/",
        rate_min=3.075, rate_max=4.375, rate_label="変動年3.075%〜4.375%（WEB申込による金利引下げ後、エコ関連リフォームはさらに優遇）",
        limit_label="10万円〜1,000万円", limit_max_yen=10_000_000,
        features=["エコ関連リフォームはさらに金利優遇", "担保不要", "他社リフォームローンの借換えにも利用可"],
        confirmed=True,
    ),
    LoanConfig(
        institution="東邦銀行", institution_category="地方銀行",
        loan_category="auto-loan", product_name="東邦・オートローン",
        url="https://www.tohobank.co.jp/kojin/loan/auto/",
        rate_min=2.6, rate_max=3.2, rate_label="変動年2.6%〜3.2%（東邦信用保証付、給与振込・住宅ローン利用者は優遇）",
        limit_label="10万円〜1,500万円", limit_max_yen=15_000_000,
        features=["東邦銀行に住宅ローン利用中なら金利年2.6%", "給与振込指定で金利年2.8%", "保証料込みの表示金利"],
        confirmed=True,
    ),
    LoanConfig(
        institution="東邦銀行", institution_category="地方銀行",
        loan_category="education-loan", product_name="東邦教育ローン（一括借入方式）",
        url="https://www.tohobank.co.jp/kojin/loan/education/",
        rate_min=2.6, rate_max=3.2, rate_label="変動年2.6%〜3.2%（東邦信用保証付、給与振込・住宅ローン利用者は優遇）",
        limit_label="要確認（公式サイトで最終確認）",
        features=["カードローン方式（在学中据置）も選択可", "東邦銀行に住宅ローン利用中なら金利年2.6%", "保証料込みの表示金利"],
        confirmed=True,
    ),

    # --- 地方銀行の対象拡充（滋賀銀行・山陰合同銀行・伊予銀行: 教育ローン・自動車ローン） ---
    LoanConfig(
        institution="滋賀銀行", institution_category="地方銀行",
        loan_category="education-loan", product_name="しがぎん教育ローン（ジャストサポート・目的型）",
        url="https://www.shigagin.com/personal/loan/purpose/justsupport/education.html",
        rate_min=3.525, rate_max=5.825, rate_label="固定年3.525%〜5.825%（店頭表示金利、審査により3水準のいずれかを適用、条件により最大0.45%引下げ）",
        limit_label="10万円〜1,000万円（超える場合は不動産担保型）", limit_max_yen=10_000_000,
        features=["進学先が決まる前でも仮審査可能（結果は3ヵ月有効）", "スマホ契約なら印紙代0円", "1,000万円超は不動産担保型ジャストサポートを利用"],
        confirmed=True,
    ),
    LoanConfig(
        institution="山陰合同銀行", institution_category="地方銀行",
        loan_category="education-loan", product_name="教育ローン「がくえん」（カード型、島根県・鳥取県）",
        url="https://www.gogin.co.jp/personal/loan/education/",
        rate_min=2.4, rate_max=4.9, rate_label="変動年2.40%〜4.90%（取引状況に応じ最大年2.5%引下げ）",
        limit_label="極度額100万円〜1,000万円", limit_max_yen=10_000_000,
        features=["カード型で必要な時にすぐ引出し可能", "在学中は利息のみの返済でOK", "給与振込利用者は基準金利から年1.0%引下げ"],
        confirmed=True,
    ),
    LoanConfig(
        institution="山陰合同銀行", institution_category="地方銀行",
        loan_category="auto-loan", product_name="ごうぎんマイカーローン",
        url="https://www.gogin.co.jp/personal/loan/mycar/",
        rate_min=2.05, rate_max=4.55, rate_label="変動年2.05%〜4.55%（取引状況に応じ最大年2.5%引下げ）",
        limit_label="最高1,000万円", limit_max_yen=10_000_000,
        features=["自動車購入資金の30%まで（最高30万円）用途自由分を上乗せ可", "車検・修理・ドレスアップ費用にも利用可", "他社からの借換えにも対応"],
        confirmed=True,
    ),
    LoanConfig(
        institution="伊予銀行", institution_category="地方銀行",
        loan_category="education-loan", product_name="いよぎん教育ローン",
        url="https://www.iyobank.co.jp/kariru/education/index.html",
        rate_min=2.8, rate_max=5.25, rate_label="固定年2.80%〜5.25%（取引状況に応じ最大年0.5%引下げ、引下げ後年2.3%〜）",
        limit_label="10万円〜1,000万円", limit_max_yen=10_000_000,
        features=["進学先が未定でも仮審査可能", "在学中は据置期間の設定が可能（最長据置5〜7年）", "団信加入時は金利に年0.2%上乗せ"],
        confirmed=True,
    ),
    LoanConfig(
        institution="伊予銀行", institution_category="地方銀行",
        loan_category="auto-loan", product_name="いよぎんマイカーローン",
        url="https://www.iyobank.co.jp/kariru/mycar-loan/",
        rate_min=2.35, rate_max=4.5, rate_label="変動年2.35%〜4.50%（取引状況に応じ最大年0.4%引下げ、引下げ後年1.95%〜）",
        limit_label="10万円〜1,000万円", limit_max_yen=10_000_000,
        features=["お車決定前でも仮審査可能", "担保・保証人は原則不要", "他社からの借換えにも対応"],
        confirmed=True,
    ),

    # --- 地方銀行の対象拡充（京葉銀行・常陽銀行・静岡銀行: 教育ローン・自動車ローンの残り） ---
    LoanConfig(
        institution="京葉銀行", institution_category="地方銀行",
        loan_category="education-loan", product_name="京葉銀行 教育ローン・学資ローン",
        url="https://www.keiyobank.co.jp/individual/loan/education/",
        rate_min=3.1, rate_max=3.6, rate_label="変動年3.1%〜3.6%（住宅ローン利用・給与振込利用者は年3.1%）",
        limit_label="最大1,000万円", limit_max_yen=10_000_000,
        features=["カードローン型・一括借入型から選択可", "年収確認資料は原則不要（借入300万円まで）", "団体信用生命保険付き（保険料は銀行負担）"],
        confirmed=True,
    ),
    LoanConfig(
        institution="常陽銀行", institution_category="地方銀行",
        loan_category="auto-loan", product_name="常陽マイカーローン",
        url="https://www.joyobank.co.jp/personal/loan/mycar/",
        rate_min=1.45, rate_max=3.45, rate_label="変動年1.45%〜3.45%（WEB契約、店頭金利年5.875%より引下げ）",
        limit_label="10万円〜1,000万円", limit_max_yen=10_000_000,
        features=["PC・スマホでのWEB契約なら大幅金利優遇", "口座がなくても仮審査可能", "繰上返済は何度でも手数料無料"],
        confirmed=True,
    ),
    LoanConfig(
        institution="静岡銀行", institution_category="地方銀行",
        loan_category="education-loan", product_name="静岡銀行教育ローン",
        url="https://www.shizuokabank.co.jp/personal/loan/education/index.html",
        rate_min=3.1, rate_max=6.6, rate_label="変動年3.1%または5.1%（優遇条件を満たす場合）、通常年4.6%または6.6%",
        limit_label="10万円〜1,000万円（医・歯・薬・獣医学部進学者は最高3,000万円）", limit_max_yen=10_000_000,
        features=["カードタイプ・一括借入タイプから選択可（金利は同一）", "静岡県内の地銀・信金で教育ローンシェアNo.1", "合格前から申込可能"],
        confirmed=True,
    ),
    LoanConfig(
        institution="静岡銀行", institution_category="地方銀行",
        loan_category="auto-loan", product_name="静岡銀行マイカーローン",
        url="https://www.shizuokabank.co.jp/personal/loan/mycar/",
        rate_min=1.4, rate_max=4.4, rate_label="変動年1.4%〜4.4%（優遇後、通常金利は年3.5%〜6.2%）",
        limit_label="10万円〜1,000万円", limit_max_yen=10_000_000,
        features=["保証料無料", "融資期間最長10年", "他社ローンの借換えにも利用可"],
        confirmed=True,
    ),
    LoanConfig(
        institution="滋賀銀行", institution_category="地方銀行",
        loan_category="auto-loan", product_name="しがぎんマイカーローン（ジャストサポート・目的型）",
        url="https://www.shigagin.com/personal/loan/purpose/justsupport/",
        rate_min=3.525, rate_max=5.825, rate_label="固定年3.525%〜5.825%（店頭表示金利、審査により3水準のいずれかを適用、条件により最大0.45%引下げ）",
        limit_label="10万円〜1,000万円", limit_max_yen=10_000_000,
        features=["自動車購入・車検・免許取得費用等に利用可", "スマホ契約なら印紙代0円", "教育ローンと同一の目的型ローン商品体系"],
        confirmed=True,
    ),

    # --- 新興銀行の対象拡充（教育ローン・自動車ローン・リフォームローン） ---
    LoanConfig(
        institution="住信SBIネット銀行（ドコモSMTBネット銀行）", institution_category="新興銀行",
        loan_category="education-loan", product_name="目的ローン（教育ローン）",
        url="https://www.netbk.co.jp/contents/lineup/loan/education/kinri/",
        rate_min=2.775, rate_max=4.475, rate_label="変動年2.775%〜4.475%（住宅ローン残高・カードローン契約・SBI証券口座保有等の条件で最大年1.0%引下げ、2026年8月時点）",
        limit_label="要確認（公式サイトで最終確認）",
        features=["住宅ローン残高がある場合は基準金利より年1.0%引下げ", "SBI証券口座保有登録でも年0.5%引下げ", "当社カードローン契約済でも年0.5%引下げ"],
        confirmed=True,
    ),
    LoanConfig(
        institution="住信SBIネット銀行（ドコモSMTBネット銀行）", institution_category="新興銀行",
        loan_category="auto-loan", product_name="目的ローン（自動車ローン）",
        url="https://www.netbk.co.jp/contents/lineup/loan/car/kinri/",
        rate_min=2.775, rate_max=4.475, rate_label="変動年2.775%〜4.475%（住宅ローン残高・カードローン契約・SBI証券口座保有等の条件で最大年1.0%引下げ、2026年8月時点）",
        limit_label="要確認（公式サイトで最終確認）",
        features=["住宅ローン残高がある場合は基準金利より年1.0%引下げ", "既存の当社自動車ローンの借換えは対象外", "WEBで手続き完結"],
        confirmed=True,
    ),
    LoanConfig(
        institution="住信SBIネット銀行（ドコモSMTBネット銀行）", institution_category="新興銀行",
        loan_category="reform-loan", product_name="目的ローン（リフォームローン）",
        url="https://www.netbk.co.jp/contents/lineup/loan/reform/kinri/",
        rate_min=3.475, rate_max=4.975, rate_label="変動年3.475%〜4.975%（住宅ローン残高・カードローン契約・SBI証券口座保有等の条件で最大年1.0%引下げ、2026年8月時点）",
        limit_label="要確認（公式サイトで最終確認）",
        features=["住宅ローン残高がある場合は基準金利より年1.0%引下げ", "耐震・バリアフリー工事等にも利用可", "WEBで手続き完結"],
        confirmed=True,
    ),
    LoanConfig(
        institution="イオン銀行", institution_category="新興銀行",
        loan_category="education-loan", product_name="教育ローン",
        url="https://www.aeonbank.co.jp/loan/educational-loan/",
        rate_min=4.70, rate_max=4.70, rate_label="変動年4.70%（無担保ローン基準金利+1.5%、住宅ローン契約者専用は年2.60%、2026年8月時点）",
        limit_label="10万円〜500万円", limit_max_yen=5_000_000,
        features=["当社カードローン契約済みなら年1.0%金利優遇", "最長で卒業まで元金据置が可能", "支払済みから4カ月以内なら申込可"],
        confirmed=True,
    ),
    LoanConfig(
        institution="イオン銀行", institution_category="新興銀行",
        loan_category="auto-loan", product_name="アシストプラン（自動車ローン）",
        url="https://www.aeonbank.co.jp/loan/netfree-loan/car-loan/",
        rate_min=3.80, rate_max=13.50, rate_label="固定年3.80%〜13.50%（審査により決定、2026年1月時点）",
        limit_label="10万円〜700万円", limit_max_yen=7_000_000,
        features=["新車・中古車とも同一金利", "車検・修理・オプション品購入にも利用可", "毎月の返済額が変わらない固定金利"],
        confirmed=True,
    ),
    LoanConfig(
        institution="イオン銀行", institution_category="新興銀行",
        loan_category="reform-loan", product_name="リフォームローン",
        url="https://www.aeonbank.co.jp/loan/reform-loan/",
        rate_min=6.05, rate_max=6.05, rate_label="固定年6.05%（全期間固定、2026年8月時点）",
        limit_label="30万円〜500万円", limit_max_yen=5_000_000,
        features=["保証料はお借入利率に含まれる（別途負担なし）", "返済日は毎月10日/20日/30日から選択可", "増改築・改装・車庫設置・造園等に利用可"],
        confirmed=True,
    ),
    LoanConfig(
        institution="楽天銀行", institution_category="新興銀行",
        loan_category="education-loan", product_name="楽天銀行教育ローン（非提携型）",
        url="https://www.rakuten-bank.co.jp/loan/education/",
        rate_min=3.900, rate_max=4.448, rate_label="固定年3.900%または変動年4.448%（非提携型、提携大学は優遇金利あり）",
        limit_label="要確認（公式サイトで最終確認）",
        features=["大学・大学院専用の教育ローン", "提携大学は優遇金利が適用される", "来店不要でWEB・アプリから申込可能"],
        confirmed=True,
    ),
]


# ---------------------------------------------------------------------------
# ページ取得・汎用抽出ロジック（fetch_prefectures.py と同じ考え方）
# ---------------------------------------------------------------------------

class _LegacyTLSAdapter(HTTPAdapter):
    """
    金融機関のサイトの中には、古いサーバー設定のままでTLSのセキュリティ
    レベルが低く、Pythonのopensslデフォルト設定（SECLEVEL=2）だと
    ハンドシェイクに失敗するものがある。ブラウザは互換性のために自動で
    ここを緩めて接続できているのに対し、requests はそのまま失敗するため、
    SECLEVEL=1 まで許容するセッションを使ってアクセスする。証明書の検証
    自体は行ったままなので、「暗号スイートの許容範囲を広げる」以上の
    ことはしていない。

    東京スター銀行のように、SECLEVEL=1だけでは
    "UNSAFE_LEGACY_RENEGOTIATION_DISABLED" エラーになるサイトも
    実際に見つかったため、OP_LEGACY_SERVER_CONNECT も併せて有効にして
    いる（こちらも古いサーバーとの再ネゴシエーション方式を許容する
    だけで、証明書検証を無効化するものではない）。
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.options |= 0x4  # ssl.OP_LEGACY_SERVER_CONNECT（Python 3.12未満に無いため定数値で直接指定）
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _build_session() -> requests.Session:
    session = requests.Session()
    session.mount("https://", _LegacyTLSAdapter())
    return session


_SESSION = _build_session()

RATE_NEAR_KEYWORD_RE = re.compile(
    r"(?:実質年率|借入利率|お借入利率|金利)[^。]{0,20}?"
    r"(\d{1,2}\.\d{1,2})\s*[%％]\s*[~〜～]\s*(\d{1,2}\.\d{1,2})\s*[%％]"
)
LIMIT_NEAR_KEYWORD_RE = re.compile(
    r"(?:ご利用限度額|利用限度額|限度額|極度額)[^。]{0,20}?"
    r"(\d{1,4})\s*万円\s*[~〜～]\s*(\d{1,4})\s*万円"
)


def fetch_page_text(url: str) -> Optional[str]:
    """URLにアクセスして本文テキストを取得する。失敗時は None を返す。"""
    try:
        res = _SESSION.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()
    except requests.RequestException:
        return None
    # レスポンスヘッダーに charset が無いサイトもあるため、res.text
    # （ヘッダー基準のデコード）ではなく生バイトを渡し、BeautifulSoupに
    # <meta charset> から実際のエンコーディングを検出させる。
    soup = BeautifulSoup(res.content, "html.parser")
    return " ".join(soup.get_text(separator=" ", strip=True).split())


def try_extract_rate(text: str):
    """「実質年率」等のキーワードのすぐ近くにある X.X%〜Y.Y% だけを拾う。"""
    m = RATE_NEAR_KEYWORD_RE.search(text)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def try_extract_limit(text: str):
    """「ご利用限度額」等のキーワードのすぐ近くにある X万円〜Y万円だけを拾う。"""
    m = LIMIT_NEAR_KEYWORD_RE.search(text)
    if not m:
        return None
    return int(m.group(2)) * 10_000  # 上限側(万円)を円に変換


def _is_placeholder(label: str) -> bool:
    return "要確認" in (label or "")


def build_product(cfg: LoanConfig, page_text: Optional[str]) -> LoanProduct:
    today = datetime.now().strftime("%Y-%m-%d")

    rate_min, rate_max, rate_label = cfg.rate_min, cfg.rate_max, cfg.rate_label
    limit_label, limit_max_yen = cfg.limit_label, cfg.limit_max_yen

    # 自動抽出はあくまで「要確認」のままになっている項目を埋めるためのもの。
    # 既に人手で確認済みの値は、汎用正規表現がページ内の無関係な数字に
    # 誤ってマッチするリスクがあるため上書きしない
    # （都道府県の制度融資で実際に誤マッチが起きた教訓を踏まえている）。
    if page_text:
        if _is_placeholder(cfg.rate_label):
            auto_rate = try_extract_rate(page_text)
            if auto_rate:
                rate_min, rate_max = auto_rate
                rate_label = f"実質年率{rate_min}%〜{rate_max}%"

        if _is_placeholder(cfg.limit_label):
            auto_limit = try_extract_limit(page_text)
            if auto_limit:
                limit_max_yen = auto_limit
                limit_label = f"上限{auto_limit // 10_000:,}万円"

    return LoanProduct(
        institution=cfg.institution,
        institution_category=cfg.institution_category,
        loan_category=cfg.loan_category,
        product_name=cfg.product_name,
        rate_min=rate_min,
        rate_max=rate_max,
        rate_label=rate_label,
        limit_label=limit_label,
        limit_max_yen=limit_max_yen,
        features=cfg.features,
        url=cfg.url,
        source_checked_at=today,
        confirmed=cfg.confirmed or (rate_min is not None and not _is_placeholder(rate_label)),
    )


def fetch_private_loan_products() -> List[LoanProduct]:
    """
    LOAN_CONFIG の各URLに実際にアクセスし、取得できたページ本文から
    自動抽出を試みる。個別のURLへのアクセスに失敗しても
    （実際、みずほ銀行はBot対策で403、プロミス・千葉銀行はJS
    レンダリングで本文が取得できない、等が起こりうる）、その1件が
    config のフォールバック値になるだけで、全体の処理は止めない。
    """
    page_cache: Dict[str, Optional[str]] = {}
    products: List[LoanProduct] = []

    for cfg in LOAN_CONFIG:
        if cfg.url not in page_cache:
            page_cache[cfg.url] = fetch_page_text(cfg.url)
        products.append(build_product(cfg, page_cache[cfg.url]))

    return products


if __name__ == "__main__":
    for p in fetch_private_loan_products():
        mark = "確定" if p.confirmed else "要確認"
        print(f"[{mark}] {p.institution} {p.product_name} | {p.rate_label} | {p.limit_label}")
