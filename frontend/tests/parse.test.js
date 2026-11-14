import assert from "node:assert/strict";
import { test } from "node:test";

import { cuisineIcon } from "../src/cuisine-icons.js";
import { parseSentence } from "../src/parse.js";

// A small slice of GET /options, in menu order.
const OPTIONS = {
  areas: ["BTM", "HSR", "Indiranagar", "Jayanagar", "Koramangala 4th Block", "Koramangala 5th Block"],
  cuisines: ["North Indian", "Chinese", "South Indian", "Italian"],
  dishes: ["Pizza", "Biryani", "Momos", "Noodles", "Chicken Biryani"],
};

test("reads area, budget, dish and rating from a sentence", () => {
  const parsed = parseSentence("pocket-friendly biryani in BTM, rated 4+", OPTIONS);
  assert.equal(parsed.area, "BTM");
  assert.equal(parsed.budget, "low");
  assert.deepEqual(parsed.dishes, ["Biryani"]);
  assert.equal(parsed.min_rating, 4);
  assert.equal(parsed.additional, "");
});

test("prefers the longest name, so chicken biryani isn't also biryani", () => {
  const parsed = parseSentence("chicken biryani near koramangala under 1000", OPTIONS);
  assert.deepEqual(parsed.dishes, ["Chicken Biryani"]);
  assert.equal(parsed.area, "Koramangala 4th Block");
  assert.equal(parsed.areaGuessed, true);
  assert.equal(parsed.budget, "medium");
});

test("keeps words it doesn't know for Anything else", () => {
  const parsed = parseSentence("family friendly north indian in hsr layout with rooftop", OPTIONS);
  assert.equal(parsed.area, "HSR");
  assert.deepEqual(parsed.cuisines, ["North Indian"]);
  assert.equal(parsed.additional, "family friendly rooftop");
});

test("understands fancy, cheap, top rated and new", () => {
  assert.equal(parseSentence("fancy date night in Indiranagar", OPTIONS).budget, "high");
  assert.equal(parseSentence("cheap momos", OPTIONS).budget, "low");
  assert.equal(parseSentence("top rated pizza", OPTIONS).min_rating, 4);
  assert.equal(parseSentence("new cafes in Jayanagar", OPTIONS).include_unrated, true);
  assert.equal(parseSentence("momos under ₹500", OPTIONS).budget, "low");
});

test("lists several dishes in menu order, and no area when none is named", () => {
  const parsed = parseSentence("noodles and momos", OPTIONS);
  assert.deepEqual(parsed.dishes, ["Momos", "Noodles"]);
  assert.equal(parsed.area, null);
});

test("cuisine icons follow the first recognised cuisine", () => {
  assert.equal(cuisineIcon("Ice Cream, Desserts"), "🍨");
  assert.equal(cuisineIcon("Kerala, South Indian"), "🥘");
  assert.equal(cuisineIcon("Italian, Pizza"), "🍕");
  assert.equal(cuisineIcon("Something new"), "🍽️");
});
