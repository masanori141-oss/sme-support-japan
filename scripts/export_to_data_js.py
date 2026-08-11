"""
data/subsidies.json を、search.html が読み込める data.js に変換する。

    python scripts/export_to_data_js.py

これを実行すると、site/data.js が作られる（上書き）。
search.html 側は、今まで直接書いていた

    const DATA = [ ...84件... ];

の部分を削除し、代わりに

    <script src="data.js"></script>

を読み込むように1回だけ変更しておく。そうすれば、以降は
data.js を差し替えるだけでサイトの表示内容が自動的に更新される
（search.html 自体を毎回書き換える必要がなくなる）。
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "subsidies.json"
OUTPUT_PATH = ROOT / "site" / "data.js"


def run():
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    js_content = "const DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n"

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(js_content)

    print(f"{len(data)} 件を {OUTPUT_PATH} に書き出しました。")


if __name__ == "__main__":
    run()
