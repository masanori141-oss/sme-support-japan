"""
中小企業庁「補助金の公募・採択」ページから、公募中・公募予定の一覧を取得する。

【ページ構造についてのメモ】
実際にアクセスして確認したところ、このページは <dl class="p-top__news__list">
の中に <dt>公開日</dt><dd>お知らせ本文（リンク付き）</dd> が並ぶ形式になっている
（テーブル形式ではない）。お知らせ本文には「〜補助金」等の制度名が
「」で囲まれて出てくることが多く、末尾に【申請受付期間：M/D～M/D】のような
形で受付期間が書かれている。

また、このページはレスポンスヘッダーに文字コード指定 (charset) が無いため、
requests の `res.text` をそのまま使うと ISO-8859-1 として解釈されて文字化け
する。`res.content`（バイト列）を BeautifulSoup に渡し、HTML内の
<meta charset> から実際のエンコーディング（UTF-8）を検出させる必要がある。

【重要な注意】
中小企業庁側の都合でページ構造は今後も変わりうる。本番運用では、定期的に
このスクリプトの取得結果を目視確認してほしい。
"""

import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .schema import Program

CHUSHO_KOUBO_URL = "https://www.chusho.meti.go.jp/koukai/hojyokin/index.html"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# 中小企業庁ページに載っている「公募中・公募予定」の情報は、制度によって
# 書式がバラバラなため、完全自動では崩れやすい。
# そこで「制度名のキーワード → 台帳側の分類」の対応表を持たせておき、
# 新しい制度が出てきたときはここに追記していく運用にする。
# （キーワードは、抽出したタイトルではなく、お知らせ本文全体に対して
#   部分一致で検索するため、文中に制度名が含まれていれば拾える）
KNOWN_PROGRAM_HINTS = {
    "デジタル化・AI導入補助金": {
        "category": "補助金",
        "purpose": ["DX・AI"],
        "scale": ["小規模5", "小規模20", "中小企業100", "中小企業300"],
    },
    "省力化投資補助金": {
        "category": "補助金",
        "purpose": ["設備投資"],
        "scale": ["小規模5", "小規模20", "中小企業100", "中小企業300"],
    },
    "持続化補助金": {
        "category": "補助金",
        "purpose": ["販路開拓"],
        "scale": ["小規模5", "小規模20"],
    },
}

DEFAULT_HINT = {
    "category": "補助金",
    "purpose": ["設備投資"],
    "scale": ["小規模5", "小規模20", "中小企業100", "中小企業300"],
}

TITLE_QUOTE_RE = re.compile(r"「(.+?)」")
TITLE_ANCHOR_RE = re.compile(r"^(.*?)の(?:第\d+回)?公募要領を公開|^(.*?)の申請受付を")
PERIOD_BLOCK_RE = re.compile(r"申請受付期間\s*[:：]\s*(.+?)】")
DATE_TOKEN_RE = re.compile(r"(?:令和(\d+)年)?(\d{1,2})/(\d{1,2})")


def fetch_koubo_list() -> List[dict]:
    """
    中小企業庁の公募ページから、お知らせ日付・本文・リンク先の並びを抜き出す。
    ページ構造が想定と異なる場合は空リストを返す（＝呼び出し側で
    「今回は0件」として扱われ、既存データが残る。main.py 側の
    マージ処理により、これだけでサイト表示が空になることはない）。
    """
    res = requests.get(CHUSHO_KOUBO_URL, headers=REQUEST_HEADERS, timeout=30)
    res.raise_for_status()
    # レスポンスヘッダーに charset が無いため、生バイトを渡して
    # BeautifulSoup に <meta charset> からエンコーディングを検出させる。
    soup = BeautifulSoup(res.content, "html.parser")

    news_list = soup.select_one("dl.p-top__news__list")
    if news_list is None:
        return []

    results = []
    dts = news_list.find_all("dt")
    dds = news_list.find_all("dd")
    for dt, dd in zip(dts, dds):
        anchor = dd.find("a")
        href = anchor.get("href") if anchor else None
        results.append({
            "date_text": dt.get_text(strip=True),
            "body_text": dd.get_text(" ", strip=True),
            "url": urljoin(CHUSHO_KOUBO_URL, href) if href else CHUSHO_KOUBO_URL,
        })

    return results


def extract_title(body_text: str) -> str:
    """
    お知らせ本文から制度名らしき部分を取り出す。
    「」で囲まれていればその中身をそのまま使い、無ければ
    「〜の公募要領を公開しました」等の定型文の手前までを使う。
    どちらにも当てはまらない場合は、受付期間の記載（【...】）より前を使う。
    """
    m = TITLE_QUOTE_RE.search(body_text)
    if m:
        return m.group(1).strip()

    m = TITLE_ANCHOR_RE.search(body_text)
    if m:
        title = m.group(1) or m.group(2)
        if title:
            return title.strip()

    return body_text.split("【")[0].strip() or body_text.strip()


def parse_period_deadline(period_text: str, announce_year: int) -> Optional[datetime]:
    """
    「8/14～9/30」「第1次締切5/12、第2次締切6/15」のような受付期間の
    記載から、最も遅い（＝実質的な最終）締切日を推定する。

    ・和暦年（令和X年）が明記されていればその年を使い、無ければ
      お知らせの公開年（announce_year）と同じ年とみなす
    ・複数の締切日が併記されている場合は、その中で最も遅い日付を採用する
    ・見つからなければ None を返す（＝呼び出し側で「締切未定」として扱う）
    """
    best: Optional[datetime] = None
    for m in DATE_TOKEN_RE.finditer(period_text):
        reiwa, month, day = m.groups()
        year = 2018 + int(reiwa) if reiwa else announce_year
        try:
            d = datetime(year, int(month), int(day))
        except ValueError:
            continue
        if best is None or d > best:
            best = d
    return best


def build_programs_from_raw(raw_rows: List[dict]) -> List[Program]:
    """
    fetch_koubo_list() の生データを Program 形式に変換する。
    """
    programs: List[Program] = []
    today = datetime.now().strftime("%Y-%m-%d")

    for row in raw_rows:
        body_text = row.get("body_text", "")
        date_text = row.get("date_text", "")
        url = row.get("url", CHUSHO_KOUBO_URL)
        if not body_text:
            continue

        title = extract_title(body_text)

        hint = DEFAULT_HINT
        for keyword, h in KNOWN_PROGRAM_HINTS.items():
            # 未知の制度名。ひとまず「要確認」枠として拾っておき、
            # 人が後で分類する運用を想定（自動で捨てない）。
            if keyword in body_text:
                hint = h
                break

        announce_year_match = re.match(r"(\d{4})年", date_text)
        announce_year = int(announce_year_match.group(1)) if announce_year_match else datetime.now().year

        period_match = PERIOD_BLOCK_RE.search(body_text)
        period_text = period_match.group(1).strip() if period_match else ""

        deadline_dt = None
        if period_text and "随時" not in period_text and not period_text.rstrip().endswith(("〜", "～", "~")):
            deadline_dt = parse_period_deadline(period_text, announce_year)

        deadline = deadline_dt.strftime("%Y-%m-%d") if deadline_dt else "2099-01-01"
        if period_text:
            deadline_label = f"申請受付期間：{period_text}"
        else:
            deadline_label = "受付状況は公式ページで確認"

        programs.append(
            Program(
                title=title,
                category=hint["category"],
                kicker="中小企業庁の公募情報より自動取得",
                scale=hint["scale"],
                purpose=hint["purpose"],
                scope="nationwide",
                scope_label="全国対象",
                pref="all",
                amount_label="要確認（自動取得のため詳細は公式ページで確認）",
                rate_label="要確認",
                deadline=deadline,
                deadline_label=deadline_label,
                eligibility=["詳細は中小企業庁の公式ページでご確認ください"],
                url=url,
                source_checked_at=today,
            )
        )

    return programs


def fetch_national_programs() -> List[Program]:
    raw_rows = fetch_koubo_list()
    return build_programs_from_raw(raw_rows)


if __name__ == "__main__":
    for p in fetch_national_programs():
        print(p.title, "|", p.deadline_label, "|", p.url)
