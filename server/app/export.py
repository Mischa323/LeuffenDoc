"""A customer's documentation, to take away.

For when a customer leaves and should get what was documented for them, for
an audit, or simply to have it outside this server. One zip with three views
of the same thing:

  * ``documentatie.html`` -- to read and to print, one page, no server needed;
  * ``data.json`` -- everything, structured, for whatever comes next;
  * ``csv/<soort>.csv`` -- one sheet per kind, for a spreadsheet (semicolons
    and a byte-order mark, which is what Excel on a Dutch machine expects).

Only what the person exporting may see goes in: nothing shut off to others.
Passwords only when asked for and only for someone who may read them, each one
written in the log as it is read -- the file then holds them in plain text,
which the page says before anyone presses the button.
"""
from __future__ import annotations

import csv
import datetime
import html
import io
import json
import time
import unicodedata
import zipfile

from . import database, schema, vault


# --------------------------------------------------------------------------- #
# Values as a person reads them
# --------------------------------------------------------------------------- #
def _date(value) -> str:
    try:
        on = datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value)
    return f"{on.day}-{on.month}-{on.year}"


def raw_value(item: dict, field: dict):
    """What the page shows for a field: the RMM's figure where the RMM keeps
    it, the typed value otherwise."""
    if field.get("rmm"):
        return (item.get("rmm") or {}).get(field["rmm"])
    return item["fields"].get(field["key"])


def text(field: dict, value, names: dict) -> str:
    if value is None or value == "" or value == []:
        return ""
    kind = field["type"]
    if kind == "ref":
        return names.get(value, "")
    if kind == "date":
        return _date(value)
    if kind == "bool":
        return "Ja" if value else "Nee"
    if kind == "list":
        return "\n".join(f"{e.get('label')}: {e.get('value')}" if e.get("label") else str(e.get("value"))
                         for e in value if isinstance(e, dict) and e.get("value"))
    return str(value)


def _file_slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return schema.slug(plain) or "klant"


def _secret_slots(kind: str) -> list:
    """Where an item of this kind keeps passwords: (field key, label)."""
    if kind == "password":
        return [("main", "Wachtwoord")]
    return [(key, schema.label_of(kind, key)) for key in schema.secret_fields_of(kind)]


# --------------------------------------------------------------------------- #
# Gathering
# --------------------------------------------------------------------------- #
def gather(org: dict, hidden: set, with_passwords: bool) -> tuple[dict, list]:
    """Everything visible at one customer, and the passwords read for it."""
    items = [i for i in database.list_items(org["id"], include_archived=True) if i["id"] not in hidden]
    names = {i["id"]: i["name"] for i in items}
    kinds = schema.KINDS_all()
    read = []
    out = []
    for item in items:
        spec = kinds.get(item["kind"], {})
        fields = []
        for key, field in schema.fields_of(item["kind"]).items():
            if field["type"] == "secret":
                continue
            value = raw_value(item, field)
            shown = text(field, value, names)
            if shown:
                fields.append({"key": key, "label": field["label"], "value": shown, "raw": value,
                               "from_rmm": bool(field.get("rmm")),
                               "multiline": field["type"] in ("textarea", "long", "list")})
        record = {
            "id": item["id"], "kind": item["kind"], "kind_label": spec.get("label", item["kind"]),
            "name": item["name"], "archived": item["archived"], "from_rmm": item.get("source") == "rmm",
            "created_at": item.get("created_at"), "created_by": item.get("created_by"),
            "updated_at": item.get("updated_at"), "updated_by": item.get("updated_by"),
            "fields": fields,
            "related": [{"id": r["id"], "name": r["name"], "kind": r["kind"]}
                        for r in database.relations_of(item["id"]) if r["id"] in names],
        }
        adapters = database.list_adapters(item["id"]) if item["kind"] in schema.adapter_kinds() else []
        if adapters:
            record["adapters"] = [{
                "name": a.get("name"), "mac": a.get("mac"), "ip": a.get("ip"), "vlan": a.get("vlan"),
                "switch": a["port"]["switch_name"] if a.get("port") and a["port"]["switch_id"] in names else None,
                "port": a["port"]["number"] if a.get("port") and a["port"]["switch_id"] in names else None,
            } for a in adapters]
        if item["kind"] == "network":
            try:
                count = int(item["fields"].get("ports") or 0)
            except (TypeError, ValueError):
                count = 0
            # A port holds an adapter; the machine behind it is only named
            # when this person may see it.
            taken = [p for p in database.ports_of(item["id"], count)
                     if p["adapter"] and p["adapter"]["item_id"] in names]
            if taken or count:
                record["ports"] = {"count": count, "taken": [
                    {"number": p["number"], "label": p["label"], "vlan": p["vlan"],
                     "item": p["adapter"]["item_name"], "adapter": p["adapter"]["name"]}
                    for p in taken]}
        secrets = []
        for key, label in _secret_slots(item["kind"]):
            stored = database.get_secret(item["id"], key)
            if not stored:
                continue
            entry = {"field": key, "label": label, "updated_at": stored["updated_at"]}
            if with_passwords:
                try:
                    entry["password"] = vault.unseal(stored)
                    read.append((item, label))
                except Exception:
                    entry["password"] = None
                    entry["error"] = "kon niet geopend worden"
            secrets.append(entry)
        if secrets:
            record["passwords"] = secrets
        out.append(record)
    return {"customer": {"id": org["id"], "name": org["name"], "rmm_org_id": org.get("rmm_org_id")},
            "exported_at": time.time(), "with_passwords": with_passwords, "items": out}, read


# --------------------------------------------------------------------------- #
# The three views
# --------------------------------------------------------------------------- #
def _order(data: dict) -> list:
    """Kinds in catalogue order, each with its items, only the ones present."""
    kinds = schema.KINDS_all()
    groups = []
    for name, spec in kinds.items():
        members = [i for i in data["items"] if i["kind"] == name]
        if members:
            groups.append((name, spec, sorted(members, key=lambda i: (i["archived"], i["name"].lower()))))
    return groups


CSS = """
body { font: 14px/1.55 -apple-system, "Segoe UI", Roboto, sans-serif; color: #1a1f2b; margin: 0; background: #f5f6f8; }
main { max-width: 900px; margin: 0 auto; padding: 32px 24px 60px; }
header { border-bottom: 2px solid #1a1f2b; padding-bottom: 14px; margin-bottom: 22px; }
h1 { margin: 0 0 4px; font-size: 26px; } h2 { margin: 34px 0 12px; font-size: 19px; }
.meta { color: #5b6475; font-size: 13px; } .warn { color: #9a5b00; font-weight: 600; }
nav ul { columns: 2; padding-left: 18px; margin: 8px 0 0; } nav a { color: #2355c5; text-decoration: none; }
.item { background: #fff; border: 1px solid #dde1e8; border-radius: 8px; padding: 14px 18px; margin-bottom: 12px;
        break-inside: avoid; }
.item h3 { margin: 0 0 8px; font-size: 16px; } .tag { font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: .04em; padding: 2px 7px; border-radius: 99px; background: #eef0f4; color: #5b6475; margin-left: 6px; }
dl { display: grid; grid-template-columns: 190px 1fr; gap: 4px 14px; margin: 0; font-size: 13.5px; }
dt { color: #5b6475; } dd { margin: 0; white-space: pre-line; word-break: break-word; }
.sub { font-size: 12px; font-weight: 600; color: #5b6475; text-transform: uppercase; letter-spacing: .05em; margin: 12px 0 4px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; } td, th { text-align: left; padding: 4px 8px 4px 0;
  border-bottom: 1px solid #eef0f4; } th { color: #5b6475; font-weight: 600; }
code { font: 13px ui-monospace, Consolas, monospace; background: #f1f3f7; padding: 1px 5px; border-radius: 4px; }
.body { white-space: pre-wrap; font-size: 13.5px; border-left: 3px solid #dde1e8; padding-left: 12px; margin-top: 8px; }
@media print { body { background: #fff; } main { padding: 0; } .item { border-color: #bbb; } nav { display: none; } }
"""


def _adapter_row(a: dict) -> str:
    e = html.escape
    port = f"{a['switch']}, poort {a['port']}" if a.get("switch") else "—"
    return (f"<tr><td>{e(a.get('name') or '')}</td><td><code>{e(a.get('mac') or '')}</code></td>"
            f"<td>{e(port)}</td><td>{e(str(a.get('vlan') or ''))}</td></tr>")


def to_html(data: dict, by: str) -> str:
    e = html.escape
    # The server's clock, with its zone said out loud: a container runs on UTC
    # unless told otherwise, and an unlabelled time is then two hours off.
    when = time.strftime("%d-%m-%Y %H:%M %Z", time.localtime(data["exported_at"]))
    groups = _order(data)
    parts = [f"<!DOCTYPE html><html lang='nl'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
             f"<title>{e(data['customer']['name'])} — documentatie</title><style>{CSS}</style></head><body><main>",
             f"<header><h1>{e(data['customer']['name'])}</h1><div class='meta'>Documentatie uit LeuffenDoc, "
             f"geëxporteerd op {e(when)} door {e(by)}. {len(data['items'])} items.</div>",
             ("<div class='meta warn'>Met wachtwoorden, leesbaar. Bewaar en verstuur dit bestand "
              "alleen versleuteld.</div>" if data["with_passwords"] else
              "<div class='meta'>Zonder wachtwoorden: die staan erin als aanwezig, niet als tekst.</div>"),
             "</header><nav><strong>Inhoud</strong><ul>"]
    for name, spec, members in groups:
        parts.append(f"<li><a href='#k-{e(name)}'>{e(spec.get('plural', name))}</a> ({len(members)})</li>")
    parts.append("</ul></nav>")
    for name, spec, members in groups:
        parts.append(f"<h2 id='k-{e(name)}'>{e(spec.get('plural', name))}</h2>")
        for item in members:
            tags = (" <span class='tag'>afgevoerd</span>" if item["archived"] else "") + \
                   (" <span class='tag'>uit de RMM</span>" if item["from_rmm"] else "")
            parts.append(f"<section class='item'><h3>{e(item['name'])}{tags}</h3>")
            body = [f for f in item["fields"] if f["key"] == "body"]
            rows = [f for f in item["fields"] if f["key"] != "body"]
            if rows:
                parts.append("<dl>" + "".join(f"<dt>{e(f['label'])}</dt><dd>{e(f['value'])}</dd>"
                                              for f in rows) + "</dl>")
            for secret in item.get("passwords", []):
                value = (f"<code>{e(secret['password'])}</code>" if secret.get("password") is not None
                         else ("<em>kon niet geopend worden</em>" if secret.get("error")
                               else "<em>aanwezig, niet meegenomen</em>"))
                parts.append(f"<dl><dt>{e(secret['label'])}</dt><dd>{value}</dd></dl>")
            if item.get("adapters"):
                parts.append("<div class='sub'>Netwerkadapters</div><table><tr><th>Naam</th><th>MAC</th>"
                             "<th>Switchpoort</th><th>VLAN</th></tr>"
                             + "".join(_adapter_row(a) for a in item["adapters"]) + "</table>")
            if item.get("ports", {}).get("taken"):
                parts.append("<div class='sub'>Patchlijst</div><table><tr><th>Poort</th><th>Wat</th>"
                             "<th>Label</th><th>VLAN</th></tr>" + "".join(
                                 f"<tr><td>{p['number']}</td><td>{e(p['item'] or '')}"
                                 f"{e(' — ' + p['adapter']) if p.get('adapter') else ''}</td>"
                                 f"<td>{e(p['label'] or '')}</td><td>{e(str(p['vlan'] or ''))}</td></tr>"
                                 for p in item["ports"]["taken"]) + "</table>")
            if item["related"]:
                parts.append("<div class='sub'>Gekoppeld</div><div>" +
                             ", ".join(e(r["name"]) for r in item["related"]) + "</div>")
            for f in body:
                parts.append(f"<div class='body'>{e(f['value'])}</div>")
            parts.append("</section>")
    parts.append("</main></body></html>")
    return "".join(parts)


def to_csv(data: dict) -> dict:
    """One sheet per kind, named after it."""
    sheets = {}
    for name, spec, members in _order(data):
        labels = []
        for field in schema.fields_of(name).values():
            if field["type"] != "secret":
                labels.append(field["label"])
        secret_labels = [label for _, label in _secret_slots(name)] if data["with_passwords"] else []
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
        writer.writerow(["Naam", *labels, *secret_labels, "Afgevoerd"])
        for item in members:
            by_label = {f["label"]: f["value"] for f in item["fields"]}
            secrets = {s["label"]: s.get("password") or "" for s in item.get("passwords", [])}
            writer.writerow([item["name"], *(by_label.get(label, "") for label in labels),
                             *(secrets.get(label, "") for label in secret_labels),
                             "ja" if item["archived"] else ""])
        sheets[f"csv/{schema.slug(spec.get('plural', name))}.csv"] = "﻿" + buf.getvalue()
    return sheets


def build(org: dict, hidden: set, with_passwords: bool, by: str) -> tuple[str, bytes, list]:
    data, read = gather(org, hidden, with_passwords)
    data["exported_by"] = by
    stamp = datetime.date.today().isoformat()
    folder = f"{_file_slug(org['name'])}-documentatie-{stamp}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{folder}/documentatie.html", to_html(data, by))
        z.writestr(f"{folder}/data.json", json.dumps(data, ensure_ascii=False, indent=2, default=str))
        for path, content in to_csv(data).items():
            z.writestr(f"{folder}/{path}", content)
    return f"{folder}.zip", buf.getvalue(), read
