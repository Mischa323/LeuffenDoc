/* Laying out the sidebar inside a customer: groups with a name (or none), the
   sections under each in order, and the sections hidden. The same editor sets
   the layout for everyone (an administrator, under Instellingen) and a
   person's own (from the sidebar itself); app.js decides which is in force.

   Sections are dragged between and within groups -- or moved with the arrows,
   for whoever works without a mouse -- groups are renamed, moved, added and
   removed, and a section is hidden with its eye. */
window.DocSidebar = function (ctx) {
  const { esc, toast } = ctx;

  /* `sections`: every section there is ({id, label, icon}); `layout`: what
     to start from ({groups:[{id,label,sections}], hidden}); `actions`: the
     buttons under it ({label, primary, run(layout)}). */
  function editor(host, { sections, layout, intro, actions }) {
    const byId = new Map(sections.map((s) => [s.id, s]));
    // Working copy: only sections that exist, each once.
    let groups = (layout.groups || []).map((g) => ({ id: g.id, label: g.label || "",
      sections: (g.sections || []).filter((id) => byId.has(id)) }));
    let hidden = (layout.hidden || []).filter((id) => byId.has(id));
    const placed = new Set([...groups.flatMap((g) => g.sections), ...hidden]);
    for (const s of sections) {
      if (!placed.has(s.id)) {
        let g = groups.find((x) => x.id === s.home);
        if (!g) { g = { id: s.home || "overig", label: s.homeLabel || "Overig", sections: [] }; groups.push(g); }
        g.sections.push(s.id);
      }
    }
    let dragging = null;

    const row = (id, gi, si) => {
      const s = byId.get(id);
      return `<div class="sbe-item" draggable="true" data-sid="${esc(id)}" data-g="${gi}" data-i="${si}">
          <span class="sbe-grip" aria-hidden="true">⠿</span>
          <span class="sbe-ic">${ICON[s.icon] || ""}</span>
          <span class="sbe-name">${esc(s.label)}</span>
          <span class="sbe-acts">
            <button type="button" class="lay-ib" data-up title="Omhoog">${ICON.arrowUp}</button>
            <button type="button" class="lay-ib" data-down title="Omlaag">${ICON.arrowDown}</button>
            <button type="button" class="lay-ib" data-hide title="Verbergen">${ICON.eyeOff}</button>
          </span>
        </div>`;
    };

    const draw = () => {
      host.innerHTML = `<div class="sbe">
          ${intro ? `<div class="sbe-intro">${intro}</div>` : ""}
          <div class="sbe-groups">${groups.map((g, gi) => `
            <div class="panel sbe-group" data-g="${gi}">
              <div class="sbe-ghead">
                <input class="inp sbe-gname" data-gname="${gi}" value="${esc(g.label)}" placeholder="Zonder kop" maxlength="40"
                       aria-label="Naam van de groep" />
                <button type="button" class="lay-ib" data-gup="${gi}" title="Groep omhoog"${gi === 0 ? " disabled" : ""}>${ICON.arrowUp}</button>
                <button type="button" class="lay-ib" data-gdown="${gi}" title="Groep omlaag"${gi === groups.length - 1 ? " disabled" : ""}>${ICON.arrowDown}</button>
                <button type="button" class="lay-ib" data-gdel="${gi}" title="Groep weghalen — wat erin staat gaat naar de groep erboven">${ICON.trash}</button>
              </div>
              <div class="sbe-items" data-drop="${gi}">
                ${g.sections.map((id, si) => row(id, gi, si)).join("") || `<div class="sbe-empty">Sleep hier een sectie heen</div>`}
              </div>
            </div>`).join("")}
          </div>
          <button type="button" class="btn ghost sm" id="sbe-add">${ICON.plus} Groep toevoegen</button>
          <div class="panel sbe-hidden">
            <div class="panel-head"><h2>Verborgen</h2><span class="sub">${hidden.length ? hidden.length : "Niets"} — niet in de zijbalk, wel te openen via een link of zoeken</span></div>
            <div class="sbe-hrows">${hidden.map((id) => `<div class="sbe-item hidden-one" data-sid="${esc(id)}">
                <span class="sbe-ic">${ICON[byId.get(id).icon] || ""}</span><span class="sbe-name">${esc(byId.get(id).label)}</span>
                <button type="button" class="btn ghost sm" data-show="${esc(id)}">${ICON.eye} Tonen</button></div>`).join("")}</div>
          </div>
          <div class="sbe-foot">${actions.map((a, i) => `<button type="button" class="btn${a.primary ? "" : " ghost"}" data-act="${i}">${a.label}</button>`).join("")}</div>
        </div>`;
      wire();
    };

    const move = (sid, toGroup, toIndex) => {
      for (const g of groups) g.sections = g.sections.filter((x) => x !== sid);
      hidden = hidden.filter((x) => x !== sid);
      const list = groups[toGroup].sections;
      list.splice(Math.max(0, Math.min(toIndex, list.length)), 0, sid);
      draw();
      const el = host.querySelector(`.sbe-item[data-sid="${CSS.escape(sid)}"]`);
      if (el) el.classList.add("sbe-moved");
    };

    const wire = () => {
      host.querySelectorAll("[data-gname]").forEach((inp) => {
        inp.oninput = () => { groups[Number(inp.dataset.gname)].label = inp.value; };
      });
      host.querySelectorAll("[data-gup]").forEach((b) => b.onclick = () => {
        const i = Number(b.dataset.gup);
        [groups[i - 1], groups[i]] = [groups[i], groups[i - 1]];
        draw();
      });
      host.querySelectorAll("[data-gdown]").forEach((b) => b.onclick = () => {
        const i = Number(b.dataset.gdown);
        [groups[i + 1], groups[i]] = [groups[i], groups[i + 1]];
        draw();
      });
      host.querySelectorAll("[data-gdel]").forEach((b) => b.onclick = () => {
        const i = Number(b.dataset.gdel);
        if (groups.length === 1) { toast("Er moet een groep overblijven"); return; }
        const into = groups[i === 0 ? 1 : i - 1];
        into.sections.push(...groups[i].sections);
        groups.splice(i, 1);
        draw();
      });
      host.querySelector("#sbe-add").onclick = () => {
        groups.push({ id: `g-${Math.random().toString(36).slice(2, 8)}`, label: "Nieuwe groep", sections: [] });
        draw();
        const inp = host.querySelector(`[data-gname="${groups.length - 1}"]`);
        if (inp) { inp.focus(); inp.select(); }
      };
      host.querySelectorAll(".sbe-groups .sbe-item").forEach((el) => {
        const gi = Number(el.dataset.g), si = Number(el.dataset.i), sid = el.dataset.sid;
        el.querySelector("[data-up]").onclick = () => {
          if (si > 0) move(sid, gi, si - 1);
          else if (gi > 0) move(sid, gi - 1, groups[gi - 1].sections.length);   // to the end of the group above
        };
        el.querySelector("[data-down]").onclick = () => {
          if (si < groups[gi].sections.length - 1) move(sid, gi, si + 1);
          else if (gi < groups.length - 1) move(sid, gi + 1, 0);                // to the top of the group below
        };
        el.querySelector("[data-hide]").onclick = () => {
          groups[gi].sections = groups[gi].sections.filter((x) => x !== sid);
          hidden.push(sid);
          draw();
        };
        el.addEventListener("dragstart", (ev) => {
          dragging = sid;
          el.classList.add("dragging");
          ev.dataTransfer.effectAllowed = "move";
          ev.dataTransfer.setData("text/plain", sid);
        });
        el.addEventListener("dragend", () => { dragging = null; el.classList.remove("dragging"); });
      });
      host.querySelectorAll("[data-drop]").forEach((zone) => {
        const gi = Number(zone.dataset.drop);
        const indexAt = (y) => {
          const items = [...zone.querySelectorAll(".sbe-item:not(.dragging)")];
          const at = items.findIndex((it) => { const r = it.getBoundingClientRect(); return y < r.top + r.height / 2; });
          return at === -1 ? items.length : at;
        };
        zone.addEventListener("dragover", (ev) => {
          if (!dragging) return;
          ev.preventDefault();
          zone.classList.add("over");
        });
        zone.addEventListener("dragleave", (ev) => { if (!zone.contains(ev.relatedTarget)) zone.classList.remove("over"); });
        zone.addEventListener("drop", (ev) => {
          ev.preventDefault();
          zone.classList.remove("over");
          if (!dragging) return;
          move(dragging, gi, indexAt(ev.clientY));
        });
      });
      host.querySelectorAll("[data-show]").forEach((b) => b.onclick = () => {
        const sid = b.dataset.show;
        const home = byId.get(sid).home;
        const gi = Math.max(0, groups.findIndex((g) => g.id === home));
        move(sid, gi, groups[gi].sections.length);
      });
      host.querySelectorAll("[data-act]").forEach((b) => b.onclick = async () => {
        b.disabled = true;
        try {
          await actions[Number(b.dataset.act)].run({
            groups: groups.map((g) => ({ id: g.id, label: g.label.trim(), sections: g.sections })),
            hidden,
          });
        } finally { b.disabled = false; }
      });
    };

    draw();
  }

  return { editor };
};
