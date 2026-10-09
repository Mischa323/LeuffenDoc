/* Microsoft 365, split into the parts people look for: the users, the
   licences, the mailboxes, the groups and Teams, SharePoint, the app
   registrations and the security settings -- each a page of its own under
   Microsoft 365 in the sidebar, with a search and the filters that part needs.
   What is shown comes from the customer's tenant items (one, as a rule):
   what the RMM read, or what was typed when there is no RMM. */
window.DocM365 = function (ctx) {
  const { api, esc, go, index } = ctx;

  const PARTS = [
    { id: "gebruikers", label: "Gebruikers", icon: "user", key: "users",
      sub: "Wie er in de tenant zit, met hun licenties" },
    { id: "licenties", label: "Licenties", icon: "clipboard", key: "subscriptions",
      sub: "De abonnementen: hoeveel, hoeveel in gebruik, en wanneer ze verlengen" },
    { id: "mailboxen", label: "Mailboxen", icon: "mail", key: "shared",
      sub: "Gedeelde mailboxen, ruimtes en apparatuur — en wie erbij kan" },
    { id: "groepen", label: "Groepen & Teams", icon: "nodes", key: "groups",
      sub: "Teams, Microsoft 365-groepen, distributielijsten en beveiligingsgroepen, met hun leden" },
    { id: "sharepoint", label: "SharePoint", icon: "folder", key: "sites", sub: "De sites" },
    { id: "apps", label: "App-registraties", icon: "key", key: "apps",
      sub: "Secrets en certificaten, en wanneer ze verlopen" },
    { id: "beveiliging", label: "Beveiliging", icon: "shield", key: null,
      sub: "Security defaults, MFA, Conditional Access en het noodaccount" },
  ];

  // A tenant's value for a field: what the RMM read where it keeps it, what
  // was typed otherwise.
  const value = (item, key) => {
    const r = item.rmm || {};
    return item.source === "m365" && Array.isArray(r.holds) && r.holds.includes(key) ? r[key] : (item.fields || {})[key];
  };
  const rowsOf = (tenants, key) => tenants.flatMap((t) => (Array.isArray(value(t, key)) ? value(t, key) : [])
    .map((r) => ({ ...r, __tenant: t })));
  const when = (s) => (s ? new Date(s * 1000).toLocaleString("nl-NL") : "");

  function days(date) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date || "")) return null;
    const [y, m, d] = date.split("-").map(Number);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    return Math.round((new Date(y, m - 1, d) - today) / 86400000);
  }
  function dateCell(date, warn) {
    const n = days(date);
    if (n === null) return esc(date || "");
    const shown = new Date(date + "T00:00:00").toLocaleDateString("nl-NL");
    const tag = n < 0 ? `<span class="tag bad">verlopen</span>` : n <= warn ? `<span class="tag warn">nog ${n} ${n === 1 ? "dag" : "dagen"}</span>` : "";
    return `${esc(shown)} ${tag}`;
  }

  /* One page: chips to filter, a search, a table. `columns`: [label,
     (row) => html]; `filters`: [{id, label, test(row)}]; `hay(row)`: what the
     search looks in. */
  function table(host, { rows, columns, filters, hay, empty, chosen, onChoose, after }) {
    let filter = chosen || (filters && filters[0] ? filters[0].id : null);
    let words = [];
    const draw = () => {
      const f = (filters || []).find((x) => x.id === filter);
      const shown = rows.filter((r) => (!f || f.test(r)) && words.every((w) => hay(r).toLowerCase().includes(w)));
      host.querySelector(".m3-body").innerHTML = shown.length ? `<div class="tview-scroll"><table class="tview-table m3-table">
          <thead><tr>${columns.map(([label]) => `<th>${esc(label)}</th>`).join("")}</tr></thead>
          <tbody>${shown.map((r) => `<tr>${columns.map(([, cell]) => `<td>${cell(r)}</td>`).join("")}</tr>`).join("")}</tbody>
        </table></div>` : `<div class="empty">${rows.length ? "Niets gevonden" : esc(empty)}</div>`;
      host.querySelector(".m3-count").textContent = rows.length ? `${shown.length} van ${rows.length}` : "";
      host.querySelectorAll("[data-filter]").forEach((b) => b.classList.toggle("on", b.dataset.filter === filter));
      host.querySelectorAll("[data-goto-part]").forEach((a) => { a.onclick = () => onChoose && onChoose(a.dataset.gotoPart, a.dataset.value); });
    };
    host.innerHTML = `<div class="panel m3">
        <div class="m3-bar">
          ${filters ? `<div class="chips">${filters.map((x) => `<button class="chip" data-filter="${esc(x.id)}">${esc(x.label)}
            <span class="n">${rows.filter(x.test).length}</span></button>`).join("")}</div>` : ""}
          <span class="spacer"></span>
          <input class="inp m3-search" type="search" placeholder="Zoeken…" aria-label="Zoeken" />
          <span class="m3-count muted"></span>
        </div>
        <div class="m3-body"></div>
      </div>${after || ""}`;
    host.querySelectorAll("[data-filter]").forEach((b) => { b.onclick = () => { filter = b.dataset.filter; draw(); }; });
    host.querySelector(".m3-search").oninput = (ev) => { words = ev.target.value.toLowerCase().split(/\s+/).filter(Boolean); draw(); };
    draw();
  }

  /* The page of one part. Returns {title, sub} for the page head, and the
     tenant to go to (when there is one). */
  async function page(host, org, partId, params, warnDays) {
    const part = PARTS.find((p) => p.id === partId) || PARTS[0];
    const tenants = (await index(org.id)).filter((i) => i.kind === "m365" && !i.archived);
    const several = tenants.length > 1;
    const tenantCol = several ? [["Tenant", (r) => esc(r.__tenant.name)]] : [];
    const read = tenants.filter((t) => t.source === "m365" && t.rmm && t.rmm.read_at)
      .map((t) => `${several ? `${t.name}: ` : ""}gelezen door de RMM ${when(t.rmm.read_at)}`).join(" · ");
    const goPart = (id, v) => go(`#/klant/${org.id}/microsoft365?deel=${id}${v ? `&licentie=${encodeURIComponent(v)}` : ""}`);
    const head = { title: part.label, sub: `Microsoft 365${read ? ` · ${read}` : ""}`, tenant: tenants.length === 1 ? tenants[0] : null };
    if (!tenants.length) {
      host.innerHTML = `<div class="panel"><div class="empty">
          <div>Deze klant heeft nog geen Microsoft 365-tenant.</div>
          <div style="font-size:12.5px;margin-top:6px">Koppel hem in de RMM (klant → Microsoft 365), of maak hem aan onder <b>Microsoft 365</b>.</div>
        </div></div>`;
      return head;
    }

    if (part.id === "gebruikers") {
      const rows = rowsOf(tenants, "users");
      const licence = params.get("licentie");
      const lic = (r) => String(r.licenses || "");
      const filters = [
        { id: "alle", label: "Alle", test: () => true },
        { id: "aan", label: "Kan aanmelden", test: (r) => r.enabled !== "Nee" },
        { id: "uit", label: "Geblokkeerd", test: (r) => r.enabled === "Nee" },
        { id: "gast", label: "Gasten", test: (r) => r.kind === "Gast" },
        { id: "zonder", label: "Zonder licentie", test: (r) => !lic(r) },
      ];
      if (licence) filters.unshift({ id: "licentie", label: licence, test: (r) => lic(r).split(", ").includes(licence) });
      table(host, {
        rows, filters, chosen: licence ? "licentie" : "alle", empty: "Nog geen gebruikers.",
        hay: (r) => `${r.name} ${r.account} ${lic(r)} ${r.job || ""}`,
        columns: [["Naam", (r) => `<b>${esc(r.name)}</b>${r.kind === "Gast" ? ' <span class="tag">gast</span>' : ""}`],
                  ["Account", (r) => `<span class="mono">${esc(r.account || "")}</span>`],
                  ["Licenties", (r) => esc(lic(r) || "—")], ["Functie", (r) => esc(r.job || "")],
                  ["Kan aanmelden", (r) => (r.enabled === "Nee" ? '<span class="tag warn">geblokkeerd</span>' : "ja")],
                  ...tenantCol],
      });
      if (licence) head.sub = `Met ${licence} · ${head.sub}`;
    } else if (part.id === "licenties") {
      const rows = rowsOf(tenants, "subscriptions");
      const users = rowsOf(tenants, "users");
      const holders = (product) => users.filter((u) => String(u.licenses || "").split(", ").includes(product)).length;
      table(host, {
        rows, empty: "Nog geen abonnementen.", onChoose: goPart,
        hay: (r) => `${r.product} ${r.status || ""}`,
        filters: [{ id: "alle", label: "Alle", test: () => true },
                  { id: "vrij", label: "Met vrije licenties", test: (r) => Number(r.seats || 0) > Number(r.used || 0) },
                  { id: "aandacht", label: "Vraagt aandacht", test: (r) => (r.status && r.status !== "Actief") || (days(r.renews) ?? 999) <= warnDays }],
        columns: [["Product", (r) => `<b>${esc(r.product)}</b>`],
                  ["Aantal", (r) => esc(r.seats ?? "")], ["In gebruik", (r) => esc(r.used ?? "")],
                  ["Vrij", (r) => { const n = Number(r.seats || 0) - Number(r.used || 0); return n > 0 ? `<b>${n}</b>` : "0"; }],
                  ["Verlengt op", (r) => dateCell(r.renews, warnDays)],
                  ["Staat", (r) => (r.status && r.status !== "Actief" ? `<span class="tag warn">${esc(r.status)}</span>` : esc(r.status || ""))],
                  ["Gebruikers", (r) => { const n = holders(r.product);
                    return n ? `<a class="m3-link" data-goto-part="gebruikers" data-value="${esc(r.product)}">${n} ${n === 1 ? "gebruiker" : "gebruikers"} →</a>` : "—"; }],
                  ...tenantCol],
        after: `<div class="hint m3-after">Licenties voor andere software staan onder <a class="m3-link" data-section="licenties">Licenties</a>.</div>`,
      });
      const other = host.querySelector("[data-section='licenties']");
      if (other) other.onclick = () => go(`#/klant/${org.id}/licenties`);
    } else if (part.id === "mailboxen") {
      const rows = rowsOf(tenants, "shared");
      const access = rowsOf(tenants, "shared_access");
      const who = (r) => access.filter((a) => (a.mailbox || "").toLowerCase() === (r.mailbox || "").toLowerCase()
        || (a.mailbox || "").toLowerCase() === (r.name || "").toLowerCase());
      table(host, {
        rows, empty: "Nog geen gedeelde mailboxen.",
        hay: (r) => `${r.mailbox} ${r.name} ${who(r).map((a) => a.who).join(" ")}`,
        filters: [{ id: "alle", label: "Alle", test: () => true },
                  { id: "gedeeld", label: "Gedeeld", test: (r) => r.kind === "Gedeeld" },
                  { id: "ruimte", label: "Ruimtes", test: (r) => r.kind === "Ruimte" },
                  { id: "apparatuur", label: "Apparatuur", test: (r) => r.kind === "Apparatuur" }],
        columns: [["Adres", (r) => `<b class="mono">${esc(r.mailbox)}</b>`], ["Naam", (r) => esc(r.name || "")],
                  ["Soort", (r) => esc(r.kind || "")],
                  ["Wie erbij kan", (r) => { const w = who(r);
                    return w.length ? w.map((a) => `${esc(a.who)}${a.rights ? ` <span class="muted">(${esc(a.rights.toLowerCase())})</span>` : ""}`).join("<br>")
                      : '<span class="muted">niet vastgelegd</span>'; }],
                  ...tenantCol],
        after: `<div class="hint m3-after">Wie bij welke mailbox kan, zegt Microsoft Graph niet; dat leg je vast op de tenant zelf
          (<b>Bewerken</b> → Mailboxen).</div>`,
      });
    } else if (part.id === "groepen") {
      const rows = rowsOf(tenants, "groups");
      const members = (r) => String(r.members || "");
      table(host, {
        rows, empty: "Nog geen groepen.",
        hay: (r) => `${r.name} ${r.mail || ""} ${r.kind} ${members(r)}`,
        filters: [{ id: "alle", label: "Alle", test: () => true },
                  { id: "teams", label: "Teams", test: (r) => r.kind === "Team" },
                  { id: "m365", label: "Microsoft 365-groepen", test: (r) => r.kind === "Microsoft 365-groep" },
                  { id: "dist", label: "Distributielijsten", test: (r) => r.kind === "Distributielijst" },
                  { id: "sec", label: "Beveiligingsgroepen", test: (r) => String(r.kind || "").startsWith("Beveiligingsgroep") }],
        columns: [["Naam", (r) => `<b>${esc(r.name)}</b>`], ["Adres", (r) => `<span class="mono">${esc(r.mail || "")}</span>`],
                  ["Soort", (r) => esc(r.kind || "")],
                  ["Leden", (r) => { const m = members(r);
                    if (!m) return '<span class="muted">—</span>';
                    if (m === "dynamisch") return '<span class="tag">dynamisch</span>';
                    const names = m.split(", ");
                    return names.length <= 4 ? esc(m)
                      : `<details class="m3-members"><summary>${esc(names.slice(0, 3).join(", "))} en ${names.length - 3} meer</summary>${esc(m)}</details>`; }],
                  ...tenantCol],
      });
    } else if (part.id === "sharepoint") {
      table(host, {
        rows: rowsOf(tenants, "sites"), empty: "Nog geen SharePoint-sites.", hay: (r) => `${r.name} ${r.url}`,
        columns: [["Site", (r) => `<b>${esc(r.name)}</b>`],
                  ["Adres", (r) => (/^https?:\/\//i.test(r.url || "") ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.url)}</a>` : esc(r.url || ""))],
                  ...tenantCol],
      });
    } else if (part.id === "apps") {
      const rows = rowsOf(tenants, "apps").sort((a, b) => String(a.expires || "9").localeCompare(String(b.expires || "9")));
      table(host, {
        rows, empty: "Nog geen app-registraties met een secret of certificaat.",
        hay: (r) => `${r.app} ${r.name || ""} ${r.kind}`,
        filters: [{ id: "alle", label: "Alle", test: () => true },
                  { id: "binnenkort", label: `Verloopt binnen ${warnDays} dagen`, test: (r) => (days(r.expires) ?? 999) <= warnDays },
                  { id: "secret", label: "Secrets", test: (r) => r.kind === "Secret" },
                  { id: "cert", label: "Certificaten", test: (r) => r.kind === "Certificaat" }],
        columns: [["App", (r) => `<b>${esc(r.app)}</b>`], ["Soort", (r) => esc(r.kind || "")],
                  ["Omschrijving", (r) => esc(r.name || "")], ["Verloopt op", (r) => dateCell(r.expires, warnDays)],
                  ...tenantCol],
      });
    } else if (part.id === "beveiliging") {
      host.innerHTML = tenants.map((t) => {
        const ca = Array.isArray(value(t, "ca")) ? value(t, "ca") : [];
        const line = (label, v) => (v ? `<div class="dt"><span>${esc(label)}</span></div><div class="dd">${esc(v)}</div>` : "");
        return `<div class="panel m3">
            <div class="panel-head"><h2>${esc(t.name)}</h2><span class="spacer"></span>
              ${several ? `<button class="btn ghost sm" data-open="${esc(t.id)}">Naar de tenant</button>` : ""}</div>
            <div class="deflist">
              ${line("Security defaults", value(t, "security_defaults"))}
              ${line("Hoe MFA geregeld is", value(t, "mfa"))}
              ${line("Noodaccount", value(t, "break_glass"))}
              ${line("Partner en GDAP", value(t, "partner"))}
              ${line("Back-up van Microsoft 365", value(t, "backup"))}
            </div>
            <div class="tview"><div class="tview-head"><span>Conditional Access</span><span class="n">${ca.length}</span></div>
              ${ca.length ? `<div class="tview-scroll"><table class="tview-table"><thead><tr><th>Beleid</th><th>Staat</th></tr></thead>
                <tbody>${ca.map((c) => `<tr><td>${esc(c.name)}</td><td>${c.state === "Aan" ? '<span class="tag ok">aan</span>'
                  : c.state === "Uit" ? '<span class="tag">uit</span>' : esc(c.state || "")}</td></tr>`).join("")}</tbody></table></div>`
                : '<div class="muted">Geen beleid — of niet te lezen (dat vraagt Entra ID P1).</div>'}</div>
          </div>`;
      }).join("");
      host.querySelectorAll("[data-open]").forEach((b) => { b.onclick = () => go(`#/klant/${org.id}/item/${b.dataset.open}`); });
    }
    return head;
  }

  return { PARTS, page, value };
};
