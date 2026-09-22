/* Sign-in page. Which buttons appear depends on what the server has been given:
   the RMM (the normal way in), Microsoft 365 (the fallback), and a development
   sign-in that only exists when DOC_DEV_LOGIN is set. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  $("mark-logo").innerHTML = ICON.file;

  function note(kind, title, text) {
    $("msg").innerHTML = `<div class="callout ${kind}" style="margin-top:16px">
      <div class="ic">${kind === "warn" ? ICON.alert : ICON.info}</div>
      <div><div class="ct">${title}</div><div class="cd">${text}</div></div></div>`;
  }

  // A sign-in that failed comes back with the reason on the page itself.
  const failure = $("msg").dataset.error;
  if (failure) note("warn", "Aanmelden lukte niet", failure);

  fetch("/api/auth/methods").then((r) => r.json()).then((m) => {
    const host = $("methods");
    let html = "";
    if (m.rmm) {
      html += `<button class="btn" id="btn-rmm">${ICON.shield} Aanmelden met Leuffen RMM</button>`;
    }
    if (m.m365) {
      html += `<button class="btn ${m.rmm ? "ghost" : ""}" id="btn-m365">${ICON.globe} Aanmelden met Microsoft 365</button>`;
    }
    if (m.dev) {
      if (html) html += `<div class="sep">of</div>`;
      html += `<div class="frow"><label>E-mailadres</label>
                 <input class="inp" id="dev-email" type="email" placeholder="jij@leuffen.nl" autocomplete="email" /></div>
               <button class="btn ghost" id="btn-dev" style="margin-top:10px">${ICON.key} Ontwikkelaanmelding</button>`;
    }
    host.innerHTML = html;

    if (m.rmm) $("btn-rmm").onclick = () => { location.href = "/auth/rmm/start"; };
    if (m.m365) $("btn-m365").onclick = () => { location.href = "/auth/m365/start"; };
    if (m.dev) {
      const field = $("dev-email");
      const btn = $("btn-dev");
      const go = async () => {
        const email = field.value.trim();
        if (!email) {
          // Saying nothing here read as a broken button: the placeholder looks
          // like a filled-in address, so a click with an empty field did
          // nothing at all and gave no reason why.
          note("warn", "Vul eerst je e-mailadres in",
               "Het grijze adres is een voorbeeld, geen ingevulde waarde.");
          field.focus();
          return;
        }
        btn.disabled = true;
        try {
          const res = await fetch("/auth/dev-login", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email }),
          });
          if (res.ok) { location.href = "/"; return; }
          const body = await res.json().catch(() => ({}));
          note("warn", "Aanmelden lukte niet", body.detail || `Serverfout ${res.status}`);
        } catch (e) {
          note("warn", "Geen verbinding met de server", String(e.message || e));
        } finally {
          btn.disabled = false;
        }
      };
      btn.onclick = go;
      field.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
      field.focus();
    }
    if (!html) {
      note("warn", "Nog geen aanmeldmethode ingesteld",
           "Stel <code>DOC_RMM_URL</code> met een API-sleutel in, of een Microsoft 365-app-registratie.");
    }
  });
})();
