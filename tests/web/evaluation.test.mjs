import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import test from "node:test";

const ui = createRequire(import.meta.url)("../../src/web/static/evaluation.js");
const data = JSON.parse(readFileSync(new URL("../../reports/evaluation_dashboard/evaluation.json", import.meta.url), "utf8"));
const run = data.runs.find(r=>r.id===data.selected_run);
data.freshness = { status: "current" };

test("only current version and one no-model comparison are shown",()=>{
  const html=ui.renderDashboard(data);
  assert.match(html,/91\.00%/);
  assert.match(html,/无大模型与当前版本对比/);
  assert.match(html,/规则与轻量模型/);
  assert.doesNotMatch(html,/优化前|已回退|开发验证|发布门槛|历史报告|evaluation-run|evaluation-mode/);
  assert.doesNotMatch(html,/undefined|NaN/);
  assert.equal((html.match(/evaluation-comparison-table/g)||[]).length,1);
});

test("current results and no-model control retain complete valid predictions",()=>{
  for(const r of data.runs) for(const mode of Object.keys(r.modes)) {
    assert.doesNotMatch(ui.renderRun(r,mode),/undefined|NaN/);
    for(let p=1;p<=10;p++) assert.doesNotMatch(ui.renderSamples(r,mode,data.inputs,"","all",p),/undefined|NaN/);
  }
});

test("filters use reference states and labels, retaining every test row",()=>{
  const rows=run.modes.deepseek_adaptive.predictions;
  assert.equal(ui.filterPredictions(rows,data.inputs,"","all").length,200);
  assert.equal(ui.filterPredictions(rows,data.inputs,"","state").length,27);
  assert.equal(ui.filterPredictions(rows,data.inputs,"","fp").length,15);
  assert.equal(ui.filterPredictions(rows,data.inputs,"","fn").length,3);
  assert.equal(ui.filterPredictions(rows,data.inputs,"TEST200","all").length,1);
  assert.match(ui.renderSamples(run,"deepseek_adaptive",data.inputs,"","all",10),/TEST200/);
});

test("query and model strings cannot inject HTML into expanded results",()=>{
  const inputs=structuredClone(data.inputs);
  inputs.TEST001.text='<img src=x onerror=alert(1)>';
  inputs.TEST001.reference.reason='<script>bad</script>';
  const html=ui.renderSamples(run,"deepseek_adaptive",inputs,"TEST001");
  assert.doesNotMatch(html,/<img|<script/);
  assert.match(html,/&lt;img/);
  assert.match(html,/&lt;script/);
});
