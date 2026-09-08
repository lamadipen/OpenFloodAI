const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(
  path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8"
);
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function selectStub() {
  const options = [];
  return {
    value: "",
    innerHTML: "",
    options,
    append(option) { options.push(option); },
    addEventListener() {},
  };
}

function runWithStubs(source, extra) {
  const context = vm.createContext({
    document: { createElement: () => ({ value: "", textContent: "" }) },
    ...extra,
  });
  vm.runInContext(source, context);
  return context;
}

function grab(name) {
  const match = script.match(
    new RegExp(`      function ${name}\\([\\s\\S]*?\\n      \\}`)
  );
  assert.ok(match, `${name} not found`);
  return match[0];
}

test("one region selector is shared instead of copied per form", () => {
  assert.equal(script.match(/function createRegionSelector\(/g).length, 1);
  for (const gone of ["drawSetupVideoFrame", "setupVideoCanvasPoint", "videoRegionToPercent"]) {
    assert.ok(!script.includes(gone), `${gone} should be gone`);
  }
  for (const id of ["setupVideoRegionSelector", "videoRegionSelector", "watchedAreaSelector"]) {
    assert.ok(script.includes(`const ${id} = createRegionSelector({`), `${id} missing`);
  }
});

test("the watched area step opens its own form, not video intake", () => {
  const source = grab("panelForAction");
  const context = runWithStubs(source, {
    setupForm: "setupForm",
    videoFormPanel: "videoFormPanel",
    labelFormPanel: "labelFormPanel",
    siteListPanel: "siteListPanel",
    videoListPanel: "videoListPanel",
    labelListPanel: "labelListPanel",
    watchedAreaFormPanel: "watchedAreaFormPanel",
  });
  assert.equal(context.panelForAction("set_watched_area"), "watchedAreaFormPanel");
  assert.equal(context.panelForAction("add_video"), "videoFormPanel");
});

test("the video dropdown lists only videos already in the chosen site", () => {
  const siteSelect = selectStub();
  const videoSelect = selectStub();
  const status = { textContent: "" };
  const resets = [];
  siteSelect.value = "river-site";
  const context = runWithStubs(grab("fillWatchedAreaVideos"), {
    latestSites: [
      { site_name: "river-site", video_ids: ["rising-001", "falling-001"] },
      { site_name: "other-site", video_ids: ["ignore-me"] },
    ],
    watchedAreaSiteSelect: siteSelect,
    watchedAreaVideoSelect: videoSelect,
    watchedAreaSelector: { reset: () => resets.push("reset") },
    watchedAreaStatus: status,
  });
  context.fillWatchedAreaVideos();
  assert.deepEqual(
    videoSelect.options.map((option) => option.value),
    ["", "rising-001", "falling-001"]
  );
  assert.deepEqual(resets, ["reset"]);
});

test("a site with no video says so instead of offering an empty picker", () => {
  const siteSelect = selectStub();
  const videoSelect = selectStub();
  const status = { textContent: "" };
  siteSelect.value = "empty-site";
  const context = runWithStubs(grab("fillWatchedAreaVideos"), {
    latestSites: [{ site_name: "empty-site", video_ids: [] }],
    watchedAreaSiteSelect: siteSelect,
    watchedAreaVideoSelect: videoSelect,
    watchedAreaSelector: { reset() {} },
    watchedAreaStatus: status,
  });
  context.fillWatchedAreaVideos();
  assert.deepEqual(videoSelect.options.map((option) => option.value), [""]);
  assert.match(status.textContent, /Add a video first/);
});

test("choosing a video asks the local server for that site's file only", () => {
  const siteSelect = selectStub();
  const videoSelect = selectStub();
  const shown = [];
  siteSelect.value = "river-site";
  videoSelect.value = "rising-001";
  const context = runWithStubs(grab("showWatchedAreaVideo"), {
    URLSearchParams,
    watchedAreaSiteSelect: siteSelect,
    watchedAreaVideoSelect: videoSelect,
    watchedAreaSelector: {
      show: (source) => shown.push(source),
      reset: () => shown.push("reset"),
    },
  });
  context.showWatchedAreaVideo();
  assert.deepEqual(shown, ["/api/site-video?folder_name=river-site&video_id=rising-001"]);

  videoSelect.value = "";
  context.showWatchedAreaVideo();
  assert.deepEqual(shown.slice(1), ["reset"]);
});

test("the watched area form posts only the region, and never a video", () => {
  const handler = script.match(
    /watchedAreaForm\.addEventListener\("submit"[\s\S]*?\n      \}\);/
  )[0];
  assert.ok(handler.includes('"/api/set-watched-area"'));
  assert.ok(handler.includes("folder_name: watchedAreaSiteSelect.value"));
  assert.ok(handler.includes("reference_region: watchedAreaSelector.region()"));
  assert.ok(!handler.includes("FormData"));
  assert.ok(handler.includes("if (!watchedAreaSelector.hasSelection())"));
});

test("the watched area form sends the chosen video id", () => {
  const handler = script.match(
    /watchedAreaForm\.addEventListener\("submit"[\s\S]*?\n      \}\);/
  )[0];
  assert.ok(handler.includes("video_id: watchedAreaVideoSelect.value"));
});
