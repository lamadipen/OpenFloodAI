const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../../tools/console/review.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const helpers =
  script.slice(script.indexOf("function formatUtc"), script.indexOf("function formatGap")) +
  script.slice(script.indexOf("let samState"), script.indexOf("async function loadSam")) +
  script.slice(script.indexOf("function samBody"), script.indexOf("async function refreshSamPlan")) +
  script.slice(script.indexOf("function samResultHtml"), script.indexOf("function renderSamPanel"));

function context(statusOverrides, samOverrides = {}) {
  const sandbox = {
    escapeHtml: (value) => String(value),
    URLSearchParams,
    Date,
    Number,
    String,
    folderName: "demo",
    days: [{ filename: "a.jpg", code: "N" }],
    state: { selectedIndex: 0 },
    sequenceId: () => "seq"
  };
  vm.createContext(sandbox);
  vm.runInContext(helpers, sandbox);
  const status = {
    enabled: true,
    credential: { configured: true, upload_acknowledged: false },
    decoder_available: true,
    provider: { signup_url: "https://dev.meta.ai/models/sam-3-1" },
    ...statusOverrides
  };
  Object.assign(vm.runInContext("samState", sandbox), { status, ...samOverrides });
  return sandbox;
}

const result = (extra) => ({
  run_id: "r1",
  result_id: "001",
  filename: "a.jpg",
  prompt: "water",
  model_requested: "sam-3.1",
  processed_at_utc: "2026-09-01T10:00:00+00:00",
  review_status: "unreviewed",
  ...extra
});

test("hosted SAM is off by default and offers no way to start", () => {
  const out = context({ enabled: false }).samPanelHtml();
  assert.match(out, /Off\. Nothing is uploaded/);
  assert.doesNotMatch(out, /samStart/);
});

test("enabled without a key asks for setup and offers no start button", () => {
  const out = context({ credential: { configured: false } }).samPanelHtml();
  assert.match(out, /Add your own API key/);
  assert.doesNotMatch(out, /samStart/);
});

test("starting needs the upload acknowledgement and shows the request count", () => {
  const plan = { request_count: 2, reused_from_earlier_runs: 0 };
  const blocked = context({}, { plan, concepts: ["water", "riverbank"] }).samPanelHtml();
  assert.match(blocked, /uploaded to Meta and my account may be charged/);
  assert.match(blocked, /Start segmentation \(2 requests\)/);
  assert.match(blocked, /id="samStart" disabled/);

  const ready = context({}, { plan, ackChecked: true }).samPanelHtml();
  assert.doesNotMatch(ready, /id="samStart" disabled/);

  const alreadyAcknowledged = context({}, { plan, ack: true }).samPanelHtml();
  assert.doesNotMatch(alreadyAcknowledged, /id="samAck"/);
});

test("a missing decoder blocks the start button", () => {
  const out = context({ decoder_available: false }, { plan: { request_count: 1 }, ackChecked: true }).samPanelHtml();
  assert.match(out, /id="samStart" disabled/);
  assert.match(out, /decoder is not installed/);
});

test("no match, failure, and success are shown as different states", () => {
  const ctx = context({}, {
    results: [
      result({ result_id: "1", status: "no_match" }),
      result({ result_id: "2", status: "failed", error_code: "rate_limited" }),
      result({ result_id: "3", status: "completed" })
    ]
  });
  const out = ctx.samPanelHtml();
  assert.match(out, /does not mean the area is normal or safe/);
  assert.match(out, /rate limiting/);
  assert.match(out, /Mask found/);
  assert.equal((out.match(/\/api\/hosted-sam\/overlay/g) || []).length, 1);
  assert.equal((out.match(/data-sam-review="accepted"/g) || []).length, 1);
  assert.match(out, /Unreviewed/);
});

test("results for other images are not shown on this image", () => {
  const out = context({}, { results: [result({ filename: "other.jpg", status: "completed" })] }).samPanelHtml();
  assert.doesNotMatch(out, /overlay/);
});

test("the panel states that a prediction is not a label or a waterline", () => {
  const out = context({}).samPanelHtml();
  assert.match(out, /not a human label, not a detected waterline/);
});
