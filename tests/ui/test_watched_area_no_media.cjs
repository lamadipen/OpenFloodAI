const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const read = (name) => fs.readFileSync(path.join(__dirname, "../../tools/console", name), "utf8");
const scriptOf = (html) => html.split("<script>").pop().split("</script>")[0];

const NO_MEDIA = "This site has no downloaded image sequence and no video yet. Add media first from Site &rarr; Setup &rarr; Add media.";

function mainSource(html) {
  const script = scriptOf(html);
  const start = script.indexOf("async function main() {");
  const end = script.indexOf("\n}\n", start) + 3;
  return script.slice(start, end);
}

// Runs the page's own main() against a stub page. The Save button lives INSIDE #body, so
// once the body's content is replaced it no longer exists, exactly as in the real page.
async function runWatchedArea(apiResponses) {
  const state = { body: "<button id=saveBtn></button>", hasSaveButton: true, saveDisabledSet: 0 };
  const sandbox = {
    folderName: "site-a",
    saved: null, rect: { x: 1, y: 1, width: 2, height: 2 },
    sequenceId: null, baselineFilename: null, videoId: null,
    escapeHtml: (v) => String(v),
    URLSearchParams,
    paintBox() {},
    loadVideoSource: async () => {},
    document: { body: {} },
    api: async (url) => {
      const key = Object.keys(apiResponses).find((k) => url.startsWith(k));
      if (!key) throw new Error("unexpected " + url);
      return apiResponses[key];
    },
    $: (id) => {
      if (id === "body") {
        return { set innerHTML(value) { state.body = value; state.hasSaveButton = false; }, get innerHTML() { return state.body; } };
      }
      if (id === "saveBtn") {
        if (!state.hasSaveButton) return null; // removed together with the replaced body
        return { set disabled(v) { state.saveDisabledSet += 1; } };
      }
      return { href: "", textContent: "", style: {}, set src(v) {}, setAttribute() {} };
    }
  };
  vm.createContext(sandbox);
  vm.runInContext(mainSource(read("form-watched-area.html")) + "\nmain;", sandbox);
  await vm.runInContext("main()", sandbox);
  return state;
}

const EMPTY = {
  "/api/site-config": { config: { reference_region: null } },
  "/api/site-image-sequences": { sequences: [] },
  "/api/site-manifest": { records: [] }
};

test("a site with no media shows the no-media message, not a script error", async () => {
  const state = await runWatchedArea(EMPTY);
  assert.equal(state.body.includes("Could not load this site"), false);
  assert.match(state.body, /This site has no downloaded image sequence and no video yet\./);
  assert.match(state.body, /Add media first from Site &rarr; Setup &rarr; Add media\./);
});

test("the watched-area message matches the riverbank guides message exactly", () => {
  const guide = read("form-waterline-guide.html");
  const area = read("form-watched-area.html");
  assert.ok(guide.includes(NO_MEDIA), "guides editor message");
  assert.ok(area.includes(NO_MEDIA), "watched area message");
});

test("a site with a downloaded image sequence still loads the editor", async () => {
  const state = await runWatchedArea({
    ...EMPTY,
    "/api/site-image-sequences": {
      sequences: [{ sequence_id: "seq", records: [{ filename: "a.jpg", download_status: "downloaded" }] }]
    }
  });
  assert.equal(state.body.includes("This site has no downloaded"), false);
  assert.equal(state.body.includes("Could not load"), false);
});

test("a real loading failure is still reported as one", async () => {
  const state = await runWatchedArea({ "/api/site-config": null });
  assert.match(state.body, /Could not load this site/);
});

test("nothing in main() touches the Save button after the body was replaced", () => {
  const src = mainSource(read("form-watched-area.html"));
  const afterReplace = src.slice(src.indexOf("This site has no downloaded"));
  assert.doesNotMatch(afterReplace.split("catch")[0], /saveBtn/);
});
