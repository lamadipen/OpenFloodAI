// Review page: the gauge and region-change charts, bucketing, and the selected-point marks.

// ---- chart metrics ----------------------------------------------------------------------------
// The second chart plots one number per image over time. Two choices:
//  - Pixel appearance change: how different the watched area looks from the baseline (the original).
//  - Water coverage: how much of the watched area the segmentation marks as water in that image.
// Water coverage comes from /api/compare/series. Filled points use a mask a reviewer accepted;
// hollow points use an unreviewed draft. An image with no usable mask has no point (never zero),
// and the two numbers are never combined.
const CHART_METRICS = [
  { id: "pixel", label: "Pixel appearance change", title: "Region change score" },
  { id: "coverage", label: "Segmentation: water coverage", title: "Water coverage of the watched area (%)" }
];

function currentMetric() {
  return CHART_METRICS.find((m) => m.id === state.metric) || CHART_METRICS[0];
}

function segRow(day) {
  return day && segByFile ? segByFile.get(day.filename) || null : null;
}

// One image's water coverage in percent, or null when it has no usable mask.
function segValueFor(day, id) {
  const row = segRow(day);
  if (!row || id !== "coverage" || row.coverage == null) return null;
  const value = row.coverage * 100;
  return Number.isFinite(value) ? value : null;
}

function metricValueCount(id) {
  if (id === "pixel") return days.filter((d) => d.score != null).length;
  return days.filter((d) => segValueFor(d, id) != null).length;
}

function bucketMetricValue(bucket, spec) {
  if (spec.id === "pixel") return bucket.meanScore;
  const values = bucket.indices.map((i) => segValueFor(days[i], spec.id)).filter((v) => v != null);
  return values.length ? isoMean(values) : null;
}

// A point is hollow when every image behind it is measured from an unreviewed draft mask.
function bucketIsDraft(bucket) {
  const rows = bucket.indices.map((i) => segRow(days[i])).filter((r) => r && r.coverage != null);
  return rows.length > 0 && rows.every((r) => r.basis === "draft");
}

function niceMax(value) {
  const steps = [1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100];
  return steps.find((n) => n >= value) || Math.ceil(value / 10) * 10;
}

function metricScale(spec, values) {
  if (spec.id === "pixel") {
    const max = Math.max(0.1, Math.ceil(Math.max(...values) * 100) / 100 + 0.02);
    return { min: 0, max, ticks: [max, max / 2, 0], fmt: (v) => (v === 0 ? "0" : v.toFixed(2)) };
  }
  const max = Math.min(100, niceMax(Math.max(5, Math.max(...values) * 1.1)));
  return { min: 0, max, ticks: [max, max / 2, 0], fmt: (v) => `${Number(v.toFixed(1))}%` };
}

function metricValueText(spec, v) {
  return spec.id === "pixel" ? `score ${v.toFixed(3)}` : `${v.toFixed(1)}% of the watched area is water`;
}

function metricEmptyHtml(spec) {
  const seg = typeof segSeries !== "undefined" ? segSeries : null;
  if (spec.id === "pixel") return `<div class="hint">No scores available.</div>`;
  if (!seg) return `<div class="hint">Segmentation values could not be loaded for this run.</div>`;
  return `<div class="hint">No image in this run has a usable water mask yet, so there is nothing to plot. Run segmentation (the checkbox beside Run validation, or the panel below the images) and the points appear here, hollow until you accept each mask. Nothing is estimated from the pixel score.</div>`;
}

function chartMetricSwitchHtml() {
  const spec = currentMetric();
  const explain = spec.id === "pixel"
    ? "How different each image looks from the baseline image, from pixel brightness. Anything that changes the picture raises it: water, light, shadow, snow or a moved camera."
    : "For each image: the share of your watched area that the segmentation marks as water. A higher point means more of the watched area is water in that picture. It is a measurement of the image, not water depth or flow.";
  return `<div role="group" aria-label="Chart measurement" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:6px;">
    <span class="hint">Measurement</span>
    ${CHART_METRICS.map((m) => {
      const active = state.metric === m.id;
      const note = m.id === "pixel" ? "" : ` <span style="font-weight:400;opacity:.75;">(${metricValueCount(m.id)}/${days.filter((d) => d.code !== "M").length})</span>`;
      return `<button class="btn${active ? " primary" : ""}" aria-pressed="${active}" data-act="chart-metric" data-value="${m.id}" style="font-size:12px;padding:5px 12px;">${escapeHtml(m.label)}${note}</button>`;
    }).join("")}
  </div>
  <div class="hint" style="margin-bottom:10px;line-height:1.5;">${escapeHtml(explain)}</div>`;
}

function chartTitleText() {
  return currentMetric().title;
}
// ---- end chart metrics ----

function currentBuckets() {
  return buildBuckets(days, state.granularity).map((b) => summarizeBucket(b, days));
}

function assignBucketX(buckets, leftPad) {
  const usableW = 1040 - leftPad;
  const n = buckets.length;
  buckets.forEach((b, i) => {
    b.x = n <= 1 ? leftPad + usableW / 2 : leftPad + (i / (n - 1)) * usableW;
  });
  return buckets;
}

// ---- Making the selected chart point obvious --------------------------------------------
// The selected point gets a column highlight and guide line through the chart, a larger dot with
// a dark ring, and a tag naming the day and value. Both charts draw the same marks, so the
// selection reads the same in each. Hovering any point enlarges it and shows its details.
function bucketIsSelected(bucket) {
  return bucket.indices.includes(state.selectedIndex);
}

function pointTitle(bucket, valueText) {
  const day = days[bucket.indices.includes(state.selectedIndex) ? state.selectedIndex : bucket.repIndex] || {};
  const when = `${day.date || ""}${day.time ? " " + day.time : ""}`.trim();
  const count = bucket.dayCount > 1 ? ` (${bucket.dayCount} images, one shown)` : "";
  return `${when}${valueText ? " \u00b7 " + valueText : ""}${count}`;
}

function selectionBackdropSvg(x, top, bottom) {
  return `<rect x="${(x - 9).toFixed(1)}" y="${top}" width="18" height="${(bottom - top).toFixed(1)}" fill="var(--accent)" opacity="0.10" pointer-events="none"/>
    <line x1="${x.toFixed(1)}" y1="${top}" x2="${x.toFixed(1)}" y2="${bottom}" stroke="var(--accent)" stroke-width="1.5" opacity="0.65" pointer-events="none"/>`;
}

function selectionMarkerSvg(x, y, r, tag, top, minX, maxX) {
  const width = Math.max(60, tag.length * 6.3 + 14);
  const left = Math.min(Math.max(x - width / 2, minX), maxX - width);
  const above = y - r - 30 >= top;
  const tagY = above ? y - r - 27 : y + r + 9;
  return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r + 5}" fill="#fff" opacity="0.9" pointer-events="none"/>
    <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r + 5}" fill="none" stroke="#1d2433" stroke-width="2.5" pointer-events="none"/>
    <g pointer-events="none">
      <rect x="${left.toFixed(1)}" y="${tagY.toFixed(1)}" width="${width.toFixed(1)}" height="19" rx="9.5" fill="#1d2433"/>
      <text x="${(left + width / 2).toFixed(1)}" y="${(tagY + 13).toFixed(1)}" font-size="11" font-weight="600" fill="#fff" text-anchor="middle">${escapeHtml(tag)}</text>
    </g>`;
}

function scoreChartSvg() {
  const spec = currentMetric();
  const pixel = spec.id === "pixel";
  const daily = state.granularity === "daily";
  const leftPad = pixel ? 34 : 46;
  const topY = 4;
  const chartH = 178;
  const bottomY = topY + chartH;
  const buckets = assignBucketX(currentBuckets(), leftPad);
  buckets.forEach((b) => { b.metric = bucketMetricValue(b, spec); });
  const points = buckets.map((b, i) => ({ b, i, v: b.metric })).filter((p) => p.v != null);
  if (!points.length) return metricEmptyHtml(spec);
  const scale = metricScale(spec, points.map((p) => p.v));
  const y = (value) => topY + chartH - ((Math.max(scale.min, Math.min(scale.max, value)) - scale.min) / (scale.max - scale.min)) * chartH;
  const dotColor = (p) => (pixel ? p.b.color : "#1769aa");
  // Draft (unreviewed) mask points are hollow so they are never mistaken for accepted ones.
  const dotFill = (p) => (!pixel && bucketIsDraft(p.b) ? "#fff" : dotColor(p));
  const dotStroke = (p, selected) => (selected ? "#1d2433" : !pixel && bucketIsDraft(p.b) ? "#1769aa" : "#fff");

  const segments = [];
  let seg = [];
  buckets.forEach((b) => {
    if (b.metric == null) {
      if (seg.length) {
        segments.push(seg.join(" "));
        seg = [];
      }
    } else {
      seg.push(`${b.x.toFixed(1)},${y(b.metric).toFixed(1)}`);
    }
  });
  if (seg.length) segments.push(seg.join(" "));

  const selectedPoint = points.find((p) => bucketIsSelected(p.b));
  const dots = points
    .map((p) => {
      const selected = p === selectedPoint;
      const r = daily ? (selected ? 6 : 3.5) : Math.min(9, 4 + p.b.dayCount / 4) + (selected ? 2 : 0);
      const title = pointTitle(p.b, metricValueText(spec, p.v));
      return `<circle class="chart-point" cx="${p.b.x.toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="${r}" fill="${dotFill(p)}" stroke="${dotStroke(p, selected)}" stroke-width="${selected ? 2.5 : !pixel && bucketIsDraft(p.b) ? 1.6 : 1}" data-act="select-day" data-index="${p.b.repIndex}" role="button" tabindex="0" aria-label="${escapeHtml(title)}" aria-pressed="${selected}" style="cursor:pointer;"><title>${escapeHtml(title)}</title></circle>${labelledRingSvg(p.b, p.b.x.toFixed(1), y(p.v).toFixed(1), r)}${samRingSvg(p.b, p.b.x.toFixed(1), y(p.v).toFixed(1), r)}`;
    })
    .join("");
  const backdrop = selectedPoint ? selectionBackdropSvg(selectedPoint.b.x, topY, bottomY) : "";
  const marker = selectedPoint
    ? selectionMarkerSvg(selectedPoint.b.x, y(selectedPoint.v), daily ? 6 : Math.min(9, 4 + selectedPoint.b.dayCount / 4) + 2, pointTitle(selectedPoint.b, metricValueText(spec, selectedPoint.v)).replace(/ \(.*\)$/, ""), topY, leftPad, 1040)
    : "";
  const thresholdY = pixel && changeInfo.threshold != null ? y(changeInfo.threshold) : null;
  const changeX = pixel ? changeXPosition(buckets) : null;
  const ticks = monthTicksFor(buckets);
  const [tickTop, tickMid, tickBottom] = scale.ticks;
  const zeroLine = !pixel && spec.id !== "coverage"
    ? `<line x1="${leftPad}" y1="${y(0).toFixed(1)}" x2="1040" y2="${y(0).toFixed(1)}" stroke="#1d2433" stroke-width="1" opacity="0.55"/>`
    : "";

  const legend = pixel
    ? `<span class="inline-row"><span style="width:9px;height:9px;border-radius:50%;background:${CODE_COLOR.N};display:inline-block;"></span>No change</span>
      <span class="inline-row"><span style="width:9px;height:9px;border-radius:50%;background:${CODE_COLOR.P};display:inline-block;"></span>Needs a look</span>
      <span class="inline-row"><span style="width:9px;height:9px;border-radius:50%;background:${CODE_COLOR.C};display:inline-block;"></span>Camera or image issue</span>`
    : `<span class="inline-row"><span style="width:9px;height:9px;border-radius:50%;background:#1769aa;display:inline-block;"></span>Mask accepted by a reviewer</span>
      <span class="inline-row"><span style="width:9px;height:9px;border-radius:50%;background:#fff;border:1.6px solid #1769aa;display:inline-block;"></span>Unreviewed draft mask</span>
      <span class="inline-row">${segCountsText()}</span>`;

  return `
    <svg viewBox="0 0 1040 200" style="width:100%;height:170px;display:block;">
      <text x="4" y="${(topY + 6).toFixed(1)}" font-size="10" fill="var(--ink-muted)">${scale.fmt(tickTop)}</text>
      <line x1="${leftPad}" y1="${topY}" x2="1040" y2="${topY}" stroke="var(--line)" stroke-width="1"/>
      <text x="4" y="${(topY + chartH / 2 + 4).toFixed(1)}" font-size="10" fill="var(--ink-muted)">${scale.fmt(tickMid)}</text>
      <line x1="${leftPad}" y1="${(topY + bottomY) / 2}" x2="1040" y2="${(topY + bottomY) / 2}" stroke="var(--line)" stroke-width="1"/>
      <text x="4" y="${(bottomY + 4).toFixed(1)}" font-size="10" fill="var(--ink-muted)">${scale.fmt(tickBottom)}</text>
      <line x1="${leftPad}" y1="${bottomY}" x2="1040" y2="${bottomY}" stroke="var(--line)" stroke-width="1"/>
      ${zeroLine}
      ${thresholdY != null ? `<line x1="${leftPad}" y1="${thresholdY.toFixed(1)}" x2="1040" y2="${thresholdY.toFixed(1)}" stroke="#1769aa" stroke-width="1" stroke-dasharray="4,3" opacity="0.7"/><text x="1036" y="${Math.max(topY + 10, thresholdY - 6).toFixed(1)}" font-size="10" fill="#1769aa" text-anchor="end">typical range ends ${changeInfo.threshold.toFixed(3)}</text>` : ""}
      ${changeX != null ? `<line x1="${changeX.toFixed(1)}" y1="${topY}" x2="${changeX.toFixed(1)}" y2="${bottomY}" stroke="#9a5b13" stroke-width="1.5" stroke-dasharray="2,3"/>` : ""}
      ${backdrop}
      ${segments.map((s) => `<polyline points="${s}" fill="none" stroke="#c3c2b7" stroke-width="1.5"/>`).join("")}
      ${dots}
      ${marker}
      ${ticks.map((t) => `<text x="${t.x.toFixed(1)}" y="${(bottomY + 18).toFixed(1)}" font-size="11" fill="var(--ink-muted)" text-anchor="middle">${escapeHtml(t.label)}</text>`).join("")}
    </svg>
    <div style="display:flex;gap:16px;margin-top:8px;font-size:12px;color:var(--ink-soft);flex-wrap:wrap;">
      ${legend}
      <span class="inline-row"><span style="width:11px;height:11px;border-radius:50%;border:1.5px solid var(--ok);display:inline-block;"></span>Human-labelled</span>
      ${samHighlightIndex() != null ? `<span class="inline-row"><span style="width:11px;height:11px;border-radius:50%;border:2.5px solid var(--sam);display:inline-block;"></span>Image that Start segmentation will use</span>` : ""}
    </div>
    ${pixel ? "" : `<div class="hint" style="margin-top:6px;line-height:1.5;">${escapeHtml(segNote())}</div>`}`;
}

function segCountsText() {
  const seg = typeof segSeries !== "undefined" ? segSeries : null;
  if (!seg) return "none loaded";
  return `${seg.counts.with_value} of ${seg.counts.images} images have a mask`;
}

function segNote() {
  const seg = typeof segSeries !== "undefined" ? segSeries : null;
  return `${seg ? seg.note + " " : ""}Separate from the pixel appearance score and never combined with it.`;
}

function gaugeChartSvg() {
  const daily = state.granularity === "daily";
  const leftPad = 50;
  const topY = 4;
  const chartH = 118;
  const bottomY = topY + chartH;
  const buckets = assignBucketX(currentBuckets(), leftPad);
  const points = buckets.map((b, i) => ({ v: b.meanGauge, i, b })).filter((p) => p.v != null);
  if (!points.length) return `<div class="hint">No gage data available.</div>`;
  const values = points.map((p) => p.v);
  const min = Math.floor(Math.min(...values) * 10) / 10 - 0.1;
  const max = Math.ceil(Math.max(...values) * 10) / 10 + 0.1;
  const range = Math.max(0.001, max - min);
  const y = (v) => topY + chartH - ((v - min) / range) * chartH;
  const polyline = points.map((p) => `${p.b.x.toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const changeX = changeXPosition(buckets);
  // Same buckets, same colors, same click target as the region-change chart's
  // dots -- selecting a point here selects the same day there, and vice versa,
  // since both read/write the shared state.selectedIndex.
  const selectedPoint = points.find((p) => bucketIsSelected(p.b));
  const unit = gaugeMeta.unit ? ` ${gaugeMeta.unit}` : "";
  const dots = points
    .map((p) => {
      const selected = p === selectedPoint;
      const r = daily ? (selected ? 6 : 3.5) : Math.min(9, 4 + p.b.dayCount / 4) + (selected ? 2 : 0);
      const title = pointTitle(p.b, `${p.v.toFixed(2)}${unit}`);
      return `<circle class="chart-point" cx="${p.b.x.toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="${r}" fill="${p.b.color}" stroke="${selected ? "#1d2433" : "#fff"}" stroke-width="${selected ? 2.5 : 1}" data-act="select-day" data-index="${p.b.repIndex}" role="button" tabindex="0" aria-label="${escapeHtml(title)}" aria-pressed="${selected}" style="cursor:pointer;"><title>${escapeHtml(title)}</title></circle>${labelledRingSvg(p.b, p.b.x.toFixed(1), y(p.v).toFixed(1), r)}${samRingSvg(p.b, p.b.x.toFixed(1), y(p.v).toFixed(1), r)}`;
    })
    .join("");
  const backdrop = selectedPoint ? selectionBackdropSvg(selectedPoint.b.x, topY, bottomY) : "";
  const marker = selectedPoint
    ? selectionMarkerSvg(selectedPoint.b.x, y(selectedPoint.v), daily ? 6 : Math.min(9, 4 + selectedPoint.b.dayCount / 4) + 2, pointTitle(selectedPoint.b, `${selectedPoint.v.toFixed(2)}${unit}`).replace(/ \(.*\)$/, ""), topY, leftPad, 1040)
    : "";

  return `<svg viewBox="0 0 1040 130" style="width:100%;height:110px;display:block;">
    <text x="4" y="${(topY + 6).toFixed(1)}" font-size="10" fill="var(--ink-muted)">${max.toFixed(1)}</text>
    <line x1="${leftPad}" y1="${topY}" x2="1040" y2="${topY}" stroke="var(--line)" stroke-width="1"/>
    <text x="4" y="${(topY + chartH / 2 + 4).toFixed(1)}" font-size="10" fill="var(--ink-muted)">${((max + min) / 2).toFixed(1)}</text>
    <line x1="${leftPad}" y1="${(topY + bottomY) / 2}" x2="1040" y2="${(topY + bottomY) / 2}" stroke="var(--line)" stroke-width="1"/>
    <text x="4" y="${(bottomY + 4).toFixed(1)}" font-size="10" fill="var(--ink-muted)">${min.toFixed(1)}</text>
    <line x1="${leftPad}" y1="${bottomY}" x2="1040" y2="${bottomY}" stroke="var(--line)" stroke-width="1"/>
    ${changeX != null ? `<line x1="${changeX.toFixed(1)}" y1="${topY}" x2="${changeX.toFixed(1)}" y2="${bottomY}" stroke="#9a5b13" stroke-width="1.5" stroke-dasharray="2,3"/>` : ""}
    ${backdrop}
    <polyline points="${polyline}" fill="none" stroke="#1769aa" stroke-width="1.6"/>
    ${dots}
    ${marker}
  </svg>`;
}
