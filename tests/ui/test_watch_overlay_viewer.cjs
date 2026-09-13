const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const panel = html.split('<section id="watchViewerPanel"')[1].split("</section>")[0];

function grabFunction(name) {
  const match = script.match(new RegExp(`      function ${name}\\([\\s\\S]*?\\n      \\}`));
  assert.ok(match, `${name} not found`);
  return match[0];
}

test("the watch panel has a video and an absolutely-positioned overlay canvas", () => {
  assert.match(panel, /<video id="watchVideoPreview" controls/);
  assert.match(panel, /<canvas id="watchOverlayCanvas"/);
  assert.match(panel, /id="watchVideoWrap" style="position: relative[^"]*"/);
  assert.match(panel, /id="watchOverlayCanvas"[^>]*position: ?absolute/);
  assert.match(panel, /id="watchOverlayCanvas"[^>]*pointer-events: ?none/);
});

test("the overlay viewer is read-only: no drag/drop listeners, tracks live playback", () => {
  const source = grabFunction("createReadOnlyOverlayViewer");
  for (const eventName of ["pointerdown", "pointermove", "pointerup"]) {
    assert.ok(!source.includes(eventName), `should not listen for ${eventName}`);
  }
  assert.ok(source.includes("timeupdate"), "should redraw as the video plays");
  assert.ok(source.includes("loadedmetadata"), "should redraw once video dimensions are known");
});

test("the overlay viewer's trust check mirrors is_normal_baseline_confirmed", () => {
  const source = grabFunction("createReadOnlyOverlayViewer");
  assert.ok(source.includes('reference.status === "confirmed"'));
  assert.ok(source.includes("reference.normal_condition === true"));
});

test("the overlay viewer never modifies the video: only reads from the existing site-video route", () => {
  const source = grabFunction("createReadOnlyOverlayViewer");
  assert.ok(!/\bfetch\(|XMLHttpRequest/.test(source), "the viewer itself makes no network calls");
  assert.ok(html.includes("watchOverlayViewer.show(`/api/site-video?"));
  assert.ok(!html.includes('"/api/watch'), "no new watch-specific API route should exist");
});

test("unavailable-reference text matches the report's exact wording", () => {
  const source = grabFunction("createReadOnlyOverlayViewer");
  assert.ok(source.includes("No confirmed reference yet."));
  assert.ok(source.includes("Reference exists but is not confirmed."));
});

test("a Watch button opens the viewer for a site with at least one video", () => {
  const buttonLine = script
    .split("\n")
    .find((line) => line.includes("openWatchViewerForSite("));
  assert.ok(buttonLine, "Watch button not found in renderSite()");
  assert.ok(buttonLine.includes("site.video_count > 0"));
  assert.ok(buttonLine.includes("disabled"));
});
