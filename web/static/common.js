// Small helpers shared by the pages. No framework.

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const eur = (v) => (v === null || v === undefined || isNaN(Number(v)))
  ? "—" : "€" + Number(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const num = (v) => (v === null || v === undefined || isNaN(Number(v)))
  ? "—" : Number(v).toLocaleString("en-GB", { maximumFractionDigits: 2 });

function dayLabel(iso) {
  if (!iso) return "—";
  const d = new Date(String(iso).slice(0, 10) + "T12:00:00");
  if (isNaN(d)) return esc(iso);
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

function clock(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return esc(iso ?? "");
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function ago(iso) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (isNaN(s)) return "";
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + " min ago";
  return Math.floor(s / 3600) + " h ago";
}

// Tiny Markdown: **bold**, `code`, "- " bullets, line breaks. Input is escaped first.
function md(text) {
  const lines = esc(text).split(/\r?\n/);
  let html = "", inList = false;
  for (const raw of lines) {
    const line = raw
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, '<code class="mono">$1</code>');
    const bullet = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
    const heading = line.match(/^\s*#{1,6}\s+(.*)$/);
    if (heading) {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<p class="md-h">${heading[1]}</p>`;
    } else if (bullet) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${bullet[1]}</li>`;
    } else {
      if (inList) { html += "</ul>"; inList = false; }
      html += line.trim() ? `<p>${line}</p>` : "";
    }
  }
  return html + (inList ? "</ul>" : "");
}

async function getJSON(url, opts) {
  const res = await fetch(url, Object.assign({ cache: "no-store" }, opts));
  let body = null;
  try { body = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const msg = (body && (body.message || body.detail)) || `${res.status} ${res.statusText}`;
    throw new Error(msg);
  }
  return body;
}

// Accept either a bare list or {items|entries|approvals: [...]}.
function asList(body, ...keys) {
  if (Array.isArray(body)) return body;
  for (const k of keys) if (body && Array.isArray(body[k])) return body[k];
  return [];
}

const STATUS = {
  confirmed: { cls: "ok", icon: "✓", label: "Confirmed" },
  approved: { cls: "ok", icon: "✓", label: "Approved by a person" },
  pending_approval: { cls: "warn", icon: "👤", label: "Needs a person's approval" },
  pending: { cls: "warn", icon: "⏳", label: "Still waiting for approval" },
  needs_clarification: { cls: "info", icon: "?", label: "Server asks the agent to confirm" },
  rejected: { cls: "bad", icon: "⛔", label: "Rejected" },
};
