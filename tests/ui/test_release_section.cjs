const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const dir = path.join(__dirname, "../../tools/console");
const read = (name) => fs.readFileSync(path.join(dir, name), "utf8");
const escapeHtml = (v) => String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function make() {
  const sandbox = {
    escapeHtml,
    dsPage: { id: "d1", view: null },
    api: async () => ({}),
    post: async () => ({}),
    refresh: async () => {},
    render() {},
    $: () => null,
    URLSearchParams,
    CSS: { escape: (s) => s },
    document: {}
  };
  vm.createContext(sandbox);
  vm.runInContext(read("datasets-release.js"), sandbox);
  sandbox.relPage = vm.runInContext("relPage", sandbox);
  return sandbox;
}

const READINESS = (over = {}) => ({
  examples: 4,
  sources: [{ name: "usgs_nims", approved: false }],
  sites: [{ site_id: "site_sid", approved: false }],
  annotation_license_recorded: false,
  missing: ["The annotation license has not been recorded."],
  can_build: false,
  ...over
});
const VIEW = { versions: [{ version: 1, examples: 4 }] };

function ready(c, over) {
  c.relPage.policy = { annotation_license: null, sources: {}, sites: {} };
  c.relPage.readiness = READINESS(over);
  c.relPage.releases = [];
  c.relPage.upload = { token_env: "HF_TOKEN", token_set: false, hub_installed: false, private_only: true };
  c.relPage.version = 1;
}

test("the section asks for a frozen version first", () => {
  const c = make();
  assert.match(c.releaseSectionHtml({ versions: [] }), /Freeze a version first/);
});

test("approvals show what is missing, never fill anything in, and say who must approve", () => {
  const c = make();
  ready(c);
  const html = c.releaseSectionHtml(VIEW);
  assert.match(html, /Nothing is filled in for you/);
  assert.equal((html.match(/Needs approval/g) || []).length, 3); // license, source, site
  assert.match(html, /People's faces/);
  assert.match(html, /License plates/);
  assert.match(html, /Private property/);
  assert.match(html, /data-save-site="site_sid"/);
});

test("approved items show who approved them", () => {
  const c = make();
  ready(c, { sources: [{ name: "usgs_nims", approved: true }], sites: [{ site_id: "site_sid", approved: true }], can_build: true, missing: [] });
  c.relPage.policy = {
    annotation_license: { spdx_id: "CC-BY-4.0", holder: "H", approved_by: "Lead" },
    sources: { usgs_nims: { credit: "Images courtesy of the U.S. Geological Survey" } },
    sites: { site_sid: { privacy_review: { reviewed_by: "Rev" }, location: { mode: "generalized" } } }
  };
  const html = c.releaseSectionHtml(VIEW);
  assert.match(html, /CC-BY-4\.0, held by H, approved by Lead/);
  assert.match(html, /Reviewed by Rev · location: generalized/);
  assert.match(html, /Approvals are in place/);
});

test("the build button is disabled, with reasons, until the approvals are in place", () => {
  const c = make();
  ready(c);
  const blocked = c.releaseSectionHtml(VIEW);
  assert.match(blocked, /Not ready to build/);
  assert.match(blocked, /The annotation license has not been recorded\./);
  assert.match(blocked, /id="buildRelease" disabled/);
  ready(c, { missing: [], can_build: true });
  assert.doesNotMatch(c.releaseSectionHtml(VIEW), /id="buildRelease" disabled/);
});

test("a release number picks the draft or public channel", () => {
  const c = make();
  assert.equal(c.releaseChannel("v0.1"), "draft");
  assert.equal(c.releaseChannel("v1.0"), "public");
  assert.equal(c.releaseChannel("1.0"), null);
});

function release(over = {}) {
  return {
    release_version: "v0.1", channel: "draft", publication_ready: false, source_version: 1,
    counts: { released: 4, rejected: 1, images: 4, masks: 0, by_split: { train: 4 } },
    readiness_gaps: [{ message: "No released camera is in the test split." }],
    checklist: [{ index: 0, checked: true, text: "Run verify" }, { index: 1, checked: false, text: "Upload <privately> first" }],
    ...over
  };
}

test("a release card shows counts, gaps, and the verify, checklist, upload and Kaggle actions", () => {
  const c = make();
  ready(c, { missing: [], can_build: true });
  c.relPage.releases = [release()];
  const html = c.releaseSectionHtml(VIEW);
  assert.match(html, /4 examples \(train 4\), 4 images, 1 left out\. Built from frozen v1/);
  assert.match(html, /No released camera is in the test split\./);
  assert.match(html, /data-verify-release="v0\.1"/);
  assert.match(html, /Checklist \(1\/2\)/);
  assert.match(html, /data-toggle-upload="v0\.1"/);
  assert.match(html, /data-kaggle="v0\.1"/);
});

test("the checklist items are boxes that reflect the saved state, with text escaped", () => {
  const c = make();
  ready(c, { missing: [], can_build: true });
  c.relPage.releases = [release()];
  c.relPage.openChecklist = "v0.1";
  const html = c.releaseSectionHtml(VIEW);
  assert.match(html, /data-check-item="0" data-release="v0\.1" checked/);
  assert.match(html, /data-check-item="1" data-release="v0\.1" >/);
  assert.match(html, /Upload &lt;privately&gt; first/);
  assert.match(html, /before making any repository public/);
});

test("the upload form is private-only, needs a token it never asks for, and a typed confirmation", () => {
  const c = make();
  ready(c, { missing: [], can_build: true });
  c.relPage.releases = [release()];
  c.relPage.openUpload = "v0.1";
  let html = c.releaseSectionHtml(VIEW);
  assert.match(html, /<strong>private<\/strong> dataset repository/);
  assert.match(html, /This page never asks for a token/);
  assert.match(html, /Type the repository name again to confirm/);
  assert.match(html, /data-upload="v0\.1" disabled/);
  assert.doesNotMatch(html, /type="password"/);
  assert.doesNotMatch(html, /placeholder="hf_/);
  c.relPage.upload = { token_env: "HF_TOKEN", token_set: true, hub_installed: true, private_only: true };
  html = c.releaseSectionHtml(VIEW);
  assert.match(html, /found in <span class="mono-12">HF_TOKEN/);
  assert.doesNotMatch(html, /data-upload="v0\.1" disabled/);
});

test("results are shown: a verify failure lists problems, an upload names the private repository", () => {
  const c = make();
  ready(c, { missing: [], can_build: true });
  c.relPage.releases = [release()];
  c.relPage.openUpload = "v0.1";
  c.relPage.results["verify-v0.1"] = { ok: false, problems: ["images/a.jpg has changed since the release was built."] };
  c.relPage.results["upload-v0.1"] = { upload: { repo_id: "me/x", next: "Work through RELEASE-CHECKLIST.md before making the repository public." } };
  const html = c.releaseSectionHtml(VIEW);
  assert.match(html, /images\/a\.jpg has changed/);
  assert.match(html, /Uploaded to the private repository me\/x/);
  c.relPage.results["upload-v0.1"] = { error: "That repository is already public." };
  assert.match(c.releaseSectionHtml(VIEW), /That repository is already public\./);
});

test("the Datasets page loads the release section and the shell stays connected", () => {
  assert.match(read("datasets.html"), /<script src="\/console\/datasets-release\.js"><\/script>/);
  const page = read("datasets.js");
  assert.match(page, /releaseSectionHtml\(view\)/);
  assert.match(page, /wireRelease\(\)/);
  assert.match(page, /loadRelease\(\)/);
});
