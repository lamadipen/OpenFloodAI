// Review page: overlay (onion-skin) comparison of the baseline and the selected image.

// ---- overlay comparison ----------------------------------------------------
// Onion-skin view: the baseline underneath, the selected image on top at an
// adjustable opacity, with the run's own saved watched area and guides drawn in
// the same frame. Nothing here changes the baseline, a guide, or any run.
let onion = { opacity: 50, area: true, guides: true };

function onionSvgHtml() {
  const setup = (detail && detail.setup_used) || {};
  const region = setup.reference_region;
  const parts = [];
  if (onion.area && region && [region.x, region.y, region.width, region.height].every((n) => typeof n === "number")) {
    parts.push(`<rect x="${region.x}" y="${region.y}" width="${region.width}" height="${region.height}" fill="none" stroke="#ffffff" stroke-width="0.6" vector-effect="non-scaling-stroke"/>`);
  }
  if (onion.guides) {
    (setup.normal_waterline_guides || []).filter((g) => g.status !== "invalid" && Array.isArray(g.points) && g.points.length > 1).forEach((g) => {
      const pts = g.points.map((p) => `${p.x},${p.y}`).join(" ");
      parts.push(`<polyline points="${pts}" fill="none" stroke="#28dc28" stroke-width="2" vector-effect="non-scaling-stroke"/>`);
    });
  }
  return `<svg viewBox="0 0 100 100" preserveAspectRatio="none" style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none;">${parts.join("")}</svg>`;
}

function onionHtml(baselineQuery, selectedQuery) {
  if (!baselineQuery || !selectedQuery) return `<div class="hint">Overlay needs a baseline and a saved image for this day.</div>`;
  return `<div id="onionBox">
    <div style="position:relative;border-radius:8px;overflow:hidden;background:#000;">
      <img id="onionBase" src="/api/image-sequence-image?${baselineQuery}" style="width:100%;display:block;" alt="Baseline image">
      <img id="onionTop" src="/api/image-sequence-image?${selectedQuery}" style="position:absolute;inset:0;width:100%;height:100%;object-fit:fill;opacity:${onion.opacity / 100};" alt="Selected image over the baseline">
      <span id="onionOverlaySvg">${onionSvgHtml()}</span>
    </div>
    <div style="display:flex;align-items:center;gap:10px;margin-top:8px;font-size:12px;flex-wrap:wrap;">
      <span>Baseline</span>
      <input id="onionSlider" type="range" min="0" max="100" value="${onion.opacity}" aria-label="Opacity of the selected image" style="flex:1;min-width:140px;">
      <span>Selected image <strong id="onionPercent">${onion.opacity}%</strong></span>
      <label><input type="checkbox" id="onionArea" ${onion.area ? "checked" : ""}> Watched area</label>
      <label><input type="checkbox" id="onionGuides" ${onion.guides ? "checked" : ""}> Riverbank guides</label>
    </div>
    <div id="onionWarning" class="hint" style="margin-top:6px;line-height:1.5;">This view assumes the camera did not move between the two images. If the landmarks do not line up, the watched area and guides do not apply to this view; set them up again instead of reusing them. A visual overlay is not a measured water height.</div>
  </div>`;
}

function wireOnion() {
  const slider = $("onionSlider");
  if (!slider) return;
  slider.addEventListener("input", () => {
    onion.opacity = Number(slider.value);
    $("onionTop").style.opacity = String(onion.opacity / 100);
    $("onionPercent").textContent = `${onion.opacity}%`;
  });
  [["onionArea", "area"], ["onionGuides", "guides"]].forEach(([id, key]) => {
    $(id).addEventListener("change", () => {
      onion[key] = $(id).checked;
      $("onionOverlaySvg").innerHTML = onionSvgHtml();
    });
  });
  const check = () => {
    const base = $("onionBase");
    const top = $("onionTop");
    if (base && top && base.naturalWidth && top.naturalWidth && (base.naturalWidth !== top.naturalWidth || base.naturalHeight !== top.naturalHeight)) {
      $("onionWarning").innerHTML = "<strong>These two images have different sizes, so they cannot be assumed to line up.</strong> Do not read this overlay as aligned.";
    }
  };
  $("onionBase").addEventListener("load", check);
  $("onionTop").addEventListener("load", check);
  check();
}
// ---- end overlay comparison ----
