// A shortlist in a link, so friends can see the same places. The link carries only what the
// shortlist shows (name, area, rating, cuisines, cost), as base64url-encoded JSON, and a shared
// link is checked as untrusted input before anything is shown.

export const MAX_SHARED = 20;
const FIELDS = ["name", "place", "rating", "cuisines", "cost"];
const MAX_FIELD = 200;

function toBase64Url(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromBase64Url(text) {
  const binary = atob(text.replace(/-/g, "+").replace(/_/g, "/"));
  return new TextDecoder().decode(Uint8Array.from(binary, (c) => c.charCodeAt(0)));
}

/** The shortlist as a compact link parameter: one array per place, in the order of FIELDS. */
export function encodeShortlist(items) {
  const rows = items.slice(0, MAX_SHARED).map((item) => FIELDS.map((f) => String(item[f] ?? "")));
  return toBase64Url(JSON.stringify(rows));
}

/** The places in a shared link, or null if the link is damaged or not a shortlist. */
export function decodeShortlist(text) {
  if (typeof text !== "string" || !text || text.length > 20000) return null;
  let rows;
  try {
    rows = JSON.parse(fromBase64Url(text));
  } catch {
    return null;
  }
  if (!Array.isArray(rows) || !rows.length) return null;
  const items = [];
  for (const row of rows.slice(0, MAX_SHARED)) {
    if (!Array.isArray(row) || row.length !== FIELDS.length) return null;
    if (!row.every((value) => typeof value === "string" && value.length <= MAX_FIELD)) return null;
    const item = Object.fromEntries(FIELDS.map((f, i) => [f, row[i]]));
    if (!item.name) return null;
    items.push({ ...item, key: `${item.name}|${item.place}` });
  }
  return items;
}
