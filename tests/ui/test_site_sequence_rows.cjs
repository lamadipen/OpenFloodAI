const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../../tools/console/site.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const helpers = script.slice(script.indexOf("// ---- sequence rows"), script.indexOf("// ---- end sequence rows"));

function context(sam = null, maskPlans = {}) {
  const escapeHtml = (v) =>
    String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  const sandbox = { escapeHtml, String, Object, state: { sam, maskPlans } };
  vm.createContext(sandbox);
  vm.runInContext(helpers, sandbox);
  return sandbox;
}

const waterSet = {
  sequence_id: "usgs-CAM-2025-01-01-2025-12-31-water_level",
  downloaded_count: 3,
  water_level_groups: { "b.jpg": "high", "a.jpg": "low", "c.jpg": "middle" },
  water_level_samples: {
    "b.jpg": { group: "high", level: 12.5, unit: "ft", quality_status: "provisional" },
    "a.jpg": { group: "low", level: 3.1, unit: "ft", quality_status: "approved" },
    "c.jpg": { group: "middle", level: 7.25, unit: "ft", quality_status: "approved" }
  },
  records: [
    { filename: "b.jpg", captured_at_utc: "2025-06-02T12:05:00+00:00", download_status: "downloaded" },
    { filename: "a.jpg", captured_at_utc: "2025-03-01T12:05:00+00:00", download_status: "downloaded" },
    { filename: "c.jpg", captured_at_utc: "2025-09-09T12:05:00+00:00", download_status: "downloaded" },
    { filename: "", captured_at_utc: "2025-04-01T00:00:00+00:00", download_status: "missing" }
  ]
};

test("a water-level set needs a baseline choice before it can run", () => {
  const out = context().sequenceRowHtml(waterSet);
  assert.match(out, /data-baseline-for="usgs-CAM-2025-01-01-2025-12-31-water_level"/);
  assert.match(out, /Choose a baseline image/);
  assert.match(out, /data-run-sequence="[^"]*" disabled/);
  assert.match(out, /no assumed normal first image/);
});

test("baseline options show the gauge level and are ordered lowest level first", () => {
  const out = context().baselineOptionsHtml(waterSet);
  const values = [...out.matchAll(/value="([^"]+)"/g)].map((m) => m[1]).filter(Boolean);
  assert.deepEqual(values, ["a.jpg", "c.jpg", "b.jpg"]); // 3.10, 7.25, 12.50 ft
  assert.match(out, /3\.10 ft &middot; Low water sample &middot; 2025-03-01 12:05 UTC/);
  assert.match(out, /7\.25 ft &middot; Middle water sample/);
  assert.match(out, /12\.50 ft \(provisional\) &middot; High water sample/);
  assert.doesNotMatch(out, /value=""[^>]*>[^<]*missing/);
});

test("images without a recorded level are listed last and say so", () => {
  const seq = { ...waterSet, water_level_samples: { "a.jpg": { group: "low", level: 3.1, unit: "ft" } } };
  const out = context().baselineOptionsHtml(seq);
  const values = [...out.matchAll(/value="([^"]+)"/g)].map((m) => m[1]).filter(Boolean);
  assert.equal(values[0], "a.jpg");
  assert.equal(values.length, 3);
  assert.match(out, /level not recorded/);
});

test("a fingerprinted water-level sequence name is recognised too", () => {
  const out = context().sequenceRowHtml({ sequence_id: "usgs-CAM-2026-01-01-2026-10-04-water_level-0a1b2c3d", downloaded_count: 9, records: [] });
  assert.match(out, /data-baseline-for=/);
});

test("a regular sequence is unchanged: no picker, button enabled", () => {
  const out = context().sequenceRowHtml({ sequence_id: "usgs-CAM-2026-08-01-2026-09-03-one_daylight_image_per_day", downloaded_count: 29 });
  assert.doesNotMatch(out, /data-baseline-for/);
  assert.doesNotMatch(out, /data-run-sequence="[^"]*" disabled/);
});

test("each sequence has its own error box, so a failure shows under the row that was clicked", () => {
  const ctx = context();
  const a = ctx.sequenceRowHtml(waterSet);
  const b = ctx.sequenceRowHtml({ sequence_id: "usgs-CAM-2026-08-01-2026-09-03-all" });
  assert.match(a, /data-run-error="usgs-CAM-2025-01-01-2025-12-31-water_level"/);
  assert.match(b, /data-run-error="usgs-CAM-2026-08-01-2026-09-03-all"/);
});

test("a named sequence shows its name with the stable id underneath, escaped", () => {
  const ctx = context();
  const out = ctx.sequenceRowHtml({
    sequence_id: "usgs-CAM-2026-01-01-2026-02-01-water_level-0a1b2c3d",
    display_name: "<img src=x onerror=1> Windy Gap",
    downloaded_count: 5,
    records: []
  });
  assert.match(out, /&lt;img src=x onerror=1&gt; Windy Gap/);
  assert.doesNotMatch(out, /<img src=x/);
  assert.match(out, /usgs-CAM-2026-01-01-2026-02-01-water_level-0a1b2c3d/);
});

test("two sequences with the same name remain distinguishable by their ids", () => {
  const ctx = context();
  const a = ctx.sequenceRowHtml({ sequence_id: "usgs-CAM-2026-01-01-2026-02-01-water_level-0a1b2c3d", display_name: "Same", records: [] });
  const b = ctx.sequenceRowHtml({ sequence_id: "usgs-CAM-2026-03-01-2026-04-01-water_level-99887766", display_name: "Same", records: [] });
  assert.match(a, /0a1b2c3d/);
  assert.match(b, /99887766/);
});

test("an unnamed sequence is shown by its generated id, as before", () => {
  const out = context().sequenceRowHtml({ sequence_id: "usgs-CAM-2026-08-01-2026-09-03-one_daylight_image_per_day", display_name: null, downloaded_count: 29 });
  assert.match(out, /usgs-CAM-2026-08-01-2026-09-03-one_daylight_image_per_day/);
  assert.doesNotMatch(out, /font-weight:600;">/);
});

test("the baseline picker says which batch each image came from", () => {
  const seq = {
    sequence_id: "usgs-CAM-2026-01-01-2026-02-01-water_level-0a1b2c3d",
    water_level_groups: { "a.jpg": "low", "b.jpg": "high" },
    water_level_samples: {
      "a.jpg": { group: "low", level: 3.1, unit: "ft", batch_number: 1 },
      "b.jpg": { group: "high", level: 9.5, unit: "ft", batch_number: 2 }
    },
    records: [
      { filename: "a.jpg", captured_at_utc: "2026-01-05T18:00:00+00:00", download_status: "downloaded" },
      { filename: "b.jpg", captured_at_utc: "2026-03-05T18:00:00+00:00", download_status: "downloaded" }
    ]
  };
  const out = context().baselineOptionsHtml(seq);
  assert.match(out, /3\.10 ft &middot; Low water sample &middot; batch 1/);
  assert.match(out, /9\.50 ft &middot; High water sample &middot; batch 2/);
});

const samReady = {
  enabled: true,
  credential: { configured: true },
  decoder_available: true,
  provider: { pricing_note: "About $2.50 per 1,000 images." }
};

test("the mask checkbox is off, with the reason, until hosted SAM is on, keyed and installed", () => {
  const off = context(null).sequenceRowHtml(waterSet);
  assert.match(off, /data-fetch-masks="[^"]*" disabled/);
  assert.match(off, /status is unavailable/);
  const disabled = context({ ...samReady, enabled: false }).sequenceRowHtml(waterSet);
  assert.match(disabled, /Turn on Hosted SAM segmentation in Settings/);
  const noKey = context({ ...samReady, credential: { configured: false } }).sequenceRowHtml(waterSet);
  assert.match(noKey, /Add your own API key in Settings/);
  const noDecoder = context({ ...samReady, decoder_available: false }).sequenceRowHtml(waterSet);
  assert.match(noDecoder, /decoder is not installed/);
});

test("when ready the checkbox sits beside Run validation and nothing is ticked by default", () => {
  const out = context(samReady).sequenceRowHtml(waterSet);
  assert.match(out, /data-fetch-masks="usgs-CAM-2025-01-01-2025-12-31-water_level"(?![^>]*disabled)/);
  assert.doesNotMatch(out, /data-fetch-masks="[^"]*"[^>]*checked/);
  assert.match(out, /Also fetch water masks/);
  assert.match(out, /Only images without a mask are sent\. You confirm the count first/);
  assert.ok(out.indexOf("Run validation</button>") < out.indexOf("data-fetch-masks"));
});

test("the plan is explained in plain words, including when every image already has a mask", () => {
  const ctx = context(samReady);
  assert.match(
    ctx.maskPlanText({ to_send: 0, total_images: 6, already_have_masks: 6 }),
    /All 6 images already have masks\. Nothing will be sent and nothing is charged/
  );
  const some = ctx.maskPlanText({ to_send: 4, total_images: 6, already_have_masks: 2, over_limit: false });
  assert.match(some, /4 of 6 images have no mask and would be sent \(paid\)\. 2 already have masks and are not sent again/);
  assert.match(ctx.maskPlanText({ to_send: 120, total_images: 120, already_have_masks: 0, over_limit: true, limit: 100 }), /over the 100-request limit/);
  assert.equal(ctx.maskPlanText({ error: "No downloaded images." }), "No downloaded images.");
});

test("the confirmation names the exact counts, the upload and the possible charge", () => {
  const text = context(samReady).maskConfirmText({ to_send: 4, total_images: 6, already_have_masks: 2 });
  assert.match(text, /4 of 6 images have no mask/);
  assert.match(text, /uploaded to the provider, and may be billed/);
  assert.match(text, /2 image\(s\) already have masks and are not sent again/);
  assert.match(text, /\$2\.50 per 1,000 images/);
  assert.match(text, /unreviewed drafts/);
});

test("each run row links to the blind review beside the detailed review", () => {
  assert.match(html, /\/console\/review-focus\.html\?\$\{new URLSearchParams\(\{ site: folderName, run_id: run\.run_id \}\)\}[^>]*>Blind review &rarr;/);
  assert.ok(html.indexOf("Blind review &rarr;") < html.indexOf("Review &rarr;</a></td>"));
});
