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
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
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
