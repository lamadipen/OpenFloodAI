const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const standalonePanel = html.split('<section id="confirmedReferenceFormPanel"')[1].split("</section>")[0];
const setupSection = html.split('<div id="setupConfirmedReferenceSection"')[1];

function grabFunction(name) {
  const match = script.match(new RegExp(`      function ${name}\\([\\s\\S]*?\\n      \\}`));
  assert.ok(match, `${name} not found`);
  return match[0];
}

function grabBlock(name) {
  const start = script.indexOf(`      function ${name}(`);
  assert.ok(start >= 0, `${name} not found`);
  // The function's parameter list is itself a destructured `{ ... }`, so the
  // body's opening brace is the one right after the parameter list's `)`,
  // not the first `{` in the source from `start`.
  const paramsEnd = script.indexOf(")", start);
  const bodyStart = script.indexOf("{", paramsEnd);
  let depth = 0;
  for (let i = bodyStart; i < script.length; i += 1) {
    if (script[i] === "{") depth += 1;
    if (script[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        return script.slice(start, i + 1);
      }
    }
  }
  throw new Error(`Could not find end of ${name}`);
}

test("both forms have a Suggest Reference button", () => {
  assert.match(standalonePanel, /<button type="button" id="suggestReferenceButton"/);
  assert.match(setupSection, /<button type="button" id="setupSuggestReferenceButton"/);
});

test("suggestReferenceRegion makes no network calls", () => {
  const source = grabFunction("suggestReferenceRegion");
  assert.ok(!/\bfetch\(|XMLHttpRequest|axios/.test(source));
});

test("both selectors expose an origin() method and a suggestReference() method", () => {
  const confirmedSelector = grabBlock("createConfirmedReferenceSelector");
  const setupSelector = grabBlock("createSiteSetupSelector");
  for (const source of [confirmedSelector, setupSelector]) {
    assert.ok(source.includes("origin: () => origin"));
    assert.ok(source.includes("suggestReference: () => {"));
    assert.ok(source.includes("canSuggestReference: () =>"));
  }
});

test("both draw() functions have a machine_suggested rendering branch", () => {
  const confirmedSelector = grabBlock("createConfirmedReferenceSelector");
  const setupSelector = grabBlock("createSiteSetupSelector");
  for (const source of [confirmedSelector, setupSelector]) {
    assert.ok(source.includes('origin === "machine_suggested"'));
    assert.ok(source.includes("Suggested"));
  }
});

test("both save call sites include the selector's origin", () => {
  assert.ok(script.includes("origin: confirmedReferenceSelector.origin()"));
  assert.ok(script.includes("origin: setupVideoRegionSelector.origin()"));
});

function grabSuggestReferenceMethod(selectorSource) {
  const start = selectorSource.indexOf("suggestReference: () => {");
  assert.ok(start >= 0, "suggestReference method not found in selector");
  const bodyStart = selectorSource.indexOf("{", start);
  let depth = 0;
  for (let i = bodyStart; i < selectorSource.length; i += 1) {
    if (selectorSource[i] === "{") depth += 1;
    if (selectorSource[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        return selectorSource.slice(start, i + 1);
      }
    }
  }
  throw new Error("Could not find end of suggestReference method");
}

test("both selectors redraw the canvas before sampling pixels for a suggestion", () => {
  const confirmedSelector = grabBlock("createConfirmedReferenceSelector");
  const setupSelector = grabBlock("createSiteSetupSelector");
  for (const source of [confirmedSelector, setupSelector]) {
    const method = grabSuggestReferenceMethod(source);
    const drawIndex = method.indexOf("draw();");
    const sampleIndex = method.indexOf("suggestReferenceRegion(");
    assert.ok(drawIndex >= 0, "expected a draw() call before sampling pixels");
    assert.ok(sampleIndex >= 0, "expected a call to suggestReferenceRegion");
    assert.ok(
      drawIndex < sampleIndex,
      "draw() must run before suggestReferenceRegion() so the canvas matches the current paused frame"
    );
  }
});

test("a confirmed or invalidated record never displays as an unconfirmed suggestion", () => {
  const confirmedSelector = grabBlock("createConfirmedReferenceSelector");
  assert.ok(confirmedSelector.includes("let recordStatus = null;"));
  assert.ok(confirmedSelector.includes("recordStatus = pendingExisting.status || null;"));
  assert.match(
    confirmedSelector,
    /const isPendingSuggestion =\s*origin === "machine_suggested" && recordStatus !== "confirmed" && recordStatus !== "invalid";/
  );
  // The suggested/dashed rendering and label must be gated on the computed
  // flag, not on origin alone.
  assert.ok(confirmedSelector.includes("if (isPendingSuggestion) {"));
});

test("showConfirmedReferenceVideo passes the saved record's status to the selector", () => {
  assert.match(script, /videoTimeSeconds: existingRecord\.video_time_seconds,\s*origin: existingRecord\.origin,\s*status: existingRecord\.status,/);
});

test("a fresh manual drag resets origin back to manual", () => {
  const confirmedSelector = grabBlock("createConfirmedReferenceSelector");
  const setupSelector = grabBlock("createSiteSetupSelector");
  // The standalone selector resets origin inside its named clearSelection().
  assert.match(confirmedSelector, /function clearSelection\(\) \{\s*mainSelection = null;\s*origin = "manual";/);
  // The setup selector has no named clearSelection for mainSelection; it resets inline.
  const manualResets = setupSelector.match(/origin = "manual";/g) || [];
  assert.ok(manualResets.length >= 2, "expected origin to reset to manual in at least two places");
});

function evalSuggestionFunction() {
  const source = `${grabFunction("clampRectToBounds")}\n${grabFunction("suggestReferenceRegion")}\nsuggestReferenceRegion;`;
  return vm.runInNewContext(source, {});
}

function makeStubContext(width, height, rowValue) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let row = 0; row < height; row += 1) {
    const value = rowValue(row);
    for (let col = 0; col < width; col += 1) {
      const i = (row * width + col) * 4;
      data[i] = value;
      data[i + 1] = value;
      data[i + 2] = value;
      data[i + 3] = 255;
    }
  }
  return {
    getImageData: () => ({ data }),
  };
}

test("suggests a band near a sharp brightness step", () => {
  const suggestReferenceRegion = evalSuggestionFunction();
  const width = 40;
  const height = 100;
  const stepRow = 60;
  const context = makeStubContext(width, height, (row) => (row < stepRow ? 20 : 200));
  const guide = { x: 0, y: 0, width, height };

  const suggestion = suggestReferenceRegion(context, guide);

  assert.ok(suggestion, "expected a suggestion for a clear brightness step");
  assert.ok(suggestion.y <= stepRow && suggestion.y + suggestion.height >= stepRow - 1);
  assert.ok(suggestion.x >= guide.x && suggestion.x + suggestion.width <= guide.x + guide.width);
  assert.ok(suggestion.y >= guide.y && suggestion.y + suggestion.height <= guide.y + guide.height);
});

test("returns null, not a throw, for a flat edge-less image", () => {
  const suggestReferenceRegion = evalSuggestionFunction();
  const context = makeStubContext(40, 100, () => 128);

  const suggestion = suggestReferenceRegion(context, { x: 0, y: 0, width: 40, height: 100 });

  assert.equal(suggestion, null);
});

test("returns null, not a throw, for a too-small guide", () => {
  const suggestReferenceRegion = evalSuggestionFunction();
  const context = makeStubContext(4, 4, () => 128);

  const suggestion = suggestReferenceRegion(context, { x: 0, y: 0, width: 4, height: 4 });

  assert.equal(suggestion, null);
});

test("returns null, not a throw, when getImageData throws", () => {
  const suggestReferenceRegion = evalSuggestionFunction();
  const context = {
    getImageData: () => {
      throw new Error("tainted canvas");
    },
  };

  const suggestion = suggestReferenceRegion(context, { x: 0, y: 0, width: 40, height: 100 });

  assert.equal(suggestion, null);
});
