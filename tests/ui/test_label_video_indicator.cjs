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

function selectStub() {
  const options = [];
  return {
    value: "",
    options,
    set innerHTML(_value) {
      options.length = 0;
    },
    append(option) {
      options.push(option);
    },
  };
}

test("the label video dropdown marks which videos already have a human label", () => {
  const labelVideoSelect = selectStub();
  const labelValueSelect = selectStub();
  const labelVideoIdInput = { value: "" };
  const labelSiteSelect = { value: "river-site" };
  let labelVideoSite = "river-site";
  const source = grab("fillSelect") + "\n" + grab("updateLabelOptionsForSelectedSite");
  const context = vm.createContext({
    document: {
      createElement: () => ({ value: "", textContent: "" }),
    },
    latestSites: [
      {
        site_name: "river-site",
        video_ids: ["rising-001", "normal-001", "unlabeled-001"],
        labeled_video_ids: ["rising-001", "normal-001"],
        human_label_options: [],
      },
    ],
    labelSiteSelect,
    labelVideoSelect,
    labelValueSelect,
    labelVideoIdInput,
    get labelVideoSite() {
      return labelVideoSite;
    },
    set labelVideoSite(value) {
      labelVideoSite = value;
    },
    labelsForSelectedSite: () => [],
    humanLabelDisplayLabels: {},
    updateLabelTimeDefaults: () => {},
  });
  vm.runInContext(source, context);
  context.updateLabelOptionsForSelectedSite();

  const rendered = Object.fromEntries(
    labelVideoSelect.options.map((option) => [option.value, option.textContent])
  );
  assert.equal(rendered["rising-001"], "rising-001 (has a label)");
  assert.equal(rendered["normal-001"], "normal-001 (has a label)");
  assert.equal(rendered["unlabeled-001"], "unlabeled-001 (no label yet)");
});

test("a site with no labels at all marks every video as not yet labeled", () => {
  const labelVideoSelect = selectStub();
  const labelValueSelect = selectStub();
  const labelVideoIdInput = { value: "" };
  const labelSiteSelect = { value: "fresh-site" };
  const source = grab("fillSelect") + "\n" + grab("updateLabelOptionsForSelectedSite");
  const context = vm.createContext({
    document: { createElement: () => ({ value: "", textContent: "" }) },
    latestSites: [
      { site_name: "fresh-site", video_ids: ["only-video"], human_label_options: [] },
    ],
    labelSiteSelect,
    labelVideoSelect,
    labelValueSelect,
    labelVideoIdInput,
    labelVideoSite: "fresh-site",
    labelsForSelectedSite: () => [],
    humanLabelDisplayLabels: {},
    updateLabelTimeDefaults: () => {},
  });
  vm.runInContext(source, context);
  context.updateLabelOptionsForSelectedSite();

  const rendered = Object.fromEntries(
    labelVideoSelect.options.map((option) => [option.value, option.textContent])
  );
  assert.equal(rendered["only-video"], "only-video (no label yet)");
});
