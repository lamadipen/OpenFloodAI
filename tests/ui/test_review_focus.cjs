const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");

const html = fs.readFileSync("tools/console/review-focus.html", "utf8");
const css = fs.readFileSync("tools/console/review-focus.css", "utf8");
const script = fs.readFileSync("tools/console/review-focus.js", "utf8");
const vm = require("node:vm");

test("blind review remains separate from the established detailed page", () => {
  assert.match(html, /review-focus\.css/);
  assert.match(html, /review-focus\.js/);
  assert.match(script, /Open the established detailed review page/);
  assert.match(script, /\/console\/review\.html/);
});

test("an independent label controls when machine evidence is revealed", () => {
  assert.match(script, /function isRevealed\(day\)/);
  assert.match(script, /Machine result, gauge, masks, and other reviewers are hidden/);
  assert.match(script, /own && revealed\) body = /);
  assert.match(script, /hiddenStageHtml\(day\)/);
  assert.match(script, /Your independent label is saved/);
});

test("blind review starts with reference and current original images", () => {
  assert.match(script, /function baselineDay\(\)/);
  assert.match(script, /Side by side/);
  assert.match(script, /Overlay/);
  assert.match(script, /Reference river image/);
  assert.match(script, /Current river image/);
  assert.equal(script.match(/let viewMode = "original"/g).length, 1);
});

test("inline labels support reviewer identity and keyboard choices", () => {
  assert.match(script, /Reviewer code/);
  assert.match(script, /reviewer_id: reviewerId/);
  assert.match(script, /Keys 1–5 choose a label/);
  assert.match(script, /event\.key === "Enter"/);
  assert.match(script, /\/api\/workspace-label/);
});

test("draft mask coverage is clearly different from accepted evidence", () => {
  assert.match(script, /% draft estimate/);
  assert.match(script, /Machine draft only\. It has not been accepted as dataset evidence/);
  assert.match(script, /% accepted coverage/);
  assert.match(script, /Missing segmentation is not evidence of no water/);
});

test("post-label tools include mask review and dataset curation", () => {
  assert.match(script, /\/api\/hosted-sam\/review/);
  assert.match(script, /Needs correction/);
  assert.match(script, /\/api\/dataset-add/);
  assert.match(script, /\/api\/dataset-add-pair/);
  assert.match(script, /Review group/);
  assert.match(script, /assigned by dataset policy when added/);
});

test("zoom, neighbours, and responsive layouts are present", () => {
  assert.match(script, /id="zoomControl"/);
  assert.match(script, /Neighbouring images/);
  assert.match(css, /grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/);
  assert.match(css, /@media \(max-width: 760px\)/);
  assert.match(css, /\.image-pair,/);
});


// ---- behaviour, run against the page's own functions ----------------------------------------

function load(extra = {}) {
  const storage = {};
  const sandbox = {
    qs: (name) => ({ site: "demo", run_id: "run-1" }[name] || ""),
    $: () => null,
    escapeHtml: (value) => String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;"),
    localStorage: { getItem: (k) => storage[k] ?? null, setItem: (k, v) => { storage[k] = v; } },
    document: { addEventListener() {}, querySelectorAll: () => [], querySelector: () => null },
    toast() {}, mountShell: () => ({}), api: async () => ({}), fetch: async () => ({ ok: true, json: async () => ({}) }),
    Date, Number, String, Object, Map, Set, Array, JSON, URLSearchParams, Math, window: {},
    ...extra
  };
  vm.createContext(sandbox);
  const source = script.replace(/\nmain\(\);\s*$/, "\n");
  vm.runInContext(source, sandbox);
  const detail = {
    summary: { sequence_id: "seq-a", baseline_filename: "base.jpg", biggest_change_filename: "b.jpg" },
    records: [
      { filename: "base.jpg", captured_at_utc: "2026-01-01T18:00:00+00:00", local_time: "2026-01-01T11:00:00-07:00", download_status: "downloaded", result: "no_water_level_change" },
      { filename: "a.jpg", captured_at_utc: "2026-01-02T18:00:00+00:00", local_time: "2026-01-02T11:00:00-07:00", download_status: "downloaded", result: "no_water_level_change" },
      { filename: "b.jpg", captured_at_utc: "2026-01-03T18:00:00+00:00", local_time: "2026-01-03T11:00:00-07:00", download_status: "downloaded", result: "possible_water_level_change" }
    ],
    gauge_evidence: { images: [] }, evidence_records: []
  };
  vm.runInContext("detail = " + JSON.stringify(detail) + "; days = buildDays(detail.records);", sandbox);
  return sandbox;
}

const review = (reviewer, human, extra = {}) => ({
  label: { human_label: human, reviewer_id: reviewer, camera_stable: "yes" },
  label_revision: 1, review_stage: "blind", ...extra
});

function withPoints(ctx, perFile) {
  const points = Object.entries(perFile).map(([filename, reviews]) => ({ key: `k-${filename}`, filename, reviews }));
  ctx.points = points;
  vm.runInContext("evidencePoints = points;", ctx);
}

test("the baseline cannot be reviewed against itself and is skipped when the page opens", () => {
  const ctx = load();
  withPoints(ctx, { "base.jpg": [], "a.jpg": [], "b.jpg": [] });
  vm.runInContext('reviewerId = "reviewer-a";', ctx);
  const base = vm.runInContext("days[0]", ctx);
  assert.equal(ctx.canReview(base), false);
  assert.equal(ctx.canReview(vm.runInContext("days[1]", ctx)), true);
  assert.equal(ctx.chooseInitialIndex(), 1);
  assert.equal(ctx.reviewableCount(), 2);
  assert.match(ctx.comparisonPicturesHtml(base), /This image is the reference/);
  // another reference makes the baseline reviewable again
  vm.runInContext('referenceChoices.set("base.jpg", { mode: "previous" });', ctx);
  assert.equal(ctx.canReview(base), false); // nothing before it
});

test("the reference can be the run baseline, the previous image or a chosen image", () => {
  const ctx = load();
  const day = (i) => vm.runInContext(`days[${i}]`, ctx);
  assert.equal(ctx.referenceFor(day(2)).kind, "baseline");
  vm.runInContext('referenceChoices.set("b.jpg", { mode: "previous" });', ctx);
  assert.equal(ctx.referenceFor(day(2)).filename, "a.jpg");
  assert.equal(ctx.referenceFor(day(2)).kind, "previous");
  vm.runInContext('referenceChoices.set("b.jpg", { mode: "chosen", item: { sequence_id: "seq-z", run_id: "run-z", filename: "z.jpg", capturedAtUtc: "2025-12-01T00:00:00+00:00" } });', ctx);
  const ref = ctx.referenceFor(day(2));
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.referencePayload(ref))), { sequence_id: "seq-z", run_id: "run-z", filename: "z.jpg" });
  assert.equal(ref.kind, "chosen");
});

test("a far reference warns about seasons, and the picker lists the nearest images first", () => {
  const ctx = load();
  const day = vm.runInContext("days[2]", ctx);
  assert.equal(ctx.daysApart("2026-01-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00") > 45, true);
  vm.runInContext('referenceChoices.set("b.jpg", { mode: "chosen", item: { sequence_id: "seq-z", run_id: "run-z", filename: "z.jpg", capturedAtUtc: "2025-06-01T00:00:00+00:00" } });', ctx);
  assert.match(ctx.referenceControlsHtml(day), /days away from this image\. Seasons and lighting can differ/);
  ctx.cands = { sequences: [{ sequence_id: "seq-z", label: "Other set" }], images: [
    { sequence_id: "seq-z", run_id: "r", filename: "far.jpg", captured_at_utc: "2025-01-01T00:00:00+00:00" },
    { sequence_id: "seq-z", run_id: "r", filename: "near.jpg", captured_at_utc: "2026-01-03T10:00:00+00:00" },
    { sequence_id: "seq-z", run_id: null, filename: "norun.jpg", captured_at_utc: "2026-01-03T11:00:00+00:00" },
    { sequence_id: "seq-a", run_id: "run-1", filename: "b.jpg", captured_at_utc: "2026-01-03T18:00:00+00:00" }
  ] };
  vm.runInContext("candidates = cands; pickerOpen = true;", ctx);
  const html = ctx.referencePickerHtml(day);
  assert.ok(html.indexOf("near.jpg") < html.indexOf("far.jpg"));
  assert.doesNotMatch(html, /norun\.jpg/); // an image with no validation run cannot be a reference
  assert.doesNotMatch(html, /data-ref-choose="seq-a\|b\.jpg"/); // not the image being reviewed
});

test("only each reviewer's latest blind label against the same reference is counted", () => {
  const ctx = load();
  withPoints(ctx, { "a.jpg": [
    review("reviewer-a", "water_level_rising"),
    review("Reviewer-A", "no_water_level_change", { label_revision: 2 }),
    review("reviewer-b", "water_level_rising", { review_stage: "informed" }),
    review("reviewer-c", "water_level_rising", { review_stage: "unspecified" }),
    review("reviewer-d", "water_level_rising", { reference: { sequence_id: "seq-a", filename: "other.jpg" } }),
    review("reviewer-e", "water_level_rising", { reference: { sequence_id: "seq-a", filename: "base.jpg" } })
  ] });
  const result = ctx.independentReviews(vm.runInContext("days[1]", ctx));
  assert.deepEqual(Array.from(result.counted.map((r) => r.reviewerId)).sort(), ["Reviewer-A", "reviewer-e"]);
  assert.equal(result.counted.find((r) => r.reviewerId === "Reviewer-A").label.human_label, "no_water_level_change");
  assert.equal(result.apart.length, 2); // the informed and the unstaged save: kept, not counted
});

test("an older review with no reference counts as against the run baseline", () => {
  const ctx = load();
  withPoints(ctx, { "a.jpg": [review("reviewer-a", "water_level_rising")] });
  const day = vm.runInContext("days[1]", ctx);
  assert.equal(ctx.reviewReferenceKey({ label: {} }), "seq-a|base.jpg");
  assert.equal(ctx.independentReviews(day).counted.length, 1);
  vm.runInContext('referenceChoices.set("a.jpg", { mode: "chosen", item: { sequence_id: "seq-z", run_id: "r", filename: "z.jpg", capturedAtUtc: "2026-01-01T00:00:00+00:00" } });', ctx);
  assert.equal(ctx.independentReviews(day).counted.length, 0); // a different reference starts again
});

test("evidence is hidden until this reviewer has a label, and a label after seeing it is informed", () => {
  const ctx = load();
  withPoints(ctx, { "a.jpg": [review("reviewer-a", "water_level_rising")] });
  vm.runInContext('reviewerId = "reviewer-a";', ctx);
  const day = vm.runInContext("days[1]", ctx);
  assert.equal(ctx.isRevealed(day), false); // labelled, but the evidence has not been shown
  assert.equal(ctx.stageForSave(day), "blind");
  ctx.markRevealed(day);
  assert.equal(ctx.isRevealed(day), true);
  assert.equal(ctx.stageForSave(day), "informed");
  vm.runInContext('reviewerId = "reviewer-b";', ctx);
  ctx.loadRevealed();
  assert.equal(ctx.stageForSave(day), "blind"); // another reviewer has seen nothing
  assert.equal(ctx.isRevealed(day), false);
  vm.runInContext('reviewerId = "";', ctx);
  assert.equal(ctx.reviewForCurrentReviewer(day), null);
});

test("the pair for a dataset is in time order whichever image is the reference", () => {
  const ctx = load();
  const day = vm.runInContext("days[1]", ctx); // 2026-01-02
  let pair = ctx.orderedPair(day); // baseline 2026-01-01 is earlier
  assert.equal(pair.earlier.filename, "base.jpg");
  assert.equal(pair.later.filename, "a.jpg");
  vm.runInContext('referenceChoices.set("a.jpg", { mode: "chosen", item: { sequence_id: "seq-z", run_id: "run-z", filename: "future.jpg", capturedAtUtc: "2026-02-01T00:00:00+00:00" } });', ctx);
  pair = ctx.orderedPair(day);
  assert.equal(pair.earlier.filename, "a.jpg");
  assert.equal(pair.later.filename, "future.jpg");
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.pairRef(pair.later))), { folder_name: "demo", run_id: "run-z", filename: "future.jpg" });
});

test("dataset requests follow the task: pairs for the pair tasks, a mask for segmentation", () => {
  const ctx = load();
  const day = vm.runInContext("days[1]", ctx);
  vm.runInContext('datasets = [{ dataset_id: "d-visual", task: "visual_change" }, { dataset_id: "d-seg", task: "water_segmentation" }, { dataset_id: "d-gauge", task: "gauge_height" }]; samResults = [{ filename: "a.jpg", status: "completed", review_status: "accepted", prompt: "river water", run_id: "sam-1", result_id: "r-1" }];', ctx);
  vm.runInContext('selectedDatasetId = "d-visual";', ctx);
  let request = ctx.datasetRequest(day);
  assert.equal(request.pair, true);
  assert.equal(request.body.earlier.filename, "base.jpg");
  vm.runInContext('selectedDatasetId = "d-seg";', ctx);
  request = ctx.datasetRequest(day);
  assert.equal(request.pair, false);
  assert.equal(request.body.mask_run_id, "sam-1");
  assert.equal(request.body.mask_result_id, "r-1");
  vm.runInContext('selectedDatasetId = "d-gauge";', ctx);
  assert.equal(ctx.datasetRequest(day).body.filename, "a.jpg");
});

test("the label needs the camera answer, records its stage and reference, and can be revised", () => {
  assert.match(script, /Say whether the camera view stayed the same/);
  assert.match(script, /review_stage: stage/);
  assert.match(script, /reference: referencePayload\(reference\)/);
  assert.match(script, /Save informed revision/);
  assert.match(script, /Revise my label/);
  assert.match(script, /Informed revision\./);
  assert.match(script, /not counted as an independent judgment/);
  assert.match(script, /data-camera="\$\{value\}"/);
  assert.match(script, /\{ s: "yes", m: "no", u: "unsure" \}/);
});

test("evidence can stay hidden across a batch, and revealing is remembered per reviewer", () => {
  assert.match(script, /Show the machine evidence right after I save/);
  assert.match(script, /Reveal evidence for this image/);
  assert.match(script, /Revise my label \(still blind\)/);
  assert.match(script, /openfloodai\.revealed\./);
  assert.match(script, /if \(saved && stage === "blind" && !autoReveal\)/);
});

test("datasets: eligibility is checked before adding, and a dataset can be created in the page", () => {
  assert.match(script, /\/api\/dataset-check/);
  assert.match(script, /Eligible: nothing has been added yet/);
  assert.match(script, /Not eligible for this dataset/);
  assert.match(script, /\/api\/dataset-create/);
  assert.match(script, /Visible water change \(human-judged pair\)/);
  assert.match(script, /judged this pair \(at least/);
  assert.match(script, /data-add-dataset \$\{savingDataset \|\| !eligible \? "disabled" : ""\}/);
});

test("zoomed images can be dragged and the two side-by-side images scroll together", () => {
  assert.match(script, /data-pan-group/);
  assert.match(script, /other\.scrollLeft = pane\.scrollLeft/);
  assert.match(script, /pane\.classList\.add\("panning"\)/);
  assert.match(css, /\.zoom-pane\.panning/);
});

test("the agreement note counts only independent reviewers and says a vote is not used", () => {
  const ctx = load();
  withPoints(ctx, { "a.jpg": [
    review("reviewer-a", "water_level_rising"),
    review("reviewer-b", "no_water_level_change"),
    review("reviewer-c", "water_level_rising", { review_stage: "informed" })
  ] });
  const html = ctx.agreementHtml(vm.runInContext("days[1]", ctx));
  assert.match(html, /Reviewers disagree/);
  assert.match(html, /no majority vote/);
  assert.match(html, /1 review made after seeing evidence, or by an older form, is kept but not counted/);
});

test("the zoom and opacity sliders update the pictures in place instead of redrawing the page", () => {
  // Redrawing on every move replaces the slider under the pointer, which ends the drag after one step.
  assert.doesNotMatch(script, /zoomControl\.addEventListener\("input", \(\) => \{[^}]*render\(\)/);
  assert.doesNotMatch(script, /opacityControl\.addEventListener\("input", \(\) => \{[^}]*render\(\)/);
  assert.match(script, /applyZoom\(Number\(zoomControl\.value\)\)/);
  assert.match(script, /applyOpacity\(Number\(opacityControl\.value\)\)/);

  const styles = [];
  const layers = [{ style: {} }, { style: {} }];
  const images = [{ style: {} }];
  const overlay = [{ style: {} }];
  const labels = [{ textContent: "Current 50%" }];
  const ctx = load({
    document: {
      addEventListener() {},
      querySelector: () => null,
      querySelectorAll: (selector) => ({ ".zoom-layer": layers, ".overlay-compare img": images, ".overlay-current": overlay, ".image-corner.right": labels }[selector] || [])
    }
  });
  ctx.applyZoom(2.5);
  assert.equal(vm.runInContext("zoom", ctx), 2.5);
  assert.deepEqual(layers.map((i) => i.style.width), ["250%", "250%"]);
  assert.equal(images[0].style.width, "250%");
  ctx.applyOpacity(30);
  assert.equal(overlay[0].style.opacity, "0.3");
  assert.equal(labels[0].textContent, "Current 30%");
  assert.equal(styles.length, 0);
});

test("after the reveal the reference stays beside the current image in every view", () => {
  const ctx = load();
  vm.runInContext('detail.setup_used = { reference_region: { x: 10, y: 20, width: 50, height: 40 }, normal_waterline_guides: [{ id: "g1", status: "confirmed", points: [{ x: 20, y: 70 }, { x: 60, y: 55 }] }, { id: "g2", status: "invalid", points: [{ x: 1, y: 1 }, { x: 2, y: 2 }] }] };', ctx);
  vm.runInContext('samResults = [{ filename: "base.jpg", status: "completed", review_status: "accepted", run_id: "s1", result_id: "r-base" }, { filename: "a.jpg", status: "completed", review_status: "unreviewed", run_id: "s1", result_id: "r-a" }];', ctx);
  const day = vm.runInContext("days[1]", ctx);
  const reference = ctx.referenceFor(day);

  vm.runInContext('viewMode = "segmentation";', ctx);
  const segRef = ctx.evidencePaneHtml(reference, "Reference", "t", false);
  const segCur = ctx.evidencePaneHtml(day, "Current", "t", true);
  assert.match(segRef, /result_id=r-base/);
  assert.match(segRef, /Accepted water mask/);
  assert.match(segCur, /result_id=r-a/);
  assert.match(segCur, /Draft water mask - unreviewed/);

  vm.runInContext('viewMode = "guide";', ctx);
  for (const html of [ctx.evidencePaneHtml(reference, "Reference", "t", false), ctx.evidencePaneHtml(day, "Current", "t", true)]) {
    assert.match(html, /class="guide-svg"/);
    assert.match(html, /points="20,70 60,55"/); // the confirmed base guide
    assert.doesNotMatch(html, /points="1,1 2,2"/); // an invalid guide is never drawn
    assert.match(html, /<rect x="10" y="20" width="50" height="40"/); // the watched area
  }
  vm.runInContext('detail.setup_used = {};', ctx);
  assert.match(ctx.evidencePaneHtml(reference, "Reference", "t", false), /No normal guide is saved for this run/);

  vm.runInContext('viewMode = "original";', ctx);
  assert.doesNotMatch(ctx.evidencePaneHtml(reference, "Reference", "t", false), /guide-svg|hosted-sam/);
  assert.match(script, /The reference is always shown beside the current image/);
  assert.doesNotMatch(script, /\["compare", "Reference"\]/); // no separate tab: it is never hidden
});

test("a reference from another sequence loads that sequence's segmentation once", async () => {
  const calls = [];
  const ctx = load({ api: async (url) => { calls.push(url); return { results: [{ filename: "z.jpg", status: "completed", review_status: "accepted", run_id: "s9", result_id: "r-z" }] }; } });
  vm.runInContext("render = function () {};", ctx); // the redraw after the fetch is not under test
  const item = { sequence_id: "seq-z", filename: "z.jpg" };
  assert.equal(ctx.segmentationForImage(item), null); // first call starts the fetch
  assert.equal(ctx.segmentationForImage(item), null); // still loading: no second request
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(calls.length, 1);
  assert.match(calls[0], /sequence_id=seq-z/);
  assert.equal(ctx.segmentationForImage(item).result_id, "r-z");
});

test("the segmentation and guide views can also be blended as an overlay", () => {
  const ctx = load();
  vm.runInContext('detail.setup_used = { normal_waterline_guides: [{ id: "g1", status: "confirmed", points: [{ x: 20, y: 70 }, { x: 60, y: 55 }] }] }; samResults = [{ filename: "base.jpg", status: "completed", review_status: "accepted", run_id: "s1", result_id: "r-base" }, { filename: "a.jpg", status: "completed", review_status: "unreviewed", run_id: "s1", result_id: "r-a" }]; compareMode = "overlay"; overlayOpacity = 35;', ctx);
  const day = vm.runInContext("days[1]", ctx);

  vm.runInContext('viewMode = "segmentation";', ctx);
  let html = ctx.stageHtml(day);
  assert.match(html, /Side by side/);
  assert.match(html, /data-compare="overlay" aria-pressed="true"/); // the same switch as the original view
  assert.match(html, /overlay-compare/);
  assert.match(html, /result_id=r-base/); // the reference's own mask underneath
  assert.match(html, /overlay-current" style="width:100%;opacity:0\.35"[^>]*><img src="[^"]*result_id=r-a/);
  assert.match(html, /Current 35%/);
  assert.match(html, /<strong>Reference:<\/strong> Accepted water mask/);
  assert.match(html, /<strong>Current:<\/strong> Draft water mask - unreviewed/);

  vm.runInContext('viewMode = "guide";', ctx);
  html = ctx.stageHtml(day);
  assert.equal((html.match(/class="guide-svg"/g) || []).length, 2); // the base guide on both layers
  assert.match(html, /overlay-compare/);

  vm.runInContext('compareMode = "side";', ctx);
  html = ctx.stageHtml(day);
  assert.doesNotMatch(html, /overlay-compare/);
  assert.equal((html.match(/class="pair-image"/g) || []).length, 2);
  assert.match(script, /querySelectorAll\("\.overlay-current"\)/); // the opacity slider moves these layers
});
