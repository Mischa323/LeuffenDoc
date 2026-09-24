/* Kluis — the passwords of every customer at once, for an administrator.

   Four questions, each with its own list: what is due to be replaced, what is
   the same password in more than one place, what is weak, and what has not
   changed in a long time. None of it opens the vault: how strong a password is
   and a fingerprint to compare it by are worked out when it is stored. What
   was stored before that is judged once, on request, and that is in the log. */
window.DocVault = function (ctx) {
  "use strict";

  const { api, esc, toast, go } = ctx;

  const plural = (n, one, more) => `${n} ${n === 1 ? one : more}`;

  function ago(days) {
    if (days < 60) return plural(days, "dag", "dagen");
    const months = Math.round(days / 30.4);
    if (months < 24) return plural(months, "maand", "maanden");
    return plural(Math.floor(days / 365), "jaar", "jaar");
  }

  function changedText(days) {
    if (days === 0) return "vandaag gewijzigd";
    if (days === 1) return "gisteren gewijzigd";
    return `${ago(days)} geleden gewijzigd`;
  }

  function rotateText(days) {
    if (days < 0) return `${ago(-days)} over tijd`;
    if (days === 0) return "vandaag";
    return `over ${plural(days, "dag", "dagen")}`;
  }

  // One password: whose it is, what it is, and why it is on this list.
  function row(e, end) {
    const what = e.field === "main" ? "" : `<span class="muted">${esc(e.field_label)}</span>`;
    return `<div class="vault-row" data-org="${esc(e.org_id)}" data-item="${esc(e.item_id)}">
        <span class="vr-org">${esc(e.org_name)}</span>
        <span class="vr-name">${esc(e.name)}</span>
        ${e.kind === "password" ? "" : `<span class="muted">${esc(e.kind_label)}</span>`}
        ${what}
        <span class="vr-end">${end}</span>
      </div>`;
  }

  function section(id, title, sub, body, empty) {
    return `<div class="panel vault-sec" id="vs-${id}">
        <div class="panel-head"><h2>${esc(title)}</h2><span class="sub">${sub}</span></div>
        ${body || `<div class="vault-none">${ICON.check} ${empty}</div>`}
      </div>`;
  }

  // `tone` colours a tile only when there is something on its list.
  function tile(id, icon, n, label, tone) {
    return `<div class="orgcard vault-tile${n ? ` ${tone}` : ""}" data-jump="${id}">
        <div class="oc-head"><span class="oc-mark">${ICON[icon]}</span>
          <div><h3>${n}</h3><small>${esc(label)}</small></div></div></div>`;
  }

  function grades(d) {
    const g = d.grades;
    const total = Math.max(d.total, 1);
    const part = (n, cls) => n ? `<span class="${cls}" style="width:${(n / total) * 100}%"></span>` : "";
    return `<div class="panel vault-sum">
        <div class="vs-line"><b>${plural(d.total, "wachtwoord", "wachtwoorden")}</b>
          <span class="muted">in gebruik, bij alle klanten</span></div>
        <div class="vault-grades">${part(g.sterk, "g-ok")}${part(g.matig, "g-mid")}${part(g.zwak, "g-bad")}${part(d.unjudged, "g-none")}</div>
        <div class="vs-legend">
          <span><i class="g-ok"></i>${g.sterk} sterk</span>
          <span><i class="g-mid"></i>${g.matig} matig</span>
          <span><i class="g-bad"></i>${g.zwak} zwak</span>
          ${d.unjudged ? `<span><i class="g-none"></i>${d.unjudged} niet beoordeeld</span>` : ""}
        </div></div>`;
  }

  function judgeCallout(d) {
    if (!d.unjudged) return "";
    return `<div class="callout info" style="margin-bottom:16px"><div class="ic">${ICON.info}</div>
        <div style="flex:1"><div class="ct">${plural(d.unjudged, "wachtwoord is", "wachtwoorden zijn")} nog niet beoordeeld</div>
          <div class="cd">Ze zijn opgeslagen voordat LeuffenDoc dat bij het opslaan deed, dus ze tellen
            hieronder niet mee. Beoordelen opent ze één keer op de server om sterkte en hergebruik vast
            te stellen. Er gaat niets naar je browser, en het komt als één regel in het logboek.</div>
          <button class="btn sm" id="vault-judge" style="margin-top:10px">${ICON.shield} Nu beoordelen</button>
        </div></div>`;
  }

  async function view(host) {
    const d = await api("/api/vault/overview");
    const reusedCount = d.reused.reduce((n, g) => n + g.count, 0);

    const rotate = d.rotate.map((e) => row(e,
      `<span class="muted">${new Date(e.rotate_at).toLocaleDateString("nl-NL")}</span>
       <span class="tag ${e.rotate_days < 0 ? "bad" : "warn"}">${esc(rotateText(e.rotate_days))}</span>`)).join("");

    const reused = d.reused.map((g) => `<div class="vault-group">
        <div class="vg-head">Hetzelfde wachtwoord op ${g.count} plaatsen${
          g.customers > 1 ? `, bij <b>${g.customers} klanten</b>` : ""}</div>
        ${g.items.map((e) => row(e, `<span class="muted">${esc(changedText(e.age_days))}</span>`)).join("")}
      </div>`).join("");

    const weak = d.weak.map((e) => row(e, `<span class="tag bad">zwak</span>`)).join("");

    const old = d.old.map((e) => row(e,
      `<span class="muted">${e.updated_by ? `door ${esc(e.updated_by)}` : ""}</span>
       <span class="tag warn">${esc(ago(e.age_days))} niet gewijzigd</span>`)).join("");

    const ageSub = d.max_age_days
      ? `Niet gewijzigd in ${plural(d.max_age_days, "dag", "dagen")} of langer — in te stellen onder Instellingen`
      : "Staat uit — in te stellen onder Instellingen";

    host.innerHTML = judgeCallout(d) + grades(d) + `
      <div class="cards vault-tiles">
        ${tile("rotate", "clock", d.rotate.length, "te vervangen", "bad")}
        ${tile("reused", "copy", reusedCount, "hergebruikt", "bad")}
        ${tile("weak", "alert", d.weak.length, "zwak", "bad")}
        ${tile("old", "history", d.old.length, "lang niet gewijzigd", "warn")}
      </div>`
      + section("rotate", "Te vervangen",
        `Waar <b>Vervangen vóór</b> verstreken is, of binnen ${plural(d.warn_days, "dag", "dagen")} valt`,
        rotate, "Niets dat vervangen moet.")
      + section("reused", "Hergebruikt",
        "Hetzelfde wachtwoord op meer dan één plek: lekt het er één, dan lekken ze allemaal",
        reused, "Geen wachtwoord staat op twee plaatsen.")
      + section("weak", "Zwak",
        "Te kort, te weinig variatie, of een bekend woord met cijfers erachter",
        weak, "Geen zwakke wachtwoorden.")
      + section("old", "Lang niet gewijzigd", esc(ageSub),
        old, d.max_age_days ? "Alles is recent genoeg gewijzigd." : "Er wordt niet op leeftijd gecontroleerd.");

    host.querySelectorAll(".vault-row").forEach((el) => {
      el.onclick = () => go(`#/klant/${el.dataset.org}/item/${el.dataset.item}`);
    });
    host.querySelectorAll("[data-jump]").forEach((el) => {
      el.onclick = () => host.querySelector(`#vs-${el.dataset.jump}`)
        .scrollIntoView({ behavior: "smooth", block: "start" });
    });
    const judge = host.querySelector("#vault-judge");
    if (judge) {
      judge.onclick = async () => {
        judge.disabled = true;
        try {
          const res = await api("/api/vault/judge", { method: "POST" });
          toast(`${plural(res.done, "wachtwoord", "wachtwoorden")} beoordeeld`
            + (res.failed ? `, ${res.failed} niet te openen` : ""));
          await view(host);
        } catch (e) {
          judge.disabled = false;
          toast(e.message);
        }
      };
    }
  }

  return { view };
};
