// Regression test for tools/console/guide-source-matching.js.
//
// This project's other tests are all pytest/Python; there is no JS test
// harness set up, so this uses Node's built-in test runner and assert
// module (both dependency-free, Node >= 18) rather than adding a new
// dependency. Run with:
//
//   node --test tests/ui/test_guide_source_matching.cjs

const test = require("node:test");
const assert = require("node:assert/strict");
const { guideSourceIdentity, sourcesMatch } = require("../../tools/console/guide-source-matching.js");

test("two image-sourced entries with the same sequence and filename match", () => {
  const a = { image_sequence_id: "seq-2026-09", image_filename: "january-15.jpg" };
  const b = { image_sequence_id: "seq-2026-09", image_filename: "january-15.jpg" };
  assert.equal(sourcesMatch(a, b), true);
});

test("same sequence but a DIFFERENT filename never matches", () => {
  // The exact bug reported in review: a guide traced on january-15.jpg
  // must not be treated as matching january-01.jpg from the same
  // sequence, even though the sequence id alone is identical.
  const guide = { image_sequence_id: "seq-2026-09", image_filename: "january-15.jpg" };
  const displayed = { image_sequence_id: "seq-2026-09", image_filename: "january-01.jpg" };
  assert.equal(sourcesMatch(guide, displayed), false);
});

test("different sequences never match, regardless of filename", () => {
  const guide = { image_sequence_id: "seq-january", image_filename: "same-name.jpg" };
  const displayed = { image_sequence_id: "seq-september", image_filename: "same-name.jpg" };
  assert.equal(sourcesMatch(guide, displayed), false);
});

test("two video-sourced entries with the same video_id match regardless of time", () => {
  // Unlike an image file, a video's time-of-day is guide-specific, not
  // part of "which source" -- two guides may legitimately be traced at
  // different moments of the SAME video.
  const a = { video_id: "river-cam-01", video_time_seconds: 4.5 };
  const b = { video_id: "river-cam-01", video_time_seconds: 91.0 };
  assert.equal(sourcesMatch(a, b), true);
});

test("different video_id never matches", () => {
  const a = { video_id: "river-cam-01", video_time_seconds: 4.5 };
  const b = { video_id: "river-cam-02", video_time_seconds: 4.5 };
  assert.equal(sourcesMatch(a, b), false);
});

test("a video source never matches an image source", () => {
  const a = { video_id: "river-cam-01", video_time_seconds: 4.5 };
  const b = { image_sequence_id: "seq-2026-09", image_filename: "january-15.jpg" };
  assert.equal(sourcesMatch(a, b), false);
});

test("an empty/missing source never matches anything, including itself", () => {
  assert.equal(guideSourceIdentity(null), null);
  assert.equal(guideSourceIdentity({}), null);
  assert.equal(sourcesMatch({}, {}), false);
  assert.equal(sourcesMatch(null, null), false);
});

test("guideSourceIdentity distinguishes filenames in its own identity string", () => {
  const a = guideSourceIdentity({ image_sequence_id: "seq", image_filename: "a.jpg" });
  const b = guideSourceIdentity({ image_sequence_id: "seq", image_filename: "b.jpg" });
  assert.notEqual(a, b);
});
