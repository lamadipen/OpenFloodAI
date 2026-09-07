const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("comparison tags show readable status with accessible labels", () => {
  const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8");
  const helper = html.match(/function comparisonStatusTag\(status\) \{[\s\S]*?\n      \}/)[0];
  const context = vm.createContext({});
  vm.runInContext(helper, context);
  for (const [status, label, color] of [
    ["agree", "Agree", "ok"],
    ["disagree", "Disagree", "missing"],
    ["cannot_compare", "Cannot compare", "warn"],
    ["unknown", "Status unavailable", "warn"],
  ]) {
    const tag = context.comparisonStatusTag(status);
    assert.ok(tag.includes(`class="badge ${color}"`));
    assert.ok(tag.includes(`>${label}</span>`));
    assert.ok(tag.includes(`aria-label="Human comparison status: ${label}"`));
  }
});
