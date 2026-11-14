import assert from "node:assert/strict";
import { test } from "node:test";

import { MAX_SHARED, decodeShortlist, encodeShortlist } from "../src/share.js";

const SAVED = [
  { key: "Jose's Mess|BTM", name: "Jose's Mess", place: "BTM", rating: "★ 4.4 (320 votes)", cuisines: "Kerala, South Indian", cost: "₹300 for two" },
  { key: "Toit|Indiranagar", name: "Toit", place: "Indiranagar", rating: "★ 4.7 (14,956 votes)", cuisines: "Italian, American", cost: "₹1,500 for two" },
];

test("a shortlist survives the link, including the rupee sign and apostrophes", () => {
  const link = encodeShortlist(SAVED);
  assert.match(link, /^[A-Za-z0-9_-]+$/);
  assert.deepEqual(decodeShortlist(link), SAVED);
});

test("a link carries at most twenty places", () => {
  const many = Array.from({ length: 30 }, (_, i) => ({ ...SAVED[0], name: `Place ${i}` }));
  assert.equal(decodeShortlist(encodeShortlist(many)).length, MAX_SHARED);
});

test("damaged or hostile links are refused", () => {
  const encode = (value) => btoa(JSON.stringify(value)).replace(/=+$/, "");
  assert.equal(decodeShortlist(""), null);
  assert.equal(decodeShortlist("not base64 at all!"), null);
  assert.equal(decodeShortlist(encode({ name: "x" })), null);
  assert.equal(decodeShortlist(encode([])), null);
  assert.equal(decodeShortlist(encode([["only", "three", "fields"]])), null);
  assert.equal(decodeShortlist(encode([[1, 2, 3, 4, 5]])), null);
  assert.equal(decodeShortlist(encode([["x".repeat(201), "", "", "", ""]])), null);
  assert.equal(decodeShortlist(encode([["", "BTM", "", "", ""]])), null);
});
