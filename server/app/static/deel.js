/* The page behind a share link. Nothing is fetched until the button is
   pressed: link previews open this page by themselves, and must not use up a
   link meant for one look. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Follow the system's light or dark, since there is no account to remember it.
  try {
    if (window.matchMedia("(prefers-color-scheme: light)").matches) {
      document.documentElement.dataset.theme = "light";
    }
  } catch (e) { /* keep dark */ }
  $("logo").innerHTML = ICON.key;

  function row(label, value, secret) {
    return `<div class="row${secret ? " secret" : ""}"><label>${esc(label)}</label>
        <div class="val"><span class="box mono">${esc(value)}</span>
          <button class="btn ghost sm" data-copy="${esc(value)}">${ICON.copy} Kopiëren</button></div></div>`;
  }

  $("open").onclick = async () => {
    $("open").disabled = true;
    let res;
    try {
      res = await fetch(location.pathname, { method: "POST", cache: "no-store" });
    } catch (e) {
      $("body").innerHTML = `<p class="lead">Geen verbinding. Probeer het zo nog eens — de link is niet gebruikt.</p>`;
      return;
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      $("body").innerHTML = `<h2>Deze link werkt niet meer</h2>
        <p class="lead">${esc(data.detail || "Hij is verlopen, al gebruikt, of ingetrokken.")}</p>`;
      return;
    }
    const until = new Date(data.expires_at * 1000).toLocaleString("nl-NL");
    $("body").innerHTML = `<h2>${esc(data.name || "Gedeeld wachtwoord")}</h2>
      ${data.username ? row("Gebruikersnaam", data.username) : ""}
      ${data.url ? row("Adres", data.url) : ""}
      ${row(data.label || "Wachtwoord", data.password, true)}
      <div class="after">${data.looks_left
        ? `Deze link werkt nog ${data.looks_left} keer, tot ${esc(until)}.`
        : "<b>Dit was de laatste keer.</b> Sla het nu op waar het hoort: deze link werkt niet meer."}
        Gedeeld door ${esc(data.shared_by)}.</div>`;
    document.querySelectorAll("[data-copy]").forEach((b) => {
      b.onclick = async () => {
        try {
          await navigator.clipboard.writeText(b.dataset.copy);
          b.textContent = "Gekopieerd";
        } catch (e) {
          // Without https the browser refuses the clipboard; select it instead.
          const box = b.parentElement.querySelector(".box");
          const range = document.createRange();
          range.selectNodeContents(box);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
          b.textContent = "Geselecteerd — Ctrl+C";
        }
      };
    });
  };
})();
