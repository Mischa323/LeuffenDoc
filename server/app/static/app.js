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

  const state = { me: null, orgs: [], org: null, tab: "klanten", item: null };

  // Top level: only what is not tied to a single customer.
  const GLOBAL = [
    { id: "klanten", label: "Klanten", icon: "building", title: "Klanten",
      sub: "Kies een klant om zijn documentatie te openen" },
    { id: "types", label: "Documenttypes", icon: "layers", title: "Documenttypes",
      sub: "Zelf samengestelde types, voor al je klanten", admin: true },
    { id: "logboek", label: "Logboek", icon: "history", title: "Logboek",
      sub: "Wie heeft wat bekeken en gewijzigd", admin: true },
  ];

  // Inside a customer. `kinds` names what a section lists; a section without it
  // is not built yet and says so rather than pretending.
  const ORG = [
    { id: "overzicht", label: "Overzicht", icon: "grid", title: "Overzicht",
      sub: "Wat er van deze klant bekend is" },
    { id: "configuraties", label: "Configuraties", icon: "desktop", title: "Configuraties",
      sub: "De apparatuur van deze klant", kinds: ["computer", "network", "printer"],
      example: "WS-014 of SW-01",
      empty: "Computers, servers, switches, firewalls en printers — met wie ze installeerde en waar ze hangen." },
    { id: "internet", label: "Internetverbindingen", icon: "globe", title: "Internetverbindingen",
      sub: "Lijnen, contracten en storingsnummers", kinds: ["internet"],
      example: "KPN glasvezel hoofdkantoor",
      empty: "Provider, snelheid, vast IP-blok, contract en wie je belt als de lijn eruit ligt." },
    { id: "locaties", label: "Locaties", icon: "building", title: "Locaties",
      sub: "Vestigingen en panden", kinds: ["location"], example: "Hoofdkantoor",
      empty: "Panden met hun adres en hoe je er binnenkomt. Apparatuur wijst hiernaar." },
    { id: "contacten", label: "Contactpersonen", icon: "user", title: "Contactpersonen",
      sub: "Wie je bij deze klant belt", kinds: ["contact"], example: "Jan de Vries",
      empty: "De mensen bij deze klant, met hun functie en nummer." },
    { id: "wachtwoorden", label: "Wachtwoorden", icon: "key", title: "Wachtwoorden",
      sub: "Versleutelde kluis van deze klant", kinds: ["password"],
      example: "Beheerder firewall",
      empty: "Wachtwoorden worden versleuteld opgeslagen en zijn te koppelen aan het apparaat of de lijn waar ze bij horen. Tonen en kopiëren komt altijd in het logboek." },
    { id: "documenten", label: "Documenten", icon: "file", title: "Documenten",
      sub: "Procedures en uitleg die niet in velden past", kinds: ["document"],
      example: "Herstart van de terminalserver",
      empty: "Voor wat niet in velden past: procedures, uitleg, hoe je iets herstart om drie uur ’s nachts. Te koppelen aan de apparatuur waar ze over gaan." },
  ];

  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (res.status === 401) { location.href = "/auth/login"; throw new Error("niet aangemeld"); }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `${res.status}`);
    return body;
  }

  // A short word after an action. Without it a save looks exactly like a
  // button that did nothing.
  let toastTimer = null;
  function toast(message) {
    let el = $("toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "toast";
      el.className = "toast";
      document.body.appendChild(el);
    }
    el.innerHTML = `${ICON.check}<span>${esc(message)}</span>`;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
  }

  const Items = window.DocItems({ api, esc, go, toast });

  /* Types defined here become sections inside a customer, after the built-in
     ones. They are rebuilt rather than reloaded, so making a type and using it
     is one continuous thing. */
  async function rebuildSections() {
    const KINDS = await Items.kinds(true);
    for (let i = ORG.length - 1; i >= 0; i--) {
      if (ORG[i].own) ORG.splice(i, 1);
    }
    for (const [id, spec] of Object.entries(KINDS)) {
      if (!spec.custom) continue;
      ORG.push({
        id: `t-${id}`, own: true, kinds: [id],
        label: spec.plural, title: spec.plural, icon: spec.icon,
        sub: spec.sub || `De ${spec.plural.toLowerCase()} van deze klant`,
        example: spec.label,
        empty: spec.sub || `Nog geen ${spec.plural.toLowerCase()} vastgelegd.`,
      });
    }
    return KINDS;
  }

  const Types = window.DocTypes({ api, esc, toast, kinds: Items.kinds,
                                  refresh: rebuildSections });

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
    const parts = location.hash.split("?")[0].replace(/^#\/?/, "").split("/").filter(Boolean);
    if (parts[0] === "zoeken") {
      state.org = null;
      state.item = null;
      state.tab = "zoeken";
      render();
      return;
    }
    if (parts[0] === "klant" && parts[1]) {
      state.org = state.orgs.find((o) => o.id === parts[1]) || null;
      // `.../item/<id>` opens one thing; everything else is a section.
      if (state.org && parts[2] === "item" && parts[3]) {
        state.item = parts[3];
        state.tab = "overzicht";
      } else {
        state.item = null;
        state.tab = state.org && ORG.some((t) => t.id === parts[2]) ? parts[2] : "overzicht";
      }
    } else {
      state.item = null;
      state.org = null;
      const tabs = tabsHere();
      state.tab = tabs.some((t) => t.id === parts[0]) ? parts[0] : "klanten";
    }
    render();
  }

  // ---- pieces ----
  /* A customer's mark, with the RMM's own shield on it when the two are
     linked. On a list of twenty customers the one that is *not* linked is what
     you are looking for, and a badge is quicker to scan than a line of text. */
  function orgMark(name, big, linked) {
    const initials = name.trim().split(/\s+/).slice(0, 2).map((w) => w[0] || "").join("").toUpperCase();
    // A stable colour per customer, so the same one always looks the same.
    let h = 0;
    for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360;
    const badge = linked
      ? `<span class="oc-rmm" title="Gekoppeld aan de Leuffen RMM">${ICON.shield}</span>` : "";
    return `<span class="oc-mark" style="background:hsl(${h} 55% 45%)${big ? ";width:46px;height:46px;font-size:17px" : ""}">${esc(initials)}${badge}</span>`;
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
    const link = state.me.is_admin ? `<div id="rmm-status"></div>` : "";
    const add = state.me.is_admin ? `
      <div class="panel" id="new-org" style="padding:16px;margin-bottom:16px;display:none">
        <div style="display:flex;gap:8px;align-items:center">
          <input class="inp" id="new-org-name" placeholder="Naam van de klant" style="flex:1" />
          <button class="btn sm" id="new-org-save">Aanmaken</button>
          <button class="btn ghost sm" id="new-org-cancel">Annuleren</button>
        </div></div>` : "";
    if (!state.orgs.length) {
      return note + link + add + `<div class="panel"><div class="empty"><div class="big">${ICON.building}</div>
        <div>Nog geen klanten</div>
        <div style="font-size:12.5px;margin-top:6px">${state.me.is_admin
          ? "Maak er een aan — documentatie en wachtwoorden horen altijd bij een klant."
          : "Vraag een beheerder om je toegang te geven."}</div></div></div>`;
    }
    return note + link + add + `<div class="cards">${state.orgs.map((o) => `
      <div class="orgcard" data-org="${esc(o.id)}">
        <div class="oc-head">${orgMark(o.name, false, o.rmm_org_id)}
          <div><h3>${esc(o.name)}</h3>
            <small>${o.rmm_org_id
              ? `<span class="oc-link">${ICON.shield} gekoppeld aan de RMM</span>`
              : "alleen in LeuffenDoc"}</small></div>
          <span class="oc-arrow">${ICON.chevR}</span>
        </div>
      </div>`).join("")}</div>`;
  }

  async function overviewView() {
    const o = state.org;
    const initials = o.name.trim().split(/\s+/).slice(0, 2).map((w) => w[0] || "").join("").toUpperCase();
    let h = 0;
    for (const ch of o.name) h = (h * 31 + ch.charCodeAt(0)) % 360;
    const summary = await api(`/api/orgs/${o.id}/summary`).catch(() => ({ counts: {} }));
    const counts = summary.counts || {};
    const sections = ORG.filter((t) => t.id !== "overzicht");

    // Dates only earn their keep if they come and find you.
    const due = await Items.expiring(o.id).catch(() => []);
    const dueBlock = due.length ? `<div class="callout warn" style="margin-bottom:16px">
        <div class="ic">${ICON.clock}</div><div style="flex:1">
        <div class="ct">${due.length === 1 ? "Er loopt iets af" : `Er lopen ${due.length} dingen af`}</div>
        <div class="cd"><div class="due-list">${due.slice(0, 8).map((d) => `
          <div class="due-row" data-item="${esc(d.item.id)}">
            <span class="due-name">${esc(d.item.name)}</span>
            <span class="muted">${esc(d.field.label.toLowerCase())}</span>
            <span class="tag warn">${esc(d.flag.text)}</span>
            <span class="muted">${new Date(d.on).toLocaleDateString("nl-NL")}</span>
          </div>`).join("")}</div>
          ${due.length > 8 ? `<div class="muted" style="margin-top:8px">en nog ${due.length - 8}</div>` : ""}
        </div></div></div>` : "";
    return dueBlock + `<div class="panel" style="padding:20px;margin-bottom:16px">
        <div class="org-head">
          <span class="mark" style="background:hsl(${h} 55% 45%)">${esc(initials)}
            ${o.rmm_org_id ? `<span class="oc-rmm" title="Gekoppeld aan de Leuffen RMM">${ICON.shield}</span>` : ""}</span>
          <div><h3>${esc(o.name)}</h3>
            <small>${o.rmm_org_id
              ? `<span class="oc-link">${ICON.shield} gekoppeld aan de RMM (<span class="mono">${esc(o.rmm_org_id)}</span>)</span>`
              : "nog niet gekoppeld aan een organisatie in de RMM"}</small></div>
        </div></div>
      <div class="cards">
        ${sections.map((t) => {
          const n = (t.kinds || []).reduce((sum, k) => sum + (counts[k] || 0), 0);
          const what = t.kinds ? (n === 1 ? "1 vastgelegd" : `${n} vastgelegd`) : "nog niet gebouwd";
          return `<div class="orgcard" data-tab="${t.id}">
            <div class="oc-head"><span class="oc-mark" style="background:var(--surface-3);color:var(--text-dim)">${ICON[t.icon]}</span>
              <div><h3>${esc(t.label)}</h3><small>${esc(what)}</small></div>
              <span class="oc-arrow">${ICON.chevR}</span></div>
          </div>`;
        }).join("")}
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
    if (state.tab === "zoeken") { await searchView(); return; }
    const tab = tabsHere().find((t) => t.id === state.tab) || tabsHere()[0];
    state.tab = tab.id;
    $("page-title").textContent = state.org && tab.id === "overzicht" ? state.org.name : tab.title;
    $("page-sub").textContent = tab.sub;
    crumbs();
    renderNav();
    $("page-actions").innerHTML = "";

    if (state.org) {
      // One open thing: which section it belongs to follows from its kind, so
      // the sidebar keeps pointing at where you came from.
      if (state.item) {
        $("view").innerHTML = `<div class="panel"><div class="empty">Laden…</div></div>`;
        let item = null;
        try {
          item = await Items.detailView($("view"), state.org, state.item);
        } catch (e) {
          $("view").innerHTML = `<div class="callout warn"><div class="ic">${ICON.alert}</div>
            <div><div class="ct">Niet gevonden</div><div class="cd">${esc(e.message)}</div></div></div>`;
          return;
        }
        const section = ORG.find((t) => (t.kinds || []).includes(item.kind));
        if (section) {
          state.tab = section.id;
          renderNav();
          $("page-actions").innerHTML =
            `<button class="btn ghost sm" id="back-list">${ICON.chevR} Terug naar ${esc(section.label.toLowerCase())}</button>`;
          $("back-list").onclick = () => go(`#/klant/${state.org.id}/${section.id}`);
          $("back-list").querySelector("svg").style.transform = "rotate(180deg)";
        }
        $("page-title").textContent = item.name;
        $("page-sub").textContent = section ? section.title : "";
        return;
      }

      if (tab.kinds) {
        $("page-actions").innerHTML =
          `<button class="btn sm" id="add-item">${ICON.plus} Toevoegen</button>`;
        await Items.listView($("view"), state.org, tab);
        $("add-item").onclick = () => Items.openCreate(state.org, tab, $("view"));
        if (tab.id === "wachtwoorden" && state.me.is_admin) await showVaultKey();
        return;
      }

      if (tab.id === "overzicht") {
        $("view").innerHTML = await overviewView();
        $("view").querySelectorAll("[data-tab]").forEach((el) => {
          el.onclick = () => go(`#/klant/${state.org.id}/${el.dataset.tab}`);
        });
        $("view").querySelectorAll(".due-row").forEach((el) => {
          el.onclick = () => go(`#/klant/${state.org.id}/item/${el.dataset.item}`);
        });
        return;
      }
      $("view").innerHTML = soonView(tab);
      return;
    }

    $("page-actions").innerHTML = (tab.id === "klanten" && state.me.is_admin)
      ? `<button class="btn sm" id="add-org">${ICON.plus} Klant toevoegen</button>` : "";

    if (tab.id === "logboek") { $("view").innerHTML = await auditView(); return; }
    if (tab.id === "types") {
      $("page-actions").innerHTML =
        `<button class="btn sm" id="new-type">${ICON.plus} Type toevoegen</button>`;
      await Types.view($("view"));
      $("new-type").onclick = () => { Types.start(); render(); };
      return;
    }

    $("view").innerHTML = orgsView();
    $("view").querySelectorAll(".orgcard[data-org]").forEach((card) => {
      card.onclick = () => go(`#/klant/${card.dataset.org}`);
    });
    wireNewOrg();
    showRmmLink();
  }

  /* Results span customers, so each one says whose it is: the usual question is
     the other way round — you have a serial number or a MAC in your hand and
     want to know where it belongs. */
  function query() {
    return new URLSearchParams(location.hash.split("?")[1] || "").get("q") || "";
  }

  function mark(text, needle) {
    const at = text.toLowerCase().indexOf(needle.toLowerCase());
    if (at < 0 || !needle) return esc(text);
    return esc(text.slice(0, at)) + "<mark>" + esc(text.slice(at, at + needle.length))
      + "</mark>" + esc(text.slice(at + needle.length));
  }

  async function searchView() {
    const q = query();
    $("page-title").textContent = "Zoeken";
    $("page-sub").textContent = q ? `Resultaten voor “${q}”` : "Zoek over al je klanten heen";
    $("page-actions").innerHTML = "";
    crumbs();
    renderNav();
    $("search-input").value = q;

    if (!q) { $("view").innerHTML = ""; return; }
    $("view").innerHTML = `<div class="panel"><div class="empty">Zoeken…</div></div>`;
    let found;
    try { found = await api("/api/search?q=" + encodeURIComponent(q)); }
    catch (e) { $("view").innerHTML = `<div class="callout warn"><div class="ic">${ICON.alert}</div>
      <div><div class="ct">Zoeken lukte niet</div><div class="cd">${esc(e.message)}</div></div></div>`; return; }

    if (found.short) {
      $("view").innerHTML = `<div class="panel"><div class="empty">
        <div>Typ er nog een letter bij</div>
        <div style="font-size:12.5px;margin-top:6px">Vanaf twee tekens wordt er gezocht.</div>
      </div></div>`;
      return;
    }
    if (!found.results.length) {
      $("view").innerHTML = `<div class="panel"><div class="empty"><div class="big">${ICON.search}</div>
        <div>Niets gevonden voor “${esc(q)}”</div>
        <div style="font-size:12.5px;margin-top:6px">Gezocht is op naam, op alle ingevulde velden,
          op wat de RMM weet, en op de MAC- en IP-adressen van netwerkadapters.</div>
      </div></div>`;
      return;
    }
    const more = found.total > found.results.length
      ? `<div class="muted" style="padding:12px 18px">${found.total} gevonden, de eerste ${found.results.length} staan hier.</div>`
      : "";
    $("view").innerHTML = `<div class="panel">${found.results.map((r) => `
        <div class="hit" data-org="${esc(r.org_id)}" data-item="${esc(r.id)}">
          <div class="hit-top">${ICON[(KINDS[r.kind] || {}).icon || "file"]}
            <span class="hit-name">${mark(r.name, q)}</span>
            <span class="muted">${esc((KINDS[r.kind] || {}).label || r.kind)}</span>
            ${r.archived ? '<span class="tag">afgevoerd</span>' : ""}
            <span class="hit-org">${esc(r.org_name)}</span></div>
          <div class="hit-why">${r.hits.map((h) =>
            `<span><b>${esc(h.where)}:</b> ${mark(h.text, q)}</span>`).join("")}</div>
        </div>`).join("")}${more}</div>`;
    $("view").querySelectorAll(".hit").forEach((hit) => {
      hit.onclick = () => go(`#/klant/${hit.dataset.org}/item/${hit.dataset.item}`);
    });
  }

  let KINDS = {};

  function wireSearch() {
    const field = $("search-input");
    $("search-ico").innerHTML = ICON.search;
    const run = () => {
      const q = field.value.trim();
      go(q ? `#/zoeken?q=${encodeURIComponent(q)}` : "#/klanten");
    };
    field.addEventListener("keydown", (e) => {
      if (e.key === "Enter") run();
      if (e.key === "Escape") { field.value = ""; field.blur(); }
    });
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        field.focus();
        field.select();
      }
    });
  }

  // The customer list is where a customer that should have come from the RMM is
  // missed, so it is where the state of that link belongs.
  function ago(seconds) {
    if (seconds < 90) return "zojuist";
    const m = Math.round(seconds / 60);
    if (m < 90) return `${m} min geleden`;
    return `${Math.round(m / 60)} uur geleden`;
  }

  async function showRmmLink() {
    const host = $("rmm-status");
    if (!host) return;
    let s;
    try { s = await api("/api/rmm/status"); } catch (e) { return; }
    if (!s.configured) {
      host.innerHTML = `<div class="callout info" style="margin-bottom:16px">
        <div class="ic">${ICON.info}</div><div>
        <div class="ct">Niet gekoppeld aan de RMM</div>
        <div class="cd">Met <code>DOC_RMM_URL</code> en <code>DOC_RMM_API_KEY</code> melden mensen zich aan met hun RMM-account, en komen klanten en toegang vanzelf mee.</div></div></div>`;
      return;
    }
    const when = s.at ? ago(Date.now() / 1000 - s.at) : "nog niet";
    const bad = s.ok === false;
    host.innerHTML = `<div class="callout ${bad ? "warn" : "info"}" style="margin-bottom:16px">
      <div class="ic">${bad ? ICON.alert : ICON.refresh}</div><div style="flex:1">
      <div class="ct">${bad ? "De RMM antwoordt niet" : "Gekoppeld aan de RMM"}</div>
      <div class="cd">${bad ? esc(s.detail) : `${s.users} gebruikers en ${s.orgs} klanten, bijgewerkt ${when}. Elke ${s.every_minutes} minuten opnieuw.`}
        <button class="btn ghost sm" id="sync-now" style="margin-left:10px">Nu bijwerken</button></div>
      </div></div>`;
    $("sync-now").onclick = async () => {
      $("sync-now").disabled = true;
      try {
        await api("/api/rmm/sync", { method: "POST" });
        state.orgs = await api("/api/orgs");
        render();
      } catch (e) { alert(e.message); }
    };
  }

  /* Where the vault's master key lives. An operator who backs up the data
     volume should know whether that backup also contains the key that opens
     it — the answer decides what a stolen backup is worth. */
  async function showVaultKey() {
    let state_;
    try { state_ = await api("/api/vault"); } catch (e) { return; }
    if (state_.from_environment || !state_.in_database) return;
    const note = document.createElement("div");
    note.className = "callout warn";
    note.style.marginBottom = "16px";
    note.innerHTML = `<div class="ic">${ICON.lock}</div><div>
      <div class="ct">De sleutel van de kluis staat in de database</div>
      <div class="cd">Er is er een aangemaakt omdat <code>DOC_SECRET_KEY</code> niet is ingesteld.
        Dat werkt, maar een back-up van het datavolume bevat dan zowel de kluis als de sleutel.
        Zet <code>DOC_SECRET_KEY</code> en bewaar hem elders — dat moet gebeuren
        <b>voordat</b> je de kluis gaat vullen, want met een andere sleutel gaan bestaande
        wachtwoorden niet meer open.</div></div>`;
    $("view").prepend(note);
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
    KINDS = await rebuildSections();
    wireSearch();
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
