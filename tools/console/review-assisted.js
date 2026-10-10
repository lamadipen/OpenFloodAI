// Assisted review: one image at a time, machine evidence visible, a dial along the bottom to move
// through the run. Labels saved here are always "informed" (the reviewer sees machine results), so
// they never count as independent judgments. Independent labels belong to Blind review.

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

const RESULT_PILL = { P: "warn", N: "gray", U: "gray", C: "bad", M: "gray" };

const LABELS = [
  ["water_level_rising", "Water level is rising", "1"],
  ["water_level_falling", "Water level is falling", "2"],
  ["no_water_level_change", "No water-level change", "3"],
  ["cannot_judge_water_level", "Cannot judge from these images", "4"],
  ["camera_video_problem", "Camera or image problem", "5"]
];
const UNJUDGED_LABELS = ["cannot_judge_water_level", "camera_video_problem"];
const LABEL_TEXT = Object.fromEntries(LABELS.map(([value, text]) => [value, text]));

// What the dial can plot. Each is a different measurement and they are never combined.
const METRICS = [
  { id: "pixel", label: "Pixel change", title: "Region change score against the run baseline", digits: 3 },
  { id: "coverage", label: "Water coverage", title: "Share of the watched area the segmentation marks as water", digits: 1 },
  { id: "gauge", label: "Gauge (context)", title: "Matched official gauge reading. Context only, never a label", digits: 2 }
];

const STEP = 24; // dial pixels between two images

const DATASET_HELP = {
  water_segmentation: "Requires a completed water mask that a person accepted for this exact image.",
  level_classification: "Requires this human review, a matched gauge reading, and an approved site category definition.",
  gauge_height: "Requires this image's matched gauge reading, station, unit, and quality.",
  level_change: "Uses the reference and this image, earlier first. The target comes from the two gauge readings, not from your label.",
  visual_change: "Uses the reference and this image, earlier first. The target is what at least two reviewers independently saw, judged blind. Labels saved on this page are informed, so they do not count."
};
const PAIR_TASK_IDS = ["level_change", "visual_change"];

const folderName = qs("site");
const runId = qs("run_id");
let detail = null;
let days = [];
let evidencePoints = [];
let gaugeByImage = new Map();
let coverageByFile = new Map();
let samResults = [];
let selectedIndex = 0;
let viewMode = "original";
let zoom = 1;
let compareMode = "single"; // "single" | "side" | "overlay"
let overlayOpacity = 50;
let swapped = false; // the big view shows the reference and the inset shows the current image
let metricId = "pixel";
let referenceMode = "baseline"; // "baseline" | "previous"
let selectedLabel = null;
let confidence = "medium";
let draftNote = "";
let draftCameraStable = "";
let saving = false;
let reviewerId = loadSetting("openfloodai.reviewerId");
let revealedFiles = new Set();
let marks = [];
let datasets = [];
let selectedDatasetId = "";
let datasetCheck = null;
let datasetCheckKey = "";
let datasetResult = null;
let datasetMaskChoice = "";
let savingDataset = false;
let quickShown = false;
let savingMask = false;

function loadSetting(key) {
  try { return localStorage.getItem(key) || ""; } catch (error) { return ""; }
}

function saveSetting(key, value) {
  try { localStorage.setItem(key, value); } catch (error) { /* Browser storage is optional. */ }
}

function normalizedReviewer(value) {
  return String(value || "").trim().toLocaleLowerCase();
}

// ---- the run's images and their evidence -----------------------------------------------------

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
  return { sequence_id: detail.summary.sequence_id, run_id: runId, filename: day.filename, capturedAtUtc: day.capturedAtUtc, date: day.date, time: day.time };
}

function previousDay(day) {
  for (let i = days.indexOf(day) - 1; i >= 0; i -= 1) if (days[i].code !== "M") return days[i];
  return null;
}

function baselineDay() {
  const filename = detail.summary.baseline_filename;
  const gaugeBaseline = (((detail.gauge_evidence || {}).images) || []).find((candidate) => candidate.filename === filename || candidate.is_baseline === true) || {};
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

// The image this one is judged against: the run baseline, or the previous image of the run.
function referenceFor(day) {
  if (referenceMode === "previous") {
    const previous = previousDay(day);
    if (previous) return { ...refFromDay(previous), kind: "previous" };
  }
  return { ...baselineDay(), kind: "baseline" };
}

function sameImage(a, b) {
  return !!a && !!b && !!a.filename && a.filename === b.filename && (a.sequence_id || detail.summary.sequence_id) === (b.sequence_id || detail.summary.sequence_id);
}

function dayFor(ref) {
  return days.find((day) => day.filename === ref.filename) || null;
}

function referencePayload(ref) {
  return { sequence_id: ref.sequence_id || detail.summary.sequence_id, run_id: ref.run_id || runId, filename: ref.filename };
}

function reviewReferenceKey(review) {
  const ref = review.reference;
  if (ref && ref.filename) return `${ref.sequence_id || detail.summary.sequence_id}|${ref.filename}`;
  return `${detail.summary.sequence_id}|${detail.summary.baseline_filename}`;
}

function canReview(day) {
  const ref = referenceFor(day);
  return day.code !== "M" && !!pointFor(day) && !!ref.filename && !sameImage(ref, refFromDay(day));
}

function reviewForCurrentReviewer(day) {
  const wanted = normalizedReviewer(reviewerId);
  if (!wanted) return null;
  const ref = referenceFor(day);
  const key = `${ref.sequence_id || detail.summary.sequence_id}|${ref.filename}`;
  return [...reviewsFor(day)].reverse().find(
    (review) => normalizedReviewer(review.label && review.label.reviewer_id) === wanted && reviewReferenceKey(review) === key
  ) || null;
}

function reviewableCount() {
  return days.filter((day) => canReview(day)).length;
}

function reviewedByCurrentCount() {
  return days.filter((day) => canReview(day) && reviewForCurrentReviewer(day)).length;
}

function refreshMarks() {
  marks = days.map((day) => !!reviewForCurrentReviewer(day));
}

// ---- blind-review bookkeeping ----------------------------------------------------------------
// The same storage key Blind review uses: an image whose machine evidence this reviewer has been
// shown can only be labelled as informed there, never as an independent judgment.

function revealKeyStorage() {
  return `openfloodai.revealed.${runId}.${normalizedReviewer(reviewerId)}`;
}

function loadRevealed() {
  try { revealedFiles = new Set(JSON.parse(loadSetting(revealKeyStorage()) || "[]")); } catch (error) { revealedFiles = new Set(); }
}

function markAllRevealed() {
  days.forEach((day) => revealedFiles.add(day.filename));
  saveSetting(revealKeyStorage(), JSON.stringify([...revealedFiles]));
}

// Opening this page shows the machine result of every image on the dial. The reviewer confirms that
// once, and from then on those images are informed for them.
function needsGate() {
  if (!normalizedReviewer(reviewerId)) return true;
  return days.some((day) => day.code !== "M" && !revealedFiles.has(day.filename));
}

// ---- machine evidence ------------------------------------------------------------------------

function gaugeKey(filename, capturedAtUtc) {
  return `${filename || ""}|${capturedAtUtc || ""}`;
}

function selectedGauge(day) {
  return gaugeByImage.get(gaugeKey(day.filename, day.capturedAtUtc)) || null;
}

function gaugeUnit() {
  for (const day of days) {
    const row = selectedGauge(day);
    if (row && row.reading && row.reading.unit) return row.reading.unit;
  }
  return "";
}

function coverageRow(day) {
  return coverageByFile.get(day.filename) || null;
}

function riverbankEvidence(day) {
  return (detail.evidence_records || []).find((row) => row.plugin_id === "riverbank_crossing_v1" && row.timestamp === day.capturedAtUtc) || null;
}

function segmentationFor(day) {
  const matches = samResults.filter((result) => result.filename === day.filename && result.status === "completed");
  return matches.find((result) => result.review_status === "accepted") || matches[0] || null;
}

// One number per image for the chosen measurement, or null. A missing value is never zero.
function metricValue(day, id) {
  if (day.code === "M") return null;
  if (id === "pixel") return day.score;
  if (id === "coverage") {
    const row = coverageRow(day);
    return row && typeof row.coverage === "number" ? row.coverage * 100 : null;
  }
  const gauge = selectedGauge(day);
  return gauge && gauge.reading && typeof gauge.reading.value === "number" ? gauge.reading.value : null;
}

function metricSpec(id) {
  return METRICS.find((metric) => metric.id === id) || METRICS[0];
}

function metricUnit(id) {
  return id === "coverage" ? "%" : id === "gauge" ? gaugeUnit() : "";
}

function metricCount(id) {
  return days.filter((day) => metricValue(day, id) != null).length;
}

function formatMetric(id, value) {
  return value == null ? "–" : value.toFixed(metricSpec(id).digits);
}

function signed(value, digits) {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(digits)}`;
}

function deltaText(id, from, to) {
  if (!from || !to) return "–";
  const a = metricValue(from, id);
  const b = metricValue(to, id);
  if (a == null || b == null) return "–";
  const unit = id === "coverage" ? " pp" : metricUnit(id) ? ` ${metricUnit(id)}` : "";
  return `${signed(b - a, metricSpec(id).digits)}${unit}`;
}

function formatUtc(value) {
  const parsed = new Date(value);
  return value && !Number.isNaN(parsed.getTime()) ? `${parsed.toISOString().slice(0, 16).replace("T", " ")} UTC` : "time unavailable";
}

function formatGaugeGap(seconds) {
  if (typeof seconds !== "number") return "";
  if (seconds === 0) return "same minute as image";
  return `${Math.round(Math.abs(seconds) / 60)} min ${seconds < 0 ? "before" : "after"} image`;
}

function shortDate(date) {
  const parsed = new Date(`${date}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? date : parsed.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

// ---- pictures --------------------------------------------------------------------------------

function imageQuery(item) {
  return new URLSearchParams({ folder_name: folderName, sequence_id: item.sequence_id || detail.summary.sequence_id, filename: item.filename });
}

function originalImageUrl(item) {
  return `/api/image-sequence-image?${imageQuery(item)}`;
}

function thumbnailUrl(item) {
  return `/api/compare/thumbnail?${imageQuery(item)}`;
}

function segmentationOverlayUrl(result) {
  return `/api/hosted-sam/overlay?${new URLSearchParams({ folder_name: folderName, run_id: result.run_id, result_id: result.result_id })}`;
}

function guideOverlayUrl(item) {
  return `/api/image-sequence-riverbank-overlay?${new URLSearchParams({ folder_name: folderName, sequence_id: detail.summary.sequence_id, run_id: runId, filename: item.filename })}`;
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
    parts.push(`<polyline points="${guide.points.map((point) => `${point.x},${point.y}`).join(" ")}" fill="none" stroke="#28dc28" stroke-width="2.4" vector-effect="non-scaling-stroke"/>`);
  });
  return { svg: parts.length ? `<svg class="guide-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${parts.join("")}</svg>` : "", guideCount: guides.length };
}

// What one image shows in the chosen view: its picture, a drawn guide when the view needs one, and a note.
function evidenceLayer(item, quick) {
  if (quick) return { imageUrl: thumbnailUrl(item), note: "Preview while moving", overlay: "" };
  const isRunImage = !!dayFor(item);
  let imageUrl = originalImageUrl(item);
  let note = "Original camera image";
  let overlay = "";
  if (viewMode === "segmentation") {
    const result = isRunImage ? segmentationFor(item) : null;
    if (result) {
      imageUrl = segmentationOverlayUrl(result);
      const status = result.review_status || "unreviewed";
      note = status === "accepted" ? "Accepted water mask" : `Draft water mask - ${status.replaceAll("_", " ")}`;
    } else {
      note = "No segmentation saved - showing original image";
    }
  } else if (viewMode === "guide") {
    const guide = baseGuideSvg();
    const riverbank = riverbankEvidence(item);
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

function layerHtml(layer, id, alt) {
  return `<div class="assist-layer" style="width:${zoom * 100}%"><img ${id ? `id="${id}"` : ""} src="${layer.imageUrl}" alt="${escapeHtml(alt)}">${layer.overlay}</div>`;
}

function panesFor(day, quick) {
  const reference = referenceFor(day);
  const current = refFromDay(day);
  const hasReference = !!reference.filename && !sameImage(reference, current);
  return { reference, current, hasReference, kindText: { baseline: "run baseline", previous: "previous image" }[reference.kind] || "reference" };
}

function navHtml() {
  return `<button class="assist-nav prev" data-step="-1" aria-label="Previous image" ${selectedIndex === 0 ? "disabled" : ""}>&lsaquo;</button>
      <button class="assist-nav next" data-step="1" aria-label="Next image" ${selectedIndex === days.length - 1 ? "disabled" : ""}>&rsaquo;</button>`;
}

function paneClass() {
  return `assist-pane ${zoom > 1 ? "zoomed" : ""}`;
}

// The reference and the current image next to each other, both in the chosen view.
function sideBySideHtml(reference, current, quick, kindText) {
  const ref = evidenceLayer(reference, quick);
  const cur = evidenceLayer(current, quick);
  return `<div class="assist-stage-body assist-side" data-pan-group>
      <figure class="assist-fig"><div class="${paneClass()}">${layerHtml(ref, "", "Reference river image")}</div><span class="assist-chip">Reference · ${escapeHtml(kindText)}</span></figure>
      <figure class="assist-fig"><div class="${paneClass()}">${layerHtml(cur, "", "Current river image")}</div><span class="assist-chip">Current</span></figure>
      ${navHtml()}
      <div class="assist-tag">${selectedIndex + 1} / ${days.length}</div>
    </div><div class="pane-note"><strong>Reference:</strong> ${escapeHtml(ref.note)} · ${escapeHtml(formatUtc(reference.capturedAtUtc))} &middot; <strong>Current:</strong> ${escapeHtml(cur.note)} · ${escapeHtml(formatUtc(current.capturedAtUtc))}</div>`;
}

// The current image blended over the reference; the slider sets how much of the current one shows.
function overlayHtml(reference, current, quick) {
  const ref = evidenceLayer(reference, quick);
  const cur = evidenceLayer(current, quick);
  return `<div class="assist-stage-body">
      <div class="${paneClass()}" id="assistPane">${layerHtml(ref, "assistImg", "Reference river image")}<div class="assist-layer assist-overlay-current" style="width:${zoom * 100}%;opacity:${overlayOpacity / 100}"><img src="${cur.imageUrl}" alt="Current river image over the reference">${cur.overlay}</div></div>
      ${navHtml()}
      <div class="assist-tag">${selectedIndex + 1} / ${days.length}</div>
      <span class="assist-chip left">Reference</span><span class="assist-chip right" id="overlayChip">Current ${overlayOpacity}%</span>
    </div><div class="pane-note"><strong>Reference:</strong> ${escapeHtml(ref.note)} · ${escapeHtml(formatUtc(reference.capturedAtUtc))} &middot; <strong>Current:</strong> ${escapeHtml(cur.note)} · ${escapeHtml(formatUtc(current.capturedAtUtc))}</div>`;
}

// Approve the water mask of the current image right under the segmentation picture. This is the same
// review as in Blind review and the detailed page; it decides whether the image can go into a
// segmentation dataset, not what you label.
function maskActionsHtml(day, quick) {
  if (viewMode !== "segmentation" || quick) return "";
  const result = segmentationFor(day);
  if (!result) return "";
  const status = result.review_status || "unreviewed";
  const pill = status === "accepted" ? "ok" : status === "rejected" ? "bad" : "warn";
  const decisions = [["accepted", "Accept"], ["rejected", "Reject"], ["needs_correction", "Needs correction"]];
  return `<div class="mask-bar" role="group" aria-label="Water mask review for the current image">
      <span class="mask-bar-label">Water mask of the current image <span class="pill ${pill}">${escapeHtml(status.replaceAll("_", " "))}</span></span>
      <span class="mask-bar-actions">${decisions.map(([value, text]) => `<button class="btn ${status === value ? "primary" : ""}" data-mask-decision="${value}" data-mask-run="${escapeHtml(result.run_id)}" data-mask-result="${escapeHtml(result.result_id)}" ${savingMask ? "disabled" : ""}>${text}</button>`).join("")}</span>
    </div>`;
}

function viewerHtml(day, quick) {
  return viewerPicturesHtml(day, quick) + maskActionsHtml(day, quick);
}

function viewerPicturesHtml(day, quick) {
  const { reference, current, hasReference, kindText } = panesFor(day);
  if (hasReference && compareMode === "side") return sideBySideHtml(reference, current, quick, kindText);
  if (hasReference && compareMode === "overlay") return overlayHtml(reference, current, quick);
  const showReference = swapped && hasReference;
  const main = showReference ? reference : current;
  const inset = showReference ? current : reference;
  const mainLayer = evidenceLayer(main, quick);
  // The small picture follows the chosen view too, so a mask or guide is compared like with like.
  const insetLayer = evidenceLayer(inset, quick || viewMode === "original");
  const mainName = showReference ? "Reference" : "Current";
  const insetName = showReference ? "Current" : "Reference";
  const insetHtml = hasReference
    ? `<button class="assist-inset" data-swap aria-label="Show the ${insetName.toLowerCase()} image large (R)" title="Show the ${insetName.toLowerCase()} image large (R)"><div class="inset-frame"><img src="${insetLayer.imageUrl}" alt="${insetName} image">${insetLayer.overlay}</div><span class="inset-caption">${insetName}${showReference ? "" : ` · ${escapeHtml(kindText)}`}</span></button>`
    : "";
  const caption = hasReference
    ? `${mainName}: ${escapeHtml(mainLayer.note)} · ${escapeHtml(formatUtc(main.capturedAtUtc))}`
    : "This image is the reference for the run. Choose “Previous image” as the reference to compare it.";
  return `<div class="assist-stage-body">
      <div class="${paneClass()}" id="assistPane">${layerHtml(mainLayer, "assistImg", `${mainName} river image`)}</div>
      ${navHtml()}
      <div class="assist-tag">${selectedIndex + 1} / ${days.length} · ${escapeHtml(mainName)}</div>
      ${insetHtml}
    </div><div class="pane-note">${caption}</div>`;
}

function toolbarHtml() {
  const views = [["original", "Original"], ["segmentation", "Segmentation"], ["guide", "Riverbank guide"]];
  const layouts = [["single", "Single"], ["side", "Side by side"], ["overlay", "Overlay"]];
  const usable = !!selectedDay() && panesFor(selectedDay()).hasReference;
  return `<div class="view-tabs" role="group" aria-label="Picture view">${views.map(([id, text]) => `<button class="view-tab" data-view="${id}" aria-pressed="${viewMode === id}">${text}</button>`).join("")}</div>
    <div class="view-tabs" role="group" aria-label="Comparison layout">${layouts.map(([id, text]) => `<button class="view-tab" data-compare="${id}" aria-pressed="${compareMode === id}" ${id !== "single" && !usable ? "disabled" : ""}>${text}</button>`).join("")}</div>
    <div class="assist-sliders">
      ${compareMode === "overlay" ? `<label class="compact-control">Current image <input type="range" id="opacityControl" min="0" max="100" value="${overlayOpacity}"></label>` : ""}
      <label class="compact-control">Zoom <input type="range" id="zoomControl" min="1" max="3" step="0.25" value="${zoom}"></label>
    </div>`;
}

function selectedDay() {
  return days[selectedIndex] || null;
}

// ---- side panel ------------------------------------------------------------------------------

function readoutHtml(day) {
  const spec = metricSpec(metricId);
  const value = metricValue(day, metricId);
  const row = coverageRow(day);
  let sub = spec.title;
  if (value == null) {
    sub = metricId === "coverage" ? "No usable water mask. Missing segmentation is not evidence of no water."
      : metricId === "gauge" ? "No gauge reading was matched to this image."
        : "This image was not compared.";
  } else if (metricId === "coverage") {
    sub = row && row.basis === "accepted" ? "Water coverage · accepted mask" : "Water coverage · machine draft only";
  }
  const unit = metricUnit(metricId);
  return `<div class="assist-readout"><span class="assist-value">${escapeHtml(formatMetric(metricId, value))}</span>${unit ? `<span class="assist-unit">${escapeHtml(unit)}</span>` : ""}<span class="pill ${RESULT_PILL[day.code]}">${escapeHtml(RESULT_TEXT[day.code])}</span></div>
    <div class="assist-sub">${escapeHtml(sub)}</div>`;
}

function contextRowsHtml(day) {
  const gaugeRow = selectedGauge(day);
  const reading = gaugeRow && gaugeRow.reading;
  const row = coverageRow(day);
  const riverbank = riverbankEvidence(day);
  const crossing = riverbank && riverbank.status === "available" && typeof riverbank.value === "number" ? riverbank.value : null;
  const gauge = reading ? `${Number(reading.value).toFixed(2)} ${reading.unit || ""} · ${formatGaugeGap(gaugeRow.time_difference_seconds)}` : "No matched reading";
  const mask = row && typeof row.coverage === "number"
    ? `${(row.coverage * 100).toFixed(1)}% ${row.basis === "accepted" ? "accepted" : "draft"}`
    : "No usable water mask";
  const guide = crossing == null ? "Unavailable" : crossing > 0 ? `${crossing.toFixed(1)}% of samples crossed` : "No clear crossing";
  return `<span>Gauge</span><b title="Official gauge reading. Context only.">${escapeHtml(gauge)}</b>
    <span>Water mask</span><b>${escapeHtml(mask)}</b>
    <span>Normal guide</span><b title="Images are not camera-aligned, so a moved camera can look like a crossing.">${escapeHtml(guide)}</b>`;
}

function metaHtml(day) {
  const reference = referenceFor(day);
  const refDay = dayFor(reference);
  const kindText = { baseline: "run baseline", previous: "previous image" }[reference.kind] || "reference";
  const hasReference = !!reference.filename && !sameImage(reference, refFromDay(day));
  const vsReference = metricId === "pixel" ? (reference.kind === "baseline" ? "scored against it" : "–") : deltaText(metricId, refDay, day);
  return `<div class="assist-meta">
    <span>Time</span><b>${escapeHtml(formatUtc(day.capturedAtUtc))}</b>
    <span>File</span><b>${escapeHtml(day.filename)}</b>
    <span>Reference</span><b>${hasReference ? `${escapeHtml(kindText)} · ${escapeHtml(formatUtc(reference.capturedAtUtc))}` : "this image"}</b>
    <span>Δ vs reference</span><b>${escapeHtml(hasReference ? vsReference : "–")}</b>
    <span>Δ vs previous</span><b>${escapeHtml(deltaText(metricId, previousDay(day), day))}</b>
    ${contextRowsHtml(day)}
  </div>`;
}

function referenceChoiceHtml(day) {
  const modes = [["baseline", "Run baseline"], ["previous", "Previous image"]];
  return `<div class="assist-reference"><span class="ref-label">Judge against</span><div class="view-tabs" role="group" aria-label="Reference image">${modes.map(([id, text]) => `<button class="view-tab" data-ref-mode="${id}" aria-pressed="${referenceMode === id}" ${id === "previous" && days.findIndex((d) => d.code !== "M") === days.indexOf(day) ? "disabled" : ""}>${text}</button>`).join("")}</div></div>`;
}

function cameraStableHtml() {
  const options = [["yes", "Same view"], ["no", "Camera moved"], ["unsure", "Not sure"]];
  return `<div class="camera-row" role="group" aria-label="Did the camera view stay the same?">
    <span class="ref-label">Did the camera view stay the same?</span>
    <div class="view-tabs">${options.map(([value, text], index) => `<button class="view-tab" data-camera="${value}" aria-pressed="${draftCameraStable === value}"><kbd>${["s", "m", "u"][index]}</kbd> ${text}</button>`).join("")}</div>
  </div>`;
}

function panelHtml(day) {
  const canLabel = canReview(day);
  const own = reviewForCurrentReviewer(day);
  const earlierBlind = own && own.review_stage === "blind";
  const notice = earlierBlind
    ? `<div class="informed-banner">You labelled this image blind earlier. A label saved here is a separate informed revision; your blind label stays on record.</div>`
    : own
      ? `<div class="hint">You already labelled this image. Saving again adds a revision; the earlier one stays in the history.</div>`
      : "";
  return `<div class="focus-kicker">Machine reading · assist only</div>
    ${readoutHtml(day)}${metaHtml(day)}${referenceChoiceHtml(day)}
    <h2 class="panel-title">What changed between the images?</h2>${notice}
    <div class="label-choices" role="group" aria-label="Human label">${LABELS.map(([value, text, key]) => `<button class="label-choice" data-label="${value}" aria-pressed="${selectedLabel === value}"><kbd>${key}</kbd><span>${escapeHtml(text)}</span></button>`).join("")}</div>
    ${cameraStableHtml()}
    <div class="confidence-row"><span>Confidence</span>${["low", "medium", "high"].map((value) => `<button data-confidence="${value}" aria-pressed="${confidence === value}">${value}</button>`).join("")}</div>
    <label class="reviewer-field" for="reviewNote">Optional note</label><textarea id="reviewNote" rows="2" placeholder="What did you see in the pictures?">${escapeHtml(draftNote)}</textarea>
    <label class="reviewer-field" for="reviewerId">Reviewer code</label><input id="reviewerId" value="${escapeHtml(reviewerId)}" maxlength="80" placeholder="Example: reviewer-a" autocomplete="off">
    <div id="labelMessage" class="form-message" aria-live="polite"></div>
    <div class="assist-actions"><button class="btn primary confirm-label" data-save ${canLabel && !saving ? "" : "disabled"}>${saving ? "Saving…" : "Save & next"}</button><button class="btn" data-next-unreviewed ${nextUnreviewedIndex() < 0 ? "disabled" : ""}>Next unreviewed</button></div>
    <div class="shortcut-note">Keys: ← → step · 1–5 label · s/m/u camera · R swap reference · Ctrl/⌘+Enter save &amp; next</div>`;
}

// ---- dial ------------------------------------------------------------------------------------

let dialSeries = null;
let pos = 0;
let target = 0;
let vel = 0;
let dragging = false;
let lastX = 0;
let lastT = 0;
let raf = null;
let settleTimer = null;
let programmatic = false; // the dial is easing to an image chosen elsewhere, so it must not change the selection

function computeSeries() {
  const values = days.map((day) => metricValue(day, metricId));
  const present = values.filter((value) => value != null);
  let lo = present.length ? Math.min(...present) : 0;
  let hi = present.length ? Math.max(...present) : 1;
  if (metricId === "pixel") lo = Math.min(lo, 0);
  if (hi - lo < 1e-9) hi = lo + 1;
  const pad = (hi - lo) * 0.08;
  dialSeries = { values, lo: metricId === "pixel" ? lo : lo - pad, hi: hi + pad };
}

function dialColor(name) {
  const wrap = $("dial");
  return wrap ? getComputedStyle(wrap).getPropertyValue(name).trim() : "#888";
}

function sizeDial() {
  const wrap = $("dial");
  const canvas = $("dialCanvas");
  if (!wrap || !canvas) return;
  const rect = wrap.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * ratio));
  canvas.height = Math.max(1, Math.round(rect.height * ratio));
  canvas.getContext("2d").setTransform(ratio, 0, 0, ratio, 0, 0);
  drawDial();
}

function drawDial() {
  const canvas = $("dialCanvas");
  if (!canvas || !dialSeries || !days.length) return;
  const ctx = canvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  const W = canvas.width / ratio;
  const H = canvas.height / ratio;
  const mid = W / 2;
  const fg = dialColor("--dial-fg");
  const dim = dialColor("--dial-dim");
  const line = dialColor("--dial-line");
  const ok = dialColor("--dial-ok");
  const warn = dialColor("--dial-warn");
  const bad = dialColor("--dial-bad");
  const refColor = dialColor("--dial-ref");
  const needle = dialColor("--dial-needle");
  const bg = dialColor("--dial-bg");
  const base = H - 34;
  const { values, lo, hi } = dialSeries;
  const gy = (v) => base - ((v - lo) / (hi - lo)) * (base - 22);
  const xAt = (i) => mid + (i - pos) * STEP;
  const first = Math.max(0, Math.floor(pos - mid / STEP) - 1);
  const last = Math.min(days.length - 1, Math.ceil(pos + mid / STEP) + 1);
  ctx.clearRect(0, 0, W, H);

  // the line, broken wherever an image has no value
  let run = [];
  const flush = () => {
    if (run.length > 1) {
      ctx.beginPath();
      ctx.moveTo(xAt(run[0]), base);
      run.forEach((i) => ctx.lineTo(xAt(i), gy(values[i])));
      ctx.lineTo(xAt(run[run.length - 1]), base);
      ctx.closePath();
      ctx.fillStyle = line;
      ctx.globalAlpha = 0.14;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.beginPath();
      run.forEach((i, n) => (n ? ctx.lineTo(xAt(i), gy(values[i])) : ctx.moveTo(xAt(i), gy(values[i]))));
      ctx.strokeStyle = line;
      ctx.lineWidth = 2;
      ctx.stroke();
    }
    run = [];
  };
  for (let i = first; i <= last; i += 1) {
    if (values[i] == null) flush(); else run.push(i);
  }
  flush();

  // points: a draft water mask is hollow, like the chart on the Review page
  if (STEP >= 14) {
    for (let i = first; i <= last; i += 1) {
      if (values[i] == null) continue;
      const draft = metricId === "coverage" && (coverageRow(days[i]) || {}).basis !== "accepted";
      ctx.beginPath();
      ctx.arc(xAt(i), gy(values[i]), 3, 0, Math.PI * 2);
      ctx.fillStyle = draft ? bg : line;
      ctx.fill();
      ctx.strokeStyle = line;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
  }

  // ticks, dates, and the marks for reviewed and machine-flagged images
  ctx.font = "600 11px 'Fira Sans', system-ui, sans-serif";
  ctx.textAlign = "center";
  let lastLabelX = -1e9;
  for (let i = first; i <= last; i += 1) {
    const x = xAt(i);
    const day = days[i];
    const newDate = i === 0 || day.date !== days[i - 1].date;
    const fade = 1 - Math.min(1, Math.abs(x - mid) / (mid + 1)) * 0.65;
    ctx.globalAlpha = fade;
    ctx.fillStyle = marks[i] ? ok : day.code === "P" ? warn : day.code === "C" ? bad : newDate ? fg : dim;
    ctx.fillRect(Math.round(x) - 0.5, base + 6, 1.5, newDate ? 14 : 8);
    if (marks[i]) ctx.fillRect(Math.round(x) - 2.5, 6, 5, 5);
    if (day.code === "P" && !marks[i]) { ctx.beginPath(); ctx.arc(x, 8.5, 2.5, 0, Math.PI * 2); ctx.fill(); }
    if (newDate && x - lastLabelX > 46) {
      ctx.fillStyle = fg;
      ctx.fillText(shortDate(day.date), x, H - 4);
      lastLabelX = x;
    }
  }
  ctx.globalAlpha = 1;

  // the reference image
  const reference = days[selectedIndex] ? referenceFor(days[selectedIndex]) : null;
  const refIndex = reference ? days.findIndex((day) => day.filename === reference.filename) : -1;
  if (refIndex >= 0) {
    const x = xAt(refIndex);
    ctx.save();
    ctx.strokeStyle = refColor;
    ctx.fillStyle = refColor;
    ctx.setLineDash([3, 4]);
    ctx.beginPath(); ctx.moveTo(x, 16); ctx.lineTo(x, base + 4); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillText("Reference", Math.min(W - 30, Math.max(30, x)), 12);
    ctx.restore();
  }

  // needle
  ctx.fillStyle = needle;
  ctx.fillRect(mid - 1, 0, 2, H);
  ctx.beginPath(); ctx.moveTo(mid - 6, 0); ctx.lineTo(mid + 6, 0); ctx.lineTo(mid, 8); ctx.fill();

  // glass edges
  const edge = ctx.createLinearGradient(0, 0, W, 0);
  edge.addColorStop(0, bg);
  edge.addColorStop(0.12, "rgba(0,0,0,0)");
  edge.addColorStop(0.88, "rgba(0,0,0,0)");
  edge.addColorStop(1, bg);
  ctx.fillStyle = edge;
  ctx.fillRect(0, 0, W, H);

  const index = Math.round(pos);
  const info = $("dialInfo");
  if (info && days[index]) {
    const value = metricValue(days[index], metricId);
    info.textContent = `Image ${index + 1} · ${formatUtc(days[index].capturedAtUtc)} · ${value == null ? "no value" : `${formatMetric(metricId, value)}${metricUnit(metricId) ? ` ${metricUnit(metricId)}` : ""}`}`;
  }
}

function loop() {
  if (!dragging) {
    if (Math.abs(vel) > 0.02) { pos += vel; vel *= 0.92; target = Math.round(pos); }
    else { vel = 0; pos += (target - pos) * 0.25; }
    pos = Math.max(0, Math.min(days.length - 1, pos));
    const rounded = Math.round(pos);
    if (!programmatic && rounded !== selectedIndex) show(rounded, true);
    if (vel === 0 && Math.abs(target - pos) < 0.01) { pos = target; programmatic = false; drawDial(); raf = null; scheduleSettle(); return; }
  }
  drawDial();
  raf = requestAnimationFrame(loop);
}

function kick() {
  if (!raf) raf = requestAnimationFrame(loop);
}

function animateTo(index) {
  target = index;
  vel = 0;
  programmatic = true;
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) { pos = index; programmatic = false; drawDial(); scheduleSettle(); } else kick();
}

function wireDial() {
  const wrap = $("dial");
  if (!wrap) return;
  wrap.addEventListener("pointerdown", (event) => {
    dragging = true; programmatic = false; vel = 0; lastX = event.clientX; lastT = performance.now();
    wrap.setPointerCapture(event.pointerId);
    wrap.classList.add("drag");
    kick();
  });
  wrap.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const dx = event.clientX - lastX;
    const now = performance.now();
    pos = Math.max(0, Math.min(days.length - 1, pos - dx / STEP));
    vel = -(dx / STEP) / Math.max(1, (now - lastT) / 16);
    lastX = event.clientX; lastT = now;
    const rounded = Math.round(pos);
    if (rounded !== selectedIndex) show(rounded, true);
  });
  const end = () => {
    if (!dragging) return;
    dragging = false;
    wrap.classList.remove("drag");
    vel = Math.max(-3, Math.min(3, vel));
    if (Math.abs(vel) < 0.1) { vel = 0; target = Math.round(pos); }
    kick();
  };
  wrap.addEventListener("pointerup", end);
  wrap.addEventListener("pointercancel", end);
  // Only sideways scrolling moves the dial, so the page can still scroll up and down over it.
  wrap.addEventListener("wheel", (event) => {
    const sideways = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.shiftKey ? event.deltaY : 0;
    if (!sideways) return;
    event.preventDefault();
    pos = Math.max(0, Math.min(days.length - 1, pos + sideways / STEP / 2));
    target = Math.round(pos); vel = 0; programmatic = false;
    kick();
  }, { passive: false });
  if (window.ResizeObserver) new ResizeObserver(sizeDial).observe(wrap);
}

// ---- moving through the run ------------------------------------------------------------------

function resetDraftForDay(day) {
  const own = reviewForCurrentReviewer(day);
  selectedLabel = own && own.label ? own.label.human_label : null;
  confidence = own && own.label && own.label.confidence ? own.label.confidence : "medium";
  draftNote = own && own.label ? own.label.note || "" : "";
  draftCameraStable = own && own.label && own.label.camera_stable ? own.label.camera_stable : "";
  swapped = false;
  datasetResult = null;
  datasetCheck = null;
  datasetCheckKey = "";
  datasetMaskChoice = "";
}

function nextUnreviewedIndex() {
  for (let offset = 1; offset <= days.length; offset += 1) {
    const index = (selectedIndex + offset) % days.length;
    if (canReview(days[index]) && !reviewForCurrentReviewer(days[index])) return index;
  }
  return -1;
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

function renderViewer(quick) {
  const stage = $("assistViewer");
  if (!stage) return;
  stage.innerHTML = viewerHtml(days[selectedIndex], quick);
  quickShown = !!quick;
  stage.querySelectorAll(".assist-pane").forEach((pane) => {
    const image = pane.querySelector("img");
    const fit = () => { if (image.naturalWidth) pane.style.setProperty("--ar", `${image.naturalWidth} / ${image.naturalHeight}`); };
    image.addEventListener("load", fit);
    if (image.complete) fit();
  });
  wireViewer();
}

function renderToolbar() {
  const toolbar = $("assistToolbar");
  if (toolbar) { toolbar.innerHTML = toolbarHtml(); wireToolbar(); }
}

function renderPanel() {
  const panel = $("assistPanel");
  if (!panel) return;
  panel.innerHTML = panelHtml(days[selectedIndex]);
  wirePanel();
}

function renderHead() {
  const done = reviewedByCurrentCount();
  const total = reviewableCount();
  const text = $("assistProgress");
  if (text) text.innerHTML = `<strong>${done} of ${total}</strong> reviewed by ${escapeHtml(reviewerId || "this reviewer")}`;
  const bar = $("assistBar");
  if (bar) bar.style.width = `${total ? (100 * done) / total : 0}%`;
  const title = $("assistTitle");
  if (title) title.textContent = `${days[selectedIndex].date}, ${days[selectedIndex].time} local`;
}

function renderDialHead() {
  const tabs = $("dialMetrics");
  if (!tabs) return;
  const reviewable = days.filter((day) => day.code !== "M").length;
  tabs.innerHTML = METRICS.map((metric) => {
    const count = metricCount(metric.id);
    return `<button class="view-tab" data-metric="${metric.id}" aria-pressed="${metricId === metric.id}" title="${escapeHtml(metric.title)}" ${count ? "" : "disabled"}>${escapeHtml(metric.label)} <span class="tab-count">${count}/${reviewable}</span></button>`;
  }).join("");
  const legend = $("dialLegend");
  if (legend) {
    legend.innerHTML = `<span class="key line">${escapeHtml(metricSpec(metricId).title)}</span><span class="key ref">reference</span><span class="key ok">labelled by you</span><span class="key warn">machine: possible change</span>${metricId === "coverage" ? '<span class="key hollow">hollow: draft mask</span>' : ""}`;
  }
  tabs.querySelectorAll("[data-metric]").forEach((button) => button.addEventListener("click", () => {
    metricId = button.dataset.metric;
    computeSeries();
    renderDialHead();
    renderPanel();
    drawDial();
  }));
}

function syncUrl() {
  try {
    const url = new URL(location.href);
    url.searchParams.set("select", days[selectedIndex].filename);
    history.replaceState(null, "", url);
  } catch (error) { /* URL synchronization is optional. */ }
}

// While the dial is moving the viewer shows a small preview; once it stops, the full picture.
function scheduleSettle() {
  clearTimeout(settleTimer);
  settleTimer = setTimeout(() => {
    if (quickShown) renderViewer(false);
    syncUrl();
    refreshDatasetCheck(days[selectedIndex]);
  }, 140);
}

function show(index, fromDial) {
  const next = Math.max(0, Math.min(index, days.length - 1));
  const changed = next !== selectedIndex || !fromDial;
  selectedIndex = next;
  if (changed) resetDraftForDay(days[selectedIndex]);
  if (!fromDial) renderToolbar();
  renderViewer(!!fromDial);
  renderPanel();
  renderDataset();
  renderHead();
  if (fromDial) scheduleSettle(); else { syncUrl(); animateTo(selectedIndex); }
}

// ---- datasets --------------------------------------------------------------------------------
// The same eligibility check and add calls as Blind review. Labels saved on this page are informed,
// so the visible-change task will refuse them; the reasons are shown before anything is added.

function selectedDataset() {
  return datasets.find((dataset) => dataset.dataset_id === selectedDatasetId) || null;
}

function acceptedMasks(day) {
  return samResults.filter((result) => result.filename === day.filename && result.status === "completed" && result.review_status === "accepted" && ["river water", "water"].includes(result.prompt));
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
    const first = acceptedMasks(day)[0];
    const choice = datasetMaskChoice || (first ? `${first.run_id}|${first.result_id}` : "");
    if (choice) [body.mask_run_id, body.mask_result_id] = choice.split("|");
  }
  return { dataset, pair: false, body };
}

async function postDataset(path, body) {
  const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok && !(response.status === 409 && data.conflict)) return { error: data.message || "Could not update the dataset." };
  return data;
}

async function refreshDatasetCheck(day) {
  if (!day || !canReview(day)) return;
  const request = datasetRequest(day);
  if (!request) { datasetCheck = null; datasetCheckKey = ""; return; }
  const key = JSON.stringify(request.body);
  if (key === datasetCheckKey) return;
  datasetCheckKey = key;
  datasetCheck = { pending: true };
  renderDataset();
  try {
    const result = await postDataset("/api/dataset-check", request.body);
    if (datasetCheckKey !== key) return;
    datasetCheck = result.error ? { error: result.error } : result;
  } catch (error) {
    if (datasetCheckKey !== key) return;
    datasetCheck = { error: error.message };
  }
  renderDataset();
}

async function addToDataset(day) {
  const request = datasetRequest(day);
  if (!request) return;
  savingDataset = true;
  renderDataset();
  try {
    datasetResult = await postDataset(request.pair ? "/api/dataset-add-pair" : "/api/dataset-add", request.body);
    datasets = (await api("/api/datasets")).datasets || datasets;
  } catch (error) { datasetResult = { error: error.message }; }
  savingDataset = false;
  datasetCheckKey = ""; // re-check: it is now already included
  renderDataset();
  refreshDatasetCheck(day);
}

function reasonListHtml(reasons) {
  const items = (reasons || []).map((reason) => `<li class="${reason.severity === "warning" ? "reason-warning" : ""}">${escapeHtml(reason.message)}</li>`).join("");
  return items ? `<ul>${items}</ul>` : "";
}

function agreementLineHtml(agreement) {
  if (!agreement) return "";
  const directions = Object.entries(agreement.by_direction || {}).map(([direction, who]) => `${direction.replaceAll("_", " ")}: ${who.join(", ")}`).join(" · ");
  return `<div class="dataset-agreement">${agreement.reviewers} of ${agreement.needed} needed independent blind reviewers${directions ? ` · ${escapeHtml(directions)}` : ""}</div>`;
}

// What to do next for the reasons that a person can fix, with a link to the page that does it.
function nextStepHtml(reasons) {
  const codes = (reasons || []).map((reason) => reason.code || "");
  const day = days[selectedIndex];
  if (codes.includes("needs_more_reviewers")) {
    return `<div class="dataset-next">A pair needs two different reviewers who judged it <strong>blind</strong>. Labels saved on this page do not count. <a href="${blindHref(day.filename)}">Label this image in Blind review</a>, then have a second reviewer do the same.</div>`;
  }
  if (codes.some((code) => code.startsWith("mask_"))) {
    const href = `/console/review.html?${new URLSearchParams({ site: folderName, run_id: runId, select: day.filename })}`;
    return `<div class="dataset-next">A person has to accept a water mask for this image first. <a href="${href}">Open the detailed review page</a> to run segmentation and accept the mask.</div>`;
  }
  return "";
}

function datasetCheckHtml() {
  if (!datasetCheck) return "";
  if (datasetCheck.pending) return `<div class="dataset-result">Checking eligibility…</div>`;
  if (datasetCheck.error) return `<div class="error-note mt-10">${escapeHtml(datasetCheck.error)}</div>`;
  const status = datasetCheck.status;
  const title = status === "eligible" ? "Eligible: nothing has been added yet" : status === "already_included" ? "Already in this dataset" : "Not eligible for this dataset";
  return `<div class="dataset-result ${status === "eligible" ? "ok" : status === "ineligible" ? "bad" : ""}"><strong>${title}</strong>${agreementLineHtml(datasetCheck.agreement)}${reasonListHtml(datasetCheck.reasons)}${status === "ineligible" ? nextStepHtml(datasetCheck.reasons) : ""}</div>`;
}

function datasetResultHtml() {
  if (!datasetResult) return "";
  if (datasetResult.error) return `<div class="error-note mt-10">${escapeHtml(datasetResult.error)}</div>`;
  const title = datasetResult.status === "ineligible" ? "Not eligible for this dataset" : datasetResult.message || `Dataset: ${datasetResult.status || "updated"}`;
  return `<div class="dataset-result"><strong>${escapeHtml(title)}</strong>${reasonListHtml(datasetResult.reasons)}</div>`;
}

function datasetPanelHtml(day) {
  const head = `<h3>Add to dataset</h3><div class="hint">Nothing is trained, uploaded, or published.</div>`;
  if (!datasets.length) {
    return `<div class="curation-block">${head}<div class="hint">No dataset drafts exist yet. Create one on the <a href="/console/datasets.html">Datasets page</a> or in <a href="${blindHref(day.filename)}">Blind review</a>.</div></div>`;
  }
  const dataset = selectedDataset();
  const isPair = !!dataset && PAIR_TASK_IDS.includes(dataset.task);
  const pair = isPair ? orderedPair(day) : null;
  const masks = dataset && dataset.task === "water_segmentation" ? acceptedMasks(day) : [];
  const maskSelect = masks.length ? `<label>Accepted mask<select id="datasetMask">${masks.map((mask) => `<option value="${escapeHtml(mask.run_id)}|${escapeHtml(mask.result_id)}" ${datasetMaskChoice === `${mask.run_id}|${mask.result_id}` ? "selected" : ""}>${escapeHtml(mask.prompt)} · ${escapeHtml(formatUtc(mask.processed_at_utc))}</option>`).join("")}</select></label>` : "";
  const pairNote = pair ? `<div class="dataset-pair">Pair, earlier first: ${escapeHtml(formatUtc(pair.earlier.capturedAtUtc))} → ${escapeHtml(formatUtc(pair.later.capturedAtUtc))}</div>` : "";
  const eligible = datasetCheck && datasetCheck.status === "eligible";
  const label = savingDataset ? "Adding…" : isPair ? "Add pair to dataset" : "Add to dataset";
  const options = datasets.map((candidate) => `<option value="${escapeHtml(candidate.dataset_id)}" ${candidate.dataset_id === selectedDatasetId ? "selected" : ""}>${escapeHtml(candidate.name)} · ${escapeHtml(candidate.task_title)}</option>`).join("");
  return `<div class="curation-block">${head}<label for="datasetSelect">Dataset</label><select id="datasetSelect">${options}</select>
    <div class="hint">${escapeHtml(DATASET_HELP[(dataset || {}).task] || "")}</div>${maskSelect}${pairNote}${canReview(day) ? datasetCheckHtml() : `<div class="hint">This image is the reference, so it cannot be added on its own.</div>`}
    <button class="btn primary" data-add-dataset ${savingDataset || !eligible ? "disabled" : ""}>${label}</button>${datasetResultHtml()}</div>`;
}

function renderDataset() {
  const box = $("assistDataset");
  if (!box || !days.length) return;
  const day = days[selectedIndex];
  box.innerHTML = datasetPanelHtml(day);
  const select = $("datasetSelect");
  if (select) select.addEventListener("change", () => {
    selectedDatasetId = select.value;
    datasetResult = null; datasetCheck = null; datasetCheckKey = "";
    saveSetting("openfloodai.reviewDataset", selectedDatasetId);
    renderDataset();
    refreshDatasetCheck(day);
  });
  const mask = $("datasetMask");
  if (mask) mask.addEventListener("change", () => { datasetMaskChoice = mask.value; datasetCheckKey = ""; renderDataset(); refreshDatasetCheck(day); });
  const add = box.querySelector("[data-add-dataset]");
  if (add) add.addEventListener("click", () => addToDataset(day));
}

async function reviewMask(button) {
  savingMask = true;
  renderViewer(false);
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
  computeSeries();
  renderDialHead();
  renderViewer(false);
  renderPanel();
  renderDataset();
  drawDial();
  refreshDatasetCheck(days[selectedIndex]);
}

// ---- saving ----------------------------------------------------------------------------------

async function refreshReviewData() {
  const workspace = await api(`/api/workspace-evidence?${new URLSearchParams({ folder_name: folderName, kind: "image", run_id: runId, media_id: detail.summary.sequence_id })}`);
  evidencePoints = workspace.points || [];
  refreshMarks();
}

async function saveLabel(advance) {
  const day = days[selectedIndex];
  const message = $("labelMessage");
  const say = (text) => { if (message) message.textContent = text; };
  const reviewerInput = $("reviewerId");
  reviewerId = String((reviewerInput && reviewerInput.value) || reviewerId || "").trim();
  if (!reviewerId) { say("Enter a reviewer code before saving."); return; }
  if (!selectedLabel) { say("Choose what changed before saving."); return; }
  if (!UNJUDGED_LABELS.includes(selectedLabel) && !draftCameraStable) {
    say("Say whether the camera view stayed the same. A moved camera looks like a water change.");
    return;
  }
  const point = pointFor(day);
  if (!point || !canReview(day)) { say("This image cannot be labelled against that reference."); return; }
  const reference = referenceFor(day);
  saving = true;
  saveSetting("openfloodai.reviewerId", reviewerId);
  renderPanel();
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
      review_stage: "informed",
      reference: referencePayload(reference),
      note: draftNote.trim(),
      ...(draftCameraStable ? { camera_stable: draftCameraStable } : {})
    });
    await refreshReviewData();
    saved = true;
    toast("Saved as an informed label. It is not counted as an independent judgment.");
  } catch (error) { toast(error.message); }
  saving = false;
  datasetCheckKey = ""; // a saved label can change eligibility
  renderHead();
  drawDial();
  if (saved && advance && selectedIndex < days.length - 1) { show(selectedIndex + 1); return; }
  if (saved) resetDraftForDay(day);
  renderPanel();
  renderDataset();
  refreshDatasetCheck(day);
}

// ---- wiring ----------------------------------------------------------------------------------

function applyZoom(value) {
  zoom = value;
  document.querySelectorAll(".assist-pane").forEach((pane) => pane.classList.toggle("zoomed", zoom > 1));
  document.querySelectorAll(".assist-layer").forEach((layer) => { layer.style.width = `${zoom * 100}%`; });
}

function applyOpacity(value) {
  overlayOpacity = value;
  document.querySelectorAll(".assist-overlay-current").forEach((layer) => { layer.style.opacity = String(overlayOpacity / 100); });
  const chip = $("overlayChip");
  if (chip) chip.textContent = `Current ${overlayOpacity}%`;
}

let panDrag = null;
let syncingPanes = false;

// One pair of window listeners for dragging a zoomed picture, however often the viewer is redrawn.
function wirePanOnce() {
  if (wirePanOnce.done) return;
  wirePanOnce.done = true;
  window.addEventListener("mousemove", (event) => {
    if (!panDrag) return;
    panDrag.pane.scrollLeft = panDrag.left - (event.clientX - panDrag.x);
    panDrag.pane.scrollTop = panDrag.top - (event.clientY - panDrag.y);
  });
  window.addEventListener("mouseup", () => {
    if (panDrag) panDrag.pane.classList.remove("panning");
    panDrag = null;
  });
}

function wireViewer() {
  wirePanOnce();
  document.querySelectorAll("#assistViewer [data-step]").forEach((button) => button.addEventListener("click", () => show(selectedIndex + Number(button.dataset.step))));
  document.querySelectorAll("#assistViewer [data-mask-decision]").forEach((button) => button.addEventListener("click", () => reviewMask(button)));
  document.querySelectorAll("#assistViewer [data-swap]").forEach((button) => button.addEventListener("click", () => { swapped = !swapped; renderViewer(false); }));
  const panes = [...document.querySelectorAll("#assistViewer .assist-pane")];
  panes.forEach((pane) => pane.addEventListener("mousedown", (event) => {
    if (zoom <= 1 || event.button !== 0) return;
    panDrag = { pane, x: event.clientX, y: event.clientY, left: pane.scrollLeft, top: pane.scrollTop };
    pane.classList.add("panning");
    event.preventDefault();
  }));
  // Side by side: both pictures scroll together so the same spot is compared.
  document.querySelectorAll("#assistViewer [data-pan-group]").forEach((group) => {
    const members = [...group.querySelectorAll(".assist-pane")];
    members.forEach((pane) => pane.addEventListener("scroll", () => {
      if (syncingPanes) return;
      syncingPanes = true;
      members.forEach((other) => { if (other !== pane) { other.scrollLeft = pane.scrollLeft; other.scrollTop = pane.scrollTop; } });
      syncingPanes = false;
    }));
  });
}

function wireToolbar() {
  document.querySelectorAll("#assistToolbar [data-view]").forEach((button) => button.addEventListener("click", () => {
    viewMode = button.dataset.view;
    renderToolbar();
    renderViewer(false);
  }));
  // Updated in place: redrawing the page on every move would replace the slider under the pointer.
  document.querySelectorAll("#assistToolbar [data-compare]").forEach((button) => button.addEventListener("click", () => {
    compareMode = button.dataset.compare;
    renderToolbar();
    renderViewer(false);
  }));
  const zoomControl = $("zoomControl");
  if (zoomControl) zoomControl.addEventListener("input", () => applyZoom(Number(zoomControl.value)));
  const opacityControl = $("opacityControl");
  if (opacityControl) opacityControl.addEventListener("input", () => applyOpacity(Number(opacityControl.value)));
}

function wirePanel() {
  const on = (selector, handler) => document.querySelectorAll(`#assistPanel ${selector}`).forEach((el) => el.addEventListener("click", () => handler(el)));
  on("[data-label]", (button) => { selectedLabel = button.dataset.label; renderPanel(); });
  on("[data-camera]", (button) => { draftCameraStable = button.dataset.camera; renderPanel(); });
  on("[data-confidence]", (button) => { confidence = button.dataset.confidence; renderPanel(); });
  on("[data-ref-mode]", (button) => {
    referenceMode = button.dataset.refMode;
    refreshMarks();
    resetDraftForDay(days[selectedIndex]);
    renderViewer(false);
    renderPanel();
    renderDataset();
    renderHead();
    drawDial();
    refreshDatasetCheck(days[selectedIndex]);
  });
  on("[data-save]", () => saveLabel(true));
  on("[data-next-unreviewed]", () => { const index = nextUnreviewedIndex(); if (index >= 0) show(index); });
  const noteInput = $("reviewNote");
  if (noteInput) noteInput.addEventListener("input", () => { draftNote = noteInput.value; });
  const reviewerInput = $("reviewerId");
  if (reviewerInput) {
    reviewerInput.addEventListener("input", () => { reviewerId = reviewerInput.value; });
    reviewerInput.addEventListener("change", () => {
      reviewerId = reviewerInput.value.trim();
      saveSetting("openfloodai.reviewerId", reviewerId);
      loadRevealed();
      refreshMarks();
      render();
    });
  }
}

// ---- page ------------------------------------------------------------------------------------

function gateHtml() {
  return `<section class="card assist-gate" aria-label="Before assisted review">
    <div class="focus-kicker">Assisted review</div>
    <h1 class="focus-title">Machine results are shown for every image in this run</h1>
    <p class="hint">The timeline plots the machine result of each image, so opening this page reveals them. Images you have not labelled blind yet will count as <strong>informed</strong> for you afterwards, and informed labels are not used as independent judgments in datasets. If you still need independent labels, do those in Blind review first.</p>
    <label class="reviewer-field" for="gateReviewer">Reviewer code</label>
    <input id="gateReviewer" value="${escapeHtml(reviewerId)}" maxlength="80" placeholder="Example: reviewer-a" autocomplete="off">
    <div class="field-help">Use a short team code, not a full personal name.</div>
    <div id="gateMessage" class="form-message" aria-live="polite"></div>
    <div class="hidden-actions"><button class="btn primary" data-start>Start assisted review</button><a class="btn" href="${blindHref()}">Go to Blind review</a></div>
  </section>`;
}

function blindHref(select) {
  return `/console/review-focus.html?${new URLSearchParams({ site: folderName, run_id: runId, ...(select ? { select } : {}) })}`;
}

function renderGate() {
  $("content").innerHTML = gateHtml();
  const start = document.querySelector("[data-start]");
  start.addEventListener("click", () => {
    const code = String(($("gateReviewer") || {}).value || "").trim();
    if (!code) { $("gateMessage").textContent = "Enter a reviewer code to continue."; return; }
    reviewerId = code;
    saveSetting("openfloodai.reviewerId", reviewerId);
    loadRevealed();
    markAllRevealed();
    refreshMarks();
    selectedIndex = chooseInitialIndex();
    resetDraftForDay(days[selectedIndex]);
    render();
  });
}

function render() {
  if (needsGate()) { renderGate(); return; }
  const fullReview = `/console/review.html?${new URLSearchParams({ site: folderName, run_id: runId, select: days[selectedIndex].filename })}`;
  $("content").innerHTML = `<div class="focus-head"><div><div class="focus-kicker">Assisted review</div><h1 class="focus-title" id="assistTitle"></h1></div>
      <div class="focus-progress"><span id="assistProgress"></span><div class="assist-bar"><i id="assistBar"></i></div></div></div>
    <div class="assist-banner"><strong>Machine evidence is visible.</strong><span>Labels saved here are recorded as informed, not as independent judgments. For independent labels use <a href="${blindHref(days[selectedIndex].filename)}">Blind review</a>. Open the <a href="${fullReview}">detailed review page</a> for masks and datasets.</span></div>
    <div class="assist-layout">
      <div class="assist-left">
      <section class="card assist-stage" aria-label="Image viewer"><div class="evidence-toolbar" id="assistToolbar"></div><div id="assistViewer"></div></section>
    <section class="card assist-dial-card" aria-label="Timeline">
      <div class="assist-dial-head"><span id="dialInfo" class="assist-dial-info"></span><div class="view-tabs" id="dialMetrics" role="group" aria-label="Timeline measurement"></div></div>
      <div class="assist-dial-legend" id="dialLegend"></div>
      <div class="dialwrap" id="dial" tabindex="0" role="slider" aria-label="Timeline of images. Drag sideways, or use the arrow keys." aria-valuemin="1" aria-valuemax="${days.length}" aria-valuenow="${selectedIndex + 1}"><canvas id="dialCanvas"></canvas></div>
    </section>
      </div>
      <div class="assist-right">
        <aside class="card assist-panel" id="assistPanel" aria-label="Machine reading and human label"></aside>
        <section class="card assist-dataset" id="assistDataset" aria-label="Add to dataset"></section>
      </div>
    </div>`;
  renderToolbar();
  renderDialHead();
  computeSeries();
  wireDial();
  pos = target = selectedIndex;
  renderViewer(false);
  renderPanel();
  renderDataset();
  renderHead();
  sizeDial();
  refreshDatasetCheck(days[selectedIndex]);
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
      { label: "Assisted review" }
    ]
  });
  content.innerHTML = '<div class="card empty-note">Loading assisted review&hellip;</div>';
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
    refreshMarks();
    selectedIndex = chooseInitialIndex();
    resetDraftForDay(days[selectedIndex]);
    $("topbarActions").innerHTML = `<a class="btn" href="${blindHref()}">Blind review</a><a class="btn" href="/console/review.html?${new URLSearchParams({ site: folderName, run_id: runId })}">Detailed review</a>`;
    render();
  } catch (error) {
    content.innerHTML = `<div class="card error-note">Could not load this review: ${escapeHtml(error.message)}</div>`;
  }
}

document.addEventListener("keydown", (event) => {
  if (!days.length || needsGate() || event.altKey) return;
  const target = event.target;
  const typing = target && (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable);
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); saveLabel(true); return; }
  if (typing || event.ctrlKey || event.metaKey || event.shiftKey) return;
  const label = LABELS.find(([, , key]) => key === event.key);
  if (label) { event.preventDefault(); selectedLabel = label[0]; renderPanel(); return; }
  const camera = { s: "yes", m: "no", u: "unsure" }[event.key];
  if (camera) { event.preventDefault(); draftCameraStable = camera; renderPanel(); return; }
  if ((event.key === "r" || event.key === "R") && compareMode === "single") { event.preventDefault(); swapped = !swapped; renderViewer(false); return; }
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    show(selectedIndex + (event.key === "ArrowRight" ? 1 : -1));
  }
});

main();
