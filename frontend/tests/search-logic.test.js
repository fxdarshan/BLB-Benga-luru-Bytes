import assert from "node:assert/strict";
import { test } from "node:test";

import {
  clampRating,
  costBand,
  defaultSearch,
  mapsUrl,
  queryToSearch,
  ratingBand,
  refineOptions,
  savedKey,
  searchToQuery,
  similarSearch,
} from "../src/search-logic.js";

const DEFAULT = 3.5;

test("a search survives the round trip through the page address", () => {
  const search = {
    area: "Koramangala 5th Block",
    budget: "low",
    cuisines: ["North Indian", "Chinese"],
    dishes: ["Biryani"],
    min_rating: 4,
    include_unrated: true,
    additional: "quiet, family friendly",
  };
  const query = searchToQuery(search, DEFAULT);
  assert.equal(
    query,
    "area=Koramangala+5th+Block&budget=low&cuisine=North+Indian&cuisine=Chinese&dish=Biryani" +
      "&rating=4&unrated=1&q=quiet%2C+family+friendly",
  );
  assert.deepEqual(queryToSearch(query, DEFAULT), search);
});

test("defaults stay out of the address", () => {
  assert.equal(searchToQuery(defaultSearch("BTM", DEFAULT), DEFAULT), "area=BTM");
  assert.deepEqual(queryToSearch("area=BTM", DEFAULT), defaultSearch("BTM", DEFAULT));
});

test("an address without an area is no search", () => {
  assert.equal(queryToSearch("", DEFAULT), null);
  assert.equal(queryToSearch("dish=Biryani", DEFAULT), null);
});

test("ratings from the address are clamped and rounded", () => {
  assert.equal(queryToSearch("area=BTM&rating=9", DEFAULT).min_rating, 5);
  assert.equal(queryToSearch("area=BTM&rating=-2", DEFAULT).min_rating, 0);
  assert.equal(queryToSearch("area=BTM&rating=3.33", DEFAULT).min_rating, 3.3);
  assert.equal(queryToSearch("area=BTM&rating=lots", DEFAULT).min_rating, DEFAULT);
  assert.equal(clampRating(undefined, 4), 4);
});

test("free text from the address is capped at 300 characters", () => {
  const long = "a".repeat(400);
  assert.equal(queryToSearch(`area=BTM&q=${long}`, DEFAULT).additional.length, 300);
});

test("ratings are coloured by band", () => {
  const rated = (rating) => ({ rating, is_rated: true });
  assert.equal(ratingBand(rated("★ 4.4 (711 votes)")), " band-good");
  assert.equal(ratingBand(rated("★ 4.0 (20 votes)")), " band-good");
  assert.equal(ratingBand(rated("★ 3.7 (90 votes)")), " band-ok");
  assert.equal(ratingBand(rated("★ 3.2 (12 votes)")), " band-low");
  assert.equal(ratingBand({ rating: "New", is_rated: false }), "");
});

test("a cost badge gives its budget band", () => {
  assert.equal(costBand("₹300 for two"), "low");
  assert.equal(costBand("₹500 for two"), "medium");
  assert.equal(costBand("₹1,500 for two"), "medium");
  assert.equal(costBand("₹2,000 for two"), "high");
  assert.equal(costBand("Cost not listed"), "any");
  assert.equal(costBand(undefined), "any");
});

test("more like this uses the first known cuisine and the price band, in the same area", () => {
  const result = { cuisines: "Cafe, Italian, Pizza", badges: ["₹1,200 for two", "Cafe"] };
  const search = { ...defaultSearch("Indiranagar", DEFAULT), dishes: ["Pizza"], min_rating: 4.5 };
  assert.deepEqual(similarSearch(result, search, ["North Indian", "Italian"], DEFAULT), {
    ...defaultSearch("Indiranagar", DEFAULT),
    budget: "medium",
    cuisines: ["Italian"],
  });
  assert.equal(similarSearch(result, search, ["Thai"], DEFAULT), null);
});

test("refine offers a lower budget, a higher rating, new places and clearing filters", () => {
  const labels = (search) => refineOptions(search, DEFAULT).map((o) => o.label);
  const base = defaultSearch("BTM", DEFAULT);
  assert.deepEqual(labels(base), ["Rated 4.0+", "Include new places"]);
  assert.deepEqual(labels({ ...base, budget: "high", min_rating: 4.2 }), [
    "Pocket friendly",
    "Rated 4.5+",
    "Include new places",
    "Clear filters",
  ]);
  assert.deepEqual(labels({ ...base, budget: "low", min_rating: 4.5, include_unrated: true }), [
    "Clear filters",
  ]);
  const pocket = refineOptions({ ...base, budget: "medium" }, DEFAULT)[0];
  assert.deepEqual(pocket.change, { budget: "low" });
  const clear = refineOptions({ ...base, dishes: ["Biryani"] }, DEFAULT).at(-1);
  assert.deepEqual(clear.change, base);
});

test("shortlist keys and directions links", () => {
  assert.equal(savedKey({ name: "Jose's Mess", place: "BTM" }), "Jose's Mess|BTM");
  assert.equal(
    mapsUrl("Jose's Mess", "BTM"),
    "https://www.google.com/maps/search/?api=1&query=Jose's%20Mess%2C%20BTM%2C%20Bangalore",
  );
});
