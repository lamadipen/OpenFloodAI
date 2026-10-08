// Review page: the gauge and region-change charts, bucketing, and the selected-point marks.

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
  const daily = state.granularity === "daily";
  const leftPad = 34;
  const topY = 4;
  const chartH = 178;
  const bottomY = topY + chartH;
  const buckets = assignBucketX(currentBuckets(), leftPad);
  const points = buckets.map((b, i) => ({ b, i })).filter((p) => p.b.meanScore != null);
  if (!points.length) return `<div class="hint">No scores available.</div>`;
  const max = Math.max(0.1, Math.ceil(Math.max(...points.map((p) => p.b.meanScore)) * 100) / 100 + 0.02);
  const y = (score) => topY + chartH - (Math.max(0, score) / max) * chartH;

  const segments = [];
  let seg = [];
  buckets.forEach((b) => {
    if (b.meanScore == null) {
      if (seg.length) {
        segments.push(seg.join(" "));
        seg = [];
      }
    } else {
      seg.push(`${b.x.toFixed(1)},${y(b.meanScore).toFixed(1)}`);
    }
  });
  if (seg.length) segments.push(seg.join(" "));

  const selectedPoint = points.find((p) => bucketIsSelected(p.b));
  const dots = points
    .map((p) => {
      const selected = p === selectedPoint;
      const r = daily ? (selected ? 6 : 3.5) : Math.min(9, 4 + p.b.dayCount / 4) + (selected ? 2 : 0);
      const title = pointTitle(p.b, `score ${p.b.meanScore.toFixed(3)}`);
      return `<circle class="chart-point" cx="${p.b.x.toFixed(1)}" cy="${y(p.b.meanScore).toFixed(1)}" r="${r}" fill="${p.b.color}" stroke="${selected ? "#1d2433" : "#fff"}" stroke-width="${selected ? 2.5 : 1}" data-act="select-day" data-index="${p.b.repIndex}" role="button" tabindex="0" aria-label="${escapeHtml(title)}" aria-pressed="${selected}" style="cursor:pointer;"><title>${escapeHtml(title)}</title></circle>${labelledRingSvg(p.b, p.b.x.toFixed(1), y(p.b.meanScore).toFixed(1), r)}${samRingSvg(p.b, p.b.x.toFixed(1), y(p.b.meanScore).toFixed(1), r)}`;
    })
    .join("");
  const backdrop = selectedPoint ? selectionBackdropSvg(selectedPoint.b.x, topY, bottomY) : "";
  const marker = selectedPoint
    ? selectionMarkerSvg(selectedPoint.b.x, y(selectedPoint.b.meanScore), daily ? 6 : Math.min(9, 4 + selectedPoint.b.dayCount / 4) + 2, pointTitle(selectedPoint.b, `score ${selectedPoint.b.meanScore.toFixed(3)}`).replace(/ \(.*\)$/, ""), topY, leftPad, 1040)
    : "";
  const thresholdY = changeInfo.threshold != null ? y(changeInfo.threshold) : null;
  const changeX = changeXPosition(buckets);
  const ticks = monthTicksFor(buckets);

  return `
    <svg viewBox="0 0 1040 200" style="width:100%;height:170px;display:block;">
      <text x="4" y="${(topY + 6).toFixed(1)}" font-size="10" fill="var(--ink-muted)">${max.toFixed(2)}</text>
      <line x1="${leftPad}" y1="${topY}" x2="1040" y2="${topY}" stroke="var(--line)" stroke-width="1"/>
      <text x="4" y="${(topY + chartH / 2 + 4).toFixed(1)}" font-size="10" fill="var(--ink-muted)">${(max / 2).toFixed(2)}</text>
      <line x1="${leftPad}" y1="${(topY + bottomY) / 2}" x2="1040" y2="${(topY + bottomY) / 2}" stroke="var(--line)" stroke-width="1"/>
      <text x="4" y="${(bottomY + 4).toFixed(1)}" font-size="10" fill="var(--ink-muted)">0</text>
      <line x1="${leftPad}" y1="${bottomY}" x2="1040" y2="${bottomY}" stroke="var(--line)" stroke-width="1"/>
      ${thresholdY != null ? `<line x1="${leftPad}" y1="${thresholdY.toFixed(1)}" x2="1040" y2="${thresholdY.toFixed(1)}" stroke="#1769aa" stroke-width="1" stroke-dasharray="4,3" opacity="0.7"/><text x="1036" y="${Math.max(topY + 10, thresholdY - 6).toFixed(1)}" font-size="10" fill="#1769aa" text-anchor="end">typical range ends ${changeInfo.threshold.toFixed(3)}</text>` : ""}
      ${changeX != null ? `<line x1="${changeX.toFixed(1)}" y1="${topY}" x2="${changeX.toFixed(1)}" y2="${bottomY}" stroke="#9a5b13" stroke-width="1.5" stroke-dasharray="2,3"/>` : ""}
      ${backdrop}
      ${segments.map((s) => `<polyline points="${s}" fill="none" stroke="#c3c2b7" stroke-width="1.5"/>`).join("")}
      ${dots}
      ${marker}
      ${ticks.map((t) => `<text x="${t.x.toFixed(1)}" y="${(bottomY + 18).toFixed(1)}" font-size="11" fill="var(--ink-muted)" text-anchor="middle">${escapeHtml(t.label)}</text>`).join("")}
    </svg>
    <div style="display:flex;gap:16px;margin-top:8px;font-size:12px;color:var(--ink-soft);flex-wrap:wrap;">
      <span class="inline-row"><span style="width:9px;height:9px;border-radius:50%;background:${CODE_COLOR.N};display:inline-block;"></span>No change</span>
      <span class="inline-row"><span style="width:9px;height:9px;border-radius:50%;background:${CODE_COLOR.P};display:inline-block;"></span>Needs a look</span>
      <span class="inline-row"><span style="width:9px;height:9px;border-radius:50%;background:${CODE_COLOR.C};display:inline-block;"></span>Camera or image issue</span>
      <span class="inline-row"><span style="width:11px;height:11px;border-radius:50%;border:1.5px solid var(--ok);display:inline-block;"></span>Human-labelled</span>
      ${samHighlightIndex() != null ? `<span class="inline-row"><span style="width:11px;height:11px;border-radius:50%;border:2.5px solid var(--sam);display:inline-block;"></span>Image that Start segmentation will use</span>` : ""}
    </div>`;
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
