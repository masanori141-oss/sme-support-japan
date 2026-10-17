"""
公式サイトの金利を毎日確認し、変わっていれば当サイトの金利を更新する仕組み。

【考え方】
ページ内の数字を広く拾う汎用抽出は、無関係な数字への誤マッチが起きるため使わない。
商品ごとに「金利のすぐ前に書かれている文言（目印）」を RateWatch.anchors に登録し、
最後の目印の直後（window 文字以内）にある金利だけを読み取る。
  - 1つの金利（住宅ローンの変動金利など）       … 最初の「X.XXX%」
  - 幅のある金利（カードローンの年1.5%〜14.6%など）… is_range=True で「X%〜Y%」の下限・上限
空白・改行の違いで外れないよう、ページ本文も目印も空白を除去・全角半角を統一して照合する。

【毎日の判定】
  1. 読み取れて、値が変わっていた → 金利を上書き（確認日=今日、履歴に記録）
  2. 読み取れて、値が同じ         → 金利は上書きしない（確認日のみ今日に更新）
  3. 読み取れない                 → 金利も確認日も変えない
     - ページは取れたのに目印が無い（ページ構成の変更）→ すぐに Issue で知らせる
     - 金融機関側のアクセス制限で取れない → 最後に確認できた日から30日を超えたら Issue で知らせる（手動確認）
  人が公式サイトで確認して設定の rate_min・rate_max・checked_at を更新した場合は、それを最新として取り込む。
安全装置：
  - 目印が見つからない・順番どおりに並んでいない → 読み取れない扱い
  - 金利がローンの種類ごとの妥当な範囲外（下限>上限も含む） → 上書きしない
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
from typing import Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "rate_watch_state.json"
REPORT_PATH = ROOT / "data" / "rate_watch_report.md"

RATE_RE = re.compile(r"(\d{1,2}\.\d{1,3})%")
RATE_INT_RE = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{1,3})?)%")  # 「15%」のような整数表記も読む（allow_int=True のときだけ）
# 「1.5%〜14.6%」「3.0~18.0%」「年1.5%～年14.6%」など（全角半角は compact() で統一済み）
RANGE_RE = re.compile(r"(\d{1,2}(?:\.\d{1,3})?)%?(?:~|〜|-|ー|－)年?(\d{1,2}(?:\.\d{1,3})?)%")
# 金融機関側のアクセス制限（クラウドのサーバーからの自動アクセスを拒否）を示す本文
BLOCKED_RE = re.compile(r"AccessDenied|Youdon'thavepermission|403Forbidden|RequestRejected")
STALE_DAYS = 30  # 公式サイトで確認できない状態がこの日数を超えたら Issue で知らせる

# ローンの種類ごとの「ありえる金利」の範囲。外れた値は誤読とみなして採用しない
CATEGORY_BOUNDS = {
    "mortgage": (0.1, 6.0),
    "card-loan": (0.3, 20.0),
}
DEFAULT_BOUNDS = (0.1, 20.0)

Rates = Tuple[float, float]  # (下限, 上限)。1つの金利なら同じ値


@dataclass
class RateWatch:
    url: str                       # 金利が掲載されている公式ページ（商品ページと違ってよい）
    anchors: List[str] = field(default_factory=list)  # 順に探す目印。最後の目印の直後の金利を読む
    render: bool = False           # JavaScriptで金利を描画するページ（ヘッドレスブラウザで取得）
    window: int = 40               # 最後の目印から何文字以内に金利があるか
    nth: int = 0                   # 目印の後の何番目の金利を読むか（0=最初。表の列で引下げ幅などが先に来る場合に使う）
    is_range: bool = False         # 「年X%〜Y%」の幅で読む（label では {min} {max} を使う）
    max_anchors: List[str] = field(default_factory=list)  # 上限が別の場所にある表の場合、上限の目印（anchors は下限の目印）
    max_nth: int = 0               # 上限の目印の後の何番目の金利を読むか
    allow_int: bool = False        # 「15%」のような小数点のない金利も読む（「80%以内」等の誤読を避けるため既定は小数のみ）
    label: str = "年{rate}%（変動金利・最優遇後の目安）"  # 表示用の文言（{rate}/{min}/{max} に金利が入る）
    min_rate: Optional[float] = None  # 妥当な範囲（未指定ならローンの種類ごとの既定値）
    max_rate: Optional[float] = None
    max_change: float = 0.5        # 1日でこれ以上動いたら翌日まで保留
    json_path: str = ""            # 金利がJSONデータで公開されている場合のキー（例 "0.new1.floatingRate.apply"）。指定時は anchors 不要
    json_path_max: str = ""        # 幅のある金利の上限のキー（JSONの場合）
    note: str = ""                 # どの数字を読んでいるかの説明（保守用）


def compact(text: str) -> str:
    """全角半角を統一し、空白・改行をすべて取り除く。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or ""))


def extract_rates(text: str, watch: RateWatch) -> Rates:
    """目印に続く金利を (下限, 上限) で返す。見つからなければ ValueError（理由つき）。"""
    if watch.json_path:
        def dig(path):
            node = data
            for k in path.split("."):
                node = node[int(k)] if isinstance(node, list) else node[k]
            return float(node)
        try:
            data = json.loads(text)
            lo = dig(watch.json_path)
            return lo, (dig(watch.json_path_max) if watch.json_path_max else lo)
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise ValueError(f"JSONから {watch.json_path} を読めません: {e}") from e
    body = compact(text)
    if watch.max_anchors:
        lo = _single_after(body, watch.anchors, watch.nth, watch.window, watch.allow_int)
        hi = _single_after(body, watch.max_anchors, watch.max_nth, watch.window, watch.allow_int)
        return lo, hi
    pos = _after_anchors(body, watch.anchors)
    end = pos + watch.window + 20
    if watch.is_range:
        found = list(RANGE_RE.finditer(body, pos, end))
        if len(found) <= watch.nth:
            raise ValueError(f"目印の直後（{watch.window}文字以内）に「X%〜Y%」の金利が見つかりません: …{body[pos:pos + 60]}…")
        m = found[watch.nth]
        return float(m.group(1)), float(m.group(2))
    found = list((RATE_INT_RE if watch.allow_int else RATE_RE).finditer(body, pos, end))
    if len(found) <= watch.nth:
        raise ValueError(f"目印の直後（{watch.window}文字以内）に金利が見つかりません: …{body[pos:pos + 60]}…")
    v = float(found[watch.nth].group(1))
    return v, v


def _after_anchors(body: str, anchors: List[str]) -> int:
    pos = 0
    for a in anchors:
        i = body.find(compact(a), pos)
        if i < 0:
            raise ValueError(f"目印「{a}」が見つかりません")
        pos = i + len(compact(a))
    return pos


def _single_after(body: str, anchors: List[str], nth: int, window: int, allow_int: bool = False) -> float:
    pos = _after_anchors(body, anchors)
    found = list((RATE_INT_RE if allow_int else RATE_RE).finditer(body, pos, pos + window + 20))
    if len(found) <= nth:
        raise ValueError(f"目印の直後（{window}文字以内）に金利が見つかりません: …{body[pos:pos + 60]}…")
    return float(found[nth].group(1))


def extract_rate(text: str, watch: RateWatch) -> float:
    """下限（1つの金利ならその値）だけを返す。"""
    return extract_rates(text, watch)[0]


# ---------------------------------------------------------------- 取得
_render_browser = None
RENDER_TEXT_JS = """() => {
  const b = document.body.cloneNode(true);
  b.querySelectorAll('script,style,noscript,template').forEach(e => e.remove());
  b.querySelectorAll('td,th,li,p,div,dt,dd,br').forEach(e => e.append(' '));
  const alts = [...document.querySelectorAll('img[alt]')].map(i => i.alt).join(' ');
  return b.textContent + ' ' + alts;
}"""


def fetch_rendered_text(url: str, ready: Optional[Callable[[str], bool]] = None) -> Optional[str]:
    """ヘッドレスブラウザ（Playwright）で描画後の本文を取得する。未導入・失敗時は None。

    解析用タグ等で通信が止まらないページがあるため「通信が落ち着くまで待つ」は使わず、
    読み込み後に最大20秒、ready(本文) が真になる（＝金利が描画される）まで待つ。
    """
    global _render_browser
    try:
        from playwright.sync_api import sync_playwright  # 遅延import（未導入でも静的取得は動く）
    except ImportError:
        return None
    try:
        if _render_browser is None:
            pw = sync_playwright().start()
            # HTTP/2 で接続を拒否するサイトがあるため HTTP/1.1 で接続する
            _render_browser = pw.chromium.launch(args=["--disable-http2"])
        page = _render_browser.new_page(locale="ja-JP", user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"))
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            text = ""
            for _ in range(20):
                page.wait_for_timeout(1000)
                # タブ切替で非表示になっている金利表も読めるよう、表示状態に関係なく本文を取得する
                text = page.evaluate(RENDER_TEXT_JS)
                if ready is None or ready(text):
                    break
            return text
        finally:
            page.close()
    except Exception as e:  # noqa: BLE001
        print(f"    [render失敗] {url}: {e}")
        return None


def _readable(text: str, watch: RateWatch) -> bool:
    try:
        extract_rates(text, watch)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- 状態
def load_state() -> Dict[str, dict]:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state: Dict[str, dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fmt_rate(rate: float) -> str:
    """1.5 → "1.50"、1.195 → "1.195"（住宅ローンの金利表記に近い形）。"""
    s = f"{rate:.3f}"
    return s[:-1] if s.endswith("0") else s


def fmt_plain(rate: float) -> str:
    """1.5 → "1.5"、14.0 → "14.0"、3.625 → "3.625"（幅のある金利の表記）。"""
    s = f"{rate:.3f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def format_label(watch: RateWatch, lo: float, hi: float) -> str:
    return watch.label.format(rate=fmt_rate(lo), min=fmt_plain(lo), max=fmt_plain(hi))


def state_key(cfg) -> str:
    return f"{cfg.institution}｜{cfg.product_name}"


def _pair_text(lo, hi) -> str:
    if lo is None:
        return "—"
    return f"{lo}%" if hi in (None, lo) else f"{lo}%〜{hi}%"


def _bounds(cfg, w: RateWatch) -> Tuple[float, float]:
    lo, hi = CATEGORY_BOUNDS.get(getattr(cfg, "loan_category", ""), DEFAULT_BOUNDS)
    return (w.min_rate if w.min_rate is not None else lo, w.max_rate if w.max_rate is not None else hi)


# ---------------------------------------------------------------- 実行
def run_watches(configs, fetch_static: Callable[[str], Optional[str]], today: Optional[str] = None) -> Dict[str, dict]:
    """watch が設定された商品の金利を確認し、状態を更新して返す。"""
    today = today or datetime.now().strftime("%Y-%m-%d")
    state = load_state()
    cache: Dict[tuple, Optional[str]] = {}
    report = {"changed": [], "same": [], "pending": [], "failed": [], "rejected": [], "blocked": []}

    for cfg in configs:
        w = getattr(cfg, "watch", None)
        if not w:
            continue
        key = state_key(cfg)
        cfg_hi = getattr(cfg, "rate_max", None)
        cfg_hi = cfg.rate_min if cfg_hi is None else cfg_hi
        st = state.setdefault(key, {
            "rate": cfg.rate_min, "rateMax": cfg_hi, "checkedAt": cfg.checked_at or None, "history": [],
        })
        st.setdefault("rateMax", st.get("rate"))
        st["url"] = w.url
        # 人が公式サイトで確認して設定（rate_min・rate_max・checked_at）を更新した場合は、それを最新として取り込む
        if cfg.checked_at and (not st.get("checkedAt") or cfg.checked_at > st["checkedAt"]):
            if (st.get("rate"), st.get("rateMax")) != (cfg.rate_min, cfg_hi):
                st["history"].append({"date": cfg.checked_at, "from": st.get("rate"), "to": cfg.rate_min,
                                      "fromMax": st.get("rateMax"), "toMax": cfg_hi, "by": "手動確認"})
                st["changedAt"] = cfg.checked_at
            st["rate"], st["rateMax"], st["checkedAt"] = cfg.rate_min, cfg_hi, cfg.checked_at
        prev = (st.get("rate"), st.get("rateMax"))

        text, how = None, ""
        if not w.render:
            if ("static", w.url) not in cache:
                cache[("static", w.url)] = fetch_static(w.url)
            text, how = cache[("static", w.url)], "通常取得"
        if text is None:
            # JavaScript描画のページ、または通常の取得が拒否された場合はヘッドレスブラウザで取得
            if ("render", w.url) not in cache:
                same_url = [c.watch for c in configs if getattr(c, "watch", None) and c.watch.url == w.url]
                cache[("render", w.url)] = fetch_rendered_text(w.url, ready=lambda t: all(_readable(t, x) for x in same_url))
            text, how = cache[("render", w.url)], "ヘッドレスブラウザ"

        if text is None or BLOCKED_RE.search(compact(text)[:300]):
            # 金融機関側のアクセス制限。毎日は知らせず、確認できない期間が STALE_DAYS を超えたら知らせる
            why = "金融機関側のアクセス制限により自動取得できません（" + ("応答なし・タイムアウト" if text is None else "Access Denied") + f"／{how}）"
            st["lastError"], st["lastErrorAt"] = why, today
            report["blocked"].append((key, why, w.url, st.get("checkedAt")))
            continue
        try:
            lo, hi = extract_rates(text, w)
        except ValueError as e:
            # ページは取得できたのに読めない＝ページ構成の変更の可能性。すぐに知らせる
            msg = f"{e}（{how}で受け取った本文の冒頭: {compact(text)[:60]}…）"
            st["lastError"], st["lastErrorAt"] = msg, today
            report["failed"].append((key, msg, w.url, st.get("checkedAt")))
            continue

        bmin, bmax = _bounds(cfg, w)
        if not (bmin <= lo <= hi <= bmax):
            msg = f"読み取った値 {_pair_text(lo, hi)} が妥当な範囲（{bmin}〜{bmax}%）外のため更新しません"
            st["lastError"], st["lastErrorAt"] = msg, today
            report["rejected"].append((key, msg, w.url))
            continue

        if prev[0] is not None and max(abs(lo - prev[0]), abs(hi - (prev[1] if prev[1] is not None else prev[0]))) >= w.max_change:
            pend = st.get("pending")
            if not pend or (pend.get("rate"), pend.get("rateMax", pend.get("rate"))) != (lo, hi):
                st["pending"] = {"rate": lo, "rateMax": hi, "since": today}
                report["pending"].append((key, _pair_text(*prev), _pair_text(lo, hi), w.url))
                continue
            # 前日以前から同じ値が続いている → 確定

        st.pop("pending", None)
        st.pop("lastError", None)
        st.pop("lastErrorAt", None)
        if prev[0] is None or (lo, hi) != prev:
            entry = {"date": today, "from": prev[0], "to": lo}
            if w.is_range:
                entry.update({"fromMax": prev[1], "toMax": hi})
            st["history"].append(entry)
            st["rate"], st["rateMax"], st["changedAt"] = lo, hi, today
            report["changed"].append((key, _pair_text(*prev), _pair_text(lo, hi), w.url))
        else:
            report["same"].append(key)
        st["checkedAt"] = today

    save_state(state)
    write_report(report, today)
    print(f"  金利の自動確認: 変更 {len(report['changed'])} / 変更なし {len(report['same'])} / "
          f"保留 {len(report['pending'])} / 読み取れず {len(report['failed'])} / 範囲外 {len(report['rejected'])} / "
          f"アクセス制限 {len(report['blocked'])}")
    return state


def _days_since(d: Optional[str], today: str) -> int:
    try:
        return (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(d, "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return 9999


def report_manual_stale(configs, legacy_checked_at: str, today: Optional[str] = None) -> List[str]:
    """自動確認の対象外（公式ページに金利が文字で載っていない等）の商品のうち、
    確認日から STALE_DAYS を超えたものをレポートに追記し、その一覧を返す。"""
    today = today or datetime.now().strftime("%Y-%m-%d")
    stale = []
    for c in configs:
        if getattr(c, "watch", None) or c.rate_min is None:
            continue
        last = c.checked_at or legacy_checked_at
        if _days_since(last, today) > STALE_DAYS:
            stale.append((state_key(c), c.url, last))
    if not stale:
        return []
    lines = []
    if not REPORT_PATH.exists():
        lines += ["ローン金利の自動確認で、対応が必要な項目があります。", ""]
    lines += [f"### 自動確認の対象外で、{STALE_DAYS}日以上公式サイトで確認していない商品（手動確認が必要）", "",
              "公式ページに金利が文字で掲載されていない（画像・PDF・計算ツール内など）ため、毎日の自動確認ができない商品です。"
              "公式ページで確認し、`crawler/fetch_private_loans.py` の該当商品の金利と `checked_at` を更新するか、"
              "金利が文字で載っているページが見つかれば `watch` を追加してください。", "",
              "| 商品 | 公式ページ | 最終確認日 |", "|---|---|---|"]
    lines += [f"| {k} | {u} | {d} |" for k, u, d in stale]
    with open(REPORT_PATH, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return [k for k, _, _ in stale]


def write_report(r: dict, today: str) -> None:
    """GitHub Actions で Issue 本文に使うレポート。要対応がなければファイルを作らない。"""
    def days_since(d):
        try:
            return (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(d, "%Y-%m-%d")).days
        except (TypeError, ValueError):
            return 9999
    stale = [b for b in r["blocked"] if days_since(b[3]) > STALE_DAYS]
    needs_action = r["failed"] or r["rejected"] or r["pending"] or stale
    if REPORT_PATH.exists():
        REPORT_PATH.unlink()
    if not needs_action:
        return
    lines = ["ローン金利の自動確認で、対応が必要な項目があります。", ""]
    if r["failed"]:
        lines += ["### 読み取れなかった商品（金利・確認日は前回のまま）", "",
                  "| 商品 | 理由 | 公式ページ | 最終確認日 |", "|---|---|---|---|"]
        lines += [f"| {k} | {why} | {u} | {last or '—'} |" for k, why, u, last in r["failed"]]
        lines += ["", "ページの構成が変わった場合は `crawler/fetch_private_loans.py` の該当商品の `watch`（url・anchors）を見直してください。", ""]
    if r["pending"]:
        lines += ["### 大きく変わったため保留中（翌日も同じ値なら自動で確定）", "",
                  "| 商品 | 前回 | 今回読み取った値 | 公式ページ |", "|---|---|---|---|"]
        lines += [f"| {k} | {a} | {b} | {u} |" for k, a, b, u in r["pending"]]
        lines += [""]
    if r["rejected"]:
        lines += ["### 妥当な範囲外のため更新しなかった商品", ""]
        lines += [f"- {k}：{why}（{u}）" for k, why, u in r["rejected"]]
        lines += [""]
    if stale:
        lines += [f"### {STALE_DAYS}日以上、公式サイトで金利を確認できていない商品（手動確認が必要）", "",
                  "金融機関側のアクセス制限で自動取得できない商品です。公式ページで金利を確認し、"
                  "`crawler/fetch_private_loans.py` の該当商品の `rate_min`・`rate_max`・`rate_label`・`checked_at`（確認日）を更新してください。", "",
                  "| 商品 | 公式ページ | 最終確認日 |", "|---|---|---|"]
        lines += [f"| {k} | {u} | {last or '—'} |" for k, why, u, last in stale]
        lines += [""]
    if r["changed"]:
        lines += ["### 参考：本日更新した金利", ""]
        lines += [f"- {k}：{a} → {b}" for k, a, b, u in r["changed"]]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def dry_run() -> int:
    """状態を保存せずに、全商品の読み取り結果だけを表示する（設定の確認用）。

    python -m crawler.rate_watch            … 全商品
    python -m crawler.rate_watch みずほ       … 名前に「みずほ」を含む商品だけ
    """
    import sys
    import tempfile
    from .fetch_private_loans import LOAN_CONFIG, fetch_page_text

    global STATE_PATH, REPORT_PATH
    tmp = Path(tempfile.mkdtemp())
    STATE_PATH, REPORT_PATH = tmp / "state.json", tmp / "report.md"
    words = sys.argv[1:]
    targets = [c for c in LOAN_CONFIG if getattr(c, "watch", None)
               and (not words or any(w in state_key(c) for w in words))]
    state = run_watches(targets, fetch_page_text)
    ng = 0
    for c in targets:
        st = state[state_key(c)]
        if st.get("lastError"):
            ng += 1
            print(f"NG  {state_key(c)}\n      {st['lastError']}")
        else:
            p = st.get("pending") or st
            print(f"OK  {state_key(c)}: {_pair_text(p['rate'], p.get('rateMax'))}")
    return 1 if ng else 0


if __name__ == "__main__":
    raise SystemExit(dry_run())
