const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../tools/console/review-compare.js"), "utf8");
const reviewSource = fs.readFileSync(path.join(__dirname, "../../tools/console/review.js"), "utf8");

function load(overrides = {}) {
  const calls = [];
  const sandbox = {
    escapeHtml: (v) => String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
    folderName: "demo",
    runId: "20261001T100000Z-aaaaaaaa",
    state: { selectedIndex: 0, filter: null },
    days: [{ filename: "cur.jpg", capturedAtUtc: "2026-02-10T18:00:00+00:00", time: "11:00" }],
    detail: { summary: { baseline_filename: "base.jpg" } },
    sequenceId: () => "seq-current",
    formatUtc: (iso) => String(iso).slice(0, 16).replace("T", " ") + " UTC",
    sideBySideHtml: (args) => `<side captions="${args.captions ? args.captions.join("|") : ""}"></side>`,
    onionHtml: (a, b) => `<onion ${a} ${b}></onion>`,
    $: () => null,
    render: () => {},
    toast: () => {},
    window: { scrollY: 120, scrollTo: (x, y) => { sandbox.scrolled = y; } },
    api: async (url, body) => {
      calls.push({ url, body });
      return overrides.api ? overrides.api(url, body) : {};
    },
    Date, Number, String, Object, Map, Array, JSON, URLSearchParams, Set, RegExp, Math
  };
  sandbox.calls = calls;
  vm.createContext(sandbox);
  vm.runInContext(source.slice(source.indexOf("// ---- compare any two images"), source.indexOf("// ---- end compare any two images")), sandbox);
  sandbox.cmp = vm.runInContext("cmp", sandbox); // a script-level let, shared by reference
  return sandbox;
}

const image = (sequence, name, when, extra = {}) => ({
  sequence_id: sequence, filename: name, captured_at_utc: when, local_time: when.replace("+00:00", "-07:00"),
  run_id: extra.run_id === undefined ? `run-${sequence}` : extra.run_id, mask_state: extra.mask_state || "accepted"
});

const candidates = {
  camera_id: "CAM",
  sequences: [{ sequence_id: "seq-current", label: "Current set", image_count: 2 }, { sequence_id: "seq-other", label: "Other set", image_count: 2 }],
  images: [
    image("seq-current", "cur.jpg", "2026-02-10T18:00:00+00:00"),
    image("seq-current", "a.jpg", "2026-01-04T18:30:00+00:00", { mask_state: "none" }),
    image("seq-other", "cur.jpg", "2026-03-01T18:00:00+00:00", { mask_state: "rejected" }), // same file name, another sequence
    image("seq-other", "b.jpg", "2026-04-25T16:00:00+00:00", { run_id: null, mask_state: "none" })
  ]
};

const available = (value = 15.5) => ({
  success: true, available: true, elapsed_seconds: 86400,
  earlier: { run_id: "r1", filename: "a.jpg" }, later: { run_id: "r2", filename: "cur.jpg" },
  evidence: {
    status: "available", value, reason_codes: ["COVERAGE_INCREASED", "ALIGNMENT_NOT_VERIFIED_AUTOMATICALLY"],
    quality: { measurement: { earlier_fraction: 0.2, later_fraction: 0.355, newly_wet_fraction: 0.16, no_longer_wet_fraction: 0.005, change_rate_pp_per_hour: 0.65 } }
  },
  provenance: { calculation_version: "water_change_mask_v1.0", earlier: { review_decision: "accepted", reviewed_at_utc: "2026-10-09T10:00:00+00:00", segmentation_run_id: "20261002T100000Z-aaaaaaaa", image_sha256: "a".repeat(64) }, later: {} },
  note: "Image-space coverage of the watched area from two accepted masks. Not water level, depth, flow speed, continuous rise or flood status."
});

test("the pair is always shown earlier then later, whichever image was picked", () => {
  const c = load();
  c.cmp.candidates = candidates;
  c.cmp.other = candidates.images[1]; // January: earlier than the current February image
  assert.equal(c.cmpOrdered().earlier.filename, "a.jpg");
  assert.equal(c.cmpOrdered().later.filename, "cur.jpg");
  c.cmp.other = candidates.images[2]; // March: later than the current image
  assert.equal(c.cmpOrdered().earlier.filename, "cur.jpg");
  assert.equal(c.cmpOrdered().later.filename, "cur.jpg");
  assert.equal(c.cmpOrdered().later.sequence_id, "seq-other");
});

test("an image is identified by sequence AND file name, so duplicate names stay distinct", () => {
  const c = load();
  c.cmp.candidates = candidates;
  assert.notEqual(c.cmpKey(candidates.images[0]), c.cmpKey(candidates.images[2]));
  const rows = c.cmpCandidateRows().map((i) => `${i.sequence_id}/${i.filename}`);
  assert.ok(!rows.includes("seq-current/cur.jpg")); // the image being reviewed is not offered
  assert.ok(rows.includes("seq-other/cur.jpg")); // the same name in another sequence is
  assert.equal(rows.length, 3);
});

test("filters narrow by sequence, dates and accepted masks without touching the data", () => {
  const c = load();
  c.cmp.candidates = candidates;
  c.cmp.filters.sequence = "seq-other";
  assert.deepEqual(c.cmpCandidateRows().map((i) => i.filename), ["cur.jpg", "b.jpg"]);
  c.cmp.filters = { sequence: "", from: "2026-03-01", to: "2026-04-30", acceptedOnly: false };
  assert.deepEqual(c.cmpCandidateRows().map((i) => i.filename), ["cur.jpg", "b.jpg"]);
  c.cmp.filters = { sequence: "", from: "", to: "", acceptedOnly: true };
  assert.equal(c.cmpCandidateRows().length, 0); // the only accepted image is the current one
  assert.equal(candidates.images.length, 4);
});

test("the picker shows exact times, the mask state and images that have no saved run", () => {
  const c = load();
  c.cmp.candidates = candidates;
  c.cmp.open = true;
  const html = c.comparePickerHtml();
  assert.match(html, /Choose the other image/);
  assert.match(html, /2026-01-04 18:30 UTC/);
  assert.match(html, /Mask rejected/);
  assert.match(html, /No mask/);
  assert.match(html, /No saved run: images only/);
  assert.match(html, /Same camera only/);
  assert.match(html, /\/api\/compare\/thumbnail\?/);
});

test("choosing an image measures the pair in the order current then other and asks no segmentation", async () => {
  const c = load({ api: () => available() });
  c.cmp.candidates = candidates;
  await c.handleCompareAction("compare-pick", { dataset: { key: c.cmpKey(candidates.images[1]) } });
  assert.equal(c.compareActive(), true);
  const measure = c.calls.find((x) => x.url === "/api/compare/measure");
  assert.deepEqual(JSON.parse(JSON.stringify(measure.body.a)), { run_id: "20261001T100000Z-aaaaaaaa", filename: "cur.jpg" });
  assert.deepEqual(JSON.parse(JSON.stringify(measure.body.b)), { run_id: "run-seq-current", filename: "a.jpg" });
  assert.equal(measure.body.framing_confirmed, false);
  assert.ok(c.calls.every((x) => x.url.startsWith("/api/compare/")), "only compare routes are used");
});

test("the numbers appear only with framing confirmed; otherwise the reason is given and no value", () => {
  const c = load();
  c.cmp.candidates = candidates;
  c.cmp.other = candidates.images[1];
  c.cmp.active = true;
  c.cmp.result = { available: false, evidence: { status: "unavailable", value: null, reason_codes: ["FRAMING_NOT_CONFIRMED", "LATER_MASK_UNREVIEWED"] }, provenance: {} };
  const out = c.compareResultHtml();
  assert.match(out, /Water coverage change is unavailable for this pair/);
  assert.match(out, /No number is shown instead of a guess/);
  assert.match(out, /Confirm below that the camera view did not move/);
  assert.match(out, /The later image has a water mask that nobody has accepted/);
  assert.doesNotMatch(out, /percentage points/);
  assert.doesNotMatch(out, /Save this comparison/);
});

test("an available result is labelled Water coverage change with pp, overlay and provenance", () => {
  const c = load();
  c.cmp.candidates = candidates;
  c.cmp.other = candidates.images[1];
  c.cmp.active = true;
  c.cmp.framing = true;
  c.cmp.result = available();
  const out = c.compareResultHtml();
  assert.match(out, /Water coverage change/);
  assert.match(out, /<strong>20\.0%<\/strong> &rarr; <strong>35\.5%<\/strong>/);
  assert.match(out, /\+15\.5 percentage points/);
  assert.match(out, /Newly wet <strong>16\.0%<\/strong> &middot; no longer wet <strong>0\.5%/);
  assert.match(out, /image-space rate/);
  assert.match(out, /\/api\/compare\/overlay\?/);
  assert.match(out, /Pixel appearance change/);
  assert.match(out, /never combined/);
  assert.match(out, /Not water level, depth, flow speed, continuous rise or flood status/);
  assert.match(out, /Mask review state and calculation/);
  assert.match(out, /accepted at 2026-10-09 10:00 UTC/);
});

test("a negative change is signed and a missing run explains itself without a request", async () => {
  const c = load();
  c.cmp.candidates = candidates;
  c.cmp.other = candidates.images[1];
  c.cmp.active = true;
  c.cmp.result = available(-8.25);
  assert.match(c.compareResultHtml(), /<strong>-8\.\d percentage points<\/strong>/);
  c.cmp.other = candidates.images[3]; // no saved run
  c.cmp.result = null;
  assert.match(c.compareResultHtml(), /no saved validation run yet/);
  c.calls.length = 0;
  await c.compareMeasure();
  assert.equal(c.calls.length, 0);
});

test("viewing never saves; Save is an explicit separate call and reports a repeat", async () => {
  const c = load({ api: (url) => (url === "/api/compare/save" ? { saved: { pair_key: "abc", reused: false } } : available()) });
  c.cmp.candidates = candidates;
  c.cmp.other = candidates.images[1];
  c.cmp.active = true;
  c.cmp.result = available();
  assert.equal(c.calls.filter((x) => x.url === "/api/compare/save").length, 0);
  await c.compareSave();
  assert.equal(c.calls.filter((x) => x.url === "/api/compare/save").length, 1);
  assert.equal(c.cmp.saved.pair_key, "abc");
  assert.match(c.compareResultHtml(), /Saved \(abc\)/);
});

test("closing restores the selection, filter and scroll position and ends the comparison", () => {
  const c = load();
  c.cmp.candidates = candidates;
  c.state.selectedIndex = 3; c.state.filter = "P";
  c.cmp.restore = { selectedIndex: 3, filter: "P", scrollY: 640 };
  c.cmp.other = candidates.images[1]; c.cmp.active = true;
  c.state.selectedIndex = 0; c.state.filter = null;
  c.compareClose();
  assert.equal(c.compareActive(), false);
  assert.equal(c.state.selectedIndex, 3);
  assert.equal(c.state.filter, "P");
  assert.equal(c.scrolled, 640);
  assert.equal(c.cmp.result, null);
});

test("choosing a different current image ends the comparison so it never describes the wrong image", () => {
  assert.match(reviewSource, /function selectIndex\(index\) \{\s*compareReset\(\)/);
  assert.match(reviewSource, /\["select-event", "biggest", "prev-event", "next-event"\]\.includes\(act\)\) compareReset\(\)/);
  const c = load();
  c.cmp.other = candidates.images[1]; c.cmp.active = true; c.cmp.result = available();
  c.compareReset();
  assert.equal(c.compareActive(), false);
  assert.equal(c.cmp.result, null);
});

test("the existing comparison views are reused, with chronological captions", () => {
  const c = load();
  c.cmp.candidates = candidates;
  c.cmp.other = candidates.images[1];
  c.cmp.active = true;
  const out = c.compareViewsHtml({ showSide: true, showOverlay: true });
  assert.match(out, /captions="Earlier &mdash; 2026-01-04 18:30 UTC[^|]*\|Later &mdash; 2026-02-10 18:00 UTC/);
  assert.match(out, /<onion /);
  assert.match(out, /Earlier &rarr; later/);
  assert.match(out, /Always in time order/);
  assert.match(reviewSource, /compareActive\(\) \? compareViewsHtml/);
  assert.match(reviewSource, /function sideBySideHtml\(\{[^}]*captions: captionTexts/);
});

test("the reason lines name the image concerned and never invent a reason", () => {
  const c = load();
  const lines = c.cmpReasonLines(["EARLIER_MASK_REJECTED", "WATCHED_AREA_CHANGED", "TIMESTAMPS_EQUAL", "SOMETHING_NEW", "ALIGNMENT_NOT_VERIFIED_AUTOMATICALLY", "COVERAGE_INCREASED"]);
  assert.ok(lines.some((l) => /The earlier image has a water mask that a reviewer rejected/.test(l)));
  assert.ok(lines.some((l) => /different watched areas/.test(l)));
  assert.ok(lines.some((l) => /same capture time/.test(l)));
  assert.ok(lines.includes("SOMETHING_NEW"));
  assert.equal(lines.length, 4);
});
