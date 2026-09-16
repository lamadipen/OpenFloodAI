const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(
  path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8"
);
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function grab(name) {
  const match = script.match(
    new RegExp(`      function ${name}\\([\\s\\S]*?\\n      \\}`)
  );
  assert.ok(match, `${name} not found`);
  return match[0];
}

function runRenderValidationSummary(site) {
  const source =
    grab("scorecardValue") +
    "\n" +
    grab("detailItem") +
    "\n" +
    grab("reviewImagesControls") +
    "\n" +
    grab("renderValidationSummary");
  const context = vm.createContext({
    escapeHtml: (value) => String(value),
    site,
  });
  vm.runInContext(source, context);
  return context.renderValidationSummary(site);
}

test("the validation summary shows how many videos have a human label, not just a count of label windows", () => {
  const rendered = runRenderValidationSummary({
    latest_scorecard: {
      videos_tested: 2,
      videos_with_human_label: 1,
      label_windows: 1,
      agree: 0,
      disagree: 0,
      cannot_compare: 2,
      human_review_needed: 2,
    },
  });
  assert.match(rendered, /Videos tested: 2/);
  assert.match(rendered, /Videos with a human label: 1 of 2/);
  assert.match(rendered, /Label windows: 1/);
});

test("an unavailable scorecard field says so instead of showing a misleading number", () => {
  const rendered = runRenderValidationSummary({
    latest_scorecard: { agree: 0, disagree: 0, cannot_compare: 0 },
  });
  assert.match(rendered, /Videos with a human label: Not available/);
});

test("no validation run yet still says so plainly", () => {
  const rendered = runRenderValidationSummary({});
  assert.match(rendered, /No validation has been run yet\./);
});
