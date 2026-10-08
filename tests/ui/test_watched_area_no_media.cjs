const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const read = (name) => fs.readFileSync(path.join(__dirname, "../../tools/console", name), "utf8");
const scriptOf = (html) => html.split("<script>").pop().split("</script>")[0];

const NO_MEDIA = "This site has no downloaded image sequence and no video yet. Add media first from Site &rarr; Setup &rarr; Add media.";

function mainSource(html) {
  const script = scriptOf(html);
  const start = script.indexOf("async function main() {");
  const end = script.indexOf("\n}\n", start) + 3;
  return script.slice(start, end);
}

// Runs the page's own main() against a stub page. The Save button lives INSIDE #body, so
// once the body's content is replaced it no longer exists, exactly as in the real page.
async function runWatchedArea(apiResponses, overrides = {}) {
  const state = { body: "<button id=saveBtn></button>", hasSaveButton: true, saveDisabledSet: 0 };
  const sandbox = {
    folderName: "site-a",
    saved: null, rect: { x: 1, y: 1, width: 2, height: 2 },
    sequenceId: null, baselineFilename: null, videoId: null,
    escapeHtml: (v) => String(v),
    URLSearchParams,
    paintBox() {},
    loadVideoSource: async () => {},
    document: { body: {} },
    ...overrides,
    api: async (url) => {
      const key = Object.keys(apiResponses).find((k) => url.startsWith(k));
      if (!key) throw new Error("unexpected " + url);
      return apiResponses[key];
    },
    $: (id) => {
      if (id === "body") {
        return { set innerHTML(value) { state.body = value; state.hasSaveButton = false; }, get innerHTML() { return state.body; } };
      }
      if (id === "saveBtn") {
        if (!state.hasSaveButton) return null; // removed together with the replaced body
        return { set disabled(v) { state.saveDisabledSet += 1; } };
      }
      return { href: "", textContent: "", style: {}, set src(v) {}, setAttribute() {}, addEventListener() {}, set value(v) {}, set innerHTML(v) {}, set hidden(v) {}, set max(v) {}, set step(v) {} };
    }
  };
  vm.createContext(sandbox);
  const html = read("form-watched-area.html");
  const script = scriptOf(html);
  const helperStart = script.indexOf("// Downloaded images of one sequence");
  const helperSource = script.slice(helperStart, script.indexOf("async function main() {"));
  vm.runInContext(helperSource + "\n" + mainSource(html) + "\nmain;", sandbox);
  await vm.runInContext("main()", sandbox);
  state.sandbox = sandbox;
  return state;
}

const EMPTY = {
  "/api/site-config": { config: { reference_region: null } },
  "/api/site-image-sequences": { sequences: [] },
  "/api/site-manifest": { records: [] }
};

test("a site with no media shows the no-media message, not a script error", async () => {
  const state = await runWatchedArea(EMPTY);
  assert.equal(state.body.includes("Could not load this site"), false);
  assert.match(state.body, /This site has no downloaded image sequence and no video yet\./);
  assert.match(state.body, /Add media first from Site &rarr; Setup &rarr; Add media\./);
});

test("the watched-area message matches the riverbank guides message exactly", () => {
  const guide = read("form-waterline-guide.html");
  const area = read("form-watched-area.html");
  assert.ok(guide.includes(NO_MEDIA), "guides editor message");
  assert.ok(area.includes(NO_MEDIA), "watched area message");
});

test("a site with a downloaded image sequence still loads the editor", async () => {
  const state = await runWatchedArea({
    ...EMPTY,
    "/api/site-image-sequences": {
      sequences: [{ sequence_id: "seq", records: [{ filename: "a.jpg", download_status: "downloaded" }] }]
    }
  });
  assert.equal(state.body.includes("This site has no downloaded"), false);
  assert.equal(state.body.includes("Could not load"), false);
});

test("a real loading failure is still reported as one", async () => {
  const state = await runWatchedArea({ "/api/site-config": null });
  assert.match(state.body, /Could not load this site/);
});

test("nothing in main() touches the Save button after the body was replaced", () => {
  const src = mainSource(read("form-watched-area.html"));
  const afterReplace = src.slice(src.indexOf("This site has no downloaded"));
  assert.doesNotMatch(afterReplace.split("catch")[0], /saveBtn/);
});

// ---- which sequence supplies the image ----------------------------------------------------

function helperOf(html) {
  const script = scriptOf(html);
  const start = script.indexOf("function pickImageSource(");
  const end = script.indexOf("\n}\n", start) + 3;
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(script.slice(start, end), sandbox);
  return sandbox.pickImageSource;
}

const downloaded = (name) => ({ filename: name, download_status: "downloaded" });
const missing = { filename: "", download_status: "missing" };
const OLDER = { sequence_id: "usgs-CAM-2026-08-01-2026-09-03-all", records: [downloaded("old1.jpg"), downloaded("old2.jpg")] };
const NEWER_EMPTY = { sequence_id: "usgs-CAM-2026-10-01-2026-10-02-one_daylight_image_per_day", records: [missing, missing] };
const NEWEST = { sequence_id: "usgs-CAM-2026-10-01-2026-10-02-water_level-0a1b2c3d", records: [downloaded("new1.jpg")] };

for (const file of ["form-waterline-guide.html"]) {
  test(`${file}: a newer sequence with no downloaded image does not hide an older one`, () => {
    const pick = helperOf(read(file));
    assert.deepEqual(JSON.parse(JSON.stringify(pick([OLDER, NEWER_EMPTY]))), { sequenceId: OLDER.sequence_id, filename: "old1.jpg" });
  });

  test(`${file}: the newest sequence that has an image is preferred`, () => {
    const pick = helperOf(read(file));
    assert.equal(pick([OLDER, NEWER_EMPTY, NEWEST]).sequenceId, NEWEST.sequence_id);
    assert.equal(pick([NEWEST, NEWER_EMPTY]).sequenceId, NEWEST.sequence_id);
  });

  test(`${file}: no sequence, only empty ones, or missing records give no image source`, () => {
    const pick = helperOf(read(file));
    assert.equal(pick([]), null);
    assert.equal(pick([NEWER_EMPTY]), null);
    assert.equal(pick([{ sequence_id: "x" }]), null);
  });
}

test("the watched-area editor loads the older sequence's image when the newest one is empty", async () => {
  const state = await runWatchedArea({
    ...EMPTY,
    "/api/site-image-sequences": { sequences: [OLDER, NEWER_EMPTY] }
  });
  assert.equal(state.body.includes("This site has no downloaded"), false);
  assert.equal(state.body.includes("Could not load"), false);
});

// ---- sequence dropdown + image slider in the watched-area editor ---------------------------

function areaHelpers() {
  const script = scriptOf(read("form-watched-area.html"));
  const start = script.indexOf("// Downloaded images of one sequence");
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(script.slice(start, script.indexOf("let imageSequences")), sandbox);
  return sandbox;
}

test("a sequence's images are ordered oldest capture first, skipping undownloaded ones", () => {
  const { downloadedImages } = areaHelpers();
  const out = downloadedImages({
    records: [
      { filename: "b.jpg", download_status: "downloaded", captured_at_utc: "2026-03-04T18:05:00+00:00" },
      { filename: "", download_status: "missing" },
      { filename: "a.jpg", download_status: "downloaded", captured_at_utc: "2026-03-01T18:05:00+00:00" }
    ]
  });
  assert.deepEqual(out.map((r) => r.filename), ["a.jpg", "b.jpg"]);
  assert.equal(downloadedImages(null).length, 0);
});

test("the dropdown label uses the display name when there is one, else the id, with the image count", () => {
  const { sequenceOptionLabel } = areaHelpers();
  const records = [{ filename: "a.jpg", download_status: "downloaded" }];
  assert.equal(sequenceOptionLabel({ sequence_id: "seq-1", records }), "seq-1 (1 images)");
  assert.equal(sequenceOptionLabel({ sequence_id: "seq-1", display_name: "Spring", records }), "Spring (1 images)");
});

test("the caption shows the file name with the local time and the UTC time", () => {
  const { imageCaptionText } = areaHelpers();
  assert.equal(
    imageCaptionText({ filename: "a.jpg", local_time: "2026-03-01T11:05:00-07:00", captured_at_utc: "2026-03-01T18:05:00+00:00" }),
    "a.jpg \u00b7 local 2026-03-01 11:05:00-07:00 \u00b7 UTC 2026-03-01 18:05:00"
  );
  assert.equal(imageCaptionText({ filename: "a.jpg" }), "a.jpg");
});

test("the watched-area page has the sequence dropdown, the caption and the image slider", () => {
  const html = read("form-watched-area.html");
  assert.match(html, /id="sequenceSelect"/);
  assert.match(html, /id="imageCaption"/);
  assert.match(html, /id="scrub"/);
});

test("the gauge line shows the level, unit, group and quality, or says none is saved", () => {
  const { gaugeReadingText } = areaHelpers();
  assert.equal(gaugeReadingText({ level: 3.15, unit: "ft", group: "low", quality_status: "approved" }), "Gauge 3.15 ft \u00b7 low \u00b7 approved");
  assert.equal(gaugeReadingText({ level: 11.549999999999999, unit: "ft" }), "Gauge 11.55 ft");
  assert.equal(gaugeReadingText(undefined), "No gauge reading saved for this image");
  assert.equal(gaugeReadingText({}), "No gauge reading saved for this image");
});

// ---- the Riverbank editor shows the frame the watched area was drawn on ----------------------

function guideHelpers() {
  const html = read("form-waterline-guide.html");
  const script = scriptOf(html);
  const start = script.indexOf("// Which image or video moment to show.");
  const sandbox = { ...require("../../tools/console/guide-source-matching.js") };
  vm.createContext(sandbox);
  vm.runInContext(script.slice(start, script.indexOf("async function main() {")), sandbox);
  return sandbox;
}

const rec = (name) => ({ filename: name, download_status: "downloaded", local_time: "2026-03-01T11:05:00-07:00" });
const SEQS = [{ sequence_id: "seq-1", records: [rec("a.jpg"), rec("b.jpg")] }];
const plain = (o) => JSON.parse(JSON.stringify(o));

test("the baseline is the image the watched area was drawn on, even when other images exist", () => {
  const { chooseBaselineSource } = guideHelpers();
  const area = { image_sequence_id: "seq-1", image_filename: "b.jpg" };
  const out = plain(chooseBaselineSource({ areaSource: area, guide: null, sequences: SEQS }));
  assert.deepEqual(out.source, area);
  assert.equal(out.fromWatchedArea, true);
});

test("guides traced on the same image keep that image, which is the watched-area image", () => {
  const { chooseBaselineSource } = guideHelpers();
  const area = { image_sequence_id: "seq-1", image_filename: "b.jpg" };
  const guide = { image_sequence_id: "seq-1", image_filename: "b.jpg" };
  assert.equal(chooseBaselineSource({ areaSource: area, guide, sequences: SEQS }).fromWatchedArea, true);
});

test("guides traced on a different image keep their own image so the lines line up", () => {
  const { chooseBaselineSource } = guideHelpers();
  const area = { image_sequence_id: "seq-1", image_filename: "b.jpg" };
  const guide = { image_sequence_id: "seq-1", image_filename: "a.jpg" };
  const out = plain(chooseBaselineSource({ areaSource: area, guide, sequences: SEQS }));
  assert.equal(out.source.image_filename, "a.jpg");
  assert.equal(out.fromWatchedArea, false);
  assert.equal(out.areaSource.image_filename, "b.jpg");
});

test("a watched-area image that is no longer on disk is not shown", () => {
  const { chooseBaselineSource } = guideHelpers();
  const area = { image_sequence_id: "seq-1", image_filename: "gone.jpg" };
  assert.equal(chooseBaselineSource({ areaSource: area, guide: null, sequences: SEQS }).source, null);
});

test("with no recorded watched-area image the editor falls back as before", () => {
  const { chooseBaselineSource } = guideHelpers();
  assert.equal(chooseBaselineSource({ areaSource: undefined, guide: null, sequences: SEQS }).source, null);
});

test("the note names the image and time the watched area was drawn on", () => {
  const { describeAreaSource } = guideHelpers();
  assert.equal(
    describeAreaSource({ image_sequence_id: "seq-1", image_filename: "b.jpg" }, SEQS),
    "Watched area was drawn on b.jpg (2026-03-01 11:05:00-07:00)."
  );
  assert.equal(describeAreaSource(null, SEQS), "");
});

// ---- reopening on the previously saved image and region -----------------------------------

function savedImageHelper() {
  const script = scriptOf(read("form-watched-area.html"));
  const helpers = script.slice(script.indexOf("// Downloaded images of one sequence"), script.indexOf("let imageSequences"));
  const start = script.indexOf("function savedImageStillAvailable(");
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(helpers + script.slice(start, script.indexOf("\n}\n", start) + 3), sandbox);
  return sandbox.savedImageStillAvailable;
}

test("the saved watched-area image counts as available only while it is still downloaded", () => {
  const available = savedImageHelper();
  const seqs = [{ sequence_id: "seq-1", records: [rec("a.jpg"), { filename: "gone.jpg", download_status: "missing" }] }];
  assert.equal(available({ image_sequence_id: "seq-1", image_filename: "a.jpg" }, seqs), true);
  assert.equal(available({ image_sequence_id: "seq-1", image_filename: "gone.jpg" }, seqs), false);
  assert.equal(available({ image_sequence_id: "other", image_filename: "a.jpg" }, seqs), false);
  assert.equal(available({ video_id: "v1" }, seqs), false);
  assert.equal(available(null, seqs), false);
});

test("the watched-area editor opens on the saved image and region", async () => {
  const state = await runWatchedArea({
    ...EMPTY,
    "/api/site-config": {
      config: {
        reference_region: { x: 5, y: 6, width: 7, height: 8 },
        reference_region_source: { image_sequence_id: "seq-1", image_filename: "b.jpg" }
      }
    },
    "/api/site-image-sequences": { sequences: [{ sequence_id: "seq-1", records: [rec("a.jpg"), rec("b.jpg")] }] }
  });
  assert.equal(state.body.includes("Could not load"), false);
  assert.equal(state.sandbox.baselineFilename, "b.jpg");
  assert.deepEqual(plain(state.sandbox.rect), { x: 5, y: 6, width: 7, height: 8 });
});

// ---- video sites keep working --------------------------------------------------------------

test("Riverbank: a watched area drawn on a video reopens that video moment", () => {
  const { chooseBaselineSource } = guideHelpers();
  const area = { video_id: "v1", video_time_seconds: 4.5 };
  const out = plain(chooseBaselineSource({ areaSource: area, guide: null, sequences: [], videos: [{ video_id: "v1" }] }));
  assert.deepEqual(out.source, area);
  assert.equal(out.fromWatchedArea, true);
});

test("Riverbank: a video guide at the watched area's moment keeps working, and a removed video is not shown", () => {
  const { chooseBaselineSource } = guideHelpers();
  const area = { video_id: "v1", video_time_seconds: 4.5 };
  const guide = { video_id: "v1", video_time_seconds: 4.5 };
  assert.equal(chooseBaselineSource({ areaSource: area, guide, sequences: [], videos: [{ video_id: "v1" }] }).fromWatchedArea, true);
  assert.equal(chooseBaselineSource({ areaSource: area, guide: null, sequences: [], videos: [] }).source, null);
  const other = { video_id: "v2", video_time_seconds: 1 };
  const out = chooseBaselineSource({ areaSource: area, guide: other, sequences: [], videos: [{ video_id: "v1" }, { video_id: "v2" }] });
  assert.equal(out.source.video_id, "v2");
  assert.equal(out.fromWatchedArea, false);
});

test("Watched area: a site with only a video still loads that video, at the saved moment", async () => {
  const calls = [];
  const state = await runWatchedArea({
    ...EMPTY,
    "/api/site-config": { config: { reference_region_source: { video_id: "v1", video_time_seconds: 4.5 } } },
    "/api/site-manifest": { records: [{ video_id: "v1" }] }
  }, { loadVideoSource: async (t) => calls.push(t) });
  assert.equal(state.body.includes("Could not load"), false);
  assert.equal(state.body.includes("This site has no downloaded"), false);
  assert.deepEqual(calls, [4.5]);
  assert.equal(state.sandbox.videoId, "v1");
});

test("Watched area: a video site with no saved source still loads its first video", async () => {
  const calls = [];
  const state = await runWatchedArea({ ...EMPTY, "/api/site-manifest": { records: [{ video_id: "v1" }] } }, { loadVideoSource: async (t) => calls.push(t) });
  assert.equal(state.sandbox.videoId, "v1");
  assert.equal(state.body.includes("This site has no downloaded"), false);
});

test("Riverbank: a video guide keeps its own frame when the watched area was drawn at another moment of the same video", () => {
  const { chooseBaselineSource } = guideHelpers();
  const area = { video_id: "v1", video_time_seconds: 60 };
  const guide = { video_id: "v1", video_time_seconds: 10 };
  const out = plain(chooseBaselineSource({ areaSource: area, guide, sequences: [], videos: [{ video_id: "v1" }] }));
  assert.deepEqual(out.source, { video_id: "v1", video_time_seconds: 10 });
  assert.equal(out.fromWatchedArea, false);
  assert.equal(out.areaSource.video_time_seconds, 60);
});

test("Riverbank: a video guide at the watched area's own moment counts as the same frame", () => {
  const { chooseBaselineSource } = guideHelpers();
  const area = { video_id: "v1", video_time_seconds: 10 };
  const guide = { video_id: "v1", video_time_seconds: 10.02 };
  assert.equal(chooseBaselineSource({ areaSource: area, guide, sequences: [], videos: [{ video_id: "v1" }] }).fromWatchedArea, true);
});
