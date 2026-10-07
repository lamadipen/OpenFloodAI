const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../../tools/console/review.html"), "utf8");
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
