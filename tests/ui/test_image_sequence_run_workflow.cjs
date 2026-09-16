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
    "imageSequenceRunDetailCache",
  ]) {
    assert.ok(!homeHtml.includes(marker), `${marker} must not appear in the home-ui.html file`);
  }
});

test("the image-sequence run flow uses its own state, never the video Runs tab's state", () => {
  assert.ok(detailsScript.includes("const runningImageSequenceValidations = new Set();"));
  assert.ok(detailsScript.includes("const imageSequenceRunDetailCache = new Map();"));
  // The two caches must be genuinely distinct variables (not aliases of the
  // video Runs tab's own runDetailCache/selectedRunIds).
  assert.ok(detailsScript.includes("const runDetailCache = new Map();"));
  assert.notEqual(
    detailsScript.indexOf("const imageSequenceRunDetailCache"),
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

test("renderImageSequenceRunDetail renders review images and the report text", () => {
  const source = grab("renderImageSequenceRunDetail");
  const context = runWithStubs(source, {
    URLSearchParams,
    escapeHtml: (value) => String(value),
  });
  const html = context.renderImageSequenceRunDetail("demo-site", "run-1", {
    summary: { baseline_filename: "a.jpg", confirmed_riverbank_guide_ids: ["left"] },
    records: [{ filename: "b.jpg", result: "possible_water_level_change", reason: "changed" }],
    report: "# Image Sequence Validation Report",
    review_images: ["image-sequence-baseline.png"],
  });

  assert.match(html, /\/api\/image-sequence-run-image\?folder_name=demo-site&run_id=run-1/);
  assert.match(html, /a\.jpg/);
  assert.match(html, /b\.jpg/);
  assert.match(html, /Image Sequence Validation Report/);
});
