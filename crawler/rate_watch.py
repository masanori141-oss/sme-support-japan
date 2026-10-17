"""
公式サイトの金利を毎日確認し、変わっていれば当サイトの金利を更新する仕組み。

【考え方】
ページ内の数字を広く拾う汎用抽出は、無関係な数字への誤マッチが起きるため使わない。
商品ごとに「金利のすぐ前に書かれている文言（目印）」を RateWatch.anchors に登録し、
最後の目印の直後（window 文字以内）にある最初の「X.XXX%」だけを読み取る。
空白・改行の違いで外れないよう、ページ本文も目印も空白を除去・全角半角を統一して照合する。

【毎日の判定】
  1. 読み取れて、値が変わっていた → 金利を上書き（確認日=今日、履歴に記録）
  2. 読み取れて、値が同じ         → 金利は上書きしない（確認日のみ今日に更新）
  3. 読み取れない                 → 金利も確認日も変えない（要対応として報告）
安全装置：
  - 目印が見つからない・順番どおりに並んでいない → 読み取れない扱い
  - 金利が妥当な範囲（min_rate〜max_rate）外 → 上書きしない
  - 前回値から max_change 以上の変化 → その日は上書きせず保留。翌日も同じ値なら確定
    （1日だけの表示崩れ・誤読で金利が大きく動くのを防ぐ）

状態（最後に確認できた金利・確認日・変更履歴）は data/rate_watch_state.json に保存する。
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "rate_watch_state.json"
REPORT_PATH = ROOT / "data" / "rate_watch_report.md"

RATE_RE = re.compile(r"(\d{1,2}\.\d{1,3})%")


@dataclass
class RateWatch:
    url: str                       # 金利が掲載されている公式ページ（商品ページと違ってよい）
    anchors: List[str] = field(default_factory=list)  # 順に探す目印。最後の目印の直後の金利を読む
    render: bool = False           # JavaScriptで金利を描画するページ（ヘッドレスブラウザで取得）
    window: int = 40               # 最後の目印から何文字以内に金利があるか
    nth: int = 0                   # 目印の後の何番目の金利を読むか（0=最初。表の列で引下げ幅などが先に来る場合に使う）
    label: str = "年{rate}%（変動金利・最優遇後の目安）"  # 表示用の文言（{rate} に金利が入る）
    min_rate: float = 0.1
    max_rate: float = 6.0
    max_change: float = 0.5        # 1日でこれ以上動いたら翌日まで保留
    json_path: str = ""            # 金利がJSONデータで公開されている場合のキー（例 "0.new1.floatingRate.apply"）。指定時は anchors 不要
    note: str = ""                 # どの数字を読んでいるかの説明（保守用）


def compact(text: str) -> str:
    """全角半角を統一し、空白・改行をすべて取り除く。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or ""))


def extract_rate(text: str, watch: RateWatch) -> float:
    """目印に続く金利を返す。見つからなければ ValueError（理由つき）。"""
    if watch.json_path:
        try:
            node = json.loads(text)
            for k in watch.json_path.split("."):
                node = node[int(k)] if isinstance(node, list) else node[k]
            return float(node)
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise ValueError(f"JSONから {watch.json_path} を読めません: {e}") from e
    body = compact(text)
    pos = 0
    for a in watch.anchors:
        i = body.find(compact(a), pos)
        if i < 0:
            raise ValueError(f"目印「{a}」が見つかりません")
        pos = i + len(compact(a))
    found = list(RATE_RE.finditer(body, pos, pos + watch.window + 12))
    if len(found) <= watch.nth:
        raise ValueError(f"目印の直後（{watch.window}文字以内）に金利が見つかりません: …{body[pos:pos + 60]}…")
    return float(found[watch.nth].group(1))


# ---------------------------------------------------------------- 取得
_render_browser = None
RENDER_TEXT_JS = """() => {
  const b = document.body.cloneNode(true);
  b.querySelectorAll('script,style,noscript,template').forEach(e => e.remove());
  b.querySelectorAll('td,th,li,p,div,dt,dd,br').forEach(e => e.append(' '));
  return b.textContent;
}"""


def fetch_rendered_text(url: str) -> Optional[str]:
    """ヘッドレスブラウザ（Playwright）で描画後の本文を取得する。未導入・失敗時は None。"""
    global _render_browser
    try:
        from playwright.sync_api import sync_playwright  # 遅延import（未導入でも静的取得は動く）
    except ImportError:
        return None
    try:
        if _render_browser is None:
            pw = sync_playwright().start()
            _render_browser = pw.chromium.launch()
        page = _render_browser.new_page(locale="ja-JP", user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"))
        try:
            page.goto(url, wait_until="networkidle", timeout=45_000)
            page.wait_for_timeout(1500)
            # タブ切替で非表示になっている金利表も読めるよう、表示状態に関係なく本文を取得する
            return page.evaluate(RENDER_TEXT_JS)
        finally:
            page.close()
    except Exception as e:  # noqa: BLE001
        print(f"    [render失敗] {url}: {e}")
        return None


# ---------------------------------------------------------------- 状態
def load_state() -> Dict[str, dict]:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state: Dict[str, dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fmt_rate(rate: float) -> str:
    """1.5 → "1.50"、1.195 → "1.195"（金融機関の表記に近い形）。"""
    s = f"{rate:.3f}"
    return s[:-1] if s.endswith("0") else s


def state_key(cfg) -> str:
    return f"{cfg.institution}｜{cfg.product_name}"


# ---------------------------------------------------------------- 実行
def run_watches(configs, fetch_static: Callable[[str], Optional[str]], today: Optional[str] = None) -> Dict[str, dict]:
    """watch が設定された商品の金利を確認し、状態を更新して返す。"""
    today = today or datetime.now().strftime("%Y-%m-%d")
    state = load_state()
    cache: Dict[tuple, Optional[str]] = {}
    report = {"changed": [], "same": [], "pending": [], "failed": [], "rejected": []}

    for cfg in configs:
        w = getattr(cfg, "watch", None)
        if not w:
            continue
        key = state_key(cfg)
        st = state.setdefault(key, {
            "rate": cfg.rate_min, "checkedAt": cfg.checked_at or None, "history": [],
        })
        st["url"] = w.url
        prev = st.get("rate")

        ck = (w.url, w.render)
        if ck not in cache:
            cache[ck] = fetch_rendered_text(w.url) if w.render else fetch_static(w.url)
        text = cache[ck]

        try:
            if text is None:
                raise ValueError("ページを取得できません（アクセス拒否・タイムアウト等）" + ("／ヘッドレスブラウザ" if w.render else ""))
            rate = extract_rate(text, w)
        except ValueError as e:
            st["lastError"], st["lastErrorAt"] = str(e), today
            report["failed"].append((key, str(e), w.url, st.get("checkedAt")))
            continue

        if not (w.min_rate <= rate <= w.max_rate):
            msg = f"読み取った値 {rate}% が妥当な範囲（{w.min_rate}〜{w.max_rate}%）外のため更新しません"
            st["lastError"], st["lastErrorAt"] = msg, today
            report["rejected"].append((key, msg, w.url))
            continue

        if prev is not None and abs(rate - prev) >= w.max_change:
            pend = st.get("pending")
            if not pend or pend.get("rate") != rate:
                st["pending"] = {"rate": rate, "since": today}
                report["pending"].append((key, prev, rate, w.url))
                continue
            # 前日以前から同じ値が続いている → 確定

        st.pop("pending", None)
        st.pop("lastError", None)
        st.pop("lastErrorAt", None)
        if prev is None or rate != prev:
            st["history"].append({"date": today, "from": prev, "to": rate})
            st["rate"], st["changedAt"] = rate, today
            report["changed"].append((key, prev, rate, w.url))
        else:
            report["same"].append(key)
        st["checkedAt"] = today

    save_state(state)
    write_report(report, today)
    print(f"  金利の自動確認: 変更 {len(report['changed'])} / 変更なし {len(report['same'])} / "
          f"保留 {len(report['pending'])} / 読み取れず {len(report['failed'])} / 範囲外 {len(report['rejected'])}")
    return state


def write_report(r: dict, today: str) -> None:
    """GitHub Actions で Issue 本文に使うレポート。要対応がなければファイルを作らない。"""
    needs_action = r["failed"] or r["rejected"] or r["pending"]
    if REPORT_PATH.exists():
        REPORT_PATH.unlink()
    if not needs_action:
        return
    lines = [f"{today} の住宅ローン金利の自動確認で、対応が必要な項目があります。", ""]
    if r["failed"]:
        lines += ["### 読み取れなかった商品（金利・確認日は前回のまま）", "",
                  "| 商品 | 理由 | 公式ページ | 最終確認日 |", "|---|---|---|---|"]
        lines += [f"| {k} | {why} | {u} | {last or '—'} |" for k, why, u, last in r["failed"]]
        lines += ["", "ページの構成が変わった場合は `crawler/fetch_private_loans.py` の該当商品の `watch`（url・anchors）を見直してください。", ""]
    if r["pending"]:
        lines += ["### 大きく変わったため保留中（翌日も同じ値なら自動で確定）", "",
                  "| 商品 | 前回 | 今回読み取った値 | 公式ページ |", "|---|---|---|---|"]
        lines += [f"| {k} | {a}% | {b}% | {u} |" for k, a, b, u in r["pending"]]
        lines += [""]
    if r["rejected"]:
        lines += ["### 妥当な範囲外のため更新しなかった商品", ""]
        lines += [f"- {k}：{why}（{u}）" for k, why, u in r["rejected"]]
        lines += [""]
    if r["changed"]:
        lines += ["### 参考：本日更新した金利", ""]
        lines += [f"- {k}：{a}% → {b}%" for k, a, b, u in r["changed"]]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
