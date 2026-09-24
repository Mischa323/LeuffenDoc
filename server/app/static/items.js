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

  async function index(orgId, fresh) {
    if (fresh) indexes.delete(orgId);
    if (!indexes.has(orgId)) {
      indexes.set(orgId, await api(`/api/orgs/${orgId}/items?archived=true`));
    }
    return indexes.get(orgId);
  }

  const forget = (orgId) => indexes.delete(orgId);

  // ---- fields ----
  function fieldsOf(kind) {
    const out = [];
    for (const group of KINDS[kind].groups) {
      for (const f of group.fields) out.push({ ...f, group: group.key });
    }
    return out;
  }

  /* Where a value comes from decides who may set it. A field the RMM fills is
     shown from the RMM and never typed here, so a documented memory size cannot
     quietly disagree with the machine. */
  function valueOf(item, field) {
    if (field.rmm) return (item.rmm || {})[field.rmm] ?? "";
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
      return other ? other.name : "(verwijderd)";
    }
    if (field.type === "list") {
      return (Array.isArray(raw) ? raw : [])
        .map((e) => (e.label ? `${e.label}: ${e.value}` : e.value)).join(" · ");
    }
    return String(raw);
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

  function inputFor(field, value, all, orgId) {
    const id = `f-${field.key}`;
    if (field.rmm) {
      return `<div class="rmm-val">${value === "" ? "<span class=\"muted\">niet bekend</span>" : esc(value)}
              <span class="tag">uit de RMM</span></div>`;
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
      const options = (all || []).filter((i) => i.kind === field.ref && !i.archived);
      return `<select class="inp" id="${id}" data-key="${field.key}">
        <option value="">—</option>
        ${options.map((o) => `<option value="${esc(o.id)}"${o.id === value ? " selected" : ""}>${esc(o.name)}</option>`).join("")}
      </select>${options.length ? "" : `<div class="hint">Nog geen ${esc(KINDS[field.ref].plural.toLowerCase())} bij deze klant.</div>`}`;
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
  }

  function formHtml(kind, item, all, orgId) {
    const spec = KINDS[kind];
    return spec.groups.map((group) => `
      <div class="panel form-block">
        <div class="panel-head"><h2>${esc(group.label)}</h2></div>
        <div class="form-body">
          ${group.fields.map((f) => `<div class="frow">
            <label for="f-${f.key}">${f.icon && ICON[f.icon]
              ? `<span class="lb-ic">${ICON[f.icon]}</span>` : ""}${esc(f.label)}</label>
            ${inputFor(f, item ? valueOf(item, f) : "", all, orgId)}
            ${f.hint ? `<div class="hint">${esc(f.hint)}</div>` : ""}
          </div>`).join("")}
        </div>
      </div>`).join("");
  }

  function readForm(root) {
    const fields = {};
    root.querySelectorAll("[data-key]").forEach((el) => {
      if (el.dataset.type === "list") {
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
    const byKey = Object.fromEntries(fieldsOf(kind).map((f) => [f.key, f]));
    return wanted.map((k) => byKey[k]).filter(Boolean);
  }

  async function listView(host, org, section) {
    await kinds();
    const all = await index(org.id);
    const allowed = section.kinds;
    const params = new URLSearchParams(location.hash.split("?")[1] || "");
    let kind = allowed.includes(params.get("soort")) ? params.get("soort") : null;
    let showArchived = params.get("oud") === "1";

    const items = all.filter((i) => allowed.includes(i.kind)
      && (!kind || i.kind === kind) && (showArchived || !i.archived));

    const chips = allowed.length > 1 ? `<div class="chips">
      <button class="chip${kind ? "" : " on"}" data-kind="">Alles
        <span class="n">${all.filter((i) => allowed.includes(i.kind) && !i.archived).length}</span></button>
      ${allowed.map((k) => `<button class="chip${kind === k ? " on" : ""}" data-kind="${k}">
        ${ICON[KINDS[k].icon]} ${esc(KINDS[k].plural)}
        <span class="n">${all.filter((i) => i.kind === k && !i.archived).length}</span></button>`).join("")}
    </div>` : "";

    const archivedCount = all.filter((i) => allowed.includes(i.kind) && i.archived).length;
    const oldToggle = archivedCount ? `<button class="btn ghost sm" id="toggle-old">
      ${showArchived ? "Verberg" : "Toon"} afgevoerde (${archivedCount})</button>` : "";

    // Columns come from the kind. A mixed list can only show what every kind
    // in it has, which for equipment is the status -- better than a bare list
    // of names, and never a column that is empty for half the rows.
    const cols = kind ? columnsOf(kind) : [];
    const shared = kind ? [] : (KINDS[allowed[0]].columns || [])
      .filter((k) => allowed.every((a) => (KINDS[a].columns || []).includes(k)));
    const sharedLabels = shared.map((k) =>
      (columnsOf(allowed[0]).find((c) => c.key === k) || {}).label || k);
    const sharedCell = (item, key) => {
      const field = fieldsOf(item.kind).find((f) => f.key === key);
      return field ? cell(item, field, all) : "";
    };
    const table = items.length ? `<div class="panel"><table class="grid"><thead><tr>
        <th>Naam</th>${kind ? "" : "<th>Soort</th>"}
        ${cols.map((c) => `<th>${esc(c.label)}</th>`).join("")}
        ${sharedLabels.map((l) => `<th>${esc(l)}</th>`).join("")}
        <th></th></tr></thead><tbody>
        ${items.map((i) => `<tr data-item="${esc(i.id)}">
          <td><b>${esc(i.name)}</b>${i.archived ? ' <span class="tag">afgevoerd</span>' : ""}
            ${i.rmm_gone ? ' <span class="tag warn">niet meer in de RMM</span>' : ""}</td>
          ${kind ? "" : `<td><span class="kind-cell">${ICON[KINDS[i.kind].icon]} ${esc(KINDS[i.kind].label)}</span></td>`}
          ${cols.map((c) => `<td>${cell(i, c, all) || "—"}</td>`).join("")}
          ${shared.map((k) => `<td>${sharedCell(i, k) || "—"}</td>`).join("")}
          <td class="right">${i.source === "rmm" ? '<span class="tag">RMM</span>' : ""}</td>
        </tr>`).join("")}
      </tbody></table></div>`
      : `<div class="panel"><div class="empty"><div class="big">${ICON[KINDS[allowed[0]].icon]}</div>
          <div>Nog niets vastgelegd</div>
          <div style="font-size:12.5px;margin-top:6px">${esc(section.empty)}</div></div></div>`;

    host.innerHTML = `<div id="new-item"></div>${chips}
      ${oldToggle ? `<div style="margin-bottom:12px">${oldToggle}</div>` : ""}${table}`;

    host.querySelectorAll(".chip").forEach((b) => {
      b.onclick = () => {
        const next = b.dataset.kind;
        go(`#/klant/${org.id}/${section.id}${next ? `?soort=${next}` : ""}`);
      };
    });
    const old = host.querySelector("#toggle-old");
    if (old) old.onclick = () => go(`#/klant/${org.id}/${section.id}?${new URLSearchParams(
      { ...(kind ? { soort: kind } : {}), ...(showArchived ? {} : { oud: "1" }) })}`);
    host.querySelectorAll("tr[data-item]").forEach((tr) => {
      tr.onclick = () => go(`#/klant/${org.id}/item/${tr.dataset.item}`);
    });
  }

  /* Adding something is a panel on the page, not a browser dialog: those are
     refused outright in some browsers, and a button that does nothing at all is
     indistinguishable from a broken one. */
  async function openCreate(org, section, host) {
    await kinds();
    const all = await index(org.id);
    const slot = host.querySelector("#new-item");
    if (!slot) return;
    if (slot.dataset.open === "1") { slot.dataset.open = "0"; slot.innerHTML = ""; return; }
    slot.dataset.open = "1";
    let kind = section.kinds[0];

    const draw = () => {
      slot.innerHTML = `<div class="panel new-head">
          <div class="panel-head"><h2>${esc(KINDS[kind].label)} toevoegen</h2></div>
          <div class="form-body">
            ${section.kinds.length > 1 ? `<div class="frow"><label>Soort</label>
              <select class="inp" id="new-kind">${section.kinds.map((k) =>
                `<option value="${k}"${k === kind ? " selected" : ""}>${esc(KINDS[k].label)}</option>`).join("")}</select></div>` : ""}
            <div class="frow"><label for="new-name">Naam</label>
              <input class="inp" id="new-name" placeholder="${esc(section.example)}" /></div>
          </div>
        </div>
        <div id="new-fields">${formHtml(kind, null, all, org.id)}</div>
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
      slot.querySelector("#new-name").focus();
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
    let all = await index(org.id);      // refreshed after a change, for the ref fields
    const spec = KINDS[item.kind];
    let editing = false;

    const source = item.source === "rmm"
      ? (item.rmm_gone
         ? `<span class="tag warn">niet meer in de RMM sinds ${when(item.rmm_seen_at)}</span>`
         : `<span class="tag">uit de RMM, bijgewerkt ${when(item.rmm_seen_at)}</span>`)
      : `<span class="tag">hier vastgelegd</span>`;

    const head = () => `<div class="panel item-head">
        <div class="ih-mark">${ICON[spec.icon]}</div>
        <div class="ih-txt">
          <h3>${esc(item.name)}${item.archived ? ' <span class="tag">afgevoerd</span>' : ""}</h3>
          <small>${esc(spec.label)} · ${source}</small>
        </div>
        <div class="ih-act" id="item-actions"></div>
      </div>`;

    const readBlocks = () => spec.groups.map((group) => {
      // A page of text does not belong in a label-and-value grid; it gets the
      // width of the panel and keeps the line breaks it was written with.
      const long = group.fields.filter((f) => f.long && display(item, f, all));
      const rows = group.fields.filter((f) => !f.long).map((f) => {
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
                  <span>${esc(f.label)}</span>${f.rmm ? ' <span class="tag sm">RMM</span>' : ""}</div>
                <div class="dd">${ref}</div>`;
      }).join("");
      if (!rows && !long.length) return "";
      return `<div class="panel">
          <div class="panel-head"><h2>${esc(group.label)}</h2></div>
          ${rows ? `<div class="deflist">${rows}</div>` : ""}
          ${long.map((f) => `<div class="longtext">${esc(display(item, f, all))}</div>`).join("")}
        </div>`;
    }).join("") || `<div class="panel"><div class="empty">
        <div>Nog niets ingevuld</div>
        <div style="font-size:12.5px;margin-top:6px">Druk op <b>Bewerken</b> om de velden in te vullen.</div>
      </div></div>`;

    const draw = async () => {
      const goneNote = item.rmm_gone ? `<div class="callout warn" style="margin-bottom:14px">
          <div class="ic">${ICON.alert}</div><div style="flex:1">
          <div class="ct">Dit apparaat staat niet meer in de RMM</div>
          <div class="cd">Sinds ${when(item.rmm_seen_at)}. De pagina blijft staan — wat je erover
            hebt vastgelegd is meestal juist dan nog nodig. Is de machine weg, voer hem dan af.
            ${item.archived ? "" : `<button class="btn ghost sm" id="gone-archive" style="margin-left:10px">${ICON.box} Afvoeren</button>`}</div>
          </div></div>` : "";
      host.innerHTML = head() + (editing ? "" : goneNote)
        + (editing ? `<div id="edit-fields">${formHtml(item.kind, item, all, org.id)}</div>
             ${adaptersFormHtml()}${portsFormHtml()}
             <div class="form-foot"><button class="btn ghost" id="edit-cancel">Annuleren</button>
               <button class="btn" id="edit-save">${ICON.save} Opslaan</button></div>`
                   : readBlocks()
                     + `<div id="secret"></div>`
                     + `<div id="adapters"></div><div id="ports"></div>`
                     + `<div id="referred"></div>`
                     + `<div id="related"></div><div id="history"></div>`);
      wireHead();
      const goneBtn = host.querySelector("#gone-archive");
      if (goneBtn) goneBtn.onclick = () => host.querySelector("#btn-archive").click();
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
        drawSecret();
        drawAdapters();
        drawPorts();
        drawReferredBy();
        await drawRelated();
        await drawHistory();
      }
    };

    function wireHead() {
      const act = host.querySelector("#item-actions");
      act.innerHTML = editing ? "" : `
        <button class="btn ghost sm" id="btn-edit">${ICON.pencil} Bewerken</button>
        <button class="btn ghost sm" id="btn-archive">${item.archived ? ICON.refresh + " Terugzetten" : ICON.box + " Afvoeren"}</button>`;
      if (editing) return;
      act.querySelector("#btn-edit").onclick = () => { editing = true; draw(); };
      act.querySelector("#btn-archive").onclick = async () => {
        try {
          item = await api(`/api/items/${item.id}/archive`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ archived: !item.archived }),
          });
          forget(org.id);
          toast(item.archived ? "Afgevoerd" : "Teruggezet");
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

    /* The password itself. It is not a field: it never travels with the rest
       of the page, it is asked for one at a time, and every reading is a line
       in the log — which is the whole reason the log is worth reading. */
    /* Which secrets this item has. A vault entry keeps one under "main"; a
       type defined here can have several, each on its own field -- a tenant
       with an administrator password and a break-glass account, say. */
    function secretSlots() {
      const out = item.kind === "password" ? [{ field: "main", label: "Wachtwoord" }] : [];
      for (const f of fieldsOf(item.kind)) {
        if (f.type === "secret") out.push({ field: f.key, label: f.label, hint: f.hint });
      }
      return out;
    }

    function secretState(field) {
      if (field === "main") {
        return { has_secret: item.has_secret, secret_updated_at: item.secret_updated_at,
                 secret_updated_by: item.secret_updated_by };
      }
      return (item.secrets || {})[field] || { has_secret: false };
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
        const changed = state.secret_updated_at
          ? `Laatst gewijzigd ${when(state.secret_updated_at)}${
              state.secret_updated_by ? ` door ${esc(state.secret_updated_by)}` : ""}`
          : (spec.hint || "");
        slot.innerHTML = `<div class="panel secret-panel">
            <div class="panel-head"><h2>${esc(spec.label)}</h2>
              <span class="sub">${esc(changed)}</span></div>
            ${state.has_secret ? `
              <div class="secret-row">
                <span class="secret-val mono sx-val">${shown ? esc(shown) : "••••••••••••"}</span>
                <button type="button" class="btn ghost sm sx-show">${shown ? ICON.eyeOff : ICON.eye} ${shown ? "Verberg" : "Tonen"}</button>
                <button type="button" class="btn ghost sm sx-copy">${ICON.copy} Kopiëren</button>
                <button type="button" class="btn ghost sm sx-edit">${ICON.pencil} Wijzigen</button>
              </div>
              <div class="secret-note">Elke keer dat dit getoond of gekopieerd wordt,
                komt dat in het logboek te staan.</div>
              <div class="sx-form"></div>`
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
      return `<div class="panel form-block" id="ports-form">
          <div class="panel-head"><h2>Poorten</h2>
            <span class="sub">Label en VLAN per poort. Aansluiten doe je op het apparaat zelf,
              zodat de MAC erbij staat</span></div>
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
    function drawReferredBy() {
      const slot = host.querySelector("#referred");
      if (!slot) return;
      const rows = item.referred_by || [];
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
                ${r.archived ? '<span class="tag">afgevoerd</span>' : ""}
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
          <button class="btn ghost sm" data-unlink="${esc(r.relation_id)}">${ICON.trash}</button>
        </div>`).join("")
        : `<div class="muted" style="padding:14px 16px">Nog nergens aan gekoppeld.</div>`;
      const options = all.filter((i) => i.id !== item.id && !i.archived
        && !item.relations.some((r) => r.id === i.id));
      slot.innerHTML = `<div class="panel">
          <div class="panel-head"><h2>Gerelateerd</h2>
            <span class="sub">Wat hier mee samenhangt</span></div>
          ${rows}
          ${options.length ? `<div class="rel-add">
            <select class="inp" id="rel-pick"><option value="">Koppel aan…</option>
              ${options.map((o) => `<option value="${esc(o.id)}">${esc(KINDS[o.kind].label)}: ${esc(o.name)}</option>`).join("")}
            </select>
            <button class="btn sm" id="rel-go">${ICON.link} Koppelen</button></div>` : ""}
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
      const go_ = slot.querySelector("#rel-go");
      if (go_) go_.onclick = async () => {
        const pick = slot.querySelector("#rel-pick").value;
        if (!pick) return;
        try {
          await api(`/api/items/${item.id}/relations`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ item_id: pick }),
          });
          item = await api(`/api/items/${item.id}`);
          draw();
        } catch (e) { toast(e.message); }
      };
    }

    /* Only a change to the item's own fields can be put back by writing the
       old value. A cable moved to another port is not one of those, and a
       button that would do nothing is worse than no button. */
    function revertible(revision) {
      if (revision.action !== "updated" || !revision.changes.length) return false;
      const own = fieldsOf(item.kind).map((f) => f.key);
      return revision.changes.every((c) => c.key === "naam" || own.includes(c.key));
    }

    async function drawHistory() {
      const slot = host.querySelector("#history");
      const revisions = await api(`/api/items/${item.id}/revisions`).catch(() => []);
      const word = { created: "aangemaakt", updated: "gewijzigd",
                     archived: "afgevoerd", restored: "teruggezet",
                     "rmm-gone": "verdween uit de RMM", "rmm-back": "staat weer in de RMM" };
      slot.innerHTML = `<div class="panel">
          <div class="panel-head"><h2>Geschiedenis</h2>
            <span class="sub">Wie wat veranderde, en waarin</span></div>
          ${revisions.map((r) => `<div class="rev-row">
            <div class="rev-top">
              <b>${esc(r.user_email || "de RMM")}</b>
              <span class="muted">${esc(word[r.action] || r.action)}</span>
              <span class="muted">${when(r.at)}</span>
              ${revertible(r)
                ? `<button class="btn ghost sm" data-revert="${r.id}">${ICON.restart} Terugdraaien</button>`
                : ""}
            </div>
            ${r.changes.map((c) => `<div class="rev-change">
              <span class="rc-field">${esc(c.label)}</span>
              <span class="rc-from">${c.from ? esc(short(c.from)) : "leeg"}</span>
              <span class="rc-arrow">→</span>
              <span class="rc-to">${c.to ? esc(short(c.to)) : "leeg"}</span>
            </div>`).join("")}
          </div>`).join("")}
        </div>`;
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
    const all = await index(orgId);
    const out = [];
    for (const item of all) {
      if (item.archived) continue;
      for (const field of fieldsOf(item.kind)) {
        const flag = expiry(field, valueOf(item, field));
        if (flag) out.push({ item, field, flag, on: valueOf(item, field) });
      }
    }
    return out.sort((a, b) => String(a.on).localeCompare(String(b.on)));
  }

  async function itemName(itemId) {
    try { return (await api(`/api/items/${itemId}`)).name; } catch (e) { return null; }
  }

  return { kinds, index, forget, listView, detailView, openCreate, expiring, itemName, setConfig };
};
