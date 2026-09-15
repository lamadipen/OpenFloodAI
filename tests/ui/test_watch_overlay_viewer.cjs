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
  assert.ok(source.includes('guide.status === "confirmed"'));
  assert.ok(source.includes("guide.normal_condition === true"));
});

test("the overlay viewer never modifies the video: only reads from the existing site-video route", () => {
  const source = grabFunction("createReadOnlyOverlayViewer");
  assert.ok(!/\bfetch\(|XMLHttpRequest/.test(source), "the viewer itself makes no network calls");
  assert.ok(html.includes("watchOverlayViewer.show(`/api/site-video?"));
  assert.ok(!html.includes('"/api/watch'), "no new watch-specific API route should exist");
});

test("status text covers the no-guide, confirmed, and unconfirmed cases", () => {
  const source = grabFunction("createReadOnlyOverlayViewer");
  assert.ok(source.includes("No normal waterline guide yet."));
  assert.ok(source.includes("confirmed normal waterline guide(s) shown"));
  assert.ok(source.includes("unconfirmed normal waterline guide(s) shown"));
});

test("a Watch button opens the viewer for a site with at least one video", () => {
  const buttonLine = script
    .split("\n")
    .find((line) => line.includes("openWatchViewerForSite("));
  assert.ok(buttonLine, "Watch button not found in renderSite()");
  assert.ok(buttonLine.includes("site.video_count > 0"));
  assert.ok(buttonLine.includes("disabled"));
});

test("normal waterline guides are shown on any video from the site, not gated on the video id", () => {
  const source = grabFunction("showWatchVideo");
  assert.ok(
    !source.includes("normal_waterline_guides.video_id === videoId"),
    "should not gate the site's normal waterline guides on the selected video's id"
  );
  assert.match(source, /normalWaterlineGuides = \(site && site\.normal_waterline_guides\)/);
});

test("the viewer draws every non-invalidated guide as a connected polyline, invalid ones excluded", () => {
  const source = grabFunction("createReadOnlyOverlayViewer");
  assert.ok(source.includes("trustedGuides"));
  assert.ok(source.includes("unconfirmedGuides"));
  assert.match(source, /guide\.status !== "invalid"/);
  assert.ok(source.includes("moveTo"));
  assert.ok(source.includes("lineTo"));
});

test("unconfirmed guides are drawn dashed and amber, confirmed guides solid and blue", () => {
  const source = grabFunction("createReadOnlyOverlayViewer");
  assert.match(source, /strokeStyle: "#d97706"[\s\S]*?dashed: true/);
  assert.match(source, /strokeStyle: "#1d4ed8"[\s\S]*?dashed: false/);
});
