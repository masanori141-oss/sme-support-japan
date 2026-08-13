/*
融資比較ページ共通ロジック。12ページ（総合台帳 + 融資分類11ページ）が
このファイル1つを共有する。各ページは <script> で PAGE_CATEGORY
（loan-data.js の loanCategory の値、総合台帳のみ 'all'）を定義してから
このファイルを読み込む。

表示ルール:
- PAGE_CATEGORY === 'all'（総合台帳）: rateMin が判明している商品のみを
  対象にする。政府系の補助金・共済は「利率」という概念を持たないため、
  総合台帳には含めない（融資商品どうしの比較に絞る）。
- それ以外（分類別ページ）: loanCategory が一致する商品をすべて対象に
  する。政府系補助金・融資カテゴリのページだけは、rateMin が無い
  補助金・共済もそのまま一覧に含まれる（rateLabel の原文で表示される）。
- 並び順は「下限金利が低い順」。rateMin が不明な商品は一覧の末尾に回す。
*/

const INSTITUTION_CATEGORY_ORDER = [
  "メガバンク", "信託銀行", "新興銀行", "政府系金融機関", "地方銀行", "消費者金融", "政府・地方公共団体",
];

const LOAN_CATEGORY_LABELS = {
  "card-loan": "カードローン",
  "education-loan": "教育ローン",
  "auto-loan": "自動車ローン",
  "reform-loan": "リフォームローン",
  "real-estate-loan": "不動産担保ローン",
  "mortgage": "住宅ローン",
  "investment-property-loan": "投資不動産ローン",
  "securities-loan": "証券担保ローン",
  "purpose-loan": "目的型ローン",
  "government": "政府系補助金・融資",
  "other-loan": "その他ローン",
};

let activeInstitutionCategories = new Set();
let rateMaxFilter = "all";
let limitMinFilter = "all";

function baseDataset() {
  if (typeof LOAN_DATA === "undefined") return [];
  if (PAGE_CATEGORY === "all") {
    return LOAN_DATA.filter((d) => d.rateMin !== null && d.rateMin !== undefined);
  }
  return LOAN_DATA.filter((d) => d.loanCategory === PAGE_CATEGORY);
}

function formatYen(yen) {
  if (yen === null || yen === undefined) return null;
  if (yen >= 100_000_000) {
    const oku = yen / 100_000_000;
    return `${Number.isInteger(oku) ? oku : oku.toFixed(1)}億円`;
  }
  return `${Math.round(yen / 10_000).toLocaleString()}万円`;
}

function renderInstitutionFilterChips() {
  const wrap = document.getElementById("inst-cat-chips");
  if (!wrap) return;
  const present = new Set(baseDataset().map((d) => d.institutionCategory));
  const cats = INSTITUTION_CATEGORY_ORDER.filter((c) => present.has(c));
  wrap.innerHTML = "";
  cats.forEach((cat) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip active";
    chip.textContent = cat;
    chip.dataset.cat = cat;
    chip.addEventListener("click", () => {
      if (activeInstitutionCategories.has(cat)) {
        activeInstitutionCategories.delete(cat);
        chip.classList.remove("active");
      } else {
        activeInstitutionCategories.add(cat);
        chip.classList.add("active");
      }
      render();
    });
    wrap.appendChild(chip);
    activeInstitutionCategories.add(cat);
  });
}

function applyFilters(list) {
  return list.filter((d) => {
    if (activeInstitutionCategories.size && !activeInstitutionCategories.has(d.institutionCategory)) return false;
    if (rateMaxFilter !== "all") {
      if (d.rateMin === null || d.rateMin === undefined) return false;
      if (d.rateMin > Number(rateMaxFilter)) return false;
    }
    if (limitMinFilter !== "all") {
      if (d.limitMaxYen === null || d.limitMaxYen === undefined) return false;
      if (d.limitMaxYen < Number(limitMinFilter)) return false;
    }
    return true;
  });
}

function sortByRate(list) {
  return [...list].sort((a, b) => {
    const am = a.rateMin === null || a.rateMin === undefined ? Infinity : a.rateMin;
    const bm = b.rateMin === null || b.rateMin === undefined ? Infinity : b.rateMin;
    return am - bm;
  });
}

function renderCard(d) {
  const rateText = d.rateMin !== null && d.rateMin !== undefined
    ? (d.rateMin === d.rateMax ? `年${d.rateMin}%（固定）` : `年${d.rateMin}%〜${d.rateMax}%`)
    : (d.rateLabel || "要確認");
  const limitText = formatYen(d.limitMaxYen) || d.limitLabel || "要確認";
  const catLabel = LOAN_CATEGORY_LABELS[d.loanCategory] || d.loanCategory;

  const card = document.createElement("article");
  card.className = "loan-card";
  card.innerHTML = `
    <div class="loan-body">
      <span class="inst-badge">${d.institutionCategory}</span>
      ${PAGE_CATEGORY === "all" || PAGE_CATEGORY === "government" ? `<span class="cat-badge">${catLabel}</span>` : ""}
      <div class="loan-inst">${d.institution}</div>
      <h2 class="loan-title">${d.productName}</h2>
      <div class="loan-features">
        ${(d.features || []).slice(0, 3).map((f) => `<div class="loan-feature"><span class="mark">✓</span>${f}</div>`).join("")}
      </div>
    </div>
    <div class="loan-figures">
      <div>
        <div class="figure-label">金利（実質年率）</div>
        <div class="figure-value rate">${rateText}</div>
      </div>
      <div>
        <div class="figure-label">ご利用限度額</div>
        <div class="figure-value">${limitText}</div>
      </div>
      <a class="detail-link" href="${d.url}" target="_blank" rel="noopener">公式サイトで詳細を見る →</a>
    </div>
  `;
  return card;
}

function render() {
  const list = sortByRate(applyFilters(baseDataset()));
  const container = document.getElementById("result-list");
  const countEl = document.getElementById("result-num");
  if (countEl) countEl.textContent = list.length;
  if (!container) return;
  container.innerHTML = "";
  if (list.length === 0) {
    container.innerHTML = '<div class="empty-state">条件に一致する商品が見つかりませんでした。絞り込み条件を減らして再度お試しください。</div>';
    return;
  }
  list.forEach((d) => container.appendChild(renderCard(d)));
}

function initFilterControls() {
  const rateSelect = document.getElementById("f-rate");
  const limitSelect = document.getElementById("f-limit");
  const resetBtn = document.getElementById("reset-btn");
  if (rateSelect) rateSelect.addEventListener("change", () => { rateMaxFilter = rateSelect.value; render(); });
  if (limitSelect) limitSelect.addEventListener("change", () => { limitMinFilter = limitSelect.value; render(); });
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      if (rateSelect) rateSelect.value = "all";
      if (limitSelect) limitSelect.value = "all";
      rateMaxFilter = "all";
      limitMinFilter = "all";
      document.querySelectorAll("#inst-cat-chips .chip").forEach((c) => {
        c.classList.add("active");
        activeInstitutionCategories.add(c.dataset.cat);
      });
      render();
    });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  renderInstitutionFilterChips();
  initFilterControls();
  render();
});
