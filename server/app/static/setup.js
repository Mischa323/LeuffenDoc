/* The first start, and the page linking with the RMM comes back to.

   Set-up asks for the code from the container's log, then for one thing: the
   RMM's address. Everything else is filled in from what the server can see of
   this very request, and can be changed under "Zelf aanpassen". */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  try {
    if (window.matchMedia("(prefers-color-scheme: light)").matches) {
      document.documentElement.dataset.theme = "light";
    }
  } catch (e) { /* keep dark */ }
  $("logo").innerHTML = ICON.file || "";

  const params = new URLSearchParams(location.search);
  let code = "";
  let seen = {};

  async function post(path, body) {
    const res = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body), cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.detail || `${res.status}`);
      err.data = data;
      throw err;
    }
    return data;
  }

  const steps = (n) => `<div class="steps">${[1, 2, 3].map((i) =>
    `<span class="${i <= n ? "on" : ""}"></span>`).join("")}</div>`;

  // ---- 1. the code ----
  function askCode() {
    $("body").innerHTML = `${steps(1)}
      <h1>LeuffenDoc instellen</h1>
      <p class="lead">Deze server is nog niet ingesteld. Vul eerst de <b>installatiecode</b> in: die staat in de
        log van de container. In Dockge zie je die log op de pagina van de stack; anders met
        <code>docker logs</code>. Zo kan alleen wie de container beheert hem instellen.</p>
      <div class="frow"><input class="inp code-inp" id="code" placeholder="XXXX-XXXX" autocomplete="off"
        spellcheck="false" maxlength="9" /></div>
      <div class="err" id="err"></div>
      <button class="btn wide" id="go">Verder</button>`;
    $("code").focus();
    const go = async () => {
      $("go").disabled = true;
      try {
        seen = await post("/api/setup/unlock", { code: $("code").value });
        code = $("code").value;
        choose();
      } catch (e) { $("err").textContent = e.message; $("go").disabled = false; }
    };
    $("go").onclick = go;
    $("code").onkeydown = (ev) => { if (ev.key === "Enter") go(); };
  }

  // ---- 2. one address, one button ----
  function choose() {
    const here = location.origin;
    const proxy = seen.via_proxy
      ? `Je komt binnen via een reverse proxy op <b>${esc(seen.proxy_address)}</b>. Alleen die wordt geloofd
         als hij zegt wie de bezoeker is — dat houdt het logboek eerlijk.`
      : `Je komt rechtstreeks binnen, zonder reverse proxy. Zet je er later een voor, stel dat dan onder
         <b>Instellingen</b> in.`;
    const vault = seen.vault_key_from_env
      ? "De sleutel van de kluis komt uit <code>DOC_SECRET_KEY</code>."
      : "De sleutel van de kluis wordt nu gemaakt en in de database bewaard. Een back-up die je downloadt is altijd versleuteld.";
    $("body").innerHTML = `${steps(2)}
      <h1>Koppelen met de RMM</h1>
      <p class="lead">Vul het adres van je Leuffen RMM in en druk op de knop. De RMM vraagt je om het goed te
        keuren; daarna is alles ingesteld en ben je aangemeld. Wie goedkeurt, beheert LeuffenDoc.</p>
      <div class="pair-box">
        <div class="frow"><label class="l">Adres van de RMM</label>
          <input class="inp mono" id="rmm" placeholder="https://rmm.voorbeeld.nl" value="${esc(params.get("rmm") || "")}" /></div>
        <button class="btn wide" id="pair">${ICON.link || ""} Koppelen met de RMM</button>
        <div class="err" id="err"></div>
      </div>
      <div class="facts">LeuffenDoc is te bereiken op <b>${esc(here)}</b>. ${proxy}<br>${vault}</div>
      <details id="own"><summary>Zelf aanpassen</summary>
        <div class="frow"><label class="l">Adres van LeuffenDoc</label>
          <input class="inp mono" id="public" value="${esc(here)}" />
          <div class="hint">Waarop collega's LeuffenDoc openen. Aanmelden stuurt je hierheen terug.</div></div>
        <label class="boolrow"><input type="checkbox" id="trust"${seen.via_proxy ? " checked" : ""} />
          <span>Er zit een reverse proxy voor</span></label>
        <div class="frow" style="margin-top:8px"><label class="l">Adres van die proxy</label>
          <input class="inp mono" id="proxy" value="${esc(seen.proxy_address || "")}" placeholder="bijvoorbeeld 172.20.0.1" />
          <div class="hint">Leeg betekent: elke verbinding mag zeggen wie de bezoeker is. Alleen veilig als niets
            anders de container kan bereiken.</div></div>
        <div class="frow"><label class="l">Extra beheerders</label>
          <input class="inp" id="admins" placeholder="naam@bedrijf.nl, …" />
          <div class="hint">Naast wie de koppeling goedkeurt. Met komma's ertussen.</div></div>
        <details id="manual"><summary>Niet koppelen met één knop, maar handmatig</summary>
          <p class="hint" style="margin:0 0 10px">Voor een RMM die koppelen met één knop nog niet kent, of om je
            alleen met Microsoft 365 aan te melden. Vul hierboven dan minstens één beheerder in.</p>
          <div class="frow"><label class="l">API-sleutel van de RMM</label>
            <input class="inp mono" id="rmm-key" type="password" placeholder="lrmm_api_…" autocomplete="off" />
            <div class="hint">Onder Settings → API &amp; webhooks in de RMM, zonder organisatie. Het adres komt uit het veld bovenaan.</div></div>
          <label class="boolrow" style="margin-bottom:12px"><input type="checkbox" id="insecure" />
            <span>Certificaat van de RMM niet controleren (self-signed op het LAN)</span></label>
          <div class="frow"><label class="l">Microsoft 365 — tenant-id</label><input class="inp mono" id="m365-tenant" /></div>
          <div class="frow"><label class="l">Client-id</label><input class="inp mono" id="m365-client" /></div>
          <div class="frow"><label class="l">Clientgeheim</label><input class="inp mono" id="m365-secret" type="password" autocomplete="off" /></div>
          <div class="err" id="err-manual"></div>
          <button class="btn ghost wide" id="save-manual">Handmatig opslaan</button>
        </details>
      </details>`;
    $("rmm").focus();
    const common = () => ({
      code,
      public_url: $("public").value.trim(),
      trust_proxy: $("trust").checked,
      proxy_ips: $("proxy").value.trim(),
      admins: $("admins").value.split(/[,;\s]+/).filter((a) => a.includes("@")),
    });
    $("pair").onclick = async () => {
      $("pair").disabled = true;
      $("err").textContent = "";
      try {
        const r = await post("/api/setup/pair", { ...common(), rmm_url: $("rmm").value.trim() });
        location.href = r.redirect;
      } catch (e) { $("err").textContent = e.message; $("pair").disabled = false; }
    };
    $("rmm").onkeydown = (ev) => { if (ev.key === "Enter") $("pair").click(); };
    $("save-manual").onclick = async () => {
      $("save-manual").disabled = true;
      $("err-manual").textContent = "";
      try {
        const r = await post("/api/setup/manual", {
          ...common(), rmm_url: $("rmm").value.trim(), rmm_key: $("rmm-key").value.trim(),
          insecure: $("insecure").checked, m365_tenant: $("m365-tenant").value,
          m365_client_id: $("m365-client").value, m365_secret: $("m365-secret").value,
        });
        location.href = r.next;
      } catch (e) { $("err-manual").textContent = e.message; $("save-manual").disabled = false; }
    };
  }

  // ---- 3. back from the RMM ----
  async function finish(extra) {
    const state = params.get("state");
    $("body").innerHTML = `${steps(3)}<h1>Koppelen…</h1><p class="lead">De sleutel wordt bij de RMM opgehaald.</p>`;
    try {
      const r = await post("/api/koppelen/afronden", { state, ...(extra || {}) });
      $("body").innerHTML = `${steps(3)}<h1>Gekoppeld</h1>
        <p class="lead">${r.customers != null ? `De RMM kent ${esc(r.customers)} klanten; die komen nu mee. ` : ""}Je wordt aangemeld…</p>`;
      setTimeout(() => { location.href = r.next; }, 900);
    } catch (e) {
      if (e.data && e.data.unreachable) { unreachable(e.message, e.data.tried); return; }
      $("body").innerHTML = `${steps(3)}<h1>Koppelen lukte niet</h1>
        <div class="err">${esc(e.message)}</div>
        <p class="lead" style="margin-top:12px"><a href="/setup">Opnieuw beginnen</a></p>`;
    }
  }

  // The browser reached the RMM, this server did not: ask for an address that works from here.
  function unreachable(detail, tried) {
    $("body").innerHTML = `${steps(3)}
      <h1>Deze server bereikt de RMM niet</h1>
      <p class="lead">Goedgekeurd is het al, maar LeuffenDoc kan de sleutel niet ophalen: ${esc(detail)}.
        Dat gebeurt als de NAS zijn eigen openbare adres niet bereikt, of de RMM een eigen certificaat heeft.
        Vul het adres in waarop <b>deze server</b> de RMM wel bereikt — meestal het LAN-adres met de poort.</p>
      <div class="frow"><label class="l">Adres van de RMM vanaf deze server</label>
        <input class="inp mono" id="server-url" value="${esc(tried || "")}" placeholder="https://192.168.1.10:8000" /></div>
      <label class="boolrow" style="margin-bottom:14px"><input type="checkbox" id="insecure" />
        <span>Certificaat niet controleren (self-signed)</span></label>
      <button class="btn wide" id="retry">Opnieuw proberen</button>`;
    $("retry").onclick = () => finish({ server_url: $("server-url").value.trim(), insecure: $("insecure").checked });
  }

  // Started from the RMM's side, on a server that is already set up: say what
  // would change, and let an administrator decide.
  async function confirmLink() {
    const rmm = params.get("rmm") || "";
    let me = null;
    try {
      const r = await fetch("/api/me", { cache: "no-store" });
      if (r.ok) me = await r.json();
    } catch (e) { /* treated as not signed in */ }
    if (!me || !me.is_admin) {
      $("body").innerHTML = `<h1>Eerst aanmelden</h1>
        <p class="lead">Koppelen met de RMM kan alleen een beheerder van LeuffenDoc. Meld je aan en druk daarna
          nog een keer op de knop in de RMM — of koppel onder <b>Instellingen</b>.</p>
        <a class="btn wide" href="/auth/login">Aanmelden</a>`;
      return;
    }
    let current = "";
    try { current = (await (await fetch("/api/rmm/status")).json()).url || ""; } catch (e) { /* none */ }
    $("body").innerHTML = `<h1>Koppelen met deze RMM?</h1>
      <p class="lead">Wie de RMM is, bepaalt wie hier mag aanmelden. Ga alleen door als je dit zelf net in de
        RMM hebt gestart.</p>
      <div class="frow"><label class="l">RMM</label><input class="inp mono" id="rmm" value="${esc(rmm)}" /></div>
      ${current ? `<p class="hint" style="margin:-4px 0 14px">Dit vervangt de koppeling met <b>${esc(current)}</b>.</p>` : ""}
      <div class="err" id="err"></div>
      <button class="btn wide" id="pair">${ICON.link || ""} Koppelen</button>
      <p class="lead" style="margin-top:12px;text-align:center"><a href="/">Niet koppelen</a></p>`;
    $("pair").onclick = async () => {
      $("pair").disabled = true;
      try {
        const r = await post("/api/admin/pair", { rmm_url: $("rmm").value.trim() });
        location.href = r.redirect;
      } catch (e) { $("err").textContent = e.message; $("pair").disabled = false; }
    };
  }

  if (location.pathname === "/koppelen" && params.get("state")) {
    finish();
  } else if (location.pathname === "/koppelen") {
    confirmLink();
  } else {
    askCode();
  }
})();
