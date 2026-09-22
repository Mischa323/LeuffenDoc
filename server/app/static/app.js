/* LeuffenDoc — the shell.

   Two levels, because documentation only means anything in the context of a
   customer: the start is the customer list, and a customer's documents, its
   passwords and the rest only appear once you are inside one. What stays at the
   top is what genuinely spans customers — the document types everyone shares,
   and the audit log.

   Where you are lives in the URL (`#/klant/<id>/documenten`), so the back
   button, a refresh and a copied link all land where you expect. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const state = { me: null, orgs: [], org: null, tab: "klanten" };

  // Top level: only what is not tied to a single customer.
  const GLOBAL = [
    { id: "klanten", label: "Klanten", icon: "building", title: "Klanten",
      sub: "Kies een klant om zijn documentatie te openen" },
    { id: "types", label: "Documenttypes", icon: "layers", title: "Documenttypes",
      sub: "Zelf samengestelde types, voor al je klanten", admin: true,
      soon: "Hiermee maak je je eigen documentatiepunten: kies de velden die erin horen — tekst, keuze, datum, wachtwoord, een link naar een apparaat — en elke klant krijgt dezelfde structuur." },
    { id: "logboek", label: "Logboek", icon: "history", title: "Logboek",
      sub: "Wie heeft wat bekeken en gewijzigd", admin: true },
  ];

  // Inside a customer.
  const ORG = [
    { id: "overzicht", label: "Overzicht", icon: "grid", title: "Overzicht",
      sub: "Wat er van deze klant bekend is" },
    { id: "documenten", label: "Documenten", icon: "file", title: "Documenten",
      sub: "Pagina's, mappen en bijlagen van deze klant",
      soon: "Documenten met een editor, mappen, labels, versies om op terug te vallen en zoeken over alles heen." },
    { id: "wachtwoorden", label: "Wachtwoorden", icon: "key", title: "Wachtwoorden",
      sub: "Versleutelde kluis van deze klant",
      soon: "Wachtwoorden worden versleuteld opgeslagen met een sleutel per klant. Tonen en kopiëren is een apart recht, en komt altijd in het logboek." },
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

  // ---- where we are ----
  function tabsHere() {
    return state.org ? ORG : GLOBAL.filter((t) => !t.admin || state.me.is_admin);
  }

  function go(hash) {
    if (location.hash === hash) route();      // same place: re-render anyway
    else location.hash = hash;
  }

  function route() {
    const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
    if (parts[0] === "klant" && parts[1]) {
      state.org = state.orgs.find((o) => o.id === parts[1]) || null;
      state.tab = state.org && ORG.some((t) => t.id === parts[2]) ? parts[2] : "overzicht";
    } else {
      state.org = null;
      const tabs = tabsHere();
      state.tab = tabs.some((t) => t.id === parts[0]) ? parts[0] : "klanten";
    }
    render();
  }

  // ---- pieces ----
  function orgMark(name, big) {
    const initials = name.trim().split(/\s+/).slice(0, 2).map((w) => w[0] || "").join("").toUpperCase();
    // A stable colour per customer, so the same one always looks the same.
    let h = 0;
    for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360;
    return `<span class="oc-mark" style="background:hsl(${h} 55% 45%)${big ? ";width:46px;height:46px;font-size:17px" : ""}">${esc(initials)}</span>`;
  }

  function renderNav() {
    $("nav-label").textContent = state.org ? "Deze klant" : "Overzicht";
    $("nav").innerHTML = tabsHere().map((t) =>
      `<button data-tab="${t.id}"${t.id === state.tab ? ' class="active"' : ""}>
         ${ICON[t.icon]} ${t.label}${t.id === "klanten" ? `<span class="count">${state.orgs.length}</span>` : ""}
       </button>`).join("")
      + (state.org ? `<button data-back="1" style="margin-top:10px">
           <span class="back-ico">${ICON.chevR}</span> Alle klanten</button>` : "");
    $("nav").querySelectorAll("button").forEach((b) => {
      b.onclick = () => go(b.dataset.back ? "#/klanten"
                                          : (state.org ? `#/klant/${state.org.id}/${b.dataset.tab}`
                                                       : `#/${b.dataset.tab}`));
    });
  }

  function crumbs() {
    $("crumb-home").className = state.org ? "" : "here";
    $("crumb-home").onclick = () => go("#/klanten");
    $("crumb-sep").classList.toggle("hidden", !state.org);
    $("crumb-org").classList.toggle("hidden", !state.org);
    if (state.org) $("crumb-org").textContent = state.org.name;
  }

  // ---- views ----
  function orgsView() {
    // A button that simply isn't there reads as a broken button. Say why.
    const note = state.me.is_admin ? "" : `<div class="callout info" style="margin-bottom:16px">
        <div class="ic">${ICON.info}</div><div>
        <div class="ct">Je kunt geen klanten toevoegen</div>
        <div class="cd">Daar is beheerderstoegang voor nodig, en die heeft je account (<b class="mono">${esc(state.me.email)}</b>) niet. Vraag een beheerder, of zet je adres in <code>DOC_BOOTSTRAP_ADMIN</code>.</div></div></div>`;
    const add = state.me.is_admin ? `
      <div class="panel" id="new-org" style="padding:16px;margin-bottom:16px;display:none">
        <div style="display:flex;gap:8px;align-items:center">
          <input class="inp" id="new-org-name" placeholder="Naam van de klant" style="flex:1" />
          <button class="btn sm" id="new-org-save">Aanmaken</button>
          <button class="btn ghost sm" id="new-org-cancel">Annuleren</button>
        </div></div>` : "";
    if (!state.orgs.length) {
      return note + add + `<div class="panel"><div class="empty"><div class="big">${ICON.building}</div>
        <div>Nog geen klanten</div>
        <div style="font-size:12.5px;margin-top:6px">${state.me.is_admin
          ? "Maak er een aan — documentatie en wachtwoorden horen altijd bij een klant."
          : "Vraag een beheerder om je toegang te geven."}</div></div></div>`;
    }
    return note + add + `<div class="cards">${state.orgs.map((o) => `
      <div class="orgcard" data-org="${esc(o.id)}">
        <div class="oc-head">${orgMark(o.name)}
          <div><h3>${esc(o.name)}</h3>
            <small>${o.rmm_org_id ? "gekoppeld aan de RMM" : "alleen in LeuffenDoc"}</small></div>
          <span class="oc-arrow">${ICON.chevR}</span>
        </div>
      </div>`).join("")}</div>`;
  }

  function overviewView() {
    const o = state.org;
    const initials = o.name.trim().split(/\s+/).slice(0, 2).map((w) => w[0] || "").join("").toUpperCase();
    let h = 0;
    for (const ch of o.name) h = (h * 31 + ch.charCodeAt(0)) % 360;
    return `<div class="panel" style="padding:20px;margin-bottom:16px">
        <div class="org-head">
          <span class="mark" style="background:hsl(${h} 55% 45%)">${esc(initials)}</span>
          <div><h3>${esc(o.name)}</h3>
            <small>${o.rmm_org_id
              ? `gekoppeld aan de RMM (<span class="mono">${esc(o.rmm_org_id)}</span>)`
              : "nog niet gekoppeld aan een organisatie in de RMM"}</small></div>
        </div></div>
      <div class="cards">
        ${[["documenten", "file", "Documenten", "Pagina's over deze klant"],
           ["wachtwoorden", "key", "Wachtwoorden", "De kluis van deze klant"]]
          .map(([id, icon, title, sub]) => `
          <div class="orgcard" data-tab="${id}">
            <div class="oc-head"><span class="oc-mark" style="background:var(--surface-3);color:var(--text-dim)">${ICON[icon]}</span>
              <div><h3>${title}</h3><small>${sub}</small></div>
              <span class="oc-arrow">${ICON.chevR}</span></div>
          </div>`).join("")}
      </div>`;
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
        `Er komen ${d.forwarded_hops} adressen binnen (<span class="mono">${esc(d.forwarded_for)}</span>). Laat de proxy het adres <b>overschrijven</b> in plaats van aanvullen: <code>proxy_set_header X-Forwarded-For $remote_addr;</code>`]);
    }
    if (d.trust_proxy && d.proxy_ips === "*") {
      rows.push(["warn", "Elk adres mag zich als proxy voordoen",
        "Zet <code>DOC_PROXY_IPS</code> op het adres van je proxy. Anders kan iemand die de container rechtstreeks bereikt zelf bepalen welk adres in het logboek komt."]);
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
    const who = state.org ? ` van ${esc(state.org.name)}` : "";
    return `<div class="panel"><div class="empty"><div class="big">${ICON[tab.icon]}</div>
      <div>${esc(tab.title)}${who} — nog niet gebouwd</div>
      <div style="font-size:12.5px;margin-top:8px;max-width:540px;margin-inline:auto;line-height:1.6">
        ${esc(tab.soon)}</div></div></div>`;
  }

  // ---- render ----
  async function render() {
    const tab = tabsHere().find((t) => t.id === state.tab) || tabsHere()[0];
    state.tab = tab.id;
    $("page-title").textContent = state.org && tab.id === "overzicht" ? state.org.name : tab.title;
    $("page-sub").textContent = tab.sub;
    crumbs();
    renderNav();

    $("page-actions").innerHTML = (!state.org && tab.id === "klanten" && state.me.is_admin)
      ? `<button class="btn sm" id="add-org">${ICON.plus} Klant toevoegen</button>` : "";

    if (state.org) {
      $("view").innerHTML = tab.id === "overzicht" ? overviewView() : soonView(tab);
      $("view").querySelectorAll("[data-tab]").forEach((el) => {
        el.onclick = () => go(`#/klant/${state.org.id}/${el.dataset.tab}`);
      });
      return;
    }
    if (tab.id === "logboek") { $("view").innerHTML = await auditView(); return; }
    if (tab.id === "types") { $("view").innerHTML = soonView(tab); return; }

    $("view").innerHTML = orgsView();
    $("view").querySelectorAll(".orgcard[data-org]").forEach((card) => {
      card.onclick = () => go(`#/klant/${card.dataset.org}`);
    });
    wireNewOrg();
  }

  function wireNewOrg() {
    const panel = $("new-org");
    if (!panel) return;
    const open = (yes) => {
      panel.style.display = yes ? "block" : "none";
      if (yes) $("new-org-name").focus();
    };
    const add = $("add-org");
    if (add) add.onclick = () => open(panel.style.display === "none");
    $("new-org-cancel").onclick = () => open(false);
    const save = async () => {
      const name = $("new-org-name").value.trim();
      if (!name) { $("new-org-name").focus(); return; }
      try {
        const org = await api("/api/orgs", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }),
        });
        state.orgs = await api("/api/orgs");
        go(`#/klant/${org.id}`);        // straight into the customer just created
      } catch (e) { alert(e.message); }
    };
    $("new-org-save").onclick = save;
    $("new-org-name").addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
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
    window.addEventListener("hashchange", route);
    route();
  })();
})();
