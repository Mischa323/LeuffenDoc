/* Types you define yourself.

   The built-in kinds cover equipment and a customer's own parts. Everything
   else an MSP writes down — a Microsoft 365 tenant, a backup job, a
   certificate — differs per shop, so it is defined here instead of guessed at.

   A type is a name and a list of fields. Nothing else in the interface knows
   about this page: the things made from a type are rendered by the same code
   as everything else, which is the whole reason it works. */
window.DocTypes = function (ctx) {
  "use strict";

  const { api, esc, toast, kinds } = ctx;

  // Which icon to put on it. A short list beats a search box of four hundred.
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
  let draft = null;           // the type being written, or null

  const blank = () => ({
    id: null, label: "", plural: "", icon: "layers", sub: "", adapters: false,
    columns: [], fields: [{ key: "", label: "", type: "text", options: [], hint: "" }],
  });

  async function load() {
    catalogue = await api("/api/types");
    return catalogue;
  }

  // ---- the list ----
  function typeCard(spec, custom) {
    const count = custom ? spec.count : null;
    return `<div class="type-card${custom ? " own" : ""}" ${custom ? `data-edit="${esc(spec.id)}"` : ""}>
        <span class="tc-ic">${ICON[spec.icon] || ICON.layers}</span>
        <div class="tc-txt">
          <h3>${esc(spec.plural)}</h3>
          <small>${esc(spec.sub || "")}</small>
        </div>
        <div class="tc-meta">
          ${custom
            ? `<span class="muted">${spec.fields.length} velden</span>
               <span class="tag">${count} ${count === 1 ? "item" : "items"}</span>`
            : `<span class="tag">ingebouwd</span>`}
        </div>
      </div>`;
  }

  function listHtml() {
    const own = catalogue.custom;
    return `<div id="type-editor"></div>
      <div class="panel" style="margin-bottom:16px">
        <div class="panel-head"><h2>Eigen types</h2>
          <span class="sub">Van jou, en bij elke klant beschikbaar</span></div>
        ${own.length
          ? own.map((t) => typeCard(t, true)).join("")
          : `<div class="muted" style="padding:14px 18px">Nog geen eigen types. Maak er een
               voor wat jij vastlegt en wat hier nog niet staat — een Microsoft 365-tenant,
               een back-upopdracht, een certificaat.</div>`}
      </div>
      <div class="panel">
        <div class="panel-head"><h2>Ingebouwd</h2>
          <span class="sub">Deze staan er altijd, en zijn niet te wijzigen</span></div>
        ${catalogue.built_in.map((t) => typeCard(t, false)).join("")}
      </div>`;
  }

  // ---- the editor ----
  /* A field that is new has no key yet, so a column is remembered by its
     label until the server hands one back. Without this the tick disappears
     the moment anything redraws the form. */
  function isColumn(field) {
    return draft.columns.includes(field.key) || draft.columns.includes(field.label);
  }

  function fieldRow(field, index) {
    const type = field.type || "text";
    const refs = Object.entries(catalogue.byKind)
      .filter(([id]) => id !== draft.id);
    return `<div class="tf-row" data-index="${index}">
        <div class="tf-grid">
          <div class="frow"><label>Naam van het veld</label>
            <input class="inp" data-tf="label" value="${esc(field.label || "")}"
                   placeholder="bijv. Tenant-id" /></div>
          <div class="frow"><label>Soort</label>
            <select class="inp" data-tf="type">
              ${Object.entries(TYPE_NAMES).map(([id, name]) =>
                `<option value="${id}"${id === type ? " selected" : ""}>${esc(name)}</option>`).join("")}
            </select></div>
          <div class="frow tf-extra">
            ${type === "select"
              ? `<label>Keuzes</label>
                 <input class="inp" data-tf="options" value="${esc((field.options || []).join(", "))}"
                        placeholder="Komma's ertussen" />`
              : type === "ref"
                ? `<label>Verwijst naar</label>
                   <select class="inp" data-tf="ref">
                     ${refs.map(([id, spec]) =>
                       `<option value="${id}"${id === field.ref ? " selected" : ""}>${esc(spec.label)}</option>`).join("")}
                   </select>`
                : type === "list"
                  ? `<label>Voorgestelde labels</label>
                     <input class="inp" data-tf="labels" value="${esc((field.labels || []).join(", "))}"
                            placeholder="Werk, Mobiel" />`
                  : `<label>Uitleg eronder</label>
                     <input class="inp" data-tf="hint" value="${esc(field.hint || "")}"
                            placeholder="Optioneel" />`}
          </div>
        </div>
        <div class="tf-flags">
          ${type === "secret" ? `<span class="hint" style="margin:0">Komt nooit in een lijst,
            en wordt alleen met Tonen of Kopiëren opgevraagd.</span>`
            : `<label class="boolrow"><input type="checkbox" data-tf="column"
            ${isColumn(field) ? "checked" : ""} /> <span>In de lijst tonen</span></label>`}
          ${type === "date" ? `<label class="boolrow"><input type="checkbox" data-tf="expiry"
            ${field.expiry ? "checked" : ""} /> <span>Waarschuw als de datum nadert</span></label>` : ""}
          ${type === "textarea" ? `<label class="boolrow"><input type="checkbox" data-tf="long"
            ${field.long ? "checked" : ""} /> <span>Hele pagina breed</span></label>` : ""}
          <button type="button" class="btn ghost sm tf-up" title="Omhoog">${ICON.arrowUp}</button>
          <button type="button" class="btn ghost sm tf-drop">${ICON.trash}</button>
        </div>
      </div>`;
  }

  function editorHtml() {
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
      </div>

      <div class="panel form-block">
        <div class="panel-head"><h2>Velden</h2>
          <span class="sub">Wat er van elk ${esc(draft.label || "item")} wordt vastgelegd</span></div>
        <div class="form-body" id="t-fields">
          ${draft.fields.map((f, i) => fieldRow(f, i)).join("")}
        </div>
        <div class="cb-pad">
          <button type="button" class="btn ghost sm" id="t-add">${ICON.plus} Veld toevoegen</button>
        </div>
      </div>

      <div class="form-foot">
        ${draft.id ? `<button class="btn ghost" id="t-delete">${ICON.trash} Type verwijderen</button>` : ""}
        <div style="flex:1"></div>
        <button class="btn ghost" id="t-cancel">Annuleren</button>
        <button class="btn" id="t-save">${ICON.save} Opslaan</button>
      </div>`;
  }

  /* Read the form back into the draft before anything is re-rendered, so
     half-typed work is not thrown away by changing a field's type. */
  function collect(host) {
    if (!draft) return;
    const val = (id) => (host.querySelector(id) || {}).value || "";
    draft.label = val("#t-label").trim();
    draft.plural = val("#t-plural").trim();
    draft.sub = val("#t-sub").trim();
    const adapters = host.querySelector("#t-adapters");
    draft.adapters = adapters ? adapters.checked : false;
    draft.columns = [];
    draft.fields = [...host.querySelectorAll(".tf-row")].map((row, index) => {
      const get = (key) => {
        const el = row.querySelector(`[data-tf="${key}"]`);
        return el ? (el.type === "checkbox" ? el.checked : el.value) : undefined;
      };
      const old = draft.fields[Number(row.dataset.index)] || {};
      const label = (get("label") || "").trim();
      const field = {
        key: old.key || "", label, type: get("type") || "text",
        hint: (get("hint") || "").trim(),
      };
      if (field.type === "select") {
        field.options = (get("options") || "").split(",").map((o) => o.trim()).filter(Boolean);
      }
      if (field.type === "ref") field.ref = get("ref");
      if (field.type === "list") {
        field.labels = (get("labels") || "").split(",").map((o) => o.trim()).filter(Boolean);
      }
      if (get("expiry")) field.expiry = true;
      if (get("long")) field.long = true;
      if (get("column") && (field.key || label)) draft.columns.push(field.key || label);
      return field;
    });
    // Columns are named by key; a field that has none yet is matched by label
    // and fixed up by the server once it has one.
    draft.columns = draft.columns.filter(Boolean);
  }

  async function view(host) {
    await load();
    catalogue.byKind = await kinds(true);

    const paint = () => {
      host.innerHTML = listHtml();
      const editor = host.querySelector("#type-editor");
      if (draft) {
        editor.innerHTML = editorHtml();
        wireEditor(host, editor);
      }
      host.querySelectorAll("[data-edit]").forEach((card) => {
        card.onclick = () => {
          const found = catalogue.custom.find((t) => t.id === card.dataset.edit);
          draft = {
            id: found.id, label: found.label, plural: found.plural, icon: found.icon,
            sub: found.sub, adapters: found.adapters,
            columns: [...(found.columns || [])],
            fields: JSON.parse(JSON.stringify(found.fields)),
          };
          paint();
          editor.scrollIntoView({ behavior: "smooth", block: "start" });
        };
      });
      const add = host.querySelector("#new-type");
      if (add) add.onclick = () => { draft = blank(); paint(); };
    };

    function wireEditor(host_, editor) {
      editor.querySelectorAll("[data-icon]").forEach((b) => {
        b.onclick = () => { collect(editor); draft.icon = b.dataset.icon; paint(); };
      });
      editor.querySelectorAll('[data-tf="type"]').forEach((sel) => {
        sel.onchange = () => { collect(editor); paint(); };
      });
      editor.querySelectorAll(".tf-drop").forEach((b) => {
        b.onclick = () => {
          const index = Number(b.closest(".tf-row").dataset.index);
          collect(editor);
          draft.fields.splice(index, 1);
          if (!draft.fields.length) draft.fields = blank().fields;
          paint();
        };
      });
      editor.querySelectorAll(".tf-up").forEach((b) => {
        b.onclick = () => {
          const index = Number(b.closest(".tf-row").dataset.index);
          if (!index) return;
          collect(editor);
          const [moved] = draft.fields.splice(index, 1);
          draft.fields.splice(index - 1, 0, moved);
          paint();
        };
      });
      editor.querySelector("#t-add").onclick = () => {
        collect(editor);
        draft.fields.push({ key: "", label: "", type: "text", options: [], hint: "" });
        paint();
        const rows = editor.querySelectorAll(".tf-row");
        rows[rows.length - 1].querySelector('[data-tf="label"]').focus();
      };
      editor.querySelector("#t-cancel").onclick = () => { draft = null; paint(); };
      editor.querySelector("#t-save").onclick = () => save(editor);
      const del = editor.querySelector("#t-delete");
      if (del) del.onclick = () => remove();
    }

    async function save(editor) {
      collect(editor);
      const body = {
        label: draft.label, plural: draft.plural, icon: draft.icon, sub: draft.sub,
        adapters: draft.adapters, columns: draft.columns,
        fields: draft.fields.filter((f) => f.label),
      };
      const btn = editor.querySelector("#t-save");
      btn.disabled = true;
      try {
        if (draft.id) {
          await api(`/api/types/${draft.id}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
        } else {
          await api("/api/types", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
        }
        draft = null;
        toast("Type opgeslagen");
        await ctx.refresh();
        await load();
        catalogue.byKind = await kinds(true);
        paint();
      } catch (e) { toast(e.message); btn.disabled = false; }
    }

    async function remove() {
      try {
        await api(`/api/types/${draft.id}`, { method: "DELETE" });
        draft = null;
        toast("Type verwijderd");
        await ctx.refresh();
        await load();
        catalogue.byKind = await kinds(true);
        paint();
      } catch (e) { toast(e.message); }
    }

    paint();
  }

  const isEditing = () => draft !== null;
  const start = () => { draft = blank(); };

  return { view, isEditing, start };
};
