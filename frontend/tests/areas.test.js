import assert from "node:assert/strict";
import { test } from "node:test";

import { AREA_CENTRES, distanceKm, nearestArea } from "../src/areas.js";

const AREAS = Object.keys(AREA_CENTRES);

test("every area of the dataset has a centre inside Bangalore", () => {
  assert.equal(AREAS.length, 30);
  for (const [lat, lon] of Object.values(AREA_CENTRES)) {
    assert.ok(lat > 12.8 && lat < 13.1 && lon > 77.5 && lon < 77.8);
  }
});

test("distances are in kilometres", () => {
  // Indiranagar to Whitefield is about 12 km.
  const km = distanceKm(AREA_CENTRES.Indiranagar, AREA_CENTRES.Whitefield);
  assert.ok(km > 10 && km < 13, String(km));
});

test("picks the nearest area", () => {
  // A point near the Indiranagar 100 Feet Road junction.
  assert.equal(nearestArea([12.9719, 77.6412], AREAS).area, "Indiranagar");
  // Near Forum Mall, Koramangala.
  assert.equal(nearestArea([12.9346, 77.6113], AREAS).area, "Koramangala 7th Block");
  // Infosys, Electronic City.
  assert.equal(nearestArea([12.8456, 77.6633], AREAS).area, "Electronic City");
});

test("only considers the areas offered, and gives up far from Bangalore", () => {
  // From Indiranagar, HSR (6.7 km) is a little nearer than BTM (7.0 km).
  assert.equal(nearestArea([12.9719, 77.6412], ["BTM", "HSR"]).area, "HSR");
  // Mysuru is about 130 km away.
  assert.equal(nearestArea([12.2958, 76.6394], AREAS), null);
  assert.equal(nearestArea([12.97, 77.64], ["Somewhere new"]), null);
});
