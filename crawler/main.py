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


# 締切・URL・確認日は「動く情報」なので毎回のクローリング結果で素直に
# 更新する。それ以外（金額・対象範囲・対象者像など）は人手で確認した
# 詳細が汎用クローラーの荒い抽出結果で劣化しないよう保護する対象。
REFRESHABLE_KEYS = ("deadline", "deadlineLabel", "url", "sourceCheckedAt")


def _is_placeholder(label: str) -> bool:
    return "要確認" in (label or "")


def merge(existing: list, fresh: list) -> list:
    """
    タイトルをキーにして、新しく取れた分は基本的に上書きし、
    取れなかった分（＝サイト構造変化等で失敗）は前回値を残す。
    これにより「クローリングが1回失敗しただけでサイトの表示が空になる」
    という事故を防ぐ。

    ただし、前回値が既に amountLabel まで具体的に判明している
    （＝人手で確認済みの）カードについては、fetch_national.py のような
    汎用クローラーの荒い抽出結果で上書きしない。同じタイトルの制度でも
    自動抽出は「募集中かどうか・締切・リンク先」程度しか正確に取れない
    ことが多く、金額や対象範囲（scope）まで含めて丸ごと差し替えると、
    既に分かっている詳細情報が失われてしまうため
    （例: 能登地域限定の災害支援枠が「全国対象」に化けてしまう事故）。
    その場合は締切・URL・確認日だけを新しい値で更新する。

    さらに、その締切更新も fresh 側が具体的な締切日（deadline が
    "2099-01-01" 以外）を持っているときに限る。中小企業庁のお知らせ一覧は
    同じ制度が「公募要領を公開しました（受付開始日のみ判明）」のような
    情報量の少ないお知らせとしても載ることがあり、これをそのまま採用すると
    既に分かっていた具体的な締切日が「未定」に後退してしまうため。
    """
    by_title = {item["title"]: item for item in existing}
    for item in fresh:
        old = by_title.get(item["title"])
        if old and not _is_placeholder(old.get("amountLabel")):
            if item.get("deadline") and item["deadline"] != "2099-01-01":
                merged_item = dict(old)
                for key in REFRESHABLE_KEYS:
                    if key in item:
                        merged_item[key] = item[key]
                by_title[item["title"]] = merged_item
            # fresh 側に具体的な締切が無い場合は、既存の確認済みカードを
            # そのまま残す（何もしない）。
        else:
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
