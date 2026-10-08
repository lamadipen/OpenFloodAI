const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = require("./review_source.cjs").reviewHtml();
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const helpers = script.slice(
  script.indexOf("function gaugeKey"),
  script.indexOf("// Granularity bucketing")
);

function context(evidence) {
  const sandbox = { escapeHtml: (value) => String(value), Number, Date, Map, String };
  vm.createContext(sandbox);
  vm.runInContext(helpers + "\nvar gaugeEvidence, gaugeImages;", sandbox);
  sandbox.gaugeEvidence = evidence;
  sandbox.gaugeImages = sandbox.buildGaugeImages(evidence);
  return sandbox;
}

const reading = (stamp, value, extra = {}) => ({
  datetime_utc: stamp,
  value,
  parameter_code: "00065",
  parameter_label: "gage height",
  unit: "ft",
  qualifiers: ["P"],
  quality_status: "provisional",
  ...extra
});

const evidence = {
  captured: true,
  status: "available",
  images: [
    {
      filename: "a.jpg",
      captured_at_utc: "2026-09-01T08:00:00+00:00",
      match_status: "matched",
      reading: reading("2026-09-01T08:10:00+00:00", 3.21),
      time_difference_seconds: 600
    },
    {
      filename: "b.jpg",
      captured_at_utc: "2026-09-01T18:00:00+00:00",
      match_status: "no_matching_reading",
      reading: null,
      time_difference_seconds: null
    }
  ]
};
const day = (filename, capturedAtUtc) => ({ filename, capturedAtUtc, time: "12:00" });

test("two images on the same day keep their own reading and gap", () => {
  const ctx = context(evidence);
  const first = ctx.selectedGaugeHtml(day("a.jpg", "2026-09-01T08:00:00+00:00"));
  const second = ctx.selectedGaugeHtml(day("b.jpg", "2026-09-01T18:00:00+00:00"));
  assert.match(first, /Gage height 3\.21 ft/);
  assert.match(first, /10 min after the image/);
  assert.match(first, /2026-09-01 08:10 UTC/);
  assert.match(first, /Provisional/);
  assert.doesNotMatch(second, /3\.21/);
  assert.match(second, /No matching gauge reading\./);
});

test("an older run without frozen evidence says it was not captured", () => {
  const ctx = context({ captured: false, status: "not_captured", images: [] });
  const text = ctx.selectedGaugeHtml(day("a.jpg", "2026-09-01T08:00:00+00:00"));
  assert.match(text, /No matching gauge reading\./);
  assert.match(text, /not captured/);
  assert.match(ctx.gaugeEmptyStateText(), /not captured/);
});

test("service-unavailable and no-station states read differently", () => {
  assert.notEqual(
    context({ captured: true, status: "service_unavailable", images: [] }).gaugeEmptyStateText(),
    context({ captured: true, status: "no_station_association", images: [] }).gaugeEmptyStateText()
  );
});

test("a discharge reading is labelled as discharge, never as gage height", () => {
  const ctx = context({
    captured: true,
    status: "available",
    images: [
      {
        filename: "a.jpg",
        captured_at_utc: "2026-09-01T08:00:00+00:00",
        reading: reading("2026-09-01T08:00:00+00:00", 450, {
          parameter_code: "00060",
          parameter_label: "discharge",
          unit: "ft3/s",
          used_fallback_discharge: true
        }),
        time_difference_seconds: 0
      }
    ]
  });
  const text = ctx.selectedGaugeHtml(day("a.jpg", "2026-09-01T08:00:00+00:00"));
  assert.match(text, /Discharge 450\.00 ft3\/s/);
  assert.match(text, /not gage height/);
  assert.match(text, /same minute/);
});

test("a peak event with no image in the window says so", () => {
  const ctx = context({
    ...evidence,
    peak_events: {
      highest: {
        event_reading: reading("2026-09-01T12:00:00+00:00", 9),
        image_status: "no_matching_image",
        image_filename: null
      },
      lowest: null
    }
  });
  assert.match(ctx.gaugePeakEventsHtml(), /No matching image within 15 minutes/);
});
