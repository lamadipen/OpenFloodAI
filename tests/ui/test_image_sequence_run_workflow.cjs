const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const homeHtml = fs.readFileSync(
  path.join(__dirname, "../../tools/openfloodai-home-ui.html"),
  "utf8"
);

const detailsHtml = fs.readFileSync(
  path.join(__dirname, "../../tools/openfloodai-site-details.html"),
  "utf8"
);
const detailsScript = detailsHtml.match(/<script>([\s\S]*?)<\/script>/)[1];

function grab(name) {
  const match = detailsScript.match(
    new RegExp(`      (?:async )?function ${name}\\([\\s\\S]*?\\n      \\}`)
  );
  assert.ok(match, `${name} not found`);
  return match[0];
}

function runWithStubs(source, extra) {
  const context = vm.createContext({
    document: { createElement: () => ({ value: "", textContent: "" }) },
    ...extra,
  });
  vm.runInContext(source, context);
  return context;
}

test("issue #182 does not touch the video Run validation UI at all", () => {
  for (const marker of [
    "run-image-sequence-validation",
    "runImageSequenceValidationForSite",
    "image-sequence-run",
    "imageSequenceRunDetailDataCache",
  ]) {
    assert.ok(!homeHtml.includes(marker), `${marker} must not appear in the home-ui.html file`);
  }
});

test("the image-sequence run flow uses its own state, never the video Runs tab's state", () => {
  assert.ok(detailsScript.includes("const runningImageSequenceValidations = new Set();"));
  assert.ok(detailsScript.includes("const imageSequenceRunDetailDataCache = new Map();"));
  // The two caches must be genuinely distinct variables (not aliases of the
  // video Runs tab's own runDetailCache/selectedRunIds).
  assert.ok(detailsScript.includes("const runDetailCache = new Map();"));
  assert.notEqual(
    detailsScript.indexOf("const imageSequenceRunDetailDataCache"),
    detailsScript.indexOf("const runDetailCache")
  );
});

test("renderImageSequenceCard adds a per-sequence run button and run list placeholder", () => {
  assert.ok(detailsHtml.includes("data-run-image-sequence-validation"));
  const source = grab("renderImageSequenceCard");
  assert.ok(source.includes('data-sequence-id="${escapeHtml(sequence.sequence_id || "")}"'));
  assert.ok(source.includes("data-run-image-sequence-validation"));
  assert.ok(source.includes("data-image-sequence-run-list"));
});

test("renderImageSequenceRunList renders counts and wires expand handlers", () => {
  const listeners = [];
  const list = {
    innerHTML: "",
    querySelectorAll: (selector) => {
      assert.equal(selector, "[data-run-head]");
      return [
        {
          addEventListener: (event, handler) => listeners.push(handler),
        },
      ];
    },
  };
  const context = runWithStubs(grab("renderImageSequenceRunList"), {
    escapeHtml: (value) => String(value),
    formatDateTime: (value) => String(value),
    fallback: (value, fallbackValue) =>
      value === undefined || value === null || value === "" ? fallbackValue : value,
  });
  context.renderImageSequenceRunList(list, "demo-site", [
    {
      run_id: "run-1",
      created_at: "2026-09-01T00:00:00+00:00",
      baseline_filename: "a.jpg",
      possible_water_level_change_count: 1,
      no_water_level_change_count: 2,
      cannot_judge_water_level_count: 0,
      camera_or_image_problem_count: 3,
    },
  ]);

  assert.match(list.innerHTML, /run-1/);
  assert.match(list.innerHTML, /1 possible/);
  assert.match(list.innerHTML, /2 no change/);
  assert.match(list.innerHTML, /3 problem/);
  assert.equal(listeners.length, 1, "the run head must get a click handler to expand it");
});

test("renderImageSequenceRunList shows an empty state when there are no runs", () => {
  const list = { innerHTML: "" };
  const context = runWithStubs(grab("renderImageSequenceRunList"), {
    escapeHtml: (value) => String(value),
    formatDateTime: (value) => String(value),
    fallback: (value, fallbackValue) => value ?? fallbackValue,
  });
  context.renderImageSequenceRunList(list, "demo-site", []);
  assert.match(list.innerHTML, /No image-sequence validation runs yet/);
});

test("runImageSequenceValidationForSite posts only to the image-sequence endpoint", () => {
  const source = grab("runImageSequenceValidationForSite");
  assert.ok(source.includes('"/api/run-image-sequence-validation"'));
  assert.ok(!source.includes('"/api/run-validation"'));
  assert.ok(source.includes("runningImageSequenceValidations"));
});

test("runImageSequenceValidationForSite sends the user-chosen baseline_filename, not just the earliest image", () => {
  const source = grab("runImageSequenceValidationForSite");
  assert.ok(source.includes('card.querySelector("[data-baseline-select]")'));
  assert.ok(source.includes("baseline_filename: baselineFilename"));
});

test("renderImageSequenceCard offers a baseline picker over the downloaded images", () => {
  const context = runWithStubs(grab("renderImageSequenceCard"), {
    escapeHtml: (value) => String(value),
    formatDateTime: (value) => String(value),
    URLSearchParams,
  });
  const html = context.renderImageSequenceCard("demo-site", {
    sequence_id: "usgs-camera-2026-09-01-2026-09-01",
    records: [
      { filename: "a.jpg", download_status: "downloaded", captured_at_utc: "T1", local_time: "T1" },
      { filename: "b.jpg", download_status: "downloaded", captured_at_utc: "T2", local_time: "T2" },
      { filename: "c.jpg", download_status: "missing", captured_at_utc: "T3", local_time: "T3" },
    ],
  });

  assert.match(html, /data-baseline-select/);
  assert.match(html, /Auto \(earliest downloaded image\)/);
  assert.match(html, /value="a\.jpg"/);
  assert.match(html, /value="b\.jpg"/);
  assert.doesNotMatch(html, /value="c\.jpg"/, "a missing image must not be offered as a baseline");
});

test("the old renderImageSequenceRunDetail helper is gone, replaced by the interactive review view", () => {
  assert.ok(
    !/function renderImageSequenceRunDetail\(/.test(detailsScript),
    "renderImageSequenceRunDetail should no longer exist as a standalone HTML-string renderer"
  );
  assert.ok(detailsScript.includes("function mountImageSequenceDetailView("));
  assert.ok(detailsScript.includes("function renderImageSequenceDetail("));
  assert.ok(
    detailsScript.includes("mountImageSequenceDetailView(body, siteName, runId,"),
    "loadImageSequenceRunBody must mount the interactive view, not cache a rendered HTML string"
  );
});

const RESULT_CODE_STUB = {
  possible_water_level_change: "P",
  no_water_level_change: "N",
  cannot_judge_water_level: "U",
  camera_or_image_problem: "C",
};
const CODE_LABEL_STUB = {
  N: "No water level change",
  P: "Possible water level change",
  C: "Camera or image problem",
  U: "Cannot judge",
  M: "No image available",
};

test("buildImageSequenceDays treats a non-downloaded record as a coverage gap, not a comparison", () => {
  const context = runWithStubs(grab("buildImageSequenceDays"), {
    RESULT_CODE: RESULT_CODE_STUB,
    CODE_LABEL: CODE_LABEL_STUB,
  });
  const days = context.buildImageSequenceDays([
    {
      captured_at_utc: "2026-06-19T18:00:00+00:00",
      local_time: "2026-06-19T12:00:00-06:00",
      download_status: "downloaded",
      result: "possible_water_level_change",
      region_change_score: 0.05,
      reason: "changed",
    },
    {
      captured_at_utc: "2026-06-20T18:00:00+00:00",
      local_time: "2026-06-20T12:00:00-06:00",
      download_status: "missing",
      result: "camera_or_image_problem",
      reason: "not downloaded",
    },
  ]);

  assert.equal(days.length, 2);
  assert.equal(days[0].code, "P");
  assert.equal(days[0].score, 0.05);
  assert.equal(days[1].code, "M", "a missing/failed image must be a gap, never a camera_or_image_problem row");
  assert.equal(days[1].score, null);
});

test("buildImageSequenceEvents clusters consecutive same-code days and never includes gaps or no-change days", () => {
  const context = runWithStubs(grab("buildImageSequenceEvents"), {});
  const days = [
    { date: "2026-06-19", code: "N", score: 0.03 },
    { date: "2026-06-20", code: "P", score: 0.05 },
    { date: "2026-06-21", code: "P", score: 0.09 },
    { date: "2026-06-22", code: "M", score: null },
    { date: "2026-06-23", code: "C", score: 0.11 },
  ];
  const events = context.buildImageSequenceEvents(days);

  assert.equal(events.length, 2);
  assert.equal(events[0].code, "P");
  assert.equal(events[0].key, "2026-06-20-2026-06-21-P");
  assert.equal(events[0].peak, 2, "the peak day within a cluster must be its highest-scoring day");
  assert.equal(events[1].code, "C");
});

test("findImageSequenceChangeStart reports no change point when there is too little baseline history", () => {
  const context = runWithStubs(grab("findImageSequenceChangeStart") + "\n" + grab("isoImageSequenceMean"), {});
  const tooFewDays = [{ score: 0.05 }, { score: 0.06 }];
  const result = context.findImageSequenceChangeStart(tooFewDays);
  assert.equal(result.index, -1);
  assert.equal(result.threshold, null);
});
