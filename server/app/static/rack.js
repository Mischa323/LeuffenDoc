/* Patch cabinets — the cabinet drawn as it stands.

   To scale: one unit (44.45 mm) is 40 px, and the 19-inch front 434 px wide,
   so a 1U switch is as flat and as wide as the real one and its 24 or 48
   ports fit where they are on the real one. U1 is at the bottom, as on the
   rails.

   Not everything is 19 inch. What is hangs in the rails; what is not -- the
   provider's modem, a desktop NAS, a UPS on its side -- stands on a shelf or
   on the bottom of the cabinet, drawn standing there. Whether a documented
   machine is 19 inch is said on its own page (or here, which writes it there);
   until then it is guessed from what it is.

   Everything is dragged in from the side and dragged around inside; a click
   picks something to change or take out. A switch shows which of its ports
   are taken, and by what, from its patch list. Every change is saved at once;
   the server checks it fits and overlaps nothing, and the drawing is redrawn
   from what it stored. */
window.DocRack = function (ctx) {
  "use strict";

  const { api, esc, toast, go } = ctx;
  const UPX = 40;                                   // one unit on screen
  const WIDTH = Math.round(UPX * 482.6 / 44.45);    // the 19-inch front: 434 px

  /* ---- fronts, as they look ---- */
  const ear = `<span class="rk-ear l"><i></i><i></i></span><span class="rk-ear r"><i></i><i></i></span>`;
  const nameTag = (text) => `<span class="rk-name">${esc(text)}</span>`;

  function portGrid(ports, rows, cls) {
    // Switches and patch panels number their ports in columns: 1 above 2, 3
    // above 4, ... -- so the top row holds the odd ones.
    const cols = Math.ceil(ports.length / rows);
    const cells = [];
    for (let c = 0; c < cols; c++) {
      for (let r = 0; r < rows; r++) {
        const p = ports[c * rows + r];
        if (!p) continue;
        cells.push(`<span class="rk-port${p.used ? " on" : ""}${cls ? ` ${cls}` : ""}"
          style="grid-column:${c + 1};grid-row:${r + 1}"
          title="Poort ${p.number}${p.who ? ` — ${esc(p.who)}` : p.label ? ` — ${esc(p.label)}` : " — vrij"}${p.vlan ? ` · VLAN ${esc(p.vlan)}` : ""}"></span>`);
      }
    }
    return `<span class="rk-ports" style="grid-template-columns:repeat(${cols}, 1fr);grid-template-rows:repeat(${rows}, 1fr)">${cells.join("")}</span>`;
  }

  function front(slot, dev, height, passive) {
    if (slot.kind === "item") {
      if (!dev) return `${ear}<span class="rk-plate rk-gone">${nameTag("Niet meer te zien")}</span>`;
      if (dev.hidden) return `${ear}<span class="rk-plate">${nameTag("Afgeschermd")}</span>`;
      if (dev.kind === "network" && dev.role === "Switch") {
        const ports = dev.ports && dev.ports.length ? dev.ports
          : Array.from({ length: 24 }, (_, i) => ({ number: i + 1 }));
        return `${ear}<span class="rk-body rk-sw">${nameTag(dev.name)}
            <span class="rk-leds"><i class="pwr"></i><i></i></span>${portGrid(ports, ports.length > 12 ? 2 : 1, "")}</span>`;
      }
      if (dev.kind === "network") {
        const ports = Array.from({ length: 8 }, (_, i) => ({ number: i + 1 }));
        return `${ear}<span class="rk-body rk-app">${nameTag(dev.name)}<span class="rk-role">${esc(dev.role || "Netwerk")}</span>
            <span class="rk-leds"><i class="pwr"></i><i></i><i></i></span>${portGrid(ports, 1, "")}</span>`;
      }
      if (dev.kind === "computer") {
        return `${ear}<span class="rk-body rk-srv">${nameTag(dev.name)}<span class="rk-role">${esc(dev.role || "")}</span>
            <span class="rk-bays h${Math.min(height, 4)}">${"<i></i>".repeat(height >= 2 ? 12 : 8)}</span>
            <span class="rk-leds"><i class="pwr"></i></span></span>`;
      }
      return `${ear}<span class="rk-body rk-gen">${nameTag(dev.name)}</span>`;
    }
    const label = slot.label || (passive[slot.kind] || {}).label || slot.kind;
    switch (slot.kind) {
      case "patch": {
        const ports = Array.from({ length: slot.ports || 24 }, (_, i) => ({ number: i + 1 }));
        return `${ear}<span class="rk-body rk-patch">${nameTag(label)}${portGrid(ports, ports.length > 24 ? 2 : 1, "jack")}</span>`;
      }
      case "blank": return `${ear}<span class="rk-plate rk-blank">${slot.label ? nameTag(slot.label) : ""}</span>`;
      case "cable": return `${ear}<span class="rk-plate rk-cable">${"<i></i>".repeat(5)}${slot.label ? nameTag(slot.label) : ""}</span>`;
      case "pdu": return `${ear}<span class="rk-body rk-pdu">${nameTag(label)}<span class="rk-sockets">${"<i></i>".repeat(8)}</span><span class="rk-leds"><i class="pwr"></i></span></span>`;
      case "ups": return `${ear}<span class="rk-body rk-ups">${nameTag(label)}<span class="rk-lcd">UPS</span><span class="rk-leds"><i class="pwr"></i><i></i><i></i></span></span>`;
      default: return `${ear}<span class="rk-plate">${nameTag(label)}</span>`;
    }
  }

  /* What stands on a shelf or the bottom: a box seen from the front, as tall
     and wide as such a thing roughly is next to the units around it. */
  function standingLook(entry, dev, standing) {
    if (entry.item) {
      if (!dev) return { cls: "rk-gone", w: 90, h: .5, label: "Niet meer te zien" };
      if (dev.hidden) return { cls: "", w: 90, h: .5, label: "Afgeschermd" };
      const role = dev.role || "";
      if (dev.kind === "network") return role === "Switch" || role === "Router" || role === "Firewall"
        ? { cls: "rk-st-net", w: 150, h: .35, label: dev.name, ports: 8 }
        : { cls: "rk-st-modem", w: 92, h: .55, label: dev.name, leds: 4 };
      if (dev.kind === "computer") return role === "NAS" ? { cls: "rk-st-nas", w: 78, h: .82, label: dev.name, bays: 4 }
        : role === "Server" ? { cls: "rk-st-tower", w: 74, h: .95, label: dev.name }
        : { cls: "rk-st-tower", w: 66, h: .9, label: dev.name };
      if (dev.kind === "printer") return { cls: "rk-st-printer", w: 140, h: .6, label: dev.name };
      return { cls: "rk-st-box", w: 100, h: .55, label: dev.name };
    }
    const label = entry.label || (standing[entry.kind] || {}).label || "Los";
    return entry.kind === "ups_box" ? { cls: "rk-st-ups", w: 84, h: .85, label, lcd: true }
      : { cls: "rk-st-box", w: 100, h: .55, label };
  }

  function thingHtml(entry, slot, dev, standing, selected) {
    const look = standingLook(entry, dev, standing);
    const room = slot.height * UPX - 14;           // above the plank, under the unit above
    const h = Math.max(18, Math.round(room * look.h));
    return `<div class="rk-thing ${look.cls}${selected ? " sel" : ""}" data-thing="${esc(entry.id)}" data-holder="${esc(slot.id)}"
        style="width:${look.w}px;height:${h}px" title="${esc(look.label)}">
        <span class="rk-thing-name">${esc(look.label)}</span>
        ${look.lcd ? `<span class="rk-lcd">UPS</span>` : ""}
        ${look.leds ? `<span class="rk-leds">${'<i class="pwr"></i>' + "<i></i>".repeat(look.leds - 1)}</span>` : ""}
        ${look.bays ? `<span class="rk-st-bays">${"<i></i>".repeat(look.bays)}</span>` : ""}
        ${look.ports ? `<span class="rk-st-ports">${"<i></i>".repeat(look.ports)}</span>` : ""}
      </div>`;
  }

  function holderHtml(slot, devices, standing, passive, selectedThing) {
    const label = slot.label || (passive[slot.kind] || {}).label;
    const things = (slot.items || []).map((t) =>
      thingHtml(t, slot, t.item ? devices[t.item] : null, standing, selectedThing === t.id)).join("");
    return `${slot.kind === "floor" ? "" : ear}<span class="rk-holder ${slot.kind === "floor" ? "rk-floor" : "rk-shelf"}">
        <span class="rk-things">${things || `<span class="rk-holder-empty">${esc(label)} — sleep hier iets op</span>`}</span>
        <span class="rk-plank">${things ? `<span class="rk-plank-name">${esc(label)}</span>` : ""}</span>
      </span>`;
  }

  async function view(host, { org, item, mayEdit, kinds }) {
    if (!host) return;
    let data;
    try { data = await api(`/api/items/${item.id}/rack`); } catch (e) {
      host.innerHTML = `<div class="callout warn"><div class="ic">${ICON.alert}</div><div class="cd">${esc(e.message)}</div></div>`;
      return;
    }
    let selected = null;        // { slot } or { holder, thing }
    let filter = "";

    const holds = (slot) => !!(data.passive[slot.kind] || {}).holds;
    const nameOf = (slot) => (slot.kind === "item"
      ? ((data.devices[slot.item] || {}).name || "Apparaat")
      : (slot.label || (data.passive[slot.kind] || {}).label || slot.kind));
    const thingName = (t) => (t.item ? ((data.devices[t.item] || {}).name || "Apparaat")
      : (t.label || (data.standing[t.kind] || {}).label || "Los"));
    const range = (slot) => (slot.height === 1 ? `U${slot.at}` : `U${slot.at}–U${slot.at + slot.height - 1}`);
    const fits = (at, height, ignore) => at >= 1 && at + height - 1 <= data.units
      && data.slots.every((s) => s.id === ignore || s.at + s.height - 1 < at || s.at > at + height - 1);
    const formTag = (c) => (c.rack ? `${c.units}U` : "los");

    async function save(slots, message) {
      try {
        data = await api(`/api/items/${item.id}/rack`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slots }),
        });
        if (message) toast(message);
      } catch (e) { toast(e.message); }
      paint();
    }

    // Whether something is 19 inch belongs to the thing: written on its page.
    async function setForm(itemId, form, units) {
      try {
        await api(`/api/items/${itemId}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ fields: { rackmount: form, ...(units ? { rack_units: String(units) } : {}) } }),
        });
        data = await api(`/api/items/${item.id}/rack`);
        toast(form === data.forms[1] ? "Opgeslagen: staat los — zet het op een plank of de bodem"
                                     : "Opgeslagen: 19 inch");
      } catch (e) { toast(e.message); }
      paint();
    }

    function formControl(dev) {
      if (!dev || dev.hidden) return "";
      return `<div class="frow"><label>Formaat${dev.guessed ? ` <span class="muted">(geschat)</span>` : ""}</label>
        <select class="inp" id="rk-form">${data.forms.map((f, i) =>
          `<option value="${esc(f)}"${(i === 0) === dev.rack ? " selected" : ""}>${esc(f)}</option>`).join("")}</select>
        <div class="hint">Wordt bij ${esc(dev.name)} zelf bewaard.</div></div>`;
    }

    function inspector() {
      if (selected && selected.thing) {
        const holder = data.slots.find((s) => s.id === selected.holder);
        const thing = holder && (holder.items || []).find((t) => t.id === selected.thing);
        if (thing) {
          const dev = thing.item ? data.devices[thing.item] : null;
          return `<div class="rk-insp">
              <div class="rk-insp-head"><b>${esc(thingName(thing))}</b>
                <span class="muted">op ${esc(nameOf(holder).toLowerCase())}, ${range(holder)}</span></div>
              ${thing.item ? formControl(dev) : `<div class="frow"><label>Naam</label>
                <input class="inp" id="rk-thing-label" value="${esc(thing.label || "")}"
                       placeholder="${esc((data.standing[thing.kind] || {}).label || "")}" /></div>`}
              <div class="rk-insp-acts">
                ${dev && !dev.hidden ? `<button class="btn ghost sm" id="rk-open">${ICON.external} Openen</button>` : ""}
                <button class="btn ghost sm" id="rk-thing-remove">${ICON.trash} Eraf halen</button>
              </div></div>`;
        }
      }
      const slot = selected && data.slots.find((s) => s.id === selected.slot);
      if (!slot) return `<div class="rk-help">Klik op iets in de kast om de hoogte of de naam te wijzigen,
          of om het eruit te halen. Wat geen 19 inch is, zet je op een plank of de bodem.</div>`;
      const dev = slot.kind === "item" ? data.devices[slot.item] : null;
      const floor = (data.passive[slot.kind] || {}).bottom;
      return `<div class="rk-insp">
          <div class="rk-insp-head"><b>${esc(nameOf(slot))}</b><span class="muted">${range(slot)}</span></div>
          <div class="frow"><label>Hoogte</label>
            <select class="inp" id="rk-height">${Array.from({ length: Math.min(12, data.units) }, (_, i) => i + 1).map((h) =>
              `<option value="${h}"${h === slot.height ? " selected" : ""}>${h}U</option>`).join("")}</select></div>
          ${slot.kind !== "item" ? `<div class="frow"><label>Naam</label>
            <input class="inp" id="rk-label" value="${esc(slot.label || "")}"
                   placeholder="${esc((data.passive[slot.kind] || {}).label || "")}" /></div>` : formControl(dev)}
          ${slot.kind === "patch" ? `<div class="frow"><label>Poorten</label>
            <select class="inp" id="rk-ports">${[12, 16, 24, 48].map((n) =>
              `<option value="${n}"${n === (slot.ports || 24) ? " selected" : ""}>${n}</option>`).join("")}</select></div>` : ""}
          <div class="rk-insp-acts">
            ${floor ? "" : `<button class="btn ghost sm" id="rk-up" title="Eén unit omhoog">${ICON.arrowUp}</button>
            <button class="btn ghost sm" id="rk-down" title="Eén unit omlaag">${ICON.arrowDown}</button>`}
            ${dev && !dev.hidden ? `<button class="btn ghost sm" id="rk-open">${ICON.external} Openen</button>` : ""}
            <button class="btn ghost sm" id="rk-remove">${ICON.trash} Uit de kast</button>
          </div>
          ${holds(slot) && (slot.items || []).length ? `<div class="hint" style="margin:-2px 0 10px">Wat erop staat gaat
            mee naar buiten, en komt terug in de lijst hiernaast.</div>` : ""}
        </div>`;
    }

    function palette() {
      const words = filter.toLowerCase().split(/\s+/).filter(Boolean);
      const devices = data.candidates.filter((c) =>
        words.every((w) => `${c.name} ${c.role}`.toLowerCase().includes(w)));
      const rail = Object.entries(data.passive).map(([kind, p]) => `
        <div class="rk-pick" draggable="true" data-new="${kind}" title="Sleep in de kast${p.bottom ? " — altijd onderin" : ""}">
          <span class="rk-mini rk-${kind}"></span><span>${esc(p.label)}</span><span class="muted">${p.height}U</span></div>`).join("");
      const loose = Object.entries(data.standing).map(([kind, p]) => `
        <div class="rk-pick" draggable="true" data-stand="${kind}" title="Sleep op een plank of de bodem">
          <span class="rk-mini rk-${kind}"></span><span>${esc(p.label)}</span><span class="muted">los</span></div>`).join("");
      return `<div class="rk-side-sec"><h3>Apparatuur van ${esc(org.name)}</h3>
          <input class="inp" id="rk-filter" type="search" placeholder="Zoek…" value="${esc(filter)}" />
          <div class="rk-picks">${devices.length ? devices.map((c) => `
            <div class="rk-pick" draggable="true" data-dev="${esc(c.id)}"
                 title="${c.rack ? "19 inch: in de rails, of op een plank" : "Los: op een plank of de bodem"}">
              <span class="rk-pick-ic">${ICON[(kinds[c.kind] || {}).icon] || ICON.box}</span>
              <span class="rk-pick-name">${esc(c.name)}</span>
              <span class="tag${c.rack ? "" : " on"}" title="${c.guessed ? "Geschat — stel het in bij het apparaat" : ""}">${formTag(c)}${c.guessed ? "?" : ""}</span></div>`).join("")
            : `<div class="muted rk-none">${data.candidates.length ? "Niets gevonden" : "Alles staat al in deze kast"}</div>`}</div>
        </div>
        <div class="rk-side-sec"><h3>In de rails</h3><div class="rk-picks">${rail}</div></div>
        <div class="rk-side-sec"><h3>Los neerzetten</h3><div class="rk-picks">${loose}</div></div>`;
    }

    function paint() {
      const rows = [];
      for (let u = data.units; u >= 1; u--) rows.push(`<span style="bottom:${(u - 1) * UPX}px">${u}</span>`);
      const outside = data.slots.filter((s) => s.at + s.height - 1 > data.units);
      const selSlot = selected && selected.slot;
      const selThing = selected && selected.thing;
      host.innerHTML = `<div class="panel rk-panel">
          <div class="panel-head"><h2>Kast</h2>
            <span class="sub">${data.units}U · ${data.slots.length ? `${data.slots.length} onderdelen,
              ${data.slots.reduce((n, s) => n + s.height, 0)}U gebruikt` : "nog leeg"}</span></div>
          <div class="rk-wrap">
            <div class="rk-cabinet">
              <div class="rk-top"></div>
              <div class="rk-frame">
                <div class="rk-rail l">${rows.join("")}</div>
                <div class="rk-bay" style="height:${data.units * UPX}px;width:${WIDTH}px">
                  ${data.slots.filter((s) => s.at + s.height - 1 <= data.units).map((s) => `
                    <div class="rk-slot${s.id === selSlot ? " sel" : ""}${holds(s) ? " rk-holds" : ""}" data-slot="${esc(s.id)}"
                         style="bottom:${(s.at - 1) * UPX}px;height:${s.height * UPX}px"
                         title="${esc(nameOf(s))} · ${range(s)}">${holds(s)
                           ? holderHtml(s, data.devices, data.standing, data.passive, selThing)
                           : front(s, data.devices[s.item], s.height, data.passive)}</div>`).join("")}
                  <div class="rk-drop hidden" id="rk-drop"></div>
                </div>
                <div class="rk-rail r">${rows.join("")}</div>
              </div>
              <div class="rk-feet"><i></i><i></i></div>
            </div>
            ${mayEdit ? `<div class="rk-side">${inspector()}${palette()}</div>`
                      : `<div class="rk-side"><div class="rk-help">Klik op een apparaat in de kast om het te openen.</div></div>`}
          </div>
          ${outside.length ? `<div class="callout warn" style="margin:0 18px 16px"><div class="ic">${ICON.alert}</div>
            <div class="cd">Past niet meer in een kast van ${data.units}U: ${outside.map((s) =>
              `${esc(nameOf(s))} (${range(s)})`).join(", ")}. Maak de kast hoger, of verplaats ze.</div></div>` : ""}
        </div>`;
      wire();
    }

    // Everything that can be in a holder, the way the server takes it.
    const plainSlots = (fn) => data.slots.map((s) => fn({ ...s, items: s.items ? s.items.map((t) => ({ ...t })) : undefined }));

    function wire() {
      const bay = host.querySelector(".rk-bay");
      const drop = host.querySelector("#rk-drop");
      let dragging = null;

      const openDevice = (itemId) => {
        const dev = data.devices[itemId];
        if (dev && !dev.hidden) go(`#/klant/${org.id}/item/${itemId}`);
      };

      // Picking, or (read only) opening.
      host.querySelectorAll(".rk-slot").forEach((el) => {
        const slot = data.slots.find((s) => s.id === el.dataset.slot);
        el.onclick = (ev) => {
          if (ev.target.closest(".rk-thing")) return;
          if (!mayEdit) { if (slot.kind === "item") openDevice(slot.item); return; }
          selected = selected && selected.slot === slot.id ? null : { slot: slot.id };
          paint();
        };
      });
      host.querySelectorAll(".rk-thing").forEach((el) => {
        el.onclick = () => {
          const holder = data.slots.find((s) => s.id === el.dataset.holder);
          const thing = (holder.items || []).find((t) => t.id === el.dataset.thing);
          if (!mayEdit) { if (thing.item) openDevice(thing.item); return; }
          selected = selected && selected.thing === thing.id ? null : { holder: holder.id, thing: thing.id };
          paint();
        };
      });
      if (!mayEdit) return;

      const end = () => {
        dragging = null;
        drop.classList.add("hidden");
        host.querySelectorAll(".drop-on").forEach((x) => x.classList.remove("drop-on"));
      };
      const start = (el, what, effect) => {
        el.addEventListener("dragstart", (ev) => {
          ev.stopPropagation();
          dragging = what();
          ev.dataTransfer.effectAllowed = effect;
          ev.dataTransfer.setData("text/plain", dragging.type);
        });
        el.addEventListener("dragend", end);
      };

      host.querySelectorAll(".rk-slot").forEach((el) => {
        const slot = data.slots.find((s) => s.id === el.dataset.slot);
        el.draggable = true;
        el.addEventListener("dragstart", (ev) => {
          if (ev.target.closest(".rk-thing")) return;
          const r = el.getBoundingClientRect();
          // Which unit of it was taken hold of, so it lands where it was held.
          const grab = Math.min(slot.height - 1, Math.floor((r.bottom - ev.clientY) / UPX));
          dragging = { type: "move", id: slot.id, height: slot.height, grab,
                       bottom: !!(data.passive[slot.kind] || {}).bottom };
          ev.dataTransfer.effectAllowed = "move";
          ev.dataTransfer.setData("text/plain", slot.id);
        });
        el.addEventListener("dragend", end);
      });
      host.querySelectorAll(".rk-thing").forEach((el) => {
        el.draggable = true;
        start(el, () => ({ type: "stand-move", holder: el.dataset.holder, id: el.dataset.thing }), "move");
      });
      host.querySelectorAll("[data-new]").forEach((el) => {
        start(el, () => {
          const p = data.passive[el.dataset.new] || {};
          return { type: "new", kind: el.dataset.new, height: p.height || 1, grab: (p.height || 1) - 1, bottom: !!p.bottom };
        }, "copy");
      });
      host.querySelectorAll("[data-stand]").forEach((el) => {
        start(el, () => ({ type: "stand-new", kind: el.dataset.stand }), "copy");
      });
      host.querySelectorAll("[data-dev]").forEach((el) => {
        start(el, () => {
          const c = data.candidates.find((x) => x.id === el.dataset.dev);
          // 19 inch: into the rails (or onto a shelf). Not: onto a shelf or the bottom only.
          return c.rack ? { type: "dev", id: c.id, height: c.units, grab: c.units - 1, name: c.name }
                        : { type: "stand-dev", id: c.id, name: c.name };
        }, "copy");
      });

      const standing = (d) => d && (d.type === "stand-new" || d.type === "stand-dev" || d.type === "stand-move");
      const railing = (d) => d && (d.type === "new" || d.type === "dev" || d.type === "move");

      // The rails.
      const landing = (ev) => {
        const r = bay.getBoundingClientRect();
        const unit = Math.floor((r.bottom - ev.clientY) / UPX) + 1;    // the unit under the pointer
        let at = Math.max(1, Math.min(data.units - dragging.height + 1, unit - dragging.grab));
        if (dragging.bottom) at = 1;                                   // the bottom is the bottom
        return { at, ok: fits(at, dragging.height, dragging.type === "move" ? dragging.id : null) };
      };
      bay.addEventListener("dragover", (ev) => {
        if (!dragging) return;
        ev.preventDefault();
        if (!railing(dragging)) return;
        const { at, ok } = landing(ev);
        drop.classList.remove("hidden");
        drop.classList.toggle("bad", !ok);
        drop.style.bottom = `${(at - 1) * UPX}px`;
        drop.style.height = `${dragging.height * UPX}px`;
      });
      bay.addEventListener("dragleave", (ev) => {
        if (!bay.contains(ev.relatedTarget)) drop.classList.add("hidden");
      });
      bay.addEventListener("drop", (ev) => {
        if (!dragging) return;
        ev.preventDefault();
        const what = dragging;
        if (standing(what)) {
          end();
          toast(`${what.name || "Dit"} is geen 19 inch: zet het op een plank of de bodem`);
          return;
        }
        const { at, ok } = landing(ev);
        end();
        if (!ok) { toast("Daar is geen plek: er zit al iets, of het steekt uit de kast"); return; }
        if (what.type === "move") {
          selected = { slot: what.id };
          save(plainSlots((s) => (s.id === what.id ? { ...s, at } : s)));
        } else if (what.type === "new") {
          const slot = { kind: what.kind, at, height: what.height, ...(what.kind === "patch" ? { ports: 24 } : {}),
                         ...((data.passive[what.kind] || {}).holds ? { items: [] } : {}) };
          save([...plainSlots((s) => s), slot], `${(data.passive[what.kind] || {}).label || "Onderdeel"} geplaatst`);
        } else {
          save([...plainSlots((s) => s), { kind: "item", item: what.id, at, height: what.height }], "In de kast gehangen");
        }
      });

      // A shelf or the bottom takes what stands -- and a 19-inch thing laid on it.
      host.querySelectorAll(".rk-slot.rk-holds").forEach((el) => {
        const holderId = el.dataset.slot;
        const accepts = (d) => standing(d) || (d && d.type === "dev");
        el.addEventListener("dragover", (ev) => {
          if (!accepts(dragging)) return;
          ev.preventDefault();
          ev.stopPropagation();
          drop.classList.add("hidden");
          el.classList.add("drop-on");
        });
        el.addEventListener("dragleave", (ev) => { if (!el.contains(ev.relatedTarget)) el.classList.remove("drop-on"); });
        el.addEventListener("drop", (ev) => {
          if (!accepts(dragging)) return;
          ev.preventDefault();
          ev.stopPropagation();
          const what = dragging;
          end();
          let moved = null;
          const slots = plainSlots((s) => {
            if (what.type === "stand-move" && s.id === what.holder) {
              moved = (s.items || []).find((t) => t.id === what.id);
              s.items = (s.items || []).filter((t) => t.id !== what.id);
            }
            return s;
          });
          const entry = what.type === "stand-move" ? moved
            : what.type === "stand-new" ? { kind: what.kind } : { item: what.id };
          if (!entry) return;
          const holder = slots.find((s) => s.id === holderId);
          holder.items = [...(holder.items || []), entry];
          save(slots, what.type === "stand-move" ? "Verplaatst" : "Neergezet");
        });
      });

      // The picked thing.
      const pick = selected || {};
      if (pick.thing) {
        const change = (fn, message) => save(plainSlots((s) => {
          if (s.id === pick.holder) s.items = fn(s.items || []);
          return s;
        }), message);
        const label = host.querySelector("#rk-thing-label");
        if (label) label.onchange = () => change((items) => items.map((t) =>
          (t.id === pick.thing ? { ...t, label: label.value.trim() } : t)));
        const remove = host.querySelector("#rk-thing-remove");
        if (remove) remove.onclick = () => { selected = null; change((items) => items.filter((t) => t.id !== pick.thing), "Eraf gehaald"); };
      }
      const slot = pick.slot && data.slots.find((s) => s.id === pick.slot);
      if (slot) {
        const change = (patch, message) => save(plainSlots((s) => (s.id === slot.id ? { ...s, ...patch } : s)), message);
        host.querySelector("#rk-height").onchange = (ev) => {
          const height = Number(ev.target.value);
          if (!fits(slot.at, height, slot.id)) { toast("Zo hoog past het daar niet"); paint(); return; }
          change({ height });
        };
        const label = host.querySelector("#rk-label");
        if (label) label.onchange = () => change({ label: label.value.trim() });
        const ports = host.querySelector("#rk-ports");
        if (ports) ports.onchange = () => change({ ports: Number(ports.value) });
        const step = (by) => {
          if (!fits(slot.at + by, slot.height, slot.id)) { toast("Daar is geen plek"); return; }
          change({ at: slot.at + by });
        };
        const up = host.querySelector("#rk-up");
        if (up) up.onclick = () => step(1);
        const down = host.querySelector("#rk-down");
        if (down) down.onclick = () => step(-1);
        host.querySelector("#rk-remove").onclick = () => {
          selected = null;
          save(data.slots.filter((s) => s.id !== slot.id), "Uit de kast gehaald");
        };
      }
      const devId = (pick.slot && slot && slot.kind === "item" && slot.item)
        || (pick.thing && ((data.slots.find((s) => s.id === pick.holder) || {}).items || [])
          .find((t) => t.id === pick.thing) || {}).item;
      const open = host.querySelector("#rk-open");
      if (open && devId) open.onclick = () => openDevice(devId);
      const form = host.querySelector("#rk-form");
      if (form && devId) form.onchange = () => {
        const height = slot && slot.kind === "item" ? slot.height : null;
        setForm(devId, form.value, form.value === data.forms[0] ? height : null);
      };

      const search = host.querySelector("#rk-filter");
      if (search) search.oninput = () => {
        filter = search.value;
        const keep = search.selectionStart;
        paint();
        const again = host.querySelector("#rk-filter");
        again.focus();
        again.setSelectionRange(keep, keep);
      };
    }

    paint();
  }

  /* On a machine's page: the cabinets it hangs or stands in, and where. */
  async function whereHangs(slot, org, itemId) {
    if (!slot) return;
    let racks = [];
    try { racks = await api(`/api/items/${itemId}/racks`); } catch (e) { return; }
    slot.innerHTML = racks.map((r) => `<a class="tag rk-where" data-goto="${esc(r.rack_id)}"
        title="Openen">${ICON.rack} ${esc(r.rack_name)} · ${r.on ? `op ${esc(r.on.toLowerCase())}, ` : ""}U${r.at}${r.height > 1 ? `–U${r.at + r.height - 1}` : ""}</a>`).join(" ");
    slot.querySelectorAll("[data-goto]").forEach((a) => {
      a.onclick = () => go(`#/klant/${org.id}/item/${a.dataset.goto}`);
    });
  }

  return { view, whereHangs };
};
