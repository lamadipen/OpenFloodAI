const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

for (const fails of [false, true]) {
  test(`validation spinner clears on ${fails ? "failure" : "success"} and blocks duplicate requests`, async () => {
    const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8");
    const start = html.indexOf("      const runningValidationSites =");
    const end = html.indexOf("      window.repairManifestForSite", start);
    let finish;
    let calls = 0;
    const pending = new Promise(resolve => { finish = resolve; });
    const button = {
      innerHTML: "Run Validation", disabled: false,
      setAttribute(name, value) { this[name] = value; },
      removeAttribute(name) { delete this[name]; },
    };
    const context = vm.createContext({
      window: {},
      fetch: async () => {
        calls++;
        await pending;
        if (fails) throw new Error("Connection lost");
        return { ok: true, json: async () => ({ success: true, counts: { agree: 1, disagree: 0, cannot_compare: 0 } }) };
      },
      alert: () => assert.equal(button.innerHTML, "Run Validation"),
      loadSites: async () => {},
    });
    vm.runInContext(html.slice(start, end), context);
    const run = context.window.runValidationForSite("river", button);
    assert.equal(button.disabled, true);
    assert.equal(button["aria-busy"], "true");
    assert.ok(button.innerHTML.includes("validation-spinner"));
    await context.window.runValidationForSite("river", button);
    assert.equal(calls, 1);
    finish();
    await run;
    assert.equal(button.disabled, false);
    assert.equal(button.innerHTML, "Run Validation");
    assert.equal(button["aria-busy"], undefined);
    await context.window.runValidationForSite("river", button);
    assert.equal(calls, 2);
  });
}
