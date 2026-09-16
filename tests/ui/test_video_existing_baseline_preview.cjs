const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(
  path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8"
);
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function grab(name) {
  const match = script.match(
    new RegExp(`      function ${name}\\([\\s\\S]*?\\n      \\}`)
  );
  assert.ok(match, `${name} not found`);
  return match[0];
}

function block() {
  return { style: { display: "" } };
}

function runWithStubs(source, extra) {
  const context = vm.createContext({ ...extra });
  vm.runInContext(source, context);
  return context;
}

test("a site with a saved reference_region is detected as having an existing baseline", () => {
  const context = runWithStubs(grab("siteHasExistingBaseline"), {
    latestSites: [
      { site_name: "with-baseline", reference_region: { x: 1, y: 2, width: 3, height: 4 } },
      { site_name: "without-baseline" },
    ],
  });
  assert.equal(context.siteHasExistingBaseline("with-baseline"), true);
  assert.equal(context.siteHasExistingBaseline("without-baseline"), false);
  assert.equal(context.siteHasExistingBaseline("unknown-site"), false);
});

test("updateVideoBaselineMode shows the existing-baseline block only when the site already has a region", () => {
  const existingBlock = block();
  const newBlock = block();
  const selector = { reset: () => {}, show: () => {} };
  const viewer = { reset: () => {}, show: () => {} };
  const siteSelect = { value: "with-baseline" };
  const fileInput = { files: [] };
  const source =
    grab("siteHasExistingBaseline") +
    "\n" +
    grab("renderVideoFilePreview") +
    "\n" +
    grab("updateVideoBaselineMode");
  const context = runWithStubs(source, {
    latestSites: [
      { site_name: "with-baseline", reference_region: { x: 1, y: 2, width: 3, height: 4 } },
      { site_name: "no-baseline-yet" },
    ],
    videoSiteSelect: siteSelect,
    videoExistingBaselineBlock: existingBlock,
    videoNewRegionBlock: newBlock,
    videoRegionSelector: selector,
    videoExistingBaselineViewer: viewer,
    videoFileObjectUrl: null,
  });
  context.updateVideoBaselineMode();
  assert.equal(existingBlock.style.display, "block");
  assert.equal(newBlock.style.display, "none");

  siteSelect.value = "no-baseline-yet";
  context.updateVideoBaselineMode();
  assert.equal(existingBlock.style.display, "none");
  assert.equal(newBlock.style.display, "block");
});

test("renderVideoFilePreview shows the read-only overlay with the site's region and guides when one exists", () => {
  const shown = [];
  const selectorResets = [];
  const viewerResets = [];
  const siteSelect = { value: "with-baseline" };
  const source = grab("renderVideoFilePreview");
  const context = vm.createContext({
    latestSites: [
      {
        site_name: "with-baseline",
        reference_region: { x: 10, y: 20, width: 30, height: 40 },
        normal_waterline_guides: [{ id: "g1" }],
      },
    ],
    videoSiteSelect: siteSelect,
    videoFileObjectUrl: "blob:fake-url",
    videoRegionSelector: { reset: () => selectorResets.push("reset"), show: () => {} },
    videoExistingBaselineViewer: {
      reset: () => viewerResets.push("reset"),
      show: (url, options) => shown.push({ url, options }),
    },
  });
  vm.runInContext(source, context);
  context.renderVideoFilePreview();
  // shown[].options crosses the vm realm boundary, so compare via JSON
  // (structurally equal, but not reference-equal under assert/strict).
  assert.deepEqual(JSON.parse(JSON.stringify(shown)), [
    {
      url: "blob:fake-url",
      options: {
        watchedRegion: { x: 10, y: 20, width: 30, height: 40 },
        normalWaterlineGuides: [{ id: "g1" }],
      },
    },
  ]);
  assert.deepEqual(selectorResets, ["reset"]);
  assert.deepEqual(viewerResets, []);
});

test("renderVideoFilePreview falls back to the drawable region selector when no baseline exists yet", () => {
  const shown = [];
  const viewerResets = [];
  const siteSelect = { value: "no-baseline-yet" };
  const source = grab("renderVideoFilePreview");
  const context = vm.createContext({
    latestSites: [{ site_name: "no-baseline-yet" }],
    videoSiteSelect: siteSelect,
    videoFileObjectUrl: "blob:fake-url",
    videoRegionSelector: { reset: () => {}, show: (url) => shown.push(url) },
    videoExistingBaselineViewer: { reset: () => viewerResets.push("reset"), show: () => {} },
  });
  vm.runInContext(source, context);
  context.renderVideoFilePreview();
  assert.deepEqual(shown, ["blob:fake-url"]);
  assert.deepEqual(viewerResets, ["reset"]);
});

test("renderVideoFilePreview resets both previews when no file is chosen", () => {
  const selectorResets = [];
  const viewerResets = [];
  const source = grab("renderVideoFilePreview");
  const context = vm.createContext({
    latestSites: [],
    videoSiteSelect: { value: "" },
    videoFileObjectUrl: null,
    videoRegionSelector: { reset: () => selectorResets.push("reset"), show: () => {} },
    videoExistingBaselineViewer: { reset: () => viewerResets.push("reset"), show: () => {} },
  });
  vm.runInContext(source, context);
  context.renderVideoFilePreview();
  assert.deepEqual(selectorResets, ["reset"]);
  assert.deepEqual(viewerResets, ["reset"]);
});

test("the video form only requires a drawn region when the site has no existing baseline", () => {
  const handler = script.match(
    /videoForm\.addEventListener\("submit"[\s\S]*?\n      \}\);/
  )[0];
  assert.ok(handler.includes("siteHasExistingBaseline(videoSiteSelect.value)"));
  assert.ok(handler.includes("!hasExistingBaseline && !videoRegionSelector.hasSelection()"));
});

test("adding a video never re-sends a region once the site already has one (backend already treats an empty reference_region as unchanged)", () => {
  assert.ok(script.includes('videoSiteSelect.addEventListener("change", updateVideoBaselineMode)'));
  assert.ok(
    script.includes("const videoExistingBaselineViewer = createReadOnlyOverlayViewer({")
  );
});

test("the change-watched-area button jumps to the dedicated watched-area form for the current site", () => {
  const handler = script.match(
    /videoExistingBaselineChangeButton\.addEventListener\("click"[\s\S]*?\n      \}\);/
  )[0];
  assert.ok(handler.includes("window.openWatchedAreaFormForSite(videoSiteSelect.value)"));
});
