const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("site Add Video opens a fresh intake form for the requested site", () => {
  const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8");
  assert.ok(!html.includes("addVideoButton"));
  const handler = html.match(/window\.openVideoFormForSite = function \(siteName\) \{[\s\S]*?\n      \};/)[0];
  const events = [];
  const panel = { style: { display: "none" } };
  const select = { value: "previous-site" };
  const context = vm.createContext({
    window: {},
    hideForms: () => events.push("hide"),
    videoForm: { reset: () => events.push("reset") },
    resetVideoPreview: () => events.push("preview-reset"),
    videoSiteSelect: select,
    videoFormPanel: panel,
    revealPanel: (value) => assert.equal(value, panel),
  });
  vm.runInContext(handler, context);
  context.window.openVideoFormForSite("river-site");
  assert.equal(select.value, "river-site");
  assert.equal(panel.style.display, "block");
  assert.deepEqual(events, ["hide", "reset", "preview-reset"]);
  context.window.openVideoFormForSite("another-site");
  assert.equal(select.value, "another-site");
});

test("site Add Label opens a fresh label form and loads that site's options", () => {
  const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8");
  const handler = html.match(/window\.openLabelFormForSite = function \(siteName\) \{[\s\S]*?\n      \};/)[0];
  const events = [];
  const panel = { style: { display: "none" } };
  const select = { value: "previous-site" };
  const context = vm.createContext({
    window: {},
    hideForms: () => events.push("hide"),
    labelForm: { reset: () => events.push("reset") },
    labelSiteSelect: select,
    updateLabelOptionsForSelectedSite: () => events.push(select.value),
    labelFormPanel: panel,
    addLabelButton: { style: { display: "inline-block" } },
    revealPanel: (value) => assert.equal(value, panel),
  });
  vm.runInContext(handler, context);
  context.window.openLabelFormForSite("river-site");
  assert.equal(select.value, "river-site");
  assert.equal(panel.style.display, "block");
  assert.deepEqual(events, ["hide", "reset", "river-site"]);
  context.window.openLabelFormForSite("another-site");
  assert.equal(select.value, "another-site");
  assert.deepEqual(events.slice(3), ["hide", "reset", "another-site"]);
});
