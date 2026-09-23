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
      return other ? other.name : "(verwijderd)";
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
    if (days <= 60) return { kind: "warn", text: days === 0 ? "vandaag" : `nog ${days} ${days === 1 ? "dag" : "dagen"}` };
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
    if (field.type === "textarea") {
      return `<textarea class="inp" id="${id}" data-key="${field.key}" rows="3">${esc(value)}</textarea>`;
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

  /* No lookalikes: a password read off a screen and typed into a console
     should not fail on I versus l. */
  function generatedPassword(length) {
    const alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#%^&*-_=+";
    const bytes = new Uint32Array(length);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (n) => alphabet[n % alphabet.length]).join("");
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
      if (gen) gen.onclick = () => { slot.querySelector("#new-secret").value = generatedPassword(20); };
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
      const rows = group.fields.map((f) => {
        const text = display(item, f, all);
        if (!text) return "";
        const ref = f.type === "ref" && item.fields[f.key]
          ? `<a data-goto="${esc(item.fields[f.key])}">${esc(text)}</a>` : cell(item, f, all);
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
      const goneNote = item.rmm_gone ? `<div class="callout warn" style="margin-bottom:14px">
          <div class="ic">${ICON.alert}</div><div style="flex:1">
          <div class="ct">Dit apparaat staat niet meer in de RMM</div>
          <div class="cd">Sinds ${when(item.rmm_seen_at)}. De pagina blijft staan — wat je erover
            hebt vastgelegd is meestal juist dan nog nodig. Is de machine weg, voer hem dan af.
            ${item.archived ? "" : `<button class="btn ghost sm" id="gone-archive" style="margin-left:10px">${ICON.box} Afvoeren</button>`}</div>
          </div></div>` : "";
      host.innerHTML = head() + (editing ? "" : goneNote)
        + (editing ? `<div id="edit-fields">${formHtml(item.kind, item, all, org.id)}</div>
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
        const first = host.querySelector("#edit-fields .inp");
        if (first) first.focus();
      } else {
        host.querySelectorAll("[data-goto]").forEach((a) => {
          a.onclick = () => go(`#/klant/${org.id}/item/${a.dataset.goto}`);
        });
        await drawSecret();
        await drawAdapters();
        await drawPorts();
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
    function setForm(id, buttonText) {
      return `<div class="plug-row">
          <input class="inp mono" id="${id}" type="text" autocomplete="new-password"
                 placeholder="Wachtwoord" style="flex:1;min-width:220px" />
          <button class="btn ghost sm" id="${id}-gen">${ICON.refresh} Genereer</button>
          <button class="btn sm" id="${id}-save">${ICON.save} ${buttonText}</button>
        </div>`;
    }

    function wireGenerate(root, id) {
      root.querySelector(`#${id}-gen`).onclick = () => {
        root.querySelector(`#${id}`).value = generatedPassword(20);
        root.querySelector(`#${id}`).type = "text";
      };
    }

    async function drawSecret() {
      const slot = host.querySelector("#secret");
      if (!slot) return;
      if (item.kind !== "password") { slot.innerHTML = ""; return; }
      let shown = null;
      let hideTimer = null;

      const paint = () => {
        const changed = item.secret_updated_at
          ? `Laatst gewijzigd ${when(item.secret_updated_at)}${
              item.secret_updated_by ? ` door ${esc(item.secret_updated_by)}` : ""}`
          : "";
        slot.innerHTML = `<div class="panel secret-panel">
            <div class="panel-head"><h2>Wachtwoord</h2>
              <span class="sub">${esc(changed)}</span></div>
            ${item.has_secret ? `
              <div class="secret-row">
                <span class="secret-val mono" id="secret-val">${shown ? esc(shown) : "••••••••••••"}</span>
                <button class="btn ghost sm" id="secret-show">${shown ? ICON.eyeOff : ICON.eye} ${shown ? "Verberg" : "Tonen"}</button>
                <button class="btn ghost sm" id="secret-copy">${ICON.copy} Kopiëren</button>
                <button class="btn ghost sm" id="secret-edit">${ICON.pencil} Wijzigen</button>
              </div>
              <div class="secret-note">Elke keer dat dit wachtwoord getoond of gekopieerd
                wordt, komt dat in het logboek te staan.</div>
              <div id="secret-form"></div>`
            : `<div class="secret-row">
                 <span class="muted">Er staat nog geen wachtwoord in.</span></div>
               <div class="cb-pad">${setForm("secret-new", "Opslaan")}</div>`}
          </div>`;

        if (!item.has_secret) {
          wireGenerate(slot, "secret-new");
          slot.querySelector("#secret-new-save").onclick = () => save("secret-new");
          return;
        }

        slot.querySelector("#secret-show").onclick = async () => {
          if (shown) { shown = null; clearTimeout(hideTimer); paint(); return; }
          try {
            shown = (await api(`/api/items/${item.id}/secret`)).password;
            // Back to dots by itself: a password left on a screen in an office
            // is the most ordinary way one gets out.
            hideTimer = setTimeout(() => { shown = null; paint(); }, 30000);
            paint();
          } catch (e) { toast(e.message); }
        };

        slot.querySelector("#secret-copy").onclick = async () => {
          try {
            const value = shown || (await api(`/api/items/${item.id}/secret`)).password;
            await navigator.clipboard.writeText(value);
            toast("Gekopieerd");
          } catch (e) {
            // Without https the browser refuses the clipboard. Show it instead
            // of failing silently, and say why.
            try {
              shown = (await api(`/api/items/${item.id}/secret`)).password;
              paint();
              toast("Kopiëren mag niet in deze browser — hier is hij");
            } catch (inner) { toast(inner.message); }
          }
        };

        slot.querySelector("#secret-edit").onclick = () => {
          const box = slot.querySelector("#secret-form");
          if (box.dataset.open === "1") { box.dataset.open = "0"; box.innerHTML = ""; return; }
          box.dataset.open = "1";
          box.innerHTML = `<div class="cb-pad">${setForm("secret-set", "Vervangen")}</div>`;
          wireGenerate(box, "secret-set");
          box.querySelector("#secret-set-save").onclick = () => save("secret-set");
          box.querySelector("#secret-set").focus();
        };
      };

      const save = async (id) => {
        const field = slot.querySelector(`#${id}`);
        const value = field.value;
        if (!value) { toast("Vul eerst een wachtwoord in"); field.focus(); return; }
        try {
          await api(`/api/items/${item.id}/secret`, {
            method: "PUT", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password: value }),
          });
          item = await api(`/api/items/${item.id}`);
          shown = null;
          toast("Wachtwoord opgeslagen");
          draw();
        } catch (e) { toast(e.message); }
      };

      paint();
    }

    /* Network adapters, and the port each one is patched into.

       You make the connection here, on the machine, because that is where you
       are when you know the answer — but it is kept on the port, so the switch
       can show its patch list and no two machines can claim one port. */
    async function drawAdapters() {
      const slot = host.querySelector("#adapters");
      if (!slot) return;
      // Only equipment has network adapters. The server sends the field for
      // those alone, so a password or a contact leaves the panel out instead
      // of offering to give a contact person a MAC address.
      if (!Array.isArray(item.adapters)) { slot.innerHTML = ""; return; }
      const adapters = item.adapters;
      const switches = all.filter((i) => i.kind === "network" && !i.archived
        && (i.fields.role === "Switch" || Number(i.fields.ports || 0) > 0));

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
          </div>
          <div class="ad-port">${where}</div>
          <div class="ad-act">
            ${a.port ? `<button class="btn ghost sm" data-unplug="${esc(a.id)}">Loskoppelen</button>`
                     : `<button class="btn ghost sm" data-plug="${esc(a.id)}">${ICON.link} Aansluiten</button>`}
            ${a.source === "rmm" ? "" : `<button class="btn ghost sm" data-del-ad="${esc(a.id)}">${ICON.trash}</button>`}
          </div>
          <div class="ad-form" id="plug-${esc(a.id)}"></div>
        </div>`;
      }).join("") : `<div class="muted" style="padding:14px 16px">
          Nog geen netwerkadapters.${item.source === "rmm"
            ? " Van een machine met een agent komen ze uit de RMM."
            : ""}</div>`;

      slot.innerHTML = `<div class="panel">
          <div class="panel-head"><h2>Netwerkadapters</h2>
            <span class="sub">Met het MAC-adres en de switchpoort waar ze aan hangen</span>
            <div class="spacer"></div>
            <button class="btn ghost sm" id="ad-add">${ICON.plus} Adapter</button></div>
          ${rows}
          <div id="ad-new"></div>
        </div>`;

      slot.querySelectorAll("[data-goto]").forEach((a) => {
        a.onclick = () => go(`#/klant/${org.id}/item/${a.dataset.goto}`);
      });

      slot.querySelectorAll("[data-plug]").forEach((b) => {
        b.onclick = () => {
          const id = b.dataset.plug;
          const box = slot.querySelector(`#plug-${CSS.escape(id)}`);
          if (box.dataset.open === "1") { box.dataset.open = "0"; box.innerHTML = ""; return; }
          box.dataset.open = "1";
          if (!switches.length) {
            box.innerHTML = `<div class="hint">Er is nog geen switch bij deze klant.
              Maak er een aan onder <b>Configuraties</b>, met het aantal poorten erbij.</div>`;
            return;
          }
          box.innerHTML = `<div class="plug-row">
              <select class="inp" id="plug-switch">${switches.map((s) =>
                `<option value="${esc(s.id)}">${esc(s.name)}${s.fields.ports ? ` (${esc(s.fields.ports)} poorten)` : ""}</option>`).join("")}</select>
              <input class="inp" id="plug-port" type="number" min="1" placeholder="poort" style="max-width:110px" />
              <input class="inp" id="plug-label" placeholder="label (optioneel)" style="max-width:180px" />
              <button class="btn sm" id="plug-go">Aansluiten</button>
            </div>`;
          box.querySelector("#plug-port").focus();
          const attach = async () => {
            try {
              await api(`/api/adapters/${id}/connect`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ switch_id: box.querySelector("#plug-switch").value,
                                       port: box.querySelector("#plug-port").value,
                                       label: box.querySelector("#plug-label").value }),
              });
              item = await api(`/api/items/${item.id}`);
              toast("Aangesloten");
              draw();
            } catch (e) { toast(e.message); }
          };
          box.querySelector("#plug-go").onclick = attach;
          box.querySelector("#plug-port").addEventListener("keydown",
            (e) => { if (e.key === "Enter") attach(); });
        };
      });

      slot.querySelectorAll("[data-unplug]").forEach((b) => {
        b.onclick = async () => {
          try {
            await api(`/api/adapters/${b.dataset.unplug}/disconnect`, { method: "POST" });
            item = await api(`/api/items/${item.id}`);
            toast("Losgekoppeld");
            draw();
          } catch (e) { toast(e.message); }
        };
      });

      slot.querySelectorAll("[data-del-ad]").forEach((b) => {
        b.onclick = async () => {
          try {
            await api(`/api/adapters/${b.dataset.delAd}`, { method: "DELETE" });
            item = await api(`/api/items/${item.id}`);
            draw();
          } catch (e) { toast(e.message); }
        };
      });

      slot.querySelector("#ad-add").onclick = () => {
        const box = slot.querySelector("#ad-new");
        if (box.dataset.open === "1") { box.dataset.open = "0"; box.innerHTML = ""; return; }
        box.dataset.open = "1";
        box.innerHTML = `<div class="plug-row">
            <input class="inp" id="ad-name" placeholder="Naam, bijv. LAN" style="max-width:200px" />
            <input class="inp mono" id="ad-mac" placeholder="MAC-adres" style="max-width:220px" />
            <input class="inp mono" id="ad-ip" placeholder="IPv4" style="max-width:170px" />
            <input class="inp" id="ad-vlan" placeholder="VLAN" style="max-width:110px" />
            <button class="btn sm" id="ad-save">Toevoegen</button>
          </div>`;
        box.querySelector("#ad-name").focus();
        box.querySelector("#ad-save").onclick = async () => {
          try {
            await api(`/api/items/${item.id}/adapters`, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ name: box.querySelector("#ad-name").value,
                                     mac: box.querySelector("#ad-mac").value,
                                     ipv4: box.querySelector("#ad-ip").value,
                                     vlan: box.querySelector("#ad-vlan").value }),
            });
            item = await api(`/api/items/${item.id}`);
            forget(org.id);
            draw();
          } catch (e) { toast(e.message); }
        };
      };
    }

    /* A switch's patch list. The whole point is the empty rows: you come here
       to find a free port as often as to look one up. */
    async function drawPorts() {
      const slot = host.querySelector("#ports");
      if (!slot) return;
      // Only a switch has a patch list. The server sends the field at all only
      // for one, so anything else leaves the panel out entirely rather than
      // inviting a computer to say how many ports it has.
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
            <th>Label</th><th>VLAN</th><th></th></tr></thead><tbody>
            ${ports.map((p) => `<tr class="${p.adapter ? "" : "free"}">
              <td class="pnum">${p.number}${p.beyond ? ' <span class="tag warn">buiten bereik</span>' : ""}</td>
              <td>${p.adapter
                ? `<a data-goto="${esc(p.adapter.item_id)}">${esc(p.adapter.item_name)}</a>
                   <span class="muted">${esc(p.adapter.name || "")}</span>
                   <span class="mono ad-mac">${esc(p.adapter.mac || "")}</span>`
                : '<span class="muted">vrij</span>'}</td>
              <td>${esc(p.label || "")}</td>
              <td>${p.vlan ? esc(p.vlan) : ""}</td>
              <td class="right">${p.adapter
                ? `<button class="btn ghost sm" data-clear="${p.number}">Leegmaken</button>` : ""}</td>
            </tr>`).join("")}
          </tbody></table></div>`;
      slot.querySelectorAll("[data-goto]").forEach((a) => {
        a.onclick = () => go(`#/klant/${org.id}/item/${a.dataset.goto}`);
      });
      slot.querySelectorAll("[data-clear]").forEach((b) => {
        b.onclick = async () => {
          try {
            await api(`/api/items/${item.id}/ports/${b.dataset.clear}`, {
              method: "PATCH", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ adapter_id: null }),
            });
            item = await api(`/api/items/${item.id}`);
            toast("Poort leeggemaakt");
            draw();
          } catch (e) { toast(e.message); }
        };
      });
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

  return { kinds, index, forget, listView, detailView, openCreate, expiring, itemName };
};
