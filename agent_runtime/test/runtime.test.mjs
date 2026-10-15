import assert from "node:assert/strict";
import { createServer } from "node:http";
import { once } from "node:events";
import { test } from "node:test";
import { runJsonTask } from "../runtime.mjs";

const baseRequest = {
  messages: [{ role: "system", content: "返回JSON对象。" }, { role: "user", content: "测试材料" }],
  task: "json_review", review_context: {}, temperature: 0, max_tokens: 300, extra_body: {},
};
const baseSettings = {
  model: "deepseek-flash", thinking: "disabled", read_timeout_seconds: 3, agent_max_turns: 3,
};

async function withProvider(handler, execute) {
  const requests = [];
  const server = createServer(async (req, res) => {
    let data = "";
    for await (const chunk of req) data += chunk;
    const body = JSON.parse(data);
    requests.push(body);
    const answer = handler(body, requests.length);
    if (answer.hold) return;
    if (answer.status) {
      res.writeHead(answer.status, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: { message: "provider error", type: "test_error" } }));
      return;
    }
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    const delta = answer.tool
      ? { tool_calls: [{ index: 0, id: "call_" + requests.length, type: "function",
          function: { name: answer.tool, arguments: JSON.stringify(answer.args) } }] }
      : { content: answer.text || "尚未提交" };
    const chunk = {
      id: "test", object: "chat.completion.chunk", created: 1, model: "deepseek-flash",
      choices: [{ index: 0, delta, finish_reason: null }],
    };
    const done = { ...chunk, choices: [{ index: 0, delta: {}, finish_reason: answer.tool ? "tool_calls" : "stop" }],
      usage: { prompt_tokens: 20, completion_tokens: 10, total_tokens: 30 } };
    res.end("data: " + JSON.stringify(chunk) + "\n\ndata: " + JSON.stringify(done) + "\n\ndata: [DONE]\n\n");
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const settings = { ...baseSettings, base_url: "http://127.0.0.1:" + server.address().port + "/v1" };
  try { await execute(settings, requests); }
  finally { server.closeAllConnections(); server.close(); await once(server, "close"); }
}

test("real Pi loop reads context, submits once, and exposes no raw text in trace", async () => {
  await withProvider((_, n) => n === 1
    ? { tool: "read_review_context", args: {} }
    : { tool: "submit_result", args: { result_json: '{"ok":true}' } }, async (settings, requests) => {
    const result = await runJsonTask({ request: baseRequest, settings, apiKey: "dummy" });
    assert.deepEqual(result.data, { ok: true });
    assert.equal(result.agent_trace.turns, 2);
    assert.equal(result.agent_trace.tool_calls, 2);
    assert.equal(requests.length, 2);
    assert.deepEqual(requests[0].thinking, { type: "disabled" });
    assert.deepEqual(requests[0].tools.map(v => v.function.name), ["read_review_context", "submit_result"]);
    assert(!JSON.stringify(result.agent_trace).includes("测试材料"));
    assert(!JSON.stringify(result.agent_trace).includes("dummy"));
  });
});

test("malformed submission becomes a tool error and is repaired within the same Agent", async () => {
  await withProvider((_, n) => ({ tool: "submit_result", args: {
    result_json: n === 1 ? "{invalid" : '{"ok":true}',
  } }), async (settings, requests) => {
    const result = await runJsonTask({ request: baseRequest, settings, apiKey: "dummy" });
    assert.equal(result.agent_trace.tool_failures, 1);
    assert.equal(result.agent_trace.turns, 2);
    assert(requests[1].messages.some(m => m.role === "tool" && m.content.includes("有效")));
  });
});

test("risk review refuses invented quotes and repairs using provided source", async () => {
  const request = { ...baseRequest, task: "risk_review", review_context: {
    target_ids: ["s1"], allowed_labels: ["承诺收益"],
    sentences: [{ sentence_id: "s1", text: "保证收益8%。", context: {
      source_sentences: [{ text: "保证收益8%。" }],
    } }],
  } };
  await withProvider((_, n) => ({ tool: "submit_result", args: {
    result_json: JSON.stringify({ items: [{ sentence_id: "s1", risk_score: .9,
      risk_labels: ["承诺收益"], reasoning: "原文承诺收益。", evidence: [n === 1 ? "从不存在的原文" : "保证收益8%"] }] }),
  } }), async settings => {
    const result = await runJsonTask({ request, settings, apiKey: "dummy" });
    assert.equal(result.agent_trace.tool_failures, 1);
    assert.deepEqual(result.data.items[0].evidence, ["保证收益8%"]);
  });
});

test("unknown tool cannot execute and the Agent can correct its next call", async () => {
  await withProvider((_, n) => n === 1
    ? { tool: "bash", args: { command: "should never run" } }
    : { tool: "submit_result", args: { result_json: '{"safe":true}' } }, async settings => {
    const result = await runJsonTask({ request: baseRequest, settings, apiKey: "dummy" });
    assert.deepEqual(result.data, { safe: true });
    assert.equal(result.agent_trace.tool_failures, 1);
  });
});

test("missing structured submission stops at the turn budget", async () => {
  await withProvider(() => ({ text: "继续分析，但不提交" }), async (settings, requests) => {
    await assert.rejects(
      runJsonTask({ request: baseRequest, settings, apiKey: "dummy" }),
      error => error.code === "turn_budget",
    );
    assert.equal(requests.length, 3);
  });
});

test("provider authentication failure has sanitized, nonretryable error", async () => {
  await withProvider(() => ({ status: 401 }), async settings => {
    await assert.rejects(
      runJsonTask({ request: baseRequest, settings, apiKey: "dummy" }),
      error => error.code === "provider_error" && !error.message.includes("dummy") && !error.retryable,
    );
  });
});

test("already cancelled task does not contact the provider", async () => {
  await withProvider(() => ({ text: "unused" }), async (settings, requests) => {
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(
      runJsonTask({ request: baseRequest, settings, apiKey: "dummy", signal: controller.signal }),
      error => error.code === "cancelled",
    );
    assert.equal(requests.length, 0);
  });
});

test("cancelling an active provider request aborts the Pi run", async () => {
  let notifyStarted;
  const started = new Promise(resolve => { notifyStarted = resolve; });
  await withProvider(() => { notifyStarted(); return { hold: true }; }, async settings => {
    const controller = new AbortController();
    const pending = runJsonTask({ request: baseRequest, settings, apiKey: "dummy", signal: controller.signal });
    const check = assert.rejects(pending, error => error.code === "cancelled");
    await started;
    controller.abort();
    await check;
  });
});

test("provider request timeout produces a bounded, retryable failure", async () => {
  await withProvider(() => ({ hold: true }), async settings => {
    await assert.rejects(
      runJsonTask({ request: baseRequest, settings: { ...settings, read_timeout_seconds: .1 }, apiKey: "dummy" }),
      error => error.code === "timeout" && error.retryable,
    );
  });
});
