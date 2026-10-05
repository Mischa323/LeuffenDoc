/* Patch cabinets — the cabinet drawn as it stands.

   To scale: one unit (44.45 mm) is 40 px, and the 19-inch front 434 px wide,
   so a 1U switch is as flat and as wide as the real one and its 24 or 48
   ports fit where they are on the real one. U1 is at the bottom, as on the
   rails. Documented equipment of the customer and passive parts -- patch
   panels, blanking plates, cable managers, shelves, power strips, a UPS --
   are dragged in from the side; what is in the cabinet is dragged to another
   height, or picked to change its height or take it out. A switch shows which
   of its ports are taken, and by what, from its patch list.

   Every change is saved at once; the server checks it fits and overlaps
   nothing, and the drawing is redrawn from what it stored. */
window.DocRack = function (ctx) {
  "use strict";

  const { api, esc, toast, go } = ctx;
  const UPX = 40;                                   // one unit on screen
  const WIDTH = Math.round(UPX * 482.6 / 44.45);    // the 19-inch front: 434 px

  // A documented thing's height when it is first put in; changeable after.
  const firstHeight = (dev) => (dev.kind === "computer" && ["Server", "NAS"].includes(dev.role) ? 2 : 1);

  /* ---- fronts, as they look ---- */
  const ear = `<span class="rk-ear l"><i></i><i></i></span><span class="rk-ear r"><i></i><i></i></span>`;

  function portGrid(ports, rows, cls) {
    // Switches and patch panels number their ports in columns: 1 above 2, 3
    // above 4, ... -- so the top row holds the odd ones.
    const n = ports.length;
    const cols = Math.ceil(n / rows);
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

  function face(slot, dev, height) {
    const name = (text) => `<span class="rk-name">${esc(text)}</span>`;
    if (slot.kind === "item") {
      if (!dev) return `${ear}<span class="rk-plate rk-gone">${name("Niet meer te zien")}</span>`;
      if (dev.hidden) return `${ear}<span class="rk-plate">${name("Afgeschermd")}</span>`;
      if (dev.kind === "network" && dev.role === "Switch") {
        const ports = dev.ports && dev.ports.length ? dev.ports
          : Array.from({ length: 24 }, (_, i) => ({ number: i + 1 }));
        return `${ear}<span class="rk-body rk-sw">${name(dev.name)}
            <span class="rk-leds"><i class="pwr"></i><i></i></span>
            ${portGrid(ports, ports.length > 12 ? 2 : 1, "")}</span>`;
      }
      if (dev.kind === "network") {
        const count = dev.role === "Modem" ? 4 : dev.role === "Wifi-punt" ? 2 : 8;
        const ports = Array.from({ length: count }, (_, i) => ({ number: i + 1 }));
        return `${ear}<span class="rk-body rk-app">${name(dev.name)}
            <span class="rk-role">${esc(dev.role || "Netwerk")}</span>
            <span class="rk-leds"><i class="pwr"></i><i></i><i></i></span>${portGrid(ports, 1, "")}</span>`;
      }
      if (dev.kind === "computer") {
        const bays = height >= 2 ? 12 : 8;
        return `${ear}<span class="rk-body rk-srv">${name(dev.name)}
            <span class="rk-role">${esc(dev.role || "")}</span>
            <span class="rk-bays h${Math.min(height, 4)}">${"<i></i>".repeat(bays)}</span>
            <span class="rk-leds"><i class="pwr"></i></span></span>`;
      }
      return `${ear}<span class="rk-body rk-gen">${name(dev.name)}</span>`;
    }
    const label = slot.label || (PASSIVE[slot.kind] || {}).label || slot.kind;
    switch (slot.kind) {
      case "patch": {
        const ports = Array.from({ length: slot.ports || 24 }, (_, i) => ({ number: i + 1 }));
        return `${ear}<span class="rk-body rk-patch">${name(label)}${portGrid(ports, ports.length > 24 ? 2 : 1, "jack")}</span>`;
      }
      case "blank": return `${ear}<span class="rk-plate rk-blank">${slot.label ? name(slot.label) : ""}</span>`;
      case "cable": return `${ear}<span class="rk-plate rk-cable">${"<i></i>".repeat(5)}${slot.label ? name(slot.label) : ""}</span>`;
      case "shelf": return `${ear}<span class="rk-plate rk-shelf">${name(label)}</span>`;
      case "pdu": return `${ear}<span class="rk-body rk-pdu">${name(label)}<span class="rk-sockets">${"<i></i>".repeat(8)}</span><span class="rk-leds"><i class="pwr"></i></span></span>`;
      case "ups": return `${ear}<span class="rk-body rk-ups">${name(label)}<span class="rk-lcd">UPS</span><span class="rk-leds"><i class="pwr"></i><i></i><i></i></span></span>`;
      default: return `${ear}<span class="rk-plate">${name(label)}</span>`;
    }
  }

  let PASSIVE = {};

  async function view(host, { org, item, mayEdit, all, kinds }) {
    if (!host) return;
    let data;
    try { data = await api(`/api/items/${item.id}/rack`); } catch (e) {
      host.innerHTML = `<div class="callout warn"><div class="ic">${ICON.alert}</div><div class="cd">${esc(e.message)}</div></div>`;
      return;
    }
    PASSIVE = data.passive || {};
    let selected = null;
    let filter = "";

    const nameOf = (slot) => (slot.kind === "item"
      ? ((data.devices[slot.item] || {}).name || "Apparaat")
      : (slot.label || (PASSIVE[slot.kind] || {}).label || slot.kind));
    const range = (slot) => (slot.height === 1 ? `U${slot.at}` : `U${slot.at}–U${slot.at + slot.height - 1}`);
    const fits = (at, height, ignore) => at >= 1 && at + height - 1 <= data.units
      && data.slots.every((s) => s.id === ignore || s.at + s.height - 1 < at || s.at > at + height - 1);

    // What can go in: this customer's equipment not in this cabinet yet.
    const inHere = () => new Set(data.slots.filter((s) => s.kind === "item").map((s) => s.item));
    const equipment = () => (all || []).filter((i) => !i.archived && i.kind !== "rack"
      && (["computer", "network", "printer"].includes(i.kind) || ((kinds[i.kind] || {}).custom))
      && !inHere().has(i.id));

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

    function inspector() {
      const slot = data.slots.find((s) => s.id === selected);
      if (!slot) return `<div class="rk-help">Klik op een onderdeel in de kast om de hoogte of de naam
          te wijzigen, of om het eruit te halen.</div>`;
      const dev = slot.kind === "item" ? data.devices[slot.item] : null;
      const maxHeight = Math.min(10, data.units);
      return `<div class="rk-insp">
          <div class="rk-insp-head"><b>${esc(nameOf(slot))}</b><span class="muted">${range(slot)}</span></div>
          <div class="frow"><label>Hoogte</label>
            <select class="inp" id="rk-height">${Array.from({ length: maxHeight }, (_, i) => i + 1).map((h) =>
              `<option value="${h}"${h === slot.height ? " selected" : ""}>${h}U</option>`).join("")}</select></div>
          ${slot.kind !== "item" ? `<div class="frow"><label>Naam</label>
            <input class="inp" id="rk-label" value="${esc(slot.label || "")}"
                   placeholder="${esc((PASSIVE[slot.kind] || {}).label || "")}" /></div>` : ""}
          ${slot.kind === "patch" ? `<div class="frow"><label>Poorten</label>
            <select class="inp" id="rk-ports">${[12, 16, 24, 48].map((n) =>
              `<option value="${n}"${n === (slot.ports || 24) ? " selected" : ""}>${n}</option>`).join("")}</select></div>` : ""}
          <div class="rk-insp-acts">
            <button class="btn ghost sm" id="rk-up" title="Eén unit omhoog">${ICON.arrowUp}</button>
            <button class="btn ghost sm" id="rk-down" title="Eén unit omlaag">${ICON.arrowDown}</button>
            ${dev && !dev.hidden ? `<button class="btn ghost sm" id="rk-open">${ICON.external} Openen</button>` : ""}
            <button class="btn ghost sm" id="rk-remove">${ICON.trash} Uit de kast</button>
          </div>
        </div>`;
    }

    function palette() {
      const passive = Object.entries(PASSIVE).map(([kind, p]) => `
        <div class="rk-pick" draggable="true" data-new="${kind}" title="Sleep in de kast">
          <span class="rk-mini rk-${kind}"></span><span>${esc(p.label)}</span><span class="muted">${p.height}U</span></div>`).join("");
      const words = filter.toLowerCase().split(/\s+/).filter(Boolean);
      const devices = equipment().filter((i) => words.every((w) => `${i.name} ${(i.fields || {}).role || ""}`.toLowerCase().includes(w)));
      return `<div class="rk-side-sec"><h3>Apparatuur van ${esc(org.name)}</h3>
          <input class="inp" id="rk-filter" type="search" placeholder="Zoek…" value="${esc(filter)}" />
          <div class="rk-picks">${devices.length ? devices.map((i) => `
            <div class="rk-pick" draggable="true" data-dev="${esc(i.id)}" title="Sleep in de kast">
              <span class="rk-pick-ic">${ICON[(kinds[i.kind] || {}).icon] || ICON.box}</span>
              <span class="rk-pick-name">${esc(i.name)}</span>
              <span class="muted">${esc((i.fields || {}).role || (kinds[i.kind] || {}).label || "")}</span></div>`).join("")
            : `<div class="muted rk-none">${equipment().length ? "Niets gevonden" : "Alles hangt al in deze kast"}</div>`}</div>
        </div>
        <div class="rk-side-sec"><h3>Passief</h3><div class="rk-picks">${passive}</div></div>`;
    }

    function paint() {
      const rows = [];
      for (let u = data.units; u >= 1; u--) rows.push(`<span style="bottom:${(u - 1) * UPX}px">${u}</span>`);
      const outside = data.slots.filter((s) => s.at + s.height - 1 > data.units);
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
                    <div class="rk-slot${s.id === selected ? " sel" : ""}" data-slot="${esc(s.id)}"
                         style="bottom:${(s.at - 1) * UPX}px;height:${s.height * UPX}px"
                         title="${esc(nameOf(s))} · ${range(s)}">${face(s, data.devices[s.item], s.height)}</div>`).join("")}
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

    function wire() {
      const bay = host.querySelector(".rk-bay");
      const drop = host.querySelector("#rk-drop");
      let dragging = null;       // { type: "new"|"dev"|"move", kind?, id?, height, grab }

      host.querySelectorAll(".rk-slot").forEach((el) => {
        const slot = data.slots.find((s) => s.id === el.dataset.slot);
        el.onclick = () => {
          if (!mayEdit) {
            if (slot.kind === "item" && data.devices[slot.item] && !data.devices[slot.item].hidden) {
              go(`#/klant/${org.id}/item/${slot.item}`);
            }
            return;
          }
          selected = selected === slot.id ? null : slot.id;
          paint();
        };
        if (!mayEdit) return;
        el.draggable = true;
        el.addEventListener("dragstart", (ev) => {
          const r = el.getBoundingClientRect();
          // Which unit of it was taken hold of, so it lands where it was held.
          const grab = Math.min(slot.height - 1, Math.floor((r.bottom - ev.clientY) / UPX));
          dragging = { type: "move", id: slot.id, height: slot.height, grab };
          ev.dataTransfer.effectAllowed = "move";
          ev.dataTransfer.setData("text/plain", slot.id);
        });
        el.addEventListener("dragend", () => { dragging = null; drop.classList.add("hidden"); });
      });
      if (!mayEdit) return;

      host.querySelectorAll("[data-new], [data-dev]").forEach((el) => {
        el.addEventListener("dragstart", (ev) => {
          if (el.dataset.new) {
            const kind = el.dataset.new;
            const height = (PASSIVE[kind] || {}).height || 1;
            dragging = { type: "new", kind, height, grab: height - 1 };
          } else {
            const found = (all || []).find((i) => i.id === el.dataset.dev);
            const height = firstHeight({ kind: found.kind, role: (found.fields || {}).role });
            dragging = { type: "dev", id: found.id, height, grab: height - 1 };
          }
          ev.dataTransfer.effectAllowed = "copy";
          ev.dataTransfer.setData("text/plain", dragging.type);
        });
        el.addEventListener("dragend", () => { dragging = null; drop.classList.add("hidden"); });
      });

      const landing = (ev) => {
        const r = bay.getBoundingClientRect();
        const unit = Math.floor((r.bottom - ev.clientY) / UPX) + 1;    // the unit under the pointer
        const at = Math.max(1, Math.min(data.units - dragging.height + 1, unit - dragging.grab));
        return { at, ok: fits(at, dragging.height, dragging.type === "move" ? dragging.id : null) };
      };
      bay.addEventListener("dragover", (ev) => {
        if (!dragging) return;
        ev.preventDefault();
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
        const { at, ok } = landing(ev);
        const what = dragging;
        dragging = null;
        drop.classList.add("hidden");
        if (!ok) { toast("Daar is geen plek: er hangt al iets, of het steekt uit de kast"); return; }
        if (what.type === "move") {
          const slots = data.slots.map((s) => (s.id === what.id ? { ...s, at } : s));
          selected = what.id;
          save(slots);
        } else if (what.type === "new") {
          const slot = { kind: what.kind, at, height: what.height, ...(what.kind === "patch" ? { ports: 24 } : {}) };
          save([...data.slots, slot], `${(PASSIVE[what.kind] || {}).label || "Onderdeel"} geplaatst`);
        } else {
          save([...data.slots, { kind: "item", item: what.id, at, height: what.height }], "In de kast gehangen");
        }
      });

      // The picked part: height, name, ports, a unit up or down, out.
      const slot = data.slots.find((s) => s.id === selected);
      if (slot) {
        const change = (patch, message) => save(data.slots.map((s) => (s.id === slot.id ? { ...s, ...patch } : s)), message);
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
        host.querySelector("#rk-up").onclick = () => step(1);
        host.querySelector("#rk-down").onclick = () => step(-1);
        const open = host.querySelector("#rk-open");
        if (open) open.onclick = () => go(`#/klant/${org.id}/item/${slot.item}`);
        host.querySelector("#rk-remove").onclick = () => {
          selected = null;
          save(data.slots.filter((s) => s.id !== slot.id), "Uit de kast gehaald");
        };
      }
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

  /* On a machine's page: the cabinets it hangs in, and at what height. */
  async function whereHangs(slot, org, itemId) {
    if (!slot) return;
    let racks = [];
    try { racks = await api(`/api/items/${itemId}/racks`); } catch (e) { return; }
    slot.innerHTML = racks.map((r) => `<a class="tag rk-where" data-goto="${esc(r.rack_id)}"
        title="Openen">${ICON.rack} ${esc(r.rack_name)} · U${r.at}${r.height > 1 ? `–U${r.at + r.height - 1}` : ""}</a>`).join(" ");
    slot.querySelectorAll("[data-goto]").forEach((a) => {
      a.onclick = () => go(`#/klant/${org.id}/item/${a.dataset.goto}`);
    });
  }

  return { view, whereHangs };
};
