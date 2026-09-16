const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(
  path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8"
);
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function grabDispatcher() {
  const match = script.match(/loadSites\(\)\.then\(\(\) => \{[\s\S]*?\n      \}\);/);
  assert.ok(match, "the site-details deep-link dispatcher was not found");
  return match[0];
}

function makeContext({ search, openers = {} }) {
  const replaceStateCalls = [];
  return vm.createContext({
    loadSites: () => Promise.resolve(),
    window: {
      location: { search, pathname: "/openfloodai-home-ui.html" },
      ...openers,
    },
    URLSearchParams,
    history: {
      replaceState: (...args) => replaceStateCalls.push(args),
    },
    _replaceStateCalls: replaceStateCalls,
  });
}

async function flush(context, source) {
  vm.runInContext(source, context);
  // The dispatcher runs inside loadSites().then(...); let that microtask settle.
  await new Promise((resolve) => setTimeout(resolve, 0));
}

test("a recognized action opens the matching form for the requested site", async () => {
  const calls = [];
  const context = makeContext({
    search: "?site=river-site&action=add_video",
    openers: { openVideoFormForSite: (site) => calls.push(site) },
  });
  await flush(context, grabDispatcher());
  assert.deepEqual(calls, ["river-site"]);
});

test("every quick-action id on the site-details page maps to a real opener function", async () => {
  const actionToOpener = {
    add_video: "openVideoFormForSite",
    add_label: "openLabelFormForSite",
    set_watched_area: "openWatchedAreaFormForSite",
    set_normal_waterline_guide: "openNormalWaterlineGuideFormForSite",
    watch: "openWatchViewerForSite",
  };
  for (const [action, openerName] of Object.entries(actionToOpener)) {
    const calls = [];
    const context = makeContext({
      search: `?site=river-site&action=${action}`,
      openers: { [openerName]: (site) => calls.push(site) },
    });
    await flush(context, grabDispatcher());
    assert.deepEqual(calls, ["river-site"], `action "${action}" did not call ${openerName}`);
  }
});

test("the query string is cleared after opening, so a later refresh does not reopen it", async () => {
  const context = makeContext({
    search: "?site=river-site&action=add_video",
    openers: { openVideoFormForSite: () => {} },
  });
  await flush(context, grabDispatcher());
  assert.deepEqual(context._replaceStateCalls, [[null, "", "/openfloodai-home-ui.html"]]);
});

test("an unknown action, or a missing site or action, opens nothing and does not touch history", async () => {
  for (const search of ["?site=river-site&action=delete_everything", "?action=add_video", "?site=river-site", ""]) {
    const calls = [];
    const context = makeContext({
      search,
      openers: {
        openVideoFormForSite: (site) => calls.push(site),
        openLabelFormForSite: (site) => calls.push(site),
        openWatchedAreaFormForSite: (site) => calls.push(site),
        openNormalWaterlineGuideFormForSite: (site) => calls.push(site),
        openWatchViewerForSite: (site) => calls.push(site),
      },
    });
    await flush(context, grabDispatcher());
    assert.deepEqual(calls, [], `search "${search}" should not have opened anything`);
    assert.deepEqual(context._replaceStateCalls, [], `search "${search}" should not have touched history`);
  }
});
