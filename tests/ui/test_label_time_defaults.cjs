const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("label times follow the selected video and preserve manual edits and newer selections", async () => {
  const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8");
  const start = html.indexOf("      let labelDurationKey =");
  const end = html.indexOf("      function updateLabelOptionsForSelectedSite", start);
  const field = value => ({ value, listeners: {}, addEventListener(event, callback) { this.listeners[event] = callback; } });
  const startInput = field("");
  const endInput = field("");
  const videoInput = field("first");
  const requests = [];
  const help = {};
  const form = field("");
  const context = vm.createContext({
    labelStartInput: startInput, labelEndInput: endInput,
    labelVideoIdInput: videoInput, labelSiteSelect: field("river"), labelForm: form,
    document: { querySelector: () => help },
    fetch: () => new Promise(resolve => requests.push(resolve)),
  });
  vm.runInContext(html.slice(start, end), context);
  const respond = duration => ({ ok: true, json: async () => ({ duration_seconds: duration }) });
  let pending = context.updateLabelTimeDefaults();
  assert.equal(startInput.value, "0");
  requests.shift()(respond(60));
  await pending;
  assert.equal(endInput.value, "60");
  endInput.value = "20";
  endInput.listeners.input();
  await context.updateLabelTimeDefaults();
  assert.equal(endInput.value, "20");

  videoInput.value = "second";
  pending = context.updateLabelTimeDefaults();
  endInput.value = "15";
  endInput.listeners.input();
  requests.shift()(respond(90));
  await pending;
  assert.equal(endInput.value, "15");

  videoInput.value = "third";
  pending = context.updateLabelTimeDefaults();
  videoInput.value = "fourth";
  const newer = context.updateLabelTimeDefaults();
  requests.shift()(respond(100));
  await pending;
  assert.equal(endInput.value, "");
  requests.shift()({ ok: false });
  await newer;
  assert.ok(help.textContent.includes("Enter the end time yourself"));
  form.listeners.reset();
  pending = context.updateLabelTimeDefaults();
  requests.shift()(respond(30));
  await pending;
  assert.equal(endInput.value, "30");
});
