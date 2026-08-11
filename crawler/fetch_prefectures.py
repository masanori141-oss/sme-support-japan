"""
都道府県ごとの制度融資・独自補助金を取得する。

47都道府県は、それぞれ公式サイトの構造が違う（今回のResearchでも
そうだった）。そのため「1本のコードで全部読める」ようにはできず、
PREF_PROGRAM_CONFIG に県ごとの「どのURLを見るか」「今分かっている
数値（初期値）」を登録しておき、実行時に各URLへ実際にアクセスして
汎用的なキーワード・正規表現で数値の自動更新を試みる、という
「半自動」の構成にしている。

【動き方】
1. 各 config の url に実際にアクセスし、ページのテキストを取得する
2. amount_label / rate_label / deadline_label が「要確認」のままの
   項目についてのみ、category（融資/補助金）に応じた正規表現で
   「限度額」「利率」「補助率」「締切日」などを探して埋める
   （すでに人手で確認済みの値は、汎用正規表現がページ内の無関係な
   数字・日付に誤ってマッチするリスクがあるため上書きしない）
3. 自動抽出できなかった場合は config に登録済みの値をそのまま使う
   （＝サイト構造が変わって自動抽出できなくても、表示が空になったり
   古すぎる値のまま気づかれない、という事故を防ぐ）
4. アクセス自体に失敗した場合（タイムアウト・404等）も同様に
   config の値にフォールバックする

【新しい制度・県を追加する場合】
PREF_PROGRAM_CONFIG に PrefProgramConfig を1件追加するだけでよい。
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from .fetch_national import parse_deadline
from .schema import Program

PREFECTURES_JA = {
    "hokkaido": "北海道", "aomori": "青森県", "iwate": "岩手県", "miyagi": "宮城県",
    "akita": "秋田県", "yamagata": "山形県", "fukushima": "福島県", "ibaraki": "茨城県",
    "tochigi": "栃木県", "gunma": "群馬県", "saitama": "埼玉県", "chiba": "千葉県",
    "tokyo": "東京都", "kanagawa": "神奈川県", "niigata": "新潟県", "toyama": "富山県",
    "ishikawa": "石川県", "fukui": "福井県", "yamanashi": "山梨県", "nagano": "長野県",
    "gifu": "岐阜県", "shizuoka": "静岡県", "aichi": "愛知県", "mie": "三重県",
    "shiga": "滋賀県", "kyoto": "京都府", "osaka": "大阪府", "hyogo": "兵庫県",
    "nara": "奈良県", "wakayama": "和歌山県", "tottori": "鳥取県", "shimane": "島根県",
    "okayama": "岡山県", "hiroshima": "広島県", "yamaguchi": "山口県", "tokushima": "徳島県",
    "kagawa": "香川県", "ehime": "愛媛県", "kochi": "高知県", "fukuoka": "福岡県",
    "saga": "佐賀県", "nagasaki": "長崎県", "kumamoto": "熊本県", "oita": "大分県",
    "miyazaki": "宮崎県", "kagoshima": "鹿児島県", "okinawa": "沖縄県",
}

DEFAULT_SCALE = ["小規模5", "小規模20", "中小企業100", "中小企業300"]

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
REQUEST_TIMEOUT = 20


@dataclass
class PrefProgramConfig:
    """1都道府県・1制度ぶんの設定。url と初期値（フォールバック値）を持つ。"""
    pref: str                      # 例: "osaka"
    category: str                  # "融資" / "補助金" / "共済"
    program_name: str              # 制度の正式名称
    url: str                       # 公式ページのURL
    kicker: str                    # 一覧に出す一言説明
    purpose: List[str]             # 目的タグ
    amount_label: str = "要確認（公式サイトで最終確認）"
    rate_label: str = "要確認（公式サイトで最終確認）"
    deadline: str = "2099-01-01"
    deadline_label: str = "随時受付中（通年・信用保証協会の保証が必要）"
    eligibility: List[str] = field(default_factory=list)
    confirmed: bool = False        # True なら「登録済みの値は確認済み」として扱う


# 今回のResearchで判明した47都道府県分の制度融資・独自補助金・共済を、
# そのまま初期値（フォールバック値）として登録。
# ここに無い県・新しい制度が出てきた場合は、この一覧に1件追加するだけでよい。
PREF_PROGRAM_CONFIG: List[PrefProgramConfig] = [
    PrefProgramConfig(
        pref="hokkaido", category="融資",
        program_name="北海道中小企業総合振興資金",
        url="https://www.pref.hokkaido.lg.jp/kz/csk/kny/yuushi/",
        kicker="制度融資 ｜ 北海道内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（公式サイトで最終確認）",
        rate_label="要確認（公式サイトで最終確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["北海道内で事業を営む中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="hokkaido", category="補助金",
        program_name="中小・小規模企業賃上げ環境整備等支援事業費補助金",
        url="https://www.pref.hokkaido.lg.jp/kz/csk/249117.html",
        kicker="賃上げ環境整備・設備投資 ｜ 道内の中小・小規模事業者向け",
        purpose=["設備投資"],
        amount_label="上限200万円（促進枠300万円）",
        rate_label="補助率 1/2（賃上げ率4.0%以上は3/4）",
        deadline="2026-09-30", deadline_label="2026年9月30日（予算上限に達し次第終了）",
        eligibility=["北海道内の中小企業・小規模事業者", "賃上げに取り組む計画がある", "新商品開発・販路拡大・設備投資のいずれかを予定"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="aomori", category="融資",
        program_name="青森県特別保証融資制度",
        url="https://www.pref.aomori.lg.jp/soshiki/sangyo/sangyo/kenyuusi.html",
        kicker="制度融資 ｜ 青森県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（メニュー別）",
        rate_label="メニュー別（経営力向上割引で年0.5%引下げ等）（融資期間:要確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="iwate", category="融資",
        program_name="岩手県中小企業成長応援資金",
        url="https://www.pref.iwate.jp/sangyoukoyou/sangyoushinkou/kinyuu/1009133.html",
        kicker="制度融資 ｜ 岩手県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="5,000万円以内",
        rate_label="3年以内 年2.5%以内、3年超10年以内 年2.7%以内（県北・沿岸は0.1%減）（融資期間:10年以内（据置2年以内））",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内に事業所を有する中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="iwate", category="補助金",
        program_name="物価高騰対策賃上げ支援金",
        url="https://iwate-bukkakoutoutaisaku.pref.iwate.jp/",
        kicker="賃上げ支援 ｜ 県内中小企業向け",
        purpose=["賃上げ支援"],
        amount_label="県全体で25億4,000万円が上限（到達次第終了）",
        rate_label="賃金引上げ実績に基づき算定",
        deadline="2026-11-13", deadline_label="2026年11月13日（上限到達次第終了）",
        eligibility=["岩手県内の中小企業者等", "賃上げを実施している、または予定している", "支援金の算定基準（引上げ実績）を満たす"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="miyagi", category="融資",
        program_name="宮城県中小企業経営安定資金",
        url="https://www.pref.miyagi.jp/soshiki/syokokin/syokinhan-index-2.html",
        kicker="制度融資 ｜ 宮城県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="5,000万円以内",
        rate_label="固定・低利（要確認）（融資期間:要確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内で事業を営む中小企業者・組合等", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="miyagi", category="補助金",
        program_name="中小企業等デジタル化支援事業",
        url="https://www.pref.miyagi.jp/soshiki/chukisi/r8digital-shien.html",
        kicker="DX・AI導入 ｜ 県内中小企業・小規模事業者向け",
        purpose=["DX・AI"],
        amount_label="アドバイザー派遣＋補助（枠により異なる）",
        rate_label="枠により異なる",
        deadline="2027-02-12", deadline_label="2027年2月12日",
        eligibility=["宮城県内に本店・住所を有する中小企業者・個人事業主", "業務効率化・生産性向上のためのデジタル化に取り組みたい", "アドバイザーの助言を受けながら進める意思がある"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="akita", category="融資",
        program_name="秋田県中小企業振興資金（一般資金）",
        url="https://www.pref.akita.lg.jp/pages/genre/14094",
        kicker="制度融資 ｜ 秋田県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（流動資産担保資金は1億円）",
        rate_label="要確認（融資期間:10年以内（据置1年以内）等）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="akita", category="補助金",
        program_name="M＆A支援事業",
        url="https://www.pref.akita.lg.jp/pages/archive/95760",
        kicker="事業承継・M&A ｜ 県内中小企業向け",
        purpose=["事業承継"],
        amount_label="上限100万円（譲渡型。類型により異なる）",
        rate_label="類型により異なる",
        deadline="2026-12-25", deadline_label="2026年12月25日（PMI型等は9/30、予算到達次第終了）",
        eligibility=["秋田県内でM&Aを実施しようとする、または実施した中小企業", "仲介契約締結・企業概要書作成等の準備段階にある", "承継後のPMI（統合）に取り組む場合も対象"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="yamagata", category="融資",
        program_name="山形県商工業振興資金融資制度",
        url="https://www.pref.yamagata.jp/110013/sangyo/shokogyo/shien/17shikin.html",
        kicker="制度融資 ｜ 山形県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（メニュー別）",
        rate_label="例）地域経済変動対策資金 年1.7%（固定）（融資期間:要確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="yamagata", category="補助金",
        program_name="中小企業まるっとサポート補助金（事業継続力強化支援 第2次）",
        url="https://www.pref.yamagata.jp/110013/sangyo/shokogyo/shinko/r8marusapo_jigyokeizoku2_bosyu.html",
        kicker="事業継続力強化 ｜ 県内中小企業・小規模事業者向け",
        purpose=["設備投資"],
        amount_label="要確認（公式要領で確認）",
        rate_label="要確認（公式要領で確認）",
        deadline="2026-12-31", deadline_label="受付中（終了日は公式要領で要確認）",
        eligibility=["山形県内の中小企業・小規模事業者等", "事業継続力強化（BCP等）の取組を予定している", "公式要領で詳細要件の確認が必要"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="fukushima", category="融資",
        program_name="福島県中小企業制度資金",
        url="https://www.pref.fukushima.lg.jp/sec/32011b/seidosikin.html",
        kicker="制度融資 ｜ 福島県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（信用組合資金は2,500万円）",
        rate_label="要確認（保証付で年2.5%以内等）（融資期間:運転10年以内・設備15年以内（据置1年以内）等）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="fukushima", category="補助金",
        program_name="中小企業等生産性向上推進事業補助金",
        url="https://www.pref.fukushima.lg.jp/sec/32011b/seisanseikoujoh.html",
        kicker="生産性向上・設備投資 ｜ 県内中小企業者向け",
        purpose=["設備投資"],
        amount_label="上限200万円（下限30万円）",
        rate_label="2/3以内",
        deadline="2026-11-27", deadline_label="2026年11月27日（予算上限到達次第終了）",
        eligibility=["福島県内に事業所を有する中小企業者等", "生産性向上計画を策定できる", "パートナーシップ構築宣言を行う（または行う予定）"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="ibaraki", category="融資",
        program_name="茨城県中小企業向け融資制度（パワーアップ融資）",
        url="https://www.pref.ibaraki.jp/shokorodo/sansei/kinyu/shosei/yushi/yushitop.html",
        kicker="制度融資 ｜ 茨城県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="設備5,000万円・運転3,000万円・併用5,000万円",
        rate_label="要確認（融資期間:設備・運転とも10年程度）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内に事業所を有し1年以上同一事業を営む中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="tochigi", category="融資",
        program_name="栃木県小規模企業資金",
        url="https://www.pref.tochigi.lg.jp/f03/work/shoukougyou/yuushi/",
        kicker="制度融資 ｜ 栃木県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="3,000万円",
        rate_label="責任共有制度対象 年1.8%以内、対象外 年1.6%以内（令和8年4月改定）（融資期間:1年超10年以内（据置1年以内））",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内に事業所を有し同一事業を1年以上営む中小企業者・小規模企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="tochigi", category="補助金",
        program_name="事業承継支援補助金",
        url="https://www.pref.tochigi.lg.jp/f03/jigyoushoukei/r8uketukekaishi.html",
        kicker="事業承継 ｜ 県内中小企業向け",
        purpose=["事業承継"],
        amount_label="要確認（交付要領による）",
        rate_label="要確認（交付要領による）",
        deadline="2026-11-30", deadline_label="2026年11月30日（予算上限到達次第終了）",
        eligibility=["栃木県内に本店（個人事業者は住所）がある中小企業者", "事業承継後も雇用維持・県内拠点維持の見込みがある", "支援機関の推薦を受けられる"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="gunma", category="融資",
        program_name="群馬県制度融資（経営サポート資金）",
        url="https://www.pref.gunma.jp/site/seidoyuushi/",
        kicker="制度融資 ｜ 群馬県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="メニュー別（経営サポート資金5,000〜6,000万円等）",
        rate_label="例）経営サポート資金 年1.7%以内（融資期間:運転7〜10年以内・設備10年以内（据置1〜2年））",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内で事業を営む中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="gunma", category="補助金",
        program_name="中小企業等海外出願支援事業",
        url="https://www.g-inf.or.jp/html/subsidy_001.html",
        kicker="海外展開・知的財産 ｜ 県内中小企業向け",
        purpose=["商品開発・海外展開"],
        amount_label="上限300万円",
        rate_label="要確認（財団要領で確認）",
        deadline="2026-08-31", deadline_label="2026年8月31日",
        eligibility=["群馬県内の中小企業者等", "外国への特許出願等を予定している", "申請前に財団への相談ができる"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="saitama", category="融資",
        program_name="埼玉県中小企業制度融資（経営安定資金）",
        url="https://www.pref.saitama.lg.jp/a0805/seidoyushi/",
        kicker="制度融資 ｜ 埼玉県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（公式サイトで最終確認）",
        rate_label="年1.8%〜2.2%（上限利率、利子補給後・固定）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["埼玉県内で事業を営む中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="saitama", category="補助金",
        program_name="埼玉県中小企業DX導入支援補助金",
        url="https://www.pref.saitama.lg.jp/a0803/dx_jigyousyashien/dx_index.html",
        kicker="ITツール・DX導入 ｜ 埼玉県内の中小企業・個人事業主向け",
        purpose=["DX・AI"],
        amount_label="上限300万円（下限7万5千円）",
        rate_label="補助率 3/4以内",
        deadline="2026-08-31", deadline_label="2026年8月31日（第2期）",
        eligibility=["埼玉県内に本社・事業所がある中小企業・個人事業主", "直近1期分の決算（確定申告）を終えている", "導入したいDXツールが明確にある"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="chiba", category="融資",
        program_name="千葉県中小企業向け融資制度",
        url="https://www.pref.chiba.lg.jp/keishi/chuushou-yuushi/yuushiseido/chuushou/",
        kicker="制度融資 ｜ 千葉県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="メニュー別（事業再生資金6,000万円等）",
        rate_label="例）固定 年1.1〜1.5%（事業再生資金）（融資期間:要確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内で事業を行う中小企業者等", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="chiba", category="補助金",
        program_name="中小企業成長促進補助金（第4弾）",
        url="https://www.pref.chiba.lg.jp/keisei/zaisei/chiba-seichohojyo4.html",
        kicker="設備投資・省力化 ｜ 県内中小企業・小規模事業者向け",
        purpose=["設備投資"],
        amount_label="上限3,000万円（小規模事業者枠は上限500万円）",
        rate_label="1/2以内",
        deadline="2026-08-21", deadline_label="2026年8月21日17時（予定）",
        eligibility=["千葉県内に事業所を有する中小企業者等", "省力化・業務効率化・生産性向上の設備投資を計画している", "小規模事業者は専用枠（上限500万円）も選べる"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="tokyo", category="融資",
        program_name="東京都中小企業制度融資",
        url="https://www.sangyo-rodo.metro.tokyo.lg.jp/",
        kicker="制度融資 ｜ 東京都内の中小企業向け",
        purpose=["設備投資"],
        amount_label="主力メニューで2億8千万円",
        rate_label="主力メニューで年2.15%以内〜2.85%以内（固定・変動選択可）（融資期間:運転・設備とも15年以内（据置2年以内））",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["都内中小企業・個人事業主", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="tokyo", category="補助金",
        program_name="地域資源活用製品等の開発・販売促進事業（販路開拓フェーズ）",
        url="https://www.tokyo-kosha.or.jp/support/josei/index.html",
        kicker="商品開発・販路開拓 ｜ 都内中小企業・個人事業主向け",
        purpose=["商品開発・海外展開"],
        amount_label="上限1,500万円",
        rate_label="2/3以内",
        deadline="2026-08-17", deadline_label="2026年8月17日",
        eligibility=["東京都内の中小企業者・個人事業主・団体等", "地域資源活用や都市課題解決に資する製品・サービスがある", "販売促進の具体的な計画がある"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="kanagawa", category="融資",
        program_name="神奈川県中小企業制度融資（事業振興融資）",
        url="https://www.pref.kanagawa.jp/docs/m6c/cnt/f5782/",
        kicker="制度融資 ｜ 神奈川県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="2億円",
        rate_label="要確認（公式サイトで最終確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["神奈川県内で事業を営む中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="kanagawa", category="補助金",
        program_name="中小企業生産性向上促進事業費補助金（一般枠）8月公募",
        url="https://www.pref.kanagawa.jp/docs/m2w/prs/r2625041.html",
        kicker="生産性向上・設備投資 ｜ 県内中小企業者向け",
        purpose=["設備投資"],
        amount_label="上限500万円（一般枠）",
        rate_label="補助率 1/2以内（小規模2/3以内）",
        deadline="2026-08-31", deadline_label="2026年8月31日17時",
        eligibility=["神奈川県内の中小企業者等", "人手不足解消・業務プロセス改善につながる設備投資を予定", "生産性向上の具体的な計画がある"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="niigata", category="融資",
        program_name="新潟県中小企業向け制度融資",
        url="https://www.pref.niigata.lg.jp/sec/chiikishinko/yuushi-seidoyushi.html",
        kicker="制度融資 ｜ 新潟県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（メニュー別）",
        rate_label="要確認（融資期間:要確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["原則県内で1年以上継続して同一事業を営む中小企業者・事業協同組合等", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="toyama", category="融資",
        program_name="富山県中小企業向け融資制度",
        url="https://www.pref.toyama.jp/1300/sangyou/shoukoukensetsu/shoukougyou/kj00012293/index.html",
        kicker="制度融資 ｜ 富山県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="メニュー別（小口事業資金2,000万円等）",
        rate_label="要確認（融資期間:要確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内で事業を営む中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="toyama", category="補助金",
        program_name="中小企業再生支援強化事業費補助金（第3次追加募集）",
        url="https://www.pref.toyama.jp/sangyou/shoukoukensetsu/shoukougyou/shien/hojokin/index.html",
        kicker="省力化・DX・GX ｜ 県内中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（公式要領で確認）",
        rate_label="要確認（公式要領で確認）",
        deadline="2026-09-30", deadline_label="追加募集開始（終了日は公式で要確認）",
        eligibility=["富山県内の中小企業者等", "省力化・省人化、DX、GXいずれかの取組がある", "公式要領で詳細要件の確認が必要"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="ishikawa", category="融資",
        program_name="石川県制度金融（制度融資）",
        url="https://www.pref.ishikawa.lg.jp/kinyuu/kinyuu/youkou.html",
        kicker="制度融資 ｜ 石川県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（小口零細等メニュー別）",
        rate_label="要確認（融資期間:要確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["原則1年以上県内に事業所を有し同一事業を営む中小企業者等", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="ishikawa", category="補助金",
        program_name="新商品・新サービス開発支援事業助成金",
        url="https://www.isico.or.jp/",
        kicker="商品開発 ｜ 県内中小企業・小規模事業者向け",
        purpose=["商品開発・海外展開"],
        amount_label="最大300万円",
        rate_label="小規模事業者2/3、中小企業者1/2",
        deadline="2026-11-30", deadline_label="2026年11月30日",
        eligibility=["石川県内の中小企業者・小規模事業者", "新商品・新サービスの開発計画がある", "石川県産業創出支援機構（ISICO）の支援を受けられる"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="fukui", category="融資",
        program_name="福井県中小企業者向け制度融資",
        url="https://www.pref.fukui.lg.jp/doc/sinsan/seidoyuusihyousi.html",
        kicker="制度融資 ｜ 福井県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="8,000万円",
        rate_label="年1.7%以下（固定）（融資期間:10年以内（据置2〜3年））",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="fukui", category="補助金",
        program_name="人材育成支援事業補助金",
        url="https://www.pref.fukui.lg.jp/doc/kanri/ninaitehozyo.html",
        kicker="人材育成（建設業） ｜ 県内建設業者向け",
        purpose=["人材確保"],
        amount_label="要確認（公式要領で確認）",
        rate_label="要確認（公式要領で確認）",
        deadline="2026-09-30", deadline_label="2026年9月30日",
        eligibility=["福井県内に主たる営業所があり建設業許可を有する事業者", "人材育成に係る取組を予定している", "事業実施は令和9年2月末までに完了予定"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="yamanashi", category="融資",
        program_name="山梨県中小企業制度融資（商工業振興資金）",
        url="https://www.pref.yamanashi.jp/shigoto/shokogyo/shogyo/yushi.html",
        kicker="制度融資 ｜ 山梨県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="一企業5,000万円（設備5,000万円／運転2,000万円）",
        rate_label="固定 年2.1%（県補助後）（融資期間:設備7年以内・運転5年以内（据置1年））",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="nagano", category="融資",
        program_name="長野県中小企業融資制度（中小企業振興資金）",
        url="https://www.pref.nagano.lg.jp/keieishien/sangyo/shokogyo/kinyu/chusyo-yushi/index.html",
        kicker="制度融資 ｜ 長野県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="設備1億円・運転5,000万円",
        rate_label="固定 年2.4%（融資期間1年以内は年2.1%）（融資期間:設備10年以内・運転7年以内）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="gifu", category="融資",
        program_name="岐阜県中小企業資金融資制度",
        url="https://www.pref.gifu.lg.jp/page/2522.html",
        kicker="制度融資 ｜ 岐阜県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（小規模企業小口1,250万円等）",
        rate_label="概ね年0.8%〜（別途保証料）（融資期間:運転7年・設備10年以内等）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="shizuoka", category="融資",
        program_name="静岡県中小企業向け制度融資（経営改善資金）",
        url="https://www.pref.shizuoka.jp/sangyoshigoto/kigyoshien/seidoyushi/index.html",
        kicker="制度融資 ｜ 静岡県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="1企業5,000万円（設備＋運転合計）",
        rate_label="要確認（別途保証料）（融資期間:要確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="aichi", category="融資",
        program_name="愛知県中小企業融資制度（経済環境適応資金等）",
        url="https://www.pref.aichi.jp/soshiki/kinyu/yushi2024.html",
        kicker="制度融資 ｜ 愛知県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（メニュー別）",
        rate_label="原則固定金利（融資期間:要確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="mie", category="融資",
        program_name="三重県中小企業融資制度",
        url="https://www.pref.mie.lg.jp/SHINSAN/HP/77426022712.htm",
        kicker="制度融資 ｜ 三重県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（がんばる小規模企業応援資金2,000万円等）",
        rate_label="固定 年1.70〜1.80%（一般扱い）（融資期間:要確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="shiga", category="融資",
        program_name="滋賀県中小企業振興資金融資制度",
        url="https://www.pref.shiga.lg.jp/ippan/shigotosangyou/kigyou/300703.html",
        kicker="制度融資 ｜ 滋賀県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="設備3,000万円・運転2,000万円",
        rate_label="固定 年1.50%（融資期間:設備7年以内・運転5年以内）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="kyoto", category="融資",
        program_name="京都府中小企業制度融資（一般資金）",
        url="https://www.pref.kyoto.jp/kinyu/seido.html",
        kicker="制度融資 ｜ 京都府内の中小企業向け",
        purpose=["設備投資"],
        amount_label="有担保2億円・無担保8,000万円",
        rate_label="取扱金融機関により異なる（期間内固定）（融資期間:10年）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["府内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="osaka", category="融資",
        program_name="大阪府制度融資",
        url="https://www.pref.osaka.lg.jp/o110080/kinyushien/seido001/index.html",
        kicker="制度融資 ｜ 大阪府内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（公式サイトで最終確認）",
        rate_label="要確認（公式サイトで最終確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["大阪府内で事業を営む中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="osaka", category="補助金",
        program_name="中小事業者の脱炭素化に係る自主的取組支援補助金（2次公募）",
        url="https://www.pref.osaka.lg.jp/o120020/eneseisaku/sec/plan2_subsidy.html",
        kicker="脱炭素・省エネ設備 ｜ 府内中小事業者向け",
        purpose=["脱炭素"],
        amount_label="上限200万円",
        rate_label="補助率 1/3以内",
        deadline="2026-10-05", deadline_label="2026年10月5日18時",
        eligibility=["大阪府内に工場・事業場がある中小事業者", "大阪府脱炭素経営宣言に登録している（申請時登録可）", "エネルギー使用量1％以上またはCO2年1トン以上の削減計画"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="hyogo", category="融資",
        program_name="兵庫県中小企業融資制度（経営活性化資金）",
        url="https://web.pref.hyogo.lg.jp/sr08/ie05_000000031.html",
        kicker="制度融資 ｜ 兵庫県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="設備5,000万円・運転3,000万円",
        rate_label="金融機関所定利率（保証料率 主に0.45〜1.90%）（融資期間:設備7年以内・運転5年以内）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="hyogo", category="補助金",
        program_name="GX診断補助金（省エネ診断受診支援）",
        url="https://web.pref.hyogo.lg.jp/sr07/sdgs.html",
        kicker="脱炭素・省エネ診断 ｜ 県内中小事業者向け",
        purpose=["脱炭素"],
        amount_label="診断メニューにより異なる",
        rate_label="補助率 1/2",
        deadline="2027-01-29", deadline_label="2027年1月29日",
        eligibility=["兵庫県内の中小事業者", "ひょうご産業SDGs推進宣言を行っている（申請時対応可）", "省エネ診断を受診したい意向がある"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="nara", category="融資",
        program_name="奈良県制度融資（中小企業事業資金）",
        url="https://www.pref.nara.jp/5217.htm",
        kicker="制度融資 ｜ 奈良県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（創業資金1,500万円等）",
        rate_label="県が利子・保証料の一部/全部を負担（要確認）（融資期間:要確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="wakayama", category="融資",
        program_name="和歌山県中小企業融資制度",
        url="https://www.pref.wakayama.lg.jp/prefg/060300/gyoumu/kinyuu/sangyoushien.html",
        kicker="制度融資 ｜ 和歌山県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認",
        rate_label="低利固定長期（県が保証料一部負担）（融資期間:要確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="tottori", category="融資",
        program_name="鳥取県企業自立サポート融資",
        url="https://www.pref.tottori.lg.jp/99469.htm",
        kicker="制度融資 ｜ 鳥取県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="1億円",
        rate_label="年2.10%（変動金利・年2回改定）（融資期間:運転7年以内・設備10年以内）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="shimane", category="融資",
        program_name="島根県中小企業制度融資（一般資金等）",
        url="https://www.pref.shimane.lg.jp/industry/syoko/sangyo/yuushi/tyusyo.html",
        kicker="制度融資 ｜ 島根県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認",
        rate_label="固定 年1.45%（責任共有）／年1.30%（責任共有外）（融資期間:設備12年・運転7年）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="shimane", category="共済",
        program_name="ジョイメイトしまね／ジョイメイトいわみ（勤労者共済会）",
        url="https://www.joymate.or.jp/",
        kicker="勤労者福祉共済 ｜ 県内中小企業の従業員・事業主向け",
        purpose=["設備投資"],
        amount_label="月会費1,000円",
        rate_label="慶弔給付・退職金制度普及・宿泊/レジャー割引（400店舗超）",
        deadline="2099-01-01", deadline_label="随時加入可能（通年）",
        eligibility=["島根県内の中小企業（従業員300人以下または資本金3億円以下）", "従業員・役員・パート・個人事業主も加入可", "国・県・市町村がバックアップする勤労者共済会"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="okayama", category="融資",
        program_name="岡山県中小企業振興資金（小規模企業支援資金）",
        url="https://www.pref.okayama.jp/page/detail-42458.html",
        kicker="制度融資 ｜ 岡山県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="一般2,000万円（組合5,000万円）",
        rate_label="年1.80%以内（保証料 年0.45〜1.52%）（融資期間:10年以内）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="hiroshima", category="融資",
        program_name="広島県制度融資（県費預託融資制度・一般資金等）",
        url="https://www.pref.hiroshima.lg.jp/soshiki/75/1168587452727.html",
        kicker="制度融資 ｜ 広島県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認",
        rate_label="固定 3年以内年1.5%／5年以内年1.7%／10年以内年1.9%（融資期間:運転10年・設備10年）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="hiroshima", category="補助金",
        program_name="中小企業等プロフェッショナル人材確保支援事業補助金",
        url="https://www.pref.hiroshima.lg.jp/site/pro-kyoten/probosyu08.html",
        kicker="人材確保 ｜ 県内中小・中堅企業向け",
        purpose=["人材確保"],
        amount_label="上限100万円/人（役員採用等は200万円）",
        rate_label="人材紹介手数料（成功報酬部分）の1/2",
        deadline="2027-03-24", deadline_label="2027年3月24日",
        eligibility=["広島県内の中小・中堅企業、組合等", "登録人材紹介会社を通じたプロ人材採用を予定", "副業・兼業人材の活用でも利用できる"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="yamaguchi", category="融資",
        program_name="山口県中小企業制度融資（経営基盤強化資金等）",
        url="https://www.pref.yamaguchi.lg.jp/soshiki/85/21831.html",
        kicker="制度融資 ｜ 山口県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認",
        rate_label="2025年度に原則0.2%引上げ（具体値はガイドブック）（融資期間:要確認）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="yamaguchi", category="補助金",
        program_name="中小企業DX推進補助金「DXツール導入型」",
        url="https://www.pref.yamaguchi.lg.jp/press/343044.html",
        kicker="DX・AI導入 ｜ 県内中小企業向け",
        purpose=["DX・AI"],
        amount_label="上限75万円（募集100件程度）",
        rate_label="1/2以内",
        deadline="2026-12-25", deadline_label="2026年12月25日（予算上限で早期終了の可能性）",
        eligibility=["山口県内に事業所を有する中小企業者（農林漁業を除く）", "DXツールの導入を計画している", "早めの申請がおすすめ（先着枠あり）"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="tokushima", category="融資",
        program_name="徳島県中小企業向け融資制度",
        url="https://www.pref.tokushima.lg.jp/jigyoshanokata/sangyo/shokogyo/5015570/",
        kicker="制度融資 ｜ 徳島県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="小口資金2,000万円・創業者無担保3,500万円等",
        rate_label="例）小口 年1.70%以内、創業1.20〜1.90%（融資期間:運転5〜7年・設備8年（据置1〜2年）等）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="tokushima", category="共済",
        program_name="あわ〜ず徳島（勤労者福祉サービスセンター事業）",
        url="https://toku-nw.com/",
        kicker="勤労者福祉共済 ｜ 県内中小企業の従業員・事業主向け",
        purpose=["設備投資"],
        amount_label="要確認（会費は公式サイトで確認）",
        rate_label="慶弔給付・医療/死亡保障・レジャー/チケット割引・ファミサポ利用助成",
        deadline="2099-01-01", deadline_label="随時加入可能（通年）",
        eligibility=["徳島県内の中小企業の勤労者・事業主", "県・市町村・経営者団体・労働者福祉事業団体が構成する公労使型組織", "2026年7月時点で1,078事業所・16,054人が加入"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="kagawa", category="融資",
        program_name="香川県中小企業者融資制度（経営安定融資）",
        url="https://www.pref.kagawa.lg.jp/keiei/kinyu/yuushi/yuushi.html",
        kicker="制度融資 ｜ 香川県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="長期8,000万円以内・短期1,000万円以内",
        rate_label="固定 長期7年以内年2.10%以内／7年超2.20%以内、短期年2.00%以内（融資期間:設備10年以内）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="ehime", category="融資",
        program_name="愛媛県中小企業向け融資制度（経済対策資金等）",
        url="https://www.pref.ehime.jp/page/59788.html",
        kicker="制度融資 ｜ 愛媛県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="運転 企業5,000万円・組合1億円、借換 企業8,000万円",
        rate_label="要確認（例 年1.50〜1.65%）（融資期間:運転7年以内（据置1年）、借換10年以内等）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="kochi", category="融資",
        program_name="高知県中小企業等融資制度",
        url="https://www.pref.kochi.lg.jp/soshiki/150401/2022041300169.html",
        kicker="制度融資 ｜ 高知県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（経営力強化枠2億8,000万円）",
        rate_label="年2回改定（例 運転2.27%・設備2.42%以内 変動）（融資期間:7年以内（据置1年）等）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="kochi", category="補助金",
        program_name="事業戦略等推進事業費補助金",
        url="https://joho-kochi.or.jp/center/r8top.php",
        kicker="地産外商・設備投資 ｜ 県内中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（公式要領で確認）",
        rate_label="要確認（公式要領で確認）",
        deadline="2027-02-28", deadline_label="毎月募集（申請月前月末営業日締切、予算上限で終了）",
        eligibility=["高知県内の中小企業者等", "ものづくりの地産外商の取組がある", "毎月のエントリー締切に間に合わせられる"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="fukuoka", category="融資",
        program_name="福岡県中小企業振興資金融資制度（緊急経済対策資金）",
        url="https://www.pref.fukuoka.lg.jp/contents/r8yuushiseidoannai.html",
        kicker="制度融資 ｜ 福岡県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="1億円以内（新規創業資金は3,500万円以内）",
        rate_label="緊急経済対策資金 年1.30%、新規創業資金 年1.30%（女性/35歳未満/55歳以上は年1.20%）（融資期間:10年以内（据置2年以内））",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="fukuoka", category="補助金",
        program_name="中小企業経営革新・賃上げ緊急支援補助金",
        url="https://www.pref.fukuoka.lg.jp/contents/fukuoka-chinage.html",
        kicker="賃上げ支援 ｜ 県内中小企業向け",
        purpose=["賃上げ支援"],
        amount_label="要確認（公式要領で確認）",
        rate_label="要確認（公式要領で確認）",
        deadline="2026-12-31", deadline_label="随時受付（予算上限に達し次第終了）",
        eligibility=["福岡県内に本店（個人事業主は県内在住）", "経営革新計画の承認を受けている（令和7年7月以降）", "事業場内最低賃金が県最低賃金以上"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="saga", category="融資",
        program_name="佐賀県中小企業金融制度（県制度融資）",
        url="https://www.pref.saga.lg.jp/kiji00327111/index.html",
        kicker="制度融資 ｜ 佐賀県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="設備4,000万円・運転2,000万円",
        rate_label="固定 5年以内年1.90%／5年超7年以内年2.00%／7年超年2.10%（融資期間:設備10年・運転7年）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="saga", category="共済",
        program_name="佐賀県中小企業勤労者福祉サービスセンター",
        url="https://saga-sc.net/",
        kicker="勤労者福祉共済 ｜ 県内中小企業の従業員・事業主向け",
        purpose=["設備投資"],
        amount_label="事業所年額6,000〜10,000円・会費月額700〜1,000円",
        rate_label="人間ドック補助（上限10,000円）・宿泊助成2,000円・共済給付（結婚祝金20,000円等）",
        deadline="2099-01-01", deadline_label="随時加入可能（通年）",
        eligibility=["佐賀県内の中小企業（資本金3億円以下または従業員300人以下）", "従業員・一人事業主も加入可", "運営費の一部を県・市町が負担（公益財団法人佐賀県産業振興機構が運営）"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="nagasaki", category="融資",
        program_name="長崎県中小企業向け制度融資",
        url="https://www.pref.nagasaki.jp/bunrui/shigoto-sangyo/chushokigyoshien-kinyu/",
        kicker="制度融資 ｜ 長崎県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="8,000万円（長期）別枠設備1億円",
        rate_label="固定 年1.95%以内（長期）（融資期間:10年以内（据置2年））",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="nagasaki", category="補助金",
        program_name="事業承継促進・後継者事業展開支援補助金",
        url="https://www.pref.nagasaki.jp/bunrui/shigoto-sangyo/chushokigyoshien-kinyu/",
        kicker="事業承継 ｜ 県内事業者向け",
        purpose=["事業承継"],
        amount_label="要確認（公式要領で確認）",
        rate_label="要確認（公式要領で確認）",
        deadline="2026-09-30", deadline_label="2026年9月30日（当日消印有効）",
        eligibility=["長崎県内の事業者", "廃業抑制・事業承継に取り組んでいる", "承継後の事業展開計画がある"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="kumamoto", category="融資",
        program_name="熊本県中小企業向け融資制度",
        url="https://www.pref.kumamoto.jp/soshiki/61/50733.html",
        kicker="制度融資 ｜ 熊本県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="5,000万円（うち運転2,500万円）組合1億円",
        rate_label="固定・低金利（一般枠は特例枠より概ね0.2%高め）（融資期間:運転1〜5年・設備1〜10年）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="kumamoto", category="補助金",
        program_name="事業承継・後継ぎ支援事業補助金（2次公募）",
        url="https://www.pref.kumamoto.jp/soshiki/61/231111.html",
        kicker="事業承継 ｜ 県内中小企業向け",
        purpose=["事業承継"],
        amount_label="上限50万円（準備枠）／100万円（後継ぎ応援枠）",
        rate_label="2/3",
        deadline="2026-11-30", deadline_label="2026年11月30日17時必着",
        eligibility=["熊本県内の中小企業", "事業承継の準備、または承継後間もない後継者である", "設備投資・販路開拓等の計画がある（後継ぎ応援枠）"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="oita", category="融資",
        program_name="大分県中小企業活性化資金（一般融資）",
        url="https://www.pref.oita.jp/soshiki/14040/seidosikin-gaiyo.html",
        kicker="制度融資 ｜ 大分県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="8,000万円",
        rate_label="7年以内 年1.8%・10年以内 年2.0%（保証料 年0.75%以内）（融資期間:10年以内（据置1年以内））",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="oita", category="補助金",
        program_name="新価値創出支援補助金（おおいたクリエイティブ活用促進事業）",
        url="https://j-net21.smrj.go.jp/snavi2/articles/184817",
        kicker="商品開発・販路開拓 ｜ 県内中小企業向け",
        purpose=["商品開発・海外展開"],
        amount_label="要確認（公式要領で確認）",
        rate_label="要確認（公式要領で確認）",
        deadline="2026-08-28", deadline_label="2026年8月28日17時必着",
        eligibility=["大分県内の中小企業", "クリエイティブ活用による商品・サービス創出を計画", "マッチングイベントへの参加実績がある"],
        confirmed=False,
    ),
    PrefProgramConfig(
        pref="miyazaki", category="融資",
        program_name="宮崎県中小企業融資制度（経営安定貸付）",
        url="https://www.pref.miyazaki.lg.jp/keieikinyushien/shigoto/chushokigyo/20200329144235.html",
        kicker="制度融資 ｜ 宮崎県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認",
        rate_label="固定・期間段階制:1年以下1.5%／3年以下1.7%／5年以下1.9%／7年以下2.1%／10年以下2.3%（融資期間:設備10年以内・運転7年以内）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="kagoshima", category="融資",
        program_name="鹿児島県中小企業融資制度（新規開業応援資金等）",
        url="http://www.pref.kagoshima.jp/af02/sangyo-rodo/syoko/yushi/yuushi/index.html",
        kicker="制度融資 ｜ 鹿児島県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="要確認（創業応援 運転・設備2,000万円等）",
        rate_label="例）新規開業応援 1年以内1.85%〜10年以内2.45%（変動）（融資期間:最長10年程度）",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="kagoshima", category="補助金",
        program_name="かごしま中小企業DX推進事業費補助金（2次募集）",
        url="https://www.pref.kagoshima.jp/af22/sangyo-rodo/2026_dx_hojokin.html",
        kicker="DX・AI導入 ｜ 県内中小企業向け",
        purpose=["DX・AI"],
        amount_label="上限400万円",
        rate_label="2/3",
        deadline="2026-08-19", deadline_label="2026年8月19日",
        eligibility=["鹿児島県内の中小企業", "デジタル技術導入による生産性向上・省力化を計画", "社内デジタル人材育成の取組も対象"],
        confirmed=True,
    ),
    PrefProgramConfig(
        pref="okinawa", category="融資",
        program_name="沖縄県融資制度（小規模企業対策資金・成長促進支援資金等）",
        url="https://www.pref.okinawa.jp/shigoto/shien/1010056/1022724/1025148/1010102.html",
        kicker="制度融資 ｜ 沖縄県内の中小企業向け",
        purpose=["設備投資"],
        amount_label="例）創業者支援2,000万円、賃上げ支援3,000万円",
        rate_label="例）小規模企業対策資金 通常2.20%・優遇1.95%（融資期間:運転7年・設備10年以内（据置1年以内））",
        deadline="2099-01-01", deadline_label="随時受付中（通年・信用保証協会の保証が必要）",
        eligibility=["県内中小企業者", "県・金融機関・信用保証協会の三者協調融資", "資金使途:運転資金・設備資金"],
        confirmed=True,
    ),
]


# ---------------------------------------------------------------------------
# ページ取得・汎用抽出ロジック
#
# 47都道府県のサイトは構造がバラバラで、個別にパーサーを書くのは非常に
# 工数がかかる。そのため「各県専用のパーサー」ではなく、実際のページ本文
# テキストに対して汎用のキーワード・正規表現を当てる方式にしている。
# ヒットすれば自動更新、ヒットしなければ PREF_PROGRAM_CONFIG の値を使う。
# ---------------------------------------------------------------------------

AMOUNT_RE = re.compile(
    r"(?:融資)?限度額[はの]?\s*[:：]?\s*([0-9０-９][0-9０-９,，]*)\s*(億円|万円)"
)
SUBSIDY_AMOUNT_RE = re.compile(
    r"(?:補助)?上限(?:額)?[はの]?\s*[:：]?\s*([0-9０-９][0-9０-９,，]*)\s*(億円|万円)"
)
LOAN_RATE_RE = re.compile(
    r"(?:融資)?利率[はの]?\s*[:：]?\s*年?\s*([0-9０-９]+(?:\.[0-9０-９]+)?)\s*[%％]"
)
SUBSIDY_RATE_FRACTION_RE = re.compile(r"補助率[はの]?\s*[:：]?\s*([0-9０-９]+)\s*/\s*([0-9０-９]+)")


def _to_halfwidth(s: str) -> str:
    return s.translate(str.maketrans("０１２３４５６７８９，", "0123456789,"))


def fetch_page_text(url: str) -> Optional[str]:
    """URLにアクセスして本文テキストを取得する。失敗時は None を返す。"""
    try:
        res = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()
    except requests.RequestException:
        return None
    soup = BeautifulSoup(res.text, "html.parser")
    return " ".join(soup.get_text(separator=" ", strip=True).split())


def try_extract_amount(text: str, category: str) -> Optional[str]:
    pattern = AMOUNT_RE if category == "融資" else SUBSIDY_AMOUNT_RE
    m = pattern.search(text)
    if not m:
        return None
    number = _to_halfwidth(m.group(1))
    unit = m.group(2)
    return f"{number}{unit}"


def try_extract_rate(text: str, category: str) -> Optional[str]:
    if category == "融資":
        m = LOAN_RATE_RE.search(text)
        if not m:
            return None
        return f"年{_to_halfwidth(m.group(1))}%"
    if category == "補助金":
        m = SUBSIDY_RATE_FRACTION_RE.search(text)
        if not m:
            return None
        return f"補助率 {_to_halfwidth(m.group(1))}/{_to_halfwidth(m.group(2))}"
    return None


REIWA_DATE = r"令和\d+年\s*\d{1,2}月\s*\d{1,2}日"
# ページ本文には催事日・更新日など締切と無関係な日付も多数出てくるため、
# 「締切」「必着」「まで」等のキーワードのすぐ近くにある日付だけを締切候補として扱う。
DEADLINE_NEAR_KEYWORD_RE = re.compile(
    rf"(?:(締切|締め切り|受付期限|申請期限)[^。]{{0,15}}({REIWA_DATE}))"
    rf"|(?:({REIWA_DATE})[^。]{{0,15}}(必着|締切|まで))"
)


def try_extract_deadline(text: str):
    """
    「締切は令和8年8月25日」のように、締切を示すキーワードのすぐ近くにある
    和暦日付だけを締切候補として拾う。見つからなければ (None, None) を返す。
    """
    m = DEADLINE_NEAR_KEYWORD_RE.search(text)
    if not m:
        return None, None
    date_text = m.group(2) or m.group(3)
    deadline = parse_deadline(date_text)
    if deadline is None:
        return None, None
    return deadline, date_text


def build_program(cfg: PrefProgramConfig, page_text: Optional[str]) -> Program:
    pref_ja = PREFECTURES_JA[cfg.pref]
    today = datetime.now().strftime("%Y-%m-%d")

    amount_label = cfg.amount_label
    rate_label = cfg.rate_label
    deadline = cfg.deadline
    deadline_label = cfg.deadline_label
    auto_updated = False

    # 自動抽出はあくまで「要確認」のままになっている項目を埋めるためのもの。
    # 既に人手で確認済みの値（"要確認"を含まない）は、汎用正規表現が
    # ページ内の無関係な数字に誤ってマッチするリスクがあるため上書きしない。
    if page_text:
        if "要確認" in amount_label:
            auto_amount = try_extract_amount(page_text, cfg.category)
            if auto_amount:
                amount_label = auto_amount
                auto_updated = True

        if "要確認" in rate_label:
            auto_rate = try_extract_rate(page_text, cfg.category)
            if auto_rate:
                rate_label = auto_rate
                auto_updated = True

        # 締切の自動更新は、募集期間が動く補助金かつ「終了日は要確認」の
        # ものだけを対象にする（融資は基本「随時受付」で対象外。
        # 既に具体的な締切日が判明している補助金も、ページ内の無関係な
        # 日付を誤って拾うリスクがあるため上書きしない）。
        if cfg.category == "補助金" and "要確認" in deadline_label:
            auto_deadline, auto_deadline_label = try_extract_deadline(page_text)
            if auto_deadline:
                deadline = auto_deadline
                deadline_label = auto_deadline_label
                auto_updated = True

    # 共済（勤労者福祉共済会等）は県が運営主体ではなく関与する形が多いため
    # ラベルを分けている。融資・補助金は県独自の制度として扱う。
    scope_label = f"都道府県{'関与' if cfg.category == '共済' else '独自'}（{pref_ja}）"

    return Program(
        title=cfg.program_name,
        category=cfg.category,
        kicker=cfg.kicker,
        scale=DEFAULT_SCALE,
        purpose=cfg.purpose,
        scope="prefecture",
        scope_label=scope_label,
        pref=cfg.pref,
        amount_label=amount_label,
        rate_label=rate_label,
        deadline=deadline,
        deadline_label=deadline_label,
        eligibility=cfg.eligibility,
        url=cfg.url,
        source_checked_at=today,
    ), (cfg.confirmed or auto_updated)


def fetch_prefecture_programs() -> List[Program]:
    """
    PREF_PROGRAM_CONFIG の各URLに実際にアクセスし、取得できたページ本文から
    自動抽出を試みる。同じURLを複数の制度が参照している場合は1回だけ取得する。
    個別のURLへのアクセスに失敗しても、その1件が config のフォールバック値に
    なるだけで、全体の処理は止めない。
    """
    page_cache: Dict[str, Optional[str]] = {}
    programs: List[Program] = []

    for cfg in PREF_PROGRAM_CONFIG:
        if cfg.url not in page_cache:
            page_cache[cfg.url] = fetch_page_text(cfg.url)
        program, _confirmed = build_program(cfg, page_cache[cfg.url])
        programs.append(program)

    return programs


if __name__ == "__main__":
    page_cache: Dict[str, Optional[str]] = {}
    for cfg in PREF_PROGRAM_CONFIG:
        if cfg.url not in page_cache:
            page_cache[cfg.url] = fetch_page_text(cfg.url)
        program, confirmed = build_program(cfg, page_cache[cfg.url])
        mark = "確定" if confirmed else "要確認"
        print(f"[{mark}] {program.title}")
