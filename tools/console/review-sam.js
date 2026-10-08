// Review page: optional hosted SAM segmentation panel (off by default).

// ---- Hosted SAM (optional, off by default) --------------------------------
// Predictions are unreviewed machine output beside the unchanged human guide.
// Nothing is uploaded until the person confirms the request count and presses
// Start. The API key never reaches this page; only a configured flag does.
let samState = { status: null, plan: null, planKey: "", results: [], concepts: ["river water"], ack: false, busy: false, message: "", target: "selected" };

// Which image would be sent: the point selected on the charts, or the run's
// baseline (the reference image the watched area and guide were drawn on).
function filenameInstant(filename) {
  const m = /___(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})Z\.jpg$/.exec(String(filename || ""));
  return m ? `${m[1]}T${m[2]}:${m[3]}:${m[4]}Z` : "";
}

function samTargetImage() {
  if (samState.target === "baseline") {
    const name = detail && detail.summary && detail.summary.baseline_filename;
    return name ? { kind: "baseline", filename: name, capturedAtUtc: filenameInstant(name), localTime: null } : null;
  }
  const sel = days[state.selectedIndex];
  if (sel && sel.filename && sel.code !== "M") return { kind: "selected", filename: sel.filename, capturedAtUtc: sel.capturedAtUtc, localTime: sel.time };
  return null;
}

// Chart point to ring: only when segmentation could actually be started for the chart-selected image.
function samHighlightIndex() {
  const st = samState.status;
  if (!st || !st.enabled || !st.credential.configured || samState.target !== "selected") return null;
  return samTargetImage() ? state.selectedIndex : null;
}

function samRingSvg(bucket, cx, cy, r) {
  const hi = samHighlightIndex();
  if (hi == null || !bucket.indices.includes(hi)) return "";
  return `<circle cx="${cx}" cy="${cy}" r="${r + 6}" fill="none" stroke="#6d28d9" stroke-width="2.5" pointer-events="none"/><text x="${cx}" y="${Number(cy) - r - 10}" font-size="10" font-weight="700" fill="#6d28d9" text-anchor="middle" pointer-events="none">SAM</text>`;
}

const SAM_STATUS_TEXT = {
  completed: "Mask found",
  no_match: "No match for this concept (this does not mean the area is normal or safe)",
  failed: "Request failed",
  not_attempted: "Not sent"
};
const SAM_ERROR_TEXT = {
  invalid_key: "The API key was rejected or revoked.",
  insufficient_quota: "The provider account has no quota left.",
  rate_limited: "The provider is rate limiting requests.",
  timeout: "The request timed out and may still have been billed.",
  network_error: "The provider could not be reached.",
  provider_error: "The provider returned an error.",
  malformed_response: "The provider reply could not be understood.",
  decoder_unavailable: "The mask decoder is not installed."
};
const SAM_REVIEW_TEXT = { unreviewed: "Unreviewed", accepted: "Accepted", rejected: "Rejected", needs_correction: "Needs correction" };

async function loadSam() {
  try {
    samState.status = await api(`/api/hosted-sam/status?${new URLSearchParams({ folder_name: folderName })}`);
    samState.ack = !!samState.status.credential.upload_acknowledged;
    // Every saved result of every run for this sequence, in one request, so the per-image
    // badges and the accepted count are complete however many runs there are.
    const listing = await api(`/api/hosted-sam/results?${new URLSearchParams({ folder_name: folderName, sequence_id: sequenceId() })}`);
    const results = listing.results || [];
    samState.results = results;
  } catch (error) {
    samState.status = null;
  }
}

function samBody(filename) {
  return { folder_name: folderName, sequence_id: sequenceId(), filenames: [filename], concepts: samState.concepts };
}

async function refreshSamPlan() {
  const st = samState.status;
  const target = samTargetImage();
  if (!st || !st.enabled || !st.credential.configured || !target) return;
  const key = `${target.filename}|${samState.concepts.join(",")}`;
  if (samState.planKey === key) return;
  samState.planKey = key;
  try {
    samState.plan = (await api("/api/hosted-sam/preflight", samBody(target.filename))).plan;
  } catch (error) {
    samState.plan = null;
    samState.message = error.message;
  }
  renderSamPanel();
}

function samResultHtml(result) {
  const review = result.review_status || "unreviewed";
  const reused = result.reused_from ? " (reused from an earlier identical run, no new request)" : "";
  const error = result.error_code ? ` ${escapeHtml(SAM_ERROR_TEXT[result.error_code] || result.message || "")}` : "";
  const overlay = result.status === "completed"
    ? `<img src="/api/hosted-sam/overlay?${new URLSearchParams({ folder_name: folderName, run_id: result.run_id, result_id: result.result_id })}" style="width:100%;border-radius:8px;display:block;margin-top:8px;" alt="Predicted mask over the original image with the human guide" onerror="this.outerHTML='<div class=&quot;hint&quot; style=&quot;margin-top:8px;&quot;>Overlay unavailable: the source image may have changed since this result was saved. The saved masks are unchanged.</div>'">`
    : "";
  const buttons = result.status === "completed"
    ? `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;">
        ${["accepted", "rejected", "needs_correction"].map((d) => `<button class="btn${review === d ? " primary" : ""}" aria-pressed="${review === d}" data-sam-review="${d}" data-run="${escapeHtml(result.run_id)}" data-result="${escapeHtml(result.result_id)}">${escapeHtml(SAM_REVIEW_TEXT[d])}</button>`).join("")}
      </div>`
    : "";
  return `<div style="border-top:1px solid var(--line-soft);padding:10px 0;">
    <div style="font-size:12px;"><strong>${escapeHtml(result.prompt)}</strong> &middot; ${escapeHtml(SAM_STATUS_TEXT[result.status] || result.status)}${error}${escapeHtml(reused)}</div>
    <div class="hint mt-2">Processed ${escapeHtml(formatUtc(result.processed_at_utc))} &middot; ${escapeHtml(result.model_requested)} &middot; <span class="pill ${review === "unreviewed" ? "gray" : review === "accepted" ? "ok" : "warn"}" style="font-size:11px;">${escapeHtml(SAM_REVIEW_TEXT[review] || review)}</span></div>
    ${overlay}${buttons}
  </div>`;
}

function samTargetHtml() {
  const target = samTargetImage();
  const hasBaseline = !!(detail && detail.summary && detail.summary.baseline_filename);
  const option = (value, title, hint, disabled) => `<label style="display:flex;gap:8px;align-items:flex-start;font-size:12px;${disabled ? "opacity:.5;" : ""}">
      <input type="radio" name="samTarget" value="${value}" data-sam-target="${value}" ${samState.target === value ? "checked" : ""} ${disabled ? "disabled" : ""}>
      <span><strong>${title}</strong><br><span style="color:var(--ink-muted);">${hint}</span></span></label>`;
  const picture = target
    ? `<img src="/api/image-sequence-image?${new URLSearchParams({ folder_name: folderName, sequence_id: sequenceId(), filename: target.filename })}" style="width:132px;border-radius:6px;display:block;border:3px solid var(--sam);" alt="Image that will be segmented">`
    : `<div class="hint" style="width:132px;">No image is selected.</div>`;
  const when = target && target.capturedAtUtc ? `${escapeHtml(formatUtc(target.capturedAtUtc))}${target.localTime ? ` (${escapeHtml(target.localTime)} local)` : ""}` : "time not recorded";
  return `<div style="border:2px solid var(--sam);border-radius:10px;padding:10px 12px;margin-top:8px;">
      <div style="font-size:12px;font-weight:700;color:var(--sam);">Image to segment</div>
      <div style="display:flex;gap:12px;margin-top:6px;align-items:flex-start;">
        ${picture}
        <div style="min-width:0;font-size:12px;line-height:1.5;">
          <div style="font-family:var(--mono);word-break:break-all;">${escapeHtml(target ? target.filename : "none")}</div>
          <div class="hint">${when}</div>
          <div class="mt-2">${target ? (target.kind === "baseline" ? "The baseline image: the reference the watched area and guide were drawn on." : "The image selected on the region change chart (ringed in purple).") : "Select a day on the chart first."}</div>
        </div>
      </div>
      <div style="display:flex;flex-direction:column;gap:6px;margin-top:8px;">
        ${option("selected", "Image selected on the region change chart", "Click any point on the charts or an event to choose it.", false)}
        ${option("baseline", "Baseline image", "The reference the watched area and guide were drawn on.", !hasBaseline)}
      </div>
    </div>`;
}

function samPanelHtml() {
  const st = samState.status;
  const sel = samTargetImage();
  const head = `<div style="font-size:12px;font-weight:600;color:var(--ink-soft);margin-bottom:6px;">Hosted SAM segmentation (optional)</div>`;
  const note = `<div class="hint" style="line-height:1.5;">A machine outline for faster review. It is not a human label, not a detected waterline, and does not change any guide, label, or flood decision.</div>`;
  if (!st) return `${head}<div class="hint">Hosted SAM status is unavailable. Normal review is unaffected.</div>`;
  if (!st.enabled) return `${head}${note}<div class="hint mt-6">Off. Nothing is uploaded. Turn it on in <a href="/console/settings.html">Settings</a> if you want to use your own Meta account.</div>${samResultsHtml(sel)}`;
  if (!st.credential.configured) return `${head}${note}<div class="hint mt-6">Add your own API key in <a href="/console/settings.html">Settings</a> to continue. Nothing is uploaded until you start a batch.</div>${samResultsHtml(sel)}`;
  const concepts = ["river water", "riverbank"];
  const count = samState.plan ? samState.plan.request_count : null;
  const canImage = !!sel;
  const ready = canImage && count != null && (samState.ack || samState.ackChecked) && !samState.busy && st.decoder_available;
  return `${head}${note}
    ${samTargetHtml()}
    <div style="display:flex;gap:14px;margin-top:8px;flex-wrap:wrap;font-size:12px;">
      ${concepts.map((c) => `<label><input type="checkbox" data-sam-concept="${c}" ${samState.concepts.includes(c) ? "checked" : ""}> ${escapeHtml(c)}</label>`).join("")}
    </div>
    <div class="hint mt-6">One request per concept for the image above: ${count == null ? "calculating" : escapeHtml(String(count))} paid request(s)${samState.plan && samState.plan.reused_from_earlier_runs ? `, ${escapeHtml(String(samState.plan.reused_from_earlier_runs))} reused from earlier identical runs` : ""}. Meta's pricing and your account apply: <a href="${escapeHtml(st.provider.signup_url)}" target="_blank" rel="noopener noreferrer">pricing</a>.</div>
    ${st.decoder_available ? "" : `<div class="hint mt-6">Meta's SAM parser package is not installed, so nothing can be started.</div>`}
    ${samState.ack ? "" : `<label style="display:block;font-size:12px;margin-top:8px;"><input type="checkbox" id="samAck" ${samState.ackChecked ? "checked" : ""}> I understand the image shown above, cropped to the watched area, will be uploaded to Meta and my account may be charged.</label>`}
    <div style="margin-top:8px;"><button class="btn primary" id="samStart" ${ready ? "" : "disabled"}>${samState.busy ? "Segmenting&hellip;" : `Start segmentation${count == null ? "" : ` (${escapeHtml(String(count))} request${count === 1 ? "" : "s"})`}`}</button></div>
    ${samState.message ? `<div class="hint" style="margin-top:6px;color:var(--bad);">${escapeHtml(samState.message)}</div>` : ""}
    ${samResultsHtml(sel)}`;
}

function samResultsHtml(sel) {
  const rows = samState.results.filter((r) => sel && r.filename === sel.filename);
  if (!rows.length) return "";
  return `<div class="mt-10">${rows.map(samResultHtml).join("")}</div>`;
}

function renderSamPanel() {
  const el = $("samPanel");
  if (!el) return;
  el.innerHTML = samPanelHtml();
  el.querySelectorAll("[data-sam-concept]").forEach((box) =>
    box.addEventListener("change", () => {
      const picked = Array.from(el.querySelectorAll("[data-sam-concept]")).filter((b) => b.checked).map((b) => b.dataset.samConcept);
      samState.concepts = picked.length ? picked : [box.dataset.samConcept];
      samState.plan = null;
      samState.planKey = "";
      renderSamPanel();
      refreshSamPlan();
    })
  );
  el.querySelectorAll("[data-sam-target]").forEach((radio) =>
    radio.addEventListener("change", () => {
      samState.target = radio.dataset.samTarget;
      samState.plan = null;
      samState.planKey = "";
      render();
    })
  );
  const ack = $("samAck");
  if (ack) ack.addEventListener("change", () => { samState.ackChecked = ack.checked; renderSamPanel(); });
  const start = $("samStart");
  if (start) start.addEventListener("click", startSam);
  el.querySelectorAll("[data-sam-review]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      try {
        await api("/api/hosted-sam/review", { folder_name: folderName, run_id: btn.dataset.run, result_id: btn.dataset.result, decision: btn.dataset.samReview });
        const row = samState.results.find((r) => r.run_id === btn.dataset.run && r.result_id === btn.dataset.result);
        if (row) row.review_status = btn.dataset.samReview;
        toast("Review saved. This is separate from human labels.");
        render();
      } catch (error) {
        toast(error.message);
      }
    })
  );
}

async function startSam() {
  const sel = samTargetImage();
  if (samState.busy || !samState.plan || !sel) return;
  samState.busy = true;
  samState.message = "";
  renderSamPanel();
  try {
    if (!samState.ack) {
      await api("/api/hosted-sam/acknowledge", { acknowledged: true });
      samState.ack = true;
    }
    await api("/api/hosted-sam/run", { ...samBody(sel.filename), confirmed_request_count: samState.plan.request_count });
    await loadSam();
    samState.planKey = "";
    samState.plan = null;
  } catch (error) {
    samState.message = error.message;
  }
  samState.busy = false;
  renderSamPanel();
  refreshSamPlan();
}
