/* Dated, source-bound evaluation results. All displayed text is escaped. */
(function (root) {
  "use strict";
  const escape = value => String(value ?? "—").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const pct = value => Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : "—";
  const fixed = value => Number.isFinite(value) ? value.toFixed(3) : "—";
  const seconds = value => Number.isFinite(value) ? `${value.toFixed(2)} s` : "—";
  const states = {risk:"明确风险", no_clear_risk:"未见明确风险", insufficient_information:"信息不足"};
  const modes = {deepseek_adaptive:"DeepSeek · 自适应融合", rules_only:"仅本地规则与轻量模型"};
  const scenes = {ST1_poster_sms_social:"海报 / 短信 / 社交文案", ST2_live_short_video:"直播 / 短视频 / 口播", ST3_product_intro_detail:"产品介绍 / 详情页", ST4_meeting_material:"说明会 / 客户活动", ST5_training_telemarketing_callback:"培训 / 电销 / 回访", ST6_penalty_backend_fact:"监管处罚 / 后台事实"};
  const metricNames = {
    queries:"样本数", state_accuracy:"三态准确率", risk_binary_accuracy:"风险二分类准确率",
    risk_precision:"风险精确率", risk_recall:"风险召回率", risk_f1:"风险 F1",
    scene_accuracy:"场景准确率", label_micro_f1:"标签 Micro-F1", label_macro_f1:"标签 Macro-F1（27 类）",
    label_supported_macro_f1:"有支持样本标签 Macro-F1", median_seconds:"中位耗时", p95_seconds:"P95 耗时",
    warnings:"含警告 Query", errors:"查询错误", missing_model_targets:"未完成模型目标",
    long_queries:"900 字以上 Query", long_median_seconds:"900 字以上中位耗时",
    judged_queries:"已判定相关性 Query", positive_queries:"有强相关案例 Query", no_positive_queries:"无强相关案例 Query",
    hit1:"Hit@1", hit5:"Hit@5", mrr:"MRR@20", recall_at_3:"Recall@3", recall_at_5:"Recall@5",
    recall_at_10:"Recall@10", recall_at_20:"Recall@20", ndcg_at_10:"NDCG@10",
  };
  const gateNames = {
    meaningful_gain:"核心指标至少提升 1 个百分点", core_no_regression:"核心指标下降不超过 0.5 个百分点",
    binary_gain:"二分类提升至少 1 个百分点", binary_minimum:"二分类准确率至少 92.5%",
    state_gain:"三态提升至少 1 个百分点", state_minimum:"三态准确率至少 89%",
    risk_recall:"风险召回门槛", label_micro_f1:"标签 Micro-F1 门槛", scene_accuracy:"场景准确率门槛",
    query_errors:"无查询错误", missing_model_targets:"无未完成模型目标",
    all_four_exposed_correct:"4 条已暴露问题全部修正", retrieval_hit5:"Hit@5 门槛", retrieval_ndcg_at_10:"NDCG@10 门槛",
  };
  function metric(key, value) {
    if (value === null || value === undefined) return "—";
    if (key.includes("seconds")) return seconds(value);
    if (key === "mrr" || key === "ndcg_at_10") return fixed(value);
    if (/accuracy|precision|recall|f1|^hit/.test(key)) return pct(value);
    return escape(value);
  }
  function table(headers, rows, cls = "") {
    return `<div class="evaluation-scroll"><table class="evaluation-table ${cls}"><thead><tr>${headers.map(h=>`<th scope="col">${escape(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(cell=>`<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  function metricTable(entries) {
    const keys = [...new Set(entries.flatMap(([,v])=>Object.keys(v)))].filter(k=>k!=="per_label");
    return table(["指标", ...entries.map(([name])=>name)], keys.map(k=>[escape(metricNames[k]||k), ...entries.map(([,v])=>metric(k,v[k]))]));
  }
  function labelsTable(values) {
    return table(["标签", "参考数量", "TP 命中", "FP 误报", "FN 漏报", "精确率", "召回率", "F1"], Object.entries(values).map(([name,v])=>[
      escape(name), v.support, v.tp, v.fp, v.fn, v.tp+v.fp ? pct(v.tp/(v.tp+v.fp)) : "—", v.support ? pct(v.tp/v.support) : "—", pct(v.f1),
    ]));
  }
  function groupTable(values, names = {}) {
    return table(["分组", "样本数", "二分类准确率", "三态准确率", "风险召回率", "标签 Micro-F1", "场景准确率", "中位耗时", "P95"], Object.entries(values).map(([k,v])=>[
      escape(names[k]||k), v.queries, pct(v.risk_binary_accuracy), pct(v.state_accuracy), pct(v.risk_recall), pct(v.label_micro_f1), pct(v.scene_accuracy), seconds(v.median_seconds), seconds(v.p95_seconds),
    ]));
  }
  const jsonDetails = (title, value) => `<details class="evaluation-details"><summary>${escape(title)}</summary><pre>${escape(JSON.stringify(value,null,2))}</pre></details>`;
  function outcomes(row, reference) {
    const a = new Set(reference.risk_labels), p = new Set(row.risk_labels || []);
    return {
      state: row.decision_state === reference.decision_state,
      scene: row.scene === reference.scene,
      fp: [...p].filter(x=>!a.has(x)), fn: [...a].filter(x=>!p.has(x)),
      falsePositive: row.decision_state === "risk" && reference.decision_state !== "risk",
      falseNegative: row.decision_state !== "risk" && reference.decision_state === "risk",
    };
  }
  function filterPredictions(predictions, inputs, query, filter) {
    const q = query.trim().toLocaleLowerCase();
    return predictions.filter(row=>{
      const input=inputs[row.query_id], o=outcomes(row,input.reference);
      const matches = !q || `${row.query_id} ${input.text} ${row.risk_labels.join(" ")} ${input.reference.risk_labels.join(" ")}`.toLocaleLowerCase().includes(q);
      return matches && (filter==="all" || (filter==="state"&&!o.state) || (filter==="labels"&&(o.fp.length||o.fn.length)) || (filter==="scene"&&!o.scene) || (filter==="fp"&&o.falsePositive) || (filter==="fn"&&o.falseNegative));
    });
  }
  function renderDashboard(data) {
    const selected=data.runs.find(r=>r.id===data.selected_run), risk=selected.risk[data.selected_mode];
    const stale=data.freshness?.status!=="current";
    const cards=[["风险二分类准确率",pct(risk.risk_binary_accuracy),"当前算法最新复测 · 200 条"],["三态准确率",pct(risk.state_accuracy),"风险 / 未见明确风险 / 信息不足"],["标签 Micro-F1",pct(risk.label_micro_f1),"固定 27 类风险标签"],["类案命中率 Hit@5",pct(selected.retrieval.hit5),"187 条有强相关案例 Query"]];
    return `<div class="evaluation-intro"><div><span class="evaluation-badge">${escape(data.evaluated_on)}</span><span class="evaluation-badge ${stale?"evaluation-warning":""}">${stale?"评测绑定已变化，请核对版本":"评测源码与数据匹配"}</span></div><h3>当前版本 · 最新复测</h3><p>DeepSeek 自适应融合 · 200 条 Query · 500 案例闭池 · 知识库 ${escape(data.knowledge_version)}</p></div>
      <div class="summary-grid">${cards.map(([a,b,c])=>`<article class="summary-card"><span>${a}</span><strong>${b}</strong><small>${c}</small></article>`).join("")}</div>
      <p class="muted evaluation-context">评测算法 ${escape(data.algorithm_revision.slice(0,7))} · ${escape(selected.id)} · 风险召回 ${pct(risk.risk_recall)} · 中位耗时 ${seconds(risk.median_seconds)} · P95 ${seconds(risk.p95_seconds)}</p>
      ${stale?`<p class="evaluation-warning">当前源文件或数据与评测记录不一致，以下为已保存的历史测试结果。</p>`:""}
      <nav class="evaluation-jumps" aria-label="评测章节"><a href="#evaluation-comparison">版本对比</a><a href="#evaluation-detail">完整分项</a><a href="#evaluation-samples">逐条结果</a><a href="#evaluation-development">开发验证</a><a href="#evaluation-method">口径与来源</a></nav>
      <section id="evaluation-comparison"><h3>四次完整测试 · 版本对比</h3><p class="muted">最新复测与发布验收使用相同算法，单次模型调用存在波动。已回退候选仅供比较。</p>${metricTable(data.runs.map(r=>[r.name,r.risk.deepseek_adaptive]))}
      <h4>500 案例检索对比</h4><p class="muted">Hit 表示至少命中一条；Recall 表示相关集合覆盖率。MRR 与 NDCG 越高越好。</p>${metricTable(data.runs.map(r=>[r.name,r.retrieval]))}</section>
      <section id="evaluation-detail"><div class="evaluation-section-heading"><div><h3>完整分项结果</h3><p class="muted">可切换全部四次测试及本地规则对照；切换同时更新下方逐条结果。</p></div><div class="evaluation-controls"><label>测试版本<select id="evaluation-run">${data.runs.map(r=>`<option value="${escape(r.id)}" ${r.id===data.selected_run?"selected":""}>${escape(r.name)}</option>`).join("")}</select></label><label>审查配置<select id="evaluation-mode">${Object.entries(modes).map(([k,v])=>`<option value="${k}">${v}</option>`).join("")}</select></label></div></div><div id="evaluation-run-detail"></div></section>
      <section id="evaluation-samples"><h3>200 条逐条测试结果</h3><div class="evaluation-controls"><label class="evaluation-search">搜索 Query、原文或标签<input id="evaluation-search" type="search" placeholder="输入编号、关键词或风险标签" /></label><label>筛选结果<select id="evaluation-filter"><option value="all">全部结果</option><option value="state">三态不一致</option><option value="labels">标签误报或漏报</option><option value="scene">场景不一致</option><option value="fp">风险误报</option><option value="fn">风险漏报</option></select></label></div><div id="evaluation-query-results"></div></section>
      <section id="evaluation-development"><h3>开发验证与发布门槛</h3>${Object.values(data.comparisons).map(c=>renderComparison(c)).join("")}</section>
      <section id="evaluation-method"><h3>评测口径与来源</h3><ul class="evaluation-notes">${data.notes.map(n=>`<li>${escape(n)}</li>`).join("")}</ul>${jsonDetails("数据集、配置与版本指纹",{dataset:data.dataset,configuration:data.default_config,algorithm_revision:data.algorithm_revision,source_bindings:data.source_bindings,context_bindings:data.context_bindings,source_reports:data.source_reports,freshness:data.freshness})}</section>
      <details class="evaluation-details"><summary>历史报告 · 2026-10-19（不作为当前版本结果）</summary>${metricTable(Object.entries(data.historical.report.risk).map(([k,v])=>[modes[k]||k,v]))}${metricTable(Object.entries(data.historical.report.retrieval))}${jsonDetails("历史报告完整数据",data.historical.report)}</details>`;
  }
  function renderComparison(c) {
    const dev=[];
    for (const [key,value] of Object.entries(c.development)) {
      if (value.queries!==undefined) dev.push([key==="new_boundaries"?"候选 · 边界验证 42 条":"候选 · 原开发前 100 条",value]);
      else for (const [group,metrics] of Object.entries(value)) dev.push([`${key==="baseline"?"基线":"候选"} · ${group==="new_boundaries"?"边界验证 24 条":"原开发前 100 条"}`,metrics]);
    }
    return `<div class="evaluation-experiment"><h4>${escape(c.title)} <span class="evaluation-badge ${c.promote?"":"evaluation-warning"}">${c.promote?"通过 · 已发布":"未通过 · 已回退"}</span></h4><p class="muted">原开发前 100 条参加过模型训练，仅作工程回归；边界验证用于选择候选，不能替代 200 条测试。</p>${metricTable(dev)}<details class="evaluation-details"><summary>开发验证 · 全部标签分项</summary>${dev.map(([name,v])=>`<h4>${escape(name)}</h4>${labelsTable(v.per_label)}`).join("")}</details>${table(["验收项","结果"],Object.entries(c.gate_checks).map(([key,pass])=>[escape(gateNames[key]||key),`<span class="${pass?"":"evaluation-warning"}">${pass?"通过":"未通过"}</span>`]))}${jsonDetails("预设门槛与评测协议",c.protocol)}${Object.keys(c.exposed_cases).length?jsonDetails("4 条已暴露问题 · 开发检查结果",c.exposed_cases):""}</div>`;
  }
  function renderRun(run, mode) {
    const detail=run.modes[mode], risk=run.risk[mode];
    return `<h4>${escape(run.name)} · ${modes[mode]}</h4>${metricTable(Object.entries(run.risk).map(([k,v])=>[modes[k]||k,v]))}<h4>三态混淆矩阵</h4><p class="muted">行是参考状态，列是预测状态。</p>${table(["参考 ＼ 预测",...Object.values(states)],Object.entries(detail.confusion).map(([s,v])=>[states[s],...Object.keys(states).map(p=>v[p])]))}<h4>27 类风险标签</h4><p class="muted">TP 为正确检出，FP 为误报，FN 为漏报；“—”表示该项分母为零。</p>${labelsTable(risk.per_label)}<h4>六类场景（按参考场景分组）</h4>${groupTable(detail.scenes,scenes)}<h4>文本长度分组</h4><p class="muted">900 字及以上只有 1 条；各组风险召回与 F1 沿用评测脚本的零分母记 0 口径。</p>${groupTable(detail.lengths)}<p class="muted">本次独立检索：${run.retrieval_verified}/200 条证据原文校验通过，${run.retrieval_warnings} 条检索警告。检索表与逐条 Top20 使用 DeepSeek 重排，不随审查配置切换。</p>`;
  }
  function renderSamples(run, mode, inputs, query="", filter="all", page=1) {
    const all=filterPredictions(run.modes[mode].predictions,inputs,query,filter);
    const pages=Math.max(1,Math.ceil(all.length/20)), current=Math.min(page,pages);
    const items=all.slice((current-1)*20,current*20).map(row=>{
      const input=inputs[row.query_id], ref=input.reference, o=outcomes(row,ref), rank=run.rankings[row.query_id];
      const badges=[!o.state?"三态不一致":"三态一致",...(o.fp.length?[`标签误报 ${o.fp.length}`]:[]),...(o.fn.length?[`标签漏报 ${o.fn.length}`]:[]),...(!o.scene?["场景不一致"]:[])];
      return `<details class="evaluation-sample"><summary><strong>${escape(row.query_id)}</strong><span>${escape(states[ref.decision_state])} → ${escape(states[row.decision_state]||row.decision_state)}</span><span class="muted">${escape(badges.join(" · "))} · ${seconds(row.seconds)}</span></summary><div class="evaluation-sample-body"><h4>测试原文</h4><p class="evaluation-query-text">${escape(input.text)}</p>${table(["项目","参考","预测"],[["状态",states[ref.decision_state],escape(states[row.decision_state]||row.decision_state)],["场景",escape(scenes[ref.scene]),escape(scenes[row.scene]||row.scene)],["标签",escape(ref.risk_labels.join("、")||"无"),escape(row.risk_labels.join("、")||"无")]])}<p>标签误报：${escape(o.fp.join("、")||"无")}；标签漏报：${escape(o.fn.join("、")||"无")}</p><p class="muted">参考理由：${escape(ref.reason)}</p><p class="muted">参考证据：${escape((ref.evidence||[]).join("；"))}</p><p class="muted">未完成目标 ${row.missing_model_targets??0} · 警告 ${escape((row.warnings||[]).join("；")||"无")} · 错误 ${escape(row.error||"无")}</p><h4>独立检索 Top20</h4><p class="muted">强相关案例总数 ${rank.relevant_count} · 原文校验 ${rank.literal_verified?"通过":"未通过"} · ${seconds(rank.seconds)}${rank.metrics?` · Hit@5 ${pct(rank.metrics.hit5)} · Recall@10 ${pct(rank.metrics.recall_at_10)} · NDCG@10 ${fixed(rank.metrics.ndcg_at_10)}`:" · 无强相关案例，不纳入排序质量均值"}</p>${table(["排名","案例 ID","相关等级（≥2 为强相关）"],rank.case_ids.map((id,i)=>[i+1,escape(id),rank.grades[i]]))}</div></details>`;
    }).join("");
    return `<p class="muted">${escape(run.name)} · ${modes[mode]} · 符合条件 ${all.length} / 200 条 · 第 ${current} / ${pages} 页</p>${items||'<div class="inline-empty">没有符合条件的结果</div>'}<div class="evaluation-pagination"><button type="button" class="quiet-button" data-evaluation-page="${current-1}" ${current===1?"disabled":""}>上一页</button><span>${current} / ${pages}</span><button type="button" class="quiet-button" data-evaluation-page="${current+1}" ${current===pages?"disabled":""}>下一页</button></div>`;
  }
  function mount(target,data) {
    target.innerHTML=renderDashboard(data);
    const find=s=>target.querySelector(s);
    let page=1;
    const run=()=>data.runs.find(r=>r.id===find("#evaluation-run").value);
    const samples=()=>{find("#evaluation-query-results").innerHTML=renderSamples(run(),find("#evaluation-mode").value,data.inputs,find("#evaluation-search").value,find("#evaluation-filter").value,page);};
    const update=()=>{page=1;find("#evaluation-run-detail").innerHTML=renderRun(run(),find("#evaluation-mode").value);samples();};
    ["#evaluation-run","#evaluation-mode"].forEach(s=>find(s).addEventListener("change",update));
    find("#evaluation-search").addEventListener("input",()=>{page=1;samples();});
    find("#evaluation-filter").addEventListener("change",()=>{page=1;samples();});
    find("#evaluation-query-results").addEventListener("click",event=>{
      const button=event.target.closest("[data-evaluation-page]");
      if(button){page=Number(button.dataset.evaluationPage);samples();}
    });
    update();
  }
  const exported={mount,renderDashboard,renderRun,renderSamples,filterPredictions,outcomes};
  if(typeof module!=="undefined"&&module.exports) module.exports=exported;
  else root.FinRiskEvaluation=exported;
})(typeof window!=="undefined"?window:globalThis);
