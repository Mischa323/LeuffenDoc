/* LeuffenDoc — the shell.

   This is the foundation: who is signed in, which customers they may see, and
   the frame the rest hangs in. Documents, custom document types and the vault
   each arrive as their own section in the sidebar. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const state = { me: null, orgs: [], tab: "orgs" };

  // Sections. The ones that aren't built yet say so plainly rather than
  // pretending to be empty.
  const TABS = [
    { id: "orgs", label: "Klanten", icon: "building", title: "Klanten",
      sub: "De klanten die je mag zien" },
    { id: "docs", label: "Documenten", icon: "file", title: "Documenten",
      sub: "Pagina's per klant", soon: "Documenten, mappen en zoeken komen in de volgende stap." },
    { id: "types", label: "Documenttypes", icon: "layers", title: "Documenttypes",
      sub: "Zelf samengestelde types met eigen velden",
      soon: "Hiermee maak je straks je eigen documentatiepunten: kies de velden, en elke klant krijgt dezelfde structuur." },
    { id: "vault", label: "Wachtwoorden", icon: "key", title: "Wachtwoorden",
      sub: "Versleutelde kluis per klant",
      soon: "De kluis wordt gebouwd nadat de documentatie staat. Opslag wordt versleuteld met een sleutel per klant, en elk tonen of kopiëren komt in het logboek." },
    { id: "audit", label: "Logboek", icon: "history", title: "Logboek",
      sub: "Wie heeft wat bekeken en gewijzigd" },
  ];

  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (res.status === 401) { location.href = "/auth/login"; throw new Error("niet aangemeld"); }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `${res.status}`);
    return body;
  }

  // ---- theme (remembered per browser) ----
  // Sun and moon aren't in the shared icon set, and a theme switch that shows an
  // eye reads as "hide something", so they live here.
  const SUN = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
    stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4
    M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`;
  const MOON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
    stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>`;

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    $("theme-btn").innerHTML = theme === "dark" ? SUN : MOON;
    try { localStorage.setItem("leuffendoc-theme", theme); } catch (e) { /* private window */ }
  }

  function initTheme() {
    let saved = null;
    try { saved = localStorage.getItem("leuffendoc-theme"); } catch (e) { /* ignore */ }
    applyTheme(saved || "dark");
    $("theme-btn").onclick = () =>
      applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  }

  // ---- sidebar ----
  function renderNav() {
    $("nav").innerHTML = TABS.map((t) =>
      `<button data-tab="${t.id}"${t.id === state.tab ? ' class="active"' : ""}>
         ${ICON[t.icon]} ${t.label}${t.id === "orgs" ? `<span class="count">${state.orgs.length}</span>` : ""}
       </button>`).join("");
    $("nav").querySelectorAll("button").forEach((b) => {
      b.onclick = () => { state.tab = b.dataset.tab; render(); };
    });
  }

  // ---- views ----
  function orgMark(name) {
    const initials = name.trim().split(/\s+/).slice(0, 2).map((w) => w[0] || "").join("").toUpperCase();
    // A stable colour per customer, so the same one always looks the same.
    let h = 0;
    for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360;
    return `<span class="oc-mark" style="background:hsl(${h} 55% 45%)">${esc(initials)}</span>`;
  }

  function orgsView() {
    if (!state.orgs.length) {
      return `<div class="panel"><div class="empty"><div class="big">${ICON.building}</div>
        <div>Nog geen klanten</div>
        <div style="font-size:12.5px;margin-top:6px">${state.me.is_admin
          ? "Voeg er een toe, of koppel de RMM zodat de klanten daar vandaan komen."
          : "Vraag een beheerder om je toegang te geven."}</div></div></div>`;
    }
    return `<div class="cards">${state.orgs.map((o) => `
      <div class="orgcard" data-org="${esc(o.id)}">
        <div class="oc-head">${orgMark(o.name)}
          <div><h3>${esc(o.name)}</h3>
            <small>${o.rmm_org_id ? "gekoppeld aan de RMM" : "alleen in LeuffenDoc"}</small></div>
          <span class="oc-arrow">${ICON.chevR}</span>
        </div>
      </div>`).join("")}</div>`;
  }

  // What the server makes of the connection. Behind a reverse proxy this is
  // the fastest way to see whether it is passing its headers on -- and the
  // audit log is only worth reading if the address in it is the visitor's.
  function connectionView(d) {
    const rows = [];
    if (!d.public_url) {
      rows.push(["warn", "Het openbare adres is niet ingesteld",
        "Zet <code>DOC_PUBLIC_URL</code> op het https-adres waar mensen binnenkomen. Aanmeldingen springen anders terug naar een adres dat niet werkt."]);
    }
    if (d.forwarded_for && !d.trust_proxy) {
      rows.push(["warn", "Er staat een proxy voor, maar die wordt niet vertrouwd",
        `Het logboek schrijft nu <b class="mono">${esc(d.client_ip)}</b> op — de proxy zelf, niet de bezoeker. Zet <code>DOC_TRUST_PROXY=1</code>.`]);
    }
    if (d.trust_proxy && !d.forwarded_for) {
      rows.push(["warn", "Vertrouwde proxy, maar geen doorgestuurd adres",
        "<code>DOC_TRUST_PROXY</code> staat aan terwijl er geen <code>X-Forwarded-For</code> binnenkomt. Laat de proxy die meesturen, of zet de instelling uit."]);
    }
    if (d.trust_proxy && d.forwarded_hops > 1) {
      rows.push(["warn", "De proxy plakt adressen aan elkaar",
        `Er komen ${d.forwarded_hops} adressen binnen (<span class="mono">${esc(d.forwarded_for)}</span>). Dan bepaalt de bezoeker het oudste adres zelf, en dat is wat er wordt vastgelegd. Laat de proxy het adres <b>overschrijven</b> in plaats van aanvullen: <code>proxy_set_header X-Forwarded-For $remote_addr;</code>`]);
    }
    if (d.trust_proxy && d.proxy_ips === "*") {
      rows.push(["warn", "Elk adres mag zich als proxy voordoen",
        "Zet <code>DOC_PROXY_IPS</code> op het adres van je proxy. Anders kan iemand die de container rechtstreeks bereikt zelf bepalen welk adres in het logboek komt."]);
    }
    if (d.secure_cookies && d.scheme !== "https") {
      rows.push(["warn", "Cookies vragen om https, maar het verkeer komt als http binnen",
        "Laat de proxy <code>X-Forwarded-Proto: https</code> meesturen, anders bewaart de browser de aanmelding niet."]);
    }
    if (!rows.length) {
      rows.push(["info", "De verbinding klopt",
        `Je komt binnen vanaf <b class="mono">${esc(d.client_ip)}</b> via <b>${esc(d.scheme)}</b> op <b class="mono">${esc(d.host || "?")}</b>.`]);
    }
    return rows.map(([kind, title, text]) => `<div class="callout ${kind}" style="margin-bottom:14px">
      <div class="ic">${kind === "warn" ? ICON.alert : ICON.info}</div>
      <div><div class="ct">${title}</div><div class="cd">${text}</div></div></div>`).join("");
  }

  async function auditView() {
    if (!state.me.is_admin) {
      return `<div class="callout info"><div class="ic">${ICON.info}</div><div>
        <div class="ct">Alleen voor beheerders</div>
        <div class="cd">Het logboek toont wat iedereen heeft bekeken en gewijzigd.</div></div></div>`;
    }
    const diag = await api("/api/diagnostics").catch(() => null);
    const head = diag ? connectionView(diag) : "";
    const entries = await api("/api/audit");
    if (!entries.length) return head + `<div class="panel"><div class="empty"><div class="big">${ICON.history}</div>
      <div>Nog niets vastgelegd</div></div></div>`;
    return head + `<div class="panel"><table class="grid"><thead><tr>
        <th>Wanneer</th><th>Wie</th><th>Wat</th><th>Waarop</th><th>Vanaf</th></tr></thead><tbody>
      ${entries.map((e) => `<tr>
        <td>${new Date(e.at * 1000).toLocaleString("nl-NL")}</td>
        <td>${esc(e.user_email || "—")}</td><td>${esc(e.action)}</td>
        <td>${esc(e.target || e.detail || "—")}</td><td class="mono">${esc(e.ip || "—")}</td>
      </tr>`).join("")}</tbody></table></div>`;
  }

  function soonView(tab) {
    return `<div class="panel"><div class="empty"><div class="big">${ICON[tab.icon]}</div>
      <div>${esc(tab.title)} — nog niet gebouwd</div>
      <div style="font-size:12.5px;margin-top:8px;max-width:520px;margin-inline:auto;line-height:1.6">
        ${esc(tab.soon)}</div></div></div>`;
  }

  async function render() {
    const tab = TABS.find((t) => t.id === state.tab) || TABS[0];
    $("page-title").textContent = tab.title;
    $("page-sub").textContent = tab.sub;
    $("crumb").textContent = tab.label;
    renderNav();

    $("page-actions").innerHTML = (tab.id === "orgs" && state.me.is_admin)
      ? `<button class="btn sm" id="add-org">${ICON.plus} Klant toevoegen</button>` : "";

    if (tab.id === "orgs") $("view").innerHTML = orgsView();
    else if (tab.id === "audit") $("view").innerHTML = await auditView();
    else $("view").innerHTML = soonView(tab);

    const add = $("add-org");
    if (add) add.onclick = async () => {
      const name = prompt("Naam van de klant");
      if (!name) return;
      try {
        await api("/api/orgs", { method: "POST", headers: { "Content-Type": "application/json" },
                                 body: JSON.stringify({ name }) });
        state.orgs = await api("/api/orgs");
        render();
      } catch (e) { alert(e.message); }
    };
  }

  // ---- boot ----
  (async function boot() {
    $("brand-logo").innerHTML = ICON.file;
    initTheme();
    state.me = await api("/api/me");
    state.orgs = await api("/api/orgs");
    const name = state.me.display_name || state.me.email.split("@")[0];
    $("user-name").textContent = name;
    $("user-email").textContent = state.me.email;
    $("avatar").textContent = name.slice(0, 2).toUpperCase();
    $("avatar").style.background = "var(--accent)";
    $("logout-btn").innerHTML = ICON.logout;
    render();
  })();
})();
