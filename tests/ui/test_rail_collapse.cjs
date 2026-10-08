const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const shared = fs.readFileSync(path.join(__dirname, "../../tools/console/shared.js"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "../../tools/console/shared.css"), "utf8");

function make(stored) {
  const classes = new Set();
  const attrs = {};
  const toggle = { title: "", setAttribute(k, v) { attrs[k] = v; } };
  const sandbox = {
    document: {
      querySelector: () => ({ classList: { toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)), contains: (c) => classes.has(c) } }),
      getElementById: (id) => (id === "railToggle" ? toggle : null)
    },
    localStorage: {
      store: stored === undefined ? {} : { "openfloodai.railCollapsed": stored },
      getItem(k) { return this.store[k] ?? null; },
      setItem(k, v) { this.store[k] = v; }
    }
  };
  vm.createContext(sandbox);
  const start = shared.indexOf("const RAIL_COLLAPSED_KEY");
  vm.runInContext(shared.slice(start, shared.indexOf("function mountShell(")), sandbox);
  return { sandbox, classes, attrs, toggle };
}

test("the rail starts open and remembers being collapsed", () => {
  assert.equal(make().sandbox.loadRailCollapsed(), false);
  assert.equal(make("1").sandbox.loadRailCollapsed(), true);
  assert.equal(make("0").sandbox.loadRailCollapsed(), false);
});

test("collapsing updates the class, the button's state and the saved choice", () => {
  const { sandbox, classes, attrs, toggle } = make();
  sandbox.setRailCollapsed(true);
  assert.equal(classes.has("rail-collapsed"), true);
  assert.equal(attrs["aria-expanded"], "false");
  assert.equal(attrs["aria-label"], "Expand navigation");
  assert.equal(toggle.title, "Expand navigation");
  assert.equal(sandbox.localStorage.store["openfloodai.railCollapsed"], "1");
  sandbox.setRailCollapsed(false);
  assert.equal(classes.has("rail-collapsed"), false);
  assert.equal(attrs["aria-expanded"], "true");
  assert.equal(sandbox.localStorage.store["openfloodai.railCollapsed"], "0");
});

test("a blocked browser store does not break the rail", () => {
  const { sandbox } = make();
  sandbox.localStorage = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.equal(sandbox.loadRailCollapsed(), false);
  assert.doesNotThrow(() => sandbox.setRailCollapsed(true));
});

test("the shell has a labelled toggle button, text labels to hide, and the collapsed styles", () => {
  assert.match(shared, /id="railToggle"[^>]*aria-expanded="true"[^>]*aria-label="Collapse navigation"/);
  for (const label of ["Dashboard", "Sites", "Settings"]) {
    assert.match(shared, new RegExp(`title="${label}">\\$\\{svgIcon\\("[a-z]+"\\)\\}<span class="rail-label">${label}</span>`));
  }
  assert.match(css, /\.app-shell\.rail-collapsed \.rail \{ width: 64px; \}/);
  assert.match(css, /\.app-shell\.rail-collapsed \.rail-sites/);
  assert.match(css, /prefers-reduced-motion/);
});
