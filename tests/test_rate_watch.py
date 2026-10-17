"""rate_watch の判定ルールのテスト（公式サイトにはアクセスしない）。

  python tests/test_rate_watch.py

確認していること:
  - 目印の直後の金利だけを読む／目印が無ければ読まない
  - 値が変わっていれば上書き・同じなら上書きしない（確認日だけ更新）・読めなければ何も変えない
  - 大きな変化は1日保留し、翌日も同じ値なら確定
  - 妥当な範囲外の値は採用しない
"""
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import crawler.rate_watch as rw  # noqa: E402
from crawler.rate_watch import RateWatch, extract_rate  # noqa: E402

PAGE = "新規お借り入れの金利 ＼借入期間40年でも／ 【ずーっと一律優遇コース】適用金利 変動金利 年1.195% （店頭表示金利 年3.375%） お借り換え 【ずーっと一律優遇コース】適用金利 変動金利 年1.245%"
W = RateWatch(url="https://example.test/rate", anchors=["新規お借り入れの金利", "【ずーっと一律優遇コース】適用金利変動金利"])


@dataclass
class Cfg:
    institution: str = "テスト銀行"
    product_name: str = "テスト住宅ローン（変動）"
    rate_min: Optional[float] = 0.945
    checked_at: str = "2026-08-14"
    watch: Optional[RateWatch] = field(default_factory=lambda: W)


def run(page, cfg, today):
    return rw.run_watches([cfg], lambda url: page, today=today)[f"{cfg.institution}｜{cfg.product_name}"]


def main():
    tmp = Path(tempfile.mkdtemp())
    rw.STATE_PATH, rw.REPORT_PATH = tmp / "state.json", tmp / "report.md"

    # 目印の直後を読む（借り換えの 1.245 や店頭金利 3.375 は読まない）
    assert extract_rate(PAGE, W) == 1.195
    # 2番目の数字を読む指定
    assert extract_rate("店頭表示金利 最下限金利 変動金利 年3.575% 年1.675%", RateWatch(url="", anchors=["変動金利"], nth=1)) == 1.675
    # JSON
    assert extract_rate('[{"new1":{"floatingRate":{"apply":1.250}}}]', RateWatch(url="", json_path="0.new1.floatingRate.apply")) == 1.25
    # 目印が無ければ例外
    try:
        extract_rate("金利一覧 年1.0%", W)
        raise AssertionError("目印が無いのに読めてしまった")
    except ValueError:
        pass

    cfg = Cfg()
    # 1. 変わっていれば上書き（0.945 → 1.195）
    st = run(PAGE, cfg, "2026-10-17")
    assert st["rate"] == 1.195 and st["checkedAt"] == "2026-10-17" and st["history"][-1] == {"date": "2026-10-17", "from": 0.945, "to": 1.195}
    # 2. 同じなら上書きしない（履歴は増えず、確認日だけ進む）
    st = run(PAGE, cfg, "2026-10-18")
    assert st["rate"] == 1.195 and st["checkedAt"] == "2026-10-18" and len(st["history"]) == 1
    # 3. 読めなければ金利も確認日も変えない
    st = run("ページ構成が変わった", cfg, "2026-10-19")
    assert st["rate"] == 1.195 and st["checkedAt"] == "2026-10-18" and "lastError" in st
    assert rw.REPORT_PATH.exists()
    # 大きな変化（1.195 → 2.195）は1日目は保留、2日目も同じなら確定
    big = PAGE.replace("年1.195%", "年2.195%")
    st = run(big, cfg, "2026-10-20")
    assert st["rate"] == 1.195 and st["pending"]["rate"] == 2.195
    st = run(big, cfg, "2026-10-21")
    assert st["rate"] == 2.195 and "pending" not in st and st["checkedAt"] == "2026-10-21"
    # 妥当な範囲外（例：店頭金利の誤読で 9.9%）は採用しない
    st = run(PAGE.replace("年1.195%", "年9.9%"), cfg, "2026-10-22")
    assert st["rate"] == 2.195 and "妥当な範囲" in st["lastError"]

    # アクセス制限：金利・確認日は変えず、30日以内は Issue 用レポートを作らない
    st = run("Access Denied You don't have permission to access", cfg, "2026-10-23")
    assert st["rate"] == 2.195 and st["checkedAt"] == "2026-10-21" and "アクセス制限" in st["lastError"]
    assert not rw.REPORT_PATH.exists()
    st = run(None, cfg, "2026-11-10")  # 応答なし（タイムアウト）も同じ扱い
    assert not rw.REPORT_PATH.exists()
    # 最後に確認できた日から30日を超えたら手動確認を促すレポートを作る
    st = run(None, cfg, "2026-11-25")
    assert rw.REPORT_PATH.exists() and "手動確認" in rw.REPORT_PATH.read_text(encoding="utf-8")
    # 人が公式サイトで確認して設定を更新したら、それを最新として取り込む
    manual = Cfg(rate_min=2.3, checked_at="2026-11-26")
    st = run(None, manual, "2026-11-27")
    assert st["rate"] == 2.3 and st["checkedAt"] == "2026-11-26" and st["history"][-1]["by"] == "手動確認"
    assert not rw.REPORT_PATH.exists()

    print("OK: rate_watch の判定ルールはすべて期待どおりです")


if __name__ == "__main__":
    main()
