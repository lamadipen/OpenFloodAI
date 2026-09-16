const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const homeHtml = fs.readFileSync(
  path.join(__dirname, "../../tools/openfloodai-home-ui.html"),
  "utf8"
);
const homeScript = homeHtml.match(/<script>([\s\S]*?)<\/script>/)[1];

const detailsHtml = fs.readFileSync(
  path.join(__dirname, "../../tools/openfloodai-site-details.html"),
  "utf8"
);
const detailsScript = detailsHtml.match(/<script>([\s\S]*?)<\/script>/)[1];

function grab(script, name) {
  const match = script.match(new RegExp(`      (?:async )?function ${name}\\([\\s\\S]*?\\n      \\}`));
  assert.ok(match, `${name} not found`);
  return match[0];
}

function grabWindowAssignment(script, name) {
  const match = script.match(
    new RegExp(`      window\\.${name} = function[\\s\\S]*?\\n      \\};`)
  );
  assert.ok(match, `window.${name} not found`);
  return match[0].replace(`window.${name} = function`, `function ${name}`).replace(/;\s*$/, "");
}

function selectStub() {
  const options = [];
  return {
    value: "",
    innerHTML: "",
    options,
    append(option) {
      options.push(option);
    },
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

test("the home UI has one USGS image-sequence form, not duplicated per selector", () => {
  assert.equal((homeHtml.match(/id="imageSequenceFormPanel"/g) || []).length, 1);
  for (const id of [
    "imageSequenceSiteSelect",
    "imageSequenceCameraUrl",
    "imageSequenceStartDate",
    "imageSequenceEndDate",
    "imageSequenceSamplingMode",
    "previewImageSequenceButton",
    "downloadImageSequenceButton",
  ]) {
    assert.ok(homeHtml.includes(`id="${id}"`), `${id} missing from markup`);
  }
});

test("the image-sequence request body matches the backend's expected fields", () => {
  const source = grab(homeScript, "imageSequenceRequestBody");
  const context = runWithStubs(source, {
    imageSequenceSiteSelect: { value: "demo-site" },
    imageSequenceCameraUrl: { value: " https://apps.usgs.gov/hivis/camera/X " },
    imageSequenceStartDate: { value: "2026-09-01" },
    imageSequenceEndDate: { value: "2026-09-02" },
    imageSequenceTimezone: { value: " America/Denver " },
    imageSequenceSamplingMode: { value: "one_per_hour" },
  });
  assert.equal(
    JSON.stringify(context.imageSequenceRequestBody()),
    JSON.stringify({
      folder_name: "demo-site",
      camera_url: "https://apps.usgs.gov/hivis/camera/X",
      start_date: "2026-09-01",
      end_date: "2026-09-02",
      timezone: "America/Denver",
      sampling_mode: "one_per_hour",
    })
  );
});

test("preview and download call the two dedicated image-sequence endpoints", () => {
  assert.ok(homeScript.includes('"/api/preview-image-sequence"'));
  assert.ok(homeScript.includes('"/api/download-image-sequence"'));
  const submitHandler = homeScript.match(
    /imageSequenceForm\.addEventListener\("submit"[\s\S]*?\n      \}\);/
  )[0];
  assert.ok(submitHandler.includes("lastImageSequencePreviewKey"));
  assert.ok(
    !submitHandler.includes("site_id:"),
    "the client must never assert site_id; the server derives it from the site's own config"
  );
  assert.ok(
    submitHandler.includes("overwrite: imageSequenceOverwrite.checked"),
    "download must let the user explicitly replace/retry an existing sequence"
  );
});

test("panelForAction opens the image-sequence panel for its own action id", () => {
  const source = grab(homeScript, "panelForAction");
  const context = runWithStubs(source, {
    setupForm: "setupForm",
    videoFormPanel: "videoFormPanel",
    labelFormPanel: "labelFormPanel",
    siteListPanel: "siteListPanel",
    videoListPanel: "videoListPanel",
    labelListPanel: "labelListPanel",
    watchedAreaFormPanel: "watchedAreaFormPanel",
    normalWaterlineGuideFormPanel: "normalWaterlineGuideFormPanel",
    imageSequenceFormPanel: "imageSequenceFormPanel",
  });
  assert.equal(context.panelForAction("start_image_sequence"), "imageSequenceFormPanel");
  assert.equal(context.panelForAction("review_image_sequences"), null);
});

test("review_image_sequences navigates to the site-details Image sequences tab", () => {
  const handler = homeScript.match(
    /window\.startWorkflowStep = function[\s\S]*?\n      \};/
  )[0];
  assert.ok(
    handler.includes(
      '`/site-details.html?site=${encodeURIComponent(siteName)}&tab=image-sequences`'
    )
  );
});

test("fillImageSequenceSites lists every site and keeps the current selection", () => {
  const select = selectStub();
  select.value = "river-site";
  const context = runWithStubs(grab(homeScript, "fillImageSequenceSites"), {
    imageSequenceSiteSelect: select,
  });
  context.fillImageSequenceSites([{ site_name: "other-site" }, { site_name: "river-site" }]);
  assert.deepEqual(select.options.map((option) => option.value), ["other-site", "river-site"]);
  assert.equal(select.value, "river-site");
});

test("useImageAsWatchedAreaReference shows the image and leaves a submittable, non-empty video select", () => {
  const shown = [];
  const panel = { style: {} };
  const select = selectStub();
  const context = runWithStubs(grabWindowAssignment(homeScript, "useImageAsWatchedAreaReference"), {
    hideForms: () => {},
    revealPanel: () => {},
    watchedAreaFormPanel: panel,
    watchedAreaSiteSelect: { value: "" },
    watchedAreaVideoSelect: select,
    watchedAreaSelector: { show: (source, options) => shown.push([source, JSON.stringify(options)]) },
    URLSearchParams,
    pendingWatchedAreaImageSource: null,
  });
  context.useImageAsWatchedAreaReference(
    "demo-site",
    "usgs-camera-2026-09-01-2026-09-01",
    "camera___2026-09-01T09-00-00Z.jpg"
  );

  assert.equal(select.options.length, 1);
  assert.notEqual(
    select.options[0].value,
    "",
    "select required=true would block form submit on an empty value"
  );
  assert.equal(
    JSON.stringify(context.pendingWatchedAreaImageSource),
    JSON.stringify({
      sequenceId: "usgs-camera-2026-09-01-2026-09-01",
      filename: "camera___2026-09-01T09-00-00Z.jpg",
    })
  );
  assert.equal(shown.length, 1);
  assert.match(shown[0][0], /^\/api\/image-sequence-image\?/);
  assert.equal(shown[0][1], JSON.stringify({ isImage: true }));
  assert.equal(panel.style.display, "block");
});

test("the watched area submit handler sends the image source instead of a video id when set", () => {
  const handler = homeScript.match(
    /watchedAreaForm\.addEventListener\("submit"[\s\S]*?\n      \}\);/
  )[0];
  assert.ok(handler.includes("pendingWatchedAreaImageSource"));
  assert.ok(handler.includes("sequence_id: pendingWatchedAreaImageSource.sequenceId"));
  assert.ok(handler.includes("image_filename: pendingWatchedAreaImageSource.filename"));
});

test("createRegionSelector draws from an image source without needing video-only properties", () => {
  assert.ok(homeScript.includes("function createRegionSelector({ video, image, canvas, input, status, emptyText })"));
  assert.ok(homeScript.includes("context.drawImage(activeSource(), 0, 0, canvas.width, canvas.height);"));
  assert.ok(homeScript.includes("sourceIsImage = isImage && Boolean(image);"));
});

test("starting the same step for a different site switches sites instead of just closing", () => {
  const panel = { style: {} };
  const select = selectStub();
  const events = [];
  const source =
    "let openWorkflowForm = null;\n" +
    grabWindowAssignment(homeScript, "startWorkflowStep");
  const context = runWithStubs(source, {
    detailSiteSelect: { value: "" },
    imageSequenceSiteSelect: select,
    panelForAction: (actionId) => (actionId === "start_image_sequence" ? panel : null),
    fillWorkflowList: () => {},
    hideForms: () => {
      events.push("hide");
      panel.style.display = "none";
    },
    mountWorkflowForm: () => {
      panel.style.display = "block";
    },
    revealPanel: () => {},
  });

  context.startWorkflowStep("start_image_sequence", "example-site", "image_sequence", null);
  assert.equal(select.value, "example-site");
  assert.equal(panel.style.display, "block");

  context.startWorkflowStep("start_image_sequence", "my-real-site", "image_sequence", null);
  assert.equal(
    select.value,
    "my-real-site",
    "clicking the same step's button for a different site must switch to it, not just toggle-close"
  );
  assert.equal(panel.style.display, "block");
});

test("the site-details page has an Image sequences tab wired to its own panel", () => {
  assert.ok(detailsHtml.includes('data-tab="image-sequences"'));
  assert.ok(detailsHtml.includes('id="panel-image-sequences"'));
  assert.ok(detailsScript.includes("async function renderImageSequencesTab(site)"));
  assert.ok(detailsScript.includes("renderImageSequencesTab(site);"));
});

test("each downloaded image links back to the home UI with the image as the watched-area source", () => {
  const source = grab(detailsScript, "renderImageSequenceCard");
  const context = runWithStubs(source, {
    URLSearchParams,
    escapeHtml: (value) => String(value),
    formatDateTime: (value) => String(value),
  });
  const html = context.renderImageSequenceCard("demo-site", {
    sequence_id: "usgs-camera-2026-09-01-2026-09-01",
    sampling_mode: "one_per_hour",
    requested_start_date: "2026-09-01",
    requested_end_date: "2026-09-01",
    timezone: "UTC",
    downloaded_count: 1,
    missing_count: 0,
    failed_count: 0,
    records: [
      {
        filename: "camera___2026-09-01T09-00-00Z.jpg",
        download_status: "downloaded",
        captured_at_utc: "2026-09-01T09:00:00+00:00",
        local_time: "2026-09-01T09:00:00+00:00",
      },
    ],
  });
  assert.match(html, /\/api\/image-sequence-image\?folder_name=demo-site/);
  assert.match(
    html,
    /\/openfloodai-home-ui\.html\?site=demo-site&action=set_watched_area&image_sequence_id=usgs-camera-2026-09-01-2026-09-01&image_filename=camera___2026-09-01T09-00-00Z\.jpg/
  );
  assert.match(
    html,
    /\/openfloodai-home-ui\.html\?site=demo-site&action=set_normal_waterline_guide&image_sequence_id=usgs-camera-2026-09-01-2026-09-01&image_filename=camera___2026-09-01T09-00-00Z\.jpg/
  );
});

test("createNormalWaterlineGuidesEditor draws from an image source without needing video-only properties", () => {
  assert.ok(
    homeScript.includes(
      "function createNormalWaterlineGuidesEditor({\n        video,\n        image,\n        canvas,"
    )
  );
  assert.ok(homeScript.includes("context.drawImage(activeSource(), 0, 0, canvas.width, canvas.height);"));
  assert.ok(homeScript.includes("sourceIsImage = isImage && Boolean(image);"));
  assert.ok(homeScript.includes("isImageSource: () => sourceIsImage,"));
});

test("useImageAsRiverbankReference shows the image, filters existing guides, and leaves a submittable video select", () => {
  const panel = { style: {} };
  const select = selectStub();
  const shown = [];
  const site = {
    site_name: "demo-site",
    reference_region: { x: 0, y: 50, width: 100, height: 50 },
    normal_waterline_guides: [
      {
        id: "matching",
        image_sequence_id: "usgs-camera-2026-09-01-2026-09-01-all",
        image_filename: "camera___2026-09-01T09-00-00Z.jpg",
      },
      {
        id: "other-image",
        image_sequence_id: "usgs-camera-2026-09-02-2026-09-02-all",
        image_filename: "camera___2026-09-02T09-00-00Z.jpg",
      },
      { id: "video-sourced", video_id: "river-001" },
    ],
  };
  const context = runWithStubs(grabWindowAssignment(homeScript, "useImageAsRiverbankReference"), {
    hideForms: () => {},
    revealPanel: () => {},
    normalWaterlineGuideFormPanel: panel,
    normalWaterlineGuideSiteSelect: { value: "" },
    normalWaterlineGuideVideoSelect: select,
    normalWaterlineGuideEditor: { show: (source, options) => shown.push([source, JSON.stringify(options)]) },
    latestSites: [site],
    URLSearchParams,
    pendingNormalWaterlineGuideImageSource: null,
  });
  context.useImageAsRiverbankReference(
    "demo-site",
    "usgs-camera-2026-09-01-2026-09-01-all",
    "camera___2026-09-01T09-00-00Z.jpg"
  );

  assert.equal(select.options.length, 1);
  assert.notEqual(
    select.options[0].value,
    "",
    "select required=true would block form submit on an empty value"
  );
  assert.equal(
    JSON.stringify(context.pendingNormalWaterlineGuideImageSource),
    JSON.stringify({
      sequenceId: "usgs-camera-2026-09-01-2026-09-01-all",
      filename: "camera___2026-09-01T09-00-00Z.jpg",
    })
  );
  assert.equal(shown.length, 1);
  assert.match(shown[0][0], /^\/api\/image-sequence-image\?/);
  const options = JSON.parse(shown[0][1]);
  assert.equal(options.isImage, true);
  assert.deepEqual(
    options.existingGuides.map((guide) => guide.id),
    ["matching"],
    "only guides for this exact image should be preloaded"
  );
  assert.equal(panel.style.display, "block");
});

test("saving normal waterline guides sends the image source instead of a video id when set", () => {
  const handler = homeScript.match(
    /saveAllNormalWaterlineGuidesButton\.addEventListener\("click"[\s\S]*?\n      \}\);/
  )[0];
  assert.ok(handler.includes("pendingNormalWaterlineGuideImageSource"));
  assert.ok(handler.includes("sequence_id: pendingNormalWaterlineGuideImageSource.sequenceId"));
  assert.ok(handler.includes("image_filename: pendingNormalWaterlineGuideImageSource.filename"));
});
