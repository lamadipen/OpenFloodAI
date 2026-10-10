// Datasets page: curate versioned local training datasets from reviewed observations (Issue #215).
//
// A dataset is a local, reviewed selection of examples for one task. Freezing makes an immutable
// version that a later export step can read. Nothing here trains a model, uploads or publishes.

const TASKS = [
  { id: "water_segmentation", title: "Water segmentation", help: "Image plus a water mask that a person accepted." },
  { id: "level_classification", title: "Low / middle / high classification", help: "Image, a human review, its own gauge reading and an approved category definition for the site." },
  { id: "gauge_height", title: "Gauge-height estimation", help: "Image plus its own matched gauge reading. No low image is needed." },
  { id: "level_change", title: "Rising / falling (height change)", help: "An earlier and a later image you pair yourself, each with a gauge reading." },
  { id: "visual_change", title: "Visible water change (human-judged pair)", help: "An earlier and a later image you pair yourself, plus what a reviewer saw between them. One judgment is enough to add a pair; it is stored as awaiting review inside the dataset. Judgments made after seeing machine evidence count too and are marked as informed. Add pairs from the focused or assisted review page." }
];

const dsPage = { datasets: [], view: null, id: qs("dataset_id"), message: "" };

function taskTitle(id) {
  return (TASKS.find((t) => t.id === id) || {}).title || id;
}

async function post(path, body) {
  const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.message || "Could not save.");
    error.data = data;
    throw error;
  }
  return data;
}

async function main() {
  const content = mountShell({
    active: "datasets",
    crumbs: [{ label: "Datasets", href: "/console/datasets.html" }]
  });
  content.innerHTML = `<div class="card card-pad muted-12">Loading datasets&hellip;</div>`;
  await refresh();
}

async function refresh() {
  try {
    dsPage.datasets = (await api("/api/datasets")).datasets || [];
    dsPage.view = dsPage.id ? await api(`/api/dataset?${new URLSearchParams({ dataset_id: dsPage.id })}`) : null;
    if (dsPage.view && typeof loadRelease === "function") await loadRelease();
  } catch (error) {
    dsPage.view = null;
    dsPage.message = error.message;
  }
  render();
}

function render() {
  keepFocus($("content"), renderNow);
}

function renderNow() {
  const content = $("content");
  content.innerHTML = `
    ${dsPage.message ? `<div class="card card-pad" style="color:var(--bad);font-size:13px;">${escapeHtml(dsPage.message)}</div>` : ""}
    <div style="display:grid;grid-template-columns:300px minmax(0,1fr);gap:16px;align-items:start;" class="review-grid">
      <div style="display:flex;flex-direction:column;gap:12px;">${listHtml()}${createFormHtml()}</div>
      <div style="display:flex;flex-direction:column;gap:16px;min-width:0;">${dsPage.view ? detailHtml(dsPage.view) : emptyHtml()}</div>
    </div>`;
  wire();
}

function emptyHtml() {
  return `<div class="card card-pad">
    <div class="title-m">Curate training datasets</div>
    <p class="soft-12" style="max-width:60ch;line-height:1.6;">Pick reviewed images from your saved runs and keep them as examples for one task.
    You add images from a run's review page with <strong>Add to dataset</strong>. Each dataset checks that an image has the evidence its task needs, keeps the original image and its evidence, and can be frozen into a version that never changes.
    Nothing here trains a model, uploads, or publishes.</p>
    <p class="muted-12">Choose a dataset on the left, or create one.</p></div>`;
}

function listHtml() {
  const rows = dsPage.datasets
    .map((d) => `<a href="/console/datasets.html?${new URLSearchParams({ dataset_id: d.dataset_id })}" style="display:block;padding:10px 14px;border-bottom:1px solid var(--line-soft);${d.dataset_id === dsPage.id ? "background:var(--accent-soft);" : ""}">
      <div class="title-s">${escapeHtml(d.name)}</div>
      <div class="muted-12">${escapeHtml(d.task_title)}</div>
      <div class="muted-12">${d.included} example${d.included === 1 ? "" : "s"}${d.rejected ? ` · ${d.rejected} rejected` : ""} · ${d.versions} version${d.versions === 1 ? "" : "s"}</div></a>`)
    .join("");
  return `<div class="card" style="overflow:hidden;"><div class="card-pad-sm title-s" style="border-bottom:1px solid var(--line-soft);">Datasets (${dsPage.datasets.length})</div>${rows || `<div class="empty-note">No datasets yet.</div>`}</div>`;
}

function createFormHtml() {
  return `<form class="card card-pad" id="createForm">
    <div class="title-s mb-8">New dataset</div>
    <label for="dsName">Name</label><input id="dsName" class="full-width" maxlength="80" required>
    <label class="mt-10" for="dsTask">What should the model learn?</label>
    <select id="dsTask" class="full-width">${TASKS.map((t) => `<option value="${t.id}">${escapeHtml(t.title)}</option>`).join("")}</select>
    <div class="hint" id="dsTaskHelp">${escapeHtml(TASKS[0].help)}</div>
    <p class="hint">Each dataset has one learning task, not one water condition. For example, a water-segmentation dataset can contain low, middle and high water images together.</p>
    <details class="mt-10">
      <summary class="soft-12">Understand the task choices</summary>
      <dl class="soft-12" style="line-height:1.6;overflow-wrap:anywhere;">
        <dt><strong>Water segmentation</strong></dt><dd>Where is the water? Keep an image with a water mask approved by a person.</dd>
        <dt><strong>Low / middle / high classification</strong></dt><dd>Which water-level category fits? Use reviewed images, matched gauge readings and approved definitions for that site.</dd>
        <dt><strong>Gauge-height estimation</strong></dt><dd>What gauge reading corresponds to this image? Keep the image and its matched reading.</dd>
        <dt><strong>Rising / falling (height change)</strong></dt><dd>Did gauge height change? Compare two images using their matched gauge readings.</dd>
        <dt><strong>Visible water change</strong></dt><dd>Does water visibly cover more or less area? Keep two images and independent human judgments.</dd>
      </dl>
      <p class="hint">The same image can belong to different datasets when it has the evidence each task needs. For example, May 1 can have an approved water mask in one dataset and be paired with April 1 for visible-change review in another. Supporting timestamps, site information and available gauge context stay with the examples.</p>
      <p class="hint">You do not need to create every dataset type. Creating a dataset does not train a model.</p>
    </details>
    <div id="toleranceRow" hidden><label class="mt-10" for="dsTolerance">No-change tolerance (optional)</label>
      <input id="dsTolerance" class="full-width" type="number" min="0" step="any" placeholder="Leave empty for a numeric change only">
      <div class="hint">In the gauge's unit. Without it, pairs get a numeric change but no rising / falling label.</div></div>
    <button class="btn primary mt-10 full-width" style="justify-content:center;">Create dataset</button>
    <div class="err" id="createError" hidden></div>
  </form>`;
}

function reasonList(items, kind) {
  if (!items.length) return "";
  const color = kind === "error" ? "var(--bad)" : "var(--warn)";
  return `<ul style="margin:6px 0 0 18px;padding:0;font-size:12px;color:${color};">${items.map((r) => `<li>${escapeHtml(r.message)}${r.member_id ? ` <span class="mono-12">(${escapeHtml(r.member_id.slice(0, 14))})</span>` : ""}</li>`).join("")}</ul>`;
}

function detailHtml(view) {
  const ds = view.dataset;
  const counts = view.label_counts;
  const included = view.members.filter((m) => m.status === "included").length;
  return `
    <div class="card card-pad">
      <div class="title-m">${escapeHtml(ds.name)}</div>
      <div class="soft-12">${escapeHtml(ds.task_title)} · ${included} example${included === 1 ? "" : "s"} · ${view.versions.length} frozen version${view.versions.length === 1 ? "" : "s"}</div>
      <div class="mt-10 pill ${view.ready_to_freeze ? "ok" : "warn"}">${view.ready_to_freeze ? "Ready to freeze" : "Not ready to freeze"}</div>
      ${reasonList(view.blocking, "error")}
      ${view.readiness_gaps.length ? `<div class="soft-12 mt-10" style="font-weight:600;">Readiness gaps</div>${reasonList(view.readiness_gaps, "warning")}` : ""}
    </div>
    ${countsHtml(ds, counts)}
    ${splitHtml(view)}
    ${ds.task === "level_classification" ? definitionsHtml(view) : ""}
    ${membersHtml(view)}
    ${view.duplicates.length ? duplicatesHtml(view) : ""}
    ${versionsHtml(view)}
    ${typeof releaseSectionHtml === "function" ? releaseSectionHtml(view) : ""}`;
}

function countsHtml(ds, c) {
  const table = (obj) => Object.entries(obj || {}).map(([k, v]) => `<span class="pill gray" style="margin:2px;">${escapeHtml(k.replace(/_/g, " "))}: ${v}</span>`).join("") || `<span class="muted-12">none yet</span>`;
  return `<div class="card card-pad"><div class="title-s mb-8">What the dataset contains</div>
    <div class="soft-12"><strong>${c.examples}</strong> example${c.examples === 1 ? "" : "s"} from ${c.cameras.length} camera${c.cameras.length === 1 ? "" : "s"}${c.cameras.length ? ` (${c.cameras.map(escapeHtml).join(", ")})` : ""}</div>
    ${c.by_category ? `<div class="mt-6">Categories ${table(c.by_category)}</div>` : ""}
    ${c.by_direction ? `<div class="mt-6">Direction ${table(c.by_direction)}</div>` : ""}
    ${c.gauge_range ? `<div class="mt-6">Gauge range ${c.gauge_range.min}–${c.gauge_range.max} ${escapeHtml(c.gauge_range.unit)}</div>` : ""}
    ${c.masks !== undefined ? `<div class="mt-6">Mask files: ${c.masks}</div>` : ""}
    <div class="mt-6">Human labels ${table(c.by_human_label)}</div>
    <div class="mt-6">Splits ${table(c.by_split)}</div></div>`;
}

function splitHtml(view) {
  const ds = view.dataset;
  const policy = ds.split_policy;
  const cameras = view.label_counts.cameras;
  const kind = policy.kind;
  const camRows = cameras.map((cam) => `<div class="inline-row mt-6"><span class="mono-12" style="min-width:200px;overflow-wrap:anywhere;">${escapeHtml(cam)}</span>
    <select data-camera="${escapeHtml(cam)}">${["", "train", "validation", "test"].map((s) => `<option value="${s}" ${((policy.assignments || {})[cam] || "") === s ? "selected" : ""}>${s || "not assigned"}</option>`).join("")}</select></div>`).join("");
  const blocks = (policy.blocks || []).map((b, i) => `<div class="inline-row mt-6" data-block="${i}"><input type="date" data-field="start_date" value="${escapeHtml(b.start_date)}"> to <input type="date" data-field="end_date" value="${escapeHtml(b.end_date)}">
    <select data-field="split">${["train", "validation", "test"].map((s) => `<option ${b.split === s ? "selected" : ""}>${s}</option>`).join("")}</select></div>`).join("");
  return `<div class="card card-pad"><div class="title-s">Train, validation and test split</div>
    <div class="hint mb-8">Neighbouring frames are never split at random. Each camera belongs to exactly one split. Locked-validation data can only be in test.</div>
    <label><input type="radio" name="policyKind" value="site_camera" ${kind === "site_camera" ? "checked" : ""}> By camera (recommended)</label>
    <div id="cameraPolicy" ${kind === "site_camera" ? "" : "hidden"}>${camRows || `<div class="muted-12 mt-6">Add examples to assign their cameras.</div>`}</div>
    <label class="mt-10"><input type="radio" name="policyKind" value="single_site_time_block" ${kind === "single_site_time_block" ? "checked" : ""}> By time blocks within one site (site-specific evaluation only)</label>
    <div id="blockPolicy" ${kind === "single_site_time_block" ? "" : "hidden"}>
      <div class="hint">This says nothing about unseen cameras and does not meet the publication rule.</div>
      <input id="blockSite" class="full-width mt-6" placeholder="Site id" value="${escapeHtml(policy.site_id || (view.members[0] ? "" : ""))}">${blocks}
      <button class="btn mt-6" type="button" id="addBlock">+ Add block</button></div>
    <div class="mt-10"><button class="btn primary" id="saveSplit">Save split policy</button></div><div class="err" id="splitError" hidden></div></div>`;
}

function definitionsHtml(view) {
  const ds = view.dataset;
  const pinned = Object.entries(ds.label_definitions).map(([site, v]) => `<div class="soft-12 mt-4"><span class="mono-12">${escapeHtml(site)}</span> uses definition version <strong>${v}</strong></div>`).join("");
  return `<div class="card card-pad"><div class="title-s">Category definitions</div>
    <div class="hint mb-8">Low, middle and high only exist where a person records approved numeric bands for one gauge station, with a unit and a source. They are local categories, not flood thresholds. A change is a new version and never recategorizes old records.</div>
    ${pinned || `<div class="muted-12">No definition chosen yet.</div>`}
    <div class="mt-10 inline-row"><input id="defSite" placeholder="Site id" style="flex:1;"><button class="btn" id="loadDefs" type="button">Show versions</button></div>
    <div id="defVersions"></div>
    <details class="mt-10"><summary class="title-s">Create a new definition</summary>
      <label class="mt-6" for="defUnit">Unit</label><input id="defUnit" class="full-width" value="ft">
      <label class="mt-6" for="defStation">Gauge station (USGS site number)</label><input id="defStation" class="full-width">
      <label class="mt-6" for="defBoundary">A value exactly on a boundary belongs to</label>
      <select id="defBoundary" class="full-width"><option value="upper_inclusive">the band below it</option><option value="lower_inclusive">the band above it</option></select>
      <div class="hint mt-6">Bands meet at shared boundaries. Leave the first lower limit and last upper limit empty.</div>
      ${["low", "middle", "high"].map((n) => `<div class="inline-row mt-6" data-band="${n}"><span style="width:60px;">${n}</span><input type="number" step="any" data-limit="lower" placeholder="from"><input type="number" step="any" data-limit="upper" placeholder="up to"></div>`).join("")}
      <label class="mt-6" for="defWhy">Source or rationale</label><input id="defWhy" class="full-width">
      <label class="mt-6" for="defAuthor">Author</label><input id="defAuthor" class="full-width">
      <label class="mt-6" for="defApprover">Approved by</label><input id="defApprover" class="full-width">
      <button class="btn primary mt-10" id="saveDef" type="button">Save definition</button><div class="err" id="defError" hidden></div></details></div>`;
}

function annotationText(a) {
  if (!a) return "";
  if (a.kind === "level_category") return `${a.category} · ${a.gauge_value} ${a.unit}`;
  if (a.kind === "gauge_height") return `${a.value} ${a.unit}`;
  if (a.kind === "water_mask") return `${a.masks.length} mask file(s)`;
  if (a.kind === "level_change") return `${a.delta} ${a.unit}${a.direction ? ` · ${a.direction}` : ""}`;
  if (a.kind === "visual_change") return `${String(a.direction || "").replaceAll("_", " ")} · ${a.reviewer_count} reviewers agree`;
  return "";
}

function membersHtml(view) {
  const rows = view.members.map((m) => {
    const o = m.observation;
    const status = m.status === "rejected" ? `<span class="pill gray">Rejected</span>` : m.problems.length ? `<span class="pill bad">Needs attention</span>` : `<span class="pill ok">Included</span>`;
    const notes = [...m.problems.map((p) => ({ ...p, severity: "error" })), ...m.warnings];
    return `<tr><td><div class="mono-12" style="overflow-wrap:anywhere;">${escapeHtml(o.filename)}${o.later_filename ? ` → ${escapeHtml(o.later_filename)}` : ""}</div>
      <div class="muted-12">${escapeHtml(o.site)} · ${escapeHtml(o.camera_id)} · ${escapeHtml(String(o.captured_at_utc).slice(0, 16).replace("T", " "))} UTC</div>
      <div class="muted-12">${m.runs.length} run${m.runs.length === 1 ? "" : "s"}</div></td>
      <td>${escapeHtml(annotationText(m.annotation))}${m.rejection_note ? `<div class="muted-12">${escapeHtml(m.rejection_note)}</div>` : ""}</td>
      <td>${m.split ? escapeHtml(m.split) : `<span class="muted-12">none</span>`}</td>
      <td>${status}${reasonList(notes, m.problems.length ? "error" : "warning")}</td>
      <td style="text-align:right;"><button class="btn" data-remove="${escapeHtml(m.member_id)}" style="height:28px;">Remove</button></td></tr>`;
  }).join("");
  return `<div class="card" style="overflow:hidden;"><div class="card-pad-sm title-s" style="border-bottom:1px solid var(--line-soft);">Examples (${view.members.length})</div>
    <div class="hint" style="padding:0 18px;">Removing only takes an example out of the draft. The image, the run and frozen versions are untouched.</div>
    <table><thead><tr><th>Image</th><th>Annotation</th><th>Split</th><th>Status</th><th></th></tr></thead><tbody>${rows || `<tr><td colspan="5" class="empty-note">Nothing yet. Add images from a run's review page.</td></tr>`}</tbody></table></div>`;
}

function duplicatesHtml(view) {
  return `<div class="card card-pad"><div class="title-s">Possible duplicates</div>
    <div class="hint mb-8">The same picture content appears under different observations. Identical content must not sit in two splits.</div>
    ${view.duplicates.map((d) => `<div class="mono-12 mt-4" style="overflow-wrap:anywhere;">${d.members.map(escapeHtml).join(" = ")}</div>`).join("")}</div>`;
}

function versionsHtml(view) {
  const versions = view.versions.map((v) => `<tr><td>v${v.version}</td><td>${escapeHtml(String(v.frozen_at_utc).slice(0, 16).replace("T", " "))} UTC</td><td>${v.examples}</td><td>${escapeHtml(v.note || "")}</td>
    <td><button class="btn" data-verify="${v.version}" style="height:28px;">Verify</button> <span data-verified="${v.version}" class="muted-12"></span></td></tr>`).join("");
  return `<div class="card card-pad"><div class="title-s">Frozen versions</div>
    <div class="hint mb-8">A frozen version keeps the original images, masks, evidence, labels, split and checksums. It never changes. Editing the draft and freezing again makes the next version. This is a local handoff for a later export; nothing is uploaded.</div>
    ${versions ? `<table><thead><tr><th>Version</th><th>Frozen</th><th>Examples</th><th>Note</th><th></th></tr></thead><tbody>${versions}</tbody></table>` : `<div class="muted-12">No versions yet.</div>`}
    <div class="mt-10 title-s">Freeze a new version</div>
    <label class="mt-6" for="freezeNote">Version note</label><input id="freezeNote" class="full-width" maxlength="300" placeholder="What changed since the last version?">
    <label class="mt-6" for="freezeBy">Your name</label><input id="freezeBy" class="full-width" maxlength="80">
    <button class="btn primary mt-10" id="freezeBtn" ${view.ready_to_freeze ? "" : "disabled"}>Freeze version</button><div class="err" id="freezeError" hidden></div></div>`;
}

function showError(id, error) {
  const el = $(id);
  if (!el) return;
  el.hidden = false;
  const blocking = error.data && error.data.blocking ? error.data.blocking.map((b) => b.message).join(" ") : "";
  el.textContent = blocking || error.message;
}

function wire() {
  const form = $("createForm");
  const task = $("dsTask");
  task.addEventListener("change", () => {
    $("dsTaskHelp").textContent = (TASKS.find((t) => t.id === task.value) || {}).help || "";
    $("toleranceRow").hidden = task.value !== "level_change";
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const body = { name: $("dsName").value, task: task.value };
      if (task.value === "level_change" && $("dsTolerance").value !== "") body.change_tolerance = Number($("dsTolerance").value);
      const made = await post("/api/dataset-create", body);
      location.href = `/console/datasets.html?${new URLSearchParams({ dataset_id: made.dataset.dataset_id })}`;
    } catch (error) {
      showError("createError", error);
    }
  });
  document.querySelectorAll("[data-remove]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      try {
        await post("/api/dataset-remove", { dataset_id: dsPage.id, member_id: btn.dataset.remove });
        await refresh();
      } catch (error) {
        dsPage.message = error.message;
        render();
      }
    })
  );
  document.querySelectorAll("[data-verify]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const result = await api(`/api/dataset-verify?${new URLSearchParams({ dataset_id: dsPage.id, version: btn.dataset.verify })}`);
      document.querySelector(`[data-verified="${btn.dataset.verify}"]`).textContent = result.ok ? "Checksums match." : result.problems.join(" ");
    })
  );
  if (!dsPage.view) return;
  wireSplit();
  if (typeof wireRelease === "function") wireRelease();
  const freeze = $("freezeBtn");
  if (freeze) freeze.addEventListener("click", async () => {
    try {
      await post("/api/dataset-freeze", { dataset_id: dsPage.id, note: $("freezeNote").value, approved_by: $("freezeBy").value });
      await refresh();
    } catch (error) {
      showError("freezeError", error);
    }
  });
  if (dsPage.view.dataset.task === "level_classification") wireDefinitions();
}

function wireSplit() {
  document.querySelectorAll('input[name="policyKind"]').forEach((radio) =>
    radio.addEventListener("change", () => {
      $("cameraPolicy").hidden = radio.value !== "site_camera" || !radio.checked;
      $("blockPolicy").hidden = radio.value !== "single_site_time_block" || !radio.checked;
    })
  );
  const add = $("addBlock");
  if (add) add.addEventListener("click", () => {
    const row = document.createElement("div");
    row.className = "inline-row mt-6";
    row.dataset.block = String(document.querySelectorAll("[data-block]").length);
    row.innerHTML = `<input type="date" data-field="start_date"> to <input type="date" data-field="end_date"><select data-field="split"><option>train</option><option>validation</option><option>test</option></select>`;
    add.before(row);
  });
  $("saveSplit").addEventListener("click", async () => {
    const kind = document.querySelector('input[name="policyKind"]:checked').value;
    let policy;
    if (kind === "site_camera") {
      const assignments = {};
      document.querySelectorAll("[data-camera]").forEach((s) => { if (s.value) assignments[s.dataset.camera] = s.value; });
      policy = { kind, assignments };
    } else {
      const blocks = Array.from(document.querySelectorAll("[data-block]")).map((row) => ({
        split: row.querySelector('[data-field="split"]').value,
        start_date: row.querySelector('[data-field="start_date"]').value,
        end_date: row.querySelector('[data-field="end_date"]').value
      }));
      policy = { kind, site_id: $("blockSite").value, blocks };
    }
    try {
      await post("/api/dataset-split-policy", { dataset_id: dsPage.id, policy });
      await refresh();
    } catch (error) {
      showError("splitError", error);
    }
  });
}

function wireDefinitions() {
  $("loadDefs").addEventListener("click", async () => {
    const site = $("defSite").value.trim();
    if (!site) return;
    const data = await api(`/api/dataset-label-definitions?${new URLSearchParams({ site_id: site })}`);
    $("defVersions").innerHTML = (data.definitions || []).map((d) => `<div class="inline-row mt-6"><span class="soft-12">Version ${d.version}: ${d.bands.map((b) => `${b.name} ${b.lower ?? "…"}–${b.upper ?? "…"}`).join(", ")} ${escapeHtml(d.unit)} · station ${escapeHtml(d.station_nwis_id)} · approved by ${escapeHtml(d.approved_by)}</span>
      <button class="btn" data-pin="${d.version}" style="height:28px;">Use for this dataset</button></div>`).join("") || `<div class="muted-12 mt-6">No definitions for that site yet.</div>`;
    document.querySelectorAll("[data-pin]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await post("/api/dataset-pin-definition", { dataset_id: dsPage.id, site_id: site, version: Number(btn.dataset.pin) });
          await refresh();
        } catch (error) {
          showError("defError", error);
        }
      })
    );
  });
  $("saveDef").addEventListener("click", async () => {
    const bands = Array.from(document.querySelectorAll("[data-band]")).map((row) => {
      const num = (name) => { const v = row.querySelector(`[data-limit="${name}"]`).value; return v === "" ? null : Number(v); };
      return { name: row.dataset.band, lower: num("lower"), upper: num("upper") };
    });
    try {
      const made = await post("/api/dataset-create-definition", {
        site_id: $("defSite").value, unit: $("defUnit").value, station_nwis_id: $("defStation").value,
        boundary: $("defBoundary").value, bands, rationale: $("defWhy").value,
        author: $("defAuthor").value, approved_by: $("defApprover").value
      });
      $("defError").hidden = false;
      $("defError").style.color = "var(--ok)";
      $("defError").textContent = `Saved as version ${made.definition.version}. Choose it with "Show versions".`;
    } catch (error) {
      showError("defError", error);
    }
  });
}
