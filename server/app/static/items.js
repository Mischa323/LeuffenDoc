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
  const indexes = new Map();        // org id -> every item of that customer

  async function kinds() {
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
      return other ? other.name : "—";
    }
    return String(raw);
  }

  function inputFor(field, value, all, orgId) {
    const id = `f-${field.key}`;
    if (field.rmm) {
      return `<div class="rmm-val">${value === "" ? "<span class=\"muted\">niet bekend</span>" : esc(value)}
              <span class="tag">uit de RMM</span></div>`;
    }
    if (field.type === "textarea") {
      return `<textarea class="inp" id="${id}" data-key="${field.key}" rows="3">${esc(value)}</textarea>`;
    }
    if (field.type === "select") {
      return `<select class="inp" id="${id}" data-key="${field.key}">
        <option value=""></option>
        ${field.options.map((o) => `<option${String(o) === String(value) ? " selected" : ""}>${esc(o)}</option>`).join("")}
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

  function formHtml(kind, item, all, orgId) {
    const spec = KINDS[kind];
    return spec.groups.map((group) => `
      <div class="panel form-block">
        <div class="panel-head"><h2>${esc(group.label)}</h2></div>
        <div class="form-body">
          ${group.fields.map((f) => `<div class="frow">
            <label for="f-${f.key}">${esc(f.label)}</label>
            ${inputFor(f, item ? valueOf(item, f) : "", all, orgId)}
            ${f.hint ? `<div class="hint">${esc(f.hint)}</div>` : ""}
          </div>`).join("")}
        </div>
      </div>`).join("");
  }

  function readForm(root) {
    const fields = {};
    root.querySelectorAll("[data-key]").forEach((el) => {
      fields[el.dataset.key] = el.dataset.type === "bool" ? el.checked : el.value.trim();
    });
    return fields;
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
      return field ? display(item, field, all) : "";
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
          ${cols.map((c) => `<td>${esc(display(i, c, all)) || "—"}</td>`).join("")}
          ${shared.map((k) => `<td>${esc(sharedCell(i, k)) || "—"}</td>`).join("")}
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
        <div class="form-foot">
          <button class="btn ghost" id="new-cancel">Annuleren</button>
          <button class="btn" id="new-save">${ICON.save} Aanmaken</button>
        </div>`;
      const picker = slot.querySelector("#new-kind");
      if (picker) picker.onchange = () => { kind = picker.value; const name = slot.querySelector("#new-name").value; draw(); slot.querySelector("#new-name").value = name; };
      slot.querySelector("#new-cancel").onclick = () => { slot.dataset.open = "0"; slot.innerHTML = ""; };
      slot.querySelector("#new-save").onclick = save;
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
          body: JSON.stringify({ kind, name, fields: readForm(slot.querySelector("#new-fields")) }),
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
      const rows = group.fields.map((f) => {
        const text = display(item, f, all);
        if (!text) return "";
        const ref = f.type === "ref" && item.fields[f.key]
          ? `<a data-goto="${esc(item.fields[f.key])}">${esc(text)}</a>` : esc(text);
        return `<div class="dt">${esc(f.label)}${f.rmm ? ' <span class="tag sm">RMM</span>' : ""}</div>
                <div class="dd">${ref}</div>`;
      }).join("");
      if (!rows) return "";
      return `<div class="panel">
          <div class="panel-head"><h2>${esc(group.label)}</h2></div>
          <div class="deflist">${rows}</div>
        </div>`;
    }).join("") || `<div class="panel"><div class="empty">
        <div>Nog niets ingevuld</div>
        <div style="font-size:12.5px;margin-top:6px">Druk op <b>Bewerken</b> om de velden in te vullen.</div>
      </div></div>`;

    const draw = async () => {
      host.innerHTML = head()
        + (editing ? `<div id="edit-fields">${formHtml(item.kind, item, all, org.id)}</div>
             <div class="form-foot"><button class="btn ghost" id="edit-cancel">Annuleren</button>
               <button class="btn" id="edit-save">${ICON.save} Opslaan</button></div>`
                   : readBlocks() + `<div id="related"></div><div id="history"></div>`);
      wireHead();
      if (editing) {
        host.querySelector("#edit-cancel").onclick = () => { editing = false; draw(); };
        host.querySelector("#edit-save").onclick = saveEdit;
        const first = host.querySelector("#edit-fields .inp");
        if (first) first.focus();
      } else {
        host.querySelectorAll("[data-goto]").forEach((a) => {
          a.onclick = () => go(`#/klant/${org.id}/item/${a.dataset.goto}`);
        });
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

    async function drawHistory() {
      const slot = host.querySelector("#history");
      const revisions = await api(`/api/items/${item.id}/revisions`).catch(() => []);
      const word = { created: "aangemaakt", updated: "gewijzigd",
                     archived: "afgevoerd", restored: "teruggezet" };
      slot.innerHTML = `<div class="panel">
          <div class="panel-head"><h2>Geschiedenis</h2>
            <span class="sub">Wie wat veranderde, en waarin</span></div>
          ${revisions.map((r) => `<div class="rev-row">
            <div class="rev-top">
              <b>${esc(r.user_email || "de RMM")}</b>
              <span class="muted">${esc(word[r.action] || r.action)}</span>
              <span class="muted">${when(r.at)}</span>
              ${r.changes.length ? `<button class="btn ghost sm" data-revert="${r.id}">${ICON.restart} Terugdraaien</button>` : ""}
            </div>
            ${r.changes.map((c) => `<div class="rev-change">
              <span class="rc-field">${esc(c.label)}</span>
              <span class="rc-from">${c.from ? esc(c.from) : "leeg"}</span>
              <span class="rc-arrow">→</span>
              <span class="rc-to">${c.to ? esc(c.to) : "leeg"}</span>
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

  async function itemName(itemId) {
    try { return (await api(`/api/items/${itemId}`)).name; } catch (e) { return null; }
  }

  return { kinds, index, forget, listView, detailView, openCreate, itemName };
};
