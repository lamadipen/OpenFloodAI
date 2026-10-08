const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const dir = path.join(__dirname, "../../tools/console");
const css = fs.readFileSync(path.join(dir, "shared.css"), "utf8");
const shared = fs.readFileSync(path.join(dir, "shared.js"), "utf8");
const pages = fs.readdirSync(dir).filter((f) => f.endsWith(".html"));

function token(name) {
  const match = css.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`));
  assert.ok(match, `token --${name} not found`);
  return match[1];
}

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

test("text colours meet 4.5:1 on the surfaces they are used on", () => {
  const pairs = [
    ["ink-muted", "card"], ["ink-muted", "paper"], ["ink-muted", "line-soft"],
    ["ink-soft", "card"], ["ink", "card"],
    ["rail-text-dim", "rail"], ["rail-text", "rail"],
    ["warn", "warn-soft"], ["ok", "ok-soft"], ["bad", "bad-soft"], ["accent", "accent-soft"],
    ["sam", "sam-soft"]
  ];
  for (const [fg, bg] of pairs) {
    const ratio = contrast(token(fg), token(bg));
    assert.ok(ratio >= 4.5, `${fg} on ${bg} is ${ratio.toFixed(2)}:1`);
  }
});

test("everything that can be pressed or followed has a visible keyboard focus", () => {
  assert.match(css, /button:focus-visible/);
  assert.match(css, /a:focus-visible/);
  assert.match(css, /\[role="button"\]:focus-visible/);
});

test("no page asks another site for fonts, so the console works offline and sends nothing out", () => {
  for (const page of pages) {
    const html = fs.readFileSync(path.join(dir, page), "utf8");
    assert.doesNotMatch(html, /fonts\.googleapis\.com|fonts\.gstatic\.com/, page);
  }
  assert.doesNotMatch(css, /googleapis|gstatic/);
});

test("small text is at least 11px in inline styles, and hints are 12px", () => {
  for (const page of pages) {
    const html = fs.readFileSync(path.join(dir, page), "utf8");
    assert.doesNotMatch(html, /font-size:(9|10)(\.\d+)?px/, page);
  }
  assert.match(css, /\.hint \{\s*font-size: 12px;/);
});

test("the review page loads its script files in dependency order and starts last", () => {
  const html = fs.readFileSync(path.join(dir, "review.html"), "utf8");
  const order = [...html.matchAll(/<script src="\/console\/([^"]+)"><\/script>/g)].map((m) => m[1]);
  assert.deepEqual(order, ["shared.js", "review.js", "review-charts.js", "review-sam.js", "review-onion.js"]);
  assert.match(html, /<script>main\(\);<\/script>\s*<\/body>/);
  assert.ok(html.split("\n").length < 60, "review.html should hold markup only");
});

// ---- keepFocus ------------------------------------------------------------------------------

function makeFocusEnv() {
  const start = shared.indexOf("function focusSignature(");
  const end = shared.indexOf('function qs(name, fallback = "")');
  let focused = null;
  const mk = (tag, attrs) => ({
    tagName: tag,
    attributes: Object.entries(attrs).map(([name, value]) => ({ name, value })),
    getAttribute(n) { return attrs[n] ?? null; },
    focus() { focused = this; }
  });
  const rootChildren = [];
  const root = {
    contains: (el) => rootChildren.includes(el),
    querySelectorAll: (tag) => rootChildren.filter((c) => c.tagName === tag.toUpperCase())
  };
  const sandbox = { document: { body: mk("BODY", {}), activeElement: null }, window: { scrollY: 120, scrollX: 0, scrollTo(x, y) { sandbox.scrolledTo = [x, y]; } } };
  vm.createContext(sandbox);
  vm.runInContext(shared.slice(start, end), sandbox);
  return { sandbox, root, rootChildren, mk, get focused() { return focused; } };
}

test("keepFocus puts focus back on the matching control after a redraw and restores scroll", () => {
  const env = makeFocusEnv();
  const oldBtn = env.mk("BUTTON", { "data-act": "next-image" });
  env.rootChildren.push(oldBtn);
  env.sandbox.document.activeElement = oldBtn;
  env.sandbox.keepFocus(env.root, () => {
    env.rootChildren.length = 0;
    env.rootChildren.push(env.mk("BUTTON", { "data-act": "prev-image" }), env.mk("BUTTON", { "data-act": "next-image" }));
  });
  assert.equal(env.focused.getAttribute("data-act"), "next-image");
  assert.deepEqual(env.sandbox.scrolledTo, [0, 120]);
});

test("keepFocus does nothing special when focus was not inside the redrawn area", () => {
  const env = makeFocusEnv();
  env.sandbox.document.activeElement = env.sandbox.document.body;
  let drawn = 0;
  env.sandbox.keepFocus(env.root, () => { drawn += 1; });
  assert.equal(drawn, 1);
  assert.equal(env.focused, null);
});
