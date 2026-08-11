"""
中小企業庁「補助金の公募・採択」ページから、公募中・公募予定の一覧を取得する。

【重要な注意】
このファイルは「動く出発点」として書いているが、対象サイトのHTML構造は
中小企業庁側の都合で変わることがある。実際に本番運用する際は、
このスクリプトを一度ローカルまたはGitHub Actions上で動かし、
取得結果が正しいか目視で確認してから使ってほしい。
（このサンドボックス環境はインターネットに接続できないため、
 実際のfetchはこの場では実行・検証していない）
"""

import re
from datetime import datetime
from typing import List

import requests
from bs4 import BeautifulSoup

from .schema import Program

CHUSHO_KOUBO_URL = "https://www.chusho.meti.go.jp/koukai/hojyokin/index.html"

# 中小企業庁ページに載っている「公募中・公募予定」の情報は、制度によって
# 掲載場所・書式がバラバラなため、完全自動では崩れやすい。
# そこで「制度名のキーワード → 台帳側の分類」の対応表を持たせておき、
# 新しい制度が出てきたときはここに追記していく運用にする。
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


def fetch_koubo_list() -> List[dict]:
    """
    中小企業庁の公募ページから、制度名・受付期間らしき文字列の並びを
    素朴に抜き出す。実際の本番運用では、ここをページの実際のHTML構造
    （テーブルなのか、リストなのか）に合わせて調整する必要がある。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    res = requests.get(CHUSHO_KOUBO_URL, headers=headers, timeout=30)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    results = []
    # 例: 本文中のテーブル行、または見出し+リンクの並びを想定した最小実装。
    # 実際の構造に応じて `soup.select(...)` の中身を書き換えること。
    for row in soup.select("table tr"):
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) >= 2:
            results.append({"raw_cells": cells})

    return results


def parse_deadline(text: str):
    """
    「令和8年8月25日」のような和暦・全角表記から ISO日付 (YYYY-MM-DD) を作る。
    複雑な日本語の日付表現は揺れが大きいので、正規表現で拾えなかった場合は
    None を返し、呼び出し側で「要確認」として扱う。
    """
    m = re.search(r"令和(\d+)年\s*(\d{1,2})月\s*(\d{1,2})日", text)
    if not m:
        return None
    reiwa_year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    year = 2018 + reiwa_year  # 令和1年 = 2019年
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def build_programs_from_raw(raw_rows: List[dict]) -> List[Program]:
    """
    fetch_koubo_list() の生データを Program 形式に変換する。
    ここは「サイト構造が分かった後に実装を詰める」部分。
    現時点では、後続の処理が壊れないようにするための最小限のガードのみ入れている。
    """
    programs: List[Program] = []
    today = datetime.now().strftime("%Y-%m-%d")

    for row in raw_rows:
        cells = row.get("raw_cells", [])
        if not cells:
            continue
        title = cells[0]

        hint = None
        for keyword, h in KNOWN_PROGRAM_HINTS.items():
            if keyword in title:
                hint = h
                break
        if hint is None:
            # 未知の制度名。ひとまず「要確認」枠として拾っておき、
            # 人が後で分類する運用を想定（自動で捨てない）。
            hint = {"category": "補助金", "purpose": ["設備投資"], "scale": ["小規模5", "小規模20", "中小企業100", "中小企業300"]}

        deadline_text = " ".join(cells[1:])
        deadline = parse_deadline(deadline_text) or "2099-01-01"

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
                deadline_label=deadline_text if deadline != "2099-01-01" else "受付状況は公式ページで確認",
                eligibility=["詳細は中小企業庁の公式ページでご確認ください"],
                url=CHUSHO_KOUBO_URL,
                source_checked_at=today,
            )
        )

    return programs


def fetch_national_programs() -> List[Program]:
    raw_rows = fetch_koubo_list()
    return build_programs_from_raw(raw_rows)


if __name__ == "__main__":
    for p in fetch_national_programs():
        print(p.title, "|", p.deadline_label)
