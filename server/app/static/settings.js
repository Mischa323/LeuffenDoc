/* Instellingen — what an administrator can change without touching the
   container.

   Each block saves on its own, so changing the generator cannot accidentally
   send a half-typed RMM address with it. A value fixed in the container's
   environment is shown but not offered, with the reason next to it: a field
   that silently ignores what you type is worse than one that says why. */
window.DocSettings = function (ctx) {
  "use strict";

  const { api, esc, toast } = ctx;
  let data = null;

  const S = (key) => data.settings[key];
  const fixedNote = (key) => S(key).from_env
    ? `<div class="hint env-note">${ICON.lock} Vastgezet via <code>${esc(key)}</code> in de omgeving van de container.</div>`
    : "";

  // ---- one field ----
  function field(key, label, opts = {}) {
    const s = S(key);
    const disabled = s.from_env ? " disabled" : "";
    let control;
    if (s.type === "bool") {
      control = `<label class="boolrow"><input type="checkbox" data-set="${key}"${
        s.value ? " checked" : ""}${disabled} /> <span>${esc(opts.check || "Aan")}</span></label>`;
    } else if (s.type === "secret") {
      control = `<input class="inp mono" type="password" data-set="${key}" autocomplete="new-password"
        placeholder="${s.set ? `ingesteld ${esc(s.hint)} — laat leeg om te houden` : "nog niet ingesteld"}"${disabled} />
        ${s.set && !s.from_env ? `<label class="boolrow clear-row"><input type="checkbox" data-clear="${key}" />
          <span>Weghalen</span></label>` : ""}`;
    } else if (s.type === "int") {
      control = `<input class="inp" type="number" data-set="${key}" value="${esc(s.value)}"
        min="${s.min ?? ""}" max="${s.max ?? ""}" style="max-width:140px"${disabled} />`;
    } else {
      control = `<input class="inp${s.type === "url" || opts.mono ? " mono" : ""}" data-set="${key}"
        value="${esc(s.value ?? "")}" placeholder="${esc(opts.placeholder || "")}"${disabled} />`;
    }
    return `<div class="frow"><label>${esc(label)}</label>${control}
        ${opts.hint ? `<div class="hint">${opts.hint}</div>` : ""}${fixedNote(key)}</div>`;
  }

  function block(id, title, sub, body, foot) {
    return `<div class="panel form-block" id="blk-${id}">
        <div class="panel-head"><h2>${title}</h2>${sub ? `<span class="sub">${sub}</span>` : ""}</div>
        <div class="form-body">${body}</div>
        ${foot === false ? "" : `<div class="blk-foot">${foot || ""}
          <div style="flex:1"></div>
          <button class="btn sm" data-save="${id}">${ICON.save} Opslaan</button></div>`}
      </div>`;
  }

  // ---- the blocks ----
  function aboutBlock() {
    return `<div class="panel form-block" id="blk-over">
        <div class="panel-head"><h2>Over deze server</h2>
          <span class="sub">Versie en bijwerken</span></div>
        <div class="form-body">
          <div class="frow"><label>Versie</label>
            <div class="ver-pill mono">${ICON.server} v${esc(data.version)}</div></div>
          <div class="frow"><label>Bijwerken</label><div id="upd">Controleren…</div></div>
        </div></div>`;
  }

  function generalBlock() {
    return block("algemeen", "Algemeen", "",
      field("DOC_PUBLIC_URL", "Openbaar adres", {
        placeholder: "https://doc.jouwdomein.nl",
        hint: "Het adres waarop mensen binnenkomen. Aanmelden via de RMM en Microsoft 365 stuurt hiernaartoe terug.",
      })
      + field("EXPIRY_WARN_DAYS", "Waarschuwen vanaf", {
        hint: "Zoveel dagen voordat een garantie, contract of vervaldatum afloopt, staat het bovenaan het klantoverzicht.",
      }));
  }

  function rmmBlock() {
    const current = S("DOC_RMM_PUBLIC_URL").value || S("DOC_RMM_URL").value || "";
    return block("rmm", "Koppeling met de RMM",
      "Aanmelden, klanten en apparaten komen hiervandaan",
      `<div class="frow"><label>Koppelen met één knop</label>
         <div class="pair-row"><input class="inp mono" id="pair-url" value="${esc(current)}" placeholder="https://rmm.jouwdomein.nl" />
           <button class="btn sm" id="pair-go" type="button">${ICON.link} Koppelen</button></div>
         <div class="hint">De RMM vraagt je om het goed te keuren en regelt de API-sleutel en zijn eigen kant zelf.
           Alleen nodig om opnieuw te koppelen, of met een andere RMM — de velden hieronder zijn voor handwerk.</div></div>`
      + field("DOC_RMM_URL", "Adres van de RMM", {
        placeholder: "https://rmm.jouwdomein.nl",
        hint: "Waar deze server de RMM bereikt. Achter dezelfde proxy mag dat een intern adres zijn.",
      })
      + field("DOC_RMM_PUBLIC_URL", "Adres voor de browser", {
        placeholder: "Leeg = hetzelfde als hierboven",
        hint: "Alleen nodig als de browser de RMM op een ander adres bereikt dan deze server.",
      })
      + field("DOC_RMM_API_KEY", "API-sleutel", {
        hint: "Te maken in de RMM onder <b>Instellingen → API &amp; webhooks</b>, zonder organisatie. Wordt versleuteld bewaard en nooit meer getoond.",
      })
      + field("DOC_SYNC_MINUTES", "Bijwerken elke (minuten)")
      + field("DOC_RMM_INSECURE_TLS", "Certificaat", {
        check: "Een zelfondertekend certificaat van de RMM accepteren",
        hint: "Alleen voor een RMM op het eigen netwerk zonder geldig certificaat.",
      }),
      `<button class="btn ghost sm" id="rmm-test" title="Test met wat er is opgeslagen">${ICON.refresh} Verbinding testen</button>
       <span id="rmm-test-out" class="test-out"></span>`);
  }

  function m365Block() {
    return block("m365", "Aanmelden met Microsoft 365",
      "De tweede weg naar binnen, voor als de RMM niet bereikbaar is",
      field("DOC_M365_TENANT", "Tenant-id", { mono: true, placeholder: "xxxxxxxx-xxxx-…" })
      + field("DOC_M365_CLIENT_ID", "Client-id", { mono: true, placeholder: "xxxxxxxx-xxxx-…" })
      + field("DOC_M365_CLIENT_SECRET", "Clientgeheim", {
        hint: "Wordt versleuteld bewaard en nooit meer getoond.",
      })
      + field("DOC_M365_ALLOW", "Toegestaan", {
        placeholder: "leuffen.nl, iemand@elders.nl",
        hint: "Domeinen of adressen, met komma's ertussen. Leeg laat iedereen uit de tenant toe.",
      })
      + `<div class="frow"><label>Redirect-URI</label>
          <div class="code mono">${esc(data.m365_redirect || "stel eerst het openbare adres in")}</div>
          <div class="hint">Zet deze in de app-registratie in Entra.</div></div>`);
  }

  function passwordBlock() {
    return block("wachtwoorden", "Wachtwoorden", "Hoe de knop Genereer ze maakt, en wanneer ze aan vervanging toe zijn",
      `<div class="tf-grid">
         ${field("PW_LENGTH", "Lengte")}
         ${field("PW_REVEAL_SECONDS", "Zichtbaar na Tonen (seconden)", {
           hint: "Daarna staan er weer bolletjes.",
         })}
         ${field("PW_MAX_AGE_DAYS", "Vervangen na (dagen)", {
           hint: "Langer niet gewijzigd en het staat onder <b>Kluis</b>. 0 is niet op leeftijd letten.",
         })}
       </div>
       <div class="pw-classes">
         ${field("PW_LOWER", "Kleine letters", { check: "a–z" })}
         ${field("PW_UPPER", "Hoofdletters", { check: "A–Z" })}
         ${field("PW_DIGITS", "Cijfers", { check: "0–9" })}
         ${field("PW_SYMBOLS", "Leestekens", { check: "Aan" })}
       </div>
       ${field("PW_SYMBOL_SET", "Welke leestekens", {
         mono: true,
         hint: "Laat tekens weg die een systeem niet accepteert — sommige routers weigeren bijvoorbeeld een aanhalingsteken.",
       })}
       ${field("PW_NO_LOOKALIKES", "Verwarrende tekens", {
         check: "Geen l, I, O, 0 of 1 — die lees je verkeerd van een scherm",
       })}
       ${field("PW_EACH_CLASS", "Van elke soort", {
         check: "Minstens één teken van elke soort die aan staat",
         hint: "Zodat een wachtwoord altijd aan een eis als ‘minstens één cijfer’ voldoet, niet meestal.",
       })}
       <div class="frow"><label>Voorbeeld</label>
         <div class="pw-sample"><span class="mono" id="pw-sample"></span>
           <button class="btn ghost sm" id="pw-again">${ICON.refresh} Nog een</button></div>
         <div class="hint">Met wat hierboven staat, ook als het nog niet is opgeslagen.</div></div>`);
  }

  function vaultBlock() {
    const v = data.vault;
    const where = v.from_environment
      ? `<div class="callout info"><div class="ic">${ICON.lock}</div><div>
           <div class="ct">De sleutel komt uit de omgeving</div>
           <div class="cd">Via <code>DOC_SECRET_KEY</code>, dus niet in de database. Een back-up van het datavolume bevat de kluis, maar niet de sleutel om hem te openen.</div></div></div>`
      : `<div class="callout warn"><div class="ic">${ICON.alert}</div><div>
           <div class="ct">De sleutel staat in de database</div>
           <div class="cd">Een back-up van het datavolume bevat dan zowel de kluis als de sleutel. Zet <code>DOC_SECRET_KEY</code> in de omgeving — vóórdat de kluis gevuld wordt, want met een andere sleutel gaan bestaande wachtwoorden niet meer open.</div></div></div>`;
    return `<div class="panel form-block">
        <div class="panel-head"><h2>Kluis</h2>
          <span class="sub">Niet te wijzigen vanaf deze pagina — een andere sleutel maakt alles onleesbaar</span></div>
        <div class="form-body" style="padding-bottom:16px">${where}</div></div>`;
  }

  /* Back-ups: snapshots in the data volume, one to take away (always
     encrypted), and putting one back. Putting back is two steps on purpose --
     choosing it, then saying yes to what it will replace. */
  function backupBlock() {
    return block("backup", "Back-ups", "Momentopnamen in het datavolume, en een versleutelde kopie om mee te nemen",
      `<div class="tf-grid">
         ${field("DOC_BACKUP_HOURS", "Automatisch, elke (uur)", {
           hint: "0 is uit. Ook na een herstart loopt dit gewoon door.",
         })}
         ${field("DOC_BACKUP_KEEP", "Automatische bewaren", {
           hint: "De oudste gaan weg. Handmatige en geüploade blijven tot je ze verwijdert.",
         })}
       </div>
       <div id="bk-list" class="bk-list"><span class="muted">Laden…</span></div>`,
      `<button class="btn ghost sm" id="bk-make">${ICON.plus} Nu een back-up maken</button>
       <button class="btn ghost sm" id="bk-upload">${ICON.upload} Back-up uploaden…</button>`);
  }

  const size = (n) => n >= 1048576 ? `${(n / 1048576).toFixed(1).replace(".", ",")} MB`
    : `${Math.max(1, Math.round(n / 1024))} kB`;
  const when = (t) => new Date(t * 1000).toLocaleString("nl-NL", { dateStyle: "medium", timeStyle: "short" });

  async function drawBackups(host) {
    const slot = host.querySelector("#bk-list");
    if (!slot) return;
    let d;
    try { d = await api("/api/admin/backups"); }
    catch (e) { slot.innerHTML = `<span class="muted">${esc(e.message)}</span>`; return; }
    const keyNote = d.key && d.key.in_database
      ? `<div class="callout warn" style="margin:4px 0 12px"><div class="ic">${ICON.alert}</div><div>
           <div class="cd">De sleutel van de kluis staat in de database, dus elke back-up bevat hem ook.
             Een gedownloade back-up is daarom altijd versleuteld met een wachtwoordzin — bewaar die
             ergens anders dan het bestand.</div></div></div>` : "";
    const failed = d.last_auto && d.last_auto.ok === false
      ? `<div class="callout warn" style="margin:4px 0 12px"><div class="ic">${ICON.alert}</div><div>
           <div class="ct">De laatste automatische back-up is mislukt</div>
           <div class="cd">${esc(d.last_auto.detail)}</div></div></div>` : "";
    const rows = d.backups.map((b) => `
        <tr data-name="${esc(b.name)}">
          <td>${esc(when(b.made_at))}</td>
          <td><span class="tag${b.kind === "voor-terugzetten" ? " warn" : ""}">${esc(b.label)}</span></td>
          <td class="muted">${b.customers ?? "?"} klanten · ${b.items ?? "?"} items · ${b.passwords ?? "?"} wachtwoorden</td>
          <td class="muted">${size(b.size)}</td>
          <td class="bk-actions">
            <button class="btn ghost sm" data-bk="download">${ICON.download} Downloaden</button>
            <button class="btn ghost sm" data-bk="restore">${ICON.history} Terugzetten</button>
            <button class="btn ghost sm" data-bk="delete" title="Verwijderen">${ICON.trash}</button>
          </td></tr>
        <tr class="bk-form hidden" data-form="${esc(b.name)}"><td colspan="5"></td></tr>`).join("");
    const upload = `<div class="bk-inline bk-up hidden" id="bk-up">
        <input type="file" id="bk-file" accept=".ldbak,.db" class="inp" />
        <input class="inp" type="password" id="bk-up-pass" placeholder="Wachtwoordzin van het bestand" autocomplete="off" />
        <button class="btn sm" id="bk-up-go">${ICON.upload} Uploaden en controleren</button>
        <div class="hint" style="flex-basis:100%;margin:0">Het bestand wordt gecontroleerd en klaargezet.
          Terugzetten is daarna een aparte stap.</div></div>`;
    slot.innerHTML = keyNote + failed + upload + (d.backups.length
      ? `<table class="grid bk-table"><thead><tr><th>Gemaakt</th><th>Soort</th><th>Inhoud</th>
          <th>Grootte</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
      : `<div class="muted" style="padding:6px 0">Nog geen back-ups.</div>`)
      + `<div class="hint" style="margin-top:8px">Ze staan in <code>${esc(d.folder)}</code>, dus een back-up
          van het datavolume neemt ze mee — als bestanden die heel zijn, ook als de server draaide.</div>`;
    wireBackups(host, d);
    wireUpload(host);
  }

  function formOf(host, name) {
    host.querySelectorAll(".bk-form").forEach((tr) => {
      if (tr.dataset.form !== name) { tr.classList.add("hidden"); tr.firstElementChild.innerHTML = ""; }
    });
    const tr = host.querySelector(`.bk-form[data-form="${CSS.escape(name)}"]`);
    tr.classList.remove("hidden");
    return tr.firstElementChild;
  }

  function wireBackups(host, d) {
    host.querySelectorAll("[data-bk]").forEach((btn) => {
      const name = btn.closest("tr").dataset.name;
      const b = d.backups.find((x) => x.name === name);
      btn.onclick = async () => {
        const what = btn.dataset.bk;
        if (what === "delete") {
          try {
            await api(`/api/admin/backups/${encodeURIComponent(name)}`, { method: "DELETE" });
            toast("Back-up verwijderd");
            drawBackups(host);
          } catch (e) { toast(e.message); }
          return;
        }
        const cell = formOf(host, name);
        if (what === "download") {
          cell.innerHTML = `<div class="bk-inline">
              <input class="inp" type="password" id="bk-pass" placeholder="Wachtwoordzin, 12+ tekens" autocomplete="new-password" />
              <input class="inp" type="password" id="bk-pass2" placeholder="Nog een keer" autocomplete="new-password" />
              <button class="btn sm" id="bk-go">${ICON.download} Versleuteld downloaden</button>
              <div class="hint" style="flex-basis:100%;margin:0">Zonder deze wachtwoordzin gaat de back-up niet
                meer open, ook niet door ons. Bewaar hem ergens anders dan het bestand.</div></div>`;
          cell.querySelector("#bk-pass").focus();
          cell.querySelector("#bk-go").onclick = async (ev) => {
            const go = ev.currentTarget;
            const pass = cell.querySelector("#bk-pass").value;
            if (pass !== cell.querySelector("#bk-pass2").value) { toast("De twee wachtwoordzinnen verschillen"); return; }
            go.disabled = true;
            try {
              const res = await fetch(`/api/admin/backups/${encodeURIComponent(name)}/download`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ passphrase: pass }),
              });
              if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `${res.status}`);
              const file = (res.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/);
              const url = URL.createObjectURL(await res.blob());
              const a = document.createElement("a");
              a.href = url;
              a.download = file ? file[1] : "leuffendoc.ldbak";
              document.body.appendChild(a);
              a.click();
              a.remove();
              setTimeout(() => URL.revokeObjectURL(url), 5000);
              cell.closest("tr").classList.add("hidden");
              toast("Gedownload — versleuteld");
            } catch (e) { toast(e.message); go.disabled = false; }
          };
        }
        if (what === "restore") {
          cell.innerHTML = `<div class="callout warn" style="margin:0"><div class="ic">${ICON.alert}</div><div style="flex:1">
              <div class="ct">Alles terugzetten naar ${esc(when(b.made_at))}?</div>
              <div class="cd">Alle documentatie, wachtwoorden, klanten en het logboek worden vervangen door wat in
                deze back-up staat: ${b.customers ?? "?"} klanten, ${b.items ?? "?"} items, ${b.passwords ?? "?"} wachtwoorden.
                Wat daarna is veranderd, is dan weg — maar de huidige stand wordt eerst zelf als back-up
                bewaard, dus dit is terug te draaien.</div>
              <div style="margin-top:10px;display:flex;gap:8px">
                <button class="btn sm danger" id="bk-yes">Ja, terugzetten</button>
                <button class="btn ghost sm" id="bk-no">Annuleren</button></div></div></div>`;
          cell.querySelector("#bk-no").onclick = () => cell.closest("tr").classList.add("hidden");
          cell.querySelector("#bk-yes").onclick = async (ev) => {
            ev.currentTarget.disabled = true;
            try {
              await api(`/api/admin/backups/${encodeURIComponent(name)}/restore`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ confirm: name }),
              });
              toast("Teruggezet — de pagina wordt opnieuw geladen");
              setTimeout(() => location.reload(), 1200);
            } catch (e) { toast(e.message); drawBackups(host); }
          };
        }
      };
    });
  }

  function wireBackupButtons(host) {
    const make = host.querySelector("#bk-make");
    make.onclick = async () => {
      make.disabled = true;
      try {
        await api("/api/admin/backups", { method: "POST" });
        toast("Back-up gemaakt");
        await drawBackups(host);
      } catch (e) { toast(e.message); }
      make.disabled = false;
    };
    host.querySelector("#bk-upload").onclick = () => {
      const form = host.querySelector("#bk-up");
      if (form) form.classList.toggle("hidden");
    };
  }

  // A file of ours needs its passphrase; a plain database taken off the volume
  // by hand needs none, and the field is simply left empty.
  function wireUpload(host) {
    const go = host.querySelector("#bk-up-go");
    if (!go) return;
    go.onclick = async () => {
      const file = host.querySelector("#bk-file").files[0];
      if (!file) { toast("Kies eerst een bestand"); return; }
      go.disabled = true;
      toast("Uploaden en controleren…");
      try {
        const got = await api("/api/admin/backups/upload", {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream",
                     // A header carries Latin-1 only; a passphrase with a € in it must still arrive.
                     "X-Backup-Passphrase": encodeURIComponent(host.querySelector("#bk-up-pass").value) },
          body: file,
        });
        toast(`Gecontroleerd en klaargezet: ${got.customers} klanten, ${got.items} items`);
        await drawBackups(host);
      } catch (e) { toast(e.message); go.disabled = false; }
    };
  }

  /* Who gets in, and through what. Set on the first start; changed here.
     Careful with these: they decide whether this page can still be reached. */
  function accessBlock() {
    const e = data.environment;
    const dev = e.DOC_DEV_LOGIN
      ? `<div class="callout warn" style="margin-bottom:12px"><div class="ic">${ICON.alert}</div><div>
           <div class="cd">Aanmelden zonder wachtwoord (<code>DOC_DEV_LOGIN</code>) staat aan. Alleen voor
             ontwikkeling — nooit op een server die anderen kunnen bereiken.</div></div></div>` : "";
    return block("toegang", "Toegang", "De reverse proxy, cookies en wie altijd beheerder is",
      dev
      + field("DOC_TRUST_PROXY", "Reverse proxy", {
        check: "Er zit een reverse proxy voor deze server",
        hint: "Dan wordt het adres van de bezoeker uit <code>X-Forwarded-For</code> gehaald in plaats van dat van de proxy.",
      })
      + field("DOC_PROXY_IPS", "Adres van de proxy", {
        mono: true, placeholder: "172.20.0.1",
        hint: "Alleen verbindingen vanaf dit adres (of bereik, met komma's) mogen zeggen wie de bezoeker is. Het <b>Logboek</b> laat zien vanaf welk adres je proxy binnenkomt.",
      })
      + field("DOC_SECURE_COOKIES", "Cookies", {
        check: "Alleen over https versturen",
        hint: "Uit alleen als LeuffenDoc zonder https wordt gebruikt — anders lukt aanmelden niet meer.",
      })
      + field("DOC_BOOTSTRAP_ADMIN", "Altijd beheerder", {
        placeholder: "naam@bedrijf.nl, …",
        hint: "Deze adressen zijn beheerder, wat de RMM ook zegt: de weg terug naar binnen als niemand anders het meer is.",
      })
      + field("DOC_SESSION_DAYS", "Aangemeld blijven (dagen)"));
  }

  // ---- saving a block ----
  function collect(root) {
    const out = {};
    const clear = [];
    root.querySelectorAll("[data-set]").forEach((el) => {
      if (el.disabled) return;
      const key = el.dataset.set;
      out[key] = el.type === "checkbox" ? el.checked : el.value.trim();
    });
    root.querySelectorAll("[data-clear]").forEach((el) => {
      if (el.checked) clear.push(el.dataset.clear);
    });
    if (clear.length) out.clear = clear;
    return out;
  }

  async function save(id, host) {
    const root = host.querySelector(`#blk-${id}`);
    const btn = root.querySelector("[data-save]");
    btn.disabled = true;
    try {
      const result = await api("/api/admin/settings", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(collect(root)),
      });
      data.settings = result.settings;
      toast(result.saved.length ? "Opgeslagen" : "Er was niets veranderd");
      await ctx.reloadConfig();
      paint(host);
    } catch (e) {
      toast(e.message);
      btn.disabled = false;
    }
  }

  // ---- the password example follows the form, saved or not ----
  function sample(host) {
    const root = host.querySelector("#blk-wachtwoorden");
    if (!root) return;
    const cfg = collect(root);
    const out = host.querySelector("#pw-sample");
    const kinds = ["PW_LOWER", "PW_UPPER", "PW_DIGITS", "PW_SYMBOLS"].filter((k) => cfg[k]);
    if (!kinds.length) { out.textContent = "kies minstens één soort teken"; return; }
    out.textContent = window.makePassword(cfg);
  }

  // ---- updating ----
  async function drawUpdate(host, st) {
    const slot = host.querySelector("#upd");
    if (!slot) return;
    if (!st) {
      try { st = await api("/api/admin/update"); }
      catch (e) { slot.innerHTML = `<span class="muted">${esc(e.message)}</span>`; return; }
    }
    if (!st.available) {
      slot.innerHTML = `<div class="upd-row"><span class="tag">niet beschikbaar</span>
          <span class="hint" style="margin:0">Hier kan het niet: ${esc(st.reason)}.</span></div>
        <div class="hint">Koppel <code>/var/run/docker.sock</code> aan de container en draai hem vanaf
          <span class="mono">ghcr.io/mischa323/leuffendoc:latest</span>, dan kan het met één knop.
          Tot die tijd: het image opnieuw ophalen en de container opnieuw starten.</div>`;
      return;
    }
    const staged = st.update_staged;
    slot.innerHTML = `<div class="upd-row">
        ${staged
          ? `<span class="tag ok">${st.waiting_version ? `v${esc(st.waiting_version)} staat klaar` : "nieuwe versie staat klaar"}</span>`
          : `<span class="tag">bijgewerkt</span>`}
        <button class="btn ghost sm" id="upd-check">${ICON.refresh} Controleren</button>
        <button class="btn sm" id="upd-apply"${staged ? "" : " disabled"}>${ICON.download} Bijwerken en herstarten</button>
      </div>
      <div class="hint">Image <span class="mono">${esc(st.image)}</span></div>
      <div id="upd-confirm"></div>`;

    slot.querySelector("#upd-check").onclick = async (ev) => {
      const b = ev.currentTarget;
      b.disabled = true; b.textContent = "Ophalen…";
      try {
        const r = await api("/api/admin/update/check", { method: "POST" });
        toast(r.update_staged ? "Er staat een nieuwe versie klaar" : "Dit is de nieuwste versie");
        drawUpdate(host, r);
      } catch (e) { toast(e.message); b.disabled = false; b.innerHTML = `${ICON.refresh} Controleren`; }
    };

    // Asked on the page, not in a browser dialog: those get refused outright
    // and would leave a button that seems to do nothing.
    slot.querySelector("#upd-apply").onclick = () => {
      const box = slot.querySelector("#upd-confirm");
      box.innerHTML = `<div class="callout warn" style="margin-top:12px"><div class="ic">${ICON.alert}</div>
        <div style="flex:1"><div class="ct">Nu bijwerken?</div>
          <div class="cd">LeuffenDoc is een halve minuut weg terwijl de container opnieuw start. Lukt het
            niet, dan wordt de huidige versie teruggezet.</div>
          <div style="display:flex;gap:8px;margin-top:10px">
            <button class="btn sm" id="upd-go">Ja, bijwerken</button>
            <button class="btn ghost sm" id="upd-no">Annuleren</button></div></div></div>`;
      box.querySelector("#upd-no").onclick = () => { box.innerHTML = ""; };
      box.querySelector("#upd-go").onclick = async (ev) => {
        ev.currentTarget.disabled = true;
        try {
          await api("/api/admin/update/apply", { method: "POST" });
          waitForNewVersion(slot, data.version);
        } catch (e) { toast(e.message); box.innerHTML = ""; }
      };
    };
  }

  /* The old server keeps answering for a few seconds after the button, so a
     reload on the first answer would land on the version you just left. Wait
     until the version has changed, or until the server has been gone and is
     back. */
  function waitForNewVersion(slot, before) {
    slot.innerHTML = `<div class="callout info"><div class="ic">${ICON.refresh}</div><div>
        <div class="ct">Bezig met bijwerken…</div>
        <div class="cd" id="upd-progress">Het nieuwe image wordt gestart. Deze pagina laadt vanzelf opnieuw.</div></div></div>`;
    let wentAway = false;
    const started = Date.now();
    const tick = async () => {
      let now = null;
      try {
        const r = await fetch("/health", { cache: "no-store" });
        if (r.ok) now = (await r.json()).version;
      } catch (e) { /* on its way down or back up */ }
      if (now === null) wentAway = true;
      if (now && now !== before) {
        toast(`Bijgewerkt naar v${now}`);
        setTimeout(() => location.reload(), 900);
        return;
      }
      if (now && wentAway) {
        // Back, but on the same version: either nothing newer was in the image
        // after all, or the new version did not come up and the previous one
        // was put back. The newer image still waiting tells the two apart.
        let st = null;
        try { st = await api("/api/admin/update"); } catch (e) { /* treat as unknown */ }
        if (st && st.update_staged) {
          slot.innerHTML = `<div class="callout warn"><div class="ic">${ICON.alert}</div><div>
            <div class="ct">Bijwerken is mislukt — de vorige versie draait weer</div>
            <div class="cd">De nieuwe versie${st.waiting_version ? ` (v${esc(st.waiting_version)})` : ""}
              startte niet goed, dus v${esc(before)} is teruggezet. Er is niets verloren gegaan.
              De logboeken van de container zeggen waarom.</div></div></div>`;
          return;
        }
        toast("De server is terug");
        setTimeout(() => location.reload(), 900);
        return;
      }
      if (Date.now() - started > 180000) {
        const p = slot.querySelector("#upd-progress");
        if (p) p.innerHTML = "Het duurt langer dan verwacht. Kijk naar de container — als de "
          + "nieuwe versie niet goed start, wordt de vorige binnen anderhalve minuut teruggezet.";
        return;
      }
      setTimeout(tick, 2000);
    };
    setTimeout(tick, 2500);
  }

  // ---- the page ----
  function paint(host) {
    host.innerHTML = `<div class="settings-grid">
        ${aboutBlock()}${generalBlock()}${rmmBlock()}${m365Block()}
        ${passwordBlock()}${vaultBlock()}${backupBlock()}${accessBlock()}
      </div>`;
    host.querySelectorAll("[data-save]").forEach((b) => {
      b.onclick = () => save(b.dataset.save, host);
    });
    const pw = host.querySelector("#blk-wachtwoorden");
    pw.addEventListener("input", () => sample(host));
    pw.addEventListener("change", () => sample(host));
    host.querySelector("#pw-again").onclick = () => sample(host);
    sample(host);

    host.querySelector("#rmm-test").onclick = async (ev) => {
      // Held on to: after an await the event no longer knows its target, and
      // the button would stay disabled for good.
      const button = ev.currentTarget;
      const out = host.querySelector("#rmm-test-out");
      button.disabled = true;
      out.textContent = "Testen…";
      out.className = "test-out";
      try {
        const r = await api("/api/admin/rmm-test", { method: "POST" });
        out.textContent = r.detail;
        out.className = `test-out ${r.ok ? "good" : "bad"}`;
      } catch (e) { out.textContent = e.message; out.className = "test-out bad"; }
      button.disabled = false;
    };
    drawUpdate(host);
    wireBackupButtons(host);
    host.querySelector("#pair-go").onclick = async (ev) => {
      const button = ev.currentTarget;
      button.disabled = true;
      try {
        const r = await api("/api/admin/pair", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rmm_url: host.querySelector("#pair-url").value.trim() }),
        });
        location.href = r.redirect;
      } catch (e) { toast(e.message); button.disabled = false; }
    };
    drawBackups(host);
  }

  async function view(host) {
    data = await api("/api/admin/settings");
    paint(host);
  }

  return { view };
};
