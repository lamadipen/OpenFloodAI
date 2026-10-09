const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = require("./review_source.cjs").reviewHtml();
const script = html.split("<script>").pop().split("</script>")[0];
const slice = script.slice(
  script.indexOf("// ---- Human-label progress and image-to-image navigation"),
  script.indexOf("function counts() {")
);

function make({ days, labelled = [], filter = null, selectedIndex = 0 }) {
  const rendered = [];
  const sandbox = {
    days,
    evidencePoints: labelled.map((filename) => ({ filename, label: { human_label: "no_water_level_change" } })),
    state: { filter, selectedIndex, eventCursor: -1 },
    CODE_LABEL: { P: "Possible", N: "No change", C: "Camera", U: "Cannot judge" },
    escapeHtml: String,
    render: () => rendered.push(sandbox.state.selectedIndex),
    history: { replaceState() {} },
    location: { href: "http://x/console/review.html?site=s&run_id=r" },
    compareReset() {}, // selecting an image ends any open comparison (review-compare.js)
    URL
  };
  vm.createContext(sandbox);
  vm.runInContext(slice, sandbox);
  sandbox.rendered = rendered;
  return sandbox;
}

const day = (n, code = "N") => ({ filename: code === "M" ? "" : `img${n}.jpg`, code, date: `2026-01-0${n}`, time: "12:00" });
const DAYS = [day(1), day(2, "P"), day(3, "M"), day(4), day(5, "C")];

test("stepping moves between images and skips days with no picture", () => {
  const s = make({ days: DAYS });
  s.stepSelection(1);
  assert.equal(s.state.selectedIndex, 1);
  s.stepSelection(1);
  assert.equal(s.state.selectedIndex, 3); // index 2 has no image
  s.stepSelection(-1);
  assert.equal(s.state.selectedIndex, 1);
});

test("stepping stops at the ends instead of wrapping", () => {
  const s = make({ days: DAYS, selectedIndex: 0 });
  s.stepSelection(-1);
  assert.equal(s.state.selectedIndex, 0);
  assert.equal(s.rendered.length, 0);
  const last = make({ days: DAYS, selectedIndex: 4 });
  last.stepSelection(1);
  assert.equal(last.state.selectedIndex, 4);
});

test("an active filter limits which images are stepped through", () => {
  const s = make({ days: DAYS, filter: "N", selectedIndex: 0 });
  s.stepSelection(1);
  assert.equal(s.state.selectedIndex, 3);
});

test("the progress counts labelled images out of images that have a picture", () => {
  const s = make({ days: DAYS, labelled: ["img1.jpg", "img4.jpg"] });
  assert.deepEqual(JSON.parse(JSON.stringify(s.labelProgress())), { done: 2, total: 4 });
  assert.equal(s.isLabelled(0), true);
  assert.equal(s.isLabelled(1), false);
  assert.equal(s.humanLabelFor(DAYS[0]), "No water-level change");
});

test("next unlabelled finds the following image, then wraps, then reports none left", () => {
  const s = make({ days: DAYS, labelled: ["img1.jpg", "img2.jpg"] });
  assert.equal(s.nextUnlabelledFrom(0), 3);
  assert.equal(s.nextUnlabelledFrom(4), 3);
  const done = make({ days: DAYS, labelled: ["img1.jpg", "img2.jpg", "img4.jpg", "img5.jpg"] });
  assert.equal(done.nextUnlabelledFrom(0), -1);
});

test("the page wires arrow keys, a navigator and the label link back to the same image", () => {
  assert.match(script, /ArrowLeft/);
  assert.match(script, /data-act="next-unlabelled"/);
  assert.match(script, /select: sel\.filename/);
  const form = fs.readFileSync(path.join(__dirname, "../../tools/console/form-human-label.html"), "utf8");
  assert.match(form, /advance: "1"/);
});

const form = fs.readFileSync(path.join(__dirname, "../../tools/console/form-human-label.html"), "utf8");
const formScript = form.split("<script>").pop().split("</script>")[0];

test("the label form starts from an image's existing label and says it adds a revision", () => {
  const start = formScript.indexOf("function prefillFrom(");
  const end = formScript.indexOf("let state = {");
  const sandbox = {
    LABELS: [{ id: "no_water_level_change" }, { id: "water_level_rising" }],
    TRISTATE_FIELDS: [{ key: "camera_stable" }, { key: "riverbank_visible" }],
    state: { label: null, confidence: "medium", tristate: {}, crossingReview: null, overlayReview: null, pilotConditions: new Set() },
    $: () => sandbox.note
  };
  sandbox.note = { value: "" };
  vm.createContext(sandbox);
  vm.runInContext(formScript.slice(start, end), sandbox);

  assert.equal(sandbox.prefillFrom({ label: null }), null);
  const info = sandbox.prefillFrom({
    label: { human_label: "water_level_rising", confidence: "high", camera_stable: "yes", note: "looks higher" },
    review: { label_revision: 2, reviewed_at_utc: "2026-10-07T19:05:58+00:00", crossing_review: "change", pilot_conditions: ["glare"] }
  });
  assert.equal(sandbox.state.label, "water_level_rising");
  assert.equal(sandbox.state.confidence, "high");
  assert.equal(sandbox.state.tristate.camera_stable, "yes");
  assert.equal(sandbox.state.crossingReview, "change");
  assert.equal(sandbox.state.pilotConditions.has("glare"), true);
  assert.equal(sandbox.note.value, "looks higher");
  assert.equal(info.revision, 2);
  const text = sandbox.revisionNoteText(info);
  assert.match(text, /revision 2/);
  assert.match(text, /adds revision 3/);
  assert.match(text, /stays in the review history/);
});

test("a label that is not one of the choices is not preselected", () => {
  const start = formScript.indexOf("function prefillFrom(");
  const sandbox = {
    LABELS: [{ id: "no_water_level_change" }],
    TRISTATE_FIELDS: [],
    state: { label: null, confidence: "medium", tristate: {}, pilotConditions: new Set() },
    $: () => ({ value: "" })
  };
  vm.createContext(sandbox);
  vm.runInContext(formScript.slice(start, formScript.indexOf("let state = {")), sandbox);
  const info = sandbox.prefillFrom({ label: { human_label: "something_old" } });
  assert.equal(sandbox.state.label, null);
  assert.equal(info.known, false);
  assert.match(sandbox.revisionNoteText(info), /choose one/);
});

test("the review page offers Edit human label for a labelled image", () => {
  assert.match(script, /Edit human label/);
  assert.match(script, /labelRevisionFor/);
});

// ---- SAM review state shows beside each image ----------------------------------------------

function samContext(results) {
  const sandbox = {
    days: [day(1), day(2)],
    evidencePoints: [],
    state: { filter: null, selectedIndex: 0, eventCursor: -1 },
    CODE_LABEL: {},
    escapeHtml: String,
    SAM_REVIEW_TEXT: { unreviewed: "Unreviewed", accepted: "Accepted", rejected: "Rejected", needs_correction: "Needs correction" },
    samState: { results, status: {} }
  };
  vm.createContext(sandbox);
  vm.runInContext(slice, sandbox);
  return sandbox;
}

test("each image's SAM state is the newest completed result per prompt", () => {
  const s = samContext([
    { filename: "img1.jpg", prompt: "river water", status: "completed", review_status: "accepted" },
    { filename: "img1.jpg", prompt: "river water", status: "completed", review_status: "rejected" }, // older run
    { filename: "img1.jpg", prompt: "riverbank", status: "completed" },
    { filename: "img1.jpg", prompt: "riverbank", status: "failed", review_status: "accepted" },
    { filename: "img2.jpg", prompt: "river water", status: "no_match" }
  ]);
  assert.deepEqual(JSON.parse(JSON.stringify(s.samSummaryFor("img1.jpg"))), [
    { prompt: "river water", review: "accepted" },
    { prompt: "riverbank", review: "unreviewed" }
  ]);
  assert.equal(s.samSummaryFor("img2.jpg").length, 0);
  assert.match(s.samPillsHtml("img1.jpg"), /SAM river water: accepted/);
  assert.match(s.samPillsHtml("img1.jpg"), /pill ok/);
  assert.equal(s.samAcceptedCount(), 1);
});

test("the SAM result buttons mark the saved decision and the page refreshes after a review", () => {
  assert.match(script, /aria-pressed="\$\{review === d\}"/);
  assert.match(script, /Review saved\. This is separate from human labels\."\);\s*render\(\);/);
});

// ---- comparison view switch ----------------------------------------------------------------

function compareContext(stored) {
  const start = script.indexOf("// Which comparison views are shown");
  const sandbox = {
    state: { compareView: "side" },
    compareButtonHtml: () => "",
    comparePickerHtml: () => "",
    localStorage: {
      store: stored === undefined ? {} : { "openfloodai.reviewCompareView": stored },
      getItem(k) { return this.store[k] ?? null; },
      setItem(k, v) { this.store[k] = v; }
    }
  };
  vm.createContext(sandbox);
  vm.runInContext(script.slice(start, script.indexOf("function counts() {")), sandbox);
  return sandbox;
}

test("the comparison view defaults to side by side and remembers a valid choice", () => {
  assert.equal(compareContext().loadCompareView(), "side");
  assert.equal(compareContext("overlay").loadCompareView(), "overlay");
  assert.equal(compareContext("both").loadCompareView(), "both");
  assert.equal(compareContext("nonsense").loadCompareView(), "side");
  const c = compareContext();
  c.saveCompareView("both");
  assert.equal(c.loadCompareView(), "both");
});

test("a blocked browser store does not break the switch", () => {
  const c = compareContext();
  c.localStorage = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.equal(c.loadCompareView(), "side");
  assert.doesNotThrow(() => c.saveCompareView("overlay"));
});

test("the switch marks the active view and each view shows the right blocks", () => {
  const c = compareContext();
  c.state.compareView = "overlay";
  const html = c.compareSwitchHtml();
  assert.match(html, /data-value="overlay"[^>]*>Overlay/);
  assert.match(html, /aria-pressed="true" data-act="compare-view" data-value="overlay"/);
  assert.match(script, /const showSide = state\.compareView !== "overlay"/);
  assert.match(script, /const showOverlay = state\.compareView !== "side"/);
});

// ---- collapsible charts --------------------------------------------------------------------

function collapseContext(stored) {
  const start = script.indexOf("// The two charts can be folded away");
  const sandbox = {
    state: { collapsed: { gauge: false, region: false } },
    localStorage: {
      store: stored === undefined ? {} : { "openfloodai.reviewCollapsed": stored },
      getItem(k) { return this.store[k] ?? null; },
      setItem(k, v) { this.store[k] = v; }
    }
  };
  vm.createContext(sandbox);
  vm.runInContext(script.slice(start, script.indexOf("function counts() {")), sandbox);
  return sandbox;
}

test("both charts start open and remember being folded", () => {
  assert.deepEqual(JSON.parse(JSON.stringify(collapseContext().loadCollapsed())), { gauge: false, region: false });
  assert.deepEqual(JSON.parse(JSON.stringify(collapseContext('{"gauge":true}').loadCollapsed())), { gauge: true, region: false });
  assert.deepEqual(JSON.parse(JSON.stringify(collapseContext("not json").loadCollapsed())), { gauge: false, region: false });
  const c = collapseContext();
  c.toggleCollapsed("region");
  assert.equal(c.isCollapsed("region"), true);
  assert.equal(c.isCollapsed("gauge"), false);
  assert.deepEqual(JSON.parse(c.localStorage.store["openfloodai.reviewCollapsed"]), { gauge: false, region: true });
  c.toggleCollapsed("region");
  assert.equal(c.isCollapsed("region"), false);
});

test("a blocked browser store does not break folding", () => {
  const c = collapseContext();
  c.localStorage = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.deepEqual(JSON.parse(JSON.stringify(c.loadCollapsed())), { gauge: false, region: false });
  assert.doesNotThrow(() => c.toggleCollapsed("gauge"));
  assert.equal(c.isCollapsed("gauge"), true);
});

test("the header is a button that says whether its section is open", () => {
  const c = collapseContext();
  assert.match(c.collapseHeaderHtml("gauge", "Gage height"), /aria-expanded="true"/);
  c.toggleCollapsed("gauge");
  const html = c.collapseHeaderHtml("gauge", "Gage height");
  assert.match(html, /aria-expanded="false"/);
  assert.match(html, /select to show/);
  assert.match(script, /state = \{[^}]*collapsed: loadCollapsed\(\)/);
});

test("nothing used while the page state is created is declared after it (no temporal dead zone)", () => {
  const stateLine = script.indexOf("let state = {");
  const early = script.slice(0, stateLine);
  assert.doesNotMatch(early, /const COLLAPSE_KEY|const COMPARE_VIEWS/);
  const loaders = script.match(/function load(Compare|Collapsed)[A-Za-z]*\(\) \{[\s\S]*?\n\}/g).join("\n");
  assert.doesNotMatch(loaders, /COMPARE_VIEWS|COLLAPSE_KEY/);
});

// ---- the side-by-side view shows each picture once ------------------------------------------

function sideContext() {
  const start = script.indexOf("// The baseline and the selected image side by side, once");
  const sandbox = {
    samState: { target: "selected", status: null },
    samHighlightIndex: () => null,
    escapeHtml: String
  };
  vm.createContext(sandbox);
  vm.runInContext(script.slice(start, script.indexOf("function counts() {")), sandbox);
  return sandbox;
}

const SIDE_ARGS = {
  summary: { baseline_filename: "base.jpg" },
  sel: { date: "2026-01-02", time: "13:45", resultLabel: "No water level change" }
};

test("with a comparison available, only the comparison image is drawn, wrapped in a link to full size", () => {
  const html = sideContext().sideBySideHtml({ ...SIDE_ARGS, baselineQuery: "b=1", selectedQuery: "s=1", comparisonQuery: "c=1" });
  assert.equal((html.match(/<img /g) || []).length, 1);
  assert.match(html, /image-sequence-comparison\?c=1/);
  assert.doesNotMatch(html, /image-sequence-image\?/);
  assert.match(html, /<a href="\/api\/image-sequence-comparison\?c=1" target="_blank"/);
  assert.match(html, /Baseline &mdash; base\.jpg/);
  assert.match(html, /2026-01-02, 13:45 local \(No water level change\)/);
});

test("without a comparison the two plain pictures are shown instead", () => {
  const both = sideContext().sideBySideHtml({ ...SIDE_ARGS, baselineQuery: "b=1", selectedQuery: "s=1", comparisonQuery: null });
  assert.equal((both.match(/<img /g) || []).length, 2);
  const noDay = sideContext().sideBySideHtml({ ...SIDE_ARGS, baselineQuery: "b=1", selectedQuery: null, comparisonQuery: null });
  assert.match(noDay, /No image for this day\./);
});

test("the segmentation badge follows the image that will be sent", () => {
  const c = sideContext();
  c.samHighlightIndex = () => 3;
  const selected = c.sideBySideHtml({ ...SIDE_ARGS, baselineQuery: "b=1", selectedQuery: "s=1", comparisonQuery: "c=1" });
  assert.equal((selected.match(/Will be segmented/g) || []).length, 1);
  c.samHighlightIndex = () => null;
  c.samState = { target: "baseline", status: { enabled: true } };
  const baseline = c.sideBySideHtml({ ...SIDE_ARGS, baselineQuery: "b=1", selectedQuery: "s=1", comparisonQuery: "c=1" });
  assert.equal((baseline.match(/Will be segmented/g) || []).length, 1);
});

// ---- selected chart point stands out -------------------------------------------------------

function markContext() {
  const start = script.indexOf("// ---- Making the selected chart point obvious");
  const sandbox = {
    state: { selectedIndex: 2 },
    days: [{ date: "2026-01-01", time: "10:00" }, { date: "2026-01-02", time: "11:00" }, { date: "2026-01-03", time: "12:30" }],
    escapeHtml: String
  };
  vm.createContext(sandbox);
  vm.runInContext(script.slice(start, script.indexOf("function scoreChartSvg() {")), sandbox);
  return sandbox;
}

test("a point is selected when its bucket holds the selected image, not only when it is the representative", () => {
  const c = markContext();
  assert.equal(c.bucketIsSelected({ indices: [0, 1, 2], repIndex: 0 }), true);
  assert.equal(c.bucketIsSelected({ indices: [0, 1], repIndex: 0 }), false);
});

test("a point's tooltip names the day, time and value, and notes grouped images", () => {
  const c = markContext();
  assert.equal(c.pointTitle({ indices: [2], repIndex: 2, dayCount: 1 }, "4.29 ft"), "2026-01-03 12:30 · 4.29 ft");
  assert.match(c.pointTitle({ indices: [0, 1, 2], repIndex: 0, dayCount: 3 }, "score 0.1"), /\(3 images, one shown\)$/);
});

test("the selection marks are a column highlight, a guide line, a ring and a tag", () => {
  const c = markContext();
  const back = c.selectionBackdropSvg(100, 4, 120);
  assert.match(back, /<rect[^>]*opacity="0.10"/);
  assert.match(back, /<line[^>]*x1="100.0"/);
  const mark = c.selectionMarkerSvg(100, 60, 6, "2026-01-03 12:30 · 4.29 ft", 4, 50, 1040);
  assert.match(mark, /stroke="#1d2433" stroke-width="2.5"/);
  assert.match(mark, />2026-01-03 12:30 · 4\.29 ft</);
  assert.match(mark, /pointer-events="none"/); // the marks never block clicking another point
});

test("the tag stays inside the chart: flipped below near the top and clamped at the edges", () => {
  const c = markContext();
  const nearTop = c.selectionMarkerSvg(100, 10, 6, "tag", 4, 50, 1040);
  assert.match(nearTop, /<rect x="[\d.]+" y="(2[0-9]|3[0-9])\./); // below the dot
  const nearLeft = c.selectionMarkerSvg(52, 100, 6, "a long tag text here", 4, 50, 1040);
  const x = Number(nearLeft.match(/<rect x="([\d.]+)"/)[1]);
  assert.ok(x >= 50);
  const nearRight = c.selectionMarkerSvg(1038, 100, 6, "a long tag text here", 4, 50, 1040);
  const xr = Number(nearRight.match(/<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)"/)[1]);
  const wr = Number(nearRight.match(/<rect x="[\d.]+" y="[\d.]+" width="([\d.]+)"/)[1]);
  assert.ok(xr + wr <= 1040.01);
});

test("both charts draw the same marks, and every point is a labelled button", () => {
  assert.equal((script.match(/selectionMarkerSvg\(/g) || []).length, 3); // definition + two charts
  assert.equal((script.match(/selectionBackdropSvg\(/g) || []).length, 3);
  assert.equal((script.match(/role="button" tabindex="0" aria-label=/g) || []).length, 2);
  assert.match(html, /\.chart-point:hover/);
  assert.match(html, /prefers-reduced-motion: reduce\) \{ \.chart-point/);
});

test("chart points can be reached and pressed from the keyboard, and the page keeps focus after redrawing", () => {
  assert.match(script, /\[role="button"\]\[data-act\]/);
  assert.match(script, /event\.key !== "Enter" && event\.key !== " "/);
  assert.match(script, /function render\(\) \{\s*keepFocus\(\$\("content"\), renderNow\);/);
});
