const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("human label dropdown displays friendly text while retaining saved values", () => {
  const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8");
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  new vm.Script(script);
  const start = script.indexOf("      const humanLabelDisplayLabels =");
  const end = script.indexOf("\n      function ", script.indexOf("      function fillSelect(", start) + 10);
  const select = {
    value: "water_falling",
    options: [],
    set innerHTML(value) { this.options = []; },
    append(option) { this.options.push(option); },
  };
  const expected = [
    ["", "Choose human label"],
    ["water_rising", "Water is rising"],
    ["water_falling", "Water is falling"],
    ["no_clear_change", "No clear water change"],
    ["cannot_judge", "I cannot judge from this video"],
    ["camera_video_problem", "Camera or video problem"],
    ["bridge_pillar_covered", "bridge_pillar_covered"],
  ];
  const context = vm.createContext({
    document: { createElement: () => ({}) },
    select,
    values: expected.slice(1).map(([value]) => value),
  });
  vm.runInContext(script.slice(start, end), context);
  vm.runInContext('fillSelect(select, values, "Choose human label", humanLabelDisplayLabels)', context);
  assert.deepEqual(select.options.map(option => [option.value, option.textContent]), expected);
  assert.equal(select.value, "water_falling");
  assert.ok(html.includes('fillSelect(labelValueSelect, labelsForSelectedSite(), "Choose human label", humanLabelDisplayLabels)'));
  const panel = html.split('<section id="labelFormPanel"')[1].split("</section>")[0];
  assert.ok(panel.includes("Choose what a person sees in this video time window. This is used only when comparing human review with machine result."));
  assert.match(panel, /name="human_label" id="labelValueSelect" aria-describedby="humanLabelHelp"/);
});
