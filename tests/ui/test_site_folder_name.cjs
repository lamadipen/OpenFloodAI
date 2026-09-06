const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

test("site name input fills the submitted folder field", () => {
  const html = fs.readFileSync(
    path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8"
  );
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  new vm.Script(script);
  const listeners = {};
  const name = {
    value: "",
    addEventListener(event, callback) { listeners[event] = callback; },
  };
  const folder = { value: "" };
  const fields = {
    "#setupSiteNameInput": name,
    "#setupFolderNameInput": folder,
  };
  const start = script.indexOf("      const setupSiteNameInput =");
  const end = script.indexOf("\n      });", start) + "\n      });".length;
  assert.ok(start >= 0 && end > start);
  vm.runInNewContext(script.slice(start, end), {
    document: { querySelector: (selector) => fields[selector] },
  });
  for (const [input, expected] of [
    ["Colorado River Site", "colorado-river-site"],
    ["  Demo   Bridge  ", "demo-bridge"],
    ["River\tNorth", "river-north"],
    ["Demo-Bridge", "demo-bridge"],
    ["River@Bridge!_01", "riverbridge_01"],
    ["UPPER_case-123", "upper_case-123"],
    ["../River/Bridge", "riverbridge"],
    ["!@#$%", ""],
    ["", ""],
    ["   ", ""],
  ]) {
    name.value = input;
    listeners.input();
    assert.equal(folder.value, expected);
  }
  name.value = folder.value = "";
  name.value = "Next Site";
  listeners.input();
  assert.equal(folder.value, "next-site");
  assert.match(html, /name="folder_name" id="setupFolderNameInput"/);
  assert.ok(html.indexOf('id="setupSiteNameInput"') < html.indexOf('id="setupFolderNameInput"'));
});
