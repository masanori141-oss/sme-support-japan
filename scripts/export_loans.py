"""
data/loans.json を、docs/loans/ 配下のサイト表示用データに変換する。

    python scripts/export_loans.py

これを実行すると、以下が作られる（すべて上書き）。

    docs/loans/loan-data.js    … 各ページが読み込む `const LOAN_DATA = [...]`
    docs/loans/loan-data.json  … 同じ内容の素のJSON（LLM・外部ツール向け）

docs/loans/*.html 側は
    <script src="loan-data.js"></script>
を読み込むようになっているので、以降はこのスクリプトを実行するだけで
全ページの表示内容（件数・並び順・絞り込み対象）が最新化される。
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "loans.json"
OUTPUT_DIR = ROOT / "docs" / "loans"


def run():
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    js_path = OUTPUT_DIR / "loan-data.js"
    js_content = "const LOAN_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n"
    js_path.write_text(js_content, encoding="utf-8")
    print(f"{len(data)} 件を {js_path} に書き出しました。")

    json_path = OUTPUT_DIR / "loan-data.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(data)} 件を {json_path} に書き出しました。")


if __name__ == "__main__":
    run()
