const state = {
  activeView: "risk",
  queryMode: "text",
  queryFile: null,
  caseFile: null,
  riskResult: null,
  riskFilter: "all",
  casePage: 1,
  casePageSize: 12,
  caseResult: null,
};

const sceneLabels = {
  ST1_poster_sms_social: "海报 / 短信 / 社交平台文案",
  ST2_live_short_video: "直播 / 短视频 / 口播",
  ST3_product_intro_detail: "产品介绍 / 详情页",
  ST4_meeting_material: "产品说明会 / 客户活动材料",
  ST5_training_telemarketing_callback: "培训 / 电销 / 回访话术",
  ST6_penalty_backend_fact: "监管处罚 / 后台业务事实",
};

const levelLabels = {
  high: "高风险",
  medium: "中风险",
  review: "需复核",
  low: "低风险",
  none: "未见明显风险",
};

const el = (selector) => document.querySelector(selector);

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.view));
});
document.querySelectorAll("[data-route]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    switchView(link.dataset.route);
  });
});
document.querySelectorAll("[data-query-mode]").forEach((button) => {
  button.addEventListener("click", () => switchQueryMode(button.dataset.queryMode));
});

setupDropZone("#query-drop-zone", "#query-file", (file) => {
  state.queryFile = file;
  el("#query-file-name").textContent = fileLabel(file);
});
setupDropZone("#case-drop-zone", "#case-file", (file) => {
  state.caseFile = file;
  el("#case-file-name").textContent = fileLabel(file);
});

el("#query-text").addEventListener("input", (event) => {
  el("#query-count").textContent = event.target.value.length.toLocaleString("zh-CN");
});
el("#analyze-button").addEventListener("click", analyzeQuery);
el("#copy-risk-result").addEventListener("click", copyRiskResult);
el("#risk-filter").addEventListener("change", (event) => {
  state.riskFilter = event.target.value;
  renderRiskSentences();
});
el("#risk-list").addEventListener("click", handleCaseLink);
el("#ingest-button").addEventListener("click", ingestCase);
el("#case-filters").addEventListener("submit", (event) => {
  event.preventDefault();
  state.casePage = 1;
  loadCases();
});
el("#refresh-cases").addEventListener("click", () => loadCases());
el("#case-list").addEventListener("click", handleCaseListClick);
el("#case-pagination").addEventListener("click", handlePagination);
el("#drawer-close").addEventListener("click", closeDrawer);
el("#drawer-backdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeDrawer();
});

loadHealth();

function switchView(view) {
  state.activeView = view;
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((panel) => panel.classList.remove("is-visible"));
  el(`#${view}-view`)?.classList.add("is-visible");
  if (view === "cases") {
    loadStatistics();
    loadCases();
  }
  window.location.hash = view;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function switchQueryMode(mode) {
  state.queryMode = mode;
  document.querySelectorAll("[data-query-mode]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.queryMode === mode);
  });
  el("#query-text-panel").classList.toggle("is-visible", mode === "text");
  el("#query-file-panel").classList.toggle("is-visible", mode === "file");
  showFormError("#query-error", "");
}

function setupDropZone(zoneSelector, inputSelector, onSelect) {
  const zone = el(zoneSelector);
  const input = el(inputSelector);
  input.addEventListener("change", () => onSelect(input.files?.[0] ?? null));
  ["dragenter", "dragover"].forEach((name) => {
    zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.add("is-dragging");
    });
  });
  ["dragleave", "drop"].forEach((name) => {
    zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.remove("is-dragging");
    });
  });
  zone.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0] ?? null;
    if (file) onSelect(file);
  });
}

async function loadHealth() {
  try {
    const data = await api("/api/health");
    el("#health-state").classList.add("is-ready");
    const model = data.llm_model ? ` · ${data.llm_model}` : " · 规则降级模式";
    el("#health-text").textContent = `${data.active_case_count.toLocaleString("zh-CN")} 条启用案例${model}`;
  } catch (error) {
    el("#health-state").classList.add("is-error");
    el("#health-text").textContent = "本地服务连接失败";
  }
}

async function analyzeQuery() {
  showFormError("#query-error", "");
  let path;
  let options;
  if (state.queryMode === "text") {
    const text = el("#query-text").value.trim();
    if (!text) return showFormError("#query-error", "请输入需要审查的文字。");
    path = "/api/query/analyze/text";
    options = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    };
  } else {
    if (!state.queryFile) return showFormError("#query-error", "请先选择 Query 文件。");
    const form = new FormData();
    form.append("file", state.queryFile);
    path = "/api/query/analyze/file";
    options = { method: "POST", body: form };
  }
  setBusy("#analyze-button", true);
  try {
    state.riskResult = await api(path, options);
    renderRiskResult();
  } catch (error) {
    showFormError("#query-error", error.message);
  } finally {
    setBusy("#analyze-button", false);
  }
}

function renderRiskResult() {
  const result = state.riskResult;
  const summary = result.risk_summary;
  el("#risk-empty").hidden = true;
  el("#risk-content").hidden = false;
  el("#risk-summary").innerHTML = `
    <article class="level-card level-${escapeHtml(summary.overall_level)}">
      <span>整体风险</span><strong>${escapeHtml(summary.overall_level_name)}</strong>
      <small>${escapeHtml(summary.action)}</small>
    </article>
    <article><span>最高分数</span><strong>${formatPercent(summary.overall_score)}</strong><small>按最高风险语句汇总</small></article>
    <article><span>风险语句</span><strong>${summary.risky_sentence_count} / ${summary.sentence_count}</strong><small>${escapeHtml(summary.risk_labels.join(" · ") || "暂无风险标签")}</small></article>
    <article><span>判断方式</span><strong>${summary.llm_used ? "融合判断" : "降级判断"}</strong><small>${escapeHtml(summary.llm_model || "规则 + 案例 BM25")}</small></article>
  `;
  el("#risk-warnings").innerHTML = summary.warnings
    .map((warning) => `<p>提示：${escapeHtml(warning)}</p>`)
    .join("");
  const classification = result.classification;
  el("#classification-note").textContent = `${sceneLabels[classification.scene] || classification.scene} · ${formatPercent(classification.confidence)} · ${classification.method === "llm" ? "大模型复核分类" : "规则分类"}`;
  renderRiskSentences();
  el("#risk-results").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderRiskSentences() {
  if (!state.riskResult) return;
  let assessments = state.riskResult.risk_assessments;
  if (state.riskFilter === "risky") {
    assessments = assessments.filter((item) => item.risk_score >= 0.2);
  }
  if (!assessments.length) {
    el("#risk-list").innerHTML = '<div class="inline-empty">当前筛选下没有风险语句。</div>';
    return;
  }
  el("#risk-list").innerHTML = assessments.map((item, index) => {
    const tags = item.risk_labels.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("");
    const evidence = item.evidence.map((value) => `<li>${escapeHtml(value.description)}</li>`).join("");
    const matches = item.matched_cases.map((matched) => `
      <button class="matched-case" type="button" data-case-id="${escapeHtml(matched.case_id)}">
        <span><b>${escapeHtml(matched.case_id)}</b><em>${formatPercent(matched.score)} 匹配</em></span>
        <strong>${escapeHtml(matched.case_title || matched.violation_behavior.slice(0, 72))}</strong>
        <small>${escapeHtml(matched.risk_tags.join(" · ") || "未标注")}</small>
      </button>
    `).join("");
    return `
      <article class="risk-card level-${escapeHtml(item.risk_level)}">
        <div class="risk-index">${String(index + 1).padStart(2, "0")}</div>
        <div class="risk-body">
          <div class="risk-card-head">
            <div><span class="level-badge">${escapeHtml(item.risk_level_name)}</span>${tags}</div>
            <strong>${formatPercent(item.risk_score)}</strong>
          </div>
          <p class="risk-text">${escapeHtml(item.text)}</p>
          <p class="reasoning">${escapeHtml(item.reasoning)}</p>
          <details>
            <summary>查看判断依据与 ${item.matched_cases.length} 条相似案例</summary>
            <div class="evidence-grid">
              <div><h4>判断依据</h4><ul>${evidence || "<li>无额外证据</li>"}</ul></div>
              <div><h4>相似案例</h4><div class="matched-list">${matches || '<p class="muted">未找到相似案例。</p>'}</div></div>
            </div>
          </details>
        </div>
      </article>
    `;
  }).join("");
}

async function copyRiskResult() {
  if (!state.riskResult) return;
  const summary = state.riskResult.risk_summary;
  const lines = [
    `整体风险：${summary.overall_level_name}（${formatPercent(summary.overall_score)}）`,
    `风险标签：${summary.risk_labels.join("、") || "无"}`,
    `建议动作：${summary.action}`,
    "",
    ...state.riskResult.risk_assessments.map((item, index) =>
      `${index + 1}. [${item.risk_level_name} ${formatPercent(item.risk_score)}] ${item.text}\n   ${item.reasoning}`
    ),
  ];
  await navigator.clipboard.writeText(lines.join("\n"));
  toast("结果摘要已复制");
}

async function ingestCase() {
  showFormError("#case-error", "");
  if (!state.caseFile) return showFormError("#case-error", "请先选择案例原始文件。");
  const form = new FormData();
  form.append("file", state.caseFile);
  setBusy("#ingest-button", true);
  try {
    const result = await api("/api/cases/upload", { method: "POST", body: form });
    renderIngestionResult(result);
    state.caseFile = null;
    el("#case-file").value = "";
    el("#case-file-name").textContent = "尚未选择文件";
    await loadHealth();
  } catch (error) {
    showFormError("#case-error", error.message);
  } finally {
    setBusy("#ingest-button", false);
  }
}

function renderIngestionResult(result) {
  const record = result.case;
  const warnings = result.warnings.map((value) => `<li>${escapeHtml(value)}</li>`).join("");
  const container = el("#ingestion-result");
  container.hidden = false;
  container.innerHTML = `
    <div class="success-mark">✓</div>
    <div class="ingestion-copy">
      <p class="kicker">INGESTION COMPLETE</p>
      <h2>${escapeHtml(record.case_title || record.case_id)}</h2>
      <p>${escapeHtml(record.violation_behavior || "案例已完成结构化录入。")}</p>
      <div class="tag-row">${record.risk_tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
      <small>案例编号 ${escapeHtml(record.case_id)} · ${result.llm_used ? "DeepSeek 结构化" : "规则降级结构化"} · ${escapeHtml(result.extraction_method)}</small>
      ${warnings ? `<ul class="warning-items">${warnings}</ul>` : ""}
      <button class="quiet-button" type="button" data-open-ingested="${escapeHtml(record.case_id)}">查看案例详情</button>
    </div>
  `;
  container.querySelector("[data-open-ingested]").addEventListener("click", () => openCase(record.case_id));
  container.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function loadStatistics() {
  try {
    const value = await api("/api/cases/statistics");
    const items = [value.total_cases, value.active_cases, value.user_cases, value.risk_tag_count];
    el("#case-stats").querySelectorAll("strong").forEach((node, index) => {
      node.textContent = items[index].toLocaleString("zh-CN");
    });
  } catch (error) {
    toast(`统计读取失败：${error.message}`);
  }
}

async function loadCases() {
  const params = new URLSearchParams({
    page: String(state.casePage),
    page_size: String(state.casePageSize),
  });
  const filters = {
    q: el("#case-search").value.trim(),
    risk_tag: el("#case-risk-tag").value.trim(),
    retrieval_status: el("#case-status").value,
    origin: el("#case-origin").value,
  };
  Object.entries(filters).forEach(([key, value]) => value && params.set(key, value));
  el("#case-list").innerHTML = '<div class="inline-empty">正在读取案例……</div>';
  try {
    state.caseResult = await api(`/api/cases?${params}`);
    renderCaseList();
  } catch (error) {
    el("#case-list").innerHTML = `<div class="inline-empty error">${escapeHtml(error.message)}</div>`;
  }
}

function renderCaseList() {
  const result = state.caseResult;
  el("#case-count-label").textContent = `共 ${result.total.toLocaleString("zh-CN")} 条 · 第 ${result.page} / ${Math.max(result.total_pages, 1)} 页`;
  if (!result.items.length) {
    el("#case-list").innerHTML = '<div class="inline-empty">没有符合条件的案例。</div>';
  } else {
    el("#case-list").innerHTML = result.items.map((item) => `
      <article class="case-row ${item.retrieval_status === "inactive" ? "is-inactive" : ""}">
        <button class="case-main" type="button" data-open-case="${escapeHtml(item.case_id)}">
          <span class="case-id">${escapeHtml(item.case_id)}</span>
          <span class="case-title">${escapeHtml(item.case_title || item.penalty_doc_no || "未命名案例")}</span>
          <span class="case-fact">${escapeHtml(item.violation_behavior || "暂无违法事实摘要")}</span>
          <span class="tag-row">${item.risk_tags.slice(0, 4).map((tag) => `<i>${escapeHtml(tag)}</i>`).join("")}</span>
        </button>
        <div class="case-meta">
          <span>${escapeHtml(item.regulator || "监管机构未记录")}</span>
          <span>${formatDate(item.penalty_date)}</span>
          <span class="origin-chip">${item.is_user_managed ? "Web 新增" : "原批次"}</span>
          <span class="status-chip ${escapeHtml(item.retrieval_status)}">${item.retrieval_status === "active" ? "启用" : "已停用"}</span>
        </div>
      </article>
    `).join("");
  }
  renderPagination(result);
}

function renderPagination(result) {
  if (result.total_pages <= 1) {
    el("#case-pagination").replaceChildren();
    return;
  }
  const pages = new Set([1, result.total_pages, result.page - 1, result.page, result.page + 1]);
  const valid = [...pages].filter((page) => page >= 1 && page <= result.total_pages).sort((a, b) => a - b);
  let previous = 0;
  const parts = [];
  valid.forEach((page) => {
    if (page - previous > 1) parts.push("<span>…</span>");
    parts.push(`<button type="button" data-page="${page}" class="${page === result.page ? "is-active" : ""}">${page}</button>`);
    previous = page;
  });
  el("#case-pagination").innerHTML = parts.join("");
}

function handleCaseListClick(event) {
  const button = event.target.closest("[data-open-case]");
  if (button) openCase(button.dataset.openCase);
}

function handleCaseLink(event) {
  const button = event.target.closest("[data-case-id]");
  if (button) openCase(button.dataset.caseId);
}

function handlePagination(event) {
  const button = event.target.closest("[data-page]");
  if (!button) return;
  state.casePage = Number(button.dataset.page);
  loadCases();
  el("#cases-view").scrollIntoView({ behavior: "smooth" });
}

async function openCase(caseId) {
  el("#case-detail").innerHTML = '<div class="inline-empty">正在读取案例详情……</div>';
  el("#drawer-backdrop").hidden = false;
  el("#case-drawer").classList.add("is-open");
  el("#case-drawer").setAttribute("aria-hidden", "false");
  document.body.classList.add("drawer-open");
  try {
    const item = await api(`/api/cases/${encodeURIComponent(caseId)}`);
    renderCaseDetail(item);
  } catch (error) {
    el("#case-detail").innerHTML = `<div class="inline-empty error">${escapeHtml(error.message)}</div>`;
  }
}

function renderCaseDetail(item) {
  const evidence = item.evidence_chunks.slice(0, 12).map((chunk) => `
    <article><span>${escapeHtml(chunk.chunk_type)}${chunk.is_verbatim ? " · 原文" : ""}</span><p>${escapeHtml(chunk.chunk_text)}</p></article>
  `).join("");
  el("#case-detail").innerHTML = `
    <p class="kicker">CASE DETAIL</p>
    <span class="drawer-case-id">${escapeHtml(item.case_id)}</span>
    <h2>${escapeHtml(item.case_title || item.penalty_doc_no || "未命名案例")}</h2>
    <div class="tag-row">${item.risk_tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
    <dl class="case-fields">
      <div><dt>当事人</dt><dd>${escapeHtml(item.party_name || "—")}</dd></div>
      <div><dt>处罚文号</dt><dd>${escapeHtml(item.penalty_doc_no || "—")}</dd></div>
      <div><dt>处罚机关</dt><dd>${escapeHtml(item.regulator || "—")}</dd></div>
      <div><dt>处罚日期</dt><dd>${formatDate(item.penalty_date)}</dd></div>
      <div><dt>数据来源</dt><dd>${item.is_user_managed ? "Web 增量录入" : "原批次构建"}</dd></div>
      <div><dt>检索状态</dt><dd>${item.retrieval_status === "active" ? "启用" : "已停用"}</dd></div>
    </dl>
    <section class="detail-section"><h3>违法事实</h3><p>${escapeHtml(item.violation_behavior || "—")}</p></section>
    <section class="detail-section"><h3>处罚内容</h3><p>${escapeHtml(item.penalty_content || "—")}</p></section>
    ${item.case_summary ? `<section class="detail-section"><h3>案例摘要</h3><p>${escapeHtml(item.case_summary)}</p></section>` : ""}
    <section class="detail-section"><h3>证据切片 <small>${item.evidence_chunks.length}</small></h3><div class="evidence-list">${evidence || '<p class="muted">暂无证据切片。</p>'}</div></section>
    <div class="drawer-actions">
      <button class="${item.retrieval_status === "active" ? "danger-button" : "primary-button"}" id="toggle-case-status" type="button">
        ${item.retrieval_status === "active" ? "停用案例" : "恢复案例"}
      </button>
      <small>${item.retrieval_status === "active" ? "停用后不再参与检索，但数据和原文仍保留。" : "恢复后将重新参与 Query 案例匹配。"}</small>
    </div>
  `;
  el("#toggle-case-status").addEventListener("click", () => toggleCaseStatus(item));
}

async function toggleCaseStatus(item) {
  const active = item.retrieval_status !== "active";
  if (!active && !window.confirm("确认停用该案例？记录和原始文件会保留，可随时恢复。")) return;
  setBusy("#toggle-case-status", true);
  try {
    const updated = await api(`/api/cases/${encodeURIComponent(item.case_id)}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active }),
    });
    renderCaseDetail(updated);
    toast(active ? "案例已恢复" : "案例已停用，可随时恢复");
    if (state.activeView === "cases") {
      await Promise.all([loadStatistics(), loadCases()]);
    }
  } catch (error) {
    toast(error.message);
  }
}

function closeDrawer() {
  el("#case-drawer").classList.remove("is-open");
  el("#case-drawer").setAttribute("aria-hidden", "true");
  el("#drawer-backdrop").hidden = true;
  document.body.classList.remove("drawer-open");
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let payload;
  try {
    payload = await response.json();
  } catch (error) {
    throw new Error(`服务返回了无法解析的响应（HTTP ${response.status}）`);
  }
  if (!response.ok) throw new Error(readApiError(payload));
  return payload;
}

function readApiError(payload) {
  if (typeof payload?.detail === "string") return payload.detail;
  if (Array.isArray(payload?.detail)) {
    return payload.detail.map((item) => item.msg || "字段校验失败").join("；");
  }
  return "请求失败，请查看服务日志。";
}

function setBusy(selector, busy) {
  const button = el(selector);
  if (!button) return;
  button.disabled = busy;
  button.classList.toggle("is-loading", busy);
}

function showFormError(selector, message) {
  el(selector).textContent = message;
}

function toast(message) {
  const node = el("#toast");
  node.textContent = message;
  node.classList.add("is-visible");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => node.classList.remove("is-visible"), 2800);
}

function fileLabel(file) {
  return file ? `${file.name} · ${formatFileSize(file.size)}` : "尚未选择文件";
}

function formatFileSize(size) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function formatPercent(value) {
  return `${Math.round(Number(value) * 100)}%`;
}

function formatDate(value) {
  return value ? new Intl.DateTimeFormat("zh-CN").format(new Date(`${value}T00:00:00`)) : "—";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const initialView = window.location.hash.slice(1);
if (["risk", "case-entry", "cases"].includes(initialView)) switchView(initialView);
