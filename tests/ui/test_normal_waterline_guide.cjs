const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const standalonePanel = html.split('<section id="normalWaterlineGuideFormPanel"')[1].split("</section>")[0];
const setupForm = html.split('<section id="setupForm"')[1].split("</section>")[0];

function grabFunction(name) {
  const match = script.match(new RegExp(`      (?:async )?function ${name}\\([\\s\\S]*?\\n      \\}`));
  assert.ok(match, `${name} not found`);
  return match[0];
}

function grabBlock(name) {
  const start = script.indexOf(`      function ${name}(`);
  assert.ok(start >= 0, `${name} not found`);
  const paramsEnd = script.indexOf(")", start);
  const bodyStart = script.indexOf("{", paramsEnd);
  let depth = 0;
  for (let i = bodyStart; i < script.length; i += 1) {
    if (script[i] === "{") depth += 1;
    if (script[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        return script.slice(start, i + 1);
      }
    }
  }
  throw new Error(`Could not find end of ${name}`);
}

test("no Suggest Reference button or machine-suggestion code exists anywhere in the file", () => {
  assert.ok(!html.includes("Suggest Reference"));
  assert.ok(!script.includes("suggestReferenceRegion"));
  assert.ok(!script.includes("machine_suggested"));
});

test("the standalone form has the click-to-add-point controls and no marker or dropdown UI", () => {
  assert.ok(/Undo Last Point/.test(standalonePanel));
  assert.ok(!/Add Marker/.test(standalonePanel));
  assert.match(standalonePanel, /Clear Active Line's Points/);
  assert.ok(!/normalWaterlineGuideExistingSelect/.test(standalonePanel), "the Guide dropdown should be gone");
});

test("the Create Site setup form has no normal-waterline-guide UI at all — only the watched area", () => {
  assert.ok(!/Normal Waterline Guide/i.test(setupForm), "guide drawing should not appear in site setup");
  assert.ok(!/Undo Last Point/.test(setupForm));
  assert.ok(!/normalWaterlineGuide/i.test(setupForm));
  assert.ok(!script.includes("function createSiteSetupSelector("));
  assert.ok(!script.includes("saveNormalWaterlineGuideFromSetup"));
});

test("the standalone form has an explicit affordance to add another line", () => {
  assert.match(standalonePanel, /id="addAnotherGuideButton"/);
  assert.match(standalonePanel, /\+ Add Another Line/);
  const handler = script.match(/addAnotherGuideButton\.addEventListener\("click"[\s\S]*?\n {6}\}\);/);
  assert.ok(handler, "addAnotherGuideButton click handler not found");
  assert.ok(handler[0].includes("normalWaterlineGuideEditor.addLine()"));
});

test("the multi-line editor exposes add/undo/clear/save/delete-tracking methods", () => {
  const editor = grabBlock("createNormalWaterlineGuidesEditor");
  assert.ok(editor.includes("addLine: () =>"));
  assert.ok(editor.includes("undoLastPoint: () =>"));
  assert.ok(editor.includes("clearActiveLinePoints: () =>"));
  assert.ok(editor.includes("collectForSave: () =>"));
  assert.ok(editor.includes("markAllExistingOnServer: () =>"));
  assert.ok(editor.includes("hasRows: () => rows.length > 0"));
});

test("every line stays visible on canvas at once, active line highlighted", () => {
  const editor = grabBlock("createNormalWaterlineGuidesEditor");
  assert.match(editor, /for \(const row of rows\) \{/);
  assert.ok(editor.includes('isActive ? "#087f5b" : "#94a3b8"'), "inactive lines must still be drawn, in a muted color");
});

test("a click outside the watched-area guide is rejected before being added to the active line", () => {
  const editor = grabBlock("createNormalWaterlineGuidesEditor");
  assert.match(
    editor,
    /if \(guideRegion && !pointInsideRect\(point, guideRegion\)\) \{\s*status\.textContent = .*;\s*return;\s*\}/
  );
  assert.ok(editor.includes("active.points.push(point)"));
});

test("clicking the canvas with no active line does not add a point", () => {
  const editor = grabBlock("createNormalWaterlineGuidesEditor");
  assert.match(editor, /if \(!active\) \{\s*status\.textContent = [^;]+;\s*return;\s*\}/);
});

test("each row has its own status, invalid-reason, normal-condition, and notes fields", () => {
  const editor = grabBlock("createNormalWaterlineGuidesEditor");
  assert.ok(editor.includes('["draft", "Draft"]'));
  assert.ok(editor.includes('["confirmed", "Confirmed"]'));
  assert.ok(editor.includes('["invalid", "Invalid"]'));
  assert.ok(editor.includes("INVALIDATION_REASON_OPTIONS"));
  assert.ok(editor.includes("normalConditionCheckbox"));
  assert.ok(editor.includes("notesInput"));
});

test("each row has a delete button that hard-deletes an already-saved line via the server", () => {
  const editor = grabBlock("createNormalWaterlineGuidesEditor");
  assert.ok(editor.includes('deleteButton.textContent = "Delete"'));
  assert.ok(editor.includes("if (row.existingOnServer)"));
  assert.ok(editor.includes("onDeleteExisting(row.id)"));
  assert.ok(editor.includes("confirm("), "delete should confirm before removing a line");
});

test("a brand-new (never-saved) line's delete just removes it locally, no network call needed first", () => {
  const editor = grabBlock("createNormalWaterlineGuidesEditor");
  const deleteHandler = editor.match(/deleteButton\.addEventListener\("click"[\s\S]*?\n {10}\}\);/);
  assert.ok(deleteHandler, "delete button handler not found");
  assert.match(deleteHandler[0], /if \(row\.existingOnServer\) \{[\s\S]*?\}/);
});

test("line ids are generated once and are not derived from the label", () => {
  const editor = grabBlock("createNormalWaterlineGuidesEditor");
  assert.ok(script.includes("function generateGuideId()"));
  assert.ok(editor.includes("id: generateGuideId()"));
  assert.ok(!editor.includes("slugify"), "guide id must not be derived from the label text");
});

test("delete uses the new hard-delete route, not invalidate", () => {
  assert.ok(script.includes('"/api/delete-normal-waterline-guide"'));
  const deleteFn = grabFunction("deleteSavedNormalWaterlineGuide");
  assert.ok(deleteFn.includes('"/api/delete-normal-waterline-guide"'));
});

test("Save All persists every row in a single bulk request", () => {
  assert.ok(script.includes('"/api/set-normal-waterline-guides"'));
  const handler = script.match(/saveAllNormalWaterlineGuidesButton\.addEventListener\("click"[\s\S]*?\n {6}\}\);/);
  assert.ok(handler, "Save All click handler not found");
  assert.ok(handler[0].includes("normalWaterlineGuideEditor.collectForSave()"));
  assert.ok(handler[0].includes("guides: collected.guides"));
  assert.ok(handler[0].includes("normalWaterlineGuideEditor.markAllExistingOnServer()"));
});

test("collectForSave sends each row's own status and reason, not a single shared one", () => {
  const editor = grabBlock("createNormalWaterlineGuidesEditor");
  assert.ok(editor.includes("row.fields.status.value"));
  assert.ok(editor.includes('rowStatus === "invalid" ? row.fields.invalidationReason.value : null'));
});

test("a saved guide's points and fields round-trip into the editor via show()", () => {
  const editor = grabBlock("createNormalWaterlineGuidesEditor");
  assert.ok(editor.includes("points: (guide.points || []).slice()"));
  assert.ok(editor.includes("existingOnServer: true"));
});

test("refreshing the site list after a save does not wipe the open editor's rows", () => {
  const fillVideos = grabFunction("fillNormalWaterlineGuideVideos");
  assert.ok(
    fillVideos.includes("normalWaterlineGuideVideoSelect.value !== previousVideoId"),
    "the editor must only reset when the selected video actually changes"
  );
});

function evalPointInsideRect() {
  const source = `${grabFunction("pointInsideRect")}\npointInsideRect;`;
  return vm.runInNewContext(source, {});
}

test("pointInsideRect algorithmic behavior", () => {
  const pointInsideRect = evalPointInsideRect();
  const rect = { x: 10, y: 10, width: 20, height: 20 };

  assert.equal(pointInsideRect({ x: 15, y: 15 }, rect), true);
  assert.equal(pointInsideRect({ x: 10, y: 10 }, rect), true, "inclusive of the top-left edge");
  assert.equal(pointInsideRect({ x: 30, y: 30 }, rect), true, "inclusive of the bottom-right edge");
  assert.equal(pointInsideRect({ x: 5, y: 15 }, rect), false);
  assert.equal(pointInsideRect({ x: 15, y: 31 }, rect), false);
});
