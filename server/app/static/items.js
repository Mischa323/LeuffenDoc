/* Everything that gets documented: configurations and the customer's own parts.

   The forms here are not written per kind. The server hands over a catalogue of
   kinds and their fields (see schema.py) and this file renders whatever is in
   it — which is why a new field, or later a type you define yourself, needs no
   change on this side.

   Three things a page always shows, because documentation you cannot trust is
   worse than none: where a value came from (typed here, or the RMM's), what it
   hangs together with, and who changed what. */
window.DocItems = function (ctx) {
  "use strict";

  const { api, esc, go, toast } = ctx;
  const Rack = window.DocRack ? window.DocRack({ api, esc, go, toast }) : null;
  let KINDS = null;
  // Set from Instellingen: how passwords are made, how long one stays on
  // screen, and when a date starts to warn.
  let CONFIG = {};
  const setConfig = (cfg) => { CONFIG = cfg || {}; };
  const indexes = new Map();        // org id -> every item of that customer

  async function kinds(fresh) {
    if (fresh) KINDS = null;
    if (!KINDS) KINDS = await api("/api/kinds");
    return KINDS;
  }

  /* Everything of one customer. Fetched fresh whenever a list, a page or the
     overview is opened -- other people change things too, and a long-open tab
     must not keep showing what was true this morning -- and reused only while
     one view redraws itself. */
  async function index(orgId, fresh) {
    if (fresh) indexes.delete(orgId);
    if (!indexes.has(orgId)) {
      indexes.set(orgId, await api(`/api/orgs/${orgId}/items?archived=true`));
    }
    return indexes.get(orgId);
  }

  const forget = (orgId) => indexes.delete(orgId);

  // Pasting a screenshot onto an item's page, and the photo viewer's keys: one
  // listener each, pointed at whichever item page is open.
  let pasteInto = null;
  let viewerKeys = null;
  function closeViewer() {
    const open = document.getElementById("viewer");
    if (open) open.remove();
    viewerKeys = null;
  }
  window.addEventListener("hashchange", closeViewer);
  document.addEventListener("keydown", (ev) => {
    if (viewerKeys && document.getElementById("viewer")) viewerKeys(ev);
  });
  document.addEventListener("paste", (ev) => {
    if (!pasteInto || !document.getElementById("files-drop")) return;
    const target = ev.target;
    if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
    const pasted = [...((ev.clipboardData && ev.clipboardData.files) || [])];
    if (!pasted.length) return;
    ev.preventDefault();
    // A screenshot comes as "image.png"; give it a name worth finding again.
    const stamp = new Date().toISOString().slice(0, 16).replace(/[T:]/g, "-");
    pasteInto(pasted.map((f, i) => (f.name && f.name !== "image.png") ? f
      : new File([f], `schermafbeelding-${stamp}${pasted.length > 1 ? `-${i + 1}` : ""}.${f.type.split("/")[1] || "png"}`,
                 { type: f.type })));
  });

  // ---- fields ----
  function fieldsOf(kind) {
    const out = [];
    for (const group of KINDS[kind].groups) {
      for (const f of group.fields) out.push({ ...f, group: group.key });
    }
    return out;
  }
  // What a person sees: a field hidden under Instellingen → Documenttypes keeps
  // its value but appears nowhere -- not in a form, a page, a list or a warning.
  const shownFieldsOf = (kind) => fieldsOf(kind).filter((f) => !f.hidden);

  /* The blocks of a page, laid out as chosen under Documenttypes: each the
     full width, or half -- two half blocks side by side. Blocks with nothing
     to show are left out. */
  function blocksHtml(parts) {
    const shown = parts.filter((p) => p.html);
    return shown.length ? `<div class="blocks">${shown.map((p) =>
      p.html.replace(/^(\s*<div class="panel)/, `$1${p.width === "half" ? " half" : ""}`)).join("")}</div>` : "";
  }

  /* Where a value comes from decides who may set it. A field the RMM fills is
     shown from the RMM and never typed here, so a documented memory size cannot
     quietly disagree with the machine -- but only for something that comes from
     the RMM, and only what the RMM says it holds for it (a UniFi switch has no
     serial number there). A switch typed in by hand has a model like any other
     field. The server decides the same way (schema.rmm_held). */
  function held(item, field) {
    if (!field.rmm || !item || !SYNCED[item.source] || !item.rmm_device_id) return false;
    const holds = (item.rmm || {}).holds;
    return Array.isArray(holds) ? holds.includes(field.rmm) : true;
  }

  // Where a held value comes from -- the RMM, or Microsoft 365 -- as a tag says it.
  const SYNCED = { rmm: { tag: "RMM", from: "uit de RMM" }, m365: { tag: "365", from: "uit Microsoft 365" } };

  function valueOf(item, field) {
    if (held(item, field)) return (item.rmm || {})[field.rmm] ?? "";
    return item.fields[field.key] ?? "";
  }

  function display(item, field, all) {
    const raw = valueOf(item, field);
    if (raw === "" || raw === null || raw === undefined) return "";
    if (field.type === "bool") return raw ? "Ja" : "Nee";
    if (field.type === "date") {
      const d = new Date(raw);
      return isNaN(d) ? String(raw) : d.toLocaleDateString("nl-NL");
    }
    if (field.type === "ref") {
      const other = (all || []).find((i) => i.id === raw);
      return other ? other.name : "(niet beschikbaar)";
    }
    if (field.type === "list") {
      return (Array.isArray(raw) ? raw : [])
        .map((e) => (e.label ? `${e.label}: ${e.value}` : e.value)).join(" · ");
    }
    if (field.type === "table") {
      const n = Array.isArray(raw) ? raw.length : 0;
      return n ? `${n} ${n === 1 ? "regel" : "regels"}` : "";
    }
    return String(raw);
  }

  /* A table on the page: what a firewall forwards, its rules -- under the
     field's name, a row a line, scrolling sideways on a narrow screen rather
     than squeezing the columns. */
  const LONG_TABLE = 12;

  function tableHtml(field, value, tag) {
    const rows = Array.isArray(value) ? value : [];
    const cols = field.columns || [];
    if (!rows.length || !cols.length) return "";
    const cellHtml = (c, v) => {
      if (!v) return "";
      // An address of a site opens it; a date that runs out says so; ports
      // and addresses line up in a fixed width.
      if (c.link && /^https?:\/\//i.test(v)) return `<a href="${esc(v)}" target="_blank" rel="noopener">${esc(v)}</a>`;
      const flag = c.expiry ? expiry({ expiry: true }, v) : null;
      const shown = c.expiry && /^\d{4}-\d{2}-\d{2}$/.test(v) ? new Date(v).toLocaleDateString("nl-NL") : v;
      return esc(shown) + (flag ? ` <span class="tag ${flag.kind}">${esc(flag.text)}</span>` : "");
    };
    const technical = (v) => /^[\d.:/\-, *]+$/.test(String(v || "").trim());
    return `<div class="tview${rows.length > LONG_TABLE ? " folded" : ""}" data-table="${esc(field.key)}">
        <div class="tview-head">${field.icon && ICON[field.icon] ? `<span class="dt-ic">${ICON[field.icon]}</span>` : ""}
          <span>${esc(field.label)}</span><span class="n">${rows.length}</span>${tag ? ` <span class="tag sm">${esc(tag)}</span>` : ""}</div>
        <div class="tview-scroll"><table class="tview-table">
          <thead><tr>${cols.map((c) => `<th>${esc(c.label)}</th>`).join("")}</tr></thead>
          <tbody>${rows.map((r, n) => `<tr${n >= LONG_TABLE ? ' class="tv-more"' : ""}>${cols.map((c) =>
            `<td${technical(r[c.key]) ? ' class="mono"' : ""}>${cellHtml(c, r[c.key])}</td>`).join("")}</tr>`).join("")}</tbody>
        </table></div>
        ${rows.length > LONG_TABLE ? `<button type="button" class="tv-all" data-n="${rows.length}">Alle ${rows.length} tonen</button>` : ""}
      </div>`;
  }

  // One row of a table in a form; a column with choices is a drop-down.
  function tableRow(field, row) {
    const r = row || {};
    return `<tr>${(field.columns || []).map((c) => {
      const v = r[c.key] || "";
      if (c.options) {
        const options = c.options.includes(v) || !v ? c.options : [...c.options, v];
        return `<td><select class="inp" data-tc="${esc(c.key)}"><option value=""></option>${options.map((o) =>
          `<option${o === v ? " selected" : ""}>${esc(o)}</option>`).join("")}</select></td>`;
      }
      return `<td><input class="inp" data-tc="${esc(c.key)}" value="${esc(v)}" /></td>`;
    }).join("")}<td><button type="button" class="btn ghost sm tf-drop" title="Regel weghalen">${ICON.trash}</button></td></tr>`;
  }

  /* A date that has run out, or is about to. Sixty days is roughly the notice
     you need to do something about it: order a replacement, or ring the
     provider before the contract renews itself. */
  function expiry(field, value) {
    if (!field.expiry || !value) return null;
    const parts = String(value).split("-").map(Number);
    if (parts.length !== 3 || parts.some(isNaN)) return null;
    const on = new Date(parts[0], parts[1] - 1, parts[2]);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const days = Math.round((on - today) / 86400000);
    if (days < 0) return { kind: "warn", text: "verlopen" };
    if (days <= (Number(CONFIG.EXPIRY_WARN_DAYS) || 60)) return { kind: "warn", text: days === 0 ? "vandaag" : `nog ${days} ${days === 1 ? "dag" : "dagen"}` };
    return null;
  }

  // A value as it appears in a table cell or on a page: the text, plus the
  // warning that makes a date worth having in the first place.
  function cell(item, field, all) {
    const text = display(item, field, all);
    if (!text) return "";
    const flag = expiry(field, valueOf(item, field));
    return esc(text) + (flag ? ` <span class="tag ${flag.kind}">${esc(flag.text)}</span>` : "");
  }

  function inputFor(field, value, all, orgId, from) {
    const id = `f-${field.key}`;
    // Kept up from elsewhere ("uit de RMM", "uit Microsoft 365"): shown, not typed.
    if (from) {
      const shown = Array.isArray(value)
        ? (value.length ? `${value.length} ${field.type === "table" ? (value.length === 1 ? "regel" : "regels") : "waarden"}` : "")
        : value;
      return `<div class="rmm-val">${shown === "" ? "<span class=\"muted\">niet bekend</span>" : esc(shown)}
              <span class="tag">${esc(from)}</span></div>`;
    }
    /* Several labelled values under one heading. One phone number per person
       is a fiction: there is a desk number, a mobile, and the one that is
       actually answered. */
    if (field.type === "list") {
      const rows = (Array.isArray(value) && value.length ? value : [{ label: "", value: "" }]);
      const suggestions = field.labels || [];
      const listId = `sug-${field.key}`;
      return `<div class="lfield" id="${id}" data-key="${field.key}" data-type="list">
          <datalist id="${listId}">${suggestions.map((o) => `<option value="${esc(o)}"></option>`).join("")}</datalist>
          <div class="lrows">${rows.map((r) => listRow(r, listId)).join("")}</div>
          <button type="button" class="btn ghost sm lf-add">${ICON.plus} Nog een</button>
        </div>`;
    }
    if (field.type === "table") {
      const rows = Array.isArray(value) && value.length ? value : [{}];
      return `<div class="tfield" id="${id}" data-key="${field.key}" data-type="table">
          <div class="tview-scroll"><table class="tf-table">
            <thead><tr>${(field.columns || []).map((c) => `<th>${esc(c.label)}</th>`).join("")}<th></th></tr></thead>
            <tbody>${rows.map((r) => tableRow(field, r)).join("")}</tbody>
          </table></div>
          <button type="button" class="btn ghost sm tf-add">${ICON.plus} Regel toevoegen</button>
        </div>`;
    }
    if (field.type === "secret") {
      return `<div class="rmm-val"><span class="muted">Wordt versleuteld bewaard en
        hieronder ingesteld, niet in dit formulier.</span></div>`;
    }
    if (field.type === "textarea") {
      return `<textarea class="inp${field.long ? " longtext-input" : ""}" id="${id}"
        data-key="${field.key}" rows="${field.long ? 20 : 3}">${esc(value)}</textarea>`;
    }
    if (field.type === "select") {
      // Something written before an option was retired must not disappear the
      // moment somebody opens the form for an unrelated reason.
      const options = field.options.includes(value) || !value
        ? field.options : [...field.options, value];
      return `<select class="inp" id="${id}" data-key="${field.key}">
        <option value=""></option>
        ${options.map((o) => `<option${String(o) === String(value) ? " selected" : ""}>${esc(o)}</option>`).join("")}
      </select>`;
    }
    if (field.type === "bool") {
      return `<label class="boolrow"><input type="checkbox" id="${id}" data-key="${field.key}"
        data-type="bool"${value ? " checked" : ""} /> <span>Ja</span></label>`;
    }
    if (field.type === "ref") {
      // A reference names one kind ("location"), or a family of them
      // ("configuratie": computers, network gear and printers alike).
      const family = !KINDS[field.ref];
      const options = (all || []).filter((i) => !i.archived
        && (i.kind === field.ref || (KINDS[i.kind] && KINDS[i.kind].family === field.ref)));
      const what = family ? "configuraties" : KINDS[field.ref].plural.toLowerCase();
      return `<select class="inp" id="${id}" data-key="${field.key}">
        <option value="">—</option>
        ${options.map((o) => `<option value="${esc(o.id)}"${o.id === value ? " selected" : ""}>${esc(o.name)}${
          family && KINDS[o.kind] ? ` — ${esc(KINDS[o.kind].label.toLowerCase())}` : ""}</option>`).join("")}
      </select>${options.length ? "" : `<div class="hint">Nog geen ${esc(what)} bij deze klant.</div>`}`;
    }
    const type = field.type === "number" ? "number" : field.type === "date" ? "date" : "text";
    return `<input class="inp${field.type === "ip" || field.type === "mac" ? " mono" : ""}"
      id="${id}" data-key="${field.key}" type="${type}" value="${esc(value)}" />`;
  }

  function listRow(entry, listId) {
    return `<div class="lrow">
        <input class="inp lf-label" data-lf="label" list="${listId}" placeholder="Waarvoor"
               value="${esc((entry && entry.label) || "")}" />
        <input class="inp" data-lf="value" placeholder="Waarde"
               value="${esc((entry && entry.value) || "")}" />
        <button type="button" class="btn ghost sm lf-drop" title="Weghalen">${ICON.trash}</button>
      </div>`;
  }

  // A form with list fields needs its rows wired wherever it is drawn.
  function wireListFields(root) {
    root.querySelectorAll(".lfield").forEach((field) => {
      const rows = field.querySelector(".lrows");
      const listId = field.querySelector("datalist").id;
      const wire = (row) => {
        row.querySelector(".lf-drop").onclick = () => {
          row.remove();
          if (!rows.querySelector(".lrow")) {
            rows.insertAdjacentHTML("beforeend", listRow(null, listId));
            wire(rows.lastElementChild);
          }
        };
      };
      rows.querySelectorAll(".lrow").forEach(wire);
      field.querySelector(".lf-add").onclick = () => {
        rows.insertAdjacentHTML("beforeend", listRow(null, listId));
        wire(rows.lastElementChild);
        rows.lastElementChild.querySelector(".lf-label").focus();
      };
    });

    // Tables: a new row is an empty copy of the first; the last one is
    // emptied rather than removed, so there is always a line to type on.
    root.querySelectorAll(".tfield").forEach((field) => {
      const body = field.querySelector("tbody");
      const blank = () => {
        const tr = body.rows[0].cloneNode(true);
        tr.querySelectorAll("[data-tc]").forEach((c) => { c.value = ""; });
        return tr;
      };
      const wire = (tr) => {
        tr.querySelector(".tf-drop").onclick = () => {
          if (body.rows.length === 1) body.appendChild(wire(blank()));
          tr.remove();
        };
        return tr;
      };
      [...body.rows].forEach(wire);
      field.querySelector(".tf-add").onclick = () => {
        const tr = wire(blank());
        body.appendChild(tr);
        tr.querySelector("[data-tc]").focus();
      };
    });

    /* A field about some types only -- NAT on a router or firewall -- is
       offered when the chosen type is one of them, or none is chosen yet;
       one that already holds something always stays. A block left with
       nothing to offer goes with it. */
    const role = root.querySelector('[data-key="role"]');
    const limited = [...root.querySelectorAll(".frow[data-roles]")];
    if (limited.length) {
      const apply = () => {
        const chosen = role ? role.value : "";
        limited.forEach((row) => {
          row.classList.toggle("hidden", !!chosen && !row.dataset.filled
            && !row.dataset.roles.split("|").includes(chosen));
        });
        new Set(limited.map((row) => row.closest(".form-block"))).forEach((block) => {
          if (block) block.classList.toggle("hidden", ![...block.querySelectorAll(".frow")].some((r) => !r.classList.contains("hidden")));
        });
      };
      if (role) role.addEventListener("change", apply);
      apply();
    }
  }

  function formHtml(kind, item, all, orgId, prefill) {
    const spec = KINDS[kind];
    return blocksHtml(spec.groups.map((group) => {
      const fields = group.fields.filter((f) => !f.hidden);
      return { width: group.width, html: fields.length ? `
      <div class="panel form-block">
        <div class="panel-head"><h2>${esc(group.label)}</h2></div>
        <div class="form-body">
          ${fields.map((f) => {
            const value = item ? valueOf(item, f) : ((prefill || {})[f.key] || "");
            const filled = Array.isArray(value) ? value.length : value !== "";
            return `<div class="frow${f.type === "table" ? " wide" : ""}"${f.roles
              ? ` data-roles="${esc(f.roles.join("|"))}"${filled ? ' data-filled="1"' : ""}` : ""}>
            <label for="f-${f.key}">${f.icon && ICON[f.icon]
              ? `<span class="lb-ic">${ICON[f.icon]}</span>` : ""}${esc(f.label)}</label>
            ${inputFor(f, value, all, orgId, held(item, f) ? SYNCED[item.source].from : "")}
            ${f.hint ? `<div class="hint">${esc(f.hint)}</div>` : ""}
          </div>`;
          }).join("")}
        </div>
      </div>` : "" };
    }));
  }

  function readForm(root) {
    const fields = {};
    root.querySelectorAll("[data-key]").forEach((el) => {
      if (el.dataset.type === "table") {
        fields[el.dataset.key] = [...el.querySelectorAll("tbody tr")]
          .map((tr) => Object.fromEntries([...tr.querySelectorAll("[data-tc]")].map((c) => [c.dataset.tc, c.value.trim()])))
          .filter((row) => Object.values(row).some(Boolean));
      } else if (el.dataset.type === "list") {
        fields[el.dataset.key] = [...el.querySelectorAll(".lrow")].map((row) => ({
          label: row.querySelector('[data-lf="label"]').value.trim(),
          value: row.querySelector('[data-lf="value"]').value.trim(),
        })).filter((entry) => entry.value);
      } else if (el.dataset.type === "bool") {
        fields[el.dataset.key] = el.checked;
      } else {
        fields[el.dataset.key] = el.value.trim();
      }
    });
    return fields;
  }

  // Made to the rules under Instellingen (see password.js).
  const generatedPassword = () => window.makePassword(CONFIG);

  // Long values (a document's text) are cut for the history, which is about
  // what changed and not about reading the whole thing again.
  function short(value, limit = 90) {
    const text = String(value);
    return text.length <= limit
      ? text
      : `${text.slice(0, limit).trimEnd()}… (${text.length} tekens)`;
  }

  // ---- list ----
  function columnsOf(kind) {
    const wanted = KINDS[kind].columns || [];
    const byKey = Object.fromEntries(shownFieldsOf(kind).map((f) => [f.key, f]));
    return wanted.map((k) => byKey[k]).filter(Boolean);
  }

  // The configuration types of some kinds, each knowing its kind.
  function subtypesOf(kinds) {
    return (kinds || []).flatMap((k) => ((KINDS[k] || {}).subtypes || []).map((s) => ({ ...s, kind: k })));
  }

  // What something is, as a list says it: its type where it has one.
  function typeCell(item) {
    const s = subtypesOf([item.kind]).find((t) => t.role === (item.fields || {}).role);
    return s ? `${ICON[s.icon] || ICON[KINDS[item.kind].icon]} ${esc(s.label)}`
             : `${ICON[KINDS[item.kind].icon]} ${esc(KINDS[item.kind].label)}`;
  }

  async function listView(host, org, section) {
    await kinds();
    const all = await index(org.id, true);
    const allowed = section.kinds;
    const params = new URLSearchParams(location.hash.split("?")[1] || "");
    let kind = allowed.includes(params.get("soort")) ? params.get("soort") : null;
    // The archive: what is no longer in use, in a view of its own rather than
    // mixed in with what is.
    const inArchive = params.get("archief") === "1";

    // Configuration types -- Desktops, Laptops, Routers, Wifi-punten -- where
    // the kinds in this section have them. "geen" is what has no type yet.
    const subs = subtypesOf(allowed);
    const typeId = params.get("type");
    const sub = subs.find((s) => s.id === typeId) || null;
    const roleOf = (i) => (i.fields || {}).role;
    const typed = (i) => subs.some((s) => s.kind === i.kind && s.role === roleOf(i));
    const inType = (i) => (sub ? i.kind === sub.kind && roleOf(i) === sub.role
                               : typeId === "geen" ? !typed(i) : true);

    const items = inArchive
      ? all.filter((i) => allowed.includes(i.kind) && i.archived)
      : all.filter((i) => allowed.includes(i.kind) && (!kind || i.kind === kind) && inType(i) && !i.archived);

    const live = all.filter((i) => allowed.includes(i.kind) && !i.archived);
    const untyped = live.filter((i) => !typed(i)).length;
    const chips = subs.length ? `<div class="chips">
      <button class="chip${sub || typeId === "geen" ? "" : " on"}" data-type="">Alles
        <span class="n">${live.length}</span></button>
      ${subs.map((s) => [s, live.filter((i) => i.kind === s.kind && roleOf(i) === s.role).length])
        .filter(([, n]) => n)
        .map(([s, n]) => `<button class="chip${sub && sub.id === s.id ? " on" : ""}" data-type="${s.id}">
          ${ICON[s.icon] || ""} ${esc(s.plural)} <span class="n">${n}</span></button>`).join("")}
      ${untyped ? `<button class="chip${typeId === "geen" ? " on" : ""}" data-type="geen">Zonder soort
        <span class="n">${untyped}</span></button>` : ""}
    </div>` : allowed.length > 1 ? `<div class="chips">
      <button class="chip${kind ? "" : " on"}" data-kind="">Alles
        <span class="n">${all.filter((i) => allowed.includes(i.kind) && !i.archived).length}</span></button>
      ${allowed.map((k) => `<button class="chip${kind === k ? " on" : ""}" data-kind="${k}">
        ${ICON[KINDS[k].icon]} ${esc(KINDS[k].plural)}
        <span class="n">${all.filter((i) => i.kind === k && !i.archived).length}</span></button>`).join("")}
    </div>` : "";

    /* Searching this list as you type: the name, every field as it reads (a
       reference by the name it points at), and what the RMM knows -- the
       serial number in your hand, the model, the operating system. */
    const byId = Object.fromEntries(all.map((x) => [x.id, x]));
    const hay = (i) => {
      const parts = [i.name];
      for (const f of shownFieldsOf(i.kind)) {
        const v = held(i, f) ? (i.rmm || {})[f.rmm] : (i.fields || {})[f.key];
        if (v === undefined || v === null || v === "") continue;
        if (f.type === "ref") parts.push((byId[v] || {}).name || "");
        else if (Array.isArray(v)) v.forEach((e) => parts.push(e && typeof e === "object" ? Object.values(e).join(" ") : String(e)));
        else parts.push(String(v));
      }
      return parts.join(" ").toLowerCase();
    };
    const query = params.get("zoek") || "";
    const searchBox = `<input class="inp list-search" id="list-search" type="search" value="${esc(query)}"
      placeholder="Zoek in ${esc(section.title.toLowerCase())}…" aria-label="Zoek in deze lijst" />`;

    const archivedCount = all.filter((i) => allowed.includes(i.kind) && i.archived).length;
    // Always there, so it is clear where something archived went -- greyed out
    // while there is nothing in it.
    const archiveBtn = inArchive ? "" : `<button class="btn ghost sm" id="toggle-archive"${archivedCount
        ? ` title="Wat niet meer in gebruik is"` : ` disabled title="Hier is nog niets gearchiveerd"`}>
        ${ICON.box} Archief <span class="count">${archivedCount}</span></button>`;
    const archiveHead = inArchive ? `<div class="callout info" style="margin-bottom:14px">
        <div class="ic">${ICON.box}</div><div style="flex:1">
        <div class="ct">Archief — ${esc(section.title.toLowerCase())}</div>
        <div class="cd">Wat niet meer in gebruik is. Het blijft hier bewaard met al zijn gegevens en zijn
          geschiedenis, telt nergens meer mee en waarschuwt nergens meer voor. Open een item om het
          uit het archief te halen.</div></div>
        <button class="btn ghost sm" id="archive-back" style="align-self:center">Terug naar de lijst</button></div>` : "";

    // Columns come from the kind. A mixed list can only show what every kind
    // in it has, which for equipment is the status -- better than a bare list
    // of names, and never a column that is empty for half the rows.
    const one = kind || (sub && sub.kind) || null;
    // In a type's own list its type goes without saying.
    const cols = one ? columnsOf(one).filter((c) => !(sub && c.key === "role")) : [];
    // In a mixed list the Soort column says the type, so "role" is not repeated.
    const shared = one ? [] : (KINDS[allowed[0]].columns || [])
      .filter((k) => k !== "role" && allowed.every((a) => (KINDS[a].columns || []).includes(k)));
    const sharedLabels = shared.map((k) =>
      (columnsOf(allowed[0]).find((c) => c.key === k) || {}).label || k);
    const sharedCell = (item, key) => {
      const field = fieldsOf(item.kind).find((f) => f.key === key);
      return field ? cell(item, field, all) : "";
    };
    const table = items.length ? `<div class="panel"><table class="grid"><thead><tr>
        <th>Naam</th>${one ? "" : "<th>Soort</th>"}
        ${cols.map((c) => `<th>${esc(c.label)}</th>`).join("")}
        ${sharedLabels.map((l) => `<th>${esc(l)}</th>`).join("")}
        <th></th></tr></thead><tbody>
        ${items.map((i) => `<tr data-item="${esc(i.id)}" data-hay="${esc(hay(i))}">
          <td><b>${esc(i.name)}</b>
            ${i.restricted ? ` <span class="tag warn" title="Alleen voor genoemde collega's">${ICON.lock}</span>` : ""}
            ${i.rmm_gone ? ' <span class="tag warn">niet meer in de RMM</span>' : ""}</td>
          ${one ? "" : `<td><span class="kind-cell">${typeCell(i)}</span></td>`}
          ${cols.map((c) => `<td>${cell(i, c, all) || "—"}</td>`).join("")}
          ${shared.map((k) => `<td>${sharedCell(i, k) || "—"}</td>`).join("")}
          <td class="right">${i.source === "rmm" ? '<span class="tag">RMM</span>' : ""}</td>
        </tr>`).join("")}
      </tbody></table></div>`
      : inArchive
        ? `<div class="panel"><div class="empty"><div class="big">${ICON.box}</div>
            <div>Hier is niets gearchiveerd</div></div></div>`
        : `<div class="panel"><div class="empty"><div class="big">${ICON[KINDS[allowed[0]].icon]}</div>
          <div>Nog niets vastgelegd</div>
          <div style="font-size:12.5px;margin-top:6px">${esc(section.empty)}</div></div></div>`;

    const none = `<div class="panel hidden" id="list-none"><div class="empty">
        <div>Niets gevonden voor “<b></b>” in ${esc(section.title.toLowerCase())}</div>
        <div style="font-size:12.5px;margin-top:6px"><a id="list-search-all" class="link">Zoek in alles
          van ${esc(org.name)}</a> — ook in wachtwoorden, documenten, contactpersonen en netwerkadapters.</div>
      </div></div>`;
    host.innerHTML = `<div id="new-item"></div>${archiveHead}
      <div class="list-bar">${items.length ? searchBox : ""}${inArchive ? "" : (chips || "<div></div>") + archiveBtn}</div>
      ${table}${none}`;

    host.querySelectorAll(".chip").forEach((b) => {
      b.onclick = () => {
        if (b.dataset.type !== undefined) {
          go(`#/klant/${org.id}/${section.id}${b.dataset.type ? `?type=${b.dataset.type}` : ""}`);
          return;
        }
        const next = b.dataset.kind;
        go(`#/klant/${org.id}/${section.id}${next ? `?soort=${next}` : ""}`);
      };
    });
    const search = host.querySelector("#list-search");
    const applySearch = () => {
      const typed = search.value.trim();
      const words = typed.toLowerCase().split(/\s+/).filter(Boolean);
      let shown = 0;
      host.querySelectorAll("tr[data-item]").forEach((tr) => {
        const hit = words.every((w) => tr.dataset.hay.includes(w));
        tr.style.display = hit ? "" : "none";
        if (hit) shown++;
      });
      const empty = host.querySelector("#list-none");
      empty.classList.toggle("hidden", !(words.length && !shown));
      empty.querySelector("b").textContent = typed;
      const tableBox = host.querySelector("table.grid");
      if (tableBox) tableBox.closest(".panel").classList.toggle("hidden", !!(words.length && !shown));
      // Kept in the address, so Back from an item lands on the same search.
      const p = new URLSearchParams(location.hash.split("?")[1] || "");
      if (typed) p.set("zoek", typed); else p.delete("zoek");
      history.replaceState(null, "", location.pathname + location.search
        + location.hash.split("?")[0] + (p.toString() ? `?${p}` : ""));
    };
    if (search) {
      search.addEventListener("input", applySearch);
      search.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { search.value = ""; applySearch(); }
      });
      if (query) applySearch();
    }
    const searchAll = host.querySelector("#list-search-all");
    if (searchAll) searchAll.onclick = () =>
      go(`#/klant/${org.id}/zoeken?q=${encodeURIComponent(search ? search.value.trim() : "")}`);
    const toArchive = host.querySelector("#toggle-archive");
    if (toArchive) toArchive.onclick = () => go(`#/klant/${org.id}/${section.id}?archief=1`);
    const back = host.querySelector("#archive-back");
    if (back) back.onclick = () => go(`#/klant/${org.id}/${section.id}`);
    host.querySelectorAll("tr[data-item]").forEach((tr) => {
      tr.onclick = () => go(`#/klant/${org.id}/item/${tr.dataset.item}`);
    });
    return sub;
  }

  /* Adding something is a panel on the page, not a browser dialog: those are
     refused outright in some browsers, and a button that does nothing at all is
     indistinguishable from a broken one. */
  async function openCreate(org, section, host, prefill) {
    await kinds();
    const all = await index(org.id);
    const slot = host.querySelector("#new-item");
    if (!slot) return;
    if (slot.dataset.open === "1") { slot.dataset.open = "0"; slot.innerHTML = ""; return; }
    slot.dataset.open = "1";
    // Adding from a type's list starts on that type's kind.
    let kind = prefill && section.kinds.includes(prefill.__kind) ? prefill.__kind : section.kinds[0];

    const copying = prefill && prefill.__from;
    const draw = () => {
      slot.innerHTML = `<div class="panel new-head">
          <div class="panel-head"><h2>${esc(KINDS[kind].label)} toevoegen</h2>
            ${copying ? `<span class="sub">als kopie van ${esc(prefill.__from)}</span>` : ""}</div>
          <div class="form-body">
            ${copying ? `<div class="callout info" style="margin-bottom:14px"><div class="ic">${ICON.copy}</div>
              <div class="cd">De ingevulde velden van <b>${esc(prefill.__from)}</b> staan er al in. Pas aan wat
                anders is en druk op <b>Aanmaken</b> — tot dan is er niets opgeslagen. Niet mee gaan:
                wachtwoorden, de koppeling met de RMM, netwerkadapters en switchpoorten, wat eraan
                gekoppeld is, en de geschiedenis.</div></div>` : ""}
            ${section.kinds.length > 1 ? `<div class="frow"><label>Soort</label>
              <select class="inp" id="new-kind">${section.kinds.map((k) =>
                `<option value="${k}"${k === kind ? " selected" : ""}>${esc(KINDS[k].label)}</option>`).join("")}</select></div>` : ""}
            <div class="frow"><label for="new-name">Naam</label>
              <input class="inp" id="new-name" placeholder="${esc(section.example)}"
                     value="${esc((prefill && prefill.__name) || "")}" /></div>
          </div>
        </div>
        <div id="new-fields">${formHtml(kind, null, all, org.id, prefill)}</div>
        ${kind === "password" ? `<div class="panel form-block">
            <div class="panel-head"><h2>Wachtwoord</h2></div>
            <div class="form-body"><div class="frow">
              <div style="display:flex;gap:8px">
                <input class="inp mono" id="new-secret" type="text" placeholder="Wachtwoord"
                       autocomplete="new-password" style="flex:1" />
                <button class="btn ghost" id="new-secret-gen">${ICON.refresh} Genereer</button>
              </div>
              <div class="hint">Wordt versleuteld opgeslagen en is daarna alleen met
                <b>Tonen</b> of <b>Kopiëren</b> op te vragen — beide komen in het logboek.</div>
            </div></div>
          </div>` : ""}
        <div class="form-foot">
          <button class="btn ghost" id="new-cancel">Annuleren</button>
          <button class="btn" id="new-save">${ICON.save} Aanmaken</button>
        </div>`;
      const picker = slot.querySelector("#new-kind");
      if (picker) picker.onchange = () => { kind = picker.value; const name = slot.querySelector("#new-name").value; draw(); slot.querySelector("#new-name").value = name; };
      const gen = slot.querySelector("#new-secret-gen");
      if (gen) gen.onclick = () => { slot.querySelector("#new-secret").value = generatedPassword(); };
      slot.querySelector("#new-cancel").onclick = () => { slot.dataset.open = "0"; slot.innerHTML = ""; };
      slot.querySelector("#new-save").onclick = save;
      wireListFields(slot);
      const nameInput = slot.querySelector("#new-name");
      nameInput.focus();
      if (copying) nameInput.select();          // a copy almost always gets a name of its own
      if (copying) slot.scrollIntoView({ block: "start" });
    };

    const save = async () => {
      const name = slot.querySelector("#new-name").value.trim();
      if (!name) {
        toast("Geef het eerst een naam");
        slot.querySelector("#new-name").focus();
        return;
      }
      const btn = slot.querySelector("#new-save");
      btn.disabled = true;
      try {
        const item = await api(`/api/orgs/${org.id}/items`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            kind, name, fields: readForm(slot.querySelector("#new-fields")),
            password: (slot.querySelector("#new-secret") || {}).value || undefined,
            copy_of: (prefill && prefill.__copyOf) || undefined,
          }),
        });
        forget(org.id);
        go(`#/klant/${org.id}/item/${item.id}`);
      } catch (e) { toast(e.message); btn.disabled = false; }
    };

    draw();
  }

  // ---- detail ----
  function when(seconds) {
    if (!seconds) return "—";
    return new Date(seconds * 1000).toLocaleString("nl-NL");
  }

  async function detailView(host, org, itemId) {
    await kinds();
    let item = await api(`/api/items/${itemId}`);
    let all = await index(org.id, true);  // refreshed after a change, for the ref fields
    const spec = KINDS[item.kind];
    // Decided by the server per customer (the role comes from the RMM); the
    // page only leaves out what would be refused anyway.
    const mayEdit = !org.may || org.may.edit;
    const mayReveal = !org.may || org.may.reveal;
    let editing = false;

    // Worked out each time the head is drawn: linking a tenant, or unlinking
    // it, changes where the page comes from without leaving it.
    const source = () => (item.source === "rmm"
      ? (item.rmm_gone
         ? `<span class="tag warn">niet meer in de RMM sinds ${when(item.rmm_seen_at)}</span>`
         : `<span class="tag">uit de RMM, bijgewerkt ${when(item.rmm_seen_at)}</span>`)
      : item.source === "m365" ? `<span class="tag">uit Microsoft 365, bijgewerkt ${when(item.rmm_seen_at)}</span>`
      : `<span class="tag">hier vastgelegd</span>`);

    const head = () => `<div class="panel item-head">
        <div class="ih-mark">${ICON[spec.icon]}</div>
        <div class="ih-txt">
          <h3>${esc(item.name)}${item.archived ? ' <span class="tag">gearchiveerd</span>' : ""}
            ${item.restricted ? ` <span class="tag warn">${ICON.lock} afgeschermd</span>` : ""}</h3>
          <small>${esc(spec.label)} · ${source()}<span id="in-rack"></span></small>
        </div>
        <div class="ih-act" id="item-actions"></div>
      </div>`;

    const readBlocks = () => blocksHtml(spec.groups.map((group) => ({ width: group.width, html: (() => {
      const fields = group.fields.filter((f) => !f.hidden);
      // A page of text does not belong in a label-and-value grid; it gets the
      // width of the panel and keeps the line breaks it was written with.
      const long = fields.filter((f) => f.long && display(item, f, all));
      const rows = fields.filter((f) => !f.long).map((f) => {
        const text = display(item, f, all);
        if (!text) return "";
        const raw = valueOf(item, f);
        const ref = f.type === "ref" && item.fields[f.key]
          ? `<a data-goto="${esc(item.fields[f.key])}">${esc(text)}</a>`
          : f.type === "list"
            ? (Array.isArray(raw) ? raw : []).map((e) => `<div class="lline">
                ${e.label ? `<span class="tag">${esc(e.label)}</span>` : ""}
                <span>${esc(e.value)}</span></div>`).join("")
            : cell(item, f, all);
        return `<div class="dt">${f.icon && ICON[f.icon] ? `<span class="dt-ic">${ICON[f.icon]}</span>` : ""}
                  <span>${esc(f.label)}</span>${held(item, f) ? ` <span class="tag sm">${SYNCED[item.source].tag}</span>` : ""}</div>
                <div class="dd">${ref}</div>`;
      }).join("");
      if (!rows && !long.length) return "";
      return `<div class="panel">
          <div class="panel-head"><h2>${esc(group.label)}</h2></div>
          ${rows ? `<div class="deflist">${rows}</div>` : ""}
          ${long.map((f) => (f.type === "table" ? tableHtml(f, valueOf(item, f), held(item, f) ? SYNCED[item.source].tag : "")
            : `<div class="longtext">${esc(display(item, f, all))}</div>`)).join("")}
        </div>`;
    })() }))) || `<div class="panel"><div class="empty">
        <div>Nog niets ingevuld</div>
        <div style="font-size:12.5px;margin-top:6px">Druk op <b>Bewerken</b> om de velden in te vullen.</div>
      </div></div>`;

    /* What UniFi says about a network device right now: whether it is up, how
       many are on it, which console it belongs to and what it hangs on. It
       changes all day, so it is shown rather than written into the history. */
    const unifiHtml = () => {
      const u = item.rmm || {};
      if (item.source !== "rmm" || u.source !== "unifi") return "";
      const hex = (m) => String(m || "").toLowerCase().replace(/[^0-9a-f]/g, "");
      const up = u.uplink_mac ? all.find((i) => i.rmm_device_id === `unifi:${hex(u.uplink_mac)}`) : null;
      const state = { online: ["ok", "online"], offline: ["warn", "offline"], pending: ["", "wordt bijgewerkt"] }[u.state]
        || ["", u.state || "onbekend"];
      const uptime = (s) => {
        const n = Number(s);
        if (!n) return "";
        const d = Math.floor(n / 86400), h = Math.floor((n % 86400) / 3600);
        return d ? `${d} ${d === 1 ? "dag" : "dagen"}${h ? `, ${h} uur` : ""}` : `${h || 1} uur`;
      };
      const rows = [
        ["Status", `<span class="tag ${state[0]}">${esc(state[1])}</span>`],
        u.clients !== null && u.clients !== undefined && u.clients !== "" ? ["Verbonden clients", esc(String(u.clients))] : null,
        up ? ["Hangt aan", `<a data-goto="${esc(up.id)}">${esc(up.name)}</a>`]
           : u.uplink_mac ? ["Hangt aan", `<span class="mono">${esc(u.uplink_mac)}</span>`] : null,
        u.mac ? ["MAC-adres", `<span class="mono">${esc(u.mac)}</span>`] : null,
        u.console ? ["Console", esc(u.console)] : null,
        uptime(u.uptime) ? ["Aan sinds", esc(uptime(u.uptime))] : null,
        u.last_seen ? ["Gezien door de RMM", esc(when(u.last_seen))] : null,
      ].filter(Boolean);
      return `<div class="panel" id="unifi">
          <div class="panel-head"><h2>UniFi</h2>
            <span class="sub">Zoals de RMM het ziet${u.account ? ` · ${esc(u.account)}` : ""}</span></div>
          <div class="deflist">${rows.map(([k, v]) => `<div class="dt"><span>${k}</span></div><div class="dd">${v}</div>`).join("")}</div>
        </div>`;
    };

    /* Microsoft 365: the RMM links the tenant and reads it; here is how its
       last reading went, and the way to where it is managed. */
    function drawM365() {
      const slot = host.querySelector("#m365");
      if (!slot) return;
      const rmmUrl = ctx.rmmUrl ? ctx.rmmUrl() : null;
      const manage = rmmUrl && org.rmm_org_id
        ? `<a class="btn ghost sm" href="${esc(rmmUrl)}/#/o/${encodeURIComponent(org.rmm_org_id)}/m365" target="_blank" rel="noopener">${ICON.external} Beheren in de RMM</a>` : "";
      const r = item.rmm || {};
      if (item.source !== "m365") {
        slot.innerHTML = `<div class="panel m365-panel">
            <div class="panel-head"><h2>Koppeling met Microsoft 365</h2><span class="spacer"></span>${manage}</div>
            <div class="m365-intro">${rmmUrl
              ? `Koppel deze tenant in de RMM, bij de klant onder <b>Microsoft 365</b>. Dan komen de domeinen, abonnementen,
                 gebruikers met hun licenties, gedeelde mailboxen, groepen en app-registraties hier vanzelf in — en waarschuwt
                 de RMM voor een app-secret dat verloopt. Een tenant-ID die hier staat, laat de RMM deze pagina overnemen.`
              : `Zonder koppeling met de RMM vul je alles hier zelf in.`}</div>
          </div>`;
        return;
      }
      const problems = r.problems || [];
      slot.innerHTML = `<div class="panel m365-panel">
          <div class="panel-head"><h2>Microsoft 365</h2>
            <span class="sub">${r.ok ? `gelezen door de RMM ${when(r.read_at)}` : `<span class="tag warn">lezen mislukt</span>`}
              · tenant <span class="mono">${esc(item.rmm.tenant_id || "")}</span></span>
            <span class="spacer"></span>${manage}</div>
          ${!r.ok && r.error ? `<div class="callout warn m365-note"><div class="ic">${ICON.alert}</div>
              <div class="cd">${esc(r.error)}. Hieronder staat de laatste lezing die wel lukte.</div></div>` : ""}
          ${problems.length ? `<div class="callout info m365-note"><div class="ic">${ICON.info}</div><div class="cd">
              <b>Niet alles kon gelezen worden.</b><ul>${problems.map((p) => `<li>${esc(p.part)}: ${p.error === "forbidden"
                ? `geen toestemming — geef de app-registratie <code>${esc(p.permission)}</code>` : esc(p.error)}</li>`).join("")}</ul>
              Dat regel je in de app-registratie van de klant; de RMM leest daarna weer.</div></div>` : ""}
        </div>`;
    }

    const draw = async () => {
      const goneNote = item.rmm_gone ? `<div class="callout warn" style="margin-bottom:14px">
          <div class="ic">${ICON.alert}</div><div style="flex:1">
          <div class="ct">${item.kind === "m365" ? "De RMM leest deze tenant niet meer" : "Dit apparaat staat niet meer in de RMM"}</div>
          <div class="cd">Sinds ${when(item.rmm_seen_at)}. De pagina blijft staan — wat je erover
            hebt vastgelegd is meestal juist dan nog nodig. ${item.kind === "m365"
              ? "Koppel hem opnieuw in de RMM, of archiveer hem als de klant ermee gestopt is."
              : "Is de machine weg, archiveer hem dan."}
            ${item.archived ? "" : `<button class="btn ghost sm" id="gone-archive" style="margin-left:10px">${ICON.box} Archiveren</button>`}</div>
          </div></div>` : "";
      // Said where you arrive, so an archived page is not mistaken for one in use.
      const archivedNote = item.archived ? `<div class="callout info" style="margin-bottom:14px">
          <div class="ic">${ICON.box}</div><div style="flex:1">
          <div class="ct">Gearchiveerd</div>
          <div class="cd">Niet meer in gebruik. Alles blijft bewaard, maar het staat niet meer in de lijsten
            en waarschuwt nergens meer voor.
            ${mayEdit ? `<button class="btn ghost sm" id="archived-restore" style="margin-left:10px">${ICON.refresh} Uit archief halen</button>` : ""}</div>
          </div></div>` : "";
      host.innerHTML = head() + (editing ? "" : archivedNote + goneNote)
        + (editing ? `<div id="edit-fields">${formHtml(item.kind, item, all, org.id)}</div>
             ${adaptersFormHtml()}${portsFormHtml()}
             <div class="form-foot"><button class="btn ghost" id="edit-cancel">Annuleren</button>
               <button class="btn" id="edit-save">${ICON.save} Opslaan</button></div>`
                   // What the thing is on the left; on the right, what hangs
                   // off it -- its files, its passwords, what it is linked to
                   // and what changed -- the way IT Glue lays out a page. A
                   // cabinet needs the width for its front and the parts
                   // beside it, so there the rest comes underneath.
                   : (item.kind === "rack" ? readBlocks() + `<div id="rack-view"></div>` : "")
                     + `<div class="item-cols${item.kind === "rack" ? " solo" : ""}"><div class="item-main">`
                     + (item.kind === "m365" ? `<div id="m365"></div>` : "")
                     + (item.kind === "rack" ? "" : readBlocks())
                     + unifiHtml()
                     + `<div id="secret"></div><div id="access"></div>`
                     + `<div id="adapters"></div><div id="ports"></div>`
                     + `</div><aside class="item-side">`
                     + `<div id="files"></div><div id="passwords"></div>`
                     + `<div id="related"></div><div id="referred"></div><div id="history"></div>`
                     + `</aside></div>`);
      wireHead();
      const goneBtn = host.querySelector("#gone-archive");
      if (goneBtn) goneBtn.onclick = () => host.querySelector("#btn-archive").click();
      const restoreBtn = host.querySelector("#archived-restore");
      if (restoreBtn) restoreBtn.onclick = () => host.querySelector("#btn-archive").click();
      if (editing) {
        host.querySelector("#edit-cancel").onclick = () => { editing = false; draw(); };
        host.querySelector("#edit-save").onclick = saveEdit;
        wireAdapterForm();
        wireListFields(host);
        const first = host.querySelector("#edit-fields .inp");
        if (first) first.focus();
      } else {
        host.querySelectorAll("[data-goto]").forEach((a) => {
          a.onclick = () => go(`#/klant/${org.id}/item/${a.dataset.goto}`);
        });
        // A long table shows its first rows; the rest on request.
        host.querySelectorAll(".tv-all").forEach((b) => {
          b.onclick = () => {
            const box = b.closest(".tview");
            box.classList.toggle("folded");
            b.textContent = box.classList.contains("folded") ? `Alle ${b.dataset.n} tonen` : "Minder tonen";
          };
        });
        if (item.kind === "m365") drawM365();
        if (Rack && item.kind === "rack") {
          Rack.view(host.querySelector("#rack-view"), { org, item, mayEdit, all, kinds: KINDS });
        }
        if (Rack && item.kind !== "rack") Rack.whereHangs(host.querySelector("#in-rack"), org, item.id);
        drawFiles();
        drawSecret();
        drawAccess();
        drawAdapters();
        drawPorts();
        drawPasswords();
        drawReferredBy();
        await drawRelated();
        await drawHistory();
      }
    };

    function wireHead() {
      const act = host.querySelector("#item-actions");
      if (!mayEdit) {
        act.innerHTML = `<span class="tag" title="Je rol bij deze klant in de RMM geeft alleen leesrechten">alleen lezen</span>`;
        return;
      }
      act.innerHTML = editing ? "" : `
        <button class="btn ghost sm" id="btn-edit">${ICON.pencil} Bewerken</button>
        <button class="btn ghost sm" id="btn-copy" title="Een nieuw ${esc(spec.label.toLowerCase())} met deze gegevens">${ICON.copy} Kopie maken</button>
        <button class="btn ghost sm" id="btn-archive">${item.archived ? ICON.refresh + " Uit archief halen" : ICON.box + " Archiveren"}</button>`;
      if (editing) return;
      act.querySelector("#btn-edit").onclick = () => { editing = true; draw(); };
      act.querySelector("#btn-copy").onclick = () => {
        const section = ctx.sectionOf && ctx.sectionOf(item.kind);
        if (section) go(`#/klant/${org.id}/${section.id}?kopie=${item.id}`);
      };
      act.querySelector("#btn-archive").onclick = async () => {
        try {
          item = await api(`/api/items/${item.id}/archive`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ archived: !item.archived }),
          });
          forget(org.id);
          toast(item.archived ? "Gearchiveerd" : "Uit het archief gehaald");
          draw();
        } catch (e) { toast(e.message); }
      };
    }

    async function saveEdit() {
      const btn = host.querySelector("#edit-save");
      btn.disabled = true;
      try {
        // The adapters and the ports go with it: one press of Opslaan, one
        // machine saved, rather than a page that commits in pieces.
        await applyAdapters();
        await applyPorts();
        item = await api(`/api/items/${item.id}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ fields: readForm(host.querySelector("#edit-fields")) }),
        });
        forget(org.id);
        all = await index(org.id);
        editing = false;
        toast("Opgeslagen");
        draw();
      } catch (e) { toast(e.message); btn.disabled = false; }
    }

    /* Photos and files: the rack, the label with the serial number, the manual,
       an exported configuration. Added from here without editing the item --
       chosen, dragged onto the panel, or pasted (a screenshot) -- and photos
       shown straight away, as a gallery. */
    const kb = (n) => n >= 1048576 ? `${(n / 1048576).toFixed(1).replace(".", ",")} MB`
      : `${Math.max(1, Math.round(n / 1024))} kB`;
    let files = [];

    async function drawFiles() {
      const slot = host.querySelector("#files");
      if (!slot) return;
      try { files = await api(`/api/items/${item.id}/attachments`); } catch (e) { return; }
      if (!files.length && !mayEdit) { slot.innerHTML = ""; return; }
      const pictures = files.filter((f) => f.is_image);
      const others = files.filter((f) => !f.is_image);
      const counted = [pictures.length ? `${pictures.length} ${pictures.length === 1 ? "foto" : "foto's"}` : "",
                       others.length ? `${others.length} ${others.length === 1 ? "bestand" : "bestanden"}` : ""]
        .filter(Boolean).join(", ");
      slot.innerHTML = `<div class="panel files-panel" id="files-drop">
          <div class="panel-head"><h2>Foto's en bestanden</h2>
            <span class="sub">${counted || "Nog niets"}</span>
            <span class="spacer"></span>
            ${mayEdit ? `<button class="btn ghost sm" id="files-add">${ICON.upload} Toevoegen</button>
              <input type="file" id="files-input" multiple hidden />` : ""}</div>
          ${pictures.length ? `<div class="gallery">${pictures.map((f) => `
            <button type="button" class="thumb" data-view="${esc(f.id)}" title="${esc(f.name)}">
              <img src="/api/attachments/${esc(f.id)}/thumb" alt="${esc(f.name)}" loading="lazy" /></button>`).join("")}</div>` : ""}
          ${others.length ? `<div class="file-list">${others.map((f) => `<div class="file-row">
              <span class="fr-ic">${ICON.file}</span>
              <a class="fr-name" href="/api/attachments/${esc(f.id)}/file${f.mime === "application/pdf" ? "" : "?download=1"}"
                 target="_blank" rel="noopener">${esc(f.name)}</a>
              <span class="fr-meta">${kb(f.size)} · ${esc(f.created_by || "")} · ${new Date(f.created_at * 1000).toLocaleDateString("nl-NL")}</span>
              <a class="lay-ib" href="/api/attachments/${esc(f.id)}/file?download=1" title="Downloaden">${ICON.download}</a>
              ${mayEdit ? `<button type="button" class="lay-ib" data-del="${esc(f.id)}" title="Verwijderen">${ICON.trash}</button>` : ""}
            </div>`).join("")}</div>` : ""}
          ${mayEdit ? `<button type="button" class="files-hint" id="files-pick">${ICON.upload}
              <span>${files.length ? "Sleep er meer hierheen" : "<b>Sleep foto's of bestanden hierheen</b>"},
              plak een schermafbeelding met Ctrl+V, of klik om ze te kiezen.</span></button>` : ""}
          <div class="files-busy hidden" id="files-busy"></div>
        </div>`;
      slot.querySelectorAll("[data-view]").forEach((b) => { b.onclick = () => openViewer(b.dataset.view); });
      slot.querySelectorAll("[data-del]").forEach((b) => { b.onclick = () => removeFile(b.dataset.del); });
      if (!mayEdit) return;
      const input = slot.querySelector("#files-input");
      slot.querySelector("#files-add").onclick = () => input.click();
      slot.querySelector("#files-pick").onclick = () => input.click();
      input.onchange = () => { upload([...input.files]); input.value = ""; };
      const zone = slot.querySelector("#files-drop");
      zone.addEventListener("dragover", (ev) => {
        if (![...(ev.dataTransfer.types || [])].includes("Files")) return;
        ev.preventDefault();
        zone.classList.add("dragover");
      });
      zone.addEventListener("dragleave", (ev) => {
        if (!zone.contains(ev.relatedTarget)) zone.classList.remove("dragover");
      });
      zone.addEventListener("drop", (ev) => {
        ev.preventDefault();
        zone.classList.remove("dragover");
        upload([...(ev.dataTransfer.files || [])]);
      });
      // A screenshot pasted anywhere on the page lands here.
      pasteInto = (list) => upload(list);
    }

    async function upload(list) {
      if (!list.length) return;
      const busy = host.querySelector("#files-busy");
      let done = 0;
      for (const [n, file] of list.entries()) {
        if (busy) {
          busy.classList.remove("hidden");
          busy.textContent = `Uploaden: ${file.name} (${n + 1} van ${list.length})…`;
        }
        try {
          const res = await fetch(`/api/items/${item.id}/attachments?name=${encodeURIComponent(file.name)}`, {
            method: "POST", headers: { "Content-Type": file.type || "application/octet-stream" }, body: file,
          });
          if (res.status === 413) {
            const body = await res.json().catch(() => null);
            // Refused by this server, it says how big a file may be; refused
            // before it got here, it is the reverse proxy, with its own limit.
            throw new Error(body && body.detail ? `${file.name}: ${body.detail}`
              : `${file.name} is te groot voor de reverse proxy (bij nginx: client_max_body_size)`);
          }
          if (!res.ok) throw new Error(`${file.name}: ${((await res.json().catch(() => ({}))).detail) || res.status}`);
          done++;
        } catch (e) { toast(e.message); }
      }
      if (done) toast(done === 1 ? "Toegevoegd" : `${done} bestanden toegevoegd`);
      await drawFiles();
      await drawHistory();
    }

    async function removeFile(id) {
      const f = files.find((x) => x.id === id);
      if (!f || !window.confirm(`“${f.name}” verwijderen?`)) return;
      try {
        await api(`/api/attachments/${id}`, { method: "DELETE" });
        toast("Verwijderd");
        closeViewer();
        await drawFiles();
        await drawHistory();
      } catch (e) { toast(e.message); }
    }

    // A photo, large, with the others an arrow key away.
    function openViewer(id) {
      const pictures = files.filter((f) => f.is_image);
      let at = Math.max(0, pictures.findIndex((f) => f.id === id));
      closeViewer();
      const box = document.createElement("div");
      box.id = "viewer";
      box.className = "viewer";
      const show = () => {
        const f = pictures[at];
        box.innerHTML = `<div class="vw-bar"><span class="vw-name">${esc(f.name)}</span>
            <span class="vw-meta">${at + 1} van ${pictures.length}${f.width ? ` · ${f.width}×${f.height}` : ""}</span>
            <span class="spacer"></span>
            <a class="btn ghost sm" href="/api/attachments/${esc(f.id)}/file?download=1">${ICON.download} Downloaden</a>
            ${mayEdit ? `<button class="btn ghost sm" id="vw-del">${ICON.trash} Verwijderen</button>` : ""}
            <button class="btn ghost sm" id="vw-close" title="Sluiten (Esc)">Sluiten</button></div>
          <div class="vw-stage">
            ${pictures.length > 1 ? `<button class="vw-nav prev" id="vw-prev" title="Vorige (←)">${ICON.chevR}</button>` : ""}
            <img src="/api/attachments/${esc(f.id)}/file" alt="${esc(f.name)}" />
            ${pictures.length > 1 ? `<button class="vw-nav next" id="vw-next" title="Volgende (→)">${ICON.chevR}</button>` : ""}
          </div>`;
        box.querySelector("#vw-close").onclick = closeViewer;
        const del = box.querySelector("#vw-del");
        if (del) del.onclick = () => removeFile(f.id);
        const step = (n) => { at = (at + n + pictures.length) % pictures.length; show(); };
        const prev = box.querySelector("#vw-prev");
        if (prev) prev.onclick = () => step(-1);
        const next = box.querySelector("#vw-next");
        if (next) next.onclick = () => step(1);
        viewerKeys = (ev) => {
          if (ev.key === "Escape") closeViewer();
          if (ev.key === "ArrowLeft" && pictures.length > 1) step(-1);
          if (ev.key === "ArrowRight" && pictures.length > 1) step(1);
        };
      };
      box.addEventListener("click", (ev) => {
        if (ev.target === box || ev.target.classList.contains("vw-stage")) closeViewer();
      });
      document.body.appendChild(box);
      show();
    }

    /* The password itself. It is not a field: it never travels with the rest
       of the page, it is asked for one at a time, and every reading is a line
       in the log — which is the whole reason the log is worth reading. */
    /* Which secrets this item has. A vault entry keeps one under "main"; a
       type defined here can have several, each on its own field -- a tenant
       with an administrator password and a break-glass account, say. */
    function secretSlots() {
      const out = item.kind === "password" ? [{ field: "main", label: "Wachtwoord" }] : [];
      for (const f of shownFieldsOf(item.kind)) {
        if (f.type === "secret") out.push({ field: f.key, label: f.label, hint: f.hint });
      }
      return out;
    }

    function secretState(field) {
      if (field === "main") {
        return { has_secret: item.has_secret, secret_updated_at: item.secret_updated_at,
                 secret_updated_by: item.secret_updated_by, secret_strength: item.secret_strength };
      }
      return (item.secrets || {})[field] || { has_secret: false };
    }

    // How strong it was judged when stored. Absent for a password stored before
    // that was done, and for someone who may not read it.
    function gradeTag(grade) {
      const grades = [
        ["bad", "zwak", "Makkelijk te raden: te kort, te weinig variatie, of een bekend woord met cijfers erachter."],
        ["", "matig", "Redelijk. Langer of gevarieerder maakt het sterk."],
        ["ok", "sterk", "Lang en gevarieerd genoeg."],
      ];
      const g = grades[grade];
      return g ? `<span class="tag ${g[0]} sx-grade" title="${esc(g[2])}">${g[1]}</span>` : "";
    }

    function drawSecret() {
      const slot = host.querySelector("#secret");
      if (!slot) return;
      const slots = secretSlots();
      if (!slots.length) { slot.innerHTML = ""; return; }
      slot.innerHTML = slots.map((s) => `<div data-secret="${esc(s.field)}"></div>`).join("");
      slots.forEach((s) =>
        drawOneSecret(slot.querySelector(`[data-secret="${CSS.escape(s.field)}"]`), s));
    }

    /* Who may see this. Everyone with access to the customer, unless it is
       shut off to named colleagues -- for anyone else it then does not exist,
       anywhere. Offered where a password lives, which is what needs it. */
    function drawAccess() {
      const slot = host.querySelector("#access");
      if (!slot) return;
      if (!secretSlots().length) { slot.innerHTML = ""; return; }
      const people = item.people || [];
      slot.innerHTML = `<div class="panel">
          <div class="panel-head"><h2>Wie mag dit zien</h2>
            ${people.length ? `<span class="tag warn">${ICON.lock} afgeschermd</span>` : ""}
            <div class="spacer"></div>
            ${mayEdit ? `<button class="btn ghost sm" id="acc-edit">${people.length
              ? `${ICON.pencil} Wijzigen` : `${ICON.lock} Afschermen`}</button>` : ""}</div>
          <div class="acc-summary">${people.length
            ? `Alleen <b>${people.map(esc).join("</b>, <b>")}</b> — en beheerders, die alles zien.
               Voor ieder ander bestaat dit niet: niet in de lijst, niet in zoeken, niet bij een koppeling.`
            : "Iedereen met toegang tot deze klant."}</div>
          <div id="acc-form"></div>
        </div>`;
      const edit = slot.querySelector("#acc-edit");
      if (!edit) return;
      edit.onclick = async () => {
        const box = slot.querySelector("#acc-form");
        if (box.dataset.open === "1") { box.dataset.open = "0"; box.innerHTML = ""; return; }
        box.dataset.open = "1";
        let access;
        try { access = await api(`/api/items/${item.id}/access`); }
        catch (e) { toast(e.message); return; }
        const chosen = new Set(access.people);
        box.innerHTML = `<div class="acc-list">${access.candidates.map((c) => `
            <label class="acc-row${c.is_admin ? " fixed" : ""}">
              <input type="checkbox" value="${esc(c.email)}"${c.is_admin ? " checked disabled"
                : chosen.has(c.email) ? " checked" : ""} />
              <span class="acc-name">${esc(c.name)}</span>
              <span class="muted">${esc(c.email)}</span>
              ${c.is_admin ? '<span class="tag">beheerder — ziet het altijd</span>'
                : c.role === "viewer" ? '<span class="tag">alleen lezen</span>' : ""}
            </label>`).join("")}</div>
          <div class="acc-foot">
            ${access.restricted ? `<button class="btn ghost sm" id="acc-open">Iedereen weer toegang geven</button>` : ""}
            <div style="flex:1"></div>
            <button class="btn sm" id="acc-save">${ICON.lock} Alleen voor wie aangevinkt is</button>
          </div>
          <div class="hint" style="padding:0 18px 14px">Jij blijft er altijd bij: afschermen voor jezelf
            kan niet.</div>`;
        const save = async (people) => {
          try {
            await api(`/api/items/${item.id}/access`, {
              method: "PUT", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ people }),
            });
            item = await api(`/api/items/${item.id}`);
            forget(org.id);
            toast(people.length ? "Afgeschermd" : "Weer zichtbaar voor iedereen bij deze klant");
            draw();
          } catch (e) { toast(e.message); }
        };
        box.querySelector("#acc-save").onclick = () => {
          const people = [...box.querySelectorAll("input:checked:not(:disabled)")].map((i) => i.value);
          if (!people.length) { toast("Vink minstens één collega aan, of kies Iedereen"); return; }
          save(people);
        };
        const open = box.querySelector("#acc-open");
        if (open) open.onclick = () => save([]);
      };
    }

    /* One panel per secret. A page can carry several -- a tenant with an
       administrator password and a break-glass account -- so everything in
       here is found by class within its own panel rather than by id, which
       two panels would share. */
    function setForm(buttonText) {
      return `<div class="plug-row">
          <input class="inp mono sx-input" type="text" autocomplete="new-password"
                 placeholder="Wachtwoord" style="flex:1;min-width:220px" />
          <button type="button" class="btn ghost sm sx-gen">${ICON.refresh} Genereer</button>
          <button type="button" class="btn sm sx-save">${ICON.save} ${buttonText}</button>
        </div>`;
    }

    function wireSetForm(root, save) {
      root.querySelector(".sx-gen").onclick = () => {
        root.querySelector(".sx-input").value = generatedPassword();
      };
      root.querySelector(".sx-save").onclick = () => save(root.querySelector(".sx-input"));
    }

    function drawOneSecret(slot, spec) {
      if (!slot) return;
      const field = spec.field;
      const query = field === "main" ? "" : `?field=${encodeURIComponent(field)}`;
      let shown = null;
      let hideTimer = null;

      /* The links made for this password: who they were for, how many looks
         are left, and a way to close one that is still open. */
      async function drawShares(everything) {
        const box = slot.querySelector(".sx-shares");
        if (!box) return;
        let shares = [];
        try { shares = await api(`/api/items/${item.id}/shares`); } catch (e) { return; }
        shares = shares.filter((sh) => sh.field_key === field);
        if (!shares.length) { box.innerHTML = ""; return; }
        // Open links always; of the closed ones only the latest few, since a
        // password shared every month would otherwise push the page down.
        const closed = shares.filter((sh) => sh.state !== "open");
        const hidden = everything ? 0 : Math.max(0, closed.length - 3);
        if (hidden) {
          const keep = new Set(closed.slice(0, 3).map((sh) => sh.id));
          shares = shares.filter((sh) => sh.state === "open" || keep.has(sh.id));
        }
        const word = { open: "open", opgebruikt: "opgebruikt", verlopen: "verlopen", ingetrokken: "ingetrokken" };
        box.innerHTML = `<div class="share-list">${shares.map((sh) => `
            <div class="share-row ${sh.state}">
              ${ICON.link}
              <span>${sh.note ? esc(sh.note) : "Deellink"}</span>
              <span class="muted">${sh.views}/${sh.max_views} keer geopend</span>
              <span class="muted">${sh.state === "open"
                ? `tot ${new Date(sh.expires_at * 1000).toLocaleString("nl-NL")}`
                : esc(sh.revoked_why || word[sh.state])}</span>
              <span class="tag${sh.state === "open" ? " ok" : ""}">${word[sh.state]}</span>
              ${sh.state === "open"
                ? `<button type="button" class="btn ghost sm" data-revoke="${esc(sh.id)}">Intrekken</button>` : ""}
            </div>`).join("")}
            ${hidden ? `<div class="share-row more"><button type="button" class="btn ghost sm sh-older">
                ${hidden} oudere ${hidden === 1 ? "link" : "links"} tonen</button></div>` : ""}</div>`;
        const older = box.querySelector(".sh-older");
        if (older) older.onclick = () => drawShares(true);
        box.querySelectorAll("[data-revoke]").forEach((b) => {
          b.onclick = async () => {
            try {
              await api(`/api/shares/${b.dataset.revoke}`, { method: "DELETE" });
              toast("Deellink ingetrokken");
              drawShares();
            } catch (e) { toast(e.message); }
          };
        });
      }

      const save = async (input) => {
        const value = input.value;
        if (!value) { toast("Vul eerst een wachtwoord in"); input.focus(); return; }
        try {
          await api(`/api/items/${item.id}/secret${query}`, {
            method: "PUT", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password: value }),
          });
          item = await api(`/api/items/${item.id}`);
          shown = null;
          toast(`${spec.label} opgeslagen`);
          draw();
        } catch (e) { toast(e.message); }
      };

      const paint = () => {
        const state = secretState(field);
        if (!mayReveal) {
          slot.innerHTML = `<div class="panel secret-panel">
              <div class="panel-head"><h2>${esc(spec.label)}</h2></div>
              <div class="secret-row"><span class="secret-val mono">${state.has_secret ? "••••••••••••" : "—"}</span>
                <span class="tag">${ICON.lock} geen toegang</span></div>
              <div class="secret-note">${state.has_secret ? "Er staat een wachtwoord in, maar" : "Hier kan een wachtwoord in, maar"}
                je rol bij deze klant geeft geen toegang tot wachtwoorden. Dat wordt in de RMM geregeld.</div>
            </div>`;
          return;
        }
        const changed = state.secret_updated_at
          ? `Laatst gewijzigd ${when(state.secret_updated_at)}${
              state.secret_updated_by ? ` door ${esc(state.secret_updated_by)}` : ""}`
          : (spec.hint || "");
        slot.innerHTML = `<div class="panel secret-panel">
            <div class="panel-head"><h2>${esc(spec.label)}</h2>
              ${state.has_secret ? gradeTag(state.secret_strength) : ""}
              <span class="sub">${esc(changed)}</span></div>
            ${state.has_secret ? `
              <div class="secret-row">
                <span class="secret-val mono sx-val">${shown ? esc(shown) : "••••••••••••"}</span>
                <button type="button" class="btn ghost sm sx-show">${shown ? ICON.eyeOff : ICON.eye} ${shown ? "Verberg" : "Tonen"}</button>
                <button type="button" class="btn ghost sm sx-copy">${ICON.copy} Kopiëren</button>
                <button type="button" class="btn ghost sm sx-edit">${ICON.pencil} Wijzigen</button>
                <button type="button" class="btn ghost sm sx-share">${ICON.link} Delen</button>
              </div>
              <div class="secret-note">Elke keer dat dit getoond of gekopieerd wordt,
                komt dat in het logboek te staan.</div>
              <div class="sx-form"></div>
              <div class="sx-shares"></div>`
            : `<div class="secret-row"><span class="muted">Er staat nog niets in.</span></div>
               <div class="cb-pad">${setForm("Opslaan")}</div>`}
          </div>`;

        if (!state.has_secret) { wireSetForm(slot, save); return; }

        slot.querySelector(".sx-show").onclick = async () => {
          if (shown) { shown = null; clearTimeout(hideTimer); paint(); return; }
          try {
            shown = (await api(`/api/items/${item.id}/secret${query}`)).password;
            // Back to dots by itself: a password left on a screen in an office
            // is the most ordinary way one gets out.
            hideTimer = setTimeout(() => { shown = null; paint(); },
                                   (Number(CONFIG.PW_REVEAL_SECONDS) || 30) * 1000);
            paint();
          } catch (e) { toast(e.message); }
        };

        slot.querySelector(".sx-copy").onclick = async () => {
          try {
            const value = shown || (await api(`/api/items/${item.id}/secret${query}`)).password;
            await navigator.clipboard.writeText(value);
            toast("Gekopieerd");
          } catch (e) {
            // Without https the browser refuses the clipboard. Show it instead
            // of failing silently, and say why.
            try {
              shown = (await api(`/api/items/${item.id}/secret${query}`)).password;
              paint();
              toast("Kopiëren mag niet in deze browser — hier is hij");
            } catch (inner) { toast(inner.message); }
          }
        };

        drawShares();
        slot.querySelector(".sx-share").onclick = () => {
          const box = slot.querySelector(".sx-form");
          if (box.dataset.open === "share") { box.dataset.open = ""; box.innerHTML = ""; return; }
          box.dataset.open = "share";
          box.innerHTML = `<div class="cb-pad share-form">
              <div class="plug-row">
                <label class="muted">Geldig</label>
                <select class="inp sh-hours" style="max-width:130px">
                  <option value="1">1 uur</option><option value="24" selected>24 uur</option>
                  <option value="72">3 dagen</option><option value="168">7 dagen</option></select>
                <label class="muted">te openen</label>
                <select class="inp sh-views" style="max-width:110px">
                  <option value="1" selected>1 keer</option><option value="2">2 keer</option>
                  <option value="3">3 keer</option><option value="5">5 keer</option>
                  <option value="10">10 keer</option></select>
                <input class="inp sh-note" placeholder="Voor wie (optioneel)" style="flex:1;min-width:160px" />
                <button type="button" class="btn sm sh-make">${ICON.link} Link maken</button>
              </div>
              <div class="hint">Voor iemand zonder account. De link geeft het wachtwoord zoals het nú is;
                wijzig je het later, dan houdt de link op met werken.</div>
            </div>`;
          box.querySelector(".sh-make").onclick = async (ev) => {
            const button = ev.currentTarget;
            button.disabled = true;
            try {
              const made = await api(`/api/items/${item.id}/shares${query}`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ hours: Number(box.querySelector(".sh-hours").value),
                                       views: Number(box.querySelector(".sh-views").value),
                                       note: box.querySelector(".sh-note").value }),
              });
              // Shown once. Only a fingerprint of it is kept, so it cannot be
              // looked up again later -- by us or by anyone with the database.
              box.innerHTML = `<div class="cb-pad"><div class="share-made">
                  <div class="ct">${ICON.check} Link gemaakt — kopieer hem nu, hij wordt niet meer getoond</div>
                  <div class="plug-row"><span class="secret-val mono sh-url">${esc(made.url)}</span>
                    <button type="button" class="btn sm sh-copy">${ICON.copy} Kopiëren</button></div>
                  ${made.guessed_address ? `<div class="hint">Het openbare adres is niet ingesteld, dus dit adres is
                    geraden uit je eigen verbinding. Controleer het, of stel het in onder Instellingen.</div>` : ""}
                </div></div>`;
              box.querySelector(".sh-copy").onclick = async () => {
                try { await navigator.clipboard.writeText(made.url); toast("Link gekopieerd"); }
                catch (e) { toast("Kopiëren mag niet in deze browser — selecteer de link"); }
              };
              drawShares();
            } catch (e) { toast(e.message); button.disabled = false; }
          };
        };

        slot.querySelector(".sx-edit").onclick = () => {
          const box = slot.querySelector(".sx-form");
          if (box.dataset.open === "1") { box.dataset.open = "0"; box.innerHTML = ""; return; }
          box.dataset.open = "1";
          box.innerHTML = `<div class="cb-pad">${setForm("Vervangen")}</div>`;
          wireSetForm(box, save);
          box.querySelector(".sx-input").focus();
        };
      };

      paint();
    }

    /* Network adapters, and the port each one is patched into.

       Reading and changing are separate: the page shows what is there, and
       everything that changes it lives in the one edit form, so a machine is
       saved in one go instead of by a scattering of little buttons that each
       commit on their own. */
    function switchesHere() {
      return all.filter((i) => i.kind === "network" && !i.archived
        && (i.fields.role === "Switch" || Number(i.fields.ports || 0) > 0));
    }

    function drawAdapters() {
      const slot = host.querySelector("#adapters");
      if (!slot) return;
      // Only equipment has network adapters. The server sends the field for
      // those alone, so a password or a contact leaves the panel out instead
      // of offering to give a contact person a MAC address.
      if (!Array.isArray(item.adapters)) { slot.innerHTML = ""; return; }
      const adapters = item.adapters;

      const rows = adapters.length ? adapters.map((a) => {
        const where = a.port
          ? `<a data-goto="${esc(a.port.switch_id)}">${esc(a.port.switch_name)}</a>
             <span class="port-no">poort ${a.port.number}</span>`
          : `<span class="muted">niet aangesloten</span>`;
        return `<div class="ad-row">
          <div class="ad-main">
            <span class="ad-name">${esc(a.name || "Adapter")}</span>
            ${a.source === "rmm" ? '<span class="tag">RMM</span>' : ""}
            <span class="mono ad-mac">${esc(a.mac || "—")}</span>
            <span class="muted">${esc(a.ipv4 || "")}</span>
            ${a.vlan ? `<span class="tag">VLAN ${esc(a.vlan)}</span>` : ""}
            ${a.speed ? `<span class="muted">${esc(a.speed)}</span>` : ""}
          </div>
          <div class="ad-port">${where}</div>
        </div>`;
      }).join("") : `<div class="muted" style="padding:14px 16px">
          Nog geen netwerkadapters.${item.source === "rmm"
            ? " Van een machine met een agent komen ze uit de RMM."
            : ""} Voeg ze toe met <b>Bewerken</b>.</div>`;

      slot.innerHTML = `<div class="panel">
          <div class="panel-head"><h2>Netwerkadapters</h2>
            <span class="sub">Met het MAC-adres en de switchpoort waar ze aan hangen</span></div>
          ${rows}
        </div>`;
      slot.querySelectorAll("[data-goto]").forEach((a) => {
        a.onclick = () => go(`#/klant/${org.id}/item/${a.dataset.goto}`);
      });
    }

    /* A switch's patch list. The whole point is the empty rows: you come here
       to find a free port as often as to look one up. */
    function drawPorts() {
      const slot = host.querySelector("#ports");
      if (!slot) return;
      if (!Array.isArray(item.ports)) { slot.innerHTML = ""; return; }
      const ports = item.ports;
      if (!ports.length) {
        slot.innerHTML = `<div class="panel"><div class="panel-head"><h2>Poorten</h2></div>
          <div class="muted" style="padding:14px 16px">Vul bij <b>Aantal poorten</b> in hoeveel
            poorten deze switch heeft, dan verschijnt hier de patchlijst.</div></div>`;
        return;
      }
      const free = ports.filter((p) => !p.adapter && !p.beyond).length;
      slot.innerHTML = `<div class="panel">
          <div class="panel-head"><h2>Poorten</h2>
            <span class="sub">${free} van ${ports.filter((p) => !p.beyond).length} vrij</span></div>
          <table class="grid ports"><thead><tr><th>Poort</th><th>Wat erop zit</th>
            <th>Label</th><th>VLAN</th></tr></thead><tbody>
            ${ports.map((p) => `<tr class="${p.adapter ? "" : "free"}">
              <td class="pnum">${p.number}${p.beyond ? ' <span class="tag warn">buiten bereik</span>' : ""}</td>
              <td>${p.adapter
                ? `<a data-goto="${esc(p.adapter.item_id)}">${esc(p.adapter.item_name)}</a>
                   <span class="muted">${esc(p.adapter.name || "")}</span>
                   <span class="mono ad-mac">${esc(p.adapter.mac || "")}</span>`
                : '<span class="muted">vrij</span>'}</td>
              <td>${esc(p.label || "")}</td>
              <td>${p.vlan ? esc(p.vlan) : ""}</td>
            </tr>`).join("")}
          </tbody></table></div>`;
      slot.querySelectorAll("[data-goto]").forEach((a) => {
        a.onclick = () => go(`#/klant/${org.id}/item/${a.dataset.goto}`);
      });
    }

    // ---- the same things, inside the edit form ----
    function adapterFields(a) {
      const rmm = a && a.source === "rmm";
      const field = (key, label, value, mono) => `<div class="frow">
          <label>${esc(label)}</label>
          ${rmm && ["name", "mac", "ipv4"].includes(key)
            ? `<div class="rmm-val">${value ? esc(value) : '<span class="muted">niet bekend</span>'}
                 <span class="tag">uit de RMM</span></div>`
            : `<input class="inp${mono ? " mono" : ""}" data-af="${key}"
                 value="${esc(value || "")}" placeholder="${esc(label)}" />`}
        </div>`;
      const port = a && a.port;
      const options = switchesHere();
      return `
        ${field("name", "Naam", a && a.name)}
        ${field("mac", "MAC-adres", a && a.mac, true)}
        ${field("ipv4", "IPv4-adres", a && a.ipv4, true)}
        ${field("vlan", "VLAN", a && a.vlan)}
        ${field("speed", "Snelheid", a && a.speed)}
        <div class="frow ad-patch">
          <label>Aangesloten op</label>
          <div style="display:flex;gap:8px">
            <select class="inp" data-af="switch" style="flex:1">
              <option value="">— niet aangesloten —</option>
              ${options.map((s) => `<option value="${esc(s.id)}"${
                port && port.switch_id === s.id ? " selected" : ""}>${esc(s.name)}${
                s.fields.ports ? ` (${esc(s.fields.ports)} poorten)` : ""}</option>`).join("")}
            </select>
            <input class="inp" data-af="port" type="number" min="1" placeholder="poort"
                   style="max-width:110px" value="${port ? port.number : ""}" />
          </div>
          ${options.length ? "" : `<div class="hint">Er is nog geen switch bij deze klant.</div>`}
        </div>`;
    }

    function adaptersFormHtml() {
      if (!Array.isArray(item.adapters)) return "";
      return `<div class="panel form-block" id="adapters-form">
          <div class="panel-head"><h2>Netwerkadapters</h2>
            <span class="sub">Het MAC-adres en de switchpoort horen bij dit apparaat,
              dus ze worden hier bewerkt en samen opgeslagen</span></div>
          <div class="form-body" id="adapter-rows">
            ${item.adapters.map((a) => `<div class="ad-edit" data-ad="${esc(a.id)}">
              <div class="ad-edit-head">
                <b>${esc(a.name || "Adapter")}</b>
                ${a.source === "rmm" ? '<span class="tag">RMM</span>' : ""}
                ${a.source === "rmm"
                  ? `<span class="hint" style="margin:0 0 0 auto">Naam, MAC en adres komen uit de RMM</span>`
                  : `<button type="button" class="btn ghost sm" data-drop style="margin-left:auto">${ICON.trash} Verwijderen</button>`}
              </div>
              <div class="ad-edit-grid">${adapterFields(a)}</div>
            </div>`).join("")}
          </div>
          <div class="cb-pad">
            <button type="button" class="btn ghost sm" id="ad-add">${ICON.plus} Adapter toevoegen</button>
          </div>
        </div>`;
    }

    function portsFormHtml() {
      if (!Array.isArray(item.ports) || !item.ports.length) return "";
      const others = switchesHere().filter((s) => s.id !== item.id);
      return `<div class="panel form-block" id="ports-form">
          <div class="panel-head"><h2>Poorten</h2>
            <span class="sub">Label en VLAN per poort. Aansluiten doe je op het apparaat zelf,
              zodat de MAC erbij staat</span></div>
          <div class="ports-bulk">
            <div class="pb-title">${ICON.zap} Snel invullen</div>
            <div class="pb-row">
              <div class="frow"><label for="pb-range">Poorten</label>
                <input class="inp mono" id="pb-range" placeholder="1-24, 26 of alle" /></div>
              <div class="frow"><label for="pb-label">Label</label>
                <input class="inp" id="pb-label" placeholder="Wandpunt A{n}" /></div>
              <div class="frow"><label for="pb-vlan">VLAN</label>
                <input class="inp" id="pb-vlan" placeholder="10" /></div>
              <button type="button" class="btn ghost sm" id="pb-apply">Invullen</button>
            </div>
            <div class="hint"><code>{n}</code> wordt het poortnummer, <code>{i}</code> telt vanaf 1 —
              <i>Wandpunt A{i}</i> op poort 13–24 wordt A1 … A12. Leeg laat staan wat er staat, <code>-</code> maakt leeg.
              Daarna <b>Opslaan</b>.</div>
            ${others.length ? `<div class="pb-row pb-copy">
              <div class="frow"><label for="pb-from">Of overnemen van</label>
                <select class="inp" id="pb-from"><option value="">— een andere switch —</option>
                  ${others.map((s) => `<option value="${esc(s.id)}">${esc(s.name)}${s.fields.ports ? ` (${esc(s.fields.ports)} poorten)` : ""}</option>`).join("")}
                </select></div>
              <button type="button" class="btn ghost sm" id="pb-copy">Labels en VLAN's overnemen</button>
            </div>` : ""}
          </div>
          <table class="grid ports"><thead><tr><th>Poort</th><th>Wat erop zit</th>
            <th>Label</th><th>VLAN</th><th></th></tr></thead><tbody>
            ${item.ports.map((p) => `<tr class="port-edit${p.adapter ? "" : " free"}"
                data-port="${p.number}" data-label="${esc(p.label || "")}"
                data-vlan="${esc(p.vlan || "")}">
              <td class="pnum">${p.number}</td>
              <td>${p.adapter
                ? `${esc(p.adapter.item_name)} <span class="muted">${esc(p.adapter.name || "")}</span>`
                : '<span class="muted">vrij</span>'}</td>
              <td><input class="inp" data-pf="label" value="${esc(p.label || "")}" /></td>
              <td><input class="inp" data-pf="vlan" value="${esc(p.vlan || "")}" style="max-width:100px" /></td>
              <td class="right">${p.adapter
                ? `<button type="button" class="btn ghost sm" data-unpatch>Leegmaken</button>` : ""}</td>
            </tr>`).join("")}
          </tbody></table>
        </div>`;
    }

    function wireAdapterForm() {
      const form = host.querySelector("#adapters-form");
      if (form) {
        const rows = form.querySelector("#adapter-rows");
        const wireDrop = (row) => {
          const drop = row.querySelector("[data-drop]");
          if (!drop) return;
          drop.onclick = () => {
            if (row.dataset.ad) {
              // An existing one is struck through and removed on save, so the
              // whole form still commits in one step.
              row.dataset.remove = row.dataset.remove === "1" ? "0" : "1";
              row.classList.toggle("removing", row.dataset.remove === "1");
              drop.innerHTML = row.dataset.remove === "1"
                ? `${ICON.restart} Toch houden` : `${ICON.trash} Verwijderen`;
            } else {
              row.remove();
            }
          };
        };
        form.querySelectorAll(".ad-edit").forEach(wireDrop);
        form.querySelector("#ad-add").onclick = () => {
          const row = document.createElement("div");
          row.className = "ad-edit";
          row.innerHTML = `<div class="ad-edit-head"><b>Nieuwe adapter</b>
              <button type="button" class="btn ghost sm" data-drop style="margin-left:auto">${ICON.trash} Verwijderen</button></div>
            <div class="ad-edit-grid">${adapterFields(null)}</div>`;
          rows.appendChild(row);
          wireDrop(row);
          row.querySelector("[data-af='name']").focus();
        };
      }
      const ports = host.querySelector("#ports-form");
      if (ports) wirePortsBulk(ports);
      if (ports) {
        ports.querySelectorAll("[data-unpatch]").forEach((b) => {
          b.onclick = () => {
            const row = b.closest("tr");
            row.dataset.unpatch = row.dataset.unpatch === "1" ? "0" : "1";
            row.classList.toggle("removing", row.dataset.unpatch === "1");
            b.textContent = row.dataset.unpatch === "1" ? "Toch laten zitten" : "Leegmaken";
          };
        });
      }
    }

    /* Filling many ports at once: a range, a label with the port number or a
       count in it, a VLAN -- or what another switch already has. It fills the
       form; Opslaan saves it, like a change typed by hand. */
    function wirePortsBulk(form) {
      const rows = () => [...form.querySelectorAll(".port-edit")];
      const flash = (row) => { row.classList.remove("pb-filled"); void row.offsetWidth; row.classList.add("pb-filled"); };
      const pick = (text) => {
        const all = rows();
        const spec = text.trim().toLowerCase();
        if (spec === "alle" || spec === "*") return all;
        const wanted = new Set();
        for (const part of spec.split(/[,;\s]+/).filter(Boolean)) {
          const m = part.match(/^(\d+)(?:-(\d+))?$/);
          if (!m) throw new Error(`“${part}” is geen poort of reeks — schrijf bijvoorbeeld 1-24, 26`);
          const a = Number(m[1]), b = Number(m[2] || m[1]);
          for (let n = Math.min(a, b); n <= Math.max(a, b); n++) wanted.add(n);
        }
        return all.filter((r) => wanted.has(Number(r.dataset.port)));
      };
      const set = (row, key, value) => {
        if (value === "") return;
        row.querySelector(`[data-pf="${key}"]`).value = value === "-" ? "" : value;
      };
      form.querySelector("#pb-apply").onclick = () => {
        let chosen;
        try { chosen = pick(form.querySelector("#pb-range").value); } catch (e) { toast(e.message); return; }
        if (!chosen.length) { toast("Geen van die poorten zit op deze switch"); return; }
        const label = form.querySelector("#pb-label").value.trim();
        const vlan = form.querySelector("#pb-vlan").value.trim();
        if (!label && !vlan) { toast("Vul een label of een VLAN in om te zetten"); return; }
        chosen.forEach((row, i) => {
          set(row, "label", label.replace(/\{n\}/g, row.dataset.port).replace(/\{i\}/g, String(i + 1)));
          set(row, "vlan", vlan);
          flash(row);
        });
        toast(`${chosen.length} ${chosen.length === 1 ? "poort" : "poorten"} ingevuld — nog opslaan`);
      };
      const copy = form.querySelector("#pb-copy");
      if (copy) copy.onclick = async () => {
        const from = form.querySelector("#pb-from").value;
        if (!from) { toast("Kies eerst de switch om van over te nemen"); return; }
        try {
          const other = await api(`/api/items/${from}`);
          const by = Object.fromEntries((other.ports || []).map((p) => [String(p.number), p]));
          let n = 0;
          rows().forEach((row) => {
            const p = by[row.dataset.port];
            if (!p || (!p.label && !p.vlan)) return;
            row.querySelector('[data-pf="label"]').value = p.label || "";
            row.querySelector('[data-pf="vlan"]').value = p.vlan || "";
            flash(row);
            n++;
          });
          toast(n ? `${n} poorten overgenomen van ${other.name} — nog opslaan` : `${other.name} heeft geen labels of VLAN's om over te nemen`);
        } catch (e) { toast(e.message); }
      };
    }

    /* Saving the adapters is a handful of calls rather than one, so the order
       matters: remove first, then write, then patch. A failure halfway stops
       and the page is reloaded from the server, so what you see is what is
       actually stored -- never a form pretending it all went through. */
    async function applyAdapters() {
      const form = host.querySelector("#adapters-form");
      if (!form) return;
      const before = Object.fromEntries((item.adapters || []).map((a) => [a.id, a]));

      for (const row of form.querySelectorAll(".ad-edit")) {
        const get = (key) => {
          const el = row.querySelector(`[data-af="${key}"]`);
          return el ? el.value.trim() : "";
        };
        const id = row.dataset.ad;

        if (id && row.dataset.remove === "1") {
          await api(`/api/adapters/${id}`, { method: "DELETE" });
          continue;
        }

        const values = { name: get("name"), mac: get("mac"), ipv4: get("ipv4"),
                         vlan: get("vlan"), speed: get("speed") };
        let adapterId = id;
        if (!adapterId) {
          if (!values.name && !values.mac) continue;     // an untouched empty row
          adapterId = (await api(`/api/items/${item.id}/adapters`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(values),
          })).id;
        } else {
          await api(`/api/adapters/${adapterId}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(values),
          });
        }

        const chosen = get("switch");
        const port = get("port");
        const was = (before[id] || {}).port;
        if (chosen && !port) throw new Error(`Kies een poortnummer voor ${values.name || "de adapter"}`);
        if (port && !chosen) throw new Error(`Kies een switch voor ${values.name || "de adapter"}`);
        if (chosen && port) {
          if (!was || was.switch_id !== chosen || String(was.number) !== String(port)) {
            await api(`/api/adapters/${adapterId}/connect`, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ switch_id: chosen, port }),
            });
          }
        } else if (was) {
          await api(`/api/adapters/${adapterId}/disconnect`, { method: "POST" });
        }
      }
    }

    async function applyPorts() {
      const form = host.querySelector("#ports-form");
      if (!form) return;
      for (const row of form.querySelectorAll(".port-edit")) {
        const label = row.querySelector('[data-pf="label"]').value.trim();
        const vlan = row.querySelector('[data-pf="vlan"]').value.trim();
        const clear = row.dataset.unpatch === "1";
        // Only the rows somebody touched, so a 48-port switch is not 48 writes.
        if (!clear && label === row.dataset.label && vlan === row.dataset.vlan) continue;
        await api(`/api/items/${item.id}/ports/${row.dataset.port}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(clear ? { label, vlan, adapter_id: null } : { label, vlan }),
        });
      }
    }

    /* The other half of a reference. A computer names its location; standing
       on the location, what you want is the list of what is there. Grouped by
       the field that points, so it reads as sentences rather than as a dump. */
    /* The passwords of a machine, where you look for them: on the machine.
       Those that name it under "Hoort bij" and those linked to it otherwise. */
    function drawPasswords() {
      const slot = host.querySelector("#passwords");
      if (!slot || !KINDS[item.kind] || KINDS[item.kind].family !== "configuratie") return;
      const seen = new Set();
      const rows = [...(item.referred_by || []), ...(item.relations || [])]
        .filter((r) => r.kind === "password" && !seen.has(r.id) && seen.add(r.id));
      slot.innerHTML = `<div class="panel">
          <div class="panel-head"><h2>Wachtwoorden</h2>
            <span class="sub">${rows.length ? rows.length : "Nog geen"}</span>
            ${mayEdit ? `<button class="btn ghost sm" id="pw-add" style="margin-left:auto"
              title="Een wachtwoord voor dit apparaat vastleggen">${ICON.plus} Toevoegen</button>` : ""}</div>
          ${rows.map((r) => `<div class="rel-row" data-goto="${esc(r.id)}">
              <span class="rel-ic">${ICON.key}</span><span class="rel-name">${esc(r.name)}</span>
              ${r.archived ? '<span class="tag">gearchiveerd</span>' : ""}</div>`).join("")}
        </div>`;
      slot.querySelectorAll("[data-goto]").forEach((row) => {
        row.onclick = () => go(`#/klant/${org.id}/item/${row.dataset.goto}`);
      });
      const add = slot.querySelector("#pw-add");
      if (add) add.onclick = () => go(`#/klant/${org.id}/wachtwoorden?voor=${encodeURIComponent(item.id)}`);
    }

    function drawReferredBy() {
      const slot = host.querySelector("#referred");
      if (!slot) return;
      // A password that names this machine is under Wachtwoorden already.
      const rows = (item.referred_by || []).filter((r) => !(r.kind === "password" && r.field === "device"));
      if (!rows.length) { slot.innerHTML = ""; return; }
      const groups = {};
      for (const r of rows) (groups[r.field_label] ||= []).push(r);
      slot.innerHTML = `<div class="panel">
          <div class="panel-head"><h2>${esc(spec.backref || "Wat hiernaar verwijst")}</h2>
            <span class="sub">${rows.length === 1 ? "1 item" : `${rows.length} items`}</span></div>
          ${Object.entries(groups).map(([label, list]) => `
            <div class="backref-group">
              <div class="backref-label">${esc(label)}</div>
              <div>${list.map((r) => `<div class="rel-row" data-goto="${esc(r.id)}">
                <span class="rel-ic">${ICON[KINDS[r.kind] ? KINDS[r.kind].icon : "link"]}</span>
                <span class="rel-name">${esc(r.name)}</span>
                ${r.archived ? '<span class="tag">gearchiveerd</span>' : ""}
                <small>${esc(KINDS[r.kind] ? KINDS[r.kind].label : r.kind)}</small>
              </div>`).join("")}</div>
            </div>`).join("")}
        </div>`;
      slot.querySelectorAll("[data-goto]").forEach((row) => {
        row.onclick = () => go(`#/klant/${org.id}/item/${row.dataset.goto}`);
      });
    }

    /* Related items are stored once and shown from both sides — you link a
       password to a firewall once, and it is on both pages. */
    async function drawRelated() {
      const slot = host.querySelector("#related");
      const rows = item.relations.length ? item.relations.map((r) => `
        <div class="rel-row" data-goto="${esc(r.id)}">
          <span class="rel-ic">${ICON[KINDS[r.kind] ? KINDS[r.kind].icon : "link"]}</span>
          <span class="rel-name">${esc(r.name)}</span>
          <small>${esc(KINDS[r.kind] ? KINDS[r.kind].label : r.kind)}</small>
          ${mayEdit ? `<button class="btn ghost sm" data-unlink="${esc(r.relation_id)}">${ICON.trash}</button>` : ""}
        </div>`).join("")
        : `<div class="muted" style="padding:14px 16px">Nog nergens aan gekoppeld.</div>`;
      const options = all.filter((i) => i.id !== item.id && !i.archived
        && !item.relations.some((r) => r.id === i.id));
      slot.innerHTML = `<div class="panel">
          <div class="panel-head"><h2>Gekoppeld</h2>
            <span class="sub">${item.relations.length || "Wat hier mee samenhangt"}</span></div>
          ${rows}
          ${options.length && mayEdit ? `<div class="rel-add">
            <div class="rel-find">
              <label class="rel-field"><span class="rel-find-ic">${ICON.link}</span>
                <input class="inp" id="rel-search" type="search" autocomplete="off" spellcheck="false"
                       placeholder="Koppel aan… zoek op naam of soort" aria-controls="rel-hits" /></label>
              <div class="rel-hits hidden" id="rel-hits" role="listbox"></div>
            </div></div>` : ""}
        </div>`;
      slot.querySelectorAll(".rel-row").forEach((row) => {
        row.onclick = (e) => {
          if (e.target.closest("[data-unlink]")) return;
          go(`#/klant/${org.id}/item/${row.dataset.goto}`);
        };
      });
      slot.querySelectorAll("[data-unlink]").forEach((b) => {
        b.onclick = async () => {
          try {
            await api(`/api/relations/${b.dataset.unlink}`, { method: "DELETE" });
            item = await api(`/api/items/${item.id}`);
            draw();
          } catch (e) { toast(e.message); }
        };
      });
      const search = slot.querySelector("#rel-search");
      if (search) wireLinkSearch(search, slot.querySelector("#rel-hits"), options);
    }

    /* Linking something: type part of its name, its kind or its type
       ("switch", "wachtwoord", "printer") and pick it -- with the mouse, or
       the arrow keys and Enter. A customer with two hundred items does not
       fit in a drop-down. */
    function wireLinkSearch(search, box, options) {
      const typeOf = (o) => {
        const sub = subtypesOf([o.kind]).find((s) => s.role === (o.fields || {}).role);
        return sub ? sub.label : "";
      };
      const hay = new Map(options.map((o) => [o.id,
        `${o.name} ${(KINDS[o.kind] || {}).label || ""} ${(KINDS[o.kind] || {}).plural || ""} ${typeOf(o)}`.toLowerCase()]));
      const sorted = [...options].sort((a, b) => a.name.localeCompare(b.name, "nl"));
      let hits = [];
      let at = 0;

      const link = async (id) => {
        search.disabled = true;
        try {
          await api(`/api/items/${item.id}/relations`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ item_id: id }),
          });
          item = await api(`/api/items/${item.id}`);
          toast("Gekoppeld");
          draw();
        } catch (e) { toast(e.message); search.disabled = false; }
      };
      const show = () => {
        const words = search.value.toLowerCase().split(/\s+/).filter(Boolean);
        const found = sorted.filter((o) => words.every((w) => hay.get(o.id).includes(w)));
        hits = found.slice(0, 8);
        at = Math.min(at, Math.max(0, hits.length - 1));
        box.innerHTML = hits.length ? hits.map((o, i) => `
            <button type="button" class="rel-hit${i === at ? " on" : ""}" role="option" data-pick="${esc(o.id)}"
                    aria-selected="${i === at}">
              <span class="rel-ic">${ICON[(KINDS[o.kind] || {}).icon] || ICON.link}</span>
              <span class="rel-name">${esc(o.name)}</span>
              <small>${esc([(KINDS[o.kind] || {}).label, typeOf(o)].filter(Boolean).join(" · "))}</small>
            </button>`).join("")
            + (found.length > hits.length ? `<div class="rel-more">nog ${found.length - hits.length} — typ verder om te verfijnen</div>` : "")
          : `<div class="rel-more">Niets gevonden</div>`;
        box.classList.remove("hidden");
        box.querySelectorAll("[data-pick]").forEach((b) => {
          // Before the field loses focus, or the list is gone before the click lands.
          b.onmousedown = (ev) => { ev.preventDefault(); link(b.dataset.pick); };
        });
      };
      search.oninput = () => { at = 0; show(); };
      search.onfocus = show;
      search.onblur = () => box.classList.add("hidden");
      search.onkeydown = (ev) => {
        if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
          ev.preventDefault();
          if (!hits.length) return;
          at = (at + (ev.key === "ArrowDown" ? 1 : -1) + hits.length) % hits.length;
          show();
        } else if (ev.key === "Enter") {
          ev.preventDefault();
          if (hits[at]) link(hits[at].id);
        } else if (ev.key === "Escape") {
          search.value = "";
          box.classList.add("hidden");
        }
      };
    }

    /* Only a change to the item's own fields can be put back by writing the
       old value. A cable moved to another port is not one of those, and a
       button that would do nothing is worse than no button. */
    function revertible(revision) {
      if (revision.action !== "updated" || !revision.changes.length) return false;
      // What the RMM or Microsoft 365 fills is not put back by writing it.
      const own = fieldsOf(item.kind).filter((f) => !held(item, f)).map((f) => f.key);
      return revision.changes.every((c) => c.key === "naam" || own.includes(c.key));
    }

    /* A change said in words, one step a line -- a cabinet arranged in one go
       is a dozen of them, and the last few are the ones you look for. */
    function said(text) {
      const steps = String(text).split("; ");
      const shown = steps.slice(-12);
      const more = steps.length - shown.length;
      return (more ? `<span class="muted">${more} eerdere stappen…</span>` : "")
        + shown.map((s) => `<span>${esc(s)}</span>`).join("");
    }

    /* The latest changes, beside the page; the rest one click away. A machine
       the RMM has kept up for a year has a long history, and the top of it is
       what you came for. */
    const RECENT = 8;
    let wholeHistory = false;

    async function drawHistory() {
      const slot = host.querySelector("#history");
      if (!slot) return;
      const revisions = await api(`/api/items/${item.id}/revisions`).catch(() => []);
      const word = { created: "aangemaakt", updated: "gewijzigd",
                     archived: "gearchiveerd", restored: "uit het archief gehaald",
                     "rmm-gone": "verdween uit de RMM", "rmm-back": "staat weer in de RMM" };
      const shown = wholeHistory ? revisions : revisions.slice(0, RECENT);
      slot.innerHTML = `<div class="panel">
          <div class="panel-head"><h2>Geschiedenis</h2>
            <span class="sub">${revisions.length === 1 ? "1 wijziging" : `${revisions.length} wijzigingen`}</span></div>
          ${shown.map((r) => `<div class="rev-row">
            <div class="rev-top">
              <b>${esc(r.user_email || (r.source === "m365" ? "Microsoft 365" : "de RMM"))}</b>
              <span class="muted">${esc(word[r.action] || r.action)}</span>
              <span class="muted">${when(r.at)}</span>
              ${revertible(r)
                ? `<button class="btn ghost sm" data-revert="${r.id}">${ICON.restart} Terugdraaien</button>`
                : ""}
            </div>
            ${r.changes.map((c) => c.said ? `<div class="rev-change">
              <span class="rc-field">${esc(c.label)}</span>
              <span class="rc-said">${said(c.said)}</span>
            </div>` : `<div class="rev-change">
              <span class="rc-field">${esc(c.label)}</span>
              <span class="rc-from">${c.from ? esc(short(c.from)) : "leeg"}</span>
              <span class="rc-arrow">→</span>
              <span class="rc-to">${c.to ? esc(short(c.to)) : "leeg"}</span>
            </div>`).join("")}
          </div>`).join("")}
          ${revisions.length > RECENT ? `<button type="button" class="rev-more" id="rev-more">${wholeHistory
            ? "Alleen de laatste tonen" : `Alle ${revisions.length} wijzigingen tonen`}</button>` : ""}
        </div>`;
      const more = slot.querySelector("#rev-more");
      if (more) more.onclick = () => { wholeHistory = !wholeHistory; drawHistory(); };
      slot.querySelectorAll("[data-revert]").forEach((b) => {
        b.onclick = async () => {
          b.disabled = true;
          try {
            item = await api(`/api/revisions/${b.dataset.revert}/revert`, { method: "POST" });
            forget(org.id);
            toast("Teruggedraaid");
            draw();
          } catch (e) { toast(e.message); b.disabled = false; }
        };
      });
    }

    await draw();
    return item;
  }

  /* What is about to run out, across everything this customer has. The point
     of a date is being told about it, not being able to look it up. */
  async function expiring(orgId) {
    await kinds();
    const all = await index(orgId, true);
    const out = [];
    for (const item of all) {
      if (item.archived) continue;
      for (const field of shownFieldsOf(item.kind)) {
        const flag = expiry(field, valueOf(item, field));
        if (flag) out.push({ item, field, flag, on: valueOf(item, field) });
      }
    }
    return out.sort((a, b) => String(a.on).localeCompare(String(b.on)));
  }

  /* What a copy starts with: the original's filled-in fields, as the form for a
     new one takes them. Not what the RMM reports (that belongs to the device),
     not passwords, and nothing hidden -- what is not shown is not copied. */
  function copyOf(item) {
    const prefill = { __kind: item.kind, __name: `${item.name} (kopie)`,
                      __from: item.name, __copyOf: item.id };
    for (const f of shownFieldsOf(item.kind)) {
      if (held(item, f) || f.type === "secret") continue;
      const value = item.fields[f.key];
      if (value === undefined || value === null || value === "" || (Array.isArray(value) && !value.length)) continue;
      prefill[f.key] = value;
    }
    return prefill;
  }

  async function itemName(itemId) {
    try { return (await api(`/api/items/${itemId}`)).name; } catch (e) { return null; }
  }

  return { kinds, index, forget, listView, detailView, openCreate, expiring, itemName, setConfig,
           subtypesOf, copyOf };
};
