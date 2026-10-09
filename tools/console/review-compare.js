// Review page: compare the selected image with ANY other saved image of the same camera (#223).
// It reuses the existing side-by-side and overlay views and their switch; this file only picks the
// second image, asks the server to measure the pair and shows the result. Viewing changes nothing:
// no label, baseline, dataset or saved run is written, and no segmentation or upload is started.

// ---- compare any two images ------------------------------------------------
const CMP_MASK_TEXT = {
  accepted: ["Accepted mask", "ok"],
  unreviewed: ["Mask not reviewed", "gray"],
  rejected: ["Mask rejected", "warn"],
  needs_correction: ["Mask needs correction", "warn"],
  no_match: ["SAM found no water", "gray"],
  none: ["No mask", "gray"]
};

// Plain-language reasons for a missing number. The images stay viewable in every case.
const CMP_REASON_TEXT = {
  FRAMING_NOT_CONFIRMED: "Confirm below that the camera view did not move between these two images. The software does not align cameras, and the same camera name is not proof the view stayed put.",
  MASK_MISSING: "has no water mask. Segmentation is not started from here; use the Segmentation panel or the mask option beside Run validation.",
  MASK_UNREVIEWED: "has a water mask that nobody has accepted yet.",
  MASK_REJECTED: "has a water mask that a reviewer rejected.",
  MASK_NEEDS_CORRECTION: "has a water mask marked as needing correction.",
  NO_MATCH_NOT_VERIFIED_EMPTY: "was segmented but the provider found no water. That is not a verified empty mask.",
  MASK_AMBIGUOUS: "has more than one different accepted mask. Choose one in the Segmentation panel.",
  MASK_NOT_WATER: "only has a mask for something other than water.",
  IMAGE_NOT_AVAILABLE: "is not available any more.",
  SOURCE_CHANGED: "changed after its run used it, so it is not the same evidence.",
  SOURCE_MISSING: "is missing from the site folder.",
  CAMERA_NOT_STABLE: "was marked by a reviewer as having an unstable camera.",
  IMAGE_SIZE_DIFFERS_FROM_SEGMENTATION: "has a different size from the one its mask was made for.",
  WATCHED_AREA_CHANGED: "The two images were segmented with different watched areas, so the view may not match.",
  WATCHED_AREA_CONFIG_CHANGED: "The watched area saved with the two runs differs, so the view may not match.",
  IMAGE_SIZE_CHANGED: "The two images have different sizes, so they cannot be assumed to line up.",
  DIFFERENT_CAMERA: "These images are from different cameras. Quantitative comparison is only for one camera.",
  TIMESTAMPS_EQUAL: "Both images have the same capture time, so there is no earlier and later.",
  TIMESTAMPS_REVERSED: "The images were not in time order.",
  MASK_OUTSIDE_WATCHED_AREA: "A mask has water outside the watched area, so it does not belong to this view.",
  MASK_SIZE_MISMATCH: "A mask does not match its image size.",
  INVALID_WATCHED_AREA: "The watched area is not valid for these images.",
  NO_SAVED_RUN: "That image's sequence has no saved validation run yet. Run validation on it first (this does not start segmentation)."
};

let cmp = {
  open: false, active: false, other: null, candidates: null, loading: false, error: "",
  filters: { sequence: "", from: "", to: "", acceptedOnly: false },
  framing: false, result: null, busy: false, saved: null, restore: null, token: 0
};

function compareActive() {
  return cmp.active && cmp.other != null;
}

// Selecting a different current image closes the comparison, so it never describes the wrong image.
function compareReset() {
  cmp.open = false; cmp.active = false; cmp.other = null; cmp.result = null; cmp.saved = null;
  cmp.framing = false; cmp.error = ""; cmp.token += 1;
}

function cmpKey(item) {
  return `${item.sequence_id}|${item.filename}`;
}

function cmpCurrent() {
  const sel = days[state.selectedIndex];
  return { sequence_id: sequenceId(), filename: sel.filename, run_id: runId, captured_at_utc: sel.capturedAtUtc, local_time: sel.time, mask_state: null };
}

function cmpImageQuery(item) {
  return new URLSearchParams({ folder_name: folderName, sequence_id: item.sequence_id, filename: item.filename });
}

function cmpOrdered() {
  // Chronological, whichever image was chosen first. The server orders the measurement the same way.
  const current = cmpCurrent();
  return String(cmp.other.captured_at_utc) < String(current.captured_at_utc)
    ? { earlier: cmp.other, later: current }
    : { earlier: current, later: cmp.other };
}

function cmpWhen(item) {
  const local = item.local_time ? String(item.local_time) : "";
  const utc = String(item.captured_at_utc || "");
  return `${escapeHtml(utc.slice(0, 10))} ${escapeHtml(utc.slice(11, 16))} UTC${local ? ` (${escapeHtml(local.length >= 16 ? local.slice(11, 16) : local)} local)` : ""}`;
}

function cmpElapsed(seconds) {
  if (typeof seconds !== "number" || seconds <= 0) return "";
  const hours = seconds / 3600;
  if (hours < 48) return `${hours.toFixed(1)} hours apart`;
  return `${(hours / 24).toFixed(1)} days apart`;
}

function compareButtonHtml() {
  if (compareActive()) return `<button class="btn" data-act="compare-close" style="font-size:12px;padding:5px 12px;">Close comparison</button>`;
  return `<button class="btn" data-act="compare-open" aria-expanded="${cmp.open}" style="font-size:12px;padding:5px 12px;">Compare with another image&hellip;</button>`;
}

// ---- picker ----
function cmpCandidateRows() {
  const all = (cmp.candidates && cmp.candidates.images) || [];
  const current = cmpCurrent();
  const f = cmp.filters;
  return all.filter((i) => {
    if (i.sequence_id === current.sequence_id && i.filename === current.filename) return false;
    if (f.sequence && i.sequence_id !== f.sequence) return false;
    const day = String(i.captured_at_utc || "").slice(0, 10);
    if (f.from && day < f.from) return false;
    if (f.to && day > f.to) return false;
    if (f.acceptedOnly && i.mask_state !== "accepted") return false;
    return true;
  });
}

function cmpRowHtml(item) {
  const [maskText, maskTone] = CMP_MASK_TEXT[item.mask_state] || CMP_MASK_TEXT.none;
  const sequence = ((cmp.candidates.sequences || []).find((s) => s.sequence_id === item.sequence_id) || {}).label || item.sequence_id;
  const thumb = `/api/compare/thumbnail?${cmpImageQuery(item)}`;
  return `<button type="button" data-act="compare-pick" data-key="${escapeHtml(cmpKey(item))}" style="display:flex;gap:10px;align-items:center;width:100%;text-align:left;border:none;border-bottom:1px solid var(--line-soft);background:transparent;padding:8px 12px;cursor:pointer;">
    <img src="${thumb}" loading="lazy" width="84" alt="" style="border-radius:4px;background:#000;flex-shrink:0;">
    <span style="display:flex;flex-direction:column;gap:3px;min-width:0;">
      <span style="font-size:12px;font-weight:600;font-family:var(--mono);">${cmpWhen(item)}</span>
      <span class="hint" style="word-break:break-all;">${escapeHtml(sequence)}</span>
      <span style="display:flex;gap:4px;flex-wrap:wrap;"><span class="pill ${maskTone}" style="font-size:11px;">${escapeHtml(maskText)}</span>${item.run_id ? "" : '<span class="pill gray" style="font-size:11px;">No saved run: images only</span>'}</span>
    </span>
  </button>`;
}

function comparePickerHtml() {
  if (!cmp.open || compareActive()) return "";
  if (cmp.loading) return `<div class="card card-pad-sm hint">Loading images of this camera&hellip;</div>`;
  if (cmp.error) return `<div class="err">${escapeHtml(cmp.error)}</div>`;
  const rows = cmpCandidateRows();
  const sequences = (cmp.candidates && cmp.candidates.sequences) || [];
  const f = cmp.filters;
  const shown = rows.slice(0, 200);
  return `<div class="card" style="margin-bottom:14px;overflow:hidden;" id="comparePicker">
    <div style="padding:10px 14px;border-bottom:1px solid var(--line-soft);display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
      <span class="title-s">Choose the other image</span>
      <span class="hint">Same camera only. Choosing never changes a label, baseline, dataset or run.</span>
    </div>
    <div style="padding:10px 14px;display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;border-bottom:1px solid var(--line-soft);font-size:12px;">
      <label>Sequence<br><select id="cmpSequence" style="max-width:240px;font-size:12px;"><option value="">All sequences</option>${sequences.map((s) => `<option value="${escapeHtml(s.sequence_id)}" ${f.sequence === s.sequence_id ? "selected" : ""}>${escapeHtml(s.label)} (${s.image_count})</option>`).join("")}</select></label>
      <label>From<br><input type="date" id="cmpFrom" value="${escapeHtml(f.from)}"></label>
      <label>To<br><input type="date" id="cmpTo" value="${escapeHtml(f.to)}"></label>
      <label class="inline-row"><input type="checkbox" id="cmpAccepted" ${f.acceptedOnly ? "checked" : ""}> Only images with an accepted mask</label>
      <button type="button" class="btn" data-act="compare-close" style="font-size:12px;padding:5px 12px;">Cancel</button>
    </div>
    <div style="max-height:340px;overflow:auto;" id="comparePickerList">
      ${shown.map(cmpRowHtml).join("") || `<div style="padding:16px;" class="hint">No other saved images of this camera match these filters.</div>`}
      ${rows.length > shown.length ? `<div class="hint" style="padding:10px 14px;">Showing the first ${shown.length} of ${rows.length}. Narrow the dates or sequence to see the rest.</div>` : ""}
    </div>
  </div>`;
}

// ---- the comparison itself (reuses the existing views) ----
function compareViewsHtml({ showSide, showOverlay }) {
  const { earlier, later } = cmpOrdered();
  const eq = cmpImageQuery(earlier);
  const lq = cmpImageQuery(later);
  const captions = [
    `Earlier &mdash; ${cmpWhen(earlier)}`,
    `Later &mdash; ${cmpWhen(later)}`
  ];
  const elapsed = cmp.result ? cmpElapsed(cmp.result.elapsed_seconds) : cmpElapsed((Date.parse(later.captured_at_utc) - Date.parse(earlier.captured_at_utc)) / 1000);
  const direction = `<div style="background:var(--paper);border-radius:8px;padding:8px 12px;margin-bottom:10px;font-size:13px;">
      <strong>Earlier &rarr; later${elapsed ? `, ${escapeHtml(elapsed)}` : ""}.</strong>
      <span class="hint"> Always in time order, whichever image you picked first. This is a comparison of two moments, not a continuous record.</span>
    </div>`;
  const side = showSide ? sideBySideHtml({ summary: detail.summary, sel: days[state.selectedIndex], baselineQuery: eq, selectedQuery: lq, comparisonQuery: null, captions }) : "";
  const over = showOverlay ? `<div class="hint" style="margin:14px 0 6px;">Overlay comparison &mdash; slide to blend the later image over the earlier one</div>${onionHtml(eq, lq)}` : "";
  return direction + side + over + compareResultHtml();
}

function cmpReasonLines(codes, framingOk) {
  const lines = [];
  (codes || []).forEach((code) => {
    if (code === "ALIGNMENT_NOT_VERIFIED_AUTOMATICALLY" || /^COVERAGE_/.test(code)) return;
    const m = /^(EARLIER|LATER)_(.+)$/.exec(code);
    const base = m ? m[2] : code;
    const text = CMP_REASON_TEXT[base];
    if (!text) { lines.push(escapeHtml(code)); return; }
    lines.push(m ? `The ${m[1].toLowerCase()} image ${escapeHtml(text)}` : escapeHtml(text));
  });
  return [...new Set(lines)];
}

function cmpPct(value) {
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function cmpProvenanceHtml(result) {
  const side = (label, d) => {
    const decision = d.review_decision ? `${escapeHtml(d.review_decision)}${d.reviewed_at_utc ? ` at ${escapeHtml(formatUtc(d.reviewed_at_utc))}` : ""}` : "no accepted mask";
    return `<div><strong>${label}:</strong> mask ${decision}${d.segmentation_run_id ? ` &middot; segmentation run ${escapeHtml(d.segmentation_run_id)}` : ""}${d.image_sha256 ? ` &middot; image ${escapeHtml(String(d.image_sha256).slice(0, 12))}` : ""}</div>`;
  };
  const p = result.provenance || {};
  return `<details style="margin-top:8px;font-size:12px;"><summary class="hint" style="cursor:pointer;">Mask review state and calculation</summary>
    <div class="hint" style="line-height:1.6;margin-top:4px;">${side("Earlier", p.earlier || {})}${side("Later", p.later || {})}<div>Calculation ${escapeHtml(p.calculation_version || "")}. Every fraction is divided by the watched-area pixels; masks inside the watched area only.</div></div></details>`;
}

function compareResultHtml() {
  const { earlier, later } = cmpOrdered();
  const framing = `<label class="inline-row" style="margin:6px 0;font-size:12px;"><input type="checkbox" id="cmpFraming" ${cmp.framing ? "checked" : ""}> I confirm the camera view did not move between these two images</label>`;
  if (cmp.busy && !cmp.result) return `<div class="card card-pad-sm hint" style="margin-top:14px;">Measuring&hellip;</div>`;
  const head = `<div style="font-size:12px;font-weight:700;color:var(--ink-soft);margin-bottom:6px;">Water coverage change</div>`;
  if (!later.run_id || !earlier.run_id) {
    return `<div class="card card-pad-sm" style="margin-top:14px;">${head}<div class="hint">${escapeHtml(CMP_REASON_TEXT.NO_SAVED_RUN)}</div></div>`;
  }
  const result = cmp.result;
  if (!result) return `<div class="card card-pad-sm" style="margin-top:14px;">${head}${framing}</div>`;
  const ev = result.evidence;
  if (result.available && ev.status === "available") {
    const m = (ev.quality || {}).measurement || {};
    const rate = typeof m.change_rate_pp_per_hour === "number" ? `${m.change_rate_pp_per_hour >= 0 ? "+" : ""}${m.change_rate_pp_per_hour.toFixed(2)} percentage points per hour (image-space rate)` : "no rate (no elapsed time)";
    const q = new URLSearchParams({ folder_name: folderName, a_run: result.earlier.run_id, a_file: result.earlier.filename, b_run: result.later.run_id, b_file: result.later.filename });
    return `<div class="card card-pad-sm" style="margin-top:14px;">${head}
      <div style="font-size:14px;line-height:1.7;">
        Coverage of the watched area: <strong>${cmpPct(m.earlier_fraction)}</strong> &rarr; <strong>${cmpPct(m.later_fraction)}</strong><br>
        Change: <strong>${ev.value >= 0 ? "+" : ""}${Number(ev.value).toFixed(1)} percentage points</strong> &middot; ${escapeHtml(rate)}<br>
        Newly wet <strong>${cmpPct(m.newly_wet_fraction)}</strong> &middot; no longer wet <strong>${cmpPct(m.no_longer_wet_fraction)}</strong> of the watched area
      </div>
      <img src="/api/compare/overlay?${q}" class="img-fill" alt="Later image with water that arrived and water that left coloured" style="margin-top:10px;">
      <div class="hint" style="margin-top:6px;"><span style="color:#0078ff;font-weight:600;">Blue</span> water arrived &middot; <span style="color:#e60000;font-weight:600;">red</span> water left &middot; <span style="color:#969696;font-weight:600;">grey</span> wet in both &middot; yellow box is the watched area.</div>
      <div class="hint" style="margin-top:6px;line-height:1.5;">${escapeHtml(result.note)} The software does not align cameras; the framing was confirmed by you. This is a separate number from the run's <em>Pixel appearance change</em> score, and the two are never combined.</div>
      ${framing}
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:6px;">
        <button class="btn" data-act="compare-save" ${cmp.busy ? "disabled" : ""} style="font-size:12px;padding:5px 12px;">Save this comparison</button>
        <span class="hint">${cmp.saved ? `Saved (${escapeHtml(cmp.saved.pair_key)}). Saving keeps the exact images, masks and calculation version and never overwrites an earlier result.` : "Optional. Viewing writes nothing."}</span>
      </div>
      ${cmpProvenanceHtml(result)}
    </div>`;
  }
  const reasons = cmpReasonLines(ev.reason_codes, cmp.framing);
  return `<div class="card card-pad-sm" style="margin-top:14px;">${head}
    <div style="background:var(--warn-soft);border-radius:8px;padding:10px 12px;font-size:12px;line-height:1.6;">
      <strong>Water coverage change is unavailable for this pair.</strong> The images above can still be compared by eye. No number is shown instead of a guess.
      <ul style="margin:6px 0 0 18px;padding:0;">${reasons.map((r) => `<li>${r}</li>`).join("")}</ul>
    </div>
    ${framing}
    ${cmpProvenanceHtml(result)}
  </div>`;
}

// ---- actions ----
async function compareOpen() {
  cmp.restore = { selectedIndex: state.selectedIndex, filter: state.filter, scrollY: window.scrollY };
  cmp.open = true; cmp.error = "";
  if (!cmp.candidates) {
    cmp.loading = true; render();
    try {
      cmp.candidates = await api(`/api/compare/candidates?${new URLSearchParams({ folder_name: folderName, run_id: runId })}`);
    } catch (error) {
      cmp.error = error.message;
    }
    cmp.loading = false;
  }
  render();
}

async function compareMeasure() {
  if (!compareActive()) return;
  const current = cmpCurrent();
  const other = cmp.other;
  if (!current.run_id || !other.run_id) { cmp.result = null; render(); return; }
  const token = ++cmp.token;
  cmp.busy = true; cmp.saved = null; render();
  try {
    const result = await api("/api/compare/measure", {
      folder_name: folderName,
      a: { run_id: current.run_id, filename: current.filename },
      b: { run_id: other.run_id, filename: other.filename },
      framing_confirmed: cmp.framing
    });
    if (token === cmp.token) cmp.result = result;
  } catch (error) {
    if (token === cmp.token) { cmp.result = null; toast(error.message); }
  }
  if (token === cmp.token) { cmp.busy = false; render(); }
}

async function compareSave() {
  if (!cmp.result || cmp.busy) return;
  const current = cmpCurrent();
  cmp.busy = true; render();
  try {
    const saved = await api("/api/compare/save", {
      folder_name: folderName,
      a: { run_id: current.run_id, filename: current.filename },
      b: { run_id: cmp.other.run_id, filename: cmp.other.filename },
      framing_confirmed: cmp.framing
    });
    cmp.saved = saved.saved;
    toast(saved.saved && saved.saved.reused ? "This comparison was already saved." : "Comparison saved.");
  } catch (error) {
    toast(error.message);
  }
  cmp.busy = false; render();
}

function compareClose() {
  const restore = cmp.restore;
  compareReset();
  if (restore) {
    state.selectedIndex = restore.selectedIndex;
    state.filter = restore.filter;
  }
  render();
  if (restore) window.scrollTo(0, restore.scrollY);
}

async function handleCompareAction(act, el) {
  if (act === "compare-open") await compareOpen();
  else if (act === "compare-close") compareClose();
  else if (act === "compare-save") await compareSave();
  else if (act === "compare-pick") {
    const item = ((cmp.candidates && cmp.candidates.images) || []).find((i) => cmpKey(i) === el.dataset.key);
    if (!item) return;
    cmp.other = item; cmp.active = true; cmp.open = false; cmp.result = null; cmp.saved = null;
    render();
    await compareMeasure();
  }
}

function wireCompare() {
  const picker = $("comparePicker");
  if (picker) {
    const sync = () => { render(); };
    $("cmpSequence").addEventListener("change", (e) => { cmp.filters.sequence = e.target.value; sync(); });
    $("cmpFrom").addEventListener("change", (e) => { cmp.filters.from = e.target.value; sync(); });
    $("cmpTo").addEventListener("change", (e) => { cmp.filters.to = e.target.value; sync(); });
    $("cmpAccepted").addEventListener("change", (e) => { cmp.filters.acceptedOnly = e.target.checked; sync(); });
  }
  const framing = $("cmpFraming");
  if (framing) framing.addEventListener("change", () => { cmp.framing = framing.checked; compareMeasure(); });
}
// ---- end compare any two images ----
