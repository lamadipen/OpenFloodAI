const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const dir = path.join(__dirname, "../../tools/console");
const read = (name) => fs.readFileSync(path.join(dir, name), "utf8");
const escapeHtml = (v) => String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function reviewContext() {
  const sandbox = {
    escapeHtml,
    folderName: "site-a",
    runId: "run-1",
    days: [{ filename: "img.jpg", code: "N", date: "2026-01-02", time: "10:00" }],
    state: { selectedIndex: 0 },
    samState: { results: [] },
    formatUtc: (v) => String(v),
    api: async () => ({ datasets: [] }),
    $: () => null,
    localStorage: { getItem: () => "", setItem() {} },
    URLSearchParams
  };
  vm.createContext(sandbox);
  vm.runInContext(read("review-datasets.js"), sandbox);
  sandbox.dsState = vm.runInContext("dsState", sandbox); // a script-level let is not a global property
  return sandbox;
}

const DS = (task, extra = {}) => ({ dataset_id: "d1", name: "My set", task, task_title: "Title", included: 2, ...extra });
const SEL = { filename: "img.jpg", code: "N" };

test("the review panel explains what the chosen task needs and links to the dataset", () => {
  const c = reviewContext();
  c.dsState.datasets = [DS("gauge_height")];
  c.dsState.selectedId = "d1";
  const html = c.datasetPanelHtml(SEL);
  assert.match(html, /Add to dataset/);
  assert.match(html, /Nothing is trained, uploaded or published/);
  assert.match(html, /own matched gauge reading/);
  assert.match(html, /datasets\.html\?dataset_id=d1/);
  assert.match(html, /data-ds-act="add"/);
});

test("with no datasets the panel points to creating one", () => {
  const c = reviewContext();
  assert.match(c.datasetPanelHtml(SEL), /No datasets yet/);
});

test("a day with no image offers nothing to add", () => {
  const c = reviewContext();
  assert.match(c.datasetPanelHtml({ filename: "", code: "M" }), /no saved image/);
});

test("a mask picker appears only when more than one accepted mask exists for the image", () => {
  const c = reviewContext();
  c.dsState.datasets = [DS("water_segmentation")];
  c.dsState.selectedId = "d1";
  const accepted = (id) => ({ filename: "img.jpg", status: "completed", review_status: "accepted", result_id: id, prompt: "river water", processed_at_utc: "t" });
  c.samState.results = [accepted("r1")];
  assert.doesNotMatch(c.datasetPanelHtml(SEL), /id="dsMask"/);
  c.samState.results = [accepted("r1"), accepted("r2")];
  assert.match(c.datasetPanelHtml(SEL), /id="dsMask"/);
  c.samState.results = [{ ...accepted("r3"), review_status: "unreviewed" }, accepted("r1")];
  assert.doesNotMatch(c.datasetPanelHtml(SEL), /id="dsMask"/);
});

test("a rising/falling dataset offers an explicit earlier and later choice, never an automatic pair", () => {
  const c = reviewContext();
  c.dsState.datasets = [DS("level_change")];
  c.dsState.selectedId = "d1";
  const before = c.datasetPanelHtml(SEL);
  assert.match(before, /data-ds-act="set-earlier"/);
  assert.match(before, /data-ds-act="add-pair" disabled/);
  assert.doesNotMatch(before, /data-ds-act="add"/);
  c.dsState.pairEarlier = { filename: "old.jpg" };
  const after = c.datasetPanelHtml(SEL);
  assert.match(after, /Earlier image: <strong>old\.jpg/);
  assert.doesNotMatch(after, /add-pair" disabled/);
});

test("an ineligible result lists every reason; a conflict offers replace or keep; text is escaped", () => {
  const c = reviewContext();
  c.dsState.datasets = [DS("gauge_height")];
  c.dsState.selectedId = "d1";
  c.dsState.result = {
    status: "ineligible",
    reasons: [{ severity: "error", message: "No gauge <b>reading</b>" }, { severity: "warning", message: "Provisional" }]
  };
  const html = c.datasetPanelHtml(SEL);
  assert.match(html, /does not meet the task's evidence rules/);
  assert.match(html, /No gauge &lt;b&gt;reading&lt;\/b&gt;/);
  assert.match(html, /Provisional/);
  c.dsState.result = {
    conflict: true,
    existing: { kind: "gauge_height", value: 4, unit: "ft", station_nwis_id: "1" },
    new: { kind: "gauge_height", value: 4.5, unit: "ft", station_nwis_id: "1" }
  };
  const conflict = c.datasetPanelHtml(SEL);
  assert.match(conflict, /different annotation/);
  assert.match(conflict, /data-ds-decision="replace"/);
  assert.match(conflict, /data-ds-decision="keep"/);
  assert.match(conflict, /4 ft/);
  assert.match(conflict, /4\.5 ft/);
});

test("annotations are summarised in plain words for each task", () => {
  const c = reviewContext();
  assert.match(c.annotationSummary({ kind: "level_category", category: "high", gauge_value: 6.1, unit: "ft", definition: { version: 2 } }), /high \(6\.1 ft, definition v2\)/);
  assert.match(c.annotationSummary({ kind: "water_mask", masks: [1, 2], prompt: "river water" }), /2 accepted mask file/);
  assert.match(c.annotationSummary({ kind: "level_change", delta: -2.5, unit: "ft", elapsed_seconds: 7200, direction: "falling" }), /change -2\.5 ft over 2 h \(falling\)/);
});

function pageContext() {
  const sandbox = {
    escapeHtml,
    qs: () => "",
    $: () => null,
    api: async () => ({}),
    keepFocus: (root, fn) => fn(),
    mountShell: () => ({}),
    URLSearchParams,
    fetch: async () => ({}),
    location: {},
    document: { querySelectorAll: () => [], querySelector: () => null }
  };
  vm.createContext(sandbox);
  vm.runInContext(read("datasets.js"), sandbox);
  return sandbox;
}

const VIEW = (over = {}) => ({
  dataset: { name: "Heights <x>", task: "gauge_height", task_title: "Gauge-height estimation", split_policy: { kind: "site_camera", assignments: {} }, label_definitions: {} },
  members: [],
  label_counts: { examples: 0, cameras: [], by_split: {}, by_human_label: {} },
  blocking: [],
  readiness_gaps: [],
  duplicates: [],
  ready_to_freeze: false,
  versions: [],
  ...over
});

test("the dataset page says why a dataset cannot be frozen, and escapes names", () => {
  const c = pageContext();
  const html = c.detailHtml(VIEW({ blocking: [{ code: "split_unassigned", message: "The camera CAM_A is not assigned", member_id: "abc" }] }));
  assert.match(html, /Not ready to freeze/);
  assert.match(html, /The camera CAM_A is not assigned/);
  assert.match(html, /Heights &lt;x&gt;/);
  assert.match(html, /id="freezeBtn" disabled/);
});

test("a ready dataset can be frozen, and readiness gaps are shown without blocking it", () => {
  const c = pageContext();
  const html = c.detailHtml(VIEW({ ready_to_freeze: true, readiness_gaps: [{ code: "insufficient_independent_cameras", message: "No camera is assigned to: validation, test." }] }));
  assert.match(html, /Ready to freeze/);
  assert.match(html, /Readiness gaps/);
  assert.doesNotMatch(html, /id="freezeBtn" disabled/);
});

test("the split card offers by-camera and time-block policies and warns about the time-block limits", () => {
  const c = pageContext();
  const html = c.detailHtml(VIEW({ label_counts: { examples: 1, cameras: ["CAM_A"], by_split: {}, by_human_label: {} } }));
  assert.match(html, /data-camera="CAM_A"/);
  assert.match(html, /By time blocks within one site \(site-specific evaluation only\)/);
  assert.match(html, /does not meet the publication rule/);
});

test("category definitions are only offered for classification datasets and say they are not flood thresholds", () => {
  const c = pageContext();
  assert.doesNotMatch(c.detailHtml(VIEW()), /Category definitions/);
  const classification = VIEW();
  classification.dataset.task = "level_classification";
  const html = c.detailHtml(classification);
  assert.match(html, /Category definitions/);
  assert.match(html, /not flood thresholds/);
  assert.match(html, /A change is a new version/);
});

test("examples show rejection notes, problems and a remove button that only edits the draft", () => {
  const c = pageContext();
  const member = (over) => ({ member_id: "m1", kind: "observation", status: "included", observation: { site: "s", camera_id: "CAM", captured_at_utc: "2026-01-02T10:00:00+00:00", filename: "a.jpg", later_filename: null }, runs: ["r"], annotation: { kind: "gauge_height", value: 4, unit: "ft" }, warnings: [], problems: [], split: "train", ...over });
  const html = c.membersHtml(VIEW({ members: [member({}), member({ member_id: "m2", status: "rejected", annotation: null, rejection_note: "Glare <i>hides</i> it" }), member({ member_id: "m3", problems: [{ message: "A kept copy changed." }] })] }));
  assert.match(html, /Included/);
  assert.match(html, /Rejected/);
  assert.match(html, /Glare &lt;i&gt;hides&lt;\/i&gt; it/);
  assert.match(html, /Needs attention/);
  assert.match(html, /Removing only takes an example out of the draft/);
  assert.equal((html.match(/data-remove=/g) || []).length, 3);
});

test("the shell links to the Datasets page", () => {
  const shared = read("shared.js");
  assert.match(shared, /href="\/console\/datasets\.html"/);
  assert.match(shared, /datasets:\s*\n?\s*'<svg/);
});

test("only accepted water masks are offered, and a choice names its segmentation run as well", () => {
  const c = reviewContext();
  c.dsState.datasets = [DS("water_segmentation")];
  c.dsState.selectedId = "d1";
  const accepted = (run, id, prompt) => ({ filename: "img.jpg", status: "completed", review_status: "accepted", run_id: run, result_id: id, prompt, processed_at_utc: "t" });
  c.samState.results = [accepted("runA", "001-x", "riverbank"), accepted("runA", "002-x", "river water"), accepted("runB", "002-x", "water")];

  const choices = c.acceptedMaskChoices(SEL);
  assert.deepEqual(choices.map((m) => m.prompt), ["river water", "water"]);
  const html = c.datasetPanelHtml(SEL);
  assert.match(html, /value="runA\|002-x"/);
  assert.match(html, /value="runB\|002-x"/);
  const picker = html.slice(html.indexOf('id="dsMask"'), html.indexOf("</select>", html.indexOf('id="dsMask"')));
  assert.doesNotMatch(picker, /riverbank/);
  assert.match(html, /not a riverbank mask/);
});
