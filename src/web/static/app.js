const state = {
  inputMode: "file",
  selectedFile: null,
  result: null,
};

const categoryLabels = {
  marketing_content: "营销宣传材料",
  formal_document: "正式业务文件",
  customer_communication: "客户沟通话术",
  unknown_or_mixed: "未知或混合",
};

const methodLabels = {
  rule: "规则分类",
  model: "轻量模型分类",
  hybrid: "规则 + 轻量模型",
  abstained: "低置信度回退",
};

const elements = {
  analyzeButton: document.querySelector("#analyze-button"),
  candidateList: document.querySelector("#candidate-list"),
  classifierMode: document.querySelector("#classifier-mode"),
  copyResult: document.querySelector("#copy-result"),
  dropZone: document.querySelector("#drop-zone"),
  emptyResults: document.querySelector("#empty-results"),
  evidenceList: document.querySelector("#evidence-list"),
  fileInput: document.querySelector("#query-file"),
  filePanel: document.querySelector("#file-panel"),
  formError: document.querySelector("#form-error"),
  resultCategory: document.querySelector("#result-category"),
  resultCategoryCode: document.querySelector("#result-category-code"),
  resultConfidence: document.querySelector("#result-confidence"),
  resultMethod: document.querySelector("#result-method"),
  resultSentenceCount: document.querySelector("#result-sentence-count"),
  resultsContent: document.querySelector("#results-content"),
  selectedFile: document.querySelector("#selected-file"),
  sentenceList: document.querySelector("#sentence-list"),
  textCount: document.querySelector("#text-count"),
  textInput: document.querySelector("#query-text"),
  textPanel: document.querySelector("#text-panel"),
  toast: document.querySelector("#toast"),
};

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.view));
});

document.querySelectorAll("[data-input-mode]").forEach((button) => {
  button.addEventListener("click", () => switchInputMode(button.dataset.inputMode));
});

elements.fileInput.addEventListener("change", () => {
  setSelectedFile(elements.fileInput.files?.[0] ?? null);
});

["dragenter", "dragover"].forEach((eventName) => {
  elements.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.dropZone.classList.add("is-dragging");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  elements.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.dropZone.classList.remove("is-dragging");
  });
});

elements.dropZone.addEventListener("drop", (event) => {
  const file = event.dataTransfer?.files?.[0] ?? null;
  if (file) {
    setSelectedFile(file);
  }
});

elements.textInput.addEventListener("input", () => {
  elements.textCount.textContent = elements.textInput.value.length.toLocaleString("zh-CN");
});

elements.analyzeButton.addEventListener("click", analyzeQuery);
elements.copyResult.addEventListener("click", copyEnhancedResult);

loadClassifierStatus();

function switchView(viewName) {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === viewName);
  });
  document.querySelectorAll(".view-panel").forEach((panel) => {
    panel.classList.remove("is-visible");
  });
  document.querySelector(`#${viewName}-view`)?.classList.add("is-visible");
}

function switchInputMode(mode) {
  state.inputMode = mode;
  document.querySelectorAll("[data-input-mode]").forEach((button) => {
    const isActive = button.dataset.inputMode === mode;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  });
  elements.filePanel.classList.toggle("is-visible", mode === "file");
  elements.textPanel.classList.toggle("is-visible", mode === "text");
  clearError();
}

function setSelectedFile(file) {
  state.selectedFile = file;
  elements.selectedFile.textContent = file
    ? `${file.name} · ${formatFileSize(file.size)}`
    : "尚未选择文件";
  clearError();
}

async function analyzeQuery() {
  clearError();
  let request;

  if (state.inputMode === "file") {
    if (!state.selectedFile) {
      showError("请先选择一个 Query 文件。");
      return;
    }
    const formData = new FormData();
    formData.append("file", state.selectedFile);
    request = fetch("/api/query/analyze/file", {
      method: "POST",
      body: formData,
    });
  } else {
    const text = elements.textInput.value.trim();
    if (!text) {
      showError("请输入需要分类和切分的文字。");
      return;
    }
    request = fetch("/api/query/analyze/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, metadata: { source_channel: "web_text" } }),
    });
  }

  setLoading(true);
  try {
    const response = await request;
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(readApiError(payload));
    }
    state.result = payload;
    renderResult(payload);
  } catch (error) {
    showError(error instanceof Error ? error.message : "处理失败，请稍后重试。");
  } finally {
    setLoading(false);
  }
}

function renderResult(result) {
  const classification = result.classification;
  const selected = classification.selected_category;
  elements.emptyResults.hidden = true;
  elements.resultsContent.hidden = false;
  elements.resultCategory.textContent =
    categoryLabels[selected.category_code] ?? selected.category_name;
  elements.resultCategoryCode.textContent = selected.category_code;
  elements.resultConfidence.textContent = formatPercent(selected.probability);
  elements.resultMethod.textContent =
    methodLabels[classification.classification_method] ?? classification.classification_method;
  elements.resultSentenceCount.textContent = String(result.sentences.length).padStart(2, "0");

  renderCandidates(classification.candidates);
  renderEvidence(classification.classification_evidence, classification.is_abstained);
  renderSentences(result.sentences);
  elements.resultsContent.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderCandidates(candidates) {
  elements.candidateList.replaceChildren();
  candidates.forEach((candidate) => {
    const row = document.createElement("div");
    row.className = "candidate-row";

    const label = document.createElement("span");
    label.textContent = categoryLabels[candidate.category_code] ?? candidate.category_name;

    const track = document.createElement("div");
    track.className = "candidate-track";
    const fill = document.createElement("div");
    fill.className = "candidate-fill";
    fill.style.width = `${Math.round(candidate.probability * 100)}%`;
    track.append(fill);

    const probability = document.createElement("strong");
    probability.textContent = formatPercent(candidate.probability);
    row.append(label, track, probability);
    elements.candidateList.append(row);
  });
}

function renderEvidence(evidence, isAbstained) {
  elements.evidenceList.replaceChildren();
  const values =
    evidence.length > 0
      ? evidence
      : [
          isAbstained
            ? "没有足够强的场景证据，已回退为未知或混合。"
            : "当前结果主要由人工标注模型给出。",
        ];
  values.forEach((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    elements.evidenceList.append(item);
  });
}

function renderSentences(sentences) {
  elements.sentenceList.replaceChildren();
  sentences.forEach((sentence) => {
    const card = document.createElement("article");
    card.className = "sentence-card";

    const number = document.createElement("span");
    number.className = "sentence-number";
    number.textContent = String(sentence.sentence_index).padStart(2, "0");

    const main = document.createElement("div");
    main.className = "sentence-main";
    const text = document.createElement("p");
    text.textContent = sentence.text;
    const metadata = document.createElement("div");
    metadata.className = "sentence-meta";
    const chip = document.createElement("span");
    chip.className = "scene-chip";
    chip.textContent =
      categoryLabels[sentence.category.category_code] ?? sentence.category.category_name;
    const offset = document.createElement("span");
    offset.textContent = `全文位置 ${sentence.start_offset}–${sentence.end_offset}`;
    metadata.append(chip, offset);
    main.append(text, metadata);

    const riskPlaceholder = document.createElement("span");
    riskPlaceholder.className = "risk-placeholder";
    riskPlaceholder.textContent = "风险结果待接入";

    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "查看交给 Risk 的增强内容";
    const enhanced = document.createElement("pre");
    enhanced.textContent = sentence.enhanced_text;
    details.append(summary, enhanced);

    card.append(number, main, riskPlaceholder, details);
    elements.sentenceList.append(card);
  });
}

async function loadClassifierStatus() {
  try {
    const response = await fetch("/api/query/classifier");
    if (!response.ok) {
      throw new Error();
    }
    const payload = await response.json();
    const stateElement = elements.classifierMode.closest(".system-state");
    stateElement?.classList.add("is-ready");
    elements.classifierMode.textContent = payload.model_ready
      ? `混合分类器 · ${payload.training_example_count} 条人工标注`
      : "规则分类器 · 等待人工标注数据";
  } catch {
    elements.classifierMode.textContent = "分类器状态暂不可用";
  }
}

async function copyEnhancedResult() {
  if (!state.result) {
    return;
  }
  try {
    await navigator.clipboard.writeText(state.result.enhanced_text);
    showToast("已复制全部增强内容");
  } catch {
    showToast("浏览器未允许复制，请展开句子手动复制");
  }
}

function setLoading(isLoading) {
  elements.analyzeButton.disabled = isLoading;
  elements.analyzeButton.classList.toggle("is-loading", isLoading);
}

function showError(message) {
  elements.formError.textContent = message;
}

function clearError() {
  elements.formError.textContent = "";
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("is-visible");
  window.setTimeout(() => elements.toast.classList.remove("is-visible"), 2200);
}

function readApiError(payload) {
  if (typeof payload?.detail === "string") {
    return payload.detail;
  }
  if (Array.isArray(payload?.detail)) {
    return payload.detail.map((item) => item.msg).join("；");
  }
  return "处理失败，请检查输入内容。";
}

function formatPercent(value) {
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatFileSize(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
