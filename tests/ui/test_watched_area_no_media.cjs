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
async function runWatchedArea(apiResponses) {
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
