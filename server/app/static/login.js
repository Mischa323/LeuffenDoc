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
      const go = async () => {
        const email = $("dev-email").value.trim();
        if (!email) return;
        const res = await fetch("/auth/dev-login", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email }),
        });
        if (res.ok) { location.href = "/"; return; }
        const body = await res.json().catch(() => ({}));
        note("warn", "Aanmelden lukte niet", body.detail || "Onbekende fout");
      };
      $("btn-dev").onclick = go;
      $("dev-email").addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    }
    if (!html) {
      note("warn", "Nog geen aanmeldmethode ingesteld",
           "Stel <code>DOC_RMM_URL</code> met een API-sleutel in, of een Microsoft 365-app-registratie.");
    }
  });
})();
