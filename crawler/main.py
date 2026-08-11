"""
クローラー全体のエントリーポイント。

    python -m crawler.main

を実行すると、
  1. 中小企業庁の全国制度を取得
  2. 都道府県の制度融資・補助金を取得
  3. 既存の data/subsidies.json とマージ
     （新しい取得に失敗した項目は、前回値をそのまま残す＝ゼロ件になる事故を防ぐ）
  4. data/subsidies.json に書き戻す

という流れを1本で実行する。GitHub Actions からはこのスクリプトを
そのまま呼び出すだけでよい。
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# このファイルの2つ上（プロジェクトルート）を import パスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler.schema import Program
from crawler.fetch_national import fetch_national_programs
from crawler.fetch_prefectures import fetch_prefecture_programs

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "subsidies.json"


def load_existing() -> list:
    if DATA_PATH.exists():
        with open(DATA_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []


def merge(existing: list, fresh: list) -> list:
    """
    タイトルをキーにして、新しく取れた分は上書き、
    取れなかった分（＝サイト構造変化等で失敗）は前回値を残す。
    これにより「クローリングが1回失敗しただけでサイトの表示が空になる」
    という事故を防ぐ。
    """
    by_title = {item["title"]: item for item in existing}
    for item in fresh:
        by_title[item["title"]] = item
    return list(by_title.values())


def run():
    print(f"[{datetime.now().isoformat()}] クローリング開始")

    fresh_programs: list[Program] = []

    try:
        fresh_programs += fetch_national_programs()
        print(f"  全国制度: {len(fresh_programs)} 件")
    except Exception as e:
        # 1つのソースが失敗しても全体を止めない
        print(f"  [警告] 全国制度の取得に失敗: {e}")

    try:
        pref_programs = fetch_prefecture_programs()
        fresh_programs += pref_programs
        print(f"  都道府県制度: {len(pref_programs)} 件")
    except Exception as e:
        print(f"  [警告] 都道府県制度の取得に失敗: {e}")

    fresh_dicts = [p.to_dict() for p in fresh_programs]

    existing = load_existing()
    merged = merge(existing, fresh_dicts)

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"[{datetime.now().isoformat()}] 完了。合計 {len(merged)} 件を保存しました。")


if __name__ == "__main__":
    run()
