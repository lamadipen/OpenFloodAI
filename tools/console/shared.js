// OpenFloodAI console — shared helpers and app shell.
// New, separate UI (tools/console/). Talks only to the existing,
// unmodified JSON APIs already served by home_server.py.

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

async function api(path, body) {
  const response = await fetch(
    path,
    body === undefined
      ? {}
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
  );
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok || (data && data.success === false)) {
    const message = (data && (data.message || data.error)) || `Request failed (${response.status})`;
    throw new Error(message);
  }
  return data;
}

function toast(message) {
  const el = $("toast");
  if (!el) return;
  el.textContent = message;
  el.hidden = false;
  window.clearTimeout(el._hideTimer);
  el._hideTimer = window.setTimeout(() => {
    el.hidden = true;
  }, 4000);
}

function svgIcon(name) {
  const icons = {
    dashboard:
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>',
    sites:
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 10l9-7 9 7"/><path d="M5 9v10a1 1 0 001 1h4v-6h4v6h4a1 1 0 001-1V9"/></svg>',
    river:
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12c2-4 5-6 8-6s6 4 8 8 6 2 6 2"/></svg>',
    download:
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M4 19h16"/></svg>'
  };
  return icons[name] || "";
}

/**
 * Render the persistent app shell (dark rail + light main column) and
 * return the DOM node where callers should place page content.
 * `active` is one of "dashboard" | "sites" | "rivers" | "downloads".
 * `activeSiteFolder`, when given, highlights that site in the rail list.
 */
function mountShell({ active, activeSiteFolder, crumbs }) {
  document.body.innerHTML = `
    <div class="app-shell">
      <aside class="rail">
        <div class="rail-brand">
          <div class="rail-mark">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12c2-4 5-6 8-6s6 4 8 8 6 2 6 2"/></svg>
          </div>
          <div>
            <div class="rail-title">OpenFloodAI</div>
            <div class="rail-subtitle">Validation console</div>
          </div>
        </div>
        <div style="height:1px;background:var(--rail-line);margin:4px 22px 16px;"></div>
        <nav class="rail-nav">
          <a class="rail-item ${active === "dashboard" ? "active" : ""}" href="/console/dashboard.html">${svgIcon("dashboard")}Dashboard</a>
          <a class="rail-item ${active === "sites" ? "active" : ""}" href="/console/dashboard.html#sites">${svgIcon("sites")}Sites</a>
        </nav>
        <div class="rail-sites">
          <div class="rail-sites-label">Your sites</div>
          <div id="railSiteList"></div>
        </div>
        <div class="rail-foot">
          <div style="height:1px;background:var(--rail-line);margin:0 0 14px;"></div>
          <div style="display:flex;align-items:center;gap:8px;font-size:11px;color:var(--rail-text-dim);">
            <span style="width:6px;height:6px;border-radius:50%;background:#3fae68;flex-shrink:0;"></span>
            Local media &middot; no public upload
          </div>
        </div>
      </aside>
      <main class="app-main">
        <div class="topbar">
          <div class="crumbs" id="crumbs"></div>
          <div id="topbarActions" style="display:flex;align-items:center;gap:10px;"></div>
        </div>
        <div class="content" id="content"></div>
      </main>
    </div>
    <div class="toast" id="toast" hidden></div>
  `;
  renderCrumbs(crumbs || []);
  loadRailSites(activeSiteFolder);
  return $("content");
}

function renderCrumbs(parts) {
  const el = $("crumbs");
  if (!el) return;
  el.innerHTML = parts
    .map((part, i) => {
      const isLast = i === parts.length - 1;
      const label = escapeHtml(part.label);
      if (isLast || !part.href) return `<span class="${isLast ? "current" : ""}">${label}</span>`;
      return `<a href="${part.href}">${label}</a><span>/</span>`;
    })
    .join("");
}

async function loadRailSites(activeSiteFolder) {
  const el = $("railSiteList");
  if (!el) return;
  try {
    const data = await api("/api/sites");
    const sites = data.sites || [];
    el.innerHTML = sites
      .map((s) => {
        const active = s.site_name === activeSiteFolder;
        return `<a class="rail-site-link ${active ? "active" : ""}" href="/console/site.html?site=${encodeURIComponent(s.site_name)}">${escapeHtml(s.site_name)}</a>`;
      })
      .join("");
  } catch (error) {
    el.innerHTML = `<div style="font-size:11px;color:var(--rail-text-dim);padding:0 10px;">Could not load sites.</div>`;
  }
}

function qs(name, fallback = "") {
  return new URLSearchParams(location.search).get(name) ?? fallback;
}
