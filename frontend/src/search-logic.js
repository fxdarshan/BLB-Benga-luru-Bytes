// Search rules with no page access, so they can be tested on their own (tests/*.test.js):
// the search in the page address, rating bands, "More like this", the refine buttons and
// shortlist keys. `defaultRating` comes from GET /options.

export const BUDGET_BANDS = ["any", "low", "medium", "high"];

/** A rating rounded to one decimal, from 0 to 5. Anything else gives `fallback`. */
export function clampRating(value, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(5, Math.max(0, Math.round(number * 10) / 10));
}

/** A search with no filters in an area. */
export function defaultSearch(area, defaultRating) {
  return {
    area,
    budget: "any",
    cuisines: [],
    dishes: [],
    min_rating: defaultRating,
    include_unrated: false,
    additional: "",
  };
}

// ---------- The search in the page address ----------
// Each search is kept in the address, such as ?area=BTM&dish=Biryani, so it can be shared or
// bookmarked, and the browser's Back button returns to the previous search.

export function searchToQuery(search, defaultRating) {
  const params = new URLSearchParams();
  params.set("area", search.area);
  if (search.budget !== "any") params.set("budget", search.budget);
  for (const cuisine of search.cuisines) params.append("cuisine", cuisine);
  for (const dish of search.dishes) params.append("dish", dish);
  if (search.min_rating !== defaultRating) params.set("rating", String(search.min_rating));
  if (search.include_unrated) params.set("unrated", "1");
  if (search.additional) params.set("q", search.additional);
  return params.toString();
}

/** The search in a query string, or null without an area. */
export function queryToSearch(query, defaultRating) {
  const params = new URLSearchParams(query);
  const area = params.get("area");
  if (!area) return null;
  return {
    area,
    budget: params.get("budget") ?? "any",
    cuisines: params.getAll("cuisine"),
    dishes: params.getAll("dish"),
    min_rating: params.has("rating")
      ? clampRating(params.get("rating"), defaultRating)
      : defaultRating,
    include_unrated: params.get("unrated") === "1",
    additional: (params.get("q") ?? "").slice(0, 300),
  };
}

// ---------- Result cards ----------

/** The class that colours a rating: green 4.0+, amber 3.5 to 3.9, grey below. */
export function ratingBand(result) {
  const value = Number((/([\d.]+)/.exec(result.rating) ?? [])[1]);
  if (!result.is_rated || !Number.isFinite(value)) return "";
  if (value >= 4) return " band-good";
  if (value >= 3.5) return " band-ok";
  return " band-low";
}

/** The budget band of a cost badge such as "₹1,200 for two", or "any" without a cost. */
export function costBand(badge) {
  const cost = Number(((/₹([\d,]+)/.exec(badge ?? "") ?? [])[1] ?? "").replace(/,/g, ""));
  if (!(cost > 0)) return "any";
  if (cost < 500) return "low";
  return cost <= 1500 ? "medium" : "high";
}

/** A search for places like this one: its main cuisine and price band, in the same area. */
export function similarSearch(result, search, knownCuisines, defaultRating) {
  const known = new Set(knownCuisines);
  const cuisine = result.cuisines
    .split(",")
    .map((c) => c.trim())
    .find((c) => known.has(c));
  if (!cuisine) return null;
  return {
    ...defaultSearch(search.area, defaultRating),
    budget: costBand(result.badges[0]),
    cuisines: [cuisine],
  };
}

/** One-tap changes to a search: pocket friendly, better rated, new places, or no filters. */
export function refineOptions(search, defaultRating) {
  const options = [];
  const lowerBudget = { high: "medium", medium: "low" }[search.budget];
  if (lowerBudget) {
    options.push({ label: "Pocket friendly", change: { budget: lowerBudget }, icon: "wallet" });
  }
  if (search.min_rating < 4.5) {
    const higher = Math.min(4.5, Math.floor(search.min_rating * 2) / 2 + 0.5);
    options.push({
      label: `Rated ${higher.toFixed(1)}+`,
      change: { min_rating: higher },
      icon: "star",
    });
  }
  if (!search.include_unrated) {
    options.push({
      label: "Include new places",
      change: { include_unrated: true },
      icon: "sparkle",
    });
  }
  const filtered =
    search.budget !== "any" ||
    search.cuisines.length > 0 ||
    search.dishes.length > 0 ||
    Boolean(search.additional) ||
    search.min_rating !== defaultRating ||
    search.include_unrated;
  if (filtered) {
    options.push({
      label: "Clear filters",
      change: defaultSearch(search.area, defaultRating),
      icon: "reset",
    });
  }
  return options;
}

// ---------- Shortlist ----------

export function savedKey(result) {
  return `${result.name}|${result.place}`;
}

export function mapsUrl(name, place) {
  const query = `${name}, ${place}, Bangalore`;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

/**
 * One-tap ways to widen a search that found nothing: drop the dish or cuisine, any budget, a
 * lower rating, new places, or a neighbouring area with the same name (another Koramangala
 * block). The server already loosens the rating and budget a little before giving up.
 */
export function loosenOptions(search, areas = []) {
  const options = [];
  if (search.dishes.length) {
    const label = search.dishes.length === 1 ? `Without ${search.dishes[0]}` : "Any dish";
    options.push({ label, change: { dishes: [] }, icon: "utensils" });
  }
  if (search.cuisines.length) {
    options.push({ label: "Any cuisine", change: { cuisines: [] }, icon: "bowl" });
  }
  if (search.budget !== "any") {
    options.push({ label: "Any budget", change: { budget: "any" }, icon: "wallet" });
  }
  if (search.min_rating > 3) {
    const lower = Math.max(0, Math.round((search.min_rating - 1) * 10) / 10);
    options.push({ label: `Rated ${lower.toFixed(1)}+`, change: { min_rating: lower }, icon: "star" });
  }
  if (!search.include_unrated) {
    options.push({ label: "Include new places", change: { include_unrated: true }, icon: "sparkle" });
  }
  const first = search.area.split(/\s+/)[0];
  const sibling = areas.find((a) => a !== search.area && a.split(/\s+/)[0] === first);
  if (sibling) options.push({ label: `Try ${sibling}`, change: { area: sibling }, icon: "pin" });
  return options;
}
