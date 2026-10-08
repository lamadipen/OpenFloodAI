const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const html = fs.readFileSync(path.join(__dirname, "../../tools/console/form-create-site.html"), "utf8");
const style = (html.match(/<style>([\s\S]*?)<\/style>/) || [])[1] || "";

test("every text field, the file picker and the notes box fill the form width", () => {
  assert.match(style, /#form input,\s*#form textarea\s*\{[^}]*width:\s*100%/);
});

test("the form still has the fields that rule is meant to stretch", () => {
  for (const id of ["video_file", "folder_name", "camera_id", "site_name", "public_location", "privacy_notes"]) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
});

test("the notes box can only be resized vertically so it cannot break the layout", () => {
  assert.match(style, /#form textarea\s*\{[^}]*resize:\s*vertical/);
});
