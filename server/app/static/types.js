/* Documenttypes — what can be documented, and how its page is laid out.

   Every type, built in or made here, is laid out in blocks: which blocks, in
   what order, how wide, and which fields sit in each. Fields are dragged
   within a block or to another one, blocks are dragged into order, and a
   block is full width or half -- two half blocks sit side by side on the page.

   A built-in field (from LeuffenDoc itself) can be moved, renamed, explained
   differently and hidden, but not removed or turned into something else: the
   RMM sync, the switch ports and the vault count on it. A hidden field keeps
   its value. Fields and blocks added here are yours to change or remove.

   Nothing else in the interface knows about this page: the things made from a
   type are rendered by the same code as everything else, which is the whole
   reason it works. */
window.DocTypes = function (ctx) {
  "use strict";

  const { api, esc, toast, kinds } = ctx;

  // Which icon to put on a type. A short list beats a search box of four hundred.
  const ICONS = ["layers", "box", "package", "cloud", "globe", "shield", "shieldCheck",
                 "key", "lock", "mail", "user", "building", "file", "folder", "clipboard",
                 "network", "server", "desktop", "monitor", "nas", "disk", "cpu", "mem",
                 "clock", "history", "zap", "bolt", "target", "radio", "wifi", "phone",
                 "code", "terminal", "gear", "euro"];

  const TYPE_NAMES = {
    text: "Tekst", textarea: "Lange tekst", number: "Getal", date: "Datum",
    select: "Keuze uit een lijst", bool: "Ja of nee", ip: "IP-adres",
    mac: "MAC-adres", list: "Meerdere waarden", secret: "Wachtwoord (versleuteld)",
    ref: "Verwijzing naar iets anders",
  };

  let catalogue = null;       // what /api/types last said
  let draft = null;           // the type being laid out, or null
  let openField = null;       // the field whose details are open (its _id)
  let pending = null;         // a refusal that can be overruled: { message, label, retry }
  let seq = 0;
  const nid = () => `f${++seq}`;
  const newField = () => ({ _id: nid(), key: "", label: "", type: "text", options: [], hint: "" });
  const alwaysShown = (f) => f.base && (catalogue.always_shown || []).includes(f.key);

  async function load() {
    catalogue = await api("/api/types");
    return catalogue;
  }

  // ---- a type, as the editor holds it ----
  function fromSpec(spec, builtIn) {
    const groups = (spec.groups || []).map((g) => ({
      key: g.key, label: g.label, width: g.width === "half" ? "half" : "full",
      fields: g.fields.map((f) => ({ ...JSON.parse(JSON.stringify(f)), _id: nid(),
                                     base: builtIn && !f.extra })),
    }));
    const idOf = {};
    groups.forEach((g) => g.fields.forEach((f) => { idOf[f.key] = f._id; }));
    return {
      id: spec.id, builtIn, label: spec.label, plural: spec.plural, icon: spec.icon || "layers",
      sub: spec.sub || "", adapters: !!spec.adapters, customized: !!spec.customized,
      columns: new Set((spec.columns || []).map((k) => idOf[k]).filter(Boolean)),
      groups,
    };
  }

  const blank = () => ({
    id: null, builtIn: false, label: "", plural: "", icon: "layers", sub: "", adapters: false,
    columns: new Set(),
    groups: [{ key: "", label: "Gegevens", width: "full", fields: [newField()] }],
  });

  // ---- the list ----
  function typeCard(spec, builtIn) {
    const fields = (spec.groups || []).reduce((n, g) => n + g.fields.length, 0);
    const meta = builtIn
      ? (spec.customized ? `<span class="tag on">aangepast</span>` : `<span class="tag">ingebouwd</span>`)
      : `<span class="muted">${fields} velden</span>
         <span class="tag">${spec.count} ${spec.count === 1 ? "item" : "items"}</span>`;
    return `<div class="type-card own" data-edit="${esc(spec.id)}" data-builtin="${builtIn ? "1" : ""}">
        <span class="tc-ic">${ICON[spec.icon] || ICON.layers}</span>
        <div class="tc-txt">
          <h3>${esc(spec.plural)}</h3>
          <small>${esc(spec.sub || "")}</small>
          ${(spec.subtypes || []).length ? `<div class="tc-subs">${spec.subtypes.map((s) =>
            `<span class="tag">${ICON[s.icon] || ""}${esc(s.label)}</span>`).join("")}</div>` : ""}
        </div>
        <div class="tc-meta">${meta}</div>
      </div>`;
  }

  function listHtml() {
    const own = catalogue.custom;
    return `<div id="type-editor"></div>
      <div class="panel" style="margin-bottom:16px">
        <div class="panel-head"><h2>Eigen types</h2>
          <span class="sub">Van jou, en bij elke klant beschikbaar</span></div>
        ${own.length
          ? own.map((t) => typeCard(t, false)).join("")
          : `<div class="muted" style="padding:14px 18px">Nog geen eigen types. Maak er een
               voor wat jij vastlegt en wat hier nog niet staat — een Microsoft 365-tenant,
               een back-upopdracht, een certificaat.</div>`}
      </div>
      <div class="panel">
        <div class="panel-head"><h2>Ingebouwd</h2>
          <span class="sub">Klik er een aan om de indeling aan te passen of velden toe te voegen</span></div>
        ${catalogue.built_in.map((t) => typeCard(t, true)).join("")}
      </div>`;
  }

  // ---- the editor: the type itself ----
  function ownHead() {
    const making = !draft.id;
    return `<div class="panel form-block">
        <div class="panel-head"><h2>${making ? "Nieuw type" : `“${esc(draft.label)}” wijzigen`}</h2>
          <span class="sub">Bij elke klant beschikbaar zodra je opslaat</span></div>
        <div class="form-body">
          <div class="tf-grid">
            <div class="frow"><label>Naam (enkelvoud)</label>
              <input class="inp" id="t-label" value="${esc(draft.label)}"
                     placeholder="Microsoft 365-tenant" /></div>
            <div class="frow"><label>Naam (meervoud)</label>
              <input class="inp" id="t-plural" value="${esc(draft.plural)}"
                     placeholder="Microsoft 365-tenants" />
              <div class="hint">Zo heet de sectie bij een klant.</div></div>
          </div>
          <div class="frow"><label>Waar het over gaat</label>
            <input class="inp" id="t-sub" value="${esc(draft.sub)}"
                   placeholder="Eén zin, onder de titel" /></div>
          <div class="frow"><label>Pictogram</label>
            <div class="icon-pick" id="t-icon">${ICONS.map((name) =>
              `<button type="button" class="ip${name === draft.icon ? " on" : ""}"
                 data-icon="${name}" title="${name}">${ICON[name]}</button>`).join("")}</div></div>
          <div class="toggle-line">
            <label class="boolrow"><input type="checkbox" id="t-adapters"
              ${draft.adapters ? "checked" : ""} />
              <span>Heeft netwerkadapters, net als een computer</span></label>
          </div>
        </div>
      </div>`;
  }

  function builtInHead() {
    return `<div class="panel form-block">
        <div class="panel-head"><span class="lay-type-ic">${ICON[draft.icon] || ICON.layers}</span>
          <h2>${esc(draft.plural)} indelen</h2>
          <span class="sub">Ingebouwd type — geldt bij elke klant</span></div>
        <div class="form-body">
          <div class="callout info" style="margin-bottom:14px"><div class="ic">${ICON.info}</div>
            <div class="cd">Velden met <span class="tag">ingebouwd</span> komen uit LeuffenDoc zelf.
              Die kun je verplaatsen, hernoemen, anders uitleggen en verbergen, maar niet weghalen of
              van soort veranderen: de koppeling met de RMM, de switchpoorten en de kluis rekenen erop.
              Wat je verbergt houdt zijn waarde. Eigen velden en blokken voeg je gewoon toe.</div></div>
        </div>
      </div>`;
  }

  // ---- the editor: the blocks ----
  function fieldEditorHtml(f, gi) {
    const refs = Object.entries(catalogue.byKind).filter(([id]) => id !== draft.id);
    const lockedChoices = f.base && f.type === "select" && alwaysShown(f);
    const extra = f.type === "select"
      ? (lockedChoices
          ? `<div class="frow"><label>Keuzes</label><div class="rmm-val">${esc((f.options || []).join(", "))}</div>
               <div class="hint">Vast: hierop zijn de configuratietypes in de zijbalk gebouwd.</div></div>`
          : `<div class="frow"><label>Keuzes</label>
               <input class="inp" data-f="options" value="${esc((f.options || []).join(", "))}"
                      placeholder="Komma's ertussen" /></div>`)
      : f.type === "ref" && !f.base
        ? `<div class="frow"><label>Verwijst naar</label>
             <select class="inp" data-f="ref">
               <option value="configuratie"${f.ref === "configuratie" ? " selected" : ""}>Configuratie (computer, netwerk of printer)</option>
               ${refs.map(([id, spec]) =>
                 `<option value="${id}"${id === f.ref ? " selected" : ""}>${esc(spec.label)}</option>`).join("")}
             </select></div>`
        : f.type === "list" && !f.base
          ? `<div class="frow"><label>Voorgestelde labels</label>
               <input class="inp" data-f="labels" value="${esc((f.labels || []).join(", "))}"
                      placeholder="Werk, Mobiel" /></div>`
          : "";
    return `<div class="lay-edit">
        <div class="tf-grid">
          <div class="frow"><label>Naam van het veld</label>
            <input class="inp" data-f="label" value="${esc(f.label || "")}" placeholder="bijv. Tenant-id" /></div>
          <div class="frow"><label>Soort</label>
            ${f.base
              ? `<div class="rmm-val">${esc(TYPE_NAMES[f.type] || f.type)}${f.rmm ? " — uit de RMM" : ""}</div>`
              : `<select class="inp" data-f="type">${Object.entries(TYPE_NAMES).map(([id, name]) =>
                  `<option value="${id}"${id === f.type ? " selected" : ""}>${esc(name)}</option>`).join("")}</select>`}</div>
          ${extra}
          <div class="frow"><label>Uitleg eronder</label>
            <input class="inp" data-f="hint" value="${esc(f.hint || "")}" placeholder="Optioneel" /></div>
        </div>
        <div class="tf-flags">
          ${f.type !== "secret" && !f.hidden ? `<label class="boolrow"><input type="checkbox" data-f="column"
              ${draft.columns.has(f._id) ? "checked" : ""} /> <span>In de lijst tonen</span></label>` : ""}
          ${f.type === "secret" ? `<span class="hint" style="margin:0">Komt nooit in een lijst,
              en wordt alleen met Tonen of Kopiëren opgevraagd.</span>` : ""}
          ${!f.base && f.type === "date" ? `<label class="boolrow"><input type="checkbox" data-f="expiry"
              ${f.expiry ? "checked" : ""} /> <span>Waarschuw als de datum nadert</span></label>` : ""}
          ${!f.base && f.type === "textarea" ? `<label class="boolrow"><input type="checkbox" data-f="long"
              ${f.long ? "checked" : ""} /> <span>Hele pagina breed</span></label>` : ""}
          <label class="boolrow lay-move">Blok
            <select class="inp" data-move-to>${draft.groups.map((g, i) =>
              `<option value="${i}"${i === gi ? " selected" : ""}>${esc(g.label || "Blok")}</option>`).join("")}</select></label>
        </div>
      </div>`;
  }

  function fieldHtml(f, gi, fi) {
    const open = openField === f._id;
    return `<div class="lay-field${f.hidden ? " is-hidden" : ""}${open ? " open" : ""}"
          data-gi="${gi}" data-fi="${fi}" data-id="${f._id}" data-key="${esc(f.key || "")}">
        <div class="lay-row">
          <span class="lay-grip" data-grip="field" title="Sleep om te verplaatsen">${ICON.menu}</span>
          <span class="lay-name">${esc(f.label || "Nieuw veld")}</span>
          <span class="lay-type">${esc(TYPE_NAMES[f.type] || f.type)}</span>
          ${f.rmm ? `<span class="tag">RMM</span>` : ""}
          ${f.base ? `<span class="tag">ingebouwd</span>` : ""}
          ${draft.columns.has(f._id) && !f.hidden ? `<span class="tag">in lijst</span>` : ""}
          ${f.hidden ? `<span class="tag warn">verborgen</span>` : ""}
          <span class="lay-acts">
            <button type="button" class="lay-ib" data-step="-1" title="Omhoog">${ICON.arrowUp}</button>
            <button type="button" class="lay-ib" data-step="1" title="Omlaag">${ICON.arrowDown}</button>
            ${f.base && !alwaysShown(f) ? `<button type="button" class="lay-ib" data-hide
                title="${f.hidden ? "Weer tonen" : "Verbergen"}">${f.hidden ? ICON.eye : ICON.eyeOff}</button>` : ""}
            <button type="button" class="lay-ib${open ? " on" : ""}" data-open title="Details">${ICON.pencil}</button>
            ${f.base ? "" : `<button type="button" class="lay-ib" data-drop-field title="Veld weghalen">${ICON.trash}</button>`}
          </span>
        </div>
        ${open ? fieldEditorHtml(f, gi) : ""}
      </div>`;
  }

  function blockHtml(g, gi) {
    const last = draft.groups.length - 1;
    return `<div class="lay-block${g.width === "half" ? " half" : ""}" data-gi="${gi}">
        <div class="lay-head">
          <span class="lay-grip" data-grip="block" title="Sleep het blok om de volgorde te bepalen">${ICON.menu}</span>
          <input class="inp lay-title" data-g="label" value="${esc(g.label)}" placeholder="Naam van het blok" />
          <span class="seg" role="group" aria-label="Breedte">
            <button type="button" class="seg-b${g.width !== "half" ? " on" : ""}" data-width="full"
                    title="Over de hele breedte van de pagina">Breed</button>
            <button type="button" class="seg-b${g.width === "half" ? " on" : ""}" data-width="half"
                    title="Halve breedte: twee halve blokken staan naast elkaar">Half</button>
          </span>
          <button type="button" class="lay-ib" data-move-block="-1" title="Eerder"${gi === 0 ? " disabled" : ""}>${ICON.arrowUp}</button>
          <button type="button" class="lay-ib" data-move-block="1" title="Later"${gi === last ? " disabled" : ""}>${ICON.arrowDown}</button>
          <button type="button" class="lay-ib" data-drop-block
            ${g.fields.length ? `disabled title="Haal eerst de velden eruit"` : `title="Blok weghalen"`}>${ICON.trash}</button>
        </div>
        <div class="lay-fields" data-gi="${gi}">
          ${g.fields.map((f, fi) => fieldHtml(f, gi, fi)).join("")
            || `<div class="lay-empty">Sleep hier een veld naartoe, of voeg er een toe</div>`}
        </div>
        <button type="button" class="lay-add" data-add-field="${gi}">${ICON.plus} Veld toevoegen</button>
      </div>`;
  }

  function editorHtml() {
    const note = pending ? `<div class="callout warn" style="margin-bottom:14px">
        <div class="ic">${ICON.alert}</div><div style="flex:1">
        <div class="ct">${esc(pending.message)}</div>
        <div class="cd">Wat in die velden staat is daarna niet meer te zien.
          <button class="btn sm" id="t-overrule" style="margin-left:10px">${esc(pending.label)}</button>
          <button class="btn ghost sm" id="t-keep">Toch niet</button></div></div></div>` : "";
    return (draft.builtIn ? builtInHead() : ownHead())
      + `<div class="panel form-block">
          <div class="panel-head"><h2>Indeling</h2>
            <span class="sub">Sleep velden binnen een blok of naar een ander blok, en blokken in de volgorde
              van de pagina. Half: twee halve blokken staan naast elkaar.</span></div>
          <div class="form-body">
            <div class="lay-grid">${draft.groups.map(blockHtml).join("")}</div>
            <div class="lay-foot"><button type="button" class="btn ghost sm" id="lay-add-block">${ICON.plus} Blok toevoegen</button></div>
          </div>
        </div>`
      + note
      + `<div class="form-foot">
          ${draft.builtIn && draft.customized
            ? `<button class="btn ghost" id="t-reset">${ICON.refresh} Standaard herstellen</button>` : ""}
          ${!draft.builtIn && draft.id ? `<button class="btn ghost" id="t-delete">${ICON.trash} Type verwijderen</button>` : ""}
          <div style="flex:1"></div>
          <button class="btn ghost" id="t-cancel">Annuleren</button>
          <button class="btn" id="t-save">${ICON.save} Opslaan</button>
        </div>`;
  }

  /* Read the form back into the draft before anything is re-rendered, so
     half-typed work is not thrown away by moving a field or changing its sort. */
  function collect(host) {
    if (!draft) return;
    if (!draft.builtIn) {
      const val = (id) => (host.querySelector(id) || {}).value;
      if (val("#t-label") !== undefined) draft.label = val("#t-label").trim();
      if (val("#t-plural") !== undefined) draft.plural = val("#t-plural").trim();
      if (val("#t-sub") !== undefined) draft.sub = val("#t-sub").trim();
      const adapters = host.querySelector("#t-adapters");
      if (adapters) draft.adapters = adapters.checked;
    }
    host.querySelectorAll(".lay-block").forEach((blk) => {
      const g = draft.groups[Number(blk.dataset.gi)];
      const title = blk.querySelector('[data-g="label"]');
      if (g && title) g.label = title.value;
    });
    const row = host.querySelector(".lay-field.open");
    if (!row) return;
    const f = draft.groups[Number(row.dataset.gi)].fields[Number(row.dataset.fi)];
    const get = (key) => {
      const el = row.querySelector(`[data-f="${key}"]`);
      return el ? (el.type === "checkbox" ? el.checked : el.value) : undefined;
    };
    const list = (key) => (get(key) || "").split(",").map((o) => o.trim()).filter(Boolean);
    if (get("label") !== undefined) f.label = get("label").trim();
    if (get("hint") !== undefined) f.hint = get("hint").trim();
    if (get("type") !== undefined) f.type = get("type");
    if (get("options") !== undefined) f.options = list("options");
    if (get("labels") !== undefined) f.labels = list("labels");
    if (get("ref") !== undefined) f.ref = get("ref");
    if (get("expiry") !== undefined) f.expiry = get("expiry");
    if (get("long") !== undefined) f.long = get("long");
    if (get("column") !== undefined) {
      if (get("column")) draft.columns.add(f._id); else draft.columns.delete(f._id);
    }
  }

  // ---- moving things ----
  function moveField(from, gi, index) {
    const source = draft.groups[from.gi].fields;
    const [field] = source.splice(from.fi, 1);
    if (from.gi === gi && from.fi < index) index -= 1;
    draft.groups[gi].fields.splice(index, 0, field);
  }

  function moveBlock(from, to) {
    const [block] = draft.groups.splice(from, 1);
    if (from < to) to -= 1;
    draft.groups.splice(to, 0, block);
  }

  // ---- what goes to the server ----
  function payloadGroups() {
    return draft.groups.map((g) => ({
      key: g.key || "", label: (g.label || "").trim() || "Blok", width: g.width,
      fields: g.fields.filter((f) => f.base || (f.label || "").trim()).map((f) => {
        const out = { key: f.key || "", label: (f.label || "").trim(), type: f.type, hint: f.hint || "" };
        for (const k of ["options", "labels", "ref", "icon"]) if (f[k] !== undefined) out[k] = f[k];
        if (f.expiry) out.expiry = true;
        if (f.long) out.long = true;
        if (f.hidden) out.hidden = true;
        return out;
      }),
    }));
  }

  function payloadColumns() {
    const out = [];
    for (const g of draft.groups) {
      for (const f of g.fields) {
        if (draft.columns.has(f._id) && !f.hidden && f.type !== "secret" && (f.key || f.label)) {
          out.push(f.key || f.label.trim());
        }
      }
    }
    return out;
  }

  async function view(host) {
    await load();
    catalogue.byKind = await kinds(true);

    const paint = () => {
      host.innerHTML = listHtml();
      const editor = host.querySelector("#type-editor");
      if (draft) {
        editor.innerHTML = editorHtml();
        wireEditor(editor);
      }
      host.querySelectorAll("[data-edit]").forEach((card) => {
        card.onclick = () => {
          const builtIn = !!card.dataset.builtin;
          const spec = (builtIn ? catalogue.built_in : catalogue.custom).find((t) => t.id === card.dataset.edit);
          draft = fromSpec(spec, builtIn);
          openField = null;
          pending = null;
          paint();
          host.querySelector("#type-editor").scrollIntoView({ behavior: "smooth", block: "start" });
        };
      });
    };

    function wireEditor(editor) {
      const redraw = () => { collect(editor); paint(); };
      editor.querySelectorAll("[data-icon]").forEach((b) => {
        b.onclick = () => { collect(editor); draft.icon = b.dataset.icon; paint(); };
      });
      editor.querySelectorAll('[data-f="type"]').forEach((sel) => { sel.onchange = redraw; });
      editor.querySelectorAll('[data-f="label"]').forEach((input) => {
        // The row's own name follows as you type, so it is clear which field is open.
        input.oninput = () => {
          const name = input.closest(".lay-field").querySelector(".lay-name");
          name.textContent = input.value || "Nieuw veld";
        };
      });
      editor.querySelectorAll(".lay-block").forEach((blk) => {
        const gi = Number(blk.dataset.gi);
        blk.querySelectorAll("[data-width]").forEach((b) => {
          b.onclick = () => { collect(editor); draft.groups[gi].width = b.dataset.width; paint(); };
        });
        blk.querySelectorAll("[data-move-block]").forEach((b) => {
          b.onclick = () => {
            collect(editor);
            const to = gi + Number(b.dataset.moveBlock);
            if (to < 0 || to >= draft.groups.length) return;
            moveBlock(gi, to > gi ? to + 1 : to);
            paint();
          };
        });
        const drop = blk.querySelector("[data-drop-block]");
        drop.onclick = () => {
          collect(editor);
          if (draft.groups[gi].fields.length || draft.groups.length === 1) return;
          draft.groups.splice(gi, 1);
          paint();
        };
        blk.querySelector("[data-add-field]").onclick = () => {
          collect(editor);
          const field = newField();
          draft.groups[gi].fields.push(field);
          openField = field._id;
          paint();
          const input = editor.ownerDocument.querySelector(`.lay-field[data-id="${field._id}"] [data-f="label"]`);
          if (input) input.focus();
        };
      });
      editor.querySelectorAll(".lay-field").forEach((row) => {
        const gi = Number(row.dataset.gi), fi = Number(row.dataset.fi);
        const f = draft.groups[gi].fields[fi];
        const on = (sel, fn) => { const el = row.querySelector(sel); if (el) el.onclick = fn; };
        on("[data-open]", () => { collect(editor); openField = openField === f._id ? null : f._id; paint(); });
        on("[data-hide]", () => {
          collect(editor);
          f.hidden = !f.hidden;
          if (f.hidden) draft.columns.delete(f._id);
          paint();
        });
        on("[data-drop-field]", () => {
          collect(editor);
          draft.groups[gi].fields.splice(fi, 1);
          draft.columns.delete(f._id);
          paint();
        });
        row.querySelectorAll("[data-step]").forEach((b) => {
          b.onclick = () => {
            collect(editor);
            const step = Number(b.dataset.step);
            const fields = draft.groups[gi].fields;
            if (fi + step >= 0 && fi + step < fields.length) {
              moveField({ gi, fi }, gi, step > 0 ? fi + 2 : fi - 1);
            } else if (gi + step >= 0 && gi + step < draft.groups.length) {
              // Past the end of its block: into the next (or previous) one.
              moveField({ gi, fi }, gi + step, step > 0 ? 0 : draft.groups[gi + step].fields.length);
            }
            paint();
          };
        });
        const to = row.querySelector("[data-move-to]");
        if (to) to.onchange = () => {
          collect(editor);
          const target = Number(to.value);
          moveField({ gi, fi }, target, draft.groups[target].fields.length);
          paint();
        };
      });
      editor.querySelector("#lay-add-block").onclick = () => {
        collect(editor);
        const field = newField();
        draft.groups.push({ key: "", label: "Nieuw blok", width: "full", fields: [field] });
        openField = field._id;
        paint();
        const blocks = editor.ownerDocument.querySelectorAll(".lay-block");
        const title = blocks[blocks.length - 1].querySelector('[data-g="label"]');
        title.focus();
        title.select();
      };
      wireDrag(editor, paint);
      editor.querySelector("#t-cancel").onclick = () => { draft = null; pending = null; paint(); };
      editor.querySelector("#t-save").onclick = () => save(editor, false);
      const reset = editor.querySelector("#t-reset");
      if (reset) reset.onclick = () => resetLayout(false);
      const del = editor.querySelector("#t-delete");
      if (del) del.onclick = () => remove();
      const overrule = editor.querySelector("#t-overrule");
      if (overrule) overrule.onclick = () => { const retry = pending.retry; pending = null; retry(); };
      const keep = editor.querySelector("#t-keep");
      if (keep) keep.onclick = () => { pending = null; paint(); };
    }

    /* Dragging. A row or a block is only draggable while its grip is held, so
       selecting text in a field's name -- or in a block's title -- still works. */
    function wireDrag(editor, repaint) {
      let dragging = null;               // { type: "field", gi, fi } | { type: "block", gi }
      const clearMarks = () => editor.querySelectorAll(".drop-before, .drop-after, .drop-into")
        .forEach((el) => el.classList.remove("drop-before", "drop-after", "drop-into"));
      const mark = (el, cls) => { clearMarks(); el.classList.add(cls); };
      const isBefore = (el, ev) => {
        const r = el.getBoundingClientRect();
        // Half blocks sit side by side: left of the middle is before.
        return el.classList.contains("lay-block") && el.classList.contains("half")
          ? ev.clientX < r.left + r.width / 2
          : ev.clientY < r.top + r.height / 2;
      };

      editor.querySelectorAll("[data-grip]").forEach((grip) => {
        const holder = grip.closest(grip.dataset.grip === "field" ? ".lay-field" : ".lay-block");
        grip.addEventListener("mousedown", () => { holder.draggable = true; });
        grip.addEventListener("mouseup", () => { holder.draggable = false; });
      });
      editor.querySelectorAll(".lay-field, .lay-block").forEach((el) => {
        el.addEventListener("dragstart", (ev) => {
          if (!el.draggable) return;
          ev.stopPropagation();
          collect(editor);
          dragging = el.classList.contains("lay-field")
            ? { type: "field", gi: Number(el.dataset.gi), fi: Number(el.dataset.fi) }
            : { type: "block", gi: Number(el.dataset.gi) };
          ev.dataTransfer.effectAllowed = "move";
          ev.dataTransfer.setData("text/plain", dragging.type);    // Firefox wants some data
          el.classList.add("dragging");
        });
        el.addEventListener("dragend", () => {
          el.draggable = false;
          el.classList.remove("dragging");
          clearMarks();
          dragging = null;
        });
      });
      editor.querySelectorAll(".lay-field").forEach((row) => {
        row.addEventListener("dragover", (ev) => {
          if (!dragging || dragging.type !== "field") return;
          ev.preventDefault();
          ev.stopPropagation();
          mark(row, isBefore(row, ev) ? "drop-before" : "drop-after");
        });
        row.addEventListener("drop", (ev) => {
          if (!dragging || dragging.type !== "field") return;
          ev.preventDefault();
          ev.stopPropagation();
          const index = Number(row.dataset.fi) + (isBefore(row, ev) ? 0 : 1);
          moveField(dragging, Number(row.dataset.gi), index);
          dragging = null;
          repaint();
        });
      });
      editor.querySelectorAll(".lay-fields").forEach((zone) => {
        zone.addEventListener("dragover", (ev) => {
          if (!dragging || dragging.type !== "field") return;
          ev.preventDefault();
          mark(zone, "drop-into");
        });
        zone.addEventListener("drop", (ev) => {
          if (!dragging || dragging.type !== "field") return;
          ev.preventDefault();
          const gi = Number(zone.dataset.gi);
          moveField(dragging, gi, draft.groups[gi].fields.length);
          dragging = null;
          repaint();
        });
      });
      editor.querySelectorAll(".lay-block").forEach((blk) => {
        blk.addEventListener("dragover", (ev) => {
          if (!dragging || dragging.type !== "block") return;
          ev.preventDefault();
          mark(blk, isBefore(blk, ev) ? "drop-before" : "drop-after");
        });
        blk.addEventListener("drop", (ev) => {
          if (!dragging || dragging.type !== "block") return;
          ev.preventDefault();
          const to = Number(blk.dataset.gi) + (isBefore(blk, ev) ? 0 : 1);
          moveBlock(dragging.gi, to);
          dragging = null;
          repaint();
        });
      });
    }

    async function after(message) {
      draft = null;
      pending = null;
      openField = null;
      toast(message);
      await ctx.refresh();
      await load();
      catalogue.byKind = await kinds(true);
      paint();
    }

    // A change that would throw filled-in values away is said first, and only
    // done when somebody presses the button that says so.
    function refused(e, label, retry) {
      if (!/gaan verloren/.test(e.message)) return false;
      pending = { message: e.message, label, retry };
      paint();
      return true;
    }

    async function save(editor, confirmed) {
      if (editor) collect(editor);
      const groups = payloadGroups();
      const columns = payloadColumns();
      const btn = document.querySelector("#t-save");
      if (btn) btn.disabled = true;
      try {
        if (draft.builtIn) {
          await api(`/api/types/${draft.id}/layout`, {
            method: "PUT", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ groups, columns, confirm_removals: confirmed }),
          });
        } else {
          const body = { label: draft.label, plural: draft.plural, icon: draft.icon, sub: draft.sub,
                         adapters: draft.adapters, columns, groups, confirm_removals: confirmed };
          await api(draft.id ? `/api/types/${draft.id}` : "/api/types", {
            method: draft.id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
        }
        await after(draft.builtIn ? "Indeling opgeslagen" : "Type opgeslagen");
      } catch (e) {
        if (!refused(e, "Toch opslaan", () => save(null, true))) toast(e.message);
        const again = document.querySelector("#t-save");
        if (again) again.disabled = false;
      }
    }

    async function resetLayout(confirmed) {
      try {
        await api(`/api/types/${draft.id}/layout${confirmed ? "?confirm=true" : ""}`, { method: "DELETE" });
        await after("Standaardindeling hersteld");
      } catch (e) {
        if (!refused(e, "Toch herstellen", () => resetLayout(true))) toast(e.message);
      }
    }

    async function remove() {
      try {
        await api(`/api/types/${draft.id}`, { method: "DELETE" });
        await after("Type verwijderd");
      } catch (e) { toast(e.message); }
    }

    paint();
  }

  const isEditing = () => draft !== null;
  const start = () => { draft = blank(); openField = draft.groups[0].fields[0]._id; pending = null; };

  return { view, isEditing, start };
};
