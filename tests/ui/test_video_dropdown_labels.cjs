const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("friendly dropdown labels preserve manifest values and selection", () => {
  const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8");
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  new vm.Script(script);
  const start = script.indexOf("      const videoPurposeLabels =");
  const end = script.indexOf("\n      function ", script.indexOf("      function fillSelect(", start) + 10);
  const context = vm.createContext({ document: { createElement: () => ({}) } });
  vm.runInContext(script.slice(start, end), context);
  const purpose = {
    practice_normal_water: "Practice: normal water",
    possible_rising_water: "Possible rising water",
    possible_falling_water: "Possible falling water",
    no_clear_change: "No clear change",
    hard_case_review: "Hard case review",
    camera_video_problem: "Camera/video problem",
  };
  const difficult = {
    night_or_dark_frame: "Dark video",
    heavy_glare: "Glare on water",
    camera_shake: "Shaky camera",
    blocked_view: "Blocked view",
    camera_offline: "Camera offline",
    unreadable_video: "Unreadable video",
    missing_video: "Missing video",
    rain_or_noisy_image: "Rain or noisy image",
    compression_or_noise_artifacts: "Compression or image noise",
    empty_video: "Empty video",
  };
  for (const [mapping, variable, placeholder] of [
    [purpose, "videoPurposeLabels", "Choose purpose"],
    [difficult, "difficultCaseLabels", "No difficult case"],
  ]) {
    context.select = {
      value: Object.keys(mapping)[1],
      options: [],
      set innerHTML(value) { this.options = []; },
      append(option) { this.options.push(option); },
    };
    context.values = Object.keys(mapping);
    context.placeholder = placeholder;
    vm.runInContext("fillSelect(select, values, placeholder, " + variable + ")", context);
    assert.equal(context.select.value, Object.keys(mapping)[1]);
    assert.deepEqual(context.select.options.map(o => [o.value, o.textContent]),
      [["", placeholder], ...Object.entries(mapping)]);
  }
  assert.ok(html.includes('"Choose purpose", videoPurposeLabels)'));
  assert.ok(html.includes('"No difficult case", difficultCaseLabels)'));
});
