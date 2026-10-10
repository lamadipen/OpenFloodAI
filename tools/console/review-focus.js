const RESULT_CODE = {
  possible_water_level_change: "P",
  no_water_level_change: "N",
  cannot_judge_water_level: "U",
  camera_or_image_problem: "C"
};

const RESULT_TEXT = {
  P: "Possible visual change",
  N: "No clear water-level change",
  U: "Cannot judge",
  C: "Camera or image problem",
  M: "Image unavailable"
};

const LABELS = [
  ["water_level_rising", "Water level is rising", "1"],
  ["water_level_falling", "Water level is falling", "2"],
  ["no_water_level_change", "No water-level change", "3"],
  ["cannot_judge_water_level", "Cannot judge from these images", "4"],
  ["camera_video_problem", "Camera or image problem", "5"]
];

const LABEL_TEXT = Object.fromEntries(LABELS.map(([value, text]) => [value, text]));
const DATASET_HELP = {
  water_segmentation: "Requires a completed water mask that a person accepted for this exact image.",
  level_classification: "Requires this human review, a matched gauge reading, and an approved site category definition.",
  gauge_height: "Requires this image's matched gauge reading, station, unit, and quality.",
  level_change: "Uses the reference and this image, earlier first. The target comes from the two gauge readings, not from your label.",
  visual_change: "Uses the reference and this image, earlier first. The target is what the reviewer saw. One judgment is enough to add the pair; it is stored as awaiting review inside the dataset. If several people judged it they must agree, not vote. Informed judgments (made after machine evidence) count too and are marked."
};

const FAR_REFERENCE_DAYS = 45;
const DATASET_TASKS = [
  ["water_segmentation", "Water segmentation"],
  ["level_classification", "Low / middle / high classification"],
  ["gauge_height", "Gauge-height estimation"],
  ["level_change", "Rising / falling (gauge-derived)"],
  ["visual_change", "Visible water change (human-judged pair)"]
];
const PAIR_TASK_IDS = ["level_change", "visual_change"];

const folderName = qs("site");
const runId = qs("run_id");
let detail = null;
let days = [];
let evidencePoints = [];
let gaugeByImage = new Map();
let coverageByFile = new Map();
let samResults = [];
let datasets = [];
let selectedDatasetId = "";
let datasetResult = null;
let selectedIndex = 0;
let viewMode = "original";
let compareMode = "side";
let zoom = 1;
let overlayOpacity = 50;
let selectedLabel = null;
let confidence = "medium";
let draftNote = "";
let draftQuality = {};
let savingLabel = false;
let savingMask = false;
let savingDataset = false;
let reviewerId = loadSetting("openfloodai.reviewerId");
let autoReveal = loadSetting("openfloodai.autoReveal") !== "no";
let revising = false;
let draftCameraStable = "";
let referenceChoices = new Map();
let revealedFiles = new Set();
let candidates = null;
let pickerOpen = false;
let pickerSequence = "";
let datasetCheck = null;
let datasetCheckKey = "";
let datasetMaskChoice = "";
let referenceResults = new Map();
let creatingDataset = false;

function loadSetting(key) {
  try { return localStorage.getItem(key) || ""; } catch (error) { return ""; }
}

function saveSetting(key, value) {
  try { localStorage.setItem(key, value); } catch (error) { /* Browser storage is optional. */ }
}

function buildDays(records) {
  return (records || []).map((record) => {
    const capturedAtUtc = String(record.captured_at_utc || "");
    const localTime = String(record.local_time || capturedAtUtc);
    const available = record.download_status === "downloaded";
    return {
      date: capturedAtUtc.slice(0, 10),
      time: localTime.length >= 16 ? localTime.slice(11, 16) : localTime,
      capturedAtUtc,
      filename: record.filename || "",
      score: typeof record.region_change_score === "number" ? record.region_change_score : null,
      reason: record.reason || "",
      code: available ? RESULT_CODE[record.result] || "N" : "M"
    };
  }).filter((day) => day.date).sort((a, b) => a.capturedAtUtc.localeCompare(b.capturedAtUtc));
}

function pointFor(day) {
  return evidencePoints.find((point) => point.filename === day.filename) || null;
}

function reviewsFor(day) {
  const point = pointFor(day);
  if (!point) return [];
  if (Array.isArray(point.reviews)) return point.reviews;
  return point.label ? [{ label: point.label, ...(point.review || {}) }] : [];
}

function refFromDay(day) {
  return {
    sequence_id: day.sequence_id || detail.summary.sequence_id,
    run_id: day.run_id || runId,
    filename: day.filename,
    capturedAtUtc: day.capturedAtUtc,
    date: day.date,
    time: day.time
  };
}

function previousDay(day) {
  const index = days.indexOf(day);
  for (let i = index - 1; i >= 0; i -= 1) if (days[i].code !== "M") return days[i];
  return null;
}

function refKey(ref) {
  return `${ref.sequence_id || detail.summary.sequence_id}|${ref.filename}`;
}

function sameImage(a, b) {
  return !!a && !!b && !!a.filename && refKey(a) === refKey(b);
}

// The image this one is judged against: the run baseline, the previous image of the run, or any
// other saved image of the same camera. The label only means something relative to it.
function referenceFor(day) {
  const choice = referenceChoices.get(day.filename) || { mode: "baseline" };
  if (choice.mode === "chosen" && choice.item) return { ...choice.item, kind: "chosen" };
  if (choice.mode === "previous") {
    const previous = previousDay(day);
    if (previous) return { ...refFromDay(previous), kind: "previous" };
  }
  return { ...baselineDay(), kind: "baseline" };
}

function referencePayload(ref) {
  return { sequence_id: ref.sequence_id || detail.summary.sequence_id, run_id: ref.run_id || runId, filename: ref.filename };
}

// A review made before this page recorded references used the run baseline.
function reviewReferenceKey(review) {
  const ref = review.reference;
  if (ref && ref.filename) return `${ref.sequence_id || detail.summary.sequence_id}|${ref.filename}`;
  return `${detail.summary.sequence_id}|${detail.summary.baseline_filename}`;
}

function reviewIsForReference(review, ref) {
  return reviewReferenceKey(review) === refKey(ref);
}

function canReview(day) {
  const ref = referenceFor(day);
  return day.code !== "M" && !!pointFor(day) && !!ref.filename && !sameImage(ref, refFromDay(day));
}

function independentReviews(day) {
  const ref = referenceFor(day);
  const latest = new Map();
  const apart = [];
  reviewsFor(day).forEach((review, index) => {
    if (!reviewIsForReference(review, ref)) return;
    const id = String((review.label && review.label.reviewer_id) || `anonymous-${index + 1}`);
    if (review.review_stage !== "blind" || !(review.label && review.label.reviewer_id)) {
      apart.push({ ...review, reviewerId: id });
      return;
    }
    latest.set(normalizedReviewer(id), { ...review, reviewerId: id });
  });
  return { counted: [...latest.values()], apart };
}

function revealKeyStorage() {
  return `openfloodai.revealed.${runId}.${normalizedReviewer(reviewerId)}`;
}

function loadRevealed() {
  try { revealedFiles = new Set(JSON.parse(loadSetting(revealKeyStorage()) || "[]")); } catch (error) { revealedFiles = new Set(); }
}

function markRevealed(day) {
  revealedFiles.add(day.filename);
  saveSetting(revealKeyStorage(), JSON.stringify([...revealedFiles]));
}

// Machine evidence for an image counts as seen once it was shown to this reviewer. A label saved
// after that is an informed revision, not an independent judgment.
function evidenceSeen(day) {
  return revealedFiles.has(day.filename);
}

function stageForSave(day) {
  return evidenceSeen(day) ? "informed" : "blind";
}

function reviewableCount() {
  return days.filter((day) => canReview(day)).length;
}

function normalizedReviewer(value) {
  return String(value || "").trim().toLocaleLowerCase();
}

function reviewForCurrentReviewer(day) {
  const wanted = normalizedReviewer(reviewerId);
  if (!wanted) return null;
  const ref = referenceFor(day);
  return [...reviewsFor(day)].reverse().find(
    (review) => normalizedReviewer(review.label && review.label.reviewer_id) === wanted && reviewIsForReference(review, ref)
  ) || null;
}

function isRevealed(day) {
  return !!reviewForCurrentReviewer(day) && evidenceSeen(day);
}

function reviewedByCurrentCount() {
  return days.filter((day) => canReview(day) && reviewForCurrentReviewer(day)).length;
}

function chooseInitialIndex() {
  const wanted = qs("select");
  const wantedIndex = wanted ? days.findIndex((day) => day.filename === wanted) : -1;
  if (wantedIndex >= 0) return wantedIndex;
  const unreviewed = days.findIndex((day) => canReview(day) && !reviewForCurrentReviewer(day));
  if (unreviewed >= 0) return unreviewed;
  const reviewable = days.findIndex((day) => canReview(day));
  return reviewable >= 0 ? reviewable : 0;
}

function baselineDay() {
  const filename = detail.summary.baseline_filename;
  const gaugeBaseline = (((detail.gauge_evidence || {}).images) || []).find(
    (candidate) => candidate.filename === filename || candidate.is_baseline === true
  ) || {};
  const record = (detail.records || []).find((candidate) => candidate.filename === filename) || gaugeBaseline;
  const capturedAtUtc = String(record.captured_at_utc || "");
  return {
    filename,
    sequence_id: detail.summary.sequence_id,
    run_id: runId,
    capturedAtUtc,
    date: capturedAtUtc.slice(0, 10) || "Reference",
    time: String(record.local_time || capturedAtUtc).slice(11, 16)
  };
}

function gaugeKey(filename, capturedAtUtc) {
  return `${filename || ""}|${capturedAtUtc || ""}`;
}

function selectedGauge(day) {
  return gaugeByImage.get(gaugeKey(day.filename, day.capturedAtUtc)) || null;
}

function riverbankEvidence(day) {
  return (detail.evidence_records || []).find(
    (row) => row.plugin_id === "riverbank_crossing_v1" && row.timestamp === day.capturedAtUtc
  ) || null;
}

function segmentationFor(day) {
  const matches = samResults.filter(
    (result) => result.filename === day.filename && result.status === "completed"
  );
  return matches.find((result) => result.review_status === "accepted") || matches[0] || null;
}

function formatUtc(value) {
  const parsed = new Date(value);
  return value && !Number.isNaN(parsed.getTime())
    ? `${parsed.toISOString().slice(0, 16).replace("T", " ")} UTC`
    : "time unavailable";
}

function formatGaugeGap(seconds) {
  if (typeof seconds !== "number") return "";
  if (seconds === 0) return "same minute as image";
  const minutes = Math.round(Math.abs(seconds) / 60);
  return `${minutes} min ${seconds < 0 ? "before" : "after"} image`;
}

function imageQuery(day) {
  return new URLSearchParams({
    folder_name: folderName,
    sequence_id: day.sequence_id || detail.summary.sequence_id,
    filename: day.filename
  });
}

function originalImageUrl(day) {
  return `/api/image-sequence-image?${imageQuery(day)}`;
}

function guideOverlayUrl(day) {
  return `/api/image-sequence-riverbank-overlay?${new URLSearchParams({
    folder_name: folderName,
    sequence_id: detail.summary.sequence_id,
    run_id: runId,
    filename: day.filename
  })}`;
}

function segmentationOverlayUrl(result) {
  return `/api/hosted-sam/overlay?${new URLSearchParams({
    folder_name: folderName,
    run_id: result.run_id,
    result_id: result.result_id
  })}`;
}

function pairImageHtml(day, title, subtitle) {
  return `<figure class="pair-image">
    <figcaption><strong>${escapeHtml(title)}</strong><span>${escapeHtml(subtitle)}</span></figcaption>
    <div class="zoom-pane"><div class="zoom-layer" style="width:${zoom * 100}%"><img src="${originalImageUrl(day)}" alt="${escapeHtml(title)} river image"></div></div>
  </figure>`;
}

// ---- the same evidence view for the reference and the current image --------------------------

// Segmentation results for an image: this run's sequence is already loaded; another sequence's
// results are fetched once, the first time a reference from it is shown.
function resultsForSequence(sequenceId) {
  if (!sequenceId || sequenceId === detail.summary.sequence_id) return samResults;
  const cached = referenceResults.get(sequenceId);
  if (cached) return cached === "loading" ? [] : cached;
  referenceResults.set(sequenceId, "loading");
  api(`/api/hosted-sam/results?${new URLSearchParams({ folder_name: folderName, sequence_id: sequenceId })}`)
    .then((data) => { referenceResults.set(sequenceId, data.results || []); render(); })
    .catch(() => { referenceResults.set(sequenceId, []); });
  return [];
}

function segmentationForImage(item) {
  const matches = resultsForSequence(item.sequence_id).filter(
    (result) => result.filename === item.filename && result.status === "completed"
  );
  return matches.find((result) => result.review_status === "accepted") || matches[0] || null;
}

// The confirmed guides this run was made with, drawn over any image as the "base guide".
function baseGuideSvg() {
  const setup = (detail && detail.setup_used) || {};
  const parts = [];
  const region = setup.reference_region;
  if (region && [region.x, region.y, region.width, region.height].every((n) => typeof n === "number")) {
    parts.push(`<rect x="${region.x}" y="${region.y}" width="${region.width}" height="${region.height}" fill="none" stroke="#ffffff" stroke-width="0.6" vector-effect="non-scaling-stroke"/>`);
  }
  const guides = (setup.normal_waterline_guides || []).filter((g) => g.status !== "invalid" && Array.isArray(g.points) && g.points.length > 1);
  guides.forEach((guide) => {
    const points = guide.points.map((point) => `${point.x},${point.y}`).join(" ");
    parts.push(`<polyline points="${points}" fill="none" stroke="#28dc28" stroke-width="2.4" vector-effect="non-scaling-stroke"/>`);
  });
  return { svg: parts.length ? `<svg class="guide-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${parts.join("")}</svg>` : "", guideCount: guides.length };
}

// What one image shows in the current view: its picture (with a drawn guide when the view needs
// one) and a one-line note. The same function serves the reference and the current image.
function evidenceLayer(item, isCurrent) {
  let imageUrl = originalImageUrl(item);
  let note = "Original camera image";
  let overlay = "";
  if (viewMode === "segmentation") {
    const result = segmentationForImage(item);
    if (result) {
      imageUrl = segmentationOverlayUrl(result);
      const status = result.review_status || "unreviewed";
      note = status === "accepted" ? "Accepted water mask" : `Draft water mask - ${status.replaceAll("_", " ")}`;
    } else {
      note = isCurrent ? "No segmentation saved - showing original image" : "No segmentation saved for the reference - showing original image";
    }
  } else if (viewMode === "guide") {
    const guide = baseGuideSvg();
    const riverbank = isCurrent ? riverbankEvidence(item) : null;
    const samples = riverbank && riverbank.quality && riverbank.quality.samples;
    if (riverbank && riverbank.status === "available" && Array.isArray(samples) && samples.length) {
      imageUrl = guideOverlayUrl(item);
      note = "Base guide with land-side and water-side bands";
    } else {
      overlay = guide.svg;
      note = guide.guideCount ? "Base guide (drawn with this run, assumes the camera did not move)" : "No normal guide is saved for this run";
    }
  }
  return { imageUrl, note, overlay };
}

function evidencePaneHtml(item, title, subtitle, isCurrent) {
  const { imageUrl, note, overlay } = evidenceLayer(item, isCurrent);
  return `<figure class="pair-image">
    <figcaption><strong>${escapeHtml(title)}</strong><span>${escapeHtml(subtitle)}</span></figcaption>
    <div class="zoom-pane"><div class="zoom-layer" style="width:${zoom * 100}%"><img src="${imageUrl}" alt="${escapeHtml(note)} for ${escapeHtml(title)}">${overlay}</div></div>
    <div class="pane-note">${escapeHtml(note)}</div>
  </figure>`;
}

// The reference and the current image of the segmentation or guide view, side by side or blended.
function evidencePicturesHtml(day) {
  const reference = referenceFor(day);
  if (compareMode === "overlay") {
    const below = evidenceLayer(reference, false);
    const above = evidenceLayer(day, true);
    return `<div class="overlay-compare zoom-pane" data-pan>
      <div class="zoom-layer" style="width:${zoom * 100}%"><img src="${below.imageUrl}" alt="Reference ${escapeHtml(below.note)}">${below.overlay}</div>
      <div class="zoom-layer overlay-current" style="width:${zoom * 100}%;opacity:${overlayOpacity / 100}"><img src="${above.imageUrl}" alt="Current ${escapeHtml(above.note)}">${above.overlay}</div>
      <span class="image-corner left">Reference</span><span class="image-corner right">Current ${overlayOpacity}%</span>
    </div>
    <div class="pane-note"><strong>Reference:</strong> ${escapeHtml(below.note)} &middot; <strong>Current:</strong> ${escapeHtml(above.note)}</div>`;
  }
  return `<div class="image-pair" data-pan-group>
    ${evidencePaneHtml(reference, "Reference", formatUtc(reference.capturedAtUtc), false)}
    ${evidencePaneHtml(day, "Current", formatUtc(day.capturedAtUtc), true)}
  </div>`;
}

function daysApart(a, b) {
  const x = Date.parse(a);
  const y = Date.parse(b);
  return Number.isNaN(x) || Number.isNaN(y) ? null : Math.abs(x - y) / 86400000;
}

function referenceControlsHtml(day) {
  const ref = referenceFor(day);
  const modes = [["baseline", "Run baseline"], ["previous", "Previous image"]];
  const apart = daysApart(day.capturedAtUtc, ref.capturedAtUtc);
  const far = apart != null && apart > FAR_REFERENCE_DAYS
    ? `<div class="reference-warning">The reference is ${Math.round(apart)} days away from this image. Seasons and lighting can differ; choose “Cannot judge” if you cannot tell.</div>`
    : "";
  const kindText = { baseline: "run baseline", previous: "previous image", chosen: "chosen image" }[ref.kind] || "reference";
  return `<div class="reference-controls">
    <span class="ref-label">Reference image</span>
    <div class="view-tabs" role="group" aria-label="Reference image">
      ${modes.map(([id, text]) => `<button class="view-tab" data-ref-mode="${id}" aria-pressed="${ref.kind === id}" ${id === "previous" && !previousDay(day) ? "disabled" : ""}>${text}</button>`).join("")}
      <button class="view-tab" data-ref-pick aria-pressed="${ref.kind === "chosen" || pickerOpen}">Choose another…</button>
    </div>
    <span class="ref-note">${escapeHtml(kindText)} · ${escapeHtml(formatUtc(ref.capturedAtUtc))}</span>
  </div>${far}${referencePickerHtml(day)}`;
}

function referencePickerHtml(day) {
  if (!pickerOpen) return "";
  if (!candidates) return `<div class="reference-picker"><div class="hint">Loading images of this camera…</div></div>`;
  if (candidates.error) return `<div class="reference-picker"><div class="error-note">${escapeHtml(candidates.error)}</div></div>`;
  const current = refFromDay(day);
  const sequences = candidates.sequences || [];
  const rows = (candidates.images || [])
    .filter((image) => image.run_id && !sameImage(image, current) && (!pickerSequence || image.sequence_id === pickerSequence))
    .map((image) => ({ image, gap: daysApart(image.captured_at_utc, day.capturedAtUtc) ?? 1e9 }))
    .sort((a, b) => a.gap - b.gap)
    .slice(0, 60);
  return `<div class="reference-picker" role="group" aria-label="Choose a reference image">
    <div class="picker-head"><strong>Nearest images first</strong>
      <label class="compact-control">Sequence <select id="pickerSequence"><option value="">All sequences</option>${sequences.map((sequence) => `<option value="${escapeHtml(sequence.sequence_id)}" ${pickerSequence === sequence.sequence_id ? "selected" : ""}>${escapeHtml(sequence.label)}</option>`).join("")}</select></label>
      <button class="btn" data-ref-close>Close</button></div>
    <div class="picker-list">${rows.map(({ image }) => `<button class="picker-row" data-ref-choose="${escapeHtml(image.sequence_id)}|${escapeHtml(image.filename)}"><img loading="lazy" alt="" src="/api/compare/thumbnail?${imageQuery({ sequence_id: image.sequence_id, filename: image.filename })}"><span><strong>${escapeHtml(String(image.captured_at_utc || "").slice(0, 16).replace("T", " "))} UTC</strong><em>${escapeHtml(((sequences.find((sequence) => sequence.sequence_id === image.sequence_id) || {}).label) || image.sequence_id)}</em></span></button>`).join("") || `<div class="hint">No other saved image with a validation run was found for this camera.</div>`}</div>
  </div>`;
}

function comparisonPicturesHtml(day) {
  const reference = referenceFor(day);
  const current = refFromDay(day);
  if (!reference.filename) {
    return `<div class="empty-note">No reference image is available. Choose one above, or choose “Cannot judge” rather than guessing from one image.</div>`;
  }
  if (sameImage(reference, current)) {
    return `<div class="empty-note"><strong>This image is the reference.</strong> It cannot be compared with itself. Choose another reference above, or go to the next image.</div>`;
  }
  if (compareMode === "overlay") {
    return `<div class="overlay-compare zoom-pane" data-pan>
      <img src="${originalImageUrl(reference)}" alt="Reference river image" style="width:${zoom * 100}%">
      <img class="overlay-current" src="${originalImageUrl(day)}" alt="Current river image over reference" style="width:${zoom * 100}%;opacity:${overlayOpacity / 100}">
      <span class="image-corner left">Reference</span><span class="image-corner right">Current ${overlayOpacity}%</span>
    </div>`;
  }
  return `<div class="image-pair" data-pan-group>
    ${pairImageHtml(reference, "Reference", formatUtc(reference.capturedAtUtc))}
    ${pairImageHtml(day, "Current", formatUtc(day.capturedAtUtc))}
  </div>`;
}

function comparisonControlsHtml(day) {
  const reference = referenceFor(day);
  const usable = !!reference.filename && !sameImage(reference, refFromDay(day));
  return `<div class="comparison-controls">
    <div class="view-tabs" role="group" aria-label="Comparison view">
      <button class="view-tab" data-compare="side" aria-pressed="${compareMode === "side"}">Side by side</button>
      <button class="view-tab" data-compare="overlay" aria-pressed="${compareMode === "overlay"}" ${usable ? "" : "disabled"}>Overlay</button>
    </div>
    <label class="compact-control">Zoom <input type="range" id="zoomControl" min="1" max="3" step="0.25" value="${zoom}"></label>
    ${compareMode === "overlay" ? `<label class="compact-control">Current image <input type="range" id="opacityControl" min="0" max="100" value="${overlayOpacity}"></label>` : ""}
  </div>`;
}

function blindComparisonHtml(day) {
  return `<section class="card blind-stage" aria-label="Blind image comparison">
    <div class="blind-banner"><strong>Blind review</strong><span>Machine result, gauge, masks, and other reviewers are hidden until you confirm your own label.</span></div>
    ${referenceControlsHtml(day)}${comparisonControlsHtml(day)}${comparisonPicturesHtml(day)}
  </section>`;
}

function stageHtml(day) {
  const reference = referenceFor(day);
  const current = refFromDay(day);
  if (!reference.filename || sameImage(reference, current)) return comparisonPicturesHtml(day);
  if (viewMode === "original") return `<div class="compare-stage">${comparisonControlsHtml(day)}${comparisonPicturesHtml(day)}</div>`;
  return `<div class="compare-stage">${comparisonControlsHtml(day)}${evidencePicturesHtml(day)}</div>`;
}

function gaugeSparklineHtml(day) {
  const values = days.map((candidate, index) => {
    const row = selectedGauge(candidate);
    const reading = row && row.reading;
    return reading && typeof reading.value === "number" ? { index, value: reading.value } : null;
  }).filter(Boolean);
  if (values.length < 2) return "";
  const width = 280;
  const height = 52;
  const min = Math.min(...values.map((item) => item.value));
  const max = Math.max(...values.map((item) => item.value));
  const span = max - min || 1;
  const x = (index) => 5 + (index / Math.max(days.length - 1, 1)) * (width - 10);
  const y = (value) => height - 6 - ((value - min) / span) * (height - 12);
  const points = values.map((item) => `${x(item.index).toFixed(1)},${y(item.value).toFixed(1)}`).join(" ");
  const current = values.find((item) => item.index === selectedIndex);
  return `<svg class="gauge-sparkline" viewBox="0 0 ${width} ${height}" role="img" aria-label="Gauge readings across this run"><line x1="5" y1="${height - 6}" x2="${width - 5}" y2="${height - 6}" stroke="#dce6e3" /><polyline points="${points}" fill="none" stroke="#258779" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />${current ? `<circle cx="${x(current.index).toFixed(1)}" cy="${y(current.value).toFixed(1)}" r="4.5" fill="#fff" stroke="#17685e" stroke-width="2.5" />` : ""}</svg>`;
}

function signalPanelHtml(day) {
  const gaugeRow = selectedGauge(day);
  const reading = gaugeRow && gaugeRow.reading;
  const coverage = coverageByFile.get(day.filename);
  const riverbank = riverbankEvidence(day);
  const alignmentMissing = !!(riverbank && (riverbank.reason_codes || []).includes("CAMERA_ALIGNMENT_UNAVAILABLE"));
  const crossing = riverbank && riverbank.status === "available" && typeof riverbank.value === "number" ? riverbank.value : null;
  const gaugeValue = reading ? `${Number(reading.value).toFixed(2)} ${reading.unit || ""}` : "No matched reading";
  const gaugeNote = reading ? `${reading.parameter_label || "Gauge reading"}; ${formatGaugeGap(gaugeRow.time_difference_seconds)}${reading.quality_status === "provisional" ? "; provisional" : ""}.` : "No gauge reading was saved within the matching time window.";
  let coverageValue = "No usable water mask";
  let coverageNote = "Missing segmentation is not evidence of no water.";
  if (coverage && typeof coverage.coverage === "number" && coverage.basis === "accepted") {
    coverageValue = `${(coverage.coverage * 100).toFixed(1)}% accepted coverage`;
    coverageNote = "Calculated from a human-accepted water mask.";
  } else if (coverage && typeof coverage.coverage === "number" && coverage.basis === "draft") {
    coverageValue = `${(coverage.coverage * 100).toFixed(1)}% draft estimate`;
    coverageNote = "Machine draft only. It has not been accepted as dataset evidence.";
  }
  const crossingValue = crossing == null ? "Guide evidence unavailable" : crossing > 0 ? `${crossing.toFixed(1)}% of samples crossed` : "No clear crossing measured";
  const crossingNote = alignmentMissing ? "Review only: images were not camera-aligned, so movement can create a false change." : "This visual measurement still needs human review.";
  return `<div class="signal-grid">
    <div class="signal-row"><div class="signal-mark gauge">G</div><div><div class="signal-label">Gauge context</div><div class="signal-value">${escapeHtml(gaugeValue)}</div><div class="signal-note">${escapeHtml(gaugeNote)}</div>${gaugeSparklineHtml(day)}</div></div>
    <div class="signal-row"><div class="signal-mark">S</div><div><div class="signal-label">Water segmentation</div><div class="signal-value">${escapeHtml(coverageValue)}</div><div class="signal-note">${escapeHtml(coverageNote)}</div></div></div>
    <div class="signal-row"><div class="signal-mark guide">L</div><div><div class="signal-label">Normal guide</div><div class="signal-value">${escapeHtml(crossingValue)}</div><div class="signal-note">${escapeHtml(crossingNote)}</div></div></div>
  </div>`;
}

function cameraStableHtml() {
  const options = [["yes", "Same view"], ["no", "Camera moved"], ["unsure", "Not sure"]];
  return `<div class="camera-row" role="group" aria-label="Did the camera view stay the same?">
    <span class="ref-label">Did the camera view stay the same between the two images?</span>
    <div class="view-tabs">${options.map(([value, text], index) => `<button class="view-tab" data-camera="${value}" aria-pressed="${draftCameraStable === value}"><kbd>${["s", "m", "u"][index]}</kbd> ${text}</button>`).join("")}</div>
    <div class="field-help">A moved camera looks like a water change. Mark it so it is never mistaken for one.</div>
  </div>`;
}

function qualityFieldsHtml() {
  const fields = [["riverbank_visible", "Reference visible"], ["water_boundary_visible", "Water boundary visible"]];
  return `<details class="quality-fields"><summary>Optional image-quality notes</summary>${fields.map(([id, text]) => `<label>${escapeHtml(text)}<select id="${id}" data-quality-field="${id}"><option value="" ${draftQuality[id] ? "" : "selected"}>Not recorded</option>${["yes", "no", "unsure"].map((value) => `<option value="${value}" ${draftQuality[id] === value ? "selected" : ""}>${value[0].toUpperCase() + value.slice(1)}</option>`).join("")}</select></label>`).join("")}</details>`;
}

function labelPanelHtml(day) {
  const canLabel = canReview(day) && !!pointFor(day);
  const own = reviewForCurrentReviewer(day);
  const seen = evidenceSeen(day);
  const banner = seen
    ? `<div class="informed-banner"><strong>Informed revision.</strong> You have already seen the machine evidence for this image, so this label is recorded as informed and is not counted as an independent judgment.</div>`
    : own
      ? `<div class="hint">You are revising your blind label. The earlier label stays in the history.</div>`
      : "";
  return `<aside class="card label-panel" aria-label="Independent human label">
    <div class="focus-kicker">${seen ? "Your revision" : "Your independent review"}</div><h2 class="panel-title">What changed between the images?</h2>
    <div class="field-help">Judge the current image compared with the reference. “Rising” means more visible water now.</div>${banner}
    <label class="reviewer-field" for="reviewerId">Reviewer code</label><input id="reviewerId" value="${escapeHtml(reviewerId)}" maxlength="80" placeholder="Example: reviewer-a" autocomplete="off"><div class="field-help">Use a short team code, not a full personal name.</div>
    <div class="label-choices" role="group" aria-label="Human label">${LABELS.map(([value, text, key]) => `<button class="label-choice" data-label="${value}" aria-pressed="${selectedLabel === value}"><kbd>${key}</kbd><span>${escapeHtml(text)}</span></button>`).join("")}</div>
    ${cameraStableHtml()}
    <div class="confidence-row"><span>Confidence</span>${["low", "medium", "high"].map((value) => `<button data-confidence="${value}" aria-pressed="${confidence === value}">${value}</button>`).join("")}</div>
    ${qualityFieldsHtml()}<label class="reviewer-field" for="reviewNote">Optional note</label><textarea id="reviewNote" rows="2" placeholder="What helped or made this difficult?">${escapeHtml(draftNote)}</textarea>
    <label class="reveal-toggle"><input type="checkbox" id="autoReveal" ${autoReveal ? "checked" : ""}> Show the machine evidence right after I save</label>
    <div id="labelMessage" class="form-message" aria-live="polite"></div><button class="btn primary confirm-label" data-save-label ${canLabel && !savingLabel ? "" : "disabled"}>${savingLabel ? "Saving…" : seen ? "Save informed revision" : "Confirm human label"}</button><div class="shortcut-note">Keys 1–5 choose a label, s/m/u the camera view. Press Enter to confirm.</div>
  </aside>`;
}

function agreementHtml(day) {
  const { counted, apart } = independentReviews(day);
  const labels = new Set(counted.map((review) => review.label && review.label.human_label));
  const agreed = counted.length >= 2 && labels.size === 1;
  const disagreed = counted.length >= 2 && labels.size > 1;
  const note = apart.length ? `<span class="muted-12">${apart.length} review${apart.length === 1 ? "" : "s"} made after seeing evidence, or by an older form, ${apart.length === 1 ? "is" : "are"} kept but not counted.</span>` : "";
  if (counted.length < 2) {
    return `<div class="agreement-note"><strong>${counted.length} independent reviewer recorded.</strong><span>A second independent reviewer is needed before agreement can be measured.</span>${note}</div>`;
  }
  return `<div class="agreement-note ${agreed ? "agreed" : "disagreed"}"><strong>${agreed ? "Reviewers agree" : "Reviewers disagree"}</strong><span>${counted.map((review) => `${escapeHtml(review.reviewerId)}: ${escapeHtml(LABEL_TEXT[(review.label || {}).human_label] || "Unknown")}`).join(" · ")}${disagreed ? " · no majority vote" : ""}</span>${note}</div>`;
}

function maskReviewHtml(day) {
  const results = samResults.filter((result) => result.filename === day.filename && result.status === "completed");
  if (!results.length) return `<div class="curation-block"><h3>Water mask review</h3><div class="hint">No completed segmentation exists for this image.</div></div>`;
  return `<div class="curation-block"><h3>Water mask review</h3><div class="hint">This affects dataset eligibility, not your human water-level label.</div>${results.map((result) => {
    const status = result.review_status || "unreviewed";
    return `<div class="mask-review-row"><div><strong>${escapeHtml(result.prompt || "Water mask")}</strong><span class="pill ${status === "accepted" ? "ok" : status === "rejected" ? "bad" : "warn"}">${escapeHtml(status.replaceAll("_", " "))}</span></div><div class="mask-actions">${[["accepted", "Accept"], ["rejected", "Reject"], ["needs_correction", "Needs correction"]].map(([value, text]) => `<button class="btn ${status === value ? "primary" : ""}" data-mask-decision="${value}" data-mask-run="${escapeHtml(result.run_id)}" data-mask-result="${escapeHtml(result.result_id)}" ${savingMask ? "disabled" : ""}>${text}</button>`).join("")}</div></div>`;
  }).join("")}</div>`;
}

function selectedDataset() {
  return datasets.find((dataset) => dataset.dataset_id === selectedDatasetId) || null;
}

function acceptedMasks(day) {
  return samResults.filter((result) => result.filename === day.filename && result.status === "completed" && result.review_status === "accepted" && ["river water", "water"].includes(result.prompt));
}

function reasonListHtml(reasons) {
  const items = (reasons || []).map((reason) => `<li class="${reason.severity === "warning" ? "reason-warning" : ""}">${escapeHtml(reason.message)}</li>`).join("");
  return items ? `<ul>${items}</ul>` : "";
}

function agreementLineHtml(agreement) {
  if (!agreement) return "";
  const directions = Object.entries(agreement.by_direction || {}).map(([direction, who]) => `${direction.replaceAll("_", " ")}: ${who.join(", ")}`).join(" · ");
  const informed = (agreement.informed || []).length ? ` · informed (saw machine evidence): ${agreement.informed.map(escapeHtml).join(", ")}` : "";
  return `<div class="dataset-agreement">${agreement.reviewers} reviewer${agreement.reviewers === 1 ? "" : "s"} judged this pair (at least ${agreement.needed} needed)${directions ? ` · ${escapeHtml(directions)}` : ""}${informed}</div>`;
}

function datasetCheckHtml() {
  if (!datasetCheck) return "";
  if (datasetCheck.pending) return `<div class="dataset-result">Checking eligibility…</div>`;
  if (datasetCheck.error) return `<div class="error-note mt-10">${escapeHtml(datasetCheck.error)}</div>`;
  const status = datasetCheck.status;
  const title = status === "eligible" ? "Eligible: nothing has been added yet" : status === "already_included" ? "Already in this dataset" : "Not eligible for this dataset";
  return `<div class="dataset-result ${status === "eligible" ? "ok" : status === "ineligible" ? "bad" : ""}"><strong>${title}</strong>${agreementLineHtml(datasetCheck.agreement)}${reasonListHtml(datasetCheck.reasons)}</div>`;
}

function datasetResultHtml() {
  if (!datasetResult) return "";
  if (datasetResult.error) return `<div class="error-note mt-10">${escapeHtml(datasetResult.error)}</div>`;
  const title = datasetResult.status === "ineligible" ? "Not eligible for this dataset" : datasetResult.message || `Dataset: ${datasetResult.status || "updated"}`;
  return `<div class="dataset-result"><strong>${escapeHtml(title)}</strong>${reasonListHtml(datasetResult.reasons)}</div>`;
}

// Reference and current image in time order, as the pair tasks need them.
function orderedPair(day) {
  const reference = referenceFor(day);
  const current = refFromDay(day);
  const refTime = Date.parse(reference.capturedAtUtc);
  const curTime = Date.parse(current.capturedAtUtc);
  const referenceIsLater = !Number.isNaN(refTime) && !Number.isNaN(curTime) && refTime > curTime;
  return referenceIsLater ? { earlier: current, later: reference } : { earlier: reference, later: current };
}

function pairRef(ref) {
  return { folder_name: folderName, run_id: ref.run_id || runId, filename: ref.filename };
}

function datasetRequest(day) {
  const dataset = selectedDataset();
  if (!dataset) return null;
  if (PAIR_TASK_IDS.includes(dataset.task)) {
    const pair = orderedPair(day);
    return { dataset, pair: true, body: { dataset_id: dataset.dataset_id, earlier: pairRef(pair.earlier), later: pairRef(pair.later) } };
  }
  const body = { dataset_id: dataset.dataset_id, folder_name: folderName, run_id: runId, filename: day.filename };
  if (dataset.task === "water_segmentation") {
    const choice = datasetMaskChoice || (acceptedMasks(day)[0] ? `${acceptedMasks(day)[0].run_id}|${acceptedMasks(day)[0].result_id}` : "");
    if (choice) [body.mask_run_id, body.mask_result_id] = choice.split("|");
  }
  return { dataset, pair: false, body };
}

async function refreshDatasetCheck(day) {
  if (!isRevealed(day) || creatingDataset) return;
  const request = datasetRequest(day);
  if (!request) { datasetCheck = null; datasetCheckKey = ""; return; }
  const key = JSON.stringify(request.body);
  if (key === datasetCheckKey) return;
  datasetCheckKey = key;
  datasetCheck = { pending: true };
  try {
    const result = await postDataset("/api/dataset-check", request.body);
    if (datasetCheckKey !== key) return;
    datasetCheck = result.error ? { error: result.error } : result;
  } catch (error) {
    if (datasetCheckKey !== key) return;
    datasetCheck = { error: error.message };
  }
  render();
}

function createDatasetHtml() {
  return `<div class="dataset-create"><label>New dataset name<input id="newDatasetName" maxlength="80" placeholder="Example: Visible change pilot"></label>
    <label>Task<select id="newDatasetTask">${DATASET_TASKS.map(([id, text]) => `<option value="${id}">${escapeHtml(text)}</option>`).join("")}</select></label>
    <div class="hint">Nothing is trained, uploaded, or published. Split policy and tolerances are set on the Datasets page.</div>
    <button class="btn primary" data-create-dataset ${savingDataset ? "disabled" : ""}>Create dataset</button></div>`;
}

function datasetPanelHtml(day) {
  const dataset = selectedDataset();
  const head = `<h3>Add to dataset</h3><div class="hint">Nothing is trained, uploaded, or published.</div>`;
  if (!datasets.length || creatingDataset) {
    return `<div class="curation-block">${head}${datasets.length ? `<button class="btn" data-cancel-create>Back to existing datasets</button>` : `<div class="hint">No dataset drafts exist yet.</div>`}${createDatasetHtml()}</div>`;
  }
  const ownReview = reviewForCurrentReviewer(day);
  const group = ownReview && ownReview.dataset_group ? ownReview.dataset_group : "not assigned";
  const masks = dataset && dataset.task === "water_segmentation" ? acceptedMasks(day) : [];
  const maskSelect = masks.length ? `<label>Accepted mask<select id="datasetMask">${masks.map((mask) => `<option value="${escapeHtml(mask.run_id)}|${escapeHtml(mask.result_id)}" ${datasetMaskChoice === `${mask.run_id}|${mask.result_id}` ? "selected" : ""}>${escapeHtml(mask.prompt)} · ${escapeHtml(formatUtc(mask.processed_at_utc))}</option>`).join("")}</select></label>` : "";
  const isPair = dataset && PAIR_TASK_IDS.includes(dataset.task);
  const pair = isPair ? orderedPair(day) : null;
  const pairNote = pair ? `<div class="dataset-pair">Pair, earlier first: ${escapeHtml(formatUtc(pair.earlier.capturedAtUtc))} → ${escapeHtml(formatUtc(pair.later.capturedAtUtc))}</div>` : "";
  const eligible = datasetCheck && datasetCheck.status === "eligible";
  const label = savingDataset ? "Adding…" : isPair ? "Add pair to dataset" : "Add to dataset";
  return `<div class="curation-block">${head}<label>Dataset<select id="datasetSelect">${datasets.map((candidate) => `<option value="${escapeHtml(candidate.dataset_id)}" ${candidate.dataset_id === selectedDatasetId ? "selected" : ""}>${escapeHtml(candidate.name)} · ${escapeHtml(candidate.task_title)}</option>`).join("")}</select></label><button class="btn link-btn" data-new-dataset>New dataset…</button><div class="dataset-meta"><span>Review group: <strong>${escapeHtml(group)}</strong></span><span>Split: <strong>assigned by dataset policy when added</strong></span></div><div class="hint">${escapeHtml(DATASET_HELP[(dataset || {}).task] || "")}</div>${maskSelect}${pairNote}${datasetCheckHtml()}<button class="btn primary" data-add-dataset ${savingDataset || !eligible ? "disabled" : ""}>${label}</button>${datasetResultHtml()}</div>`;
}

function evidenceStageHtml(day) {
  const own = reviewForCurrentReviewer(day);
  const stage = own && own.review_stage === "informed" ? "Informed revision saved" : "Your independent label is saved";
  return `<div class="revealed-head"><div><div class="focus-kicker">Stage 2 · Evidence revealed</div><h2>${stage}</h2></div><div class="revealed-actions"><span class="pill ok">${escapeHtml(LABEL_TEXT[(own.label || {}).human_label] || "Human review saved")}</span><button class="btn" data-revise>Revise my label</button></div></div>${agreementHtml(day)}<div class="evidence-layout"><section class="card evidence-stage" aria-label="Machine evidence after human review"><div class="evidence-toolbar"><div class="view-tabs" role="group" aria-label="Evidence view">${[["original", "Original"], ["segmentation", "Segmentation"], ["guide", "Riverbank guide"]].map(([id, text]) => `<button class="view-tab" data-view="${id}" aria-pressed="${viewMode === id}">${text}</button>`).join("")}</div><span class="pill ${day.code === "P" ? "warn" : day.code === "C" ? "bad" : "gray"}">${escapeHtml(RESULT_TEXT[day.code])}</span></div>${stageHtml(day)}<div class="stage-caption"><span>The reference is always shown beside the current image. Machine and gauge evidence are visible only after your label is saved.</span></div></section><aside class="card decision-panel"><div class="decision-head"><div class="focus-kicker">Decision support</div><div class="title-m mt-4">Compare with your judgment</div><div class="hint">Supporting evidence, not a flood declaration.</div></div>${signalPanelHtml(day)}</aside></div><section class="card curation-panel"><div class="curation-grid">${maskReviewHtml(day)}${datasetPanelHtml(day)}</div></section>`;
}

function hiddenStageHtml(day) {
  const own = reviewForCurrentReviewer(day);
  return `<section class="card hidden-stage"><div class="revealed-head"><div><div class="focus-kicker">Label saved · evidence hidden</div><h2>Your independent label is saved</h2></div><span class="pill ok">${escapeHtml(LABEL_TEXT[(own.label || {}).human_label] || "Human review saved")}</span></div>
    <p class="hint">Machine results, gauge and other reviewers stay hidden so the next image is judged blind too. Reveal them when you want to check this one; a label changed after that is recorded as informed.</p>
    <div class="hidden-actions"><button class="btn primary" data-reveal>Reveal evidence for this image</button><button class="btn" data-revise>Revise my label (still blind)</button></div></section>`;
}

function queueHtml() {
  const baselineName = detail.summary.baseline_filename;
  return `<div class="card queue"><div class="queue-head"><div class="title-s">Neighbouring images</div><div class="muted-12">Choose nearby dates without revealing machine results.</div></div><div class="queue-list" id="focusQueue">${days.map((day, index) => {
    const count = independentReviews(day).counted.length;
    const own = !!reviewForCurrentReviewer(day);
    const isBaseline = day.filename === baselineName;
    const text = day.code === "M" ? "Image unavailable" : isBaseline && !canReview(day) ? "Reference image" : count ? `${count} reviewer${count === 1 ? "" : "s"}` : "Not reviewed";
    return `<button class="queue-item" data-index="${index}" aria-current="${index === selectedIndex}"><span class="queue-thumb"><img src="${day.code === "M" ? "" : originalImageUrl(day)}" alt="" loading="lazy"></span><span class="queue-date">${escapeHtml(day.date)}</span><span class="queue-state"><span class="state-dot ${own ? "reviewed" : ""}"></span>${escapeHtml(text)}</span></button>`;
  }).join("")}</div></div>`;
}

function resetDraftForDay(day) {
  const own = reviewForCurrentReviewer(day);
  selectedLabel = own && own.label ? own.label.human_label : null;
  confidence = own && own.label && own.label.confidence ? own.label.confidence : "medium";
  draftNote = own && own.label ? own.label.note || "" : "";
  draftCameraStable = own && own.label && own.label.camera_stable ? own.label.camera_stable : "";
  draftQuality = {};
  ["riverbank_visible", "water_boundary_visible"].forEach((field) => {
    if (own && own.label && own.label[field]) draftQuality[field] = own.label[field];
  });
  datasetResult = null;
  datasetCheck = null;
  datasetCheckKey = "";
  datasetMaskChoice = "";
  revising = false;
  viewMode = "original";
}

function selectDay(index) {
  selectedIndex = Math.max(0, Math.min(index, days.length - 1));
  resetDraftForDay(days[selectedIndex]);
  try {
    const url = new URL(location.href);
    url.searchParams.set("select", days[selectedIndex].filename);
    history.replaceState(null, "", url);
  } catch (error) { /* URL synchronization is optional. */ }
  render();
}

function nextUnreviewedIndex() {
  for (let offset = 1; offset <= days.length; offset += 1) {
    const index = (selectedIndex + offset) % days.length;
    if (canReview(days[index]) && !reviewForCurrentReviewer(days[index])) return index;
  }
  return -1;
}

async function refreshReviewData() {
  const sequenceId = detail.summary.sequence_id;
  const workspace = await api(`/api/workspace-evidence?${new URLSearchParams({ folder_name: folderName, kind: "image", run_id: runId, media_id: sequenceId })}`);
  evidencePoints = workspace.points || [];
}

const UNJUDGED_LABELS = ["cannot_judge_water_level", "camera_video_problem"];

async function saveHumanLabel() {
  const day = days[selectedIndex];
  const reviewerInput = $("reviewerId");
  reviewerId = String((reviewerInput && reviewerInput.value) || reviewerId || "").trim();
  const message = $("labelMessage");
  if (!reviewerId) { message.textContent = "Enter a reviewer code before saving."; return; }
  if (!selectedLabel) { message.textContent = "Choose what changed before saving."; return; }
  if (!UNJUDGED_LABELS.includes(selectedLabel) && !draftCameraStable) {
    message.textContent = "Say whether the camera view stayed the same. A moved camera looks like a water change.";
    return;
  }
  const point = pointFor(day);
  if (!point || !canReview(day)) { message.textContent = "This image cannot be labelled against that reference."; return; }
  const reference = referenceFor(day);
  const stage = stageForSave(day);
  savingLabel = true;
  saveSetting("openfloodai.reviewerId", reviewerId);
  render();
  let saved = false;
  try {
    await api("/api/workspace-label", {
      folder_name: folderName,
      kind: "image",
      run_id: runId,
      media_id: detail.summary.sequence_id,
      sample_key: point.key,
      human_label: selectedLabel,
      confidence,
      reviewer_id: reviewerId,
      review_stage: stage,
      reference: referencePayload(reference),
      note: draftNote.trim(),
      ...(draftCameraStable ? { camera_stable: draftCameraStable } : {}),
      ...draftQuality
    });
    await refreshReviewData();
    loadRevealed();
    saved = true;
    if (stage === "blind" && autoReveal) markRevealed(day);
    toast(stage === "informed" ? "Informed revision saved. It is not counted as an independent judgment." : autoReveal ? "Independent human label saved. Machine evidence is now revealed." : "Independent human label saved. Evidence stays hidden.");
  } catch (error) { toast(error.message); }
  savingLabel = false;
  revising = false;
  if (saved && stage === "blind" && !autoReveal) {
    const next = nextUnreviewedIndex();
    if (next >= 0) { selectDay(next); return; }
  }
  resetDraftForDay(day);
  render();
}

async function ensureCandidates() {
  if (candidates) return;
  try {
    candidates = await api(`/api/compare/candidates?${new URLSearchParams({ folder_name: folderName, run_id: runId })}`);
  } catch (error) {
    candidates = { error: error.message };
  }
}

async function reviewMask(button) {
  savingMask = true;
  render();
  try {
    await api("/api/hosted-sam/review", {
      folder_name: folderName,
      run_id: button.dataset.maskRun,
      result_id: button.dataset.maskResult,
      decision: button.dataset.maskDecision
    });
    const sequenceId = detail.summary.sequence_id;
    const [sam, coverage] = await Promise.all([
      api(`/api/hosted-sam/results?${new URLSearchParams({ folder_name: folderName, sequence_id: sequenceId })}`),
      api(`/api/compare/series?${new URLSearchParams({ folder_name: folderName, run_id: runId })}`)
    ]);
    samResults = sam.results || [];
    coverageByFile = new Map((coverage.images || []).map((row) => [row.filename, row]));
    datasetCheckKey = ""; // a changed mask changes eligibility
    toast("Mask review saved.");
  } catch (error) { toast(error.message); }
  savingMask = false;
  render();
}

async function postDataset(path, body) {
  const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok && !(response.status === 409 && data.conflict)) return { error: data.message || "Could not update the dataset." };
  return data;
}

async function addToDataset(day) {
  const request = datasetRequest(day);
  if (!request) return;
  savingDataset = true;
  render();
  try {
    datasetResult = await postDataset(request.pair ? "/api/dataset-add-pair" : "/api/dataset-add", request.body);
    datasets = (await api("/api/datasets")).datasets || datasets;
  } catch (error) { datasetResult = { error: error.message }; }
  savingDataset = false;
  datasetCheckKey = ""; // re-check: it is now already included
  render();
}

async function createDataset() {
  const name = ($("newDatasetName") || {}).value || "";
  const task = ($("newDatasetTask") || {}).value || "";
  if (!name.trim()) { toast("Name the dataset first."); return; }
  savingDataset = true;
  render();
  try {
    const result = await postDataset("/api/dataset-create", { name: name.trim(), task });
    if (result.error) throw new Error(result.error);
    datasets = (await api("/api/datasets")).datasets || datasets;
    selectedDatasetId = result.dataset.dataset_id;
    saveSetting("openfloodai.reviewDataset", selectedDatasetId);
    creatingDataset = false;
    datasetCheckKey = "";
    toast("Dataset created.");
  } catch (error) { toast(error.message); }
  savingDataset = false;
  render();
}

let syncingPanes = false;

function applyZoom(value) {
  zoom = value;
  document.querySelectorAll(".zoom-layer").forEach((layer) => { layer.style.width = `${zoom * 100}%`; });
  document.querySelectorAll(".overlay-compare img").forEach((image) => { image.style.width = `${zoom * 100}%`; });
}

function applyOpacity(value) {
  overlayOpacity = value;
  document.querySelectorAll(".overlay-current").forEach((image) => { image.style.opacity = String(overlayOpacity / 100); });
  document.querySelectorAll(".image-corner.right").forEach((label) => { label.textContent = `Current ${overlayOpacity}%`; });
}

function wirePanes() {
  const panes = [...document.querySelectorAll(".zoom-pane")];
  panes.forEach((pane) => {
    let drag = null;
    pane.addEventListener("mousedown", (event) => {
      if (zoom <= 1 || event.button !== 0) return;
      drag = { x: event.clientX, y: event.clientY, left: pane.scrollLeft, top: pane.scrollTop };
      pane.classList.add("panning");
      event.preventDefault();
    });
    window.addEventListener("mousemove", (event) => {
      if (!drag) return;
      pane.scrollLeft = drag.left - (event.clientX - drag.x);
      pane.scrollTop = drag.top - (event.clientY - drag.y);
    });
    window.addEventListener("mouseup", () => { drag = null; pane.classList.remove("panning"); });
  });
  document.querySelectorAll("[data-pan-group]").forEach((group) => {
    const members = [...group.querySelectorAll(".zoom-pane")];
    members.forEach((pane) => pane.addEventListener("scroll", () => {
      if (syncingPanes) return;
      syncingPanes = true;
      members.forEach((other) => { if (other !== pane) { other.scrollLeft = pane.scrollLeft; other.scrollTop = pane.scrollTop; } });
      syncingPanes = false;
    }));
  });
}

function setReference(day, choice) {
  referenceChoices.set(day.filename, choice);
  pickerOpen = false;
  datasetCheckKey = "";
  resetDraftForDay(day);
  render();
}

function wireControls(day) {
  const on = (selector, event, handler) => document.querySelectorAll(selector).forEach((el) => el.addEventListener(event, () => handler(el)));
  on("[data-index]", "click", (button) => selectDay(Number(button.dataset.index)));
  on("[data-step]", "click", (button) => selectDay(selectedIndex + Number(button.dataset.step)));
  on("[data-compare]", "click", (button) => { compareMode = button.dataset.compare; render(); });
  on("[data-view]", "click", (button) => { viewMode = button.dataset.view; render(); });
  on("[data-label]", "click", (button) => { selectedLabel = button.dataset.label; render(); });
  on("[data-camera]", "click", (button) => { draftCameraStable = button.dataset.camera; render(); });
  on("[data-confidence]", "click", (button) => { confidence = button.dataset.confidence; render(); });
  on("[data-mask-decision]", "click", (button) => reviewMask(button));
  on("[data-ref-mode]", "click", (button) => setReference(day, { mode: button.dataset.refMode }));
  on("[data-ref-pick]", "click", async () => { pickerOpen = !pickerOpen; render(); if (pickerOpen) { await ensureCandidates(); render(); } });
  on("[data-ref-close]", "click", () => { pickerOpen = false; render(); });
  on("[data-ref-choose]", "click", (button) => {
    const [sequenceId, filename] = button.dataset.refChoose.split("|");
    const image = ((candidates && candidates.images) || []).find((item) => item.sequence_id === sequenceId && item.filename === filename);
    if (!image || !image.run_id) return;
    setReference(day, { mode: "chosen", item: { sequence_id: image.sequence_id, run_id: image.run_id, filename: image.filename, capturedAtUtc: String(image.captured_at_utc || ""), date: String(image.captured_at_utc || "").slice(0, 10), time: String(image.local_time || "").slice(11, 16) } });
  });
  const pickerSelect = $("pickerSequence");
  if (pickerSelect) pickerSelect.addEventListener("change", () => { pickerSequence = pickerSelect.value; render(); });
  on("[data-revise]", "click", () => { revising = true; render(); });
  on("[data-reveal]", "click", () => { markRevealed(day); datasetCheckKey = ""; render(); });
  on("[data-new-dataset]", "click", () => { creatingDataset = true; render(); });
  on("[data-cancel-create]", "click", () => { creatingDataset = false; render(); });
  on("[data-create-dataset]", "click", () => createDataset());
  const saveButton = document.querySelector("[data-save-label]");
  if (saveButton) saveButton.addEventListener("click", saveHumanLabel);
  const nextButton = document.querySelector("[data-next-unreviewed]");
  if (nextButton) nextButton.addEventListener("click", () => { const index = nextUnreviewedIndex(); if (index >= 0) selectDay(index); });
  // The sliders update the pictures in place. Redrawing the page on every move would replace the
  // slider under the pointer and end the drag after one step.
  const zoomControl = $("zoomControl");
  if (zoomControl) zoomControl.addEventListener("input", () => applyZoom(Number(zoomControl.value)));
  const opacityControl = $("opacityControl");
  if (opacityControl) opacityControl.addEventListener("input", () => applyOpacity(Number(opacityControl.value)));
  const reviewerInput = $("reviewerId");
  if (reviewerInput) {
    reviewerInput.addEventListener("input", () => { reviewerId = reviewerInput.value; });
    reviewerInput.addEventListener("change", () => { reviewerId = reviewerInput.value.trim(); saveSetting("openfloodai.reviewerId", reviewerId); loadRevealed(); resetDraftForDay(day); render(); });
  }
  const reveal = $("autoReveal");
  if (reveal) reveal.addEventListener("change", () => { autoReveal = reveal.checked; saveSetting("openfloodai.autoReveal", autoReveal ? "yes" : "no"); });
  const noteInput = $("reviewNote");
  if (noteInput) noteInput.addEventListener("input", () => { draftNote = noteInput.value; });
  document.querySelectorAll("[data-quality-field]").forEach((select) => select.addEventListener("change", () => {
    if (select.value) draftQuality[select.dataset.qualityField] = select.value;
    else delete draftQuality[select.dataset.qualityField];
  }));
  const datasetSelect = $("datasetSelect");
  if (datasetSelect) datasetSelect.addEventListener("change", () => { selectedDatasetId = datasetSelect.value; datasetResult = null; datasetCheck = null; datasetCheckKey = ""; saveSetting("openfloodai.reviewDataset", selectedDatasetId); render(); });
  const maskSelect = $("datasetMask");
  if (maskSelect) maskSelect.addEventListener("change", () => { datasetMaskChoice = maskSelect.value; datasetCheckKey = ""; render(); });
  const addDataset = document.querySelector("[data-add-dataset]");
  if (addDataset) addDataset.addEventListener("click", () => addToDataset(day));
  const current = document.querySelector('.queue-item[aria-current="true"]');
  if (current) current.scrollIntoView({ block: "nearest", inline: "center" });
  wirePanes();
  refreshDatasetCheck(day);
}

function labelPanelShown(day) {
  return !reviewForCurrentReviewer(day) || revising;
}

function render() {
  const content = $("content");
  const day = days[selectedIndex];
  const own = !!reviewForCurrentReviewer(day);
  const revealed = isRevealed(day);
  const fullReview = `/console/review.html?${new URLSearchParams({ site: folderName, run_id: runId, select: day.filename })}`;
  const labelling = `<div class="blind-layout">${blindComparisonHtml(day)}${labelPanelHtml(day)}</div>`;
  let body;
  if (own && revealed) body = (revising ? labelling : "") + evidenceStageHtml(day);
  else if (own) body = revising ? labelling : hiddenStageHtml(day);
  else body = labelling;
  content.innerHTML = `<div class="focus-head"><div><div class="focus-kicker">Human evidence review</div><h1 class="focus-title">${escapeHtml(day.date)}, ${escapeHtml(day.time)} local</h1></div><div class="focus-progress"><strong>${reviewedByCurrentCount()} of ${reviewableCount()}</strong> reviewed by ${escapeHtml(reviewerId || "this reviewer")}</div></div>${body}<div class="review-navigation"><button class="btn nav-arrow" data-step="-1" aria-label="Previous image" ${selectedIndex === 0 ? "disabled" : ""}>&larr;</button><button class="btn" data-next-unreviewed ${nextUnreviewedIndex() < 0 ? "disabled" : ""}>Next unreviewed</button><button class="btn nav-arrow" data-step="1" aria-label="Next image" ${selectedIndex === days.length - 1 ? "disabled" : ""}>&rarr;</button></div>${queueHtml()}<details class="card detail-disclosure"><summary>Technical run details</summary><div class="detail-body">Machine result and technical evidence stay hidden until this reviewer saves a label. <a href="${fullReview}">Open the established detailed review page</a>.</div></details>`;
  wireControls(day);
}

async function main() {
  if (!folderName || !runId) {
    document.body.innerHTML = '<div class="pad-40">Missing <code>?site=</code> or <code>?run_id=</code> in the URL.</div>';
    return;
  }
  const content = mountShell({
    active: "sites",
    activeSiteFolder: folderName,
    crumbs: [
      { label: "Sites", href: "/console/dashboard.html" },
      { label: folderName, href: `/console/site.html?${new URLSearchParams({ site: folderName })}` },
      { label: "Blind review" }
    ]
  });
  content.innerHTML = '<div class="card empty-note">Loading blind review&hellip;</div>';
  try {
    detail = await api(`/api/image-sequence-run-detail?${new URLSearchParams({ folder_name: folderName, run_id: runId })}`);
    days = buildDays(detail.records);
    if (!days.length) throw new Error("This run has no image records to review.");
    const sequenceId = detail.summary.sequence_id;
    const [workspace, coverage, sam, datasetListing] = await Promise.all([
      api(`/api/workspace-evidence?${new URLSearchParams({ folder_name: folderName, kind: "image", run_id: runId, media_id: sequenceId })}`).catch(() => ({ points: [] })),
      api(`/api/compare/series?${new URLSearchParams({ folder_name: folderName, run_id: runId })}`).catch(() => ({ images: [] })),
      api(`/api/hosted-sam/results?${new URLSearchParams({ folder_name: folderName, sequence_id: sequenceId })}`).catch(() => ({ results: [] })),
      api("/api/datasets").catch(() => ({ datasets: [] }))
    ]);
    evidencePoints = workspace.points || [];
    coverageByFile = new Map((coverage.images || []).map((row) => [row.filename, row]));
    samResults = sam.results || [];
    datasets = datasetListing.datasets || [];
    const rememberedDataset = loadSetting("openfloodai.reviewDataset");
    selectedDatasetId = datasets.some((dataset) => dataset.dataset_id === rememberedDataset) ? rememberedDataset : (datasets[0] || {}).dataset_id || "";
    gaugeByImage = new Map((((detail.gauge_evidence || {}).images) || []).map((row) => [gaugeKey(row.filename, row.captured_at_utc), row]));
    loadRevealed();
    selectedIndex = chooseInitialIndex();
    resetDraftForDay(days[selectedIndex]);
    $("topbarActions").innerHTML = `<a class="btn" href="/console/review-assisted.html?${new URLSearchParams({ site: folderName, run_id: runId })}" title="Move through the run with the machine results visible">Assisted review</a><a class="btn" href="/console/review.html?${new URLSearchParams({ site: folderName, run_id: runId })}">Detailed review</a>`;
    render();
  } catch (error) {
    content.innerHTML = `<div class="card error-note">Could not load this review: ${escapeHtml(error.message)}</div>`;
  }
}

document.addEventListener("keydown", (event) => {
  if (!days.length || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  const target = event.target;
  if (target && (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable)) return;
  const day = days[selectedIndex];
  if (labelPanelShown(day)) {
    const label = LABELS.find(([, , key]) => key === event.key);
    if (label) { event.preventDefault(); selectedLabel = label[0]; render(); return; }
    const camera = { s: "yes", m: "no", u: "unsure" }[event.key];
    if (camera) { event.preventDefault(); draftCameraStable = camera; render(); return; }
    if (event.key === "Enter" && selectedLabel) { event.preventDefault(); saveHumanLabel(); return; }
  }
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    selectDay(selectedIndex + (event.key === "ArrowRight" ? 1 : -1));
  }
});

main();
