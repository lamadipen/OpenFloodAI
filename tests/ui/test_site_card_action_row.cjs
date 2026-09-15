const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function grabFunction(name) {
  const match = script.match(new RegExp(`      function ${name}\\([\\s\\S]*?\\n      \\}`));
  assert.ok(match, `${name} not found`);
  return match[0];
}

test("the site card's action button row wraps instead of overflowing and being clipped", () => {
  const renderSite = grabFunction("renderSite");
  const actionRow = renderSite.match(/<div style="padding: 0 18px 14px;[^"]*">/);
  assert.ok(actionRow, "site card action row div not found");
  assert.match(
    actionRow[0],
    /flex-wrap:\s*wrap/,
    "the action row must wrap so Watch/Details View aren't clipped by .site-card's overflow: hidden once there are enough buttons to overflow a narrow card"
  );
});
