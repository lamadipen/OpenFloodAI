// Datasets page: the Release section (Issue #207).
//
// A release is a clean, versioned export of one FROZEN dataset version, for sharing with other
// researchers. This section records the human approvals the release depends on, builds it,
// verifies it, shows the checklist to complete before anything becomes public, and can send a
// verified release to a PRIVATE Hugging Face repository. Building never uploads. The page never
// asks for, stores or shows a token: an upload uses the HF_TOKEN environment variable.

const relPage = {
  policy: null,
  readiness: null,
  releases: [],
  upload: null,
  version: 0,
  message: "",
  results: {},
  openChecklist: "",
  openUpload: ""
};

async function loadRelease() {
  const view = dsPage.view;
  const versions = (view && view.versions) || [];
  if (!versions.length) {
    relPage.readiness = null;
    relPage.releases = [];
    return;
  }
  if (!versions.some((v) => v.version === relPage.version)) relPage.version = versions[versions.length - 1].version;
  try {
    const id = encodeURIComponent(dsPage.id);
    [relPage.policy, relPage.readiness, relPage.releases, relPage.upload] = await Promise.all([
      api("/api/release-policy"),
      api(`/api/release-readiness?dataset_id=${id}&version=${relPage.version}`),
      api(`/api/dataset-releases?dataset_id=${id}`).then((r) => r.releases || []),
      api("/api/release-upload-status")
    ]);
  } catch (error) {
    relPage.message = error.message;
  }
}

function releaseChannel(version) {
  const match = /^v(\d+)\.(\d+)(?:\.(\d+))?$/.exec(version.trim());
  if (!match) return null;
  return Number(match[1]) >= 1 ? "public" : "draft";
}

function approvalPill(ok) {
  return `<span class="pill ${ok ? "ok" : "warn"}">${ok ? "Approved" : "Needs approval"}</span>`;
}

function approvalsHtml(r) {
  const license = relPage.policy && relPage.policy.annotation_license;
  const sources = r.sources
    .map((s) => `<div class="mt-10"><div class="inline-row"><span class="mono-12">${escapeHtml(s.name)}</span>${approvalPill(s.approved)}</div>
      ${s.approved ? `<div class="muted-12">${escapeHtml(((relPage.policy.sources[s.name] || {}).credit) || "")}</div>` : ""}
      <details class="mt-4"><summary class="soft-12" style="cursor:pointer;">${s.approved ? "Replace" : "Record"} the reuse permission</summary>
        <div data-source-form="${escapeHtml(s.name)}">
          <label class="mt-6">License</label><input class="full-width" data-f="license_name" placeholder="For example: U.S. Government work">
          <label class="mt-6">Credit text</label><input class="full-width" data-f="credit" placeholder="USGS images must credit the U.S. Geological Survey">
          <label class="mt-6">Reuse note</label><input class="full-width" data-f="reuse_note">
          <label class="mt-6">Approved by</label><input class="full-width" data-f="approved_by">
          <button class="btn primary mt-6" type="button" data-save-source="${escapeHtml(s.name)}">Save approval</button></div></details></div>`)
    .join("");
  const sites = r.sites
    .map((s) => `<div class="mt-10"><div class="inline-row"><span class="mono-12" style="overflow-wrap:anywhere;">${escapeHtml(s.site_id)}</span>${approvalPill(s.approved)}</div>
      ${s.approved ? `<div class="muted-12">Reviewed by ${escapeHtml(relPage.policy.sites[s.site_id].privacy_review.reviewed_by)} · location: ${escapeHtml(relPage.policy.sites[s.site_id].location.mode.replace(/_/g, " "))}</div>` : ""}
      <details class="mt-4"><summary class="soft-12" style="cursor:pointer;">${s.approved ? "Redo" : "Record"} the privacy review</summary>
        <div data-site-form="${escapeHtml(s.site_id)}">
          <label class="mt-6">Reviewed by</label><input class="full-width" data-f="reviewed_by">
          <div class="hint">The review must cover all three:</div>
          <label><input type="checkbox" data-check="faces_reviewed"> People's faces</label>
          <label><input type="checkbox" data-check="license_plates_reviewed"> License plates</label>
          <label><input type="checkbox" data-check="private_property_reviewed"> Private property</label>
          <label class="mt-6">Location in the release</label>
          <select class="full-width" data-f="location_mode"><option value="generalized">Generalized (recommended)</option><option value="omitted">Hidden</option><option value="exact_approved">Exact (needs an approver)</option></select>
          <label class="mt-6">Decimal places when generalized (1 is about 11 km)</label><input class="full-width" type="number" min="0" max="3" value="1" data-f="precision_decimals">
          <label class="mt-6">Exact location approved by</label><input class="full-width" data-f="exact_location_approved_by">
          <label class="mt-6">Notes</label><input class="full-width" data-f="notes">
          <button class="btn primary mt-6" type="button" data-save-site="${escapeHtml(s.site_id)}">Save privacy review</button></div></details></div>`)
    .join("");
  return `<div class="card card-pad"><div class="title-s">Approvals</div>
    <div class="hint mb-8">A release only includes what a person has approved, under their name. Nothing is filled in for you. Images from a source or site without an approval are left out and listed.</div>
    <div class="inline-row"><span class="title-s" style="font-size:12px;">Annotation license</span>${approvalPill(!!license)}</div>
    ${license ? `<div class="muted-12">${escapeHtml(license.spdx_id)}, held by ${escapeHtml(license.holder)}, approved by ${escapeHtml(license.approved_by)}</div>` : ""}
    <details class="mt-4"><summary class="soft-12" style="cursor:pointer;">${license ? "Replace" : "Record"} the annotation license</summary>
      <div data-license-form>
        <label class="mt-6">License identifier</label><input class="full-width" data-f="spdx_id" placeholder="For example: CC-BY-4.0">
        <label class="mt-6">Held by</label><input class="full-width" data-f="holder">
        <label class="mt-6">Approved by</label><input class="full-width" data-f="approved_by">
        <button class="btn primary mt-6" type="button" id="saveLicense">Save license</button></div></details>
    <div class="title-s mt-10" style="font-size:12px;">Image sources</div>${sources || `<div class="muted-12">No sources.</div>`}
    <div class="title-s mt-10" style="font-size:12px;">Sites</div>${sites || `<div class="muted-12">No sites.</div>`}
    <div class="err" id="approvalError" hidden></div></div>`;
}

function buildHtml(view, r) {
  const versions = view.versions.map((v) => `<option value="${v.version}" ${v.version === relPage.version ? "selected" : ""}>Frozen v${v.version} (${v.examples} examples)</option>`).join("");
  const previous = relPage.releases.map((x) => `<option value="${escapeHtml(x.release_version)}">${escapeHtml(x.release_version)}</option>`).join("");
  const blocked = r.missing.length ? `<ul style="margin:6px 0 0 18px;padding:0;font-size:12px;color:var(--warn);">${r.missing.map((m) => `<li>${escapeHtml(m)}</li>`).join("")}</ul>` : "";
  const result = relPage.results.build;
  let resultHtml = "";
  if (result && result.error) resultHtml = `<div class="err">${escapeHtml(result.error)}${(result.details || []).map((d) => `<div>${escapeHtml(d.message)}</div>`).join("")}</div>`;
  else if (result) resultHtml = `<div class="soft-12 mt-6" style="color:var(--ok);">Built ${escapeHtml(result.manifest.release_version)}: ${result.manifest.counts.released} examples released, ${result.manifest.counts.rejected} left out. Nothing was uploaded.</div>`;
  return `<div class="card card-pad"><div class="title-s">Build a release</div>
    <div class="hint mb-8">Reads only the frozen version you pick. It never changes a site folder and never uploads. v0.x are private drafts and may list gaps; v1.0 and later need cameras in train, validation and test. A release is never replaced: a correction is a new version.</div>
    ${r.can_build ? `<div class="pill ok">Approvals are in place</div>` : `<div class="pill warn">Not ready to build</div>${blocked}`}
    <label class="mt-10" for="relFrozen">Frozen dataset version</label><select id="relFrozen" class="full-width">${versions}</select>
    <label class="mt-6" for="relVersion">Release version</label><input id="relVersion" class="full-width" placeholder="v0.1">
    <div class="hint" id="relChannel"></div>
    <label class="mt-6" for="relNotes">Release notes</label><input id="relNotes" class="full-width" maxlength="400" placeholder="What is in this release?">
    ${relPage.releases.length ? `<label class="mt-6" for="relPrev">Carry the changelog from</label><select id="relPrev" class="full-width"><option value="">Nothing</option>${previous}</select>` : ""}
    <label class="mt-6"><input type="checkbox" id="relParquet"> Also write metadata.parquet (needs the optional pyarrow package)</label>
    <button class="btn primary mt-10" id="buildRelease" ${r.can_build ? "" : "disabled"}>Build release</button>${resultHtml}</div>`;
}

function checklistHtml(release) {
  return release.checklist
    .map((item) => `<label style="display:flex;gap:8px;margin-top:6px;font-size:12px;font-weight:400;"><input type="checkbox" data-check-item="${item.index}" data-release="${escapeHtml(release.release_version)}" ${item.checked ? "checked" : ""}> <span>${escapeHtml(item.text)}</span></label>`)
    .join("");
}

function uploadFormHtml(release) {
  const u = relPage.upload || {};
  const v = release.release_version;
  const result = relPage.results[`upload-${v}`];
  return `<div class="mt-10" style="border-top:1px solid var(--line-soft);padding-top:10px;">
    <div class="title-s" style="font-size:12px;">Upload to Hugging Face (private)</div>
    <div class="hint">Sends this verified release to a <strong>private</strong> dataset repository. Making it public is a separate step you take on Hugging Face after the checklist above.</div>
    <div class="soft-12 mt-6">Token: ${u.token_set ? `found in <span class="mono-12">${escapeHtml(u.token_env)}</span>` : `<span style="color:var(--bad);">not set.</span> Set <span class="mono-12">${escapeHtml(u.token_env)}</span> in the environment where you started this app. This page never asks for a token.`}</div>
    <div class="soft-12">Hugging Face library: ${u.hub_installed ? "installed" : `<span style="color:var(--bad);">not installed.</span> Install it with <span class="mono-12">pip install "openfloodai[export]"</span>.`}</div>
    <label class="mt-6">Repository (owner/name)</label><input class="full-width" data-up="repo_id" data-release="${escapeHtml(v)}" placeholder="your-name/openfloodai-${escapeHtml(v.replace(".", "-"))}">
    <label class="mt-6">Type the repository name again to confirm</label><input class="full-width" data-up="confirm_repo_id" data-release="${escapeHtml(v)}">
    <label class="mt-6"><input type="checkbox" data-up="confirmed" data-release="${escapeHtml(v)}"> I understand this uploads these images and data to a private Hugging Face repository.</label>
    <button class="btn primary mt-6" data-upload="${escapeHtml(v)}" ${u.token_set && u.hub_installed ? "" : "disabled"}>Upload privately</button>
    ${result && result.error ? `<div class="err">${escapeHtml(result.error)}</div>` : ""}
    ${result && result.upload ? `<div class="soft-12 mt-6" style="color:var(--ok);">Uploaded to the private repository ${escapeHtml(result.upload.repo_id)}. ${escapeHtml(result.upload.next)}</div>` : ""}
  </div>`;
}

function releaseCardHtml(release) {
  const v = release.release_version;
  const verify = relPage.results[`verify-${v}`];
  const gaps = release.readiness_gaps.map((g) => `<li>${escapeHtml(g.message)}</li>`).join("");
  const kaggle = relPage.results[`kaggle-${v}`];
  const done = release.checklist.filter((i) => i.checked).length;
  return `<div class="card" style="padding:12px 14px;margin-top:10px;">
    <div class="inline-row" style="justify-content:space-between;"><span class="title-s">${escapeHtml(v)}</span>
      <span><span class="pill ${release.channel === "public" ? "info" : "gray"}">${escapeHtml(release.channel)}</span> ${release.publication_ready ? `<span class="pill ok">Publication ready</span>` : ""}</span></div>
    <div class="soft-12 mt-4">${release.counts.released} examples (${Object.entries(release.counts.by_split).map(([k, n]) => `${k} ${n}`).join(", ")}), ${release.counts.images} images, ${release.counts.rejected} left out. Built from frozen v${release.source_version}.</div>
    ${gaps ? `<ul style="margin:6px 0 0 18px;padding:0;font-size:12px;color:var(--warn);">${gaps}</ul>` : ""}
    <div class="inline-row mt-10" style="flex-wrap:wrap;">
      <button class="btn" data-verify-release="${escapeHtml(v)}">Verify</button>
      <button class="btn" data-toggle-checklist="${escapeHtml(v)}">Checklist (${done}/${release.checklist.length})</button>
      <button class="btn" data-toggle-upload="${escapeHtml(v)}">Upload privately…</button>
      <button class="btn" data-kaggle="${escapeHtml(v)}">Kaggle metadata</button></div>
    ${verify ? (verify.error ? `<div class="err">${escapeHtml(verify.error)}</div>` : verify.ok ? `<div class="soft-12 mt-6" style="color:var(--ok);">Verified: checksums, files, splits and the privacy scan all pass.</div>` : `<ul style="margin:6px 0 0 18px;padding:0;font-size:12px;color:var(--bad);">${verify.problems.map((p) => `<li>${escapeHtml(p)}</li>`).join("")}</ul>`) : ""}
    ${relPage.openChecklist === v ? `<div class="mt-10"><div class="hint">Complete every item before making any repository public.</div>${checklistHtml(release)}</div>` : ""}
    ${relPage.openUpload === v ? uploadFormHtml(release) : ""}
    ${relPage.openKaggle === v ? `<div class="mt-10"><div class="hint">Mirror the identical release files to Kaggle with this metadata. No upload happens here.</div>
      <label>Kaggle username</label><input class="full-width" id="kaggleOwner" value="${escapeHtml(relPage.kaggleOwner || "")}"><button class="btn mt-6" data-kaggle-make="${escapeHtml(v)}">Generate</button>
      ${kaggle && kaggle.error ? `<div class="err">${escapeHtml(kaggle.error)}</div>` : ""}${kaggle && kaggle.metadata ? `<pre class="mono-12" style="white-space:pre-wrap;overflow-wrap:anywhere;">${escapeHtml(JSON.stringify(kaggle.metadata, null, 2))}</pre>` : ""}</div>` : ""}
  </div>`;
}

function releaseSectionHtml(view) {
  if (!view.versions.length) {
    return `<div class="card card-pad"><div class="title-s">Release for sharing</div><div class="muted-12 mt-4">Freeze a version first. A release is built from a frozen version.</div></div>`;
  }
  const r = relPage.readiness;
  if (!r) return `<div class="card card-pad"><div class="title-s">Release for sharing</div><div class="muted-12 mt-4">Loading&hellip;</div></div>`;
  return `<div class="card card-pad"><div class="title-m">Release for sharing</div>
    <p class="soft-12" style="max-width:62ch;line-height:1.6;">Turn a frozen version into a clean, versioned export for other researchers. It leaves out private notes, local paths and anything without an approval, and nothing is uploaded unless you choose to at the end.</p>
    ${relPage.message ? `<div class="err">${escapeHtml(relPage.message)}</div>` : ""}</div>
    ${approvalsHtml(r)}
    ${buildHtml(view, r)}
    <div class="card card-pad"><div class="title-s">Releases (${relPage.releases.length})</div>
      ${relPage.releases.map(releaseCardHtml).join("") || `<div class="muted-12 mt-4">No releases built yet.</div>`}</div>`;
}

function formValues(root) {
  const values = {};
  root.querySelectorAll("[data-f]").forEach((el) => { values[el.dataset.f] = el.value; });
  return values;
}

async function relPost(path, body, key) {
  try {
    const data = await post(path, body);
    if (key) relPage.results[key] = data;
    return data;
  } catch (error) {
    if (key) relPage.results[key] = { error: error.message, details: (error.data && error.data.details) || [] };
    else relPage.message = error.message;
    return null;
  } finally {
    await refresh();
  }
}

function wireRelease() {
  const section = $("content");
  const frozen = $("relFrozen");
  if (frozen) frozen.addEventListener("change", async () => { relPage.version = Number(frozen.value); await loadRelease(); render(); });
  const version = $("relVersion");
  if (version) version.addEventListener("input", () => {
    const channel = releaseChannel(version.value);
    $("relChannel").textContent = channel ? (channel === "public" ? "A public release: needs released cameras in train, validation and test." : "A private draft: gaps are allowed and listed.") : "Use a version like v0.1 or v1.0.";
  });
  section.querySelectorAll("[data-save-source]").forEach((btn) => btn.addEventListener("click", async () => {
    const values = formValues(section.querySelector(`[data-source-form="${CSS.escape(btn.dataset.saveSource)}"]`));
    const data = await relPost("/api/release-approve-source", { source_system: btn.dataset.saveSource, ...values }, "approval");
    if (!data) return;
  }));
  const license = $("saveLicense");
  if (license) license.addEventListener("click", () => relPost("/api/release-approve-license", formValues(section.querySelector("[data-license-form]")), "approval"));
  section.querySelectorAll("[data-save-site]").forEach((btn) => btn.addEventListener("click", () => {
    const root = section.querySelector(`[data-site-form="${CSS.escape(btn.dataset.saveSite)}"]`);
    const checks = {};
    root.querySelectorAll("[data-check]").forEach((box) => { checks[box.dataset.check] = box.checked; });
    const values = formValues(root);
    relPost("/api/release-approve-site", { site_id: btn.dataset.saveSite, ...values, precision_decimals: Number(values.precision_decimals || 1), checks }, "approval");
  }));
  const build = $("buildRelease");
  if (build) build.addEventListener("click", () => relPost("/api/release-build", {
    dataset_id: dsPage.id, dataset_version: Number($("relFrozen").value), release_version: $("relVersion").value.trim(),
    notes: $("relNotes").value, previous_version: ($("relPrev") || {}).value || "", parquet: $("relParquet").checked
  }, "build"));
  section.querySelectorAll("[data-verify-release]").forEach((btn) => btn.addEventListener("click", async () => {
    const v = btn.dataset.verifyRelease;
    try {
      relPage.results[`verify-${v}`] = await api(`/api/release-verify?${new URLSearchParams({ dataset_id: dsPage.id, release_version: v })}`);
    } catch (error) {
      relPage.results[`verify-${v}`] = { error: error.message };
    }
    render();
  }));
  section.querySelectorAll("[data-toggle-checklist]").forEach((btn) => btn.addEventListener("click", () => {
    relPage.openChecklist = relPage.openChecklist === btn.dataset.toggleChecklist ? "" : btn.dataset.toggleChecklist;
    render();
  }));
  section.querySelectorAll("[data-toggle-upload]").forEach((btn) => btn.addEventListener("click", () => {
    relPage.openUpload = relPage.openUpload === btn.dataset.toggleUpload ? "" : btn.dataset.toggleUpload;
    render();
  }));
  section.querySelectorAll("[data-kaggle]").forEach((btn) => btn.addEventListener("click", () => {
    relPage.openKaggle = relPage.openKaggle === btn.dataset.kaggle ? "" : btn.dataset.kaggle;
    render();
  }));
  section.querySelectorAll("[data-kaggle-make]").forEach((btn) => btn.addEventListener("click", () => {
    relPage.kaggleOwner = $("kaggleOwner").value;
    relPost("/api/release-kaggle-metadata", { dataset_id: dsPage.id, release_version: btn.dataset.kaggleMake, owner: relPage.kaggleOwner }, `kaggle-${btn.dataset.kaggleMake}`);
  }));
  section.querySelectorAll("[data-check-item]").forEach((box) => box.addEventListener("change", () => relPost("/api/release-checklist", {
    dataset_id: dsPage.id, release_version: box.dataset.release, index: Number(box.dataset.checkItem), checked: box.checked
  })));
  section.querySelectorAll("[data-upload]").forEach((btn) => btn.addEventListener("click", () => {
    const v = btn.dataset.upload;
    const field = (name) => section.querySelector(`[data-up="${name}"][data-release="${CSS.escape(v)}"]`);
    relPost("/api/release-upload-hf", {
      dataset_id: dsPage.id, release_version: v, repo_id: field("repo_id").value.trim(),
      confirm_repo_id: field("confirm_repo_id").value.trim(), confirmed: field("confirmed").checked
    }, `upload-${v}`);
  }));
  const approvalResult = relPage.results.approval;
  if (approvalResult && approvalResult.error && $("approvalError")) {
    $("approvalError").hidden = false;
    $("approvalError").textContent = approvalResult.error;
  }
}
