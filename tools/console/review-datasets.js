// Review page: add the selected image to a local training dataset (Issue #215).
//
// This only keeps a reviewed example for later curation. Nothing is trained, uploaded or
// published, and the run, its gauge match and its human review are never changed.

// Tasks whose example is a pair of images the reviewer chooses.
const PAIR_DATASET_TASKS = ["level_change", "visual_change"];

const DATASET_TASK_HELP = {
  water_segmentation: "Needs a water mask (not a riverbank mask) for this exact image that a person accepted in the hosted segmentation panel below.",
  level_classification: "Needs a human review of this image, its own matched gauge reading, and an approved category definition for this site.",
  gauge_height: "Needs this image's own matched gauge reading with unit, station and quality. It does not need a low image.",
  level_change: "Needs an earlier and a later image from the same camera view, each with a gauge reading. Choose both yourself; pairs are never made automatically.",
  visual_change: "Needs an earlier and a later image from the same camera view, and at least one reviewer's judgment of what changed (blind or informed; informed ones are marked). Other reviewers confirm it later, inside the dataset. Choose both yourself; the focused review page shows whether reviewers agree before you add."
};

let dsState = { datasets: [], selectedId: "", result: null, busy: false, pairEarlier: null, pendingReject: false };

async function loadDatasets() {
  try {
    dsState.datasets = (await api("/api/datasets")).datasets || [];
  } catch (error) {
    dsState.datasets = [];
  }
  const remembered = (() => { try { return localStorage.getItem("openfloodai.reviewDataset") || ""; } catch (e) { return ""; } })();
  if (!dsState.datasets.some((d) => d.dataset_id === dsState.selectedId)) {
    dsState.selectedId = dsState.datasets.some((d) => d.dataset_id === remembered) ? remembered : (dsState.datasets[0] || {}).dataset_id || "";
  }
}

function chosenDataset() {
  return dsState.datasets.find((d) => d.dataset_id === dsState.selectedId) || null;
}

function datasetImageRef(day) {
  return { folder_name: folderName, run_id: runId, filename: day.filename };
}

function reasonsHtml(reasons) {
  return (reasons || [])
    .map((r) => `<li style="color:${r.severity === "error" ? "var(--bad)" : "var(--warn)"};">${escapeHtml(r.message)}</li>`)
    .join("");
}

function annotationSummary(a) {
  if (!a) return "";
  if (a.kind === "level_category") return `${a.category} (${a.gauge_value} ${a.unit}, definition v${a.definition.version})`;
  if (a.kind === "gauge_height") return `${a.value} ${a.unit} at station ${a.station_nwis_id}`;
  if (a.kind === "water_mask") return `${a.masks.length} accepted mask file(s) for "${a.prompt}"`;
  if (a.kind === "level_change") return `change ${a.delta} ${a.unit} over ${Math.round(a.elapsed_seconds / 3600)} h${a.direction ? ` (${a.direction})` : ""}`;
  if (a.kind === "visual_change") return `${String(a.direction || "").replaceAll("_", " ")} over ${Math.round(a.elapsed_seconds / 3600)} h, ${a.reviewer_count} independent reviewers agree`;
  return "";
}

// Only a completed, accepted WATER mask can be a water-segmentation example, so only those are offered.
const WATER_MASK_PROMPTS = ["river water", "water"];

function acceptedMaskChoices(day) {
  return (samState.results || []).filter(
    (r) => r.filename === day.filename && r.status === "completed" && r.review_status === "accepted" && WATER_MASK_PROMPTS.includes(r.prompt)
  );
}

function datasetResultHtml() {
  const r = dsState.result;
  if (!r) return "";
  if (r.conflict) {
    return `<div class="mt-10" style="font-size:12px;">
      <div style="font-weight:600;color:var(--warn);">Already in this dataset with a different annotation</div>
      <div class="mt-4">In the dataset: <strong>${escapeHtml(annotationSummary(r.existing))}</strong></div>
      <div>From this run: <strong>${escapeHtml(annotationSummary(r.new))}</strong></div>
      <div class="inline-row mt-6">
        <button class="btn" data-ds-decision="replace">Replace</button>
        <button class="btn" data-ds-decision="keep">Keep existing</button>
      </div></div>`;
  }
  if (r.error) return `<div class="err mt-10">${escapeHtml(r.error)}</div>`;
  const heading = {
    added: ["Added to the dataset draft.", "var(--ok)"],
    unchanged: ["Already in the dataset with the same annotation. Nothing changed.", "var(--ink-soft)"],
    replaced: ["Replaced the earlier annotation.", "var(--ok)"],
    kept: ["Kept the existing annotation.", "var(--ink-soft)"],
    rejected: ["Rejected for this dataset. It stays listed as rejected.", "var(--ink-soft)"],
    ineligible: ["Not added. This image does not meet the task's evidence rules:", "var(--bad)"]
  }[r.status] || ["", "inherit"];
  const summary = r.annotation ? `<div class="mt-4">Annotation: <strong>${escapeHtml(annotationSummary(r.annotation))}</strong></div>` : "";
  const list = (r.reasons || []).length ? `<ul style="margin:6px 0 0 18px;padding:0;">${reasonsHtml(r.reasons)}</ul>` : "";
  return `<div class="mt-10" style="font-size:12px;"><div style="font-weight:600;color:${heading[1]};">${heading[0]}</div>${summary}${list}</div>`;
}

function datasetPanelHtml(sel) {
  if (!sel || !sel.filename || sel.code === "M") {
    return `<div class="title-s mb-8">Add to dataset</div><div class="hint">This day has no saved image to add.</div>`;
  }
  const options = dsState.datasets
    .map((d) => `<option value="${escapeHtml(d.dataset_id)}" ${d.dataset_id === dsState.selectedId ? "selected" : ""}>${escapeHtml(d.name)} · ${escapeHtml(d.task_title)} (${d.included})</option>`)
    .join("");
  const ds = chosenDataset();
  let body;
  if (!dsState.datasets.length) {
    body = `<div class="hint">No datasets yet. <a href="/console/datasets.html" style="color:var(--accent);font-weight:600;">Create one</a> to start keeping examples.</div>`;
  } else {
    const masks = ds && ds.task === "water_segmentation" ? acceptedMaskChoices(sel) : [];
    const maskPicker = masks.length > 1
      ? `<label class="mt-10" for="dsMask">Which accepted mask</label><select id="dsMask" class="full-width">${masks.map((m) => `<option value="${escapeHtml(m.run_id)}|${escapeHtml(m.result_id)}">${escapeHtml(m.prompt)} · ${escapeHtml(formatUtc(m.processed_at_utc))}</option>`).join("")}</select>`
      : "";
    const pair = ds && PAIR_DATASET_TASKS.includes(ds.task)
      ? `<div class="mt-10" style="font-size:12px;">${dsState.pairEarlier ? `Earlier image: <strong>${escapeHtml(dsState.pairEarlier.filename)}</strong> <button class="btn" data-ds-act="clear-earlier" style="height:26px;">Clear</button>` : "No earlier image chosen yet."}</div>
         <div class="inline-row mt-6"><button class="btn" data-ds-act="set-earlier">Use as earlier</button><button class="btn primary" data-ds-act="add-pair" ${dsState.pairEarlier ? "" : "disabled"}>Add pair with this as later</button></div>`
      : `<div class="inline-row mt-10"><button class="btn primary" data-ds-act="add" ${dsState.busy ? "disabled" : ""}>Add this image</button><button class="btn" data-ds-act="reject">Reject</button></div>
         ${dsState.pendingReject ? `<label class="mt-6" for="dsRejectNote">Why reject it for this dataset?</label><input id="dsRejectNote" class="full-width" maxlength="300"><button class="btn mt-6" data-ds-act="confirm-reject">Save rejection</button>` : ""}`;
    body = `<label for="dsSelect">Dataset</label><select id="dsSelect" class="full-width">${options}</select>
      <div class="hint">${escapeHtml(DATASET_TASK_HELP[(ds || {}).task] || "")}</div>${maskPicker}${pair}${datasetResultHtml()}
      <div class="mt-10" style="font-size:12px;">${ds ? `<a href="/console/datasets.html?${new URLSearchParams({ dataset_id: ds.dataset_id })}" style="color:var(--accent);font-weight:600;">Open this dataset</a>` : ""}</div>`;
  }
  return `<div class="title-s">Add to dataset</div>
    <div class="hint mb-8">Keep this image as a training example. Nothing is trained, uploaded or published.</div>${body}`;
}

async function postDataset(path, body) {
  dsState.busy = true;
  try {
    const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json();
    if (res.status === 409 && data.conflict) return { conflict: true, ...data };
    if (!res.ok) return { error: data.message || "Could not save." };
    return data;
  } catch (error) {
    return { error: error.message };
  } finally {
    dsState.busy = false;
  }
}

async function datasetAction(action, decision) {
  const sel = days[state.selectedIndex];
  const ds = chosenDataset();
  if (!sel || !ds) return;
  const maskSelect = $("dsMask");
  const base = { dataset_id: ds.dataset_id, ...datasetImageRef(sel) };
  if (maskSelect) {
    // A result id repeats across segmentation runs, so the choice names the run as well.
    const [maskRun, maskResult] = maskSelect.value.split("|");
    base.mask_run_id = maskRun;
    base.mask_result_id = maskResult;
  }
  if (decision) base.decision = decision;
  if (action === "add") dsState.result = await postDataset("/api/dataset-add", base);
  else if (action === "confirm-reject") {
    dsState.result = await postDataset("/api/dataset-reject", { ...base, note: ($("dsRejectNote") || {}).value || "" });
    dsState.pendingReject = false;
  } else if (action === "add-pair") {
    dsState.result = await postDataset("/api/dataset-add-pair", { dataset_id: ds.dataset_id, earlier: dsState.pairEarlier, later: datasetImageRef(sel), decision });
  }
  await loadDatasets();
  renderDatasetPanel();
}

function renderDatasetPanel() {
  const el = $("datasetPanel");
  if (!el) return;
  el.innerHTML = datasetPanelHtml(days[state.selectedIndex]);
  const select = $("dsSelect");
  if (select) {
    select.addEventListener("change", () => {
      dsState.selectedId = select.value;
      dsState.result = null;
      dsState.pairEarlier = null;
      try { localStorage.setItem("openfloodai.reviewDataset", dsState.selectedId); } catch (error) { /* a convenience only */ }
      renderDatasetPanel();
    });
  }
  el.querySelectorAll("[data-ds-act]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const act = btn.dataset.dsAct;
      if (act === "reject") { dsState.pendingReject = true; renderDatasetPanel(); }
      else if (act === "set-earlier") { dsState.pairEarlier = datasetImageRef(days[state.selectedIndex]); dsState.result = null; renderDatasetPanel(); }
      else if (act === "clear-earlier") { dsState.pairEarlier = null; renderDatasetPanel(); }
      else datasetAction(act);
    })
  );
  el.querySelectorAll("[data-ds-decision]").forEach((btn) =>
    btn.addEventListener("click", () => datasetAction(PAIR_DATASET_TASKS.includes(chosenDataset().task) ? "add-pair" : "add", btn.dataset.dsDecision))
  );
}
